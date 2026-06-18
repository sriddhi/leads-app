"""Shared result types for the recipe."""

from dataclasses import dataclass, field

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


@dataclass
class Finding:
    invariant_id: str          # e.g. "INV1"
    title: str
    severity: str              # low|medium|high|critical
    endpoint: str              # e.g. "POST /leads" or "-"
    error_class: str           # short machine tag, e.g. "double_assignee"
    detail: str                # human explanation
    samples: list = field(default_factory=list)  # offending ids/values

    @property
    def signature(self) -> str:
        return f"{self.invariant_id}|{self.endpoint}|{self.error_class}"


@dataclass
class Metrics:
    intake_attempted: int = 0
    intake_201: int = 0
    intake_429: int = 0
    intake_422: int = 0
    intake_413: int = 0
    intake_5xx: int = 0
    other_unexpected: int = 0
    reached_out: int = 0
    conflict_409: int = 0
    latencies_ms: list = field(default_factory=list)
    queue_depth_samples: list = field(default_factory=list)
    duration_s: float = 0.0

    def p(self, pct: float) -> float:
        if not self.latencies_ms:
            return 0.0
        xs = sorted(self.latencies_ms)
        k = max(0, min(len(xs) - 1, int(round(pct / 100 * (len(xs) - 1)))))
        return round(xs[k], 1)

    @property
    def total_requests(self) -> int:
        return self.intake_attempted

    @property
    def error_count(self) -> int:
        # Unexpected errors only: 5xx + unexpected non-edge responses. Intended 429/422/413/409
        # from edge cohorts and races are NOT errors.
        return self.intake_5xx + self.other_unexpected

    @property
    def error_rate(self) -> float:
        return (self.error_count / self.total_requests) if self.total_requests else 0.0
