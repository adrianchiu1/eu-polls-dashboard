"""Reference implementation of the headline average. The rule is written out in docs/AVERAGING.md.

This file exists to generate and check the fixtures in this folder. It is NOT the production code.
pipeline/average.py must reproduce expected.json to 1e-6 and may be written quite differently
(vectorised, incremental, whatever suits). When the two disagree, read docs/AVERAGING.md; if that
is ambiguous too, ask the owner rather than picking a side.

Input frame, one row per poll (wide):
    poll_id, pollster, fieldwork_start, fieldwork_end, <one column per party, NaN if not reported>
Only polls that are eligible for the average belong in the frame: right contest, right electoral
cycle, headline line-up, not party-commissioned.
"""
from __future__ import annotations

import math
from statistics import median

import pandas as pd

SETTINGS = {
    "window_days": 30,
    "widened_window_days": 60,
    "min_pollsters_in_window": 3,
    "lookback_days": 365,
    "consensus_window_days": 30,
    "min_other_pollsters_for_consensus": 2,
    "min_polls_for_own_volatility": 6,
    "min_pollsters_with_volatility": 3,
    "weight_cap_multiple_of_median": 3.0,
    "volatility_floor_points": 0.1,
    "thin_window_days": 90,
}

META = ["poll_id", "pollster", "fieldwork_start", "fieldwork_end"]


def load(path) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["fieldwork_start", "fieldwork_end"])


def parties_of(polls: pd.DataFrame) -> list[str]:
    return [c for c in polls.columns if c not in META]


def _days(n: int) -> pd.Timedelta:
    return pd.Timedelta(days=n)


def _in_window(polls: pd.DataFrame, t: pd.Timestamp, days: int) -> pd.DataFrame:
    """Polls whose fieldwork ended in (t - days, t]."""
    return polls[(polls["fieldwork_end"] > t - _days(days)) & (polls["fieldwork_end"] <= t)]


def _latest_per_pollster(polls: pd.DataFrame) -> pd.DataFrame:
    """One row per pollster: latest fieldwork_end, then latest fieldwork_start, then highest poll_id."""
    ordered = polls.sort_values(["fieldwork_end", "fieldwork_start", "poll_id"])
    return ordered.groupby("pollster", sort=False).tail(1)


def residuals(polls: pd.DataFrame, s: dict = SETTINGS) -> pd.DataFrame:
    """Step 1 and 2: each poll's figure minus the leave-one-out consensus, per party.

    The consensus for a poll that ended on day d is the unweighted mean of the latest poll from every
    OTHER pollster with fieldwork_end in (d - consensus_window_days, d]. It uses nothing after d.
    A residual is defined only when at least min_other_pollsters_for_consensus others report the party.
    """
    parties = parties_of(polls)
    rows = []
    for _, poll in polls.iterrows():
        others = _in_window(polls[polls["pollster"] != poll["pollster"]], poll["fieldwork_end"],
                            s["consensus_window_days"])
        latest = _latest_per_pollster(others)
        for party in parties:
            if pd.isna(poll[party]):
                continue
            values = latest[party].dropna()
            if len(values) < s["min_other_pollsters_for_consensus"]:
                continue
            rows.append({
                "poll_id": poll["poll_id"],
                "pollster": poll["pollster"],
                "fieldwork_end": poll["fieldwork_end"],
                "party": party,
                "residual": float(poll[party]) - float(values.mean()),
            })
    return pd.DataFrame(rows, columns=["poll_id", "pollster", "fieldwork_end", "party", "residual"])


def volatilities(res: pd.DataFrame, t: pd.Timestamp, s: dict = SETTINGS) -> dict:
    """Steps 3 and 4: pooled standard deviation of demeaned residuals, per pollster, as of day t.

    Residuals in (t - lookback_days, t] are demeaned per pollster AND party, so a steady house lean
    drops out. Degrees of freedom are sum over parties of (n - 1). A pollster needs at least
    min_polls_for_own_volatility polls with a defined residual to get its own estimate.
    """
    recent = res[(res["fieldwork_end"] > t - _days(s["lookback_days"])) & (res["fieldwork_end"] <= t)]
    out = {}
    for pollster, group in recent.groupby("pollster"):
        n_polls = int(group["poll_id"].nunique())
        if n_polls < s["min_polls_for_own_volatility"]:
            continue
        demeaned = group["residual"] - group.groupby("party")["residual"].transform("mean")
        dof = int((group.groupby("party").size() - 1).clip(lower=0).sum())
        if dof <= 0:
            continue
        sigma = math.sqrt(float((demeaned ** 2).sum()) / dof)
        out[pollster] = {"sigma": max(sigma, s["volatility_floor_points"]), "n_polls_lookback": n_polls}
    return out


def _unweighted(polls: pd.DataFrame, t: pd.Timestamp, window: int, flags: list[str]):
    in_window = _in_window(polls, t, window)
    if in_window.empty:
        return None
    latest = _latest_per_pollster(in_window)
    averages = {p: float(latest[p].dropna().mean()) for p in parties_of(polls) if latest[p].notna().any()}
    return {
        "date": t.date().isoformat(),
        "weighting": "unweighted",
        "window_days": window,
        "flags": flags,
        "n_polls": int(len(latest)),
        "n_pollsters": int(latest["pollster"].nunique()),
        "averages": averages,
        "pollsters": {},
    }


def average(polls: pd.DataFrame, t, s: dict = SETTINGS, tier: str = "national", res: pd.DataFrame | None = None):
    """The headline average on day t. Returns None when no poll is in the window."""
    t = pd.Timestamp(t)

    # Sub-national contests never use volatility weights.
    if tier == "subnational":
        return _unweighted(polls, t, s["thin_window_days"], ["thin_polling"])

    window, flags = s["window_days"], []
    in_window = _in_window(polls, t, window)
    if in_window["pollster"].nunique() < s["min_pollsters_in_window"]:
        window = s["widened_window_days"]
        flags.append("low_coverage")
        in_window = _in_window(polls, t, window)
    if in_window.empty:
        return None

    if res is None:
        res = residuals(polls, s)
    vol = volatilities(res, t, s)
    if len(vol) < s["min_pollsters_with_volatility"]:
        return _unweighted(polls, t, window, flags + ["unweighted_no_volatility"])

    # Step 5: weights. A pollster without its own estimate takes the median volatility of those with one.
    median_sigma = median(v["sigma"] for v in vol.values())
    present = sorted(in_window["pollster"].unique())
    sigma = {h: (vol[h]["sigma"] if h in vol else median_sigma) for h in present}
    raw = {h: sigma[h] ** -2 for h in present}
    cap = s["weight_cap_multiple_of_median"] * median(raw.values())   # median over pollsters in the window
    weight = {h: min(raw[h], cap) for h in present}
    n_in_window = in_window.groupby("pollster").size().to_dict()

    per_poll = in_window["pollster"].map(lambda h: weight[h] / n_in_window[h])
    averages = {}
    for party in parties_of(polls):
        reported = in_window[party].notna()
        if not reported.any():
            continue
        averages[party] = float((per_poll[reported] * in_window.loc[reported, party]).sum()
                                / per_poll[reported].sum())

    total = sum(weight.values())
    return {
        "date": t.date().isoformat(),
        "weighting": "volatility",
        "window_days": window,
        "flags": flags,
        "n_polls": int(len(in_window)),
        "n_pollsters": int(len(present)),
        "averages": averages,
        "pollsters": {
            h: {
                "volatility": sigma[h],
                "volatility_source": "own" if h in vol else "median",
                "n_polls_in_window": int(n_in_window[h]),
                "capped": bool(raw[h] > cap),
                "weight_share": weight[h] / total,
            }
            for h in present
        },
    }
