"""Deterministic intake cohort generator. Produces the bulk load (normal + families +
same-phone + resubmits) — all expected to create a lead (201). Targeted edge probes
(idempotency/injection/honeypot/invalid/oversized) live in the harness as a fixed set."""

import random


def build_intake(n_leads: int, seed: int = 1337) -> list[dict]:
    """Return `n_leads` submission specs. Each: {cohort, first_name, last_name, email, phone}.
    Embeds family (shared email) and same-phone (shared number) groups + resubmits so the
    history/dedup invariants have signal. RNG is seeded for reproducibility."""
    rng = random.Random(seed)
    out: list[dict] = []
    run = rng.randint(10**6, 10**7)  # per-build salt so reruns don't collide in a shared DB

    def email(i: int) -> str:
        return f"lead{run}_{i}@load.test"

    def phone(i: int) -> str:
        return f"+1 555 {run % 1000:03d} {i:04d}"

    i = 0
    # families: 5 groups, 3 members each — same email, different names
    for g in range(5):
        shared = email(f"fam{g}")
        for m in range(3):
            out.append({"cohort": "family", "first_name": f"Fam{g}M{m}",
                        "last_name": f"Group{g}", "email": shared, "phone": phone(i)})
            i += 1
    # same-phone: 5 groups, 2 members — same phone, different names + emails
    for g in range(5):
        shared = phone(f"sp{g}".__hash__() % 10000)
        for m in range(2):
            out.append({"cohort": "same_phone", "first_name": f"Ph{g}M{m}",
                        "last_name": f"Shared{g}", "email": email(f"sp{g}_{m}"), "phone": shared})
            i += 1
    # resubmits: 10 people submit twice (same email) → past history
    for r in range(10):
        e = email(f"re{r}")
        p = phone(i)
        for _ in range(2):
            out.append({"cohort": "resubmit", "first_name": f"Re{r}", "last_name": "Peat",
                        "email": e, "phone": p})
            i += 1
    # fill the rest with unique normal leads
    while len(out) < n_leads:
        out.append({"cohort": "normal", "first_name": f"User{i}", "last_name": "Lead",
                    "email": email(i), "phone": phone(i)})
        i += 1

    rng.shuffle(out)
    return out[:n_leads]
