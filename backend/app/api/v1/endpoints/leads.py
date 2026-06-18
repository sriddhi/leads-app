import asyncio
import html
import logging
import uuid
from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.auth import (
    get_current_attorney_or_admin,
    get_current_user,
)
from app.core.database import get_db
from app.crud.leads import (
    HISTORY_DIMS,
    case_history,
    create_lead,
    get_lead_by_id,
    get_lead_by_idempotency_key,
    get_lead_by_number,
    get_leads_paginated,
    get_my_cases,
    get_queue,
    next_lead_number,
    related_open_duplicates,
)
from app.crud.settings import get_app_settings
from app.models.lead import Lead
from app.models.user import User
import re
from pathlib import Path

from fastapi.responses import FileResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.core.config import settings
from app.core.security import decode_access_token
from app.crud.users import get_user_by_email
from app.schemas.lead import (
    AssignRequest,
    CaseHistoryItem,
    LeadDetail,
    LeadRead,
    LeadReceipt,
    LeadStatusUpdate,
    PaginatedLeads,
    QueueItem,
    ReassignRequest,
    RelatedLeadItem,
    RelatedTransitionRequest,
    RelatedTransitionResult,
    ReverseRequest,
    StatePeriodRead,
)
from app.services import assignment, audit, identity, ratelimit, timeline
from app.services.email import send_lead_emails
from app.services.storage import save_resume
from app.services.workflow import can_transition, version_conflict

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/leads", tags=["leads"])

# Pragmatic server-side email format check — never trust the client's validation.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Hold references to fire-and-forget email tasks so they aren't garbage-collected
# mid-flight (and so their exceptions are observed via the done callback).
_email_tasks: set = set()


def _fire_emails(first_name: str, last_name: str, email: str) -> None:
    task = asyncio.create_task(
        send_lead_emails(first_name=first_name, last_name=last_name, email=email)
    )
    _email_tasks.add(task)
    task.add_done_callback(_email_tasks.discard)


def _client_ip(request: Request) -> str | None:
    """Resolve the client IP for rate limiting.

    By default this is the real socket peer. ``X-Forwarded-For`` / ``X-Real-IP`` are
    honoured ONLY when ``TRUST_PROXY_HEADERS`` is enabled (i.e. the app genuinely sits
    behind a trusted proxy). Otherwise a client could spoof the header to mint a fresh
    rate-limit bucket on every request and bypass throttling entirely.
    """
    if settings.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real = request.headers.get("x-real-ip")
        if real:
            return real.strip()
    return request.client.host if request.client else None


def _sanitize_text(value: str, max_length: int) -> str:
    """Trim, length-cap, and HTML-escape free text from public submissions."""
    cleaned = (value or "").strip()[:max_length]
    return html.escape(cleaned)


def _age_seconds(created_at: datetime) -> int:
    now = datetime.now(timezone.utc)
    ref = created_at
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    return max(0, int((now - ref).total_seconds()))


async def _assignee_name(db: AsyncSession, lead: Lead) -> str | None:
    """Resolve the assigned attorney's display name (None if unassigned)."""
    if lead.assignee_id is None:
        return None
    user = await db.get(User, lead.assignee_id)
    return user.full_name if user else None


async def _build_detail(db: AsyncSession, lead: Lead) -> LeadDetail:
    periods = await timeline.lead_timeline(db, lead.id)
    detail = LeadDetail.model_validate(lead)
    detail.assignee_name = await _assignee_name(db, lead)
    detail.timeline = [StatePeriodRead.model_validate(p) for p in periods]
    return detail


# --------------------------------------------------------------------------- #
# Public submission
# --------------------------------------------------------------------------- #
@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Submit a new lead (public endpoint)",
)
async def submit_lead(
    request: Request,
    first_name: str = Form(..., max_length=100),
    last_name: str = Form(..., max_length=100),
    email: str = Form(..., max_length=255),
    phone: str = Form("", max_length=50, description="Optional phone number"),
    message: str = Form("", max_length=2000, description="Optional message/question"),
    resume: UploadFile = File(...),
    company_website: str = Form("", description="Honeypot — must be left empty"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
):
    """
    Public endpoint — no authentication required.

    Includes honeypot spam protection, per-IP rate limiting, idempotency,
    duplicate flagging (link & flag, never merge), and optional auto-assignment.
    """
    ip = _client_ip(request)

    # Honeypot: if the hidden field is filled, treat as spam — audit, no real lead.
    if company_website.strip():
        await audit.record(
            db,
            lead_id=None,
            actor_id=None,
            actor_kind="PUBLIC",
            action="SPAM_BLOCKED",
            ip=ip,
            reason="Honeypot field populated.",
        )
        logger.info("Spam submission blocked from ip=%s", ip)
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED, content={"status": "accepted"}
        )

    # Per-IP rate limiting.
    if ip is not None and not ratelimit.is_allowed(ip):
        await audit.record(
            db,
            lead_id=None,
            actor_id=None,
            actor_kind="PUBLIC",
            action="RATE_LIMITED",
            ip=ip,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many submissions. Please try again later.",
        )

    # Idempotency: replay returns a minimal receipt (never another user's lead data).
    if idempotency_key:
        existing = await get_lead_by_idempotency_key(db, idempotency_key)
        if existing is not None:
            return LeadReceipt(lead_number=existing.lead_number, status=existing.status)

    # Sanitize / length-enforce.
    first_clean = _sanitize_text(first_name, 100)
    last_clean = _sanitize_text(last_name, 100)
    email_clean = (email or "").strip()[:255]
    phone_clean = _sanitize_text(phone, 50) or None
    normalized_phone = identity.normalize_phone(phone_clean)
    message_clean = _sanitize_text(message, settings.MAX_MESSAGE_CHARS) or None

    # Server-side validation — do not trust the client. Required text + email format.
    if not first_clean or not last_clean:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="First and last name are required.",
        )
    if not _EMAIL_RE.match(email_clean):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A valid email address is required.",
        )
    normalized = identity.normalize_email(email_clean)

    # Validate + persist resume file (streamed, magic-byte checked).
    stored_filename, original_filename = await save_resume(resume)

    # Duplicate detection (link & flag).
    dup_id = await identity.detect_duplicates(
        db, normalized, full_name=f"{first_clean} {last_clean}"
    )
    is_dup = dup_id is not None

    # Race-safe create: lead_number (count-derived) and idempotency_key are unique, so two
    # concurrent submits can collide. Retry with a fresh number; if a concurrent request won
    # the same idempotency key, return its receipt instead of a 500.
    lead = None
    for _attempt in range(4):
        lead_number = await next_lead_number(db)
        try:
            lead = await create_lead(
                db,
                first_name=first_clean,
                last_name=last_clean,
                email=email_clean,
                normalized_email=normalized,
                phone=phone_clean,
                normalized_phone=normalized_phone,
                message=message_clean,
                resume_filename=stored_filename,
                resume_original_filename=original_filename,
                lead_number=lead_number,
                submitter_ip=ip,
                idempotency_key=idempotency_key,
                duplicate_of=dup_id,
                is_potential_duplicate=is_dup,
            )
            break
        except IntegrityError:
            await db.rollback()
            if idempotency_key:
                existing = await get_lead_by_idempotency_key(db, idempotency_key)
                if existing is not None:
                    return LeadReceipt(lead_number=existing.lead_number, status=existing.status)
            # else: lead_number collision — loop retries with a fresh number.
    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not record your submission right now. Please try again.",
        )

    if is_dup:
        await audit.record(
            db,
            lead_id=lead.id,
            actor_id=None,
            actor_kind="SYSTEM",
            action="DUPLICATE_FLAGGED",
            after={"duplicate_of": str(dup_id)},
            ip=ip,
        )

    # Open the initial QUEUED period.
    await timeline.open_period(db, lead, state="QUEUED", assignee_id=None)
    await audit.record(
        db,
        lead_id=lead.id,
        actor_id=None,
        actor_kind="PUBLIC",
        action="LEAD_CREATED",
        after={"lead_number": lead.lead_number, "status": lead.status},
        ip=ip,
    )

    # Optional auto-assignment to least-loaded under-cap attorney.
    app_settings = await get_app_settings(db)
    if app_settings.auto_assign_enabled:
        attorney = await assignment.pick_attorney(db)
        if attorney is not None:
            lead.assignee_id = attorney.id
            lead.updated_at = datetime.now(timezone.utc)
            db.add(lead)
            await db.flush()
            await timeline.open_period(
                db, lead, state="ASSIGNED", assignee_id=attorney.id
            )
            await audit.record(
                db,
                lead_id=lead.id,
                actor_id=None,
                actor_kind="SYSTEM",
                action="AUTO_ASSIGNED",
                after={"assignee_id": str(attorney.id)},
                ip=ip,
            )
            await db.refresh(lead)

    # Capture fields for the email BEFORE returning; commit happens in get_db after this
    # handler. Fire-and-forget with a tracked task so it isn't GC'd and can't crash the request.
    receipt = LeadReceipt(lead_number=lead.lead_number, status=lead.status)
    _fire_emails(lead.first_name, lead.last_name, lead.email)

    logger.info("New lead created: id=%s number=%s", lead.id, lead.lead_number)
    return receipt


# --------------------------------------------------------------------------- #
# Queue / my-cases
# --------------------------------------------------------------------------- #
@router.get(
    "/queue",
    response_model=list[QueueItem],
    summary="Unassigned PENDING leads (FIFO)",
)
async def list_queue(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_attorney_or_admin),
) -> list[QueueItem]:
    leads = await get_queue(db)
    return [
        QueueItem(
            id=lead.id,
            lead_number=lead.lead_number,
            first_name=lead.first_name,
            last_name=lead.last_name,
            email=lead.email,
            status=lead.status,
            assignee_id=lead.assignee_id,
            version=lead.version,
            is_potential_duplicate=lead.is_potential_duplicate,
            created_at=lead.created_at,
            age_seconds=_age_seconds(lead.created_at),
        )
        for lead in leads
    ]


@router.get(
    "/my-cases",
    response_model=list[LeadRead],
    summary="Caller's open assigned leads",
)
async def list_my_cases(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_attorney_or_admin),
) -> list[LeadRead]:
    leads = await get_my_cases(db, current_user.id)
    # All of these are assigned to the caller, so the name is the caller's.
    out = []
    for lead in leads:
        item = LeadRead.model_validate(lead)
        item.assignee_name = current_user.full_name
        out.append(item)
    return out


# --------------------------------------------------------------------------- #
# Admin list (keep existing pagination shape)
# --------------------------------------------------------------------------- #
@router.get(
    "",
    response_model=PaginatedLeads,
    summary="List all leads (protected)",
)
async def list_leads(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_attorney_or_admin),
) -> PaginatedLeads:
    return await get_leads_paginated(db, page=page, page_size=page_size)


# --------------------------------------------------------------------------- #
# Lookups
# --------------------------------------------------------------------------- #
@router.get(
    "/by-number/{lead_number}",
    response_model=LeadDetail,
    summary="Get a lead by its human number (with timeline)",
)
async def get_lead_by_number_endpoint(
    lead_number: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> LeadDetail:
    lead = await get_lead_by_number(db, lead_number)
    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead '{lead_number}' was not found.",
        )
    return await _build_detail(db, lead)


@router.get(
    "/{lead_id}",
    response_model=LeadDetail,
    summary="Get a single lead by ID (with timeline)",
)
async def get_lead(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> LeadDetail:
    lead = await get_lead_by_id(db, lead_id)
    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead with id '{lead_id}' was not found.",
        )
    return await _build_detail(db, lead)


@router.get(
    "/{lead_id}/resume",
    summary="Download a lead's resume (authenticated; PII)",
)
async def download_resume(
    lead_id: uuid.UUID,
    token: str = Query(..., description="JWT (an <a> download cannot send headers)"),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Serve the resume only to an authenticated attorney/admin. Resumes are sensitive PII,
    so they are never exposed as public static files. Auth is via a ``token`` query param
    because a browser download link cannot set an Authorization header."""
    email = decode_access_token(token)
    user = await get_user_by_email(db, email=email) if email else None
    if user is None or not user.is_active or user.role not in ("ADMIN", "ATTORNEY"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )

    lead = await get_lead_by_id(db, lead_id)
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found.")

    # Resolve strictly within the upload dir (the stored name is a UUID we generated, but
    # resolve + containment check defends against any path-traversal regression).
    upload_dir = Path(settings.UPLOAD_DIR).resolve()
    path = (upload_dir / lead.resume_filename).resolve()
    if upload_dir not in path.parents or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume file not found.")

    # Sanitize the download filename (strip path separators) to avoid header issues.
    safe_name = (lead.resume_original_filename or "resume").replace("/", "_").replace("\\", "_")
    return FileResponse(path, filename=safe_name, media_type="application/octet-stream")


@router.get(
    "/{lead_id}/history",
    response_model=list[CaseHistoryItem],
    summary="Prior cases matching this lead (phone/email/name) within the last N months",
)
async def lead_history(
    lead_id: uuid.UUID,
    dims: str = Query("phone,email", description="csv of phone,email,first_name,last_name"),
    months: int = Query(6, ge=1, le=24),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_attorney_or_admin),
) -> list[CaseHistoryItem]:
    """Case history for the agent: prior cases matching ANY selected dimension within `months`.
    Default = phone OR email. Auth-gated (attorney/admin)."""
    lead = await get_lead_by_id(db, lead_id)
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found.")

    selected = [d.strip() for d in dims.split(",") if d.strip() in HISTORY_DIMS]
    if not selected:
        selected = ["phone", "email"]

    pairs = await case_history(db, lead, selected, months=months)
    return [
        CaseHistoryItem(
            id=other.id,
            lead_number=other.lead_number,
            first_name=other.first_name,
            last_name=other.last_name,
            email=other.email,
            phone=other.phone,
            status=other.status,
            created_at=other.created_at,
            matched_on=matched,
        )
        for other, matched in pairs
    ]


# --------------------------------------------------------------------------- #
# Related open duplicates (bulk transition)
# --------------------------------------------------------------------------- #
@router.get(
    "/{lead_id}/related",
    response_model=list[RelatedLeadItem],
    summary="Open leads in this lead's duplicate cluster (eligible for bulk action)",
)
async def list_related(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_attorney_or_admin),
) -> list[RelatedLeadItem]:
    lead = await _load_or_404(db, lead_id)
    related = await related_open_duplicates(db, lead)
    return [RelatedLeadItem.model_validate(r) for r in related]


@router.post(
    "/{lead_id}/related/transition",
    response_model=list[RelatedTransitionResult],
    summary="Assign-to-self or mark-reached-out selected related (duplicate) leads",
)
async def transition_related(
    lead_id: uuid.UUID,
    body: RelatedTransitionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_attorney_or_admin),
) -> list[RelatedTransitionResult]:
    """Apply one action to selected OPEN leads in the parent lead's duplicate cluster.

    Each transition records an audit note referencing the parent case number, so the trail shows
    these were actioned together with the parent. Per-lead failures (capacity, already assigned,
    not a cluster member) are reported individually rather than failing the whole batch.
    """
    parent = await _load_or_404(db, lead_id)
    is_admin = current_user.role == "ADMIN"

    # Only leads genuinely in the parent's open cluster are eligible — prevents using this as a
    # generic bulk-mutate over arbitrary ids.
    eligible = {r.id: r for r in await related_open_duplicates(db, parent)}

    ref = f"Related to parent case {parent.lead_number}"
    note = (body.note or "").strip()
    reason = f"{ref}. {note}" if note else ref

    # Self-assign is capacity-gated: lock the caller's row once up front so the per-lead checks
    # below are atomic against concurrent assignments for the whole batch (no over-commit). The
    # lock is held for the transaction and is unaffected by the per-lead savepoints; the per-lead
    # has_capacity() re-counts (seeing earlier assigns in this batch) but need not re-lock.
    if body.action == "assign":
        await assignment.lock_attorney(db, current_user.id)

    results: list[RelatedTransitionResult] = []
    for target_id in body.lead_ids:
        lead = eligible.get(target_id)
        if lead is None:
            results.append(RelatedTransitionResult(
                id=target_id, lead_number=None, ok=False,
                detail="Not an open lead in this duplicate cluster.",
            ))
            continue

        # Capture identity BEFORE the savepoint. A StaleDataError rolls the savepoint back and
        # EXPIRES this lead's attributes, so reading lead.lead_number afterwards would trigger a
        # lazy reload — sync IO in an async context (MissingGreenlet). Plain locals are safe.
        lead_id, lead_no = lead.id, lead.lead_number

        # Each lead is mutated inside its own SAVEPOINT. The version_id_col compare-and-swap
        # can raise StaleDataError if a lead was changed concurrently; the savepoint lets us
        # roll back just that one lead and report it as a per-lead failure, exactly like the
        # in-memory _SkipReason checks, without poisoning the rest of the batch.
        try:
            async with db.begin_nested():
                if body.action == "assign":
                    if lead.assignee_id is not None:
                        raise _SkipReason(
                            "Already assigned."
                            if lead.assignee_id != current_user.id
                            else "Already assigned to you."
                        )
                    if not await assignment.has_capacity(db, current_user):
                        raise _SkipReason("You are at your maximum open case capacity.")
                    lead.assignee_id = current_user.id
                    lead.updated_at = datetime.now(timezone.utc)
                    db.add(lead)
                    await db.flush()
                    await timeline.open_period(db, lead, state="ASSIGNED", assignee_id=current_user.id)
                    await audit.record(
                        db, lead_id=lead.id, actor_id=current_user.id, actor_kind=current_user.role,
                        action="SELF_ASSIGNED",
                        after={"assignee_id": str(current_user.id), "parent_lead": parent.lead_number},
                        reason=reason,
                    )
                    detail = "Assigned to you."
                else:  # reached_out
                    if lead.assignee_id is None:
                        raise _SkipReason("Lead must be assigned before it can be reached out.")
                    if not is_admin and lead.assignee_id != current_user.id:
                        raise _SkipReason("Assigned to another attorney.")
                    before = {"status": lead.status}
                    lead.status = "REACHED_OUT"
                    lead.updated_at = datetime.now(timezone.utc)
                    db.add(lead)
                    await db.flush()
                    await timeline.open_period(db, lead, state="REACHED_OUT", assignee_id=lead.assignee_id)
                    await audit.record(
                        db, lead_id=lead.id, actor_id=current_user.id, actor_kind=current_user.role,
                        action="MARKED_REACHED_OUT",
                        before=before, after={"status": "REACHED_OUT", "parent_lead": parent.lead_number},
                        reason=reason,
                    )
                    detail = "Marked reached out."
            results.append(RelatedTransitionResult(
                id=lead_id, lead_number=lead_no, ok=True, detail=detail,
            ))
        except _SkipReason as skip:
            results.append(RelatedTransitionResult(
                id=lead_id, lead_number=lead_no, ok=False, detail=str(skip),
            ))
        except StaleDataError:
            results.append(RelatedTransitionResult(
                id=lead_id, lead_number=lead_no, ok=False,
                detail="Changed by someone else; reload and retry.",
            ))
    return results


class _SkipReason(Exception):
    """Per-lead, non-fatal reason a bulk transition skipped one lead."""


# --------------------------------------------------------------------------- #
# Assignment
# --------------------------------------------------------------------------- #
async def _load_or_404(db: AsyncSession, lead_id: uuid.UUID) -> Lead:
    lead = await get_lead_by_id(db, lead_id)
    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead with id '{lead_id}' was not found.",
        )
    return lead


def _check_version(lead: Lead, expected: int) -> None:
    """Fast, friendly pre-check: reject a stale client version before doing any work.

    This is an optimization for the common case and a clearer error message — it is NOT
    the safety guarantee. The actual guarantee is the database compare-and-swap enforced
    by ``version_id_col`` on the model, surfaced via :func:`_flush_or_conflict`. The window
    between this in-memory check and the flush is exactly where a concurrent writer slips
    through, and that is what the DB-level guard closes.
    """
    if version_conflict(lead.version, expected):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Version conflict: lead is at version {lead.version}, "
                f"you sent {expected}. Reload and retry."
            ),
        )


async def _flush_or_conflict(db: AsyncSession) -> None:
    """Flush pending changes, translating the optimistic-lock failure into a 409.

    With ``version_id_col`` configured, SQLAlchemy emits ``UPDATE ... WHERE id=:id AND
    version=:loaded`` and raises :class:`StaleDataError` when that matches 0 rows — i.e.
    another transaction committed a change to this row after we loaded it. That is the
    atomic compare-and-swap; we map it to the same 409 a stale version would produce.
    """
    try:
        await db.flush()
    except StaleDataError:
        # `from None`: a lost optimistic-lock race is an expected 409, not an internal error —
        # suppress the StaleDataError chain so it doesn't surface as a traceback in logs.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This lead was just modified by someone else. Reload and retry.",
        ) from None


@router.post(
    "/{lead_id}/assign",
    response_model=LeadDetail,
    summary="Self-assign a queued lead (attorney)",
)
async def assign_lead(
    lead_id: uuid.UUID,
    body: AssignRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_attorney_or_admin),
) -> LeadDetail:
    lead = await _load_or_404(db, lead_id)
    _check_version(lead, body.version)

    if lead.assignee_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lead is already assigned.",
        )

    if not await assignment.has_capacity(db, current_user, lock=True):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are at your maximum open case capacity.",
        )

    before = {"assignee_id": None}
    lead.assignee_id = current_user.id
    lead.updated_at = datetime.now(timezone.utc)
    db.add(lead)
    await _flush_or_conflict(db)  # version_id_col CAS: loses the race -> 409, never double-assigns

    await timeline.open_period(db, lead, state="ASSIGNED", assignee_id=current_user.id)
    await audit.record(
        db,
        lead_id=lead.id,
        actor_id=current_user.id,
        actor_kind=current_user.role,
        action="SELF_ASSIGNED",
        before=before,
        after={"assignee_id": str(current_user.id)},
    )
    await db.refresh(lead)
    return await _build_detail(db, lead)


@router.post(
    "/{lead_id}/reassign",
    response_model=LeadDetail,
    summary="Reassign a lead (admin or current assignee)",
)
async def reassign_lead(
    lead_id: uuid.UUID,
    body: ReassignRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_attorney_or_admin),
) -> LeadDetail:
    lead = await _load_or_404(db, lead_id)
    _check_version(lead, body.version)

    is_admin = current_user.role == "ADMIN"
    if not is_admin and lead.assignee_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an admin or the current assignee may reassign this lead.",
        )

    target_id = body.assignee_id
    before = {"assignee_id": str(lead.assignee_id) if lead.assignee_id else None}

    if target_id is not None:
        # Capacity-check the target attorney.
        target = await db.get(User, target_id)
        if target is None or target.role != "ATTORNEY" or not target.is_active:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Target must be an active attorney.",
            )
        if not await assignment.has_capacity(db, target, lock=True):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Target attorney is at maximum open case capacity.",
            )

    lead.assignee_id = target_id
    lead.updated_at = datetime.now(timezone.utc)
    db.add(lead)
    await _flush_or_conflict(db)

    if target_id is not None:
        await timeline.open_period(db, lead, state="ASSIGNED", assignee_id=target_id)
        action = "REASSIGNED"
    else:
        await timeline.open_period(db, lead, state="QUEUED", assignee_id=None)
        action = "UNASSIGNED"

    await audit.record(
        db,
        lead_id=lead.id,
        actor_id=current_user.id,
        actor_kind=current_user.role,
        action=action,
        before=before,
        after={"assignee_id": str(target_id) if target_id else None},
        reason=body.reason,
    )
    await db.refresh(lead)
    return await _build_detail(db, lead)


# --------------------------------------------------------------------------- #
# Status transitions
# --------------------------------------------------------------------------- #
@router.patch(
    "/{lead_id}/status",
    response_model=LeadDetail,
    summary="Mark a lead REACHED_OUT (assignee or admin)",
)
async def patch_lead_status(
    lead_id: uuid.UUID,
    body: LeadStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_attorney_or_admin),
) -> LeadDetail:
    lead = await _load_or_404(db, lead_id)

    is_admin = current_user.role == "ADMIN"
    if not is_admin and lead.assignee_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the assignee or an admin may update this lead's status.",
        )

    _check_version(lead, body.version)

    # Already in the target state -> conflict, no duplicate audit.
    if lead.status == "REACHED_OUT":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lead is already marked REACHED_OUT.",
        )

    # You can only "reach out" on a lead someone owns — otherwise the reach-out has no
    # attributable attorney and would be lost from time accounting.
    if lead.assignee_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Lead must be assigned to an attorney before it can be marked REACHED_OUT.",
        )

    if not can_transition(lead.status, body.status):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cannot transition lead from '{lead.status}' to '{body.status}'.",
        )

    before = {"status": lead.status}
    lead.status = body.status
    lead.updated_at = datetime.now(timezone.utc)
    db.add(lead)
    await _flush_or_conflict(db)

    await timeline.open_period(
        db, lead, state="REACHED_OUT", assignee_id=lead.assignee_id
    )
    await audit.record(
        db,
        lead_id=lead.id,
        actor_id=current_user.id,
        actor_kind=current_user.role,
        action="MARKED_REACHED_OUT",
        before=before,
        after={"status": lead.status},
    )
    await db.refresh(lead)
    return await _build_detail(db, lead)


@router.post(
    "/{lead_id}/reverse",
    response_model=LeadDetail,
    summary="Reverse REACHED_OUT -> PENDING (assignee or admin, reason required)",
)
async def reverse_lead(
    lead_id: uuid.UUID,
    body: ReverseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_attorney_or_admin),
) -> LeadDetail:
    lead = await _load_or_404(db, lead_id)

    is_admin = current_user.role == "ADMIN"
    if not is_admin and lead.assignee_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the assignee or an admin may reverse this lead.",
        )

    _check_version(lead, body.version)

    if not can_transition(lead.status, "PENDING"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cannot reverse a lead in status '{lead.status}'.",
        )

    before = {"status": lead.status}

    # Reversal restores the lead to its PREVIOUS state — the state it held immediately
    # before REACHED_OUT (with that assignee). Fetch it before open_period() closes the
    # current REACHED_OUT period and makes it the latest-closed.
    prior = await timeline.previous_closed_period(db, lead.id)
    if prior is not None and prior.state in ("ASSIGNED", "QUEUED"):
        prior_state, prior_assignee = prior.state, prior.assignee_id
    else:
        # No usable prior workable period — derive from current ownership.
        prior_assignee = lead.assignee_id
        prior_state = "ASSIGNED" if prior_assignee is not None else "QUEUED"

    lead.status = "PENDING"
    lead.assignee_id = prior_assignee
    lead.updated_at = datetime.now(timezone.utc)
    db.add(lead)
    await _flush_or_conflict(db)

    await timeline.open_period(db, lead, state=prior_state, assignee_id=prior_assignee)

    await audit.record(
        db,
        lead_id=lead.id,
        actor_id=current_user.id,
        actor_kind=current_user.role,
        action="REVERSED",
        before=before,
        after={"status": lead.status, "restored_state": prior_state},
        reason=body.reason,
    )
    await db.refresh(lead)
    return await _build_detail(db, lead)
