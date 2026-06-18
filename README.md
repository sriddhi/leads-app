# Leads Management

A full-stack lead-intake platform. Prospects submit an application (name, email, phone, resume)
on a public page; attorneys log in to a dashboard to triage a queue, self- or auto-assign cases,
mark them reached out, and look up case history — with an admin view for capacity, a live audit
trail, and per-attorney time accounting.

---

## Run it locally — one command

You only need **Docker**.

```bash
git clone https://github.com/sriddhi/leads-app.git && cd leads-app
docker compose up --build
```

Then open **http://localhost:3000**. That's the whole setup.

Postgres, the API, the web app, and a local mail inbox all start together. The backend waits for
the database, applies migrations, and seeds itself — including one fully-worked example lead — so
the app is usable the moment it's up. No `.env`, no manual DB steps.

| What | URL |
|---|---|
| Public application form | http://localhost:3000 |
| Attorney / admin login | http://localhost:3000/login |
| API docs (OpenAPI) | http://localhost:8000/docs |
| Email inbox (MailHog) | http://localhost:8025 |

### Sign in

| Role | Email | Password |
|---|---|---|
| Admin | `admin@company.com` | `admin123` |
| Attorney | `attorney@company.com` | `attorney123` |

> Demo credentials only — change them before any real use.

Stop with `Ctrl-C`, or `docker compose down` (`-v` to also drop the database volume).

If port 3000/8000/5432 is taken, override it:

```bash
FRONTEND_PORT=13000 BACKEND_PORT=18000 POSTGRES_PORT=15432 docker compose up --build
```

---

## What it does

- **Public intake** — name, email, phone, required resume (PDF/DOC/DOCX, content-verified), optional message. Hardened: honeypot, rate limiting, idempotency, streaming size cap.
- **Queue & assignment** — FIFO queue, attorney self-assign or least-loaded auto-assign, per-attorney capacity, reassign, and audited reversal.
- **Status flow** — `PENDING → REACHED_OUT`, guarded by optimistic locking (no double-assign, no lost updates).
- **Duplicates** — same email/phone is linked and flagged, never merged; related open cases can be transitioned together.
- **Case history** — prior cases matching phone/email/name within a 6-month window.
- **Admin** — capacity controls, auto-assign toggle, live audit stream, and per-attorney time accounting.
- **Email** — both prospect and attorney are notified on submission (viewable in MailHog locally).

## Stack

FastAPI · PostgreSQL · SQLAlchemy (async) + Alembic · JWT auth · Next.js 14 · Tailwind · Docker Compose.

## Tests

```bash
cd backend && pip install -r requirements.txt -r requirements-dev.txt
pytest                       # unit + integration suite
```

A repeatable load/benchmark recipe also lives in `backend/tests/load/` (see its README); the
latest curated run is in `docs/benchmarks/`.

## Configuration (optional)

Defaults work out of the box. To customize (real email via Resend, a production `SECRET_KEY`,
CORS origins, etc.), copy `backend/.env.example` to `backend/.env` and edit. **Never commit a
real `.env` or any secret** — `.env` files, logs, and local tooling settings are gitignored.

## More docs

- [`DESIGN.md`](DESIGN.md) — architecture and key decisions.
- [`AGENTS.md`](AGENTS.md) — how this was built.

---

> _Built for a candidate interview with Alma — not business code._ Expect deliberate
> prototype-grade tradeoffs (in-memory rate limiting, local file storage, seeded demo data)
> over production hardening.
