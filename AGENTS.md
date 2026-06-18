# Agent Usage — Leads Management App

How AI coding agents were used to build this application: what was delegated versus
decided by hand, and where agent output was wrong and had to be corrected.

---

## Tools Used

- **Claude Code** as the primary orchestrator — the interactive agent that designed the
  system, wrote the subagent specs, reviewed output, ran the app, and fixed bugs.
- **Subagents** (spawned via the Agent tool) for parallel implementation:
  - one built the **FastAPI backend**,
  - one built the **Next.js frontend**,
  - one built the **infrastructure + documentation** (Docker, README, DESIGN, this file).
- The three subagents ran **concurrently** once the specs were finalized, which is where
  the parallelism paid off — three independent, well-bounded slices of the repo.

---

## What Was Delegated vs. Written / Decided by Hand

### Delegated to agents
- Full FastAPI backend: ORM models, Pydantic schemas, CRUD, JWT/bcrypt security helpers,
  Resend email service, file-upload storage, API routers, Alembic config, seed script.
- Full Next.js frontend: all pages, components, the typed API client, auth helpers,
  Tailwind/Next config.
- Infrastructure: `docker-compose.yml`, both `Dockerfile`s.
- First drafts of `README.md`, `DESIGN.md`, and this document.

### Written / decided by hand (engineer judgment)
- **System design**: the endpoint surface, the lead schema (which fields, which required),
  the `PENDING → REACHED_OUT` state machine, the auth strategy, choice of Resend for email,
  local-disk storage for resumes.
- **The subagent prompts** — exact field names, endpoint paths, HTTP status codes,
  file structure, security constraints. This is the real work: the specs are the design.
- **Verification and fixes** — reading every generated file, then actually *running* the
  stack (Postgres in Docker, migrations, seed, uvicorn, `curl` of every endpoint, and a
  real browser pass over the UI) and fixing what broke. The bugs below were all caught this
  way, not by reading alone.

---

## Why This Split

Agents are excellent at "how" given a precise "what." With exact field names, paths, status
codes, and behavior spelled out, an agent emits correct, idiomatic boilerplate faster than
hand-writing it. What they can't do is decide *what* to build or notice when a plausible-
looking choice is subtly wrong — that's where the human review and the run-it-for-real step
earn their keep.

---

## Where the Agents Produced Wrong Code

Four issues surfaced. The first is the most instructive — it passed type-checking and code
review and only failed when the app was actually run.

### 1. The subtle one: `passlib` + `bcrypt` version incompatibility (runtime-only)

The backend agent pinned `passlib[bcrypt]==1.7.4` in `requirements.txt` but left `bcrypt`
**unpinned**. Reading the code, everything looks correct — `passlib`'s `CryptContext` is the
textbook way to hash passwords. It type-checks. It reviews clean.

But `pip` resolves the unpinned dependency to the latest `bcrypt` (5.0.0), and `passlib`
1.7.4 — last released in 2020 — runs an internal version-detection probe on import that
hashes a **>72-byte** test string. Older `bcrypt` silently truncated; `bcrypt` 5.x now
**raises** `ValueError: password cannot be longer than 72 bytes`. The result: *all* password
hashing throws, so the seed script and every login fail.

**How it was caught:** not by review — by running `python seed.py` against a real Postgres,
which blew up with the traceback inside `passlib/handlers/bcrypt.py`.

**The fix** (`backend/requirements.txt`): pin `bcrypt` to the last compatible release.

```
passlib[bcrypt]==1.7.4
bcrypt==4.0.1   # passlib 1.7.4 breaks on bcrypt>=4.1 (its >72-byte probe now raises)
```

This is the canonical "subtly bad agent code": individually each pin is reasonable, the bug
lives in the *interaction*, and it's invisible until execution.

### 2. Missing Alembic template — migrations couldn't be generated

The backend agent wrote `alembic/env.py` and `alembic.ini` but never created
`alembic/script.py.mako`, the template Alembic reads to render new migration files.
`alembic revision --autogenerate` died with
`FileNotFoundError: 'alembic/script.py.mako'`. Caught when running the migration step;
fixed by adding the standard template file.

### 3. Cross-agent inconsistency — Next.js standalone output

The docs agent wrote a `frontend/Dockerfile` using the Next.js **standalone** output
(`COPY .next/standalone`), but the frontend agent's `next.config` didn't set
`output: 'standalone'`. Two agents, two files, individually fine — but the Docker build
would fail because `.next/standalone` is never produced. Fixed by adding
`output: 'standalone'` to the Next config. (The frontend agent also correctly noted that
Next 14 doesn't support a `.ts` config and emitted `next.config.mjs`.)

### 4. Stale-value log line

In `leads.py`, the status-transition handler logged `old → new` *after* mutating the
object, so it would have logged `REACHED_OUT → REACHED_OUT` instead of
`PENDING → REACHED_OUT`. Cosmetic, but wrong; fixed by capturing `old_status` before the
update.

---

## Representative Agent Prompt (excerpt)

The backend subagent prompt, abbreviated — note the precision, which is what makes the
output usable:

```
Build a production-quality FastAPI backend ... endpoints:
- POST /api/v1/leads        — public; multipart: first_name, last_name, email, resume file
- GET  /api/v1/leads        — protected; paginated list (JWT)
- GET  /api/v1/leads/{id}   — protected; single lead
- PATCH /api/v1/leads/{id}/status — protected; PENDING -> REACHED_OUT
- POST /api/v1/auth/login   — returns JWT given email+password
- GET  /api/v1/auth/me      — current user

leads table: id UUID pk, first_name, last_name, email, resume_filename,
  resume_original_filename, status (PENDING|REACHED_OUT) default PENDING,
  created_at, updated_at  (timezone-aware)

Security: JWT HS256 24h, bcrypt via passlib, file upload MIME-validated
  (pdf/doc/docx only), 10MB max, UUID-prefixed filenames.
Email: Resend via httpx, fire-and-forget, fault-tolerant (log, never raise).
On lead submit, email BOTH the prospect and ATTORNEY_EMAIL.
```

The frontend prompt was equally explicit: every page path, every component, the exact
shape of each API call, the zod validation rules, and the auth-guard pattern.

---

## Attribution

| Area | Author |
|---|---|
| `backend/**` (app code) | Agent-generated from spec |
| `frontend/**` (app code) | Agent-generated from spec |
| `alembic/script.py.mako` | **Hand-added** (agent omitted it) |
| `requirements.txt` bcrypt pin | **Hand-fixed** after runtime failure |
| `next.config.mjs` standalone flag | **Hand-fixed** (cross-agent inconsistency) |
| `leads.py` log-order fix | **Hand-fixed** |
| `docker-compose.yml`, `Dockerfile`s | Agent-generated |
| `README.md`, `DESIGN.md`, `AGENTS.md` | Agent-drafted, **hand-edited for accuracy** |
| System/architecture decisions, all prompts | Hand-written by engineer |

> Verification was done by running the full stack locally (Dockerized Postgres → Alembic →
> seed → uvicorn), exercising every endpoint with `curl`, and driving the UI in a real
> browser (public form render, login over CORS, dashboard data render). All four bugs above
> were fixed and re-verified.
