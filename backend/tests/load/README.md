# Load / Flow / Correctness Recipe

A repeatable, configurable test suite that loads the leads platform, exercises every role and
flow under real concurrency, checks correctness invariants, benchmarks itself against an error
budget, and writes a report that turns each failure into a fix prompt. Runs against the live
stack over HTTP. Only email is non-critical (the app's email backend is pluggable; see below).

## Run it
```bash
# 1) bring up the stack with a raised rate limit (load isn't the throttle test) + a test DB
#    (docker compose is easiest — see repo README; or run uvicorn with RATE_LIMIT_MAX high)
# 2) from backend/, with the venv:
LOAD_TEST=1 python -m tests.load.run --profile ci  --base-url http://localhost:8000
LOAD_TEST=1 python -m tests.load.run --profile demo --base-url http://localhost:8000
```
`LOAD_TEST=1` is required (safety). Reset refuses unless the DB name looks like a test/load DB
**or** you pass `--force`.

## Configure (override any profile knob)
```bash
python -m tests.load.run --profile ci \
  --n-leads 1000 --duration 300 --attorneys 75 --cap 10 --process-s 10 \
  --rate-limit-max 1000000 --seed 1337 --error-budget 0.02 \
  --base-url http://localhost:8000 [--skip-pytest] [--force]
```
| Flag | Meaning |
|---|---|
| `--profile` | `ci` (~5-min budget) or `demo` (1000/5-min/75-attorney) base |
| `--n-leads / --duration / --attorneys / --cap / --process-s` | scale knobs (smoke → soak) |
| `--rate-limit-max` | informational; the **server** must be started with this `RATE_LIMIT_MAX` |
| `--seed` | cohort RNG seed (reproducible families/phones/resubmits) |
| `--error-budget` | max unexpected-error rate (default 0.02 = 2%) |
| `--skip-pytest` | skip the correctness suite step |
| `--force` | allow reset on a non-test-named DB |

## What it does (phases)
selftest (guard + plant-a-bug) → safety-guarded reset+seed (75 attorneys, backdated history
cohorts) → pytest correctness suite → load (intake generator + attorney workers + admin monitor
+ authz probes + cap-burst + edge probes) → retention cleanup → state invariants → report.

## Output
`tests/load/reports/run-<ts>.{md,json}` — gates, metrics (intake, throughput, p50/p95, queue
depth, 409s), and per-failure fix prompts (deduped by signature, severity-ranked, sample-capped).
Exit code: 0 clean · 1 low/med · 2 high · 3 critical. JSON carries cross-run counters for trend.

## Gates (pass/fail)
1. correctness pytest green · 2. all invariants hold · 3. error-rate ≤ budget, 0×5xx.

## Email during the run
The recipe runs with the app's email backend as configured. For demo, set `EMAIL_BACKEND=smtp`
with MailHog (docker compose includes it) to see real emails at http://localhost:8025 — no
external provider/keys. `EMAIL_BACKEND=console` (default) just logs; `resend` uses the HTTP API.
