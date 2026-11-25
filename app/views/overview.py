"""Overview tab: the election calendar, data freshness, the review queue and the monthly review list."""
from __future__ import annotations

import datetime as dt
from html import escape
from pathlib import Path

import pandas as pd

from app import charts, components, data, logic
from app.blocks import Expander, Figure, Html, to_html, to_streamlit
from pipeline import config


def _add_months(day: dt.date, months: int) -> dt.date:
    y, m = divmod(day.month - 1 + months, 12)
    return dt.date(day.year + y, m + 1, min(day.day, 28))


def freshness_html(data_dir: Path, today: dt.date) -> str:
    """Latest poll, polls in 90 days and fetch status for every contest that has been fetched."""
    q = data.quality(data_dir)
    if not q["contests"]:
        return ""
    by_id = {k["contest_id"]: k for k in config.contests()}
    label = {"ok": "OK", "stale": "Stale: last fetch failed", "failed": "Failed: never fetched"}
    rows = []
    for cid, e in q["contests"].items():
        k = by_id.get(cid)
        if k is None:
            continue
        status = label.get(e.get("parser_status"), "Unknown")
        if e.get("parser_status") == "ok" and logic.is_stale(e, today):
            status = "Stale: no fetch on schedule"
        if e.get("parser_status") != "ok" or logic.is_stale(e, today):
            status = f'<span class="rg-flag">{status}</span>'
        latest = components.fmt_date(e["latest_poll_date"]) if e.get("latest_poll_date") else "–"
        rows.append(f'<tr><td class="rg-nowrap">{escape(config.country(k["country"])["name"])}</td>'
                    f'<td>{escape(k["body"])}' + (f' <span class="rg-muted">· {escape(k["territory"])}</span>' if k["tier"] == "subnational" else "")
                    + f'</td><td class="rg-nowrap">{latest}</td><td class="rg-num">{e.get("polls_90d", 0)}</td>'
                    f'<td class="rg-num">{e.get("pollsters_90d", 0)}</td><td>{status}</td>'
                    f'<td class="rg-num">{len(e.get("validation_warnings", []))}</td></tr>')
    as_of = q.get("data_as_of") or ""
    return ('<div class="rg"><h2>Data freshness</h2>'
            f'<p class="rg-muted">Data as of {escape(as_of[:16].replace("T", " "))} UTC.</p>'
            '<div class="rg-scroll"><table class="rg-table rg-small"><thead><tr><th>Country</th><th>Contest</th>'
            '<th>Latest poll</th><th class="rg-num">Polls, 90 days</th><th class="rg-num">Pollsters, 90 days</th>'
            '<th>Fetch</th><th class="rg-num">Warnings</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div></div>")


TRIGGER_LABEL = {
    "new_party": "New party", "pollster_new": "New pollster", "pollster_silent": "Pollster gone quiet",
    "subnational_in_window": "Section opened", "layout_change": "Source could not be read",
    "validation_failed": "Validation failing", "source_disagreement": "Sources disagree", "review_due": "Review due",
}


def queue_html(data_dir: Path) -> str:
    """What the daily scan has queued for the weekly check."""
    queue = data.review_queue(data_dir)
    names = {c["code"]: c["name"] for c in config.countries()}
    if not queue:
        body = '<p class="rg-muted">Nothing is queued. The daily scan found no trigger firing.</p>'
    else:
        rows = "".join(
            f'<tr><td class="rg-nowrap">{escape(TRIGGER_LABEL.get(e["trigger"], e["trigger"]))}</td>'
            f'<td class="rg-nowrap">{escape(names.get(e["country"], "Every tab"))}</td>'
            f'<td>{escape(e["evidence"])}</td>'
            f'<td class="rg-nowrap">{escape(", ".join(e.get("judgement_ids") or []) or "–")}</td>'
            f'<td class="rg-nowrap">{components.fmt_date(e["first_seen"])}</td></tr>' for e in queue)
        body = ('<div class="rg-scroll"><table class="rg-table rg-small"><thead><tr><th>Trigger</th><th>Where</th>'
                "<th>What fired it</th><th>May reopen</th><th>First seen</th></tr></thead>"
                f"<tbody>{rows}</tbody></table></div>")
    return (f'<div class="rg"><h2>Review queue ({len(queue)})</h2>'
            '<p class="rg-muted">Mechanical triggers from the daily scan. The weekly check reads these and '
            "opens a proposal where one is warranted; nothing here changes the dashboard by itself.</p>"
            + body + "</div>")


def calendar_marks(ahead: list[dict], today: dt.date) -> pd.DataFrame:
    """One mark per country, day and kind of contest; contests sharing all three share a mark."""
    names = {c["code"]: c["name"] for c in config.countries()}
    groups: dict[tuple, list[tuple[dict, dt.date, str]]] = {}
    for k in ahead:
        days = k.get("round_dates") or [config.contest_sort_date(k)]
        for i, day in enumerate(days):
            if day < today:
                continue
            note = f"Round {i + 1}" if len(days) > 1 else ""
            groups.setdefault((k["country"], day, k["kind"], bool(k.get("date"))), []).append((k, day, note))
    rows = []
    for (cc, day, kind, firm), items in groups.items():
        first = items[0][0]
        if len(items) == 1:
            title = first["body"] + ("" if first["territory"] == names[cc] else f", {first['territory']}")
        else:
            title = f"{len(items)} contests: " + ", ".join(k["territory"] for k, _, _ in items)
        lines = [names[cc], components.contest_when(first) + (f" · {items[0][2]}" if items[0][2] else ""),
                 f"{(day - today).days} days from today" + ("" if firm else " at the latest"),
                 components.DATE_STATUS_LABEL[first["date_status"]]
                 + (" · election called" if first["status"] == "called" else "")]
        rows.append({"country": names[cc], "date": pd.Timestamp(day), "kind": kind, "firm": firm,
                     "title": title, "detail": "<br>".join(escape(x) for x in lines)})
    return pd.DataFrame(rows, columns=["country", "date", "kind", "firm", "title", "detail"])


def build(today: dt.date | None = None, data_dir: Path = data.DATA) -> list:
    """The Overview tab as blocks: the calendar chart, its table, then the lists."""
    today = today or dt.datetime.now(dt.timezone.utc).date()
    s = config.settings()
    months = s["contests"]["subnational_window_months"]
    horizon = _add_months(today, months)
    countries = config.countries()
    ahead = [k for k in config.contests() if today <= config.contest_sort_date(k) <= horizon]
    ahead.sort(key=lambda k: (config.contest_sort_date(k), k["contest_id"]))
    due = [j for j in config.judgements() if j["review_by"] <= _add_months(today, 1)]
    due.sort(key=lambda j: (j["review_by"], j["id"]))
    watch = [j for j in config.judgements() if j["status"] == "on_watch" and j not in due]
    marks = calendar_marks(ahead, today)
    blocks: list = [Html(
        f'<div class="rg"><h2>Election calendar: the next {months} months</h2>'
        f'<p class="rg-muted">{len(ahead)} contests with a date, a legal deadline or an expected window up to '
        f"{components.fmt_date(horizon)}. Hover a mark for the contest. A hollow mark is a deadline or an "
        "expected window, not a fixed date.</p></div>")]
    if not marks.empty:
        blocks.append(Figure(charts.election_calendar(marks, today, horizon), "calendar"))
    blocks.append(Expander(f"Show the calendar as a table ({len(ahead)} contests)",
                           [Html(components.calendar_html(ahead, countries))]))
    blocks.append(Html(
        freshness_html(data_dir, today) + queue_html(data_dir)
        + '<div class="rg"><h2>Monthly review list</h2>'
        f"<h3>Due for review within a month ({len(due)})</h3>" + components.judgement_list_html(due)
        + f"<h3>On watch ({len(watch)})</h3>"
        '<p class="rg-muted">On-watch entries are reviewed every month whether or not anything fired.</p>'
        + components.judgement_list_html(watch) + "</div>"))
    return blocks


def page_html(today: dt.date | None = None, data_dir: Path = data.DATA) -> str:
    """The Overview tab as static HTML (charts need Plotly on the page; scripts/snapshot.py adds it)."""
    return to_html(build(today, data_dir))


def render() -> None:
    to_streamlit(build())
