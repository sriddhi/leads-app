#!/usr/bin/env python
"""Entrypoint: `python -m tests.load.run --profile ci|demo [overrides]`

Flow: selftest → safety-guarded reset+seed → (pytest correctness suite) → load run → cleanup →
invariants → report. Exit code = highest failure severity (0 clean, 1 low/med, 2 high, 3 critical).

Configurable: any profile knob can be overridden (--n-leads/--duration/--attorneys/--cap/
--process-s/--rate-limit-max), plus --seed (cohort RNG), --error-budget, --base-url, --skip-pytest,
--force. So the same recipe scales from a 30s smoke to a multi-minute soak without code changes.
"""

import argparse
import asyncio
import dataclasses
import os
import subprocess
import sys

import httpx

from app.core.database import AsyncSessionLocal
from app.jobs.cleanup import purge_old_cases
from tests.load import invariants, report, selftest
from tests.load.harness import run_load
from tests.load.profiles import get_profile
from tests.load.seed_load import reset_and_seed, restore_clean_state


def _effective_profile(args):
    base = get_profile(args.profile)
    overrides = {k: v for k, v in {
        "n_leads": args.n_leads, "duration_s": args.duration, "attorneys": args.attorneys,
        "cap": args.cap, "process_s": args.process_s, "rate_limit_max": args.rate_limit_max,
    }.items() if v is not None}
    return dataclasses.replace(base, **overrides) if overrides else base


async def _admin_token(base_url: str) -> tuple[httpx.AsyncClient, str]:
    c = httpx.AsyncClient(base_url=base_url, timeout=30.0)
    r = await c.post("/api/v1/auth/login", data={"username": "admin@company.com", "password": "admin123"})
    return c, r.json()["access_token"]


async def main(args) -> int:
    profile = _effective_profile(args)
    base_url = args.base_url
    print(f"• profile: {profile}")

    print("• selftest (guard + plant-a-bug)…")
    ok, issues = await selftest.run()
    if not ok:
        print("SELFTEST FAILED — the recipe cannot be trusted:")
        for i in issues:
            print("  -", i)
        return 3
    print("  selftest OK")

    code = 3
    try:
        print(f"• reset + seed (profile={profile.name})…")
        await reset_and_seed(profile, force=args.force)

        if not args.skip_pytest:
            print("• correctness suite (pytest)…")
            r = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q",
                                "--ignore=tests/load"], cwd=os.getcwd())
            if r.returncode != 0:
                print("CORRECTNESS SUITE FAILED — aborting load run.")
                return 2  # finally still restores a clean state
            # the suite mutates the DB; re-seed for a clean load baseline
            await reset_and_seed(profile, force=args.force)

        print(f"• load run ({profile.n_leads} leads / {profile.duration_s}s / {profile.attorneys} attorneys)…")
        metrics, findings = await run_load(profile, base_url, seed=args.seed)

        print("• retention cleanup…")
        async with AsyncSessionLocal() as s:
            await purge_old_cases(s, older_than_days=365)

        print("• invariants…")
        c, admin = await _admin_token(base_url)
        try:
            findings += await invariants.run_all(c, admin, profile.cap)
        finally:
            await c.aclose()

        rep = report.build(metrics, findings, profile, report.now_ts(), error_budget=args.error_budget)
        path, code = report.write(rep)
        print(f"• report: {path}")
        print(f"• gates: {rep['gates']}  | findings: {len(rep['findings'])}  | exit {code}")
    finally:
        # ALWAYS leave a clean, demo-ready baseline (no leftover test data), unless asked to keep it.
        if args.keep_data:
            print("• --keep-data set: leaving load data in place.")
        else:
            print("• restoring clean state (standard users, no leads, empty uploads)…")
            await restore_clean_state(force=args.force)
            print("  clean state restored.")
    return code


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Leads platform load/benchmark recipe")
    p.add_argument("--profile", default="ci", help="ci | demo (base; override any knob below)")
    p.add_argument("--base-url", default=os.environ.get("BASE_URL", "http://localhost:8000"))
    p.add_argument("--n-leads", type=int, default=None)
    p.add_argument("--duration", type=float, default=None, help="intake window seconds")
    p.add_argument("--attorneys", type=int, default=None)
    p.add_argument("--cap", type=int, default=None, help="per-attorney max open cases")
    p.add_argument("--process-s", type=float, default=None, help="simulated work per case")
    p.add_argument("--rate-limit-max", type=int, default=None)
    p.add_argument("--seed", type=int, default=1337, help="cohort RNG seed (reproducibility)")
    p.add_argument("--error-budget", type=float, default=0.02, help="max unexpected-error rate")
    p.add_argument("--skip-pytest", action="store_true")
    p.add_argument("--keep-data", action="store_true",
                   help="skip the end-of-run clean-state restore (leave load data for inspection)")
    p.add_argument("--force", action="store_true", help="allow reset on a non-test-named DB")
    args = p.parse_args()
    sys.exit(asyncio.run(main(args)))
