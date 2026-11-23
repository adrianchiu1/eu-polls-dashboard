#!/usr/bin/env python3
"""Build or check the averaging fixtures.

    python tests/fixtures/averaging/build_fixtures.py --check        recompute expected.json from the
                                                                     CSVs on disk and compare
    python tests/fixtures/averaging/build_fixtures.py --regenerate   rewrite the CSVs and expected.json

The polls are synthetic. Pollster and party names are placeholders, not real organisations.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import reference_average as ref  # noqa: E402

START, END = pd.Timestamp("2025-12-01"), pd.Timestamp("2026-11-20")
PARTIES = ["A", "B", "C", "D"]


def truth(day: pd.Timestamp) -> dict:
    """Slow drift over the cycle: A falls 30 -> 27, B rises 25 -> 28, C and D flat."""
    f = (day - START).days / (END - START).days
    return {"A": 30 - 3 * f, "B": 25 + 3 * f, "C": 15.0, "D": 10.0}


def simulate(pollsters: dict, seed: int, with_lean: bool = True) -> pd.DataFrame:
    """pollsters: name -> dict(first, every, noise, lean={party: points}, last=optional)."""
    rng = np.random.default_rng(seed)
    rows = []
    for name, spec in pollsters.items():
        day = pd.Timestamp(spec["first"])
        last = pd.Timestamp(spec.get("last", END))
        while day <= last:
            true = truth(day)
            row = {"pollster": name, "fieldwork_start": day - pd.Timedelta(days=3), "fieldwork_end": day}
            for party in PARTIES:
                base = round(true[party] + rng.normal(0, spec["noise"]), 1)   # drawn whether or not lean applies
                lean = spec.get("lean", {}).get(party, 0.0) if with_lean else 0.0
                row[party] = round(base + lean, 1)
            rows.append(row)
            day += pd.Timedelta(days=spec["every"])
    df = pd.DataFrame(rows).sort_values(["fieldwork_end", "pollster"]).reset_index(drop=True)
    df.insert(0, "poll_id", [f"p{i:04d}" for i in range(1, len(df) + 1)])
    return df[["poll_id", "pollster", "fieldwork_start", "fieldwork_end"] + PARTIES]


MAIN = {
    "Alpha":   {"first": "2025-12-05", "every": 14, "noise": 0.6},
    "Beta":    {"first": "2025-12-09", "every": 21, "noise": 1.2},
    "Gamma":   {"first": "2025-12-16", "every": 21, "noise": 2.2},
    "Delta":   {"first": "2025-12-12", "every": 28, "noise": 1.2, "lean": {"A": 2.5, "B": -2.5}},
    "Epsilon": {"first": "2026-10-02", "every": 21, "noise": 1.0},          # newcomer: 3 polls
}
CAP = {
    "Steady": {"first": "2025-12-05", "every": 14, "noise": 0.1},
    "Loud1":  {"first": "2025-12-07", "every": 14, "noise": 2.0},
    "Loud2":  {"first": "2025-12-09", "every": 14, "noise": 2.0},
    "Loud3":  {"first": "2025-12-11", "every": 14, "noise": 2.0},
    "Loud4":  {"first": "2025-12-13", "every": 14, "noise": 2.0},
    "Loud5":  {"first": "2025-12-15", "every": 14, "noise": 2.0},
}
THIN = {
    "Local1": {"first": "2026-07-10", "every": 45, "noise": 1.5},
    "Local2": {"first": "2026-09-20", "every": 60, "noise": 1.5},
}


def build_frames() -> dict[str, pd.DataFrame]:
    main = simulate(MAIN, seed=20261123, with_lean=True)
    main_no_lean = simulate(MAIN, seed=20261123, with_lean=False)
    # low coverage: three pollsters fall silent, so the 30-day window holds only two
    silent = (main["pollster"].isin(["Gamma", "Delta", "Epsilon"]) & (main["fieldwork_end"] > "2026-10-10"))
    return {
        "main": main,
        "main_no_lean": main_no_lean,
        "low_coverage": main[~silent].reset_index(drop=True),
        "cap": simulate(CAP, seed=7),
        "thin_subnational": simulate(THIN, seed=11),
    }


CASES = [
    # (case name, fixture, tier, date)
    ("main_latest",            "main",             "national",    "2026-11-20"),
    ("main_midcycle",          "main",             "national",    "2026-06-01"),
    ("main_no_lean_latest",    "main_no_lean",     "national",    "2026-11-20"),
    ("early_cycle_unweighted", "main",             "national",    "2025-12-31"),
    ("low_coverage_widened",   "low_coverage",     "national",    "2026-11-20"),
    ("cap_binds",              "cap",              "national",    "2026-11-20"),
    ("thin_subnational",       "thin_subnational", "subnational", "2026-11-20"),
]


def _round(obj, nd=8):
    if isinstance(obj, float):
        return round(obj, nd)
    if isinstance(obj, dict):
        return {k: _round(v, nd) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round(v, nd) for v in obj]
    return obj


def compute_expected(frames: dict[str, pd.DataFrame]) -> dict:
    results = {}
    for case, fixture, tier, date in CASES:
        results[case] = {"fixture": f"{fixture}.csv", "tier": tier, "date": date,
                         "result": _round(ref.average(frames[fixture], date, tier=tier))}
    return {
        "settings": ref.SETTINGS,
        "tolerance": 1e-6,
        "cases": results,
        "invariants": [
            {
                "name": "own_lean_costs_nothing",
                "statement": "Delta carries a steady lean of +2.5 on A and -2.5 on B in main.csv and none in "
                             "main_no_lean.csv. Delta's own volatility is identical in both.",
                "cases": ["main_latest", "main_no_lean_latest"],
            },
            {
                "name": "lean_leaks_into_others",
                "statement": "Known property, not a bug: the OTHER pollsters' volatilities differ slightly "
                             "between the two files, because Delta drops in and out of their 30-day "
                             "consensus and its lean then looks like noise to them. The size of the leak "
                             "in this fixture is recorded below; it must stay small.",
                "cases": ["main_latest", "main_no_lean_latest"],
                "max_abs_volatility_difference_points": _round(max(
                    abs(results["main_latest"]["result"]["pollsters"][h]["volatility"]
                        - results["main_no_lean_latest"]["result"]["pollsters"][h]["volatility"])
                    for h in results["main_latest"]["result"]["pollsters"] if h != "Delta")),
                "must_stay_below_points": 0.05,
            },
            {
                "name": "point_in_time",
                "statement": "main_midcycle is unchanged if every poll after 2026-06-01 is deleted from main.csv.",
                "cases": ["main_midcycle"],
            },
        ],
    }


def _close(a, b, tol=1e-6, path="") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                out.append(f"{path}/{key}: missing on one side")
            else:
                out += _close(a[key], b[key], tol, f"{path}/{key}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: list length {len(a)} != {len(b)}"]
        return [m for i, (x, y) in enumerate(zip(a, b)) for m in _close(x, y, tol, f"{path}[{i}]")]
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return [] if abs(a - b) <= tol else [f"{path}: {a} != {b}"]
    return [] if a == b else [f"{path}: {a!r} != {b!r}"]


def check_invariants(expected: dict, frames: dict[str, pd.DataFrame]) -> list[str]:
    problems = []
    a = expected["cases"]["main_latest"]["result"]["pollsters"]
    b = expected["cases"]["main_no_lean_latest"]["result"]["pollsters"]
    if abs(a["Delta"]["volatility"] - b["Delta"]["volatility"]) > 1e-6:
        problems.append(f"a steady lean changed Delta's own volatility: "
                        f"{a['Delta']['volatility']} vs {b['Delta']['volatility']}")
    leak = max(abs(a[h]["volatility"] - b[h]["volatility"]) for h in a if h != "Delta")
    if leak >= 0.05:
        problems.append(f"Delta's lean moved another pollster's volatility by {leak:.4f} points (limit 0.05)")
    truncated = frames["main"][frames["main"]["fieldwork_end"] <= "2026-06-01"]
    again = _round(ref.average(truncated, "2026-06-01"))
    problems += _close(expected["cases"]["main_midcycle"]["result"], again, path="point_in_time")
    return problems


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    if mode == "--regenerate":
        frames = build_frames()
        for name, df in frames.items():
            df.to_csv(HERE / f"{name}.csv", index=False, date_format="%Y-%m-%d")
        frames = {name: ref.load(HERE / f"{name}.csv") for name in frames}   # reload: what readers get
        expected = compute_expected(frames)
        (HERE / "expected.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
        problems = check_invariants(expected, frames)
    elif mode == "--check":
        names = sorted({fixture for _, fixture, _, _ in CASES})
        frames = {name: ref.load(HERE / f"{name}.csv") for name in names}
        on_disk = json.loads((HERE / "expected.json").read_text(encoding="utf-8"))
        expected = compute_expected(frames)
        problems = _close(on_disk["cases"], json.loads(json.dumps(expected["cases"])), path="cases")
        problems += check_invariants(expected, frames)
    else:
        print(__doc__)
        return 2

    for case, body in expected["cases"].items():
        r = body["result"]
        print(f"{case:24s} {r['weighting']:10s} window={r['window_days']:>2}  polls={r['n_polls']:>2}  "
              f"pollsters={r['n_pollsters']}  flags={','.join(r['flags']) or '-'}")
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print("  -", p)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
