"""Pure renderers for the judgement register and the election calendar.

Each function takes configuration rows and returns an HTML fragment. The Streamlit views show the
fragments with st.html and scripts/snapshot.py writes the same fragments to a file, so a review
snapshot shows exactly what the app shows. Styles are in app/static/register.css.
"""
from __future__ import annotations

import datetime as dt
from html import escape
from pathlib import Path

STATIC = Path(__file__).resolve().parent / "static"
REPO_URL = "https://github.com/adrianchiu1/eu-polls-dashboard"

STATUS_LABEL = {
    "active": "Active",
    "on_watch": "On watch",
    "proposed_change": "Proposed change",
    "retired": "Retired",
}
DECIDED_LABEL = {"owner": "Decided by owner", "draft": "Draft, not yet confirmed"}
DATE_STATUS_LABEL = {
    "fixed": "Fixed",
    "expected": "Expected",
    "deadline": "Deadline only",
    "unscheduled": "Unscheduled",
    "unknown": "Not researched",
}
VERIFICATION_LABEL = {
    "opened": "Source page opened",
    "search": "From search results",
    "legal_term": "From the legal term",
    "unverified": "Unverified",
}


def css(*, dark: bool = False) -> str:
    """The shared stylesheet. `dark=True` adds dark-theme token values (snapshot pages follow the
    viewer's theme; the app pins a light theme in .streamlit/config.toml)."""
    text = (STATIC / "register.css").read_text(encoding="utf-8")
    if dark:
        text += (STATIC / "register-dark.css").read_text(encoding="utf-8")
    return text



def fmt_date(value) -> str:
    """ISO date or date object to '18 Apr 2027'."""
    if value is None:
        return ""
    if isinstance(value, str):
        value = dt.date.fromisoformat(value)
    return f"{value.day} {value:%b %Y}"


def _linked(text: str) -> str:
    text = str(text)
    if text.startswith(("http://", "https://")):
        return f'<a href="{escape(text, quote=True)}">{escape(text)}</a>'
    return escape(text)


def _bullets(items) -> str:
    if not items:
        return '<span class="rg-muted">None recorded</span>'
    return "<ul>" + "".join(f"<li>{_linked(i)}</li>" for i in items) + "</ul>"


def judgement_counts(judgements: list[dict]) -> dict:
    return {
        "total": len(judgements),
        "on_watch": sum(j["status"] == "on_watch" for j in judgements),
        "owner": sum(j["decided_by"] == "owner" for j in judgements),
        "draft": sum(j["decided_by"] == "draft" for j in judgements),
    }


def counts_html(judgements: list[dict]) -> str:
    c = judgement_counts(judgements)
    return (
        '<ul class="rg-counts">'
        f'<li><b>{c["total"]}</b>entries</li>'
        f'<li><b>{c["on_watch"]}</b>on watch</li>'
        f'<li><b>{c["owner"]}</b>decided by owner</li>'
        f'<li><b>{c["draft"]}</b>draft, not yet confirmed</li>'
        "</ul>"
    )


def judgement_html(j: dict, *, open_: bool = False) -> str:
    """One register entry as a foldable block."""
    status_cls = " rg-watch" if j["status"] == "on_watch" else ""
    decided_cls = " rg-owner" if j["decided_by"] == "owner" else ""
    rows = [
        ("Decision", escape(j["decision"])),
        ("Why", escape(j["rationale"])),
        ("Rejected", _bullets(j.get("alternatives"))),
        ("Reopens if", _bullets(j.get("triggers"))),
        ("Evidence", _bullets(j.get("evidence"))),
        ("Confidence", escape(j["confidence"].capitalize())),
        ("Decided", f'{fmt_date(j["decided_on"])} · review by {fmt_date(j["review_by"])}'),
    ]
    if j.get("notes"):
        rows.append(("Notes", escape(j["notes"])))
    body = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows)
    return (
        f'<details class="rg-entry" id="{escape(j["id"])}"{" open" if open_ else ""}>'
        "<summary>"
        f'<span class="rg-id">{escape(j["id"])}</span>'
        f'<span class="rg-q">{escape(j["question"])}</span>'
        f'<span class="rg-pill{status_cls}">{STATUS_LABEL[j["status"]]}</span>'
        f'<span class="rg-pill{decided_cls}">{DECIDED_LABEL[j["decided_by"]]}</span>'
        f'<span class="rg-short">{escape(j["decision"])}</span>'
        "</summary>"
        f'<div class="rg-body"><dl>{body}</dl></div>'
        "</details>"
    )


def judgement_list_html(judgements: list[dict], *, open_: bool = False) -> str:
    if not judgements:
        return '<p class="rg-muted">No entries.</p>'
    return '<div class="rg-list">' + "".join(judgement_html(j, open_=open_) for j in judgements) + "</div>"


def register_html(judgements: list[dict], countries: list[dict]) -> str:
    """The full register: on-watch entries first, then rules for every tab, then each country."""
    names = {c["code"]: c["name"] for c in countries}
    parts = [counts_html(judgements)]
    watch = [j for j in judgements if j["status"] == "on_watch"]
    parts.append(f"<h3>On watch ({len(watch)})</h3>")
    parts.append(
        '<p class="rg-muted">Reviewed monthly instead of every six months. '
        "Each also appears under its country below.</p>"
    )
    parts.append(
        '<div class="rg-list">'
        + "".join(judgement_html(j).replace(f'id="{escape(j["id"])}"', f'id="watch-{escape(j["id"])}"', 1) for j in watch)
        + "</div>"
    )
    groups = [("ALL", "Rules for every tab")] + [(c["code"], c["name"]) for c in countries]
    for code, label in groups:
        rows = [j for j in judgements if j["country"] == code]
        if not rows:
            continue
        parts.append(f"<h3>{escape(names.get(code, label))} ({len(rows)})</h3>")
        parts.append(judgement_list_html(rows))
    return '<div class="rg">' + "".join(parts) + "</div>"


def contest_when(k: dict) -> str:
    """How a contest's timing reads: a date, both round dates, a window or a deadline."""
    if k.get("round_dates"):
        return " and ".join(fmt_date(d) for d in k["round_dates"])
    if k.get("date"):
        return fmt_date(k["date"])
    if k.get("deadline"):
        text = f'By {fmt_date(k["deadline"])}'
        return f'{text} ({k["expected_window"]})' if k.get("expected_window") else text
    return k.get("expected_window") or "No date known"


def calendar_html(contests: list[dict], countries: list[dict], *, show_country: bool = True) -> str:
    """Contests as a table, with a country column unless the table is for one country."""
    names = {c["code"]: c["name"] for c in countries}
    head = (["Country"] if show_country else []) + ["Contest", "When", "Date status", "Checked"]
    out = ['<div class="rg"><div class="rg-scroll"><table class="rg-table"><thead><tr>']
    out += [f"<th>{h}</th>" for h in head]
    out.append("</tr></thead><tbody>")
    for k in contests:
        body = escape(k["body"])
        if k["territory"] != names[k["country"]]:
            body += f' <span class="rg-muted">· {escape(k["territory"])}</span>'
        checked = VERIFICATION_LABEL[k["verification"]]
        if k["verification"] != "opened":
            checked = f'<span class="rg-flag">{checked}</span>'
        if k.get("source_url"):
            checked += f' · <a href="{escape(k["source_url"], quote=True)}">source</a>'
        out.append("<tr>")
        if show_country:
            out.append(f'<td class="rg-nowrap">{escape(names[k["country"]])}</td>')
        out.append(f'<td>{body}<br><span class="rg-id">{escape(k["contest_id"])}</span></td>')
        out.append(f"<td>{escape(contest_when(k))}</td>")
        out.append(f'<td class="rg-nowrap">{DATE_STATUS_LABEL[k["date_status"]]}</td>')
        out.append(f"<td>{checked}</td></tr>")
    out.append("</tbody></table></div></div>")
    return "".join(out)
