import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead
from app.models.user import User


def choose_least_loaded(
    candidates: list[tuple[uuid.UUID, int, int]],
) -> uuid.UUID | None:
    """
    Pure helper (no DB) so the assignment policy is unit-testable.

    `candidates` is a list of (attorney_id, open_count, max_open_cases).
    Returns the id of the least-loaded attorney whose open_count < cap.
    Ties are broken deterministically (round-robin friendly) by preserving the
    caller's input order — the first attorney with the minimum load wins.
    Returns None if every attorney is at/over capacity.
    """
    eligible = [
        (attorney_id, open_count)
        for (attorney_id, open_count, cap) in candidates
        if open_count < cap
    ]
    if not eligible:
        return None

    min_load = min(open_count for (_, open_count) in eligible)
    for attorney_id, open_count in eligible:
        if open_count == min_load:
            return attorney_id
    return None


async def open_case_count(db: AsyncSession, attorney_id: uuid.UUID) -> int:
    """Number of open (non-REACHED_OUT) leads currently assigned to an attorney."""
    result = await db.execute(
        select(func.count())
        .select_from(Lead)
        .where(Lead.assignee_id == attorney_id)
        .where(Lead.status != "REACHED_OUT")
    )
    return int(result.scalar_one())


async def has_capacity(db: AsyncSession, attorney: User) -> bool:
    """True if the attorney is below their max_open_cases capacity."""
    count = await open_case_count(db, attorney.id)
    return count < attorney.max_open_cases


async def pick_attorney(db: AsyncSession) -> User | None:
    """
    Pick the least-loaded active ATTORNEY whose open case count is under their
    max_open_cases. Round-robin tiebreak by ordering on user id. Returns None if
    every attorney is full.
    """
    attorneys_result = await db.execute(
        select(User)
        .where(User.role == "ATTORNEY")
        .where(User.is_active.is_(True))
        .order_by(User.id.asc())
    )
    attorneys = list(attorneys_result.scalars().all())
    if not attorneys:
        return None

    by_id = {a.id: a for a in attorneys}
    candidates: list[tuple[uuid.UUID, int, int]] = []
    for attorney in attorneys:
        count = await open_case_count(db, attorney.id)
        candidates.append((attorney.id, count, attorney.max_open_cases))

    chosen_id = choose_least_loaded(candidates)
    if chosen_id is None:
        return None
    return by_id[chosen_id]
