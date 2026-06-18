"""Retention cleanup: purge cases older than a cutoff (default 1 year).

For each old lead we delete its state-periods and its PII-bearing audit rows (FK order matters),
delete the resume file, delete the lead, and write a single PII-free `CASE_PURGED` audit event
(lead_number + ts only) so the trail records the purge without retaining personal data.

Deletions are batched so a large purge never holds one giant transaction/lock. Idempotent.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.lead import Lead
from app.models.timeline import LeadStatePeriod
from app.services import audit, storage

logger = logging.getLogger(__name__)


async def purge_old_cases(
    db: AsyncSession,
    older_than_days: int = 365,
    batch_size: int = 200,
) -> int:
    """Delete leads with created_at < now - older_than_days. Returns the number purged."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    purged = 0

    while True:
        result = await db.execute(
            select(Lead).where(Lead.created_at < cutoff).limit(batch_size)
        )
        batch = list(result.scalars().all())
        if not batch:
            break

        for lead in batch:
            lead_number = lead.lead_number
            resume = lead.resume_filename
            # Children first (FK order): state-periods, then this lead's audit rows.
            await db.execute(
                delete(LeadStatePeriod).where(LeadStatePeriod.lead_id == lead.id)
            )
            await db.execute(delete(AuditEvent).where(AuditEvent.lead_id == lead.id))
            await db.delete(lead)
            await db.flush()
            # Resume file (best-effort; ignores missing).
            if resume:
                storage.delete_resume(resume)
            # PII-free purge record (lead is gone → lead_id None).
            await audit.record(
                db,
                lead_id=None,
                actor_id=None,
                actor_kind="SYSTEM",
                action="CASE_PURGED",
                after={"lead_number": lead_number, "purged_before": cutoff.isoformat()},
            )
            purged += 1

        await db.commit()

    logger.info("purge_old_cases: removed %d case(s) older than %s", purged, cutoff.isoformat())
    return purged
