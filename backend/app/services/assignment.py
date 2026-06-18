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


async def lock_attorney(db: AsyncSession, attorney_id: uuid.UUID) -> None:
    """Acquire a row lock on the attorney, held until the transaction commits.

    The capacity check is a count-then-assign: read the open-case count, and if it is under
    cap, assign. Without serialization two concurrent assignments to the SAME attorney can both
    read the same under-cap count and both assign, pushing the attorney past max_open_cases.
    Locking the attorney row makes that window atomic — the second assigner blocks until the
    first commits, then re-counts and sees the updated load. The lead row's optimistic-lock
    CAS does NOT cover this, because the two assignments touch different lead rows."""
    await db.execute(select(User.id).where(User.id == attorney_id).with_for_update())


async def has_capacity(db: AsyncSession, attorney: User, *, lock: bool = False) -> bool:
    """True if the attorney is below their max_open_cases capacity.

    Pass ``lock=True`` to first take the attorney row lock (see :func:`lock_attorney`) so the
    check is atomic against concurrent assignments. Callers that have already locked the
    attorney for the duration of a batch may leave it False to avoid re-locking."""
    if lock:
        await lock_attorney(db, attorney.id)
    count = await open_case_count(db, attorney.id)
    return count < attorney.max_open_cases


async def pick_attorney(db: AsyncSession) -> User | None:
    """
    Pick the least-loaded active ATTORNEY whose open case count is under their
    max_open_cases. Round-robin tiebreak by ordering on user id. Returns None if
    every attorney is full.
    """
    # Lock every candidate attorney row (FOR UPDATE) for the duration of the transaction so the
    # least-loaded pick and the assignment that follows are atomic — concurrent auto-assigns
    # serialize here and observe each other's loads, so capacity can't be over-committed.
    # Ordering by id gives a consistent lock-acquisition order, so two concurrent auto-assigns
    # can't deadlock; single-row lockers (self-assign/reassign) take only one lock and so can't
    # form a cycle with this one either.
    attorneys_result = await db.execute(
        select(User)
        .where(User.role == "ATTORNEY")
        .where(User.is_active.is_(True))
        .order_by(User.id.asc())
        .with_for_update()
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
