# Runbook

Operational guide: how to run, operate, and troubleshoot the platform. For *why* it's built this
way see [`DESIGN.md`](DESIGN.md); for internals see [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## 1. Quick reference

| | |
|---|---|
| Start (one command) | `docker compose up --build` |
| Web | http://localhost:3000 |
| API + Swagger | http://localhost:8000/docs |
| Mail inbox (MailHog) | http://localhost:8025 |
| Health check | `curl http://localhost:8000/health` |
| Stop | `docker compose down` (add `-v` to drop the DB volume) |
| Logs | `docker compose logs -f backend` |
| Admin login | `admin@company.com` / `admin123` |
| Attorney login | `attorney@company.com` / `attorney123` |

> Demo credentials only. The DB self-migrates and self-seeds on startup — no manual steps.

---

## 2. Start / stop / reset

```bash
# Start (foreground; Ctrl-C to stop)
docker compose up --build

# Start detached
docker compose up -d --build

# Tail logs
docker compose logs -f backend

# Stop, keep data
docker compose down

# Stop AND wipe the database + uploads volume (full reset)
docker compose down -v
```

**Custom ports** (when 3000/8000/5432 are taken):

```bash
FRONTEND_PORT=13100 BACKEND_PORT=18000 POSTGRES_PORT=15432 \
SMTP_PORT=11025 MAILHOG_UI_PORT=8026 \
docker compose -p leadsdemo up -d --build
```

When you override ports, use the **same `-p <project>`** and the same env vars on every
subsequent command (`logs`, `down`, `exec`) so Compose targets the same stack.

---

## 3. Startup sequence (what happens on `up`)

```
postgres starts → healthcheck passes
backend waits for healthy DB
backend runs: alembic upgrade head      → schema at latest migration
backend runs: python seed.py            → users + 1 worked example lead (idempotent)
backend serves uvicorn on :8000
frontend builds + serves on :3000
mailhog serves SMTP :1025 / UI :8025
```

Seeding is **idempotent** — it skips anything that already exists, so restarts are safe.

---

## 4. Configuration

Defaults work with zero config. To customize, copy `backend/.env.example` → `backend/.env`.

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | compose-internal | `postgresql+asyncpg://user:pass@host:port/db` |
| `SECRET_KEY` | `change-me-in-production` | **Set a long random value in prod.** |
| `EMAIL_BACKEND` | `smtp` (compose) | `console` / `smtp` / `resend` |
| `RESEND_API_KEY` | empty | required only for `EMAIL_BACKEND=resend` |
| `ATTORNEY_EMAIL` | `attorney@company.com` | who gets new-lead alerts |
| `RATE_LIMIT_MAX` | `10` | per-IP submissions per window |
| `TRUST_PROXY_HEADERS` | `false` | enable only behind a trusted proxy |
| `UPLOAD_DIR` | `./uploads` | resume storage path |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | JSON array |

> **Never commit a real `.env` or any secret.** `.env`, `*.log`, `uploads/`, load-run reports,
> and local tooling (`.claude/`, `.vscode/`, `.idea/`) are gitignored.

---

## 5. Common operations

**Apply migrations manually / check current revision**
```bash
docker exec leadsdemo-backend-1 alembic current
docker exec leadsdemo-backend-1 alembic upgrade head
docker exec leadsdemo-backend-1 alembic downgrade -1   # roll back one
```

**Re-seed / reset to a clean baseline (keeps schema, replaces data)**
```bash
docker exec leadsdemo-backend-1 python -c "
import asyncio; from sqlalchemy import text
from app.core.database import AsyncSessionLocal; from seed import seed_baseline
async def r():
    async with AsyncSessionLocal() as s:
        await s.execute(text('TRUNCATE leads, lead_state_periods, audit_events, app_settings, users RESTART IDENTITY CASCADE'))
        await s.commit(); await seed_baseline(s)
asyncio.run(r())"
```

**Open a DB shell**
```bash
docker exec -it leadsdemo-postgres-1 psql -U postgres -d leads_db
```

**Run the retention cleanup (purge leads > 1 year)**
```bash
docker exec leadsdemo-backend-1 python scripts/cleanup_old_cases.py
```

**Run the test suites**
```bash
# unit + integration (needs the DB up)
docker exec leadsdemo-backend-1 pytest --ignore=tests/load

# 5-minute load/benchmark (against the running stack, raised rate limit)
RATE_LIMIT_MAX=1000000 docker compose -p leadsdemo up -d backend   # unthrottle first
LOAD_TEST=1 DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:15432/leads_db" \
  BASE_URL="http://localhost:18000" \
  backend/venv/bin/python -m tests.load.run --profile demo --skip-pytest --force
# report → backend/tests/load/reports/run-*.md ; restore the default rate limit after
```

---

## 6. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Bind for 0.0.0.0:5432 failed: port allocated` | Another Postgres on the host | Override ports (§2). |
| Backend restarts / can't reach DB | DB not healthy yet, or wrong `DATABASE_URL` | `docker compose logs postgres`; confirm healthcheck; verify URL host = service name `postgres` inside compose. |
| Login fails for everyone | bcrypt/passlib mismatch (only if deps changed) | Ensure `bcrypt==4.0.1` pinned (passlib 1.7.4 breaks on bcrypt ≥4.1). |
| Public form submit → 429 | Rate limit hit | Expected protection; raise `RATE_LIMIT_MAX` for load/testing only. |
| Submit → 503 "could not record" | `lead_number` collision retries exhausted | Check for a unique-constraint anomaly; numbering is `MAX(seq)+1`. |
| No email in MailHog | `EMAIL_BACKEND` not `smtp`, or MailHog down | Check `docker compose ps mailhog`; confirm `SMTP_HOST=mailhog`. |
| Resume download 401 | Token missing/expired on the link | Re-open from the dashboard (link carries a fresh token). |
| Frontend shows stale copy | Old build cached | `docker compose up -d --build frontend`. |
| Load test wipes demo data | By design — it resets, runs, then restores the baseline | Run against a dedicated DB if you must preserve data; teardown always restores the seed baseline. |

**First moves for any incident**
```bash
docker compose -p leadsdemo ps                 # what's up / healthy
docker compose -p leadsdemo logs --tail=100 backend
curl -s localhost:18000/health                 # API alive?
docker exec leadsdemo-backend-1 alembic current  # schema sane?
```

---

## 7. Backup & restore (Postgres)

```bash
# Backup
docker exec leadsdemo-postgres-1 pg_dump -U postgres leads_db > backup_$(date +%F).sql

# Restore (into a fresh DB)
cat backup_2026-06-18.sql | docker exec -i leadsdemo-postgres-1 psql -U postgres -d leads_db
```

Resume files live in the backend's `UPLOAD_DIR` volume — back that up alongside the DB (in
production these move to S3, where versioning/backup is native).

---

## 8. Incident playbooks

**Database down.** API returns 5xx on DB-touching routes; `/health` may still answer.
→ `docker compose logs postgres`; restart `docker compose -p leadsdemo restart postgres`; the
backend reconnects via the pool. No data loss (transactions roll back atomically).

**Email failing.** Intake is unaffected by design (fire-and-forget never blocks). Check
`docker compose logs backend | grep email`; verify the backend and (for Resend) the API key.
Failed sends are logged and dropped — re-trigger by resubmitting if needed.

**High latency under load.** Expect a tail (p95 ~1 s) when concurrency exceeds the 30-connection
pool. Raise `pool_size`/`max_overflow`, move the load client off-box, or front Postgres with
PgBouncer. This is contention, not a slow query — see `ARCHITECTURE.md` §8.

**A lead looks "stuck."** Inspect its timeline + audit:
```bash
docker exec leadsdemo-backend-1 python -c "import asyncio; ..."  # or query lead_state_periods/audit_events
```
A PENDING-but-unassigned lead is normal (waiting in the queue); an attorney self-assigns or admin
reassigns it.

---

## 9. Health & monitoring signals

- **Liveness**: `GET /health`.
- **Operational metrics**: `GET /api/v1/admin/metrics` (queue depth, oldest wait, in-progress,
  reached-out, per-attorney utilization).
- **Live activity**: `GET /api/v1/admin/audit/stream` (SSE) or the admin dashboard.
- **In production**: ship container logs to CloudWatch; alarm on 5xx rate, p95 latency, queue
  depth, and DB connections-in-use approaching the pool ceiling.
