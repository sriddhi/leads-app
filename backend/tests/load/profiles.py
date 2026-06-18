"""Load profiles. One code path, parameterized. `ci` fits a ~5-minute budget; `demo` is the
full 1000/5-min/75-attorney benchmark."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    name: str
    n_leads: int          # total intake submissions over the window
    duration_s: float     # intake window
    attorneys: int        # worker count
    cap: int              # per-attorney max open cases
    process_s: float      # simulated work per case before reaching out
    rate_limit_max: int   # server must be started with this RATE_LIMIT_MAX


CI = Profile(
    name="ci",
    n_leads=400,
    duration_s=120.0,
    attorneys=75,
    cap=10,
    process_s=0.8,
    rate_limit_max=1_000_000,
)

DEMO = Profile(
    name="demo",
    n_leads=1000,
    duration_s=300.0,
    attorneys=75,
    cap=10,
    process_s=10.0,
    rate_limit_max=1_000_000,
)

PROFILES = {"ci": CI, "demo": DEMO}


def get_profile(name: str) -> Profile:
    if name not in PROFILES:
        raise SystemExit(f"unknown profile '{name}'; choose from {sorted(PROFILES)}")
    return PROFILES[name]
