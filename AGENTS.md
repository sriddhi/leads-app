# Coding-Agent Usage

How AI coding agents were used to build this platform — what was delegated, what stayed a human
decision, and one place the agent was subtly wrong and how it was caught.

---

## Writeup (the half-page)

**Tools.** Claude Code was the primary agent — used as an orchestrator, not an autocomplete. It
held the design context, generated implementation, ran the stack, and drove fixes. For
independent slices it fanned out subagents (backend, frontend, infrastructure/docs) that ran in
parallel once their specs were pinned down.

**What I delegated.** The *implementation* — given a precise spec. SQLAlchemy models and
migrations, Pydantic schemas, CRUD, the FastAPI endpoints, the service modules (assignment,
identity, timeline, audit, storage, email, rate-limit), the full Next.js UI and typed API client,
the Dockerfiles and compose, and first drafts of the docs and tests. Agents are excellent at
*how* once the *what* is exact, and they emit idiomatic boilerplate far faster than hand-writing.

**What I owned by hand.** The decisions, which are the actual engineering: the data model
(append-only audit + interval state-periods to *justify attorney time*; link-and-flag dedup that
never merges families), optimistic locking as the concurrency strategy, the `PENDING → REACHED_OUT`
state machine, the public-boundary threat model (honeypot, rate limit, idempotency, magic-byte
file validation, minimal receipt), and the AWS-portability seams. I also wrote the *specs* the
agents executed against — exact field names, paths, status codes, invariants — and I did the
verification: reading every generated file, then **running the system for real** (Postgres,
migrations, seed, every endpoint, a browser pass, and a 1000-lead/75-attorney load harness).

**Where the agent was subtly wrong.** The backend agent pinned `passlib[bcrypt]==1.7.4` but left
`bcrypt` unpinned. It type-checked and reviewed clean — `CryptContext` is the textbook way to
hash passwords. But `pip` resolved `bcrypt` to 5.x, and passlib 1.7.4 runs an import-time probe
that hashes a >72-byte string; modern bcrypt now *raises* `ValueError: password cannot be longer
than 72 bytes` instead of truncating. Result: every password hash threw, so seeding and **all
logins failed**. Reading the code never reveals this — the bug lives in the *interaction* between
two individually-reasonable versions. It surfaced the moment I ran `python seed.py` against real
Postgres. **Fix:** pin `bcrypt==4.0.1`. (A second class of issue — a `next_lead_number` that used
`count()+1` and collided after retention deletes left gaps — was caught the same way, by the load
harness, and fixed to `MAX(seq)+1` with a regression test.) The lesson that shaped my process:
agent output must be *executed*, not just reviewed.

---

## Representative prompts (excerpts)

Precision is what makes agent output usable. The specs read like a contract, not a wish.

**Backend spec (excerpt):**
```
Build an async FastAPI backend. Public POST /api/v1/leads (multipart:
first_name, last_name, email, phone?, message?, resume file) → minimal receipt
ONLY (lead_number, status) — never leak internal fields.

leads: id uuid pk, lead_number unique (LEAD-000123), normalized_email + 
normalized_phone (indexed), status PENDING|REACHED_OUT, assignee_id fk,
version int (optimistic lock), idempotency_key unique, duplicate_of fk,
is_potential_duplicate. created/updated_at tz-aware.

Concurrency: assign/status writes check client version → 409 on mismatch.
Audit: append-only audit_events (before/after JSONB); NO update/delete path.
Time: lead_state_periods (QUEUED|ASSIGNED|REACHED_OUT) with entered/exited_at,
exactly one open period per lead — this powers per-attorney time accounting.
Dedup: link & flag on normalized_email; NEVER merge.
Security: JWT HS256 24h, bcrypt via passlib (PIN bcrypt==4.0.1), upload
validated by MAGIC BYTES not extension, streamed size cap.
```

**Refinement prompt (concurrency invariant):**
```
Make double-assignment impossible, not unlikely. Two attorneys assigning the
same queued lead at the same version must end with exactly one owner and a 409
for the other — assert this with a real concurrent integration test, not a mock.
```

**Verification prompt (run it, don't trust it):**
```
Bring up Postgres in Docker, migrate, seed, then exercise every endpoint and a
browser pass. Report what actually broke at runtime — not what looks correct.
```

The frontend spec was equally explicit: every route, the uncontrolled-form submit pattern
(robust to autofill), the auth-guard, and the exact shape of each API call.

---

## Attribution

This repository is **co-created**: an engineer-owned design and spec, implemented with Claude
Code, and verified together by running it. The table records the *mode* of collaboration per
area — not a claim that any part was untouched by review.

| Area | Collaboration mode |
|---|---|
| Architecture, data model, threat model, state machine, AWS seams | **Engineer-decided**, agent-sounded-board |
| Agent specs / invariants / acceptance criteria | **Engineer-authored** |
| Backend app code (models, services, endpoints, crud, migrations) | Agent-generated from spec, **engineer-reviewed & run** |
| Frontend app code (pages, components, API client) | Agent-generated from spec, **engineer-reviewed & run** |
| Tests (unit, integration, load/benchmark recipe) | Co-authored; invariants engineer-specified |
| Infra (Dockerfiles, compose), docs (README, DESIGN, this file) | Agent-drafted, **engineer-edited for accuracy** |
| `bcrypt==4.0.1` pin, `next_lead_number` MAX+1, other runtime fixes | **Engineer-fixed** after running the system |

Every commit carries a `Co-Authored-By` trailer reflecting this shared authorship. Verification —
the full Dockerized stack plus the load/benchmark run — is the line that separates "looks
correct" from "is correct," and it was done by hand on every change.
