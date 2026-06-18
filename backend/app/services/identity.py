import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead


def normalize_email(email: str) -> str:
    """Return a canonical form of an email address (trimmed + lowercased)."""
    return (email or "").strip().lower()


def normalize_phone(phone: str | None) -> str | None:
    """Return a canonical form of a phone number: digits only (drops spaces, dashes,
    parens, leading +). Returns None when there are no digits (so matching/indexing
    skips empty values)."""
    if not phone:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit())
    return digits or None


async def detect_duplicates(
    db: AsyncSession,
    normalized_email: str,
    full_name: str | None = None,
) -> uuid.UUID | None:
    """
    LINK & FLAG duplicate detection — never merges.

    Returns the id of the EARLIEST existing lead that shares the same
    normalized_email, or None if there is no match. full_name is accepted for
    interface completeness/future heuristics but matching is on email only:
    family members or different names sharing an email are still flagged
    (linked to the earliest), never merged.
    """
    normalized_email = normalize_email(normalized_email)
    if not normalized_email:
        return None

    result = await db.execute(
        select(Lead.id)
        .where(Lead.normalized_email == normalized_email)
        .order_by(Lead.created_at.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()
