# Benchmark — Run 1

_For a candidate interview with Alma — not business code._

A full load / flow / correctness run of the leads platform, executed by the repeatable test
recipe (`backend/tests/load/run_5min.sh`). This is the baseline ("Run 1") for tracking the
system over time.

| | |
|---|---|
| **Date** | 2026-06-18 |
| **Profile** | `demo` — 1000 leads / 5-min intake / 75 attorneys / cap 10 / 10s processing |
| **Target** | live stack over HTTP (FastAPI + Postgres + Next.js + MailHog) |
| **Email** | real SMTP → MailHog (no external provider) |
| **Result** | ✅ **PASS** (exit 0, 0 findings) |

## Gates

| Gate | Threshold | Result |
|---|---|---|
| Correctness invariants | all hold | ✅ **PASS** (0 findings) |
| Unexpected error rate | ≤ 2% | ✅ **PASS** — **0 / 1000 = 0.00%** |
| Server errors (5xx) | 0 | ✅ **PASS** (0) |

## Metrics

| Metric | Value |
|---|---|
| Leads submitted → created | **1000 / 1000** |
| Rejected (429 / 422 / 5xx) | 0 / 0 / 0 |
| Cases reached out | 594 |
| Optimistic-lock conflicts (409) | 2039 _(expected; all handled — see notes)_ |
| Intake latency p50 / p95 | **25.9 ms / 625.9 ms** |
| Queue depth max / end | 1 / **0** (fully drained) |
| Run duration (incl. setup/teardown) | 434 s |
| **Emails delivered (MailHog)** | **2028** _(prospect + attorney per lead)_ |

## What was verified (all green)

- **Intake at scale** — 1000 submissions, 0 errors, 0 5xx.
- **Concurrency** — 75 attorneys self-assigning; optimistic locking correctly rejected stale
  writes (2039× `409`), single-assignee held, no data corruption.
- **Capacity** — per-attorney cap never exceeded; boundary (exactly `cap`) checked.
- **Dedup / families / same-phone** — every submission a distinct case; matches linked, never merged.
- **State + audit + time-tracking** — one open period per lead; durations ≥ 0; every transition
  audited (append-only); metrics matched DB ground truth.
- **Security** — unauth → 401, wrong-role → 403, public receipt leaked no internal fields, CORS
  rejected a disallowed origin, injection stored escaped, honeypot → 202.
- **Retention** — cases older than 1 year purged; recent cases untouched.
- **Email under load** — **2028 emails** actually delivered via SMTP to MailHog (proves the real
  send path, not just a unit mock).
- **Self-test** — the recipe's DB-wipe guard refuses a non-test DB and the invariant engine
  flags planted violations, so a green run is trustworthy.

## Notes

- **`reached_out` = 594 / 1000** is *not* a failure (all correctness gates passed). The queue
  fully drained (all 1000 assigned), but with 75 workers polling a shallow, intake-paced queue,
  ~40% were assigned-but-not-yet-marked when the 5-min window closed. Reducing 409 contention
  (batched pulls / back-off) would raise this in a future run — a throughput tuning, not a defect.
- Latency/throughput numbers are hardware-sensitive; compare against this baseline on like
  hardware. The machine-readable copy lives in `backend/tests/load/reports/run-*.json`.

## Reproduce

```bash
# 1) bring the stack up with a raised rate limit + email→MailHog
RATE_LIMIT_MAX=1000000 docker compose up --build -d
# 2) run the 5-minute bundle (point DATABASE_URL at the same DB the backend uses)
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/leads_db \
BASE_URL=http://localhost:8000 \
backend/tests/load/run_5min.sh
# → report in backend/tests/load/reports/run-<ts>.md ; emails at http://localhost:8025
```
