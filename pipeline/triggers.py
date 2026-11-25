"""The daily trigger scan (SPEC.md section 8): mechanical signs that a judgement may need another look.

`scan` reads configuration, data/quality.json and the poll files, and returns the entries of
data/review_queue.json. It decides nothing: the weekly check reads the queue and proposes changes.

Triggers
    new_party              a label not in the party file reaches the configured share in the configured
                           number of polls
    pollster_new           a pollster's first poll in a contest is recent
    pollster_silent        a regular pollster has just passed the configured days without a poll
    subnational_in_window  a sub-national section has just started to show
    layout_change          a pull failed because the source could not be read
    validation_failed      a pull failed validation twice running
    review_due             a judgement's review date is near or past
Not scanned yet: source_disagreement (no contest has a second source).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from pipeline import config, model

VALIDATION_ERRORS = ("failed validation", "no valid poll", "down from")


def add_months(day: dt.date, months: int) -> dt.date:
    y, m = divmod(day.month - 1 + months, 12)
    return dt.date(day.year + y, m + 1, min(day.day, 28))


def subnational_visible(contest: dict, poll_ends: pd.Series, poll_ids: pd.Series, today: dt.date) -> bool:
    """A sub-national section shows within the configured months of its election, or once it has
    the configured number of polls in the last 12 months."""
    c = config.settings()["contests"]
    when = config.contest_sort_date(contest)
    if today <= when <= add_months(today, c["subnational_window_months"]):
        return True
    recent = poll_ids[pd.to_datetime(poll_ends) > pd.Timestamp(add_months(today, -12))]
    return recent.nunique() >= c["subnational_min_polls_12m"]


def judgements_for(country: str, *scopes: str) -> list[str]:
    """Ids of the register entries a trigger may reopen: this country's and the all-tab rules' in these scopes."""
    return [j["id"] for j in config.judgements() if j["country"] in (country, "ALL") and j["scope"] in scopes]


def unmapped_summary(figures: dict[str, list[float]], unit: str, chamber_size: int | None) -> dict:
    """Per unmapped label: how many figures, how many at the new-party share, and the largest."""
    r = config.settings()["review"]
    floor = r["new_party_trigger_pct"] * (chamber_size / 100 if unit == "seats" and chamber_size else 1)
    return {label: {"figures": len(v), "at_trigger_share": sum(x >= floor for x in v), "max": max(v)}
            for label, v in sorted(figures.items()) if v}


def scan(data_dir: Path = model.DATA, today: dt.date | None = None, quality: dict | None = None,
         previous: list[dict] | None = None) -> list[dict]:
    """Every trigger firing today, as review-queue entries. `previous` keeps each entry's first_seen."""
    import json

    today = today or dt.datetime.now(dt.timezone.utc).date()
    r = config.settings()["review"]
    a = config.settings()["average"]
    if quality is None:
        path = data_dir / "quality.json"
        quality = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"contests": {}}
    by_id = {k["contest_id"]: k for k in config.contests()}
    out: list[dict] = []

    def add(trigger, country, contest_id, subject, scopes, evidence, ids=None):
        out.append({"trigger": trigger, "country": country, "contest_id": contest_id, "subject": subject,
                    "judgement_ids": ids if ids is not None else judgements_for(country, *scopes),
                    "evidence": evidence})

    recent = dt.timedelta(days=r["event_trigger_days"])
    for cid, entry in quality.get("contests", {}).items():
        k = by_id.get(cid)
        if k is None:
            continue
        cc = k["country"]
        where = f'{k["body"]}, {k["territory"]}'
        for label, u in (entry.get("unmapped_labels") or {}).items():
            if u["at_trigger_share"] >= r["new_party_trigger_polls"]:
                add("new_party", cc, cid, label, ("parties",),
                    f"'{label}' is not in config/parties/{cc}.yaml and reaches {r['new_party_trigger_pct']:g}% in "
                    f"{u['at_trigger_share']} polls of {where} (largest figure {u['max']:g}).")
        status, error = entry.get("parser_status"), entry.get("last_error") or ""
        if status in ("stale", "failed"):
            if any(e in error for e in VALIDATION_ERRORS):
                if entry.get("consecutive_failures", 0) >= 2:
                    add("validation_failed", cc, cid, None, ("sources", "polls"),
                        f"{where}: validation has failed the pull {entry['consecutive_failures']} runs running. {error}")
            else:
                add("layout_change", cc, cid, None, ("sources",), f"{where}: the source could not be read. {error}")
        since = entry.get("visible_since")
        if k["tier"] == "subnational" and since and today - dt.date.fromisoformat(since) <= recent:
            add("subnational_in_window", cc, cid, None, ("sub-national",),
                f"{where} started to show on {since}: it is inside the sub-national window or has enough polls.")

    countries = {k["country"] for k in by_id.values() if k["contest_id"] in quality.get("contests", {})}
    silent_days = r["pollster_silent_days"]
    for cc in sorted(countries):
        polls = model.read_polls(cc, data_dir)
        if polls.empty:
            continue
        heads = polls.drop_duplicates(["contest_id", "poll_id"])
        ends = pd.to_datetime(heads["fieldwork_end"]).dt.date
        for cid, group in heads.assign(_end=ends).groupby("contest_id"):
            k = by_id.get(cid)
            if k is None:
                continue
            where = f'{k["body"]}, {k["territory"]}'
            first_poll = group["_end"].min()
            for pollster, g in group.groupby("pollster"):
                first, last, n = g["_end"].min(), g["_end"].max(), g["poll_id"].nunique()
                if today - first <= recent and first > first_poll:
                    add("pollster_new", cc, cid, pollster, ("pollsters", "polls"),
                        f"{pollster} published its first poll of {where} with fieldwork to {first.isoformat()}.")
                gap = (today - last).days
                if n >= a["min_polls_for_own_volatility"] and silent_days < gap <= silent_days + r["event_trigger_days"]:
                    add("pollster_silent", cc, cid, pollster, ("pollsters", "polls"),
                        f"{pollster} has {n} polls of {where} and none since {last.isoformat()} ({gap} days).")

    notice = dt.timedelta(days=r["review_due_notice_days"])
    for j in config.judgements():
        if j["status"] != "retired" and j["review_by"] <= today + notice:
            late = "was due" if j["review_by"] < today else "is due"
            add("review_due", j["country"], None, j["id"], (), f"{j['id']} {late} for review on {j['review_by'].isoformat()}: "
                f"{j['question']}", ids=[j["id"]])

    seen = {(e["trigger"], e.get("contest_id"), e.get("subject")): e.get("first_seen") for e in previous or []}
    for e in out:
        e["first_seen"] = seen.get((e["trigger"], e["contest_id"], e["subject"])) or today.isoformat()
        e["last_seen"] = today.isoformat()
    return sorted(out, key=lambda e: (e["trigger"], e["country"], e["contest_id"] or "", e["subject"] or ""))
