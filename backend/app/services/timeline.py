import uuid
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead
from app.models.timeline import LeadStatePeriod
from app.models.user import User


def compute_duration_seconds(entered_at: datetime, exited_at: datetime) -> int:
    """Pure helper: whole seconds between two timestamps (never negative)."""
    delta = (exited_at - entered_at).total_seconds()
    return max(0, int(delta))


def aggregate_attorney_time(
    periods: Iterable[dict],
    now: datetime,
) -> dict[uuid.UUID, dict]:
    """
    Pure aggregation helper (no DB) so the time report is unit-testable.

    Each period dict has keys: assignee_id, state, entered_at, exited_at,
    duration_seconds. Returns a mapping attorney_id -> aggregate dict with:
      total_holding_seconds, cases_handled, avg_time_to_reached_out_seconds,
      current_open_load, oldest_open_age_seconds.
    """
    acc: dict[uuid.UUID, dict] = {}

    def bucket(attorney_id: uuid.UUID) -> dict:
        if attorney_id not in acc:
            acc[attorney_id] = {
                "total_holding_seconds": 0,
                "_assigned_lead_ids": set(),
                "_time_to_reached_out": [],
                "current_open_load": 0,
                "oldest_open_age_seconds": 0,
            }
        return acc[attorney_id]

    for p in periods:
        attorney_id = p.get("assignee_id")
        if attorney_id is None:
            continue
        b = bucket(attorney_id)
        state = p["state"]
        entered_at = p["entered_at"]
        exited_at = p.get("exited_at")
        duration = p.get("duration_seconds")

        if state == "ASSIGNED":
            if exited_at is None:
                # Open assigned period: contributes live holding time + load.
                live = compute_duration_seconds(entered_at, now)
                b["total_holding_seconds"] += live
                b["current_open_load"] += 1
                b["oldest_open_age_seconds"] = max(b["oldest_open_age_seconds"], live)
            else:
                seconds = (
                    duration
                    if duration is not None
                    else compute_duration_seconds(entered_at, exited_at)
                )
                b["total_holding_seconds"] += seconds
                # A closed ASSIGNED period that transitioned to REACHED_OUT counts
                # as a handled case and contributes to time-to-reached-out.
                if p.get("led_to_reached_out"):
                    b["_assigned_lead_ids"].add(p["lead_id"])
                    b["_time_to_reached_out"].append(seconds)

    report: dict[uuid.UUID, dict] = {}
    for attorney_id, b in acc.items():
        times = b["_time_to_reached_out"]
        avg = int(sum(times) / len(times)) if times else 0
        report[attorney_id] = {
            "total_holding_seconds": b["total_holding_seconds"],
            "cases_handled": len(b["_assigned_lead_ids"]),
            "avg_time_to_reached_out_seconds": avg,
            "current_open_load": b["current_open_load"],
            "oldest_open_age_seconds": b["oldest_open_age_seconds"],
        }
    return report


async def open_period(
    db: AsyncSession,
    lead: Lead,
    state: str,
    assignee_id: uuid.UUID | None,
) -> LeadStatePeriod:
    """
    Close the lead's current open period (set exited_at + duration_seconds) and
    insert a new open period for `state`. Call on EVERY state transition so that
    exactly one period per lead remains open.
    """
    now = datetime.now(timezone.utc)

    existing = await db.execute(
        select(LeadStatePeriod)
        .where(LeadStatePeriod.lead_id == lead.id)
        .where(LeadStatePeriod.exited_at.is_(None))
    )
    for current in existing.scalars().all():
        current.exited_at = now
        current.duration_seconds = compute_duration_seconds(current.entered_at, now)
        db.add(current)

    period = LeadStatePeriod(
        lead_id=lead.id,
        state=state,
        assignee_id=assignee_id,
        entered_at=now,
    )
    db.add(period)
    await db.flush()
    return period


async def previous_closed_period(
    db: AsyncSession, lead_id: uuid.UUID
) -> LeadStatePeriod | None:
    """The most recently CLOSED period — i.e. the state the lead was in *before* its
    current open period. Used by reversal to restore the exact prior state + assignee."""
    result = await db.execute(
        select(LeadStatePeriod)
        .where(LeadStatePeriod.lead_id == lead_id)
        .where(LeadStatePeriod.exited_at.is_not(None))
        # entered_at is the deterministic tiebreaker: if two periods ever share an
        # exited_at, the one that started later is the true "most recent".
        .order_by(LeadStatePeriod.exited_at.desc(), LeadStatePeriod.entered_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def lead_timeline(db: AsyncSession, lead_id: uuid.UUID) -> list[LeadStatePeriod]:
    """Return all state periods for a lead ordered chronologically."""
    result = await db.execute(
        select(LeadStatePeriod)
        .where(LeadStatePeriod.lead_id == lead_id)
        .order_by(LeadStatePeriod.entered_at.asc())
    )
    return list(result.scalars().all())


async def attorney_time_report(db: AsyncSession) -> list[dict]:
    """
    Per-attorney time aggregation justifying how long each attorney has held
    cases. Returns a list of rows (one per ATTORNEY) suitable for the
    AttorneyTimeRow schema.
    """
    now = datetime.now(timezone.utc)

    attorneys_result = await db.execute(
        select(User).where(User.role == "ATTORNEY").order_by(User.full_name.asc())
    )
    attorneys = list(attorneys_result.scalars().all())

    periods_result = await db.execute(select(LeadStatePeriod))
    periods = list(periods_result.scalars().all())

    # Determine which closed ASSIGNED periods led directly to REACHED_OUT: a lead
    # whose current status is REACHED_OUT had its last ASSIGNED period lead to it.
    reached_out_leads_result = await db.execute(
        select(Lead.id).where(Lead.status == "REACHED_OUT")
    )
    reached_out_lead_ids = set(reached_out_leads_result.scalars().all())

    period_dicts: list[dict] = []
    for p in periods:
        period_dicts.append(
            {
                "lead_id": p.lead_id,
                "assignee_id": p.assignee_id,
                "state": p.state,
                "entered_at": p.entered_at,
                "exited_at": p.exited_at,
                "duration_seconds": p.duration_seconds,
                "led_to_reached_out": (
                    p.state == "ASSIGNED"
                    and p.exited_at is not None
                    and p.lead_id in reached_out_lead_ids
                ),
            }
        )

    agg = aggregate_attorney_time(period_dicts, now)

    rows: list[dict] = []
    for attorney in attorneys:
        data = agg.get(
            attorney.id,
            {
                "total_holding_seconds": 0,
                "cases_handled": 0,
                "avg_time_to_reached_out_seconds": 0,
                "current_open_load": 0,
                "oldest_open_age_seconds": 0,
            },
        )
        rows.append(
            {
                "attorney_id": attorney.id,
                "name": attorney.full_name,
                **data,
            }
        )
    return rows
