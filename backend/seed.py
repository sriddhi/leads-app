"""
seed.py — Bootstrap the initial users, settings, and ONE end-to-end "happy case" so the app is
immediately demonstrable on init: a test prospect whose lead was created → assigned to an
attorney → reached out, with a full audit trail + state timeline.

Usage (from backend/):  python seed.py
Idempotent: skips anything that already exists. The same baseline is reused by the load recipe's
clean-state teardown, so there is a single source of truth.
"""

import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import AsyncSessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.audit import AuditEvent  # noqa: E402
from app.models.lead import Lead  # noqa: E402
from app.models.settings import AppSettings  # noqa: E402
from app.models.timeline import LeadStatePeriod  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import identity  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# (email, password, first_name, last_name, role, max_open_cases)
SEED_USERS: list[tuple[str, str, str, str, str, int]] = [
    ("admin@company.com", "admin123", "Ada", "Admin", "ADMIN", 0),
    ("attorney@company.com", "attorney123", "Alex", "Attorney", "ATTORNEY", 20),
    ("attorney2@company.com", "attorney123", "Blair", "Barrister", "ATTORNEY", 20),
    ("attorney3@company.com", "attorney123", "Casey", "Counsel", "ATTORNEY", 20),
]

# One test prospect email used for the happy-path case.
TEST_PROSPECT_EMAIL = "prospect@example.com"
HAPPY_LEAD_NUMBER = "LEAD-000001"


async def seed_baseline(session) -> None:
    """Create users + settings + one fully-worked happy case (idempotent)."""
    for email, password, first, last, role, cap in SEED_USERS:
        existing = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing is not None:
            continue
        session.add(User(
            email=email, hashed_password=hash_password(password),
            first_name=first, last_name=last, full_name=f"{first} {last}",
            is_active=True, role=role, max_open_cases=cap,
        ))
        logger.info("Created %s: %s / %s (%s %s)", role, email, password, first, last)
    await session.flush()

    settings_row = (await session.execute(select(AppSettings).where(AppSettings.id == 1))).scalar_one_or_none()
    if settings_row is None:
        session.add(AppSettings(id=1, auto_assign_enabled=True))
        logger.info("Created AppSettings row (auto_assign_enabled=true).")

    await _happy_case(session)
    await session.commit()
    logger.info("Seed complete.")


async def _happy_case(session) -> None:
    """A test prospect, created → assigned → reached out, with audit + timeline (idempotent)."""
    existing = (await session.execute(
        select(Lead).where(Lead.lead_number == HAPPY_LEAD_NUMBER)
    )).scalar_one_or_none()
    if existing is not None:
        return
    attorney = (await session.execute(
        select(User).where(User.email == "attorney@company.com")
    )).scalar_one_or_none()
    if attorney is None:
        return

    now = datetime.now(timezone.utc)
    t_created = now - timedelta(minutes=30)
    t_assigned = now - timedelta(minutes=25)
    t_reached = now - timedelta(minutes=5)

    lead = Lead(
        first_name="Riya", last_name="Sharma", email=TEST_PROSPECT_EMAIL,
        normalized_email=identity.normalize_email(TEST_PROSPECT_EMAIL),
        phone="(415) 555-0100", normalized_phone=identity.normalize_phone("(415) 555-0100"),
        message="Looking for help with an O-1 visa.",
        resume_filename="sample.pdf", resume_original_filename="riya_resume.pdf",
        status="REACHED_OUT", lead_number=HAPPY_LEAD_NUMBER, assignee_id=attorney.id,
        version=3, created_at=t_created, updated_at=t_reached,
    )
    session.add(lead)
    await session.flush()

    # full timeline: QUEUED -> ASSIGNED -> REACHED_OUT (last one open)
    session.add(LeadStatePeriod(lead_id=lead.id, state="QUEUED", assignee_id=None,
                                entered_at=t_created, exited_at=t_assigned,
                                duration_seconds=int((t_assigned - t_created).total_seconds())))
    session.add(LeadStatePeriod(lead_id=lead.id, state="ASSIGNED", assignee_id=attorney.id,
                                entered_at=t_assigned, exited_at=t_reached,
                                duration_seconds=int((t_reached - t_assigned).total_seconds())))
    session.add(LeadStatePeriod(lead_id=lead.id, state="REACHED_OUT", assignee_id=attorney.id,
                                entered_at=t_reached, exited_at=None))
    # audit trail
    for kind, action, ts, after in [
        ("PUBLIC", "LEAD_CREATED", t_created, {"lead_number": HAPPY_LEAD_NUMBER, "status": "PENDING"}),
        ("ATTORNEY", "SELF_ASSIGNED", t_assigned, {"assignee_id": str(attorney.id)}),
        ("ATTORNEY", "MARKED_REACHED_OUT", t_reached, {"status": "REACHED_OUT"}),
    ]:
        session.add(AuditEvent(lead_id=lead.id, actor_id=attorney.id if kind == "ATTORNEY" else None,
                               actor_kind=kind, action=action, after=after, created_at=ts))
    logger.info("Created happy-path case %s for %s (assigned to %s)",
                HAPPY_LEAD_NUMBER, TEST_PROSPECT_EMAIL, attorney.email)


async def seed() -> None:
    logger.info("Connecting to database: %s", settings.DATABASE_URL.split("@")[-1])
    async with AsyncSessionLocal() as session:
        await seed_baseline(session)


if __name__ == "__main__":
    asyncio.run(seed())
