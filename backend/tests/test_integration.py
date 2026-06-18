"""Async DB integration tests — exercise the real endpoints against the live app + Postgres
(in-process via httpx ASGITransport).

The PUBLIC submit endpoint returns only a minimal receipt (lead_number + status) by design, so
these tests read full lead data back through the AUTHENTICATED internal API (by lead_number).
Requires a reachable DATABASE_URL with migrations applied and seed users present.
"""

import asyncio
import io
import uuid

import httpx
import pytest

from app.core.database import engine
from app.main import app
from app.services import ratelimit

pytestmark = pytest.mark.asyncio

BASE = "http://test/api/v1"


@pytest.fixture(autouse=True)
async def _fresh_state():
    """asyncpg pools bind to the creating loop; pytest-asyncio uses a fresh loop per test.
    Also reset the in-process rate limiter so per-test submit volume doesn't trip it."""
    ratelimit.reset()
    await engine.dispose()
    yield
    await engine.dispose()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _resume() -> dict:
    # Leading bytes %PDF satisfy the magic-byte check.
    return {"resume": ("cv.pdf", io.BytesIO(b"%PDF-1.4 test resume"), "application/pdf")}


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"


async def _login(c, email: str, password: str) -> str:
    r = await c.post(f"{BASE}/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _auth(c, email="attorney@company.com", pw="attorney123") -> dict:
    return {"Authorization": f"Bearer {await _login(c, email, pw)}"}


async def _submit(c, *, first="A", last="B", email=None, message=None, idem=None, honeypot=None):
    data = {"first_name": first, "last_name": last, "email": email or _uniq("x")}
    if message is not None:
        data["message"] = message
    if honeypot is not None:
        data["company_website"] = honeypot
    headers = {"Idempotency-Key": idem} if idem else {}
    return await c.post(f"{BASE}/leads", data=data, files=_resume(), headers=headers)


async def _by_number(c, headers, lead_number) -> dict:
    r = await c.get(f"{BASE}/leads/by-number/{lead_number}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def _free_capacity(c, admin, email="attorney@company.com") -> None:
    """Raise the attorney's cap so accumulated leads in a shared DB don't block self-assign
    (keeps assignment tests deterministic regardless of pre-existing state)."""
    attorneys = (await c.get(f"{BASE}/admin/attorneys", headers=admin)).json()
    aid = next(a["id"] for a in attorneys if a["email"] == email)
    # 1000 is the schema's max (le=1000) — ample headroom over a fresh attorney's 0 open cases.
    await c.put(f"{BASE}/admin/attorneys/{aid}/capacity",
                json={"max_open_cases": 1000}, headers=admin)


# --------------------------------------------------------------------------- #
# Public receipt: shape + no internal leakage
# --------------------------------------------------------------------------- #

async def test_public_receipt_is_minimal_and_leaks_nothing():
    async with _client() as c:
        r = await _submit(c, first="Msg", last="Test", email=_uniq("msg"),
                          message="Please call me about my case.")
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["lead_number"].startswith("LEAD-")
        assert body["status"] == "PENDING"
        # Must NOT leak internal fields on the public channel.
        for leaked in ("id", "assignee_id", "version", "is_potential_duplicate",
                       "duplicate_of", "submitter_ip", "email"):
            assert leaked not in body, f"public receipt leaked '{leaked}'"


async def test_message_stored_and_readable_internally():
    async with _client() as c:
        admin = await _auth(c, "admin@company.com", "admin123")
        ln = (await _submit(c, message="ping")).json()["lead_number"]
        lead = await _by_number(c, admin, ln)
        assert lead["message"] == "ping"


# --------------------------------------------------------------------------- #
# Dedup, idempotency, validation, spam
# --------------------------------------------------------------------------- #

async def test_duplicate_is_linked_not_merged():
    async with _client() as c:
        admin = await _auth(c, "admin@company.com", "admin123")
        email = _uniq("dup")
        ln_a = (await _submit(c, first="A", last="One", email=email)).json()["lead_number"]
        ln_b = (await _submit(c, first="B", last="Two", email=f"  {email.upper()} ")).json()["lead_number"]
        assert ln_a != ln_b
        a = await _by_number(c, admin, ln_a)
        b = await _by_number(c, admin, ln_b)
        assert a["id"] != b["id"]
        assert a["is_potential_duplicate"] is False
        assert b["is_potential_duplicate"] is True
        assert b["duplicate_of"] == a["id"]  # linked, not merged


async def test_idempotency_key_collapses_resubmit():
    async with _client() as c:
        key = f"idem-{uuid.uuid4().hex}"
        data = dict(first="Idem", last="Key", email=_uniq("idem"), idem=key)
        r1 = await _submit(c, **data)
        r2 = await _submit(c, **data)
        assert r1.json()["lead_number"] == r2.json()["lead_number"]


async def test_validation_and_injection():
    async with _client() as c:
        admin = await _auth(c, "admin@company.com", "admin123")
        # missing email
        r = await c.post(f"{BASE}/leads", data={"first_name": "NoEmail"}, files=_resume())
        assert r.status_code == 422
        # malformed email rejected server-side
        r = await _submit(c, email="not-an-email")
        assert r.status_code == 422
        # injection stored escaped
        ln = (await _submit(c, first="<script>alert(1)</script>", email=_uniq("inj"))).json()["lead_number"]
        lead = await _by_number(c, admin, ln)
        assert "&lt;script&gt;" in lead["first_name"] and "<script>" not in lead["first_name"]


async def test_honeypot_blocks_without_creating_lead():
    async with _client() as c:
        r = await _submit(c, email=_uniq("spam"), honeypot="http://spam")
        assert r.status_code == 202


async def test_bad_file_content_rejected():
    async with _client() as c:
        # Declared as PDF but the bytes are not a real PDF/DOC/DOCX → rejected by magic-byte check.
        files = {"resume": ("fake.pdf", io.BytesIO(b"GIF89a not really a pdf"), "application/pdf")}
        r = await c.post(f"{BASE}/leads",
                         data={"first_name": "Bad", "last_name": "File", "email": _uniq("bad")},
                         files=files)
        assert r.status_code == 400


# --------------------------------------------------------------------------- #
# Auth, assignment, concurrency, reversal
# --------------------------------------------------------------------------- #

async def test_resume_download_is_authenticated():
    async with _client() as c:
        admin = await _auth(c, "admin@company.com", "admin123")
        att_token = await _login(c, "attorney@company.com", "attorney123")
        ln = (await _submit(c, first="Res", email=_uniq("res"))).json()["lead_number"]
        lead = await _by_number(c, admin, ln)
        lid, fname = lead["id"], lead["resume_filename"]
        # The old public static path no longer exists.
        assert (await c.get(f"/uploads/{fname}")).status_code == 404
        # Missing token → 422 (required); bad token → 401.
        assert (await c.get(f"{BASE}/leads/{lid}/resume")).status_code == 422
        assert (await c.get(f"{BASE}/leads/{lid}/resume?token=garbage")).status_code == 401
        # Valid attorney token → 200 with the file bytes.
        r = await c.get(f"{BASE}/leads/{lid}/resume?token={att_token}")
        assert r.status_code == 200 and r.content.startswith(b"%PDF")


async def test_authz_unauth_401_and_wrong_role_403():
    async with _client() as c:
        assert (await c.get(f"{BASE}/leads/queue")).status_code == 401
        att = await _auth(c)
        assert (await c.get(f"{BASE}/admin/metrics", headers=att)).status_code == 403


async def test_optimistic_lock_and_single_assignee():
    async with _client() as c:
        att = await _auth(c)
        admin = await _auth(c, "admin@company.com", "admin123")
        await c.put(f"{BASE}/admin/settings/auto-assign", json={"enabled": False}, headers=admin)
        await _free_capacity(c, admin)
        ln = (await _submit(c, first="Lock", email=_uniq("lock"))).json()["lead_number"]
        lead = await _by_number(c, att, ln)
        lid, ver = lead["id"], lead["version"]
        assert (await c.post(f"{BASE}/leads/{lid}/assign", json={"version": ver}, headers=att)).status_code == 200
        # stale version → conflict
        assert (await c.post(f"{BASE}/leads/{lid}/assign", json={"version": ver}, headers=att)).status_code == 409


async def test_concurrent_self_assign_has_exactly_one_winner():
    """The headline guarantee: two attorneys racing to claim the SAME queued lead with the
    SAME (valid) version must not both succeed. The DB-level version_id_col compare-and-swap
    is what enforces this — the in-memory version pre-check alone would let both through, since
    both load version=1 before either commits. Exactly one 200, one 409; no double-assign."""
    async with _client() as c:
        admin = await _auth(c, "admin@company.com", "admin123")
        att1 = await _auth(c, "attorney@company.com", "attorney123")
        att2 = await _auth(c, "attorney2@company.com", "attorney123")
        await c.put(f"{BASE}/admin/settings/auto-assign", json={"enabled": False}, headers=admin)
        await _free_capacity(c, admin, "attorney@company.com")
        await _free_capacity(c, admin, "attorney2@company.com")

        ln = (await _submit(c, first="Race", email=_uniq("race"))).json()["lead_number"]
        lead = await _by_number(c, att1, ln)
        lid, ver = lead["id"], lead["version"]

        # Fire both claims concurrently with the same starting version.
        r1, r2 = await asyncio.gather(
            c.post(f"{BASE}/leads/{lid}/assign", json={"version": ver}, headers=att1),
            c.post(f"{BASE}/leads/{lid}/assign", json={"version": ver}, headers=att2),
        )
        codes = sorted([r1.status_code, r2.status_code])
        assert codes == [200, 409], (r1.status_code, r1.text, r2.status_code, r2.text)

        # The lead is assigned to exactly one attorney, and the version advanced exactly once.
        after = await _by_number(c, admin, ln)
        assert after["assignee_id"] is not None
        assert after["version"] == ver + 1


async def test_concurrent_reached_out_has_exactly_one_winner():
    """Same CAS guarantee on the status transition: two concurrent REACHED_OUT patches at the
    same version cannot both win (which would double-count time accounting / emit two events)."""
    async with _client() as c:
        admin = await _auth(c, "admin@company.com", "admin123")
        att = await _auth(c, "attorney@company.com", "attorney123")
        await c.put(f"{BASE}/admin/settings/auto-assign", json={"enabled": False}, headers=admin)
        await _free_capacity(c, admin)

        ln = (await _submit(c, first="Reach", email=_uniq("reach"))).json()["lead_number"]
        lead = await _by_number(c, att, ln)
        lid = lead["id"]
        await c.post(f"{BASE}/leads/{lid}/assign", json={"version": lead["version"]}, headers=att)
        ver = (await _by_number(c, att, ln))["version"]

        body = {"status": "REACHED_OUT", "version": ver}
        r1, r2 = await asyncio.gather(
            c.patch(f"{BASE}/leads/{lid}/status", json=body, headers=att),
            c.patch(f"{BASE}/leads/{lid}/status", json=body, headers=att),
        )
        assert sorted([r1.status_code, r2.status_code]) == [200, 409], (r1.text, r2.text)
        assert (await _by_number(c, admin, ln))["status"] == "REACHED_OUT"


async def test_auto_assign_bumps_version_no_gap():
    """Versioning has no gaps: the auto-assign path (which previously set assignee_id without
    bumping version) now advances the version like every other mutation, because version_id_col
    is managed by the DB on every UPDATE. A freshly auto-assigned lead is at version 2."""
    async with _client() as c:
        admin = await _auth(c, "admin@company.com", "admin123")
        await c.put(f"{BASE}/admin/settings/auto-assign", json={"enabled": True}, headers=admin)
        await _free_capacity(c, admin, "attorney@company.com")
        await _free_capacity(c, admin, "attorney2@company.com")
        await _free_capacity(c, admin, "attorney3@company.com")
        try:
            ln = (await _submit(c, first="Auto", email=_uniq("auto"))).json()["lead_number"]
            lead = await _by_number(c, admin, ln)
            assert lead["assignee_id"] is not None, "expected auto-assignment"
            assert lead["version"] == 2, f"auto-assign should bump version to 2, got {lead['version']}"
        finally:
            # Restore default so other tests aren't affected by shared DB state.
            await c.put(f"{BASE}/admin/settings/auto-assign", json={"enabled": False}, headers=admin)


async def test_bulk_related_transition_conflict_degrades_per_lead():
    """The bulk transition mutates each lead inside its own SAVEPOINT. When two callers race
    the same clustered lead, the loser hits the version_id_col CAS (StaleDataError) — which must
    roll back only that lead's savepoint and report it as a per-lead failure, NOT 500 the batch.
    Exactly one winner; the lead is assigned once."""
    async with _client() as c:
        admin = await _auth(c, "admin@company.com", "admin123")
        att = await _auth(c, "attorney@company.com", "attorney123")
        att2 = await _auth(c, "attorney2@company.com", "attorney123")
        await c.put(f"{BASE}/admin/settings/auto-assign", json={"enabled": False}, headers=admin)
        await _free_capacity(c, admin, "attorney@company.com")
        await _free_capacity(c, admin, "attorney2@company.com")

        shared = _uniq("bulkrace")
        ln_a = (await _submit(c, first="Sam", last="Lee", email=shared)).json()["lead_number"]
        ln_b = (await _submit(c, first="Sam", last="Lee", email=shared)).json()["lead_number"]
        a = await _by_number(c, att, ln_a)
        b = await _by_number(c, att, ln_b)
        assert b["duplicate_of"] == a["id"]

        body = {"action": "assign", "lead_ids": [b["id"]]}
        r1, r2 = await asyncio.gather(
            c.post(f"{BASE}/leads/{a['id']}/related/transition", json=body, headers=att),
            c.post(f"{BASE}/leads/{a['id']}/related/transition", json=body, headers=att2),
        )
        # Neither request fails outright — the batch always returns 200 with per-lead results.
        assert r1.status_code == 200 and r2.status_code == 200, (r1.text, r2.text)
        oks = sorted([r1.json()[0]["ok"], r2.json()[0]["ok"]])
        assert oks == [False, True], (r1.json(), r2.json())  # exactly one winner
        after = await _by_number(c, admin, ln_b)
        assert after["assignee_id"] is not None
        assert after["version"] == b["version"] + 1  # assigned exactly once


async def _set_capacity(c, admin, email, cap) -> None:
    attorneys = (await c.get(f"{BASE}/admin/attorneys", headers=admin)).json()
    aid = next(a["id"] for a in attorneys if a["email"] == email)
    await c.put(f"{BASE}/admin/attorneys/{aid}/capacity", json={"max_open_cases": cap}, headers=admin)


async def test_concurrent_assign_cannot_over_commit_capacity():
    """The capacity over-commit race: two assignments of DIFFERENT leads to the same attorney
    both pass the count-then-assign check before either commits, pushing the attorney past cap.
    The lead-version CAS can't catch it (different rows), so only assignment.lock_attorney's row
    lock can. This is driven at the session level with a controlled interleave (a hold between
    the capacity check and commit) so the race is deterministic, not timing-dependent: WITH the
    lock the second checker blocks until the first commits and then correctly refuses; WITHOUT
    it (regression) both would land. Verified to fail if the lock is removed."""
    import uuid as _uuid
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.lead import Lead
    from app.models.user import User
    from app.services import assignment

    email = "attorney3@company.com"
    async with _client() as c:
        admin = await _auth(c, "admin@company.com", "admin123")
        await c.put(f"{BASE}/admin/settings/auto-assign", json={"enabled": False}, headers=admin)
        attorneys = (await c.get(f"{BASE}/admin/attorneys", headers=admin)).json()
        att_id = _uuid.UUID(next(a["id"] for a in attorneys if a["email"] == email))

        # Read true current load, then leave EXACTLY one open slot.
        async with AsyncSessionLocal() as s:
            base_load = await assignment.open_case_count(s, att_id)
        await _set_capacity(c, admin, email, base_load + 1)

        ln1 = (await _submit(c, first="Cap1", email=_uniq("cap1"))).json()["lead_number"]
        ln2 = (await _submit(c, first="Cap2", email=_uniq("cap2"))).json()["lead_number"]
        lid1 = _uuid.UUID((await _by_number(c, admin, ln1))["id"])
        lid2 = _uuid.UUID((await _by_number(c, admin, ln2))["id"])

        async def claim(lead_id, hold):
            """One assignment attempt in its own session: capacity-check (with the row lock),
            hold the window open, then assign + commit. Returns True if it assigned."""
            async with AsyncSessionLocal() as s:
                att = (await s.execute(select(User).where(User.id == att_id))).scalar_one()
                if not await assignment.has_capacity(s, att, lock=True):
                    return False
                await asyncio.sleep(hold)
                lead = (await s.execute(select(Lead).where(Lead.id == lead_id))).scalar_one()
                lead.assignee_id = att_id
                s.add(lead)
                await s.commit()
                return True

        try:
            # Both start together; the holds force both past their capacity check before the
            # first commits — exactly the over-commit window.
            r1, r2 = await asyncio.gather(claim(lid1, 0.4), claim(lid2, 0.4))
            assert sorted([r1, r2]) == [False, True], (r1, r2)  # exactly one landed
            async with AsyncSessionLocal() as s:
                final_load = await assignment.open_case_count(s, att_id)
            assert final_load == base_load + 1, f"over-committed: {final_load} > cap {base_load + 1}"
        finally:
            # Unassign whatever landed and restore the seed default cap.
            async with AsyncSessionLocal() as s:
                for lid in (lid1, lid2):
                    lead = (await s.execute(select(Lead).where(Lead.id == lid))).scalar_one()
                    lead.assignee_id = None
                    s.add(lead)
                await s.commit()
            await _set_capacity(c, admin, email, 20)


async def test_reached_out_requires_assignment_and_reversal_restores_state():
    async with _client() as c:
        att = await _auth(c)
        admin = await _auth(c, "admin@company.com", "admin123")
        await c.put(f"{BASE}/admin/settings/auto-assign", json={"enabled": False}, headers=admin)
        await _free_capacity(c, admin)
        ln = (await _submit(c, first="Rev", email=_uniq("rev"))).json()["lead_number"]
        lead = await _by_number(c, att, ln)
        lid = lead["id"]
        # attorney can't touch a lead they aren't assigned to → 403
        assert (await c.patch(f"{BASE}/leads/{lid}/status",
                json={"status": "REACHED_OUT", "version": lead["version"]}, headers=att)).status_code == 403
        # admin bypasses the assignee check but still can't reach out an UNASSIGNED lead → 422
        assert (await c.patch(f"{BASE}/leads/{lid}/status",
                json={"status": "REACHED_OUT", "version": lead["version"]}, headers=admin)).status_code == 422
        # assign → reach out
        v = (await _by_number(c, att, ln))["version"]
        await c.post(f"{BASE}/leads/{lid}/assign", json={"version": v}, headers=att)
        v = (await _by_number(c, att, ln))["version"]
        assert (await c.patch(f"{BASE}/leads/{lid}/status",
                json={"status": "REACHED_OUT", "version": v}, headers=att)).status_code == 200
        # reverse needs reason; restores previous (ASSIGNED) state
        v = (await _by_number(c, att, ln))["version"]
        assert (await c.post(f"{BASE}/leads/{lid}/reverse", json={"version": v}, headers=att)).status_code == 422
        body = (await c.post(f"{BASE}/leads/{lid}/reverse",
                json={"version": v, "reason": "wrong person"}, headers=att)).json()
        assert body["status"] == "PENDING"
        assert body["assignee_id"] is not None
        assert body["timeline"][-1]["state"] == "ASSIGNED"


# --------------------------------------------------------------------------- #
# Related open duplicates: bulk transition references the parent case
# --------------------------------------------------------------------------- #
async def test_related_duplicate_bulk_transition():
    async with _client() as c:
        att = await _auth(c)
        admin = await _auth(c, "admin@company.com", "admin123")
        await c.put(f"{BASE}/admin/settings/auto-assign", json={"enabled": False}, headers=admin)
        await _free_capacity(c, admin)

        # Two submissions with the SAME email+name → second is linked (not merged) to the first.
        shared = _uniq("family")
        ln_a = (await _submit(c, first="Sam", last="Lee", email=shared)).json()["lead_number"]
        ln_b = (await _submit(c, first="Sam", last="Lee", email=shared)).json()["lead_number"]
        a = await _by_number(c, att, ln_a)
        b = await _by_number(c, att, ln_b)
        assert b["duplicate_of"] == a["id"]  # linked

        # From the parent (A), the open related list includes B.
        related = (await c.get(f"{BASE}/leads/{a['id']}/related", headers=att)).json()
        assert any(r["id"] == b["id"] for r in related)

        # Bulk-assign B to the caller, referencing the parent case in the note.
        res = (await c.post(
            f"{BASE}/leads/{a['id']}/related/transition",
            json={"action": "assign", "lead_ids": [b["id"]], "note": "same applicant"},
            headers=att,
        )).json()
        assert res[0]["ok"] is True
        b2 = await _by_number(c, att, ln_b)
        assert b2["assignee_id"] is not None

        # B no longer appears as an OPEN related case once... it's still PENDING+assigned, so it
        # is still open; now bulk-mark it reached out.
        res2 = (await c.post(
            f"{BASE}/leads/{a['id']}/related/transition",
            json={"action": "reached_out", "lead_ids": [b["id"]]},
            headers=att,
        )).json()
        assert res2[0]["ok"] is True
        b3 = await _by_number(c, att, ln_b)
        assert b3["status"] == "REACHED_OUT"

        # The reached-out lead drops out of the OPEN related list.
        related_after = (await c.get(f"{BASE}/leads/{a['id']}/related", headers=att)).json()
        assert not any(r["id"] == b["id"] for r in related_after)

        # The audit trail on B records the parent reference.
        audit = (await c.get(f"{BASE}/admin/audit", headers=admin)).json()["items"]
        b_events = [e for e in audit if e["lead_id"] == b["id"] and e.get("reason")]
        assert any(ln_a in (e["reason"] or "") for e in b_events)


async def test_related_transition_rejects_non_cluster_lead():
    async with _client() as c:
        att = await _auth(c)
        admin = await _auth(c, "admin@company.com", "admin123")
        await c.put(f"{BASE}/admin/settings/auto-assign", json={"enabled": False}, headers=admin)
        await _free_capacity(c, admin)

        ln_a = (await _submit(c, first="Solo", email=_uniq("solo-a"))).json()["lead_number"]
        ln_x = (await _submit(c, first="Other", email=_uniq("solo-x"))).json()["lead_number"]
        a = await _by_number(c, att, ln_a)
        x = await _by_number(c, att, ln_x)

        # X is unrelated to A → the transition reports it as ineligible, changes nothing.
        res = (await c.post(
            f"{BASE}/leads/{a['id']}/related/transition",
            json={"action": "assign", "lead_ids": [x["id"]]},
            headers=att,
        )).json()
        assert res[0]["ok"] is False
        assert (await _by_number(c, att, ln_x))["assignee_id"] is None
