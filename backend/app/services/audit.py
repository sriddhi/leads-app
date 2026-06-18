import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent

# In-process pub/sub for live audit streaming (SSE). Each subscriber gets its own
# asyncio.Queue; publish() fans an event dict out to every subscriber.
_subscribers: set["asyncio.Queue[dict]"] = set()


def subscribe() -> "asyncio.Queue[dict]":
    """Register a new subscriber queue for live audit events."""
    queue: "asyncio.Queue[dict]" = asyncio.Queue(maxsize=1000)
    _subscribers.add(queue)
    return queue


def unsubscribe(queue: "asyncio.Queue[dict]") -> None:
    """Remove a subscriber queue (call when an SSE connection closes)."""
    _subscribers.discard(queue)


def publish(event_dict: dict) -> None:
    """Fan an event dict out to all current subscribers (non-blocking)."""
    for queue in list(_subscribers):
        try:
            queue.put_nowait(event_dict)
        except asyncio.QueueFull:
            # Drop for slow consumers rather than blocking the writer.
            pass


def _serialize(event: AuditEvent) -> dict:
    return {
        "id": str(event.id),
        "lead_id": str(event.lead_id) if event.lead_id else None,
        "actor_id": str(event.actor_id) if event.actor_id else None,
        "actor_kind": event.actor_kind,
        "action": event.action,
        "before": event.before,
        "after": event.after,
        "reason": event.reason,
        "ip": event.ip,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


async def record(
    db: AsyncSession,
    *,
    lead_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    actor_kind: str,
    action: str,
    before: dict | None = None,
    after: dict | None = None,
    reason: str | None = None,
    ip: str | None = None,
) -> AuditEvent:
    """
    Append an AuditEvent (append-only — never updated/deleted) and publish it to
    live subscribers for SSE streaming.
    """
    event = AuditEvent(
        lead_id=lead_id,
        actor_id=actor_id,
        actor_kind=actor_kind,
        action=action,
        before=before,
        after=after,
        reason=reason,
        ip=ip,
        created_at=datetime.now(timezone.utc),
    )
    db.add(event)
    await db.flush()
    await db.refresh(event)

    publish(_serialize(event))
    return event
