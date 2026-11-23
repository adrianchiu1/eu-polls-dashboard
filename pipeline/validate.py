"""Validation before publish (SPEC.md section 6).

Hard rules drop a poll and record why: shares sum inside the configured band (seats: the chamber
size), fieldwork dates are ordered and not in the future, and no second poll has the same pollster,
end date, contest, line-up and round. The swing rule only flags. Thresholds come from settings.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd

from pipeline import config, model

GROUP = ["poll_id", "lineup_id", "round"]


@dataclass
class Report:
    polls: pd.DataFrame                              # rows that passed, with swing flags added
    warnings: list[str] = field(default_factory=list)
    dropped: int = 0                                 # polls (poll, line-up, round) dropped by a hard rule
    checked: int = 0


def _label(row) -> str:
    extra = "" if row["lineup_id"] == "default" and row["round"] == 1 else f' [{row["lineup_id"]}, round {row["round"]}]'
    return f'{row["pollster"]} {row["fieldwork_end"]}{extra}'


def validate(polls: pd.DataFrame, *, chamber_size: int | None = None, today: dt.date | None = None,
             check_sums: bool = True) -> Report:
    """Apply every rule to one contest's long rows.

    `check_sums=False` is for tables that do not list every party (no Others column), where a low sum
    says nothing about the poll.
    """
    v = config.settings()["validation"]
    today = today or dt.datetime.now(dt.timezone.utc).date()
    if polls.empty:
        return Report(polls)
    df = polls.copy()
    df["fieldwork_end"] = pd.to_datetime(df["fieldwork_end"]).dt.date
    df["fieldwork_start"] = pd.to_datetime(df["fieldwork_start"]).dt.date
    df["fieldwork_start"] = df["fieldwork_start"].where(df["fieldwork_start"].notna(), None)
    head = df.drop_duplicates(GROUP).set_index(GROUP)
    warnings: list[str] = []
    bad: set = set()

    def drop(key, why: str) -> None:
        if key not in bad:
            bad.add(key)
            warnings.append(f"dropped {_label(dict(head.loc[key], lineup_id=key[1], round=key[2]))}: {why}")

    # values
    for key, g in df.groupby(GROUP, sort=False):
        if g["value"].isna().any() or (g["value"] < 0).any():
            drop(key, "a missing or negative figure")
        if g["party_id"].duplicated().any():
            drop(key, "the same party twice")

    # share sums
    if check_sums:
        sums = df.groupby(GROUP, sort=False)["value"].sum()
        units = df.groupby(GROUP, sort=False)["unit"].first()
        for key, total in sums.items():
            if units[key] == "seats":
                if chamber_size and round(total) != chamber_size:
                    drop(key, f"seats sum to {total:g}, chamber has {chamber_size}")
            elif not (v["share_sum_min_pct"] <= total <= v["share_sum_max_pct"]):
                drop(key, f"shares sum to {total:.1f}%")

    # dates
    for key, row in head.iterrows():
        start, end = row["fieldwork_start"], row["fieldwork_end"]
        if end > today:
            drop(key, "fieldwork ends in the future")
        elif start is not None and not pd.isna(start) and start > end:
            drop(key, "fieldwork starts after it ends")

    # duplicates: same pollster, end date, contest, line-up and round. The first by poll_id stays.
    dup_cols = ["contest_id", "pollster", "fieldwork_end", "lineup_id", "round"]
    ordered = head.reset_index().sort_values("poll_id")
    for _, row in ordered[ordered.duplicated(dup_cols, keep="first")].iterrows():
        drop((row["poll_id"], row["lineup_id"], row["round"]), "duplicate of another poll by the same pollster and end date")

    keys = pd.MultiIndex.from_frame(df[GROUP])
    keep = ~keys.isin(list(bad)) if bad else pd.Series(True, index=df.index).to_numpy()
    out = df[keep].copy()

    # swing: flagged, never dropped
    limit = v["swing_flag_points"]
    swung: set = set()
    pct = out[out["unit"] == "pct"]
    for _, g in pct.groupby(["contest_id", "pollster", "lineup_id", "round", "party_id"], sort=False):
        g = g.sort_values(["fieldwork_end", "poll_id"])
        jump = g["value"].diff().abs() > limit
        swung.update(zip(g.loc[jump, "poll_id"], g.loc[jump, "lineup_id"], g.loc[jump, "round"]))
    if swung:
        mask = pd.MultiIndex.from_frame(out[GROUP]).isin(list(swung))
        out.loc[mask, "flags"] = out.loc[mask, "flags"].map(lambda f: model.add_flag(f, "swing"))
        warnings.append(f"{len(swung)} poll(s) flagged for a swing above {limit:g} points from the pollster's previous poll")

    return Report(out, warnings, dropped=len(bad), checked=len(head))
