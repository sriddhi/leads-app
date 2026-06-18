"""Self-test: the recipe must be trustworthy. (1) the DB-wipe guard refuses a non-test DB;
(2) the invariant engine actually flags planted violations; (3) the report turns a finding into
a ranked fix prompt. Runs FIRST and gates the real run — a green recipe that can't go red is worthless."""

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from tests.load import invariants, seed_load
from tests.load.profiles import CI
from tests.load.report import build
from tests.load.types import Finding


async def run() -> tuple[bool, list[str]]:
    issues: list[str] = []

    # (1) guard refuses a non-test DB (regardless of the real DB name)
    import os
    orig = seed_load._db_name
    os.environ["LOAD_TEST"] = "1"
    seed_load._db_name = lambda: "production_main"  # type: ignore
    try:
        try:
            seed_load.guard(force=False)
            issues.append("SAFETY: guard did NOT refuse a non-test DB")
        except seed_load.SafetyError:
            pass
    finally:
        seed_load._db_name = orig  # type: ignore

    # (2) plant violations and confirm the engine flags them
    async with AsyncSessionLocal() as s:
        await s.execute(text(
            "INSERT INTO users (id,email,hashed_password,full_name,role,max_open_cases,is_active,created_at)"
            " VALUES (gen_random_uuid(),'selftest-over@cap.test','x','Over Cap','ATTORNEY',1,true,now())"
        ))
        uid = (await s.execute(text("SELECT id FROM users WHERE email='selftest-over@cap.test'"))).scalar_one()
        for i in range(2):  # 2 open cases vs cap 1
            await s.execute(text(
                "INSERT INTO leads (id,lead_number,first_name,last_name,email,resume_filename,"
                "resume_original_filename,status,assignee_id,version,created_at,updated_at) VALUES "
                "(gen_random_uuid(),:ln,'S','T','st@x.test','r.pdf','r.pdf','PENDING',:a,1,now(),now())"
            ), {"ln": f"ST-CAP-{i}", "a": uid})
        # a lead with two open periods
        lid = (await s.execute(text(
            "INSERT INTO leads (id,lead_number,first_name,last_name,email,resume_filename,"
            "resume_original_filename,status,version,created_at,updated_at) VALUES "
            "(gen_random_uuid(),'ST-PER','S','T','stp@x.test','r.pdf','r.pdf','PENDING',1,now(),now())"
            " RETURNING id"
        ))).scalar_one()
        for _ in range(2):
            await s.execute(text(
                "INSERT INTO lead_state_periods (id,lead_id,state,entered_at) VALUES "
                "(gen_random_uuid(),:l,'QUEUED',now())"
            ), {"l": lid})
        await s.commit()

    if not await invariants.check_caps(CI.cap):
        issues.append("ENGINE: check_caps did not flag a planted over-cap attorney")
    if not await invariants.check_periods():
        issues.append("ENGINE: check_periods did not flag a planted multi-open-period lead")

    # cleanup planted rows (the real run also truncates, but keep standalone clean)
    async with AsyncSessionLocal() as s:
        await s.execute(text("DELETE FROM lead_state_periods WHERE lead_id IN "
                             "(SELECT id FROM leads WHERE lead_number LIKE 'ST-%')"))
        await s.execute(text("DELETE FROM leads WHERE lead_number LIKE 'ST-%'"))
        await s.execute(text("DELETE FROM users WHERE email='selftest-over@cap.test'"))
        await s.commit()

    # (3) report turns a finding into a ranked fix prompt
    rep = build(_dummy_metrics(), [Finding("INV1", "Double assignee", "critical",
                "POST /leads/{id}/assign", "double_assignee", "planted", ["LEAD-1"])], CI, "selftest")
    if not rep["findings"] or "FIX" not in rep["findings"][0]["fix_prompt"]:
        issues.append("REPORT: did not produce a fix prompt for a finding")
    if rep["highest_severity"] < 3:
        issues.append("REPORT: critical finding not ranked critical")

    return (len(issues) == 0), issues


def _dummy_metrics():
    from tests.load.types import Metrics
    m = Metrics()
    m.intake_attempted = 1
    m.intake_201 = 1
    return m
