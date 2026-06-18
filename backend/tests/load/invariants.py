"""Post-run, state-based correctness checks. Each returns Findings (empty = pass)."""

from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from tests.load.types import Finding


async def check_caps(cap: int) -> list[Finding]:
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(text(
            "SELECT u.email, count(l.id) AS open "
            "FROM users u LEFT JOIN leads l ON l.assignee_id = u.id AND l.status <> 'REACHED_OUT' "
            "WHERE u.role = 'ATTORNEY' GROUP BY u.email, u.max_open_cases "
            "HAVING count(l.id) > u.max_open_cases"
        ))).all()
    if rows:
        return [Finding("INV2", "Attorney over capacity", "critical", "-", "over_cap",
                        f"{len(rows)} attorney(s) exceed cap (limit {cap})",
                        [f"{e}={n}" for e, n in rows[:5]])]
    return []


async def check_periods() -> list[Finding]:
    async with AsyncSessionLocal() as s:
        multi = (await s.execute(text(
            "SELECT lead_id, count(*) c FROM lead_state_periods WHERE exited_at IS NULL "
            "GROUP BY lead_id HAVING count(*) > 1"
        ))).all()
        neg = (await s.execute(text(
            "SELECT count(*) FROM lead_state_periods WHERE duration_seconds < 0"
        ))).scalar_one()
    f = []
    if multi:
        f.append(Finding("INV8", "Multiple open state periods", "critical", "-", "multi_open",
                         f"{len(multi)} lead(s) have >1 open period", [str(x[0]) for x in multi[:5]]))
    if neg:
        f.append(Finding("INV8", "Negative period duration", "high", "-", "neg_duration",
                         f"{neg} period(s) have negative duration"))
    return f


async def check_audit_reached_out() -> list[Finding]:
    async with AsyncSessionLocal() as s:
        # every REACHED_OUT lead should have at least one MARKED_REACHED_OUT audit event
        # Exclude directly-seeded backdated rows (SEED-/HIST-/ST-), which never went through the
        # API transition flow and so legitimately carry no MARKED_REACHED_OUT event.
        missing = (await s.execute(text(
            "SELECT l.lead_number FROM leads l WHERE l.status = 'REACHED_OUT' "
            "AND l.lead_number NOT LIKE 'SEED-%' AND l.lead_number NOT LIKE 'HIST-%' "
            "AND l.lead_number NOT LIKE 'ST-%' AND NOT EXISTS "
            "(SELECT 1 FROM audit_events a WHERE a.lead_id = l.id AND a.action = 'MARKED_REACHED_OUT')"
        ))).all()
    if missing:
        return [Finding("INV7", "Reach-out not audited", "high", "-", "audit_gap",
                        f"{len(missing)} REACHED_OUT lead(s) lack an audit event",
                        [x[0] for x in missing[:5]])]
    return []


async def check_metrics(c: httpx.AsyncClient, admin_token: str) -> list[Finding]:
    async with AsyncSessionLocal() as s:
        qd = (await s.execute(text(
            "SELECT count(*) FROM leads WHERE assignee_id IS NULL AND status = 'PENDING'"
        ))).scalar_one()
    r = await c.get("/api/v1/admin/metrics", headers={"Authorization": f"Bearer {admin_token}"})
    if r.status_code != 200:
        return [Finding("INV12", "Metrics endpoint failed", "high", "GET /admin/metrics",
                        "metrics_fail", f"status {r.status_code}")]
    api_qd = r.json().get("queue_depth")
    if api_qd != qd:
        return [Finding("INV12", "Metrics mismatch DB", "medium", "GET /admin/metrics",
                        "metrics_drift", f"queue_depth api={api_qd} db={qd}")]
    return []


async def check_cors(c: httpx.AsyncClient) -> list[Finding]:
    r = await c.get("/health", headers={"Origin": "https://evil.example"})
    allow = r.headers.get("access-control-allow-origin")
    if allow == "https://evil.example" or allow == "*":
        return [Finding("INV15", "CORS allows disallowed origin", "critical", "GET /health",
                        "cors_open", f"allow-origin echoed '{allow}' for a disallowed origin")]
    return []


async def check_retention() -> list[Finding]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=365)
    async with AsyncSessionLocal() as s:
        old = (await s.execute(text(
            "SELECT count(*) FROM leads WHERE created_at < :c"
        ), {"c": cutoff})).scalar_one()
    if old:
        return [Finding("INV13", "Old cases not purged", "high", "-", "retention",
                        f"{old} lead(s) older than 1yr remain after cleanup")]
    return []


async def run_all(c: httpx.AsyncClient, admin_token: str, cap: int) -> list[Finding]:
    f: list[Finding] = []
    for coro in (check_caps(cap), check_periods(), check_audit_reached_out(),
                 check_metrics(c, admin_token), check_cors(c), check_retention()):
        f += await coro
    return f
