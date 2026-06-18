"""Run report: dedup findings by signature, rank by severity, cap samples, emit md + json,
and turn each failure into a ready-to-paste fix prompt. Exit severity drives the process code."""

import glob
import json
import os
from collections import defaultdict
from datetime import datetime, timezone

from tests.load.profiles import Profile
from tests.load.types import SEVERITY_ORDER, Finding, Metrics

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")
MAX_SAMPLES_PER_SIG = 5
ERROR_BUDGET = 0.02  # ≤ 2%


def _prior_counts() -> dict:
    files = sorted(glob.glob(os.path.join(REPORTS_DIR, "run-*.json")))
    if not files:
        return {}
    try:
        data = json.load(open(files[-1]))
        return {f["signature"]: f for f in data.get("findings", [])}
    except Exception:
        return {}


def _fix_prompt(f: Finding, count: int) -> str:
    return (
        f"FIX — {f.invariant_id} ({f.title}) failed ×{count} at `{f.endpoint}`. {f.detail}. "
        f"Samples: {f.samples[:MAX_SAMPLES_PER_SIG] or 'n/a'}. "
        f"Investigate the handler/logic behind `{f.endpoint}` in backend/app/, fix the root cause "
        f"(do not weaken the check), and add a regression test in backend/tests/."
    )


def build(metrics: Metrics, findings: list[Finding], profile: Profile, ts: str,
          error_budget: float = ERROR_BUDGET) -> dict:
    # dedup by signature
    groups: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        groups[f.signature].append(f)
    prior = _prior_counts()

    deduped = []
    for sig, items in groups.items():
        rep = items[0]
        merged_samples = []
        for it in items:
            merged_samples += it.samples
        runs_seen = (prior.get(sig, {}).get("runs_seen", 0) + 1)
        first_seen = prior.get(sig, {}).get("first_seen", ts)
        deduped.append({
            "signature": sig, "invariant_id": rep.invariant_id, "title": rep.title,
            "severity": rep.severity, "endpoint": rep.endpoint, "error_class": rep.error_class,
            "count": len(items), "samples": merged_samples[:MAX_SAMPLES_PER_SIG],
            "first_seen": first_seen, "runs_seen": runs_seen,
            "fix_prompt": _fix_prompt(rep, len(items)),
        })
    deduped.sort(key=lambda d: SEVERITY_ORDER.get(d["severity"], 0), reverse=True)

    # gates
    error_rate = metrics.error_rate
    gates = {
        "invariants": len(deduped) == 0,
        "error_rate": error_rate <= error_budget,
        "no_5xx": metrics.intake_5xx == 0,
    }
    highest = max((SEVERITY_ORDER.get(d["severity"], 0) for d in deduped), default=-1)
    if not gates["error_rate"] or not gates["no_5xx"]:
        highest = max(highest, SEVERITY_ORDER["high"])

    return {
        "ts": ts, "profile": profile.name, "gates": gates, "error_budget": error_budget,
        "metrics": {
            "intake_attempted": metrics.intake_attempted, "intake_201": metrics.intake_201,
            "intake_429": metrics.intake_429, "intake_422": metrics.intake_422,
            "intake_5xx": metrics.intake_5xx, "other_unexpected": metrics.other_unexpected,
            "reached_out": metrics.reached_out, "conflict_409": metrics.conflict_409,
            "error_count": metrics.error_count, "error_rate": round(error_rate, 4),
            "p50_ms": metrics.p(50), "p95_ms": metrics.p(95),
            "queue_depth_max": max(metrics.queue_depth_samples, default=0),
            "queue_depth_end": metrics.queue_depth_samples[-1] if metrics.queue_depth_samples else 0,
            "duration_s": metrics.duration_s,
        },
        "findings": deduped,
        "highest_severity": highest,
    }


def write(report: dict) -> tuple[str, int]:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    base = os.path.join(REPORTS_DIR, f"run-{report['ts']}")
    with open(base + ".json", "w") as fh:
        json.dump(report, fh, indent=2)

    m = report["metrics"]
    lines = [
        f"# Load run report — {report['ts']} (profile: {report['profile']})", "",
        "## Gates",
        f"- invariants: {'PASS' if report['gates']['invariants'] else 'FAIL'}",
        f"- error-rate ≤ {report.get('error_budget', ERROR_BUDGET)*100:.1f}%: "
        f"{'PASS' if report['gates']['error_rate'] else 'FAIL'} "
        f"({m['error_count']}/{m['intake_attempted']} = {m['error_rate']*100:.2f}%)",
        f"- no 5xx: {'PASS' if report['gates']['no_5xx'] else 'FAIL'} ({m['intake_5xx']})",
        "",
        "## Metrics",
        f"- intake: {m['intake_201']}/{m['intake_attempted']} created; "
        f"429={m['intake_429']} 422={m['intake_422']} 5xx={m['intake_5xx']}",
        f"- reached_out: {m['reached_out']}; 409 conflicts: {m['conflict_409']}",
        f"- latency p50/p95 ms: {m['p50_ms']}/{m['p95_ms']}; duration: {m['duration_s']}s",
        f"- queue depth max/end: {m['queue_depth_max']}/{m['queue_depth_end']}",
        "",
        f"## Findings ({len(report['findings'])})",
    ]
    if not report["findings"]:
        lines.append("None — all invariants held. ✅")
    for d in report["findings"]:
        lines += [
            f"### [{d['severity'].upper()}] {d['invariant_id']} — {d['title']} (×{d['count']}, "
            f"seen in {d['runs_seen']} run(s))",
            f"- endpoint: `{d['endpoint']}` · class: `{d['error_class']}`",
            f"- samples: {d['samples'] or 'n/a'}",
            f"- **{d['fix_prompt']}**", "",
        ]
    with open(base + ".md", "w") as fh:
        fh.write("\n".join(lines) + "\n")

    # exit code: 0 clean; 1 low/medium; 2 high; 3 critical
    code = 0 if report["highest_severity"] < 0 else min(3, report["highest_severity"] + 1) \
        if report["highest_severity"] >= SEVERITY_ORDER["high"] else 1
    if report["highest_severity"] < 0:
        code = 0
    elif report["highest_severity"] >= SEVERITY_ORDER["critical"]:
        code = 3
    elif report["highest_severity"] >= SEVERITY_ORDER["high"]:
        code = 2
    else:
        code = 1
    return base + ".md", code


def now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
