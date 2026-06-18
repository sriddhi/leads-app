"""Tests for the new features: phone field, case-history matching/window, retention cleanup.

History-window and cleanup need leads with a PAST created_at, which the API never produces, so
those rows are inserted directly via the DB.
"""

import io
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal, engine
from app.jobs.cleanup import purge_old_cases
from app.main import app
from app.models.audit import AuditEvent
from app.models.lead import Lead
from app.services import identity, ratelimit

pytestmark = pytest.mark.asyncio
BASE = "http://test/api/v1"


@pytest.fixture(autouse=True)
async def _fresh_state():
    ratelimit.reset()
    await engine.dispose()
    yield
    await engine.dispose()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _resume() -> dict:
    return {"resume": ("cv.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")}


def _uniq(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:8]}@example.com"


async def _auth(c, email="attorney@company.com", pw="attorney123") -> dict:
    r = await c.post(f"{BASE}/auth/login", data={"username": email, "password": pw})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _submit(c, *, first="A", last="B", email=None, phone=None):
    data = {"first_name": first, "last_name": last, "email": email or _uniq("x")}
    if phone is not None:
        data["phone"] = phone
    return await c.post(f"{BASE}/leads", data=data, files=_resume())


async def _by_number(c, headers, ln) -> dict:
    r = await c.get(f"{BASE}/leads/by-number/{ln}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def _insert_backdated(*, first, last, email, phone, days_ago, status="REACHED_OUT") -> str:
    """Insert a lead with a past created_at; returns its lead_number."""
    ln = f"HIST-{uuid.uuid4().hex[:8]}"
    ts = datetime.now(timezone.utc) - timedelta(days=days_ago)
    async with AsyncSessionLocal() as s:
        s.add(Lead(
            first_name=first, last_name=last, email=email,
            normalized_email=identity.normalize_email(email),
            phone=phone, normalized_phone=identity.normalize_phone(phone),
            resume_filename="hist.pdf", resume_original_filename="hist.pdf",
            status=status, lead_number=ln, created_at=ts, updated_at=ts,
        ))
        await s.commit()
    return ln


# --- phone ------------------------------------------------------------------------------------

async def test_phone_stored_normalized_and_not_in_public_receipt():
    async with _client() as c:
        admin = await _auth(c, "admin@company.com", "admin123")
        r = await _submit(c, first="Phon", email=_uniq("ph"), phone="(415) 555-0199")
        assert r.status_code == 201
        assert "phone" not in r.json()  # public receipt stays minimal
        lead = await _by_number(c, admin, r.json()["lead_number"])
        assert lead["phone"] == "(415) 555-0199"

    # normalized to digits in the DB
    async with AsyncSessionLocal() as s:
        row = (await s.execute(select(Lead).where(Lead.lead_number == lead["lead_number"]))).scalar_one()
        assert row.normalized_phone == "4155550199"


# --- case history -----------------------------------------------------------------------------

async def test_history_phone_or_email_default_and_window_and_dims():
    async with _client() as c:
        admin = await _auth(c, "admin@company.com", "admin123")
        # Unique per run so prior runs' backdated rows (shared DB) don't pollute matches.
        phone = "+1 " + str(uuid.uuid4().int)[:10]
        email = _uniq("fam")
        # current case
        cur_ln = (await _submit(c, first="Jane", last="Doe", email=email, phone=phone)).json()["lead_number"]
        cur = await _by_number(c, admin, cur_ln)

        # matches within 6 months
        await _insert_backdated(first="Jane", last="Roe", email=_uniq("other"), phone=phone, days_ago=60)   # phone match
        await _insert_backdated(first="John", last="Smith", email=email, phone="9999999999", days_ago=90)   # email match (family)
        # outside the 6-month window (should be excluded)
        await _insert_backdated(first="Old", last="Phone", email=_uniq("old"), phone=phone, days_ago=210)

        # default dims = phone OR email
        h = (await c.get(f"{BASE}/leads/{cur['id']}/history", headers=admin)).json()
        assert len(h) == 2, h
        assert all(cur["id"] != row["id"] for row in h)  # self excluded
        assert any("phone" in row["matched_on"] for row in h)
        assert any("email" in row["matched_on"] for row in h)

        # dims = email only → just the family (email) match
        h_email = (await c.get(f"{BASE}/leads/{cur['id']}/history?dims=email", headers=admin)).json()
        assert all("email" in row["matched_on"] for row in h_email)
        assert len(h_email) == 1


async def test_history_requires_auth():
    async with _client() as c:
        admin = await _auth(c, "admin@company.com", "admin123")
        ln = (await _submit(c, email=_uniq("h"))).json()["lead_number"]
        lead = await _by_number(c, admin, ln)
        assert (await c.get(f"{BASE}/leads/{lead['id']}/history")).status_code == 401


# --- retention cleanup ------------------------------------------------------------------------

async def test_cleanup_purges_over_one_year_keeps_recent():
    old_ln = await _insert_backdated(first="Ancient", last="Case", email=_uniq("old"),
                                     phone="111", days_ago=400)   # > 1 year → purge
    new_ln = await _insert_backdated(first="Recent", last="Case", email=_uniq("new"),
                                     phone="222", days_ago=60)    # < 1 year → keep

    async with AsyncSessionLocal() as s:
        purged = await purge_old_cases(s, older_than_days=365)
    assert purged >= 1

    async with AsyncSessionLocal() as s:
        gone = (await s.execute(select(Lead).where(Lead.lead_number == old_ln))).scalar_one_or_none()
        kept = (await s.execute(select(Lead).where(Lead.lead_number == new_ln))).scalar_one_or_none()
        purged_evt = (await s.execute(
            select(AuditEvent).where(AuditEvent.action == "CASE_PURGED")
        )).scalars().all()
    assert gone is None          # old case removed
    assert kept is not None      # recent case untouched
    assert len(purged_evt) >= 1  # PII-free purge recorded


async def test_next_lead_number_robust_to_gaps():
    """Regression: lead_number derives from MAX (not count), so a number far above `count`
    (e.g. a gap left by retention cleanup) does NOT cause a colliding number / 503. Relative to
    the DB's current max so it's safe in a shared DB, and fully self-cleaning."""
    from sqlalchemy import func

    from app.crud.leads import next_lead_number
    async with AsyncSessionLocal() as s:
        cur = (await s.execute(
            select(func.max(Lead.lead_number)).where(Lead.lead_number.like("LEAD-%"))
        )).scalar_one_or_none()
        base = int(cur.split("-")[-1]) if cur else 0
        gap = base + 500  # a high number with a big gap below it (count << gap)
        high = f"LEAD-{gap:06d}"
        s.add(Lead(first_name="Hi", last_name="Num", email=_uniq("num"),
                   normalized_email=identity.normalize_email(_uniq("num")),
                   resume_filename="r.pdf", resume_original_filename="r.pdf",
                   status="PENDING", lead_number=high))
        await s.commit()
    try:
        async with AsyncSessionLocal() as s:
            nxt = await next_lead_number(s)
        assert nxt == f"LEAD-{gap + 1:06d}", nxt  # max+1, not count+1
    finally:
        async with AsyncSessionLocal() as s:
            await s.execute(text("DELETE FROM leads WHERE lead_number = :n"), {"n": high})
            await s.commit()


async def test_cleanup_is_idempotent():
    async with AsyncSessionLocal() as s:
        await purge_old_cases(s, older_than_days=365)
    async with AsyncSessionLocal() as s:
        second = await purge_old_cases(s, older_than_days=365)
    assert second == 0  # nothing left to purge on the second pass
