"""Overview tab. Phase 0 shows the contests ahead and the entries due for review.

The freshness grid joins in Phase 2, once there is polling data to be fresh.
"""
from __future__ import annotations

import datetime as dt

from app import components
from pipeline import config


def _add_months(day: dt.date, months: int) -> dt.date:
    y, m = divmod(day.month - 1 + months, 12)
    return dt.date(day.year + y, m + 1, min(day.day, 28))


def page_html(today: dt.date | None = None) -> str:
    today = today or dt.datetime.now(dt.timezone.utc).date()
    s = config.settings()
    horizon = _add_months(today, s["contests"]["subnational_window_months"])
    countries = config.countries()
    ahead = [k for k in config.contests() if today <= config.contest_sort_date(k) <= horizon]
    ahead.sort(key=lambda k: (config.contest_sort_date(k), k["contest_id"]))
    due = [j for j in config.judgements() if j["review_by"] <= _add_months(today, 1)]
    due.sort(key=lambda j: (j["review_by"], j["id"]))
    months = s["contests"]["subnational_window_months"]
    return (
        f'<div class="rg"><h2>Contests in the next {months} months</h2>'
        f'<p class="rg-muted">{len(ahead)} contests with a date or legal deadline up to '
        f"{components.fmt_date(horizon)}, soonest first.</p></div>"
        + components.calendar_html(ahead, countries)
        + f'<div class="rg"><h2>Judgements due for review ({len(due)})</h2>'
        '<p class="rg-muted">Entries whose review date falls within a month.</p>'
        + components.judgement_list_html(due)
        + "</div>"
    )


def render() -> None:
    import streamlit as st

    st.html(page_html())
