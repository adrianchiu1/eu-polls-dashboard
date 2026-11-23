"""What a country tab shows, worked out from configuration and data. No drawing happens here."""
from __future__ import annotations

import datetime as dt

import pandas as pd

from pipeline import config, model, parties
from pipeline.config import previous_contest_id

FLAG_TEXT = {
    "low_coverage": "Low coverage: fewer than {min_pollsters} pollsters in {window} days, so the window is {widened} days.",
    "unweighted_no_volatility": "Unweighted: too few pollsters have enough polls for a volatility estimate.",
    "thin_polling": "Thin polling: the unweighted mean of each pollster's latest poll in {thin} days.",
}


def add_months(day: dt.date, months: int) -> dt.date:
    y, m = divmod(day.month - 1 + months, 12)
    return dt.date(day.year + y, m + 1, min(day.day, 28))


def flag_notes(flags: str) -> list[str]:
    s = config.settings()
    fill = dict(min_pollsters=s["average"]["min_pollsters_in_window"], window=s["average"]["window_days"],
                widened=s["average"]["widened_window_days"], thin=s["thin_polling"]["window_days"])
    return [FLAG_TEXT[f].format(**fill) for f in str(flags or "").split(";") if f in FLAG_TEXT]


def phase(contest: dict, today: dt.date, results: pd.DataFrame) -> str:
    """upcoming | result_pending | post_election | rolled  (SPEC.md section 1, "After polling day")."""
    date = contest.get("date")
    if date is None or today <= date:
        return "upcoming"
    has_result = not results[results["contest_id"] == contest["contest_id"]].empty
    if not has_result:
        return "result_pending"
    days = config.settings()["contests"]["post_election_view_days"]
    return "post_election" if today <= date + dt.timedelta(days=days) else "rolled"


def presidential_polled(polls: pd.DataFrame, today: dt.date) -> bool:
    """At least the configured number of presidential polls in the configured window."""
    c = config.settings()["contests"]
    since = pd.Timestamp(add_months(today, -c["presidential_polls_window_months"]))
    recent = polls[(polls["round"] == 1) & (polls["fieldwork_end"] > since)]
    return recent["poll_id"].nunique() >= c["presidential_min_polls_to_show"]


def subnational_visible(contest: dict, polls: pd.DataFrame, today: dt.date) -> bool:
    """Within the configured months of its election, or polled often enough in the last 12 months."""
    c = config.settings()["contests"]
    when = config.contest_sort_date(contest)
    if today <= when <= add_months(today, c["subnational_window_months"]):
        return True
    recent = polls[polls["fieldwork_end"] > pd.Timestamp(add_months(today, -12))]
    return recent["poll_id"].nunique() >= c["subnational_min_polls_12m"]


def headline_series(averages: pd.DataFrame, contest_id: str) -> pd.DataFrame:
    return averages[(averages["contest_id"] == contest_id) & (averages["round"] == 1)]


def standings(contest: dict, averages: pd.DataFrame, results: pd.DataFrame, as_of: dt.date,
              order: str = "support") -> tuple[pd.DataFrame, dict]:
    """The headline table for a contest on a day: one row per party with its own line, then Others.

    Returns (rows, meta). rows: party_id, short, name, colour, lr_score, average, delta_election,
    delta_window. meta: date, n_polls, n_pollsters, window_days, weighting, flags; {} when no value.
    A party has its own line at the configured minimum average; smaller ones are summed into Others.
    """
    cc = contest["country"]
    s = config.settings()
    series = headline_series(averages, contest["contest_id"])
    series = series[series["date"] <= pd.Timestamp(as_of)]
    if series.empty:
        return pd.DataFrame(), {}
    day = series["date"].max()
    now = series[series["date"] == day].set_index("party_id")["average"]
    before_day = day - pd.Timedelta(days=s["average"]["window_days"])
    before = series[series["date"] == before_day].set_index("party_id")["average"]
    prev_id = previous_contest_id(contest)
    last = results[results["contest_id"] == prev_id].set_index("party_id")["vote_share"] if prev_id else pd.Series(dtype=float)

    floor = s["parties"]["own_line_min_average_pct"]
    own = [p for p, v in now.items() if p != model.OTHERS and v >= floor]
    small = [p for p in now.index if p not in own]
    rows = []
    for p in own:
        d = parties.display(cc, p)
        rows.append(dict(party_id=p, **d, average=float(now[p]),
                         delta_election=float(now[p] - last[p]) if p in last.index else None,
                         delta_window=float(now[p] - before[p]) if p in before.index else None))
    rows.sort(key=lambda r: -r["average"])
    if order == "lr" and rows and all(r["lr_score"] is not None for r in rows):
        rows.sort(key=lambda r: r["lr_score"])
    if small:
        d = parties.display(cc, model.OTHERS)
        rows.append(dict(party_id=model.OTHERS, **d, average=float(now[small].sum()),
                         delta_election=None, delta_window=None))
    first = series[series["date"] == day].iloc[0]
    meta = dict(date=day.date(), n_polls=int(first["n_polls"]), n_pollsters=int(first["n_pollsters"]),
                window_days=int(first["window_days"]), weighting=first["weighting"],
                flags=first["flags"] if isinstance(first["flags"], str) else "", folded=len(small) - (model.OTHERS in small))
    return pd.DataFrame(rows), meta


def matchup_rows(contest: dict, averages: pd.DataFrame, as_of: dt.date) -> pd.DataFrame:
    """Second-round pairings with a current average, most-polled first."""
    cc = contest["country"]
    second = averages[(averages["contest_id"] == contest["contest_id"]) & (averages["round"] == 2)
                      & (averages["date"] <= pd.Timestamp(as_of))]
    rows = []
    for lineup, g in second.groupby("lineup_id"):
        day = g["date"].max()
        if (pd.Timestamp(as_of) - day).days > 0:
            continue                                        # no poll of this pairing in the window today
        latest = g[g["date"] == day].sort_values("party_id")
        if len(latest) != 2:
            continue
        a, b = (dict(parties.display(cc, r.party_id), average=float(r.average)) for r in latest.itertuples())
        rows.append({"label": f"{a['short']} v {b['short']}", "n_polls": int(latest["n_polls"].iloc[0]),
                     **{f"a_{k}": v for k, v in a.items()}, **{f"b_{k}": v for k, v in b.items()}})
    return pd.DataFrame(rows).sort_values(["n_polls", "label"], ascending=[False, True]) if rows else pd.DataFrame()
