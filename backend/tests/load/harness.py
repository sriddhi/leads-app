"""Async load harness: drives intake + attorney workers + admin monitor + authz probes +
cap-burst + edge probes against the running stack over HTTP. Returns Metrics + Findings."""

import asyncio
import io
import time

import httpx

from tests.load.cohorts import build_intake
from tests.load.profiles import Profile
from tests.load.seed_load import LOAD_PASSWORD, load_attorney_email
from tests.load.types import Finding, Metrics

PDF = b"%PDF-1.4 load-test resume"


def _resume() -> dict:
    return {"resume": ("cv.pdf", io.BytesIO(PDF), "application/pdf")}


async def _login(c: httpx.AsyncClient, email: str, pw: str) -> str | None:
    r = await c.post("/api/v1/auth/login", data={"username": email, "password": pw})
    return r.json()["access_token"] if r.status_code == 200 else None


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


async def run_load(profile: Profile, base_url: str, seed: int = 1337) -> tuple[Metrics, list[Finding]]:
    m = Metrics()
    findings: list[Finding] = []
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=100)
    started = time.monotonic()
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0, limits=limits) as c:
        admin = await _login(c, "admin@company.com", "admin123")
        if not admin:
            findings.append(Finding("SETUP", "Admin login failed", "critical",
                                    "POST /auth/login", "no_admin", "could not log in as admin"))
            return m, findings
        # pull model for the main run
        await c.put("/api/v1/admin/settings/auto-assign", json={"enabled": False}, headers=_hdr(admin))

        worker_tokens = await asyncio.gather(
            *[_login(c, load_attorney_email(i), LOAD_PASSWORD) for i in range(1, profile.attorneys + 1)]
        )
        worker_tokens = [t for t in worker_tokens if t]

        deadline = started + profile.duration_s
        specs = build_intake(profile.n_leads, seed=seed)

        async def intake() -> None:
            gap = profile.duration_s / max(1, profile.n_leads)
            for spec in specs:
                t0 = time.monotonic()
                try:
                    r = await c.post("/api/v1/leads", data={
                        "first_name": spec["first_name"], "last_name": spec["last_name"],
                        "email": spec["email"], "phone": spec["phone"],
                    }, files=_resume())
                    m.latencies_ms.append((time.monotonic() - t0) * 1000)
                    m.intake_attempted += 1
                    sc = r.status_code
                    if sc == 201:
                        m.intake_201 += 1
                    elif sc == 429:
                        m.intake_429 += 1
                    elif sc == 422:
                        m.intake_422 += 1
                    elif sc >= 500:
                        m.intake_5xx += 1
                    else:
                        m.other_unexpected += 1
                except Exception:
                    m.intake_attempted += 1
                    m.other_unexpected += 1
                await asyncio.sleep(gap)

        async def worker(tok: str) -> None:
            h = _hdr(tok)
            while time.monotonic() < deadline:
                try:
                    q = await c.get("/api/v1/leads/queue", headers=h)
                    items = q.json() if q.status_code == 200 else []
                    if not items:
                        await asyncio.sleep(0.2)
                        continue
                    lead = items[0]
                    a = await c.post(f"/api/v1/leads/{lead['id']}/assign",
                                     json={"version": lead["version"]}, headers=h)
                    if a.status_code == 409:
                        m.conflict_409 += 1
                        continue
                    if a.status_code != 200:
                        continue
                    await asyncio.sleep(profile.process_s)
                    d = await c.get(f"/api/v1/leads/{lead['id']}", headers=h)
                    ver = d.json()["version"] if d.status_code == 200 else lead["version"] + 1
                    s = await c.patch(f"/api/v1/leads/{lead['id']}/status",
                                      json={"status": "REACHED_OUT", "version": ver}, headers=h)
                    if s.status_code == 200:
                        m.reached_out += 1
                    elif s.status_code == 409:
                        m.conflict_409 += 1
                except Exception:
                    await asyncio.sleep(0.1)

        async def monitor() -> None:
            while time.monotonic() < deadline:
                try:
                    mt = await c.get("/api/v1/admin/metrics", headers=_hdr(admin))
                    if mt.status_code == 200:
                        m.queue_depth_samples.append(mt.json().get("queue_depth", 0))
                except Exception:
                    pass
                await asyncio.sleep(3.0)

        await asyncio.gather(intake(), monitor(), *[worker(t) for t in worker_tokens])

        # --- targeted checks after the load window ---
        findings += await _authz_probes(c)
        findings += await _edge_probes(c, admin)
        findings += await _cap_burst(c, admin, profile)

    m.duration_s = round(time.monotonic() - started, 1)
    return m, findings


async def _authz_probes(c: httpx.AsyncClient) -> list[Finding]:
    f: list[Finding] = []
    r = await c.get("/api/v1/leads/queue")
    if r.status_code != 401:
        f.append(Finding("INV10", "Unauth internal access", "critical", "GET /leads/queue",
                         "no_401", f"expected 401, got {r.status_code}"))
    att = await _login(c, "attorney@company.com", "attorney123")
    if att:
        r = await c.get("/api/v1/admin/metrics", headers=_hdr(att))
        if r.status_code != 403:
            f.append(Finding("INV10", "Wrong-role admin access", "critical", "GET /admin/metrics",
                             "no_403", f"attorney expected 403, got {r.status_code}"))
    return f


async def _edge_probes(c: httpx.AsyncClient, admin: str) -> list[Finding]:
    f: list[Finding] = []
    # honeypot
    r = await c.post("/api/v1/leads", data={"first_name": "S", "last_name": "B",
        "email": "spam@load.test", "company_website": "x"}, files=_resume())
    if r.status_code != 202:
        f.append(Finding("INV11", "Honeypot not blocked", "high", "POST /leads", "honeypot",
                         f"expected 202, got {r.status_code}"))
    # invalid email
    r = await c.post("/api/v1/leads", data={"first_name": "S", "last_name": "B",
        "email": "not-an-email"}, files=_resume())
    if r.status_code != 422:
        f.append(Finding("INV11", "Invalid email accepted", "high", "POST /leads", "bad_email",
                         f"expected 422, got {r.status_code}"))
    # contract stability: public receipt must expose only the pinned key set
    r = await c.post("/api/v1/leads", data={"first_name": "C", "last_name": "T",
        "email": "contract@load.test", "phone": "5551234567"}, files=_resume())
    if r.status_code == 201:
        leaked = set(r.json()) - {"lead_number", "status", "message"}
        if leaked:
            f.append(Finding("INV14", "Public receipt leaks fields", "critical", "POST /leads",
                             "contract_drift", f"unexpected keys: {sorted(leaked)}", sorted(leaked)))
    # injection escaped (verify via admin lookup)
    r = await c.post("/api/v1/leads", data={"first_name": "<script>alert(1)</script>",
        "last_name": "X", "email": "inj@load.test"}, files=_resume())
    if r.status_code == 201:
        ln = r.json()["lead_number"]
        d = await c.get(f"/api/v1/leads/by-number/{ln}", headers=_hdr(admin))
        if d.status_code == 200 and "<script>" in d.json().get("first_name", ""):
            f.append(Finding("INV11", "Injection not escaped", "critical", "POST /leads",
                             "xss", "raw <script> stored", [ln]))
    return f


async def _cap_burst(c: httpx.AsyncClient, admin: str, profile: Profile) -> list[Finding]:
    """Drive one fresh attorney to exactly cap, assert (cap+1)->409, freeing one admits exactly one."""
    f: list[Finding] = []
    tok = await _login(c, load_attorney_email(profile.attorneys), LOAD_PASSWORD)
    if not tok:
        return f
    h = _hdr(tok)
    # create cap+2 fresh queued leads (auto-assign already off)
    lns = []
    for i in range(profile.cap + 2):
        r = await c.post("/api/v1/leads", data={"first_name": f"Burst{i}", "last_name": "Cap",
            "email": f"burst{i}@load.test", "phone": "5559990000"}, files=_resume())
        if r.status_code == 201:
            lns.append(r.json()["lead_number"])
    ids = []
    for ln in lns:
        d = await c.get(f"/api/v1/leads/by-number/{ln}", headers=h)
        if d.status_code == 200:
            ids.append((d.json()["id"], d.json()["version"]))
    ok = 0
    for lead_id, ver in ids:
        r = await c.post(f"/api/v1/leads/{lead_id}/assign", json={"version": ver}, headers=h)
        if r.status_code == 200:
            ok += 1
        elif r.status_code == 409 and ok >= profile.cap:
            break  # hit the cap (expected)
    if ok != profile.cap:
        f.append(Finding("INV2", "Capacity boundary wrong", "critical", "POST /leads/{id}/assign",
                         "cap_off_by_one", f"expected exactly {profile.cap} successful self-assigns, got {ok}"))
    return f
