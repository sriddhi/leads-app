"""Pure workflow helpers (no DB) so the state machine and optimistic-locking
rules are unit-testable in isolation."""

# Valid lead status transitions.
ALLOWED_TRANSITIONS: dict[str, list[str]] = {
    "PENDING": ["REACHED_OUT"],
    "REACHED_OUT": ["PENDING"],  # reversal (audited, requires reason + permission)
}


def can_transition(current: str, target: str) -> bool:
    """True if `current` -> `target` is a permitted status transition."""
    return target in ALLOWED_TRANSITIONS.get(current, [])


def version_conflict(current_version: int, expected_version: int) -> bool:
    """True if the client's expected version does not match the stored version."""
    return current_version != expected_version


def format_lead_number(seq: int) -> str:
    """Format a sequential integer as a human-friendly lead number."""
    return f"LEAD-{seq:06d}"
