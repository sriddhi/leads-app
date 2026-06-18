# Leads Management App

A full-stack leads management application for law firms (or similar professional services). Prospects submit an application on a public page; attorneys log in to a dashboard to view leads and mark them as reached out.

---

## Project Overview

- **Public form**: anyone can submit a lead — `first_name`, `last_name`, `email`, `resume` file (required), and an optional `message`
- **Attorney dashboard**: authenticated, paginated view of all leads, with the ability to transition a lead from `PENDING` to `REACHED_OUT`
- **Email notifications**: on submission, both the prospect and the attorney receive an email (via Resend)
- **File uploads**: resume uploads (PDF/DOC/DOCX, max 20 MB) stored locally and downloadable from the dashboard

> _For a candidate interview with Alma — not business code._
>
> **Built hackathon-style:** this was put together as a fast, exploratory prototype to show
> breadth and product thinking under time pressure — not the steady, incremental way one would
> build and harden a system in everyday production work. Expect prototype-grade tradeoffs
> (in-memory rate limiting, local file storage, seeded demo data) over enterprise rigor.

It also includes an **admin dashboard** (per-attorney capacity, auto-assign toggle,
live audit), **case assignment** (queue + self/auto-assign, reassign), **duplicate
link-&-flag**, **per-state time tracking + attorney-time accounting**, and an optional
**message** field on the public form.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend API | FastAPI (Python 3.11) |
| Database | PostgreSQL 16 |
| ORM | SQLAlchemy 2.x async + asyncpg |
| Migrations | Alembic |
| Auth | JWT (Bearer tokens, 24h expiry) + bcrypt |
| Email | Resend |
| Frontend | Next.js 14 (App Router) |
| UI | Tailwind CSS |
| Form validation | zod + react-hook-form |
| Containerization | Docker Compose |

---

## Local Development (Quickstart)

### Prerequisites

- Python 3.11+
- Node.js 20+
- PostgreSQL 16 running locally (or use Docker Compose — see below)

### 1. Clone the repo

```bash
git clone <repo-url>
cd leads-app
```

### 2. Set up PostgreSQL

Either install PostgreSQL locally and create a database:

```bash
createdb leads_db
```

Or skip this step and use Docker Compose (see the [Docker Compose section](#docker-compose-alternative) below).

### 3. Backend setup

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and fill in the required values:

```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/leads_db
SECRET_KEY=your-secret-key-here
RESEND_API_KEY=re_your_key_here
ATTORNEY_EMAIL=attorney@yourfirm.com
```

Run migrations and seed the database (the initial migration is committed, so you only need `upgrade`):

```bash
alembic upgrade head
python seed.py   # creates attorney@company.com / attorney123
```

Start the backend:

```bash
uvicorn app.main:app --reload --port 8000
```

The API will be available at http://localhost:8000. Interactive docs at http://localhost:8000/docs.

### 4. Frontend setup

Open a new terminal:

```bash
cd frontend
npm install
cp .env.example .env.local
# .env.local already contains NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
```

### 5. Open the app

Visit http://localhost:3000

- Public lead form: http://localhost:3000
- Attorney login: http://localhost:3000/login
- Dashboard: http://localhost:3000/dashboard

---

## Docker Compose (Alternative)

For a fully containerized setup (no local PostgreSQL, Python, or `.env` required) — this is the
**clone-and-run** path:

```bash
git clone <repo-url> && cd leads-app
docker compose up --build
# → http://localhost:3000  (API: http://localhost:8000/docs)
```

That's it. The backend container **auto-applies migrations and seeds** (admin + attorneys)
before serving — no manual steps. Host ports are overridable to avoid collisions, e.g.:

```bash
POSTGRES_PORT=15432 BACKEND_PORT=18000 FRONTEND_PORT=13000 docker compose up --build
```

All three services (postgres, backend, frontend) start; the backend waits for postgres healthy.

To stop:
```bash
docker compose down
# Add -v to also remove the postgres data volume:
docker compose down -v
```

---

## Environment Variables

### Backend (`backend/.env`)

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string. Format: `postgresql+asyncpg://user:pass@host:port/dbname` |
| `SECRET_KEY` | Yes | Secret key for signing JWT tokens. Use a long random string in production. |
| `RESEND_API_KEY` | Yes* | API key from resend.com. Without it, email sends will log errors but the app continues to work. |
| `ATTORNEY_EMAIL` | Yes | The attorney's email address — receives notification when a new lead is submitted. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | JWT expiry in minutes. Defaults to `1440` (24 hours). |
| `UPLOAD_DIR` | No | Directory for uploaded files. Defaults to `./uploads`. |
| `CORS_ORIGINS` | No | JSON array of allowed frontend origins. Defaults to `["http://localhost:3000"]`. |

> Max upload size (20 MB) and the accepted MIME types (PDF/DOC/DOCX) are enforced in code (`app/services/storage.py`), not via env vars.

### Frontend (`frontend/.env.local`)

| Variable | Required | Description |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | Yes | Base URL of the FastAPI backend. Defaults to `http://localhost:8000`. |

---

## Default Credentials

The `seed.py` script creates an admin and three attorney accounts:

| Role | Email | Password |
|---|---|---|
| ADMIN | `admin@company.com` | `admin123` |
| ATTORNEY | `attorney@company.com` | `attorney123` |
| ATTORNEY | `attorney2@company.com` | `attorney123` |
| ATTORNEY | `attorney3@company.com` | `attorney123` |

Change these credentials in production.

---

## API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/v1/leads` | None | Submit a new lead (public form, `multipart/form-data`) |
| `GET` | `/api/v1/leads` | Bearer | List all leads, paginated (newest first) |
| `GET` | `/api/v1/leads/{id}` | Bearer | Get a single lead by ID |
| `PATCH` | `/api/v1/leads/{id}/status` | Bearer | Transition a lead's status (`PENDING` → `REACHED_OUT`) |
| `POST` | `/api/v1/auth/login` | None | Authenticate (form fields `username`, `password`); returns a JWT |
| `GET` | `/api/v1/auth/me` | Bearer | Get the current authenticated user |
| `GET` | `/uploads/{filename}` | None | Download an uploaded resume (static file serving) |
| `GET` | `/health` | None | Health check |

Interactive OpenAPI docs are available at `http://localhost:8000/docs`.

### Lead statuses

`PENDING` → `REACHED_OUT`

A lead starts as `PENDING` on submission. An attorney marks it `REACHED_OUT` after making contact. The transition is one-way and enforced server-side (re-transitioning returns `422`).

### Pagination

The list endpoint accepts `?page=1&page_size=20` query parameters (`page_size` max 100) and returns `{ items, total, page, page_size, pages }`.

---

## Email Setup (Resend)

The app uses [Resend](https://resend.com) to send transactional emails.

1. Sign up at https://resend.com (free tier: 3,000 emails/month)
2. Go to API Keys → Create API Key
3. Copy the key and add it to `backend/.env` as `RESEND_API_KEY=re_...`
4. Set `ATTORNEY_EMAIL` to the inbox that should receive lead notifications

If `RESEND_API_KEY` is not set or is invalid, the app logs the error and continues — lead creation succeeds, email just fails silently.

---

## Project Structure

```
leads-app/
├── docker-compose.yml
├── README.md
├── DESIGN.md
├── AGENTS.md
├── .gitignore
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── .env.example
│   ├── seed.py                     # creates the default attorney user
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/
│   ├── uploads/                    # uploaded files (gitignored)
│   └── app/
│       ├── main.py                 # app factory, CORS, static mount, lifespan
│       ├── core/
│       │   ├── config.py           # settings (pydantic-settings)
│       │   ├── database.py         # async engine + session
│       │   └── security.py         # JWT + bcrypt helpers
│       ├── models/                 # SQLAlchemy ORM models (base, lead, user)
│       ├── schemas/                # Pydantic schemas (lead, user, token)
│       ├── crud/                   # DB operations (leads, users)
│       ├── services/
│       │   ├── email.py            # Resend email service
│       │   └── storage.py          # file validation + storage
│       └── api/
│           └── v1/
│               ├── router.py
│               └── endpoints/
│                   ├── leads.py    # /api/v1/leads routes
│                   └── auth.py     # /api/v1/auth routes
│
└── frontend/
    ├── Dockerfile
    ├── package.json
    ├── next.config.mjs             # output: 'standalone'
    ├── tailwind.config.ts
    ├── .env.example
    └── src/
        ├── app/
        │   ├── layout.tsx          # root layout
        │   ├── page.tsx            # public lead form (/)
        │   ├── login/
        │   │   └── page.tsx        # attorney login
        │   └── dashboard/
        │       ├── layout.tsx      # auth guard + navbar
        │       ├── page.tsx        # leads list
        │       └── [id]/
        │           └── page.tsx    # lead detail
        ├── components/
        │   ├── LeadForm.tsx
        │   ├── LeadsTable.tsx
        │   ├── StatusBadge.tsx
        │   └── ui/                 # Button, Input, Badge
        ├── lib/
        │   ├── api.ts              # typed fetch wrappers
        │   └── auth.ts             # token storage helpers
        └── types/
            └── index.ts            # shared TypeScript types
```
