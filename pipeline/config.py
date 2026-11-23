"""Read-only access to config/. The app, the pipeline and the snapshot script all load through here."""
from __future__ import annotations

import datetime as dt
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"

FAR_FUTURE = dt.date(9999, 12, 31)


@lru_cache(maxsize=None)
def _load(name: str):
    with open(CONFIG / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def settings() -> dict:
    return _load("settings.yaml")


def countries() -> list[dict]:
    """Country tabs in tab order."""
    return sorted(_load("countries.yaml")["countries"], key=lambda c: c["tab_order"])


def country(code: str) -> dict:
    for c in countries():
        if c["code"] == code:
            return c
    raise KeyError(code)


def contest_sort_date(contest: dict) -> dt.date:
    """The date a contest sorts by: its date, else its legal deadline, else last."""
    return contest.get("date") or contest.get("deadline") or FAR_FUTURE


def contests(country_code: str | None = None) -> list[dict]:
    """Contests, national before sub-national, then by date. Optionally one country's."""
    rows = _load("contests.yaml")["contests"]
    if country_code is not None:
        rows = [k for k in rows if k["country"] == country_code]
    return sorted(rows, key=lambda k: (k["tier"] != "national", contest_sort_date(k), k["contest_id"]))


def judgements(country_code: str | None = None) -> list[dict]:
    """Register entries in file order. `country_code` may be a country code or "ALL"."""
    rows = _load("judgements.yaml")["judgements"]
    if country_code is not None:
        rows = [j for j in rows if j["country"] == country_code]
    return list(rows)


def sources(contest_id: str | None = None) -> list[dict]:
    rows = _load("sources.yaml")["sources"]
    if contest_id is not None:
        rows = [s for s in rows if s["contest_id"] == contest_id]
    return sorted(rows, key=lambda s: (s["contest_id"], s["priority"]))


def previous_contest_id(contest: dict) -> str | None:
    """The id that results of the previous election to the same body are stored under in
    data/results.csv: <cc>-<pres|parl|sub>-<year>. None when no previous date is configured."""
    if not contest.get("previous_date"):
        return None
    return "-".join(contest["contest_id"].split("-")[:2] + [str(contest["previous_date"].year)])


def panel_id(panel: str) -> str:
    """The line-up id of a regional panel of a contest: 'Flanders' -> 'flanders'."""
    import re

    return re.sub(r"[^a-z0-9]+", "-", panel.lower()).strip("-")
