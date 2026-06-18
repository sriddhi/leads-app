"""Reset + seed the DB to a known load-profile state.

SAFETY: refuses to wipe unless LOAD_TEST=1 AND (the DB name looks like a test/load DB OR
force=True). An untested rail is a liability, so selftest.py exercises this guard.
"""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.lead import Lead
from app.services import identity
from tests.load.profiles import Profile

STANDARD_USERS = [
    # (email, password, full_name, role, cap) — needed by the correctness pytest suite.
    ("admin@company.com", "admin123", "Default Admin", "ADMIN", 0),
    ("attorney@company.com", "attorney123", "Default Attorney", "ATTORNEY", 20),
    ("attorney2@company.com", "attorney123", "Attorney Two", "ATTORNEY", 20),
    ("attorney3@company.com", "attorney123", "Attorney Three", "ATTORNEY", 20),
]
LOAD_PASSWORD = "load1234"


class SafetyError(RuntimeError):
    pass


def _db_name() -> str:
    return settings.DATABASE_URL.rsplit("/", 1)[-1].split("?")[0]


def guard(force: bool = False) -> None:
    """Raise unless it's safe to TRUNCATE the target DB."""
    if os.environ.get("LOAD_TEST") != "1":
        raise SafetyError("refusing to reset: set LOAD_TEST=1 to confirm a load-test DB.")
    name = _db_name().lower()
    if not force and not ("test" in name or "load" in name):
        raise SafetyError(
            f"refusing to reset DB '{name}': name doesn't look like a test/load DB. "
            f"Use a dedicated DB or pass force=True."
        )


def load_attorney_email(i: int) -> str:
    return f"att{i}@load.test"


async def reset_and_seed(profile: Profile, *, force: bool = False) -> None:
    guard(force=force)
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as s:  # type: AsyncSession
        await s.execute(text(
            "TRUNCATE users, leads, lead_state_periods, audit_events, app_settings "
            "RESTART IDENTITY CASCADE"
        ))
        # users: standard (for pytest) + N load attorneys at the profile cap
        rows = []
        for email, pw, name, role, cap in STANDARD_USERS:
            rows.append((email, hash_password(pw), name, role, cap))
        for i in range(1, profile.attorneys + 1):
            rows.append((load_attorney_email(i), hash_password(LOAD_PASSWORD),
                         f"Load Attorney {i}", "ATTORNEY", profile.cap))
        for email, pwh, name, role, cap in rows:
            await s.execute(text(
                "INSERT INTO users (id, email, hashed_password, full_name, role, "
                "max_open_cases, is_active, created_at) VALUES "
                "(gen_random_uuid(), :e, :p, :n, :r, :c, true, now())"
            ), {"e": email, "p": pwh, "n": name, "r": role, "c": cap})
        # app settings (auto-assign off by default; harness toggles as needed)
        await s.execute(text(
            "INSERT INTO app_settings (id, auto_assign_enabled) VALUES (1, false)"
        ))
        await s.commit()

        # backdated historical cohorts: in-window (2mo), out-of-window (7mo), purge-eligible (13mo)
        await _backdated(s, "Hist", "Window2mo", "hist2mo@load.test", "5550002000", now - timedelta(days=60))
        await _backdated(s, "Hist", "Window7mo", "hist7mo@load.test", "5550007000", now - timedelta(days=210))
        await _backdated(s, "Hist", "Purge13mo", "hist13mo@load.test", "5550013000", now - timedelta(days=400))
        await s.commit()


async def restore_clean_state(*, force: bool = False) -> None:
    """Leave a clean, demo-ready baseline: no leads/periods/audit, no load attorneys — only the
    standard seeded users + default settings, and an empty upload dir. Called at the END of every
    run (even on failure) so a test never leaves test data behind."""
    guard(force=force)
    from seed import seed_baseline  # single source of truth for the demo baseline
    async with AsyncSessionLocal() as s:
        await s.execute(text(
            "TRUNCATE users, leads, lead_state_periods, audit_events, app_settings "
            "RESTART IDENTITY CASCADE"
        ))
        await s.commit()
        # standard users (with names) + settings + one end-to-end happy case
        await seed_baseline(s)
    # clear uploaded resume files left by the run
    updir = Path(settings.UPLOAD_DIR)
    if updir.is_dir():
        for f in updir.iterdir():
            if f.is_file() and f.name != ".gitkeep":
                f.unlink(missing_ok=True)


async def _backdated(s, first, last, email, phone, ts) -> None:
    s.add(Lead(
        first_name=first, last_name=last, email=email,
        normalized_email=identity.normalize_email(email),
        phone=phone, normalized_phone=identity.normalize_phone(phone),
        resume_filename="seed.pdf", resume_original_filename="seed.pdf",
        status="REACHED_OUT", lead_number=f"SEED-{abs(hash((email, ts))) % 10**8:08d}",
        created_at=ts, updated_at=ts,
    ))
