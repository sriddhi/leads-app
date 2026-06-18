"""CLI for the retention cleanup job. Usage (from backend/):

    python scripts/cleanup_old_cases.py [--days 365]

Idempotent; safe to schedule (cron/worker) in production. Uses the app's async engine.
"""

import argparse
import asyncio
import logging
import sys

sys.path.insert(0, ".")

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.jobs.cleanup import purge_old_cases  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")


async def main(days: int) -> None:
    async with AsyncSessionLocal() as session:
        count = await purge_old_cases(session, older_than_days=days)
    print(f"Purged {count} case(s) older than {days} days.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Purge leads older than N days.")
    parser.add_argument("--days", type=int, default=365)
    args = parser.parse_args()
    asyncio.run(main(args.days))
