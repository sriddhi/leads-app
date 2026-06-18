import math
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead
from app.schemas.lead import PaginatedLeads
from app.services.workflow import format_lead_number

# Match dimensions an attorney can toggle in the case-history view.
HISTORY_DIMS = ("phone", "email", "first_name", "last_name")


async def case_history(
    db: AsyncSession,
    lead: Lead,
    dims: list[str],
    months: int = 6,
) -> list[tuple[Lead, list[str]]]:
    """Prior cases (excluding this lead) created within the last `months`, matching ANY of the
    selected `dims` (phone / email / first_name / last_name). Returns (lead, matched_on) pairs,
    newest first. Default dims (phone+email) are applied by the caller."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=30 * months)
    conds = []
    if "phone" in dims and lead.normalized_phone:
        conds.append(Lead.normalized_phone == lead.normalized_phone)
    if "email" in dims and lead.normalized_email:
        conds.append(Lead.normalized_email == lead.normalized_email)
    if "first_name" in dims and lead.first_name:
        conds.append(func.lower(Lead.first_name) == lead.first_name.lower())
    if "last_name" in dims and lead.last_name:
        conds.append(func.lower(Lead.last_name) == lead.last_name.lower())
    if not conds:
        return []

    result = await db.execute(
        select(Lead)
        .where(Lead.id != lead.id)
        .where(Lead.created_at >= cutoff)
        .where(or_(*conds))
        .order_by(Lead.created_at.desc())
    )
    rows = list(result.scalars().all())

    out: list[tuple[Lead, list[str]]] = []
    for r in rows:
        matched: list[str] = []
        if "phone" in dims and lead.normalized_phone and r.normalized_phone == lead.normalized_phone:
            matched.append("phone")
        if "email" in dims and lead.normalized_email and r.normalized_email == lead.normalized_email:
            matched.append("email")
        if "first_name" in dims and r.first_name.lower() == (lead.first_name or "").lower():
            matched.append("first_name")
        if "last_name" in dims and r.last_name.lower() == (lead.last_name or "").lower():
            matched.append("last_name")
        out.append((r, matched))
    return out


async def related_open_duplicates(db: AsyncSession, lead: Lead) -> list[Lead]:
    """Other OPEN (PENDING) leads in the same duplicate cluster as `lead`.

    Duplicates are linked, never merged: each flagged lead carries `duplicate_of` pointing at the
    earlier lead it resembles. The cluster's root is `lead.duplicate_of or lead.id`; members are
    that root plus everything pointing at it. Returns only still-actionable (PENDING) members,
    excluding `lead` itself, oldest first — these are the ones an attorney may want to transition
    together with a reference to the parent case number.
    """
    root = lead.duplicate_of or lead.id
    result = await db.execute(
        select(Lead)
        .where(Lead.id != lead.id)
        .where(Lead.status == "PENDING")
        .where(or_(Lead.id == root, Lead.duplicate_of == root))
        .order_by(Lead.created_at.asc())
    )
    return list(result.scalars().all())


async def next_lead_number(db: AsyncSession) -> str:
    """
    Generate the next sequential, zero-padded lead number (e.g. 'LEAD-000123').

    Derived from the MAX existing LEAD-* number + 1 (not count), so it never collides
    after rows are deleted (e.g. retention cleanup leaves gaps below the max). Concurrent
    callers may still race to the same value; the create path retries on IntegrityError.
    """
    result = await db.execute(
        select(func.max(Lead.lead_number)).where(Lead.lead_number.like("LEAD-%"))
    )
    current_max = result.scalar_one_or_none()
    seq = (int(current_max.split("-")[-1]) + 1) if current_max else 1
    return format_lead_number(seq)


async def create_lead(
    db: AsyncSession,
    *,
    first_name: str,
    last_name: str,
    email: str,
    normalized_email: str,
    resume_filename: str,
    resume_original_filename: str,
    phone: str | None = None,
    normalized_phone: str | None = None,
    message: str | None = None,
    lead_number: str | None = None,
    submitter_ip: str | None = None,
    idempotency_key: str | None = None,
    duplicate_of: uuid.UUID | None = None,
    is_potential_duplicate: bool = False,
) -> Lead:
    """Insert a new lead record and return it."""
    lead = Lead(
        first_name=first_name,
        last_name=last_name,
        email=email,
        normalized_email=normalized_email,
        phone=phone,
        normalized_phone=normalized_phone,
        message=message,
        resume_filename=resume_filename,
        resume_original_filename=resume_original_filename,
        status="PENDING",
        lead_number=lead_number,
        submitter_ip=submitter_ip,
        idempotency_key=idempotency_key,
        duplicate_of=duplicate_of,
        is_potential_duplicate=is_potential_duplicate,
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead


async def get_lead_by_id(db: AsyncSession, lead_id: uuid.UUID) -> Lead | None:
    """Fetch a single lead by its UUID."""
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    return result.scalar_one_or_none()


async def get_lead_by_number(db: AsyncSession, lead_number: str) -> Lead | None:
    """Fetch a single lead by its human lead_number."""
    result = await db.execute(select(Lead).where(Lead.lead_number == lead_number))
    return result.scalar_one_or_none()


async def get_lead_by_idempotency_key(
    db: AsyncSession, idempotency_key: str
) -> Lead | None:
    """Fetch a lead previously created with the given idempotency key."""
    result = await db.execute(
        select(Lead).where(Lead.idempotency_key == idempotency_key)
    )
    return result.scalar_one_or_none()


async def get_queue(db: AsyncSession) -> list[Lead]:
    """Unassigned, PENDING leads in FIFO order (oldest first)."""
    result = await db.execute(
        select(Lead)
        .where(Lead.assignee_id.is_(None))
        .where(Lead.status == "PENDING")
        .order_by(Lead.created_at.asc())
    )
    return list(result.scalars().all())


async def get_my_cases(db: AsyncSession, attorney_id: uuid.UUID) -> list[Lead]:
    """Caller's open assigned (PENDING) leads, oldest first."""
    result = await db.execute(
        select(Lead)
        .where(Lead.assignee_id == attorney_id)
        .where(Lead.status == "PENDING")
        .order_by(Lead.created_at.asc())
    )
    return list(result.scalars().all())


async def get_leads_paginated(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
) -> PaginatedLeads:
    """
    Return a paginated list of leads ordered by creation date (newest first).
    """
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    offset = (page - 1) * page_size

    count_result = await db.execute(select(func.count()).select_from(Lead))
    total: int = count_result.scalar_one()

    items_result = await db.execute(
        select(Lead).order_by(Lead.created_at.desc()).offset(offset).limit(page_size)
    )
    items = list(items_result.scalars().all())

    pages = math.ceil(total / page_size) if total > 0 else 1

    return PaginatedLeads(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


async def update_lead_status(
    db: AsyncSession,
    lead: Lead,
    new_status: str,
) -> Lead:
    """Update the status of an existing lead."""
    lead.status = new_status
    lead.updated_at = datetime.now(timezone.utc)
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead
