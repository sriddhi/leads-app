import asyncio
import json
import logging
import math
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.auth import get_current_admin
from app.core.security import decode_access_token
from app.crud.users import get_user_by_email
from app.core.database import get_db
from app.crud.settings import get_app_settings
from app.models.audit import AuditEvent
from app.models.lead import Lead
from app.models.user import User
from app.schemas.admin import (
    AttorneyRead,
    AttorneyTimeRow,
    AuditEventRead,
    AutoAssignToggle,
    CapacityUpdate,
    MetricsAttorneyRow,
    MetricsRead,
    PaginatedAudit,
)
from app.services import assignment, audit, timeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# --------------------------------------------------------------------------- #
# Attorneys
# --------------------------------------------------------------------------- #
@router.get(
    "/attorneys",
    response_model=list[AttorneyRead],
    summary="List attorneys with capacity and current load",
)
async def list_attorneys(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> list[AttorneyRead]:
    result = await db.execute(
        select(User).where(User.role == "ATTORNEY").order_by(User.full_name.asc())
    )
    attorneys = list(result.scalars().all())

    rows: list[AttorneyRead] = []
    for attorney in attorneys:
        load = await assignment.open_case_count(db, attorney.id)
        rows.append(
            AttorneyRead(
                id=attorney.id,
                name=attorney.full_name,
                email=attorney.email,
                role=attorney.role,
                is_active=attorney.is_active,
                max_open_cases=attorney.max_open_cases,
                open=load,
            )
        )
    return rows


@router.put(
    "/attorneys/{attorney_id}/capacity",
    response_model=AttorneyRead,
    summary="Update an attorney's max open cases",
)
async def update_capacity(
    attorney_id: uuid.UUID,
    body: CapacityUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> AttorneyRead:
    attorney = await db.get(User, attorney_id)
    if attorney is None or attorney.role != "ATTORNEY":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attorney not found.",
        )

    before = {"max_open_cases": attorney.max_open_cases}
    attorney.max_open_cases = body.max_open_cases
    db.add(attorney)
    await db.flush()

    await audit.record(
        db,
        lead_id=None,
        actor_id=admin.id,
        actor_kind="ADMIN",
        action="CAPACITY_CHANGED",
        before=before,
        after={"max_open_cases": attorney.max_open_cases},
    )

    load = await assignment.open_case_count(db, attorney.id)
    return AttorneyRead(
        id=attorney.id,
        name=attorney.full_name,
        email=attorney.email,
        role=attorney.role,
        is_active=attorney.is_active,
        max_open_cases=attorney.max_open_cases,
        open=load,
    )


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
@router.put(
    "/settings/auto-assign",
    summary="Enable/disable auto-assignment",
)
async def set_auto_assign(
    body: AutoAssignToggle,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> dict:
    app_settings = await get_app_settings(db)
    before = {"auto_assign_enabled": app_settings.auto_assign_enabled}
    app_settings.auto_assign_enabled = body.enabled
    db.add(app_settings)
    await db.flush()

    await audit.record(
        db,
        lead_id=None,
        actor_id=admin.id,
        actor_kind="ADMIN",
        action="AUTO_ASSIGN_TOGGLED",
        before=before,
        after={"auto_assign_enabled": app_settings.auto_assign_enabled},
    )
    return {"auto_assign_enabled": app_settings.auto_assign_enabled}


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #
@router.get(
    "/audit",
    response_model=PaginatedAudit,
    summary="Recent audit events (paginated)",
)
async def list_audit(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    lead_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> PaginatedAudit:
    base = select(AuditEvent)
    count_q = select(func.count()).select_from(AuditEvent)
    if lead_id is not None:
        base = base.where(AuditEvent.lead_id == lead_id)
        count_q = count_q.where(AuditEvent.lead_id == lead_id)

    total = int((await db.execute(count_q)).scalar_one())
    offset = (page - 1) * page_size
    result = await db.execute(
        base.order_by(AuditEvent.created_at.desc()).offset(offset).limit(page_size)
    )
    items = list(result.scalars().all())
    pages = math.ceil(total / page_size) if total > 0 else 1

    return PaginatedAudit(
        items=[AuditEventRead.model_validate(e) for e in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get(
    "/audit/stream",
    summary="Live audit event stream (SSE)",
)
async def audit_stream(
    request: Request,
    token: str = Query(..., description="JWT (EventSource cannot send headers)"),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Server-Sent Events stream of new audit events.

    Auth is via the ``token`` query param because the browser ``EventSource`` API
    cannot set an Authorization header. The token is validated to an active ADMIN.
    """
    email = decode_access_token(token)
    user = await get_user_by_email(db, email=email) if email else None
    if user is None or not user.is_active or user.role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or non-admin token.",
        )

    queue = audit.subscribe()

    async def event_generator():
        try:
            # Initial comment so clients open the stream immediately.
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Keepalive comment to hold the connection open.
                    yield ": keepalive\n\n"
        finally:
            audit.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
@router.get(
    "/metrics",
    response_model=MetricsRead,
    summary="Operational dashboard metrics",
)
async def metrics(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> MetricsRead:
    now = datetime.now(timezone.utc)

    # Queue depth: unassigned PENDING.
    queue_depth = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Lead)
                .where(Lead.assignee_id.is_(None))
                .where(Lead.status == "PENDING")
            )
        ).scalar_one()
    )

    oldest_queued_row = (
        await db.execute(
            select(func.min(Lead.created_at))
            .where(Lead.assignee_id.is_(None))
            .where(Lead.status == "PENDING")
        )
    ).scalar_one_or_none()
    if oldest_queued_row is not None:
        ref = oldest_queued_row
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        oldest_queued_age = max(0, int((now - ref).total_seconds()))
    else:
        oldest_queued_age = 0

    in_progress = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Lead)
                .where(Lead.assignee_id.isnot(None))
                .where(Lead.status == "PENDING")
            )
        ).scalar_one()
    )

    reached_out = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Lead)
                .where(Lead.status == "REACHED_OUT")
            )
        ).scalar_one()
    )

    hour_ago = now - timedelta(hours=1)
    reached_out_last_hour = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Lead)
                .where(Lead.status == "REACHED_OUT")
                .where(Lead.updated_at >= hour_ago)
            )
        ).scalar_one()
    )

    attorneys_result = await db.execute(
        select(User).where(User.role == "ATTORNEY").order_by(User.full_name.asc())
    )
    attorneys = list(attorneys_result.scalars().all())
    attorney_rows: list[MetricsAttorneyRow] = []
    for attorney in attorneys:
        load = await assignment.open_case_count(db, attorney.id)
        cap = attorney.max_open_cases
        utilization = round(load / cap, 4) if cap > 0 else 0.0
        attorney_rows.append(
            MetricsAttorneyRow(
                id=attorney.id,
                name=attorney.full_name,
                open=load,
                cap=cap,
                utilization=utilization,
            )
        )

    return MetricsRead(
        queue_depth=queue_depth,
        oldest_queued_age_seconds=oldest_queued_age,
        in_progress=in_progress,
        reached_out=reached_out,
        reached_out_last_hour=reached_out_last_hour,
        attorneys=attorney_rows,
    )


@router.get(
    "/attorney-time",
    response_model=list[AttorneyTimeRow],
    summary="Per-attorney time tracking report",
)
async def attorney_time(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> list[AttorneyTimeRow]:
    rows = await timeline.attorney_time_report(db)
    return [AttorneyTimeRow(**row) for row in rows]
