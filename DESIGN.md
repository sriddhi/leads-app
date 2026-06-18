# Design Document — Leads Management App

This document explains the architectural decisions behind the leads management application: why each technology was chosen, what tradeoffs were made, and what would change in a production system.

---

## 1. Architecture Overview

```
                    ┌──────────────────────────────────┐
                    │          Browser / Client         │
                    └──────────────┬───────────────────┘
                                   │ HTTP/HTTPS
                    ┌──────────────▼───────────────────┐
                    │       Next.js 14 Frontend         │
                    │  (App Router, React Server        │
                    │   Components + Client Components) │
                    └──────────────┬───────────────────┘
                                   │ REST API (JSON)
                    ┌──────────────▼───────────────────┐
                    │       FastAPI Backend             │
                    │  (async Python, JWT auth,         │
                    │   Pydantic v2 validation)         │
                    └──────┬──────────────┬────────────┘
                           │              │
              ┌────────────▼───┐   ┌──────▼──────────┐
              │  PostgreSQL 16  │   │  Local Filesystem│
              │  (leads, users) │   │  (/uploads)      │
              └────────────────┘   └──────────────────┘
                                          │
                                   ┌──────▼──────────┐
                                   │  Resend Email   │
                                   │  (transactional)│
                                   └─────────────────┘
```

### Two user paths

**Public path (prospect submits a lead)**
1. Prospect visits the root page (`/`)
2. Fills out the lead form (name, email, phone, message, optional file upload)
3. Frontend POST to `POST /api/leads` — no auth required
4. Backend creates the lead record, fires off two emails asynchronously (confirmation to prospect, notification to attorney)
5. Prospect sees a success screen

**Internal path (attorney manages leads)**
1. Attorney navigates to `/login`, submits credentials
2. Frontend POST to `POST /api/auth/login`, receives a JWT
3. JWT stored in localStorage; included as `Authorization: Bearer <token>` on every subsequent request
4. Attorney browses `/dashboard` — paginated lead list with status filter
5. Attorney clicks a lead to view detail and update status via `PATCH /api/leads/{id}/status`

---

## 2. API Design Choices

### Why FastAPI

- **Async-first**: built on Starlette and asyncio — handles concurrent I/O (DB queries, email calls) without blocking
- **Automatic OpenAPI docs**: interactive docs at `/docs` out of the box, useful during development
- **Pydantic v2**: strict request/response validation with type inference; errors are returned as structured JSON automatically
- **Production-ready**: used at scale by many companies; not a toy framework

### RESTful resource design

The lead is the core resource. Endpoints follow REST conventions:

```
POST   /api/leads                  create
GET    /api/leads                  list (with pagination + filter)
GET    /api/leads/{id}             read one
PATCH  /api/leads/{id}/status      update status
GET    /api/leads/{id}/resume      download file
```

### Why PATCH (not PUT) for status updates

`PUT` implies full replacement of the resource. The client would need to send every lead field to avoid accidentally nulling out fields it didn't include. `PATCH` with an explicit `status` field makes the intent clear: this is a controlled state transition, not a full replacement. It also prevents the client from accidentally overwriting other fields.

### Pagination design

List endpoint uses `page` / `page_size` query parameters (offset pagination) rather than cursor pagination. Tradeoffs:

| | Offset pagination | Cursor pagination |
|---|---|---|
| Simplicity | Simple to implement and reason about | More complex |
| Random access | Supports page jumps (e.g. "go to page 5") | Cannot jump to arbitrary page |
| Consistency under inserts | New inserts can shift pages | Stable cursor |
| At expected scale (<10k leads) | Perfectly fine | Unnecessary complexity |

Offset pagination is the right call here. Cursor pagination would be worth revisiting if the leads table grew to millions of rows with high insert frequency.

---

## 3. Database Design

### Why PostgreSQL

- ACID guarantees — lead data must not be lost or partially written
- Native UUID type — used for primary keys
- Timezone-aware timestamps (`TIMESTAMP WITH TIME ZONE`) — avoids the classic "what timezone is this?" bug
- Well-supported by SQLAlchemy and asyncpg

### Why SQLAlchemy 2.x async + asyncpg

- **asyncpg** is the fastest PostgreSQL driver for Python (binary protocol, no libpq dependency)
- **SQLAlchemy 2.x async** wraps asyncpg with a familiar ORM interface; supports `async with session` context managers
- Keeps DB operations non-blocking — the FastAPI event loop is not stalled waiting for queries

### Why Alembic

Schema migrations need to be version-controlled and repeatable. Alembic integrates directly with SQLAlchemy models (`--autogenerate` diffs the ORM against the live DB and generates migration scripts). This means schema evolution is tracked in git alongside the code that depends on it.

### Schema decisions

**UUID primary keys**

```python
id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
```

- Globally unique — safe to generate client-side or in distributed systems without coordination
- No sequential leakage — an attacker cannot enumerate records by incrementing an integer ID
- Slight storage overhead vs. integer PKs, but negligible at this scale

**Server-side timestamp defaults**

```python
created_at: Mapped[datetime] = mapped_column(server_default=func.now())
updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
```

Timestamps are set by the database server, not the application. This avoids clock skew issues if multiple application instances are running.

**Status as VARCHAR with application-level enum**

Status is stored as a plain `VARCHAR` in the database, with the valid values enforced by a Python `Enum` in the application layer. This means:
- Adding a new status (e.g. `on_hold`) requires only a code change, not a database migration
- The database does not enforce the constraint, which is a tradeoff — invalid values could be inserted via direct SQL. Acceptable for this scope.

An alternative is a PostgreSQL `ENUM` type, which enforces the constraint at the DB level but requires a migration to add new values.

---

## 4. Authentication & Security

### JWT Bearer tokens

```
POST /api/auth/login → { access_token, token_type: "bearer" }
```

- **Stateless**: the server does not store session state; any instance can verify any token
- **24-hour expiry**: balances security (short-lived tokens reduce the blast radius of token theft) against UX (attorney does not need to re-login every few hours)
- **HS256 signing**: symmetric signing with `SECRET_KEY`; fast to verify

### Bcrypt password hashing

Passwords are hashed with bcrypt before storage. Bcrypt is intentionally slow (configurable work factor), which means even if the database is leaked, an attacker cannot crack passwords quickly via brute force or precomputed tables.

### Why not OAuth/SSO

Out of scope for this exercise. In a real production deployment, attorney login would use SSO (Google Workspace, Okta, Azure AD) rather than username/password. This eliminates the need to store passwords at all and centralizes identity management. The JWT-based approach used here is a reasonable stand-in that demonstrates the auth flow clearly.

### File upload security

Uploaded resumes go through several checks before being stored:

1. **MIME type validation**: only `application/pdf`, `application/msword`, and `application/vnd.openxmlformats-officedocument.wordprocessingml.document` are accepted
2. **Filename sanitization**: original filename is discarded; files are stored as `{uuid}_{original_name}` to prevent path traversal attacks
3. **Size limit**: files over 20MB are rejected before reading the full stream
4. **Served as static files**: uploaded files are served separately from the API, under `/uploads/`, preventing them from being executed as code

---

## 5. File Storage

Files are stored on the local filesystem in an `uploads/` directory. The backend mounts this directory as a StaticFiles route so uploaded resumes are accessible via URL.

This is appropriate for a single-instance deployment but does not scale horizontally — if you run multiple backend instances, they do not share the same filesystem. In production:

- **S3 or GCS**: store files in object storage; return a pre-signed URL for download
- **CDN**: serve files through a CDN for better performance and reduced backend load
- **Lifecycle policies**: automatically delete files after a retention period if needed

The local filesystem approach was chosen here for simplicity — it requires no external service and keeps the development setup self-contained.

---

## 6. Email Architecture

### Why Resend over SendGrid/Mailgun

- Simpler API surface (a single `send` call with minimal required fields)
- Better developer experience (clear error messages, no IP warming required for low volume)
- Generous free tier (3,000 emails/month, 100/day)
- Modern SDK with first-class Python support

### Fire-and-forget with asyncio.create_task

Emails are sent asynchronously using `asyncio.create_task`:

```python
@router.post("/api/leads")
async def create_lead(...):
    lead = await crud.create_lead(db, ...)
    asyncio.create_task(email_service.send_confirmation(lead))
    asyncio.create_task(email_service.send_attorney_notification(lead))
    return lead
```

This means:
- The HTTP response is returned to the client immediately after the lead is saved
- Email sending happens in the background and does not block the response
- A failed email never causes the lead creation to fail or return an error to the prospect

The tasks are created inside an async FastAPI endpoint, which means there is always a running event loop — the `create_task` call is safe. Each task wraps its body in a `try/except` so a Resend API error is logged but does not propagate and kill the task.

---

## 7. Frontend Design

### Next.js 14 App Router

The frontend uses Next.js 14 with the App Router (introduced in Next.js 13). Key decisions:

- **File-system routing**: routes map directly to directories under `src/app/`
- **Server vs. client components**: pages that only render HTML (no interactivity) are React Server Components by default; components that use hooks (`useState`, `useEffect`) are marked `"use client"`
- **Layout files**: `layout.tsx` files wrap child routes; the dashboard layout enforces authentication for all `/dashboard/*` routes in a single place

### Auth storage

JWT tokens are stored in `localStorage`. This is simple and works well for this exercise. In production, this approach has a known weakness: localStorage is accessible to any JavaScript running on the page, including injected scripts (XSS). The production approach is:

- Store the token in an **httpOnly cookie** (inaccessible to JavaScript)
- Use a **refresh token** (long-lived, httpOnly cookie) to issue new short-lived access tokens
- Implement **token rotation**: refresh tokens are single-use

### Dashboard auth guard

```typescript
// src/app/dashboard/layout.tsx
export default function DashboardLayout({ children }) {
  const token = useAuth(); // redirects to /login if no token
  if (!token) return null;
  return <>{children}</>;
}
```

This pattern centralizes auth enforcement. Any new route added under `/dashboard/` is automatically protected without needing to add auth checks to each page individually.

### Form validation with zod + react-hook-form

- **zod**: schema-first validation library; define the schema once and get TypeScript types inferred automatically
- **react-hook-form**: minimal re-renders, integrates cleanly with zod via `@hookform/resolvers/zod`
- Validation errors are displayed inline next to each field without a round-trip to the server

---

## 8. What Would Change in Production

| Area | Current (exercise) | Production |
|---|---|---|
| Auth token storage | localStorage | httpOnly cookie + refresh token rotation |
| Password auth | bcrypt username/password | SSO (Google/Okta/Azure AD) |
| File storage | Local filesystem | S3/GCS with pre-signed download URLs |
| Rate limiting | None | Rate limit public lead submission endpoint (e.g. 5 req/min per IP) |
| Caching | None | Redis for hot data (e.g. lead counts, recent activity) |
| Background jobs | asyncio.create_task | Celery + Redis or a managed queue (e.g. AWS SQS) for reliability |
| Email retry | No retry on failure | Queue-backed retry with exponential backoff |
| Observability | stdout logs | Structured logging → Datadog/Sentry; uptime monitoring |
| CI/CD | None | GitHub Actions: lint, test, build, deploy on merge to main |
| Secrets | .env file | Secrets manager (AWS Secrets Manager, GCP Secret Manager, HashiCorp Vault) |
| Database | Single instance | Managed PostgreSQL (RDS/Cloud SQL) with read replicas and automated backups |
| HTTPS | None (HTTP) | TLS termination at load balancer; HSTS headers |
| CORS | Permissive | Restrict `allowed_origins` to the production frontend domain only |
