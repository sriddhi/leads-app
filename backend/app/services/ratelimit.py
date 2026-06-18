import time
from collections import deque

from app.core.config import settings

# In-memory per-client sliding-window rate limiter. Single-process only — for a
# multi-process / multi-replica deployment, swap for a shared store (e.g. Redis),
# otherwise each process keeps its own window. Buckets are pruned and evicted so
# memory stays bounded even under a flood of distinct keys.

_hits: dict[str, deque[float]] = {}


def _prune(bucket: "deque[float]", now: float, window_seconds: int) -> None:
    cutoff = now - window_seconds
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()


def is_allowed(
    key: str,
    *,
    limit: int | None = None,
    window_seconds: int | None = None,
    now: float | None = None,
) -> bool:
    """
    Return True (and record the hit) if a request from `key` is within the window;
    False (without recording) once the limit is reached. `now` is injectable for tests.
    """
    limit = settings.RATE_LIMIT_MAX if limit is None else limit
    window_seconds = settings.RATE_LIMIT_WINDOW_SECONDS if window_seconds is None else window_seconds
    current = time.monotonic() if now is None else now

    bucket = _hits.get(key)
    if bucket is None:
        # Memory guard: if we are tracking too many distinct keys, drop fully-expired
        # buckets before admitting a new one (cheap amortised cleanup).
        if len(_hits) >= settings.RATE_LIMIT_MAX_TRACKED_IPS:
            _evict_expired(current, window_seconds)
        bucket = _hits.setdefault(key, deque())

    _prune(bucket, current, window_seconds)

    if len(bucket) >= limit:
        return False

    bucket.append(current)
    return True


def _evict_expired(now: float, window_seconds: int) -> None:
    cutoff = now - window_seconds
    for k in [k for k, b in _hits.items() if not b or b[-1] <= cutoff]:
        del _hits[k]


def reset() -> None:
    """Clear all rate-limit state (used by tests)."""
    _hits.clear()
