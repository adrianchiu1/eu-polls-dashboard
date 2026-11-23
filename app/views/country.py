"""Country tab: the six zones of SPEC.md section 5, built as a list of blocks.

1 status strip · 2 headline panel · 3 recent polls · 4 parliamentary subsection (presidential-first
tabs) · 5 sub-national sections · 6 how this tab is defined. Only this country's files are read.
"""
from __future__ import annotations

import datetime as dt
from html import escape
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from app import charts, components, data, logic
from app.blocks import Columns, Expander, Figure, Html, Table
from pipeline import config, model, parties

RECENT_POLLS = 10


def _today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def _rg(html: str) -> Html:
    return Html(f'<div class="rg">{html}</div>')


# ----------------------------------------------------------------------------- zone 1
def status_strip(country: dict, contests: list[dict], quality: dict, results: pd.DataFrame, today: dt.date) -> list:
    blocks = []
    national = [k for k in contests if k["tier"] == "national"]
    for k in national:
        ph = logic.phase(k, today, results)
        when = components.contest_when(k)
        if k["status"] == "called" and ph == "upcoming":
            days = (k["date"] - today).days
            blocks.append(_rg(f'<p class="rg-banner">Election called. {escape(k["body"])}: {escape(when)}, '
                              f'{"today" if days == 0 else f"in {days} days"}.</p>'))
        elif ph == "result_pending":
            blocks.append(_rg(f'<p class="rg-banner">Result pending. {escape(k["body"])} voted on {escape(when)}; '
                              "the official result is not in the data yet. Final polls are shown.</p>"))
        elif ph == "post_election":
            blocks.append(_rg(f'<p class="rg-banner">{escape(k["body"])} voted on {escape(when)}. '
                              "Showing the result against the final polls.</p>"))
    cells = []
    for k in national:
        target = k.get("date") or k.get("deadline")
        if target and target >= today:
            countdown = f"{(target - today).days} days" + ("" if k.get("date") else " at most")
        else:
            countdown = "held" if target else ""
        cells.append(f'<div class="rg-stat"><span class="rg-muted">{escape(k["body"])}</span>'
                     f"<b>{escape(components.contest_when(k))}</b>"
                     f'<span>{countdown + " · " if countdown else ""}<span class="rg-pill">{components.DATE_STATUS_LABEL[k["date_status"]]}</span></span></div>')
    entries = [quality["contests"].get(k["contest_id"]) for k in contests]
    entries = [e for e in entries if e]
    latest = max((e["latest_poll_date"] for e in entries if e.get("latest_poll_date")), default=None)
    as_of = quality.get("data_as_of")
    cells.append('<div class="rg-stat"><span class="rg-muted">Latest poll</span>'
                 f'<b>{components.fmt_date(latest) if latest else "None yet"}</b>'
                 f'<span>Data as of {escape(as_of[:16].replace("T", " ") + " UTC") if as_of else "no fetch yet"}</span></div>')
    blocks.append(_rg(f'<div class="rg-status">{"".join(cells)}</div>'))
    stale = [e for e in entries if e.get("parser_status") in ("stale", "failed")]
    names = {k["contest_id"]: f'{k["body"]}, {k["territory"]}' for k in contests}
    for e in stale:
        last = e.get("last_successful_pull")
        blocks.append(_rg(f'<p class="rg-banner rg-warn"><b>Stale.</b> The last fetch for {escape(names[e["contest_id"]])} '
                          f'failed, so the figures are from {escape(last[:10]) if last else "no successful fetch"}.</p>'))
    return blocks


# ----------------------------------------------------------------------------- zones 2 and 3
def _recent_polls_html(polls: pd.DataFrame, cc: str, party_ids: list[str], unit: str) -> str:
    head_polls = polls[(polls["round"] == 1) & polls["is_headline_lineup"].astype(bool)]
    order = (head_polls.drop_duplicates("poll_id").sort_values(["fieldwork_end", "poll_id"], ascending=False)
             .head(RECENT_POLLS))
    shorts = [parties.display(cc, p)["short"] for p in party_ids]
    out = ['<div class="rg-scroll"><table class="rg-table rg-small"><thead><tr><th>Pollster</th><th>Client</th>'
           "<th>Fieldwork</th><th>Sample</th>"]
    out += [f'<th class="rg-num">{escape(s)}</th>' for s in shorts]
    out.append("<th>Source</th></tr></thead><tbody>")
    suffix = "" if unit == "seats" else "%"
    for row in order.itertuples():
        values = head_polls[head_polls["poll_id"] == row.poll_id].set_index("party_id")["value"]
        start = row.fieldwork_start
        span = components.fmt_date(row.fieldwork_end.date())
        if pd.notna(start) and start != row.fieldwork_end:
            span = f"{start.day} {start:%b} – {span}"
        marks = "".join(f' <span class="rg-pill rg-watch">{escape(f.replace("_", " "))}</span>'
                        for f in str(row.flags or "").split(";") if f)
        sample = f"{int(row.sample_size):,}" if pd.notna(row.sample_size) else "–"
        out.append(f"<tr><td>{escape(row.pollster)}{marks}</td>"
                   f'<td>{escape(row.client) if isinstance(row.client, str) else "–"}</td>'
                   f'<td class="rg-nowrap">{span}</td><td class="rg-num">{sample}</td>')
        out += [f'<td class="rg-num">{values[p]:g}{suffix}</td>' if p in values.index else '<td class="rg-num rg-muted">–</td>'
                for p in party_ids]
        out.append(f'<td><a href="{escape(row.source_url, quote=True)}">link</a></td></tr>')
    out.append("</tbody></table></div>")
    return "".join(out)


def contest_panel(contest: dict, country: dict, bundle: dict, today: dt.date, order: str, small: bool = False) -> list:
    """Zones 2 and 3 for one contest: standings, trend, spectrum strip, match-ups, recent polls, data."""
    cid, cc, unit = contest["contest_id"], contest["country"], country["unit"]
    polls = bundle["polls"][bundle["polls"]["contest_id"] == cid]
    averages, results = bundle["averages"], bundle["results"]
    ph = logic.phase(contest, today, results)
    if polls.empty:
        return [_rg(f'<p class="rg-muted">Not yet polled. Next: {escape(components.contest_when(contest))}.</p>')]
    if ph == "rolled":
        return [_rg(f'<p class="rg-muted">{escape(contest["body"])} voted on {components.fmt_date(contest["date"])}. '
                    "The tab has rolled to the next cycle, which has no contest in configuration yet.</p>")]
    as_of = contest["date"] if ph in ("result_pending", "post_election") else today
    rows, meta = logic.standings(contest, averages, results, as_of, order)
    blocks: list = []
    if rows.empty or (ph == "upcoming" and (today - meta["date"]).days > 0):
        latest = polls["fieldwork_end"].max().date()
        window = config.settings()["average"]["widened_window_days"]
        blocks.append(_rg(f'<p class="rg-muted">No current average: no poll in the last {window} days. '
                          f"Latest poll {components.fmt_date(latest)}; {polls['poll_id'].nunique()} polls this cycle.</p>"))
        rows, meta = logic.standings(contest, averages, results, latest, order)
        if rows.empty:
            return blocks
        blocks.append(_rg(f'<p class="rg-muted">Figures below are the last average, for {components.fmt_date(meta["date"])}.</p>'))

    compare_label = None
    if ph == "post_election":
        res = results[results["contest_id"] == cid].set_index("party_id")["vote_share"]
        rows["compare"] = rows["party_id"].map(res)
        compare_label = "Result"
    weighting = "weighted by pollster volatility" if meta["weighting"] == "volatility" else "unweighted"
    lead = "Final polls" if ph != "upcoming" else "Average"
    caption = (f'{lead} for {components.fmt_date(meta["date"])}: {meta["n_polls"]} polls by {meta["n_pollsters"]} '
               f'pollsters in {meta["window_days"]} days, {weighting}.')
    if compare_label:
        caption += " The black tick marks the official result."
    notes = "".join(f'<p class="rg-flag">{escape(n)}</p>' for n in logic.flag_notes(meta["flags"]))
    if meta.get("folded"):
        floor = config.settings()["parties"]["own_line_min_average_pct"]
        notes += f'<p class="rg-muted">{meta["folded"]} parties under {floor:g}% are summed into Others.</p>'

    party_ids = list(rows["party_id"])
    shown = [dict(party_id=r.party_id, short=r.short, name=r.name, colour=r.colour) for r in rows.itertuples()
             if r.party_id != model.OTHERS]
    head = polls[(polls["round"] == 1) & polls["is_headline_lineup"].astype(bool)]
    points = head[head["party_id"].isin([p["party_id"] for p in shown])].rename(columns={"fieldwork_end": "date"})
    series = logic.headline_series(averages, cid)
    if ph != "upcoming":
        series = series[series["date"] <= pd.Timestamp(as_of)]
    has_delta = rows["delta_election"].notna().any()
    deltas = ("Hover a bar for the change since the last election and over 30 days."
              if has_delta else "Hover a bar for the change over 30 days. No previous result is in the data for this contest.")
    left = [Figure(charts.ranked_bars(rows, unit, compare_label), f"bars-{cid}"),
            _rg(f'<p class="rg-muted">{deltas}</p>')]
    right = [Figure(charts.trend(points[["date", "party_id", "value", "pollster"]],
                                 series[["date", "party_id", "average"]], shown, unit), f"trend-{cid}")]
    blocks.append(_rg(f"<p>{escape(caption)}</p>{notes}"))
    blocks.append(Columns([left, right], [2, 3]) if not small else Columns([left, right], [1, 1]))

    totals = logic.coalition_totals(contest, averages, as_of)
    if totals:
        suffix = "" if unit == "seats" else "%"
        cells = "".join(
            f'<div class="rg-stat"><span class="rg-muted">{escape(t["name"])}</span><b>{t["total"]:.1f}{suffix}</b>'
            f'<span>{escape(" + ".join(t["members"]))}'
            + (f' · not polled: {escape(", ".join(t["missing"]))}' if t["missing"] else "") + "</span></div>"
            for t in totals)
        blocks.append(_rg(f'<h4>Coalition totals</h4><div class="rg-status">{cells}</div>'
                          '<p class="rg-muted">Sums of the member lists\' averages. Membership is this dashboard\'s '
                          "definition; see how this tab is defined, below.</p>"))

    own = rows[rows["party_id"] != model.OTHERS]
    n_scored = int(own["lr_score"].notna().sum())
    strip = pd.DataFrame(logic.spectrum_order(rows.to_dict("records"))) if n_scored else rows
    blocks.append(Figure(charts.spectrum_strip(strip, unit), f"strip-{cid}"))
    if n_scored == 0:
        note = "Spectrum strip in order of support: none of these has a left-right score yet."
    else:
        note = "Ordered left to right by Chapel Hill Expert Survey score; hover a segment for the score."
        unplaced = [r.short for r in own.itertuples() if pd.isna(r.lr_score)]
        if unplaced:
            note += f" Not yet placed, shown at the end: {', '.join(unplaced)}."
    blocks.append(_rg(f'<p class="rg-muted">{escape(note)}</p>'))

    pairs = logic.matchup_rows(contest, averages, as_of)
    if not pairs.empty:
        blocks.append(_rg("<h4>Second-round match-ups</h4>"
                          '<p class="rg-muted">Each bar is one tested pairing, averaged like the headline. '
                          "Pairings without a poll in the window are left out.</p>"))
        blocks.append(Figure(charts.matchups(pairs), f"pairs-{cid}"))

    blocks.append(_rg(f"<h4>Recent polls</h4>{_recent_polls_html(polls, cc, party_ids[:9], unit)}"))
    show = polls.drop(columns=["poll_id", "retrieved_at"]).copy()
    for col in ("fieldwork_start", "fieldwork_end"):
        show[col] = show[col].dt.strftime("%Y-%m-%d")
    blocks.append(Expander(f"Show data ({polls['poll_id'].nunique():,} polls, {len(show):,} rows)",
                           [Table(show, f"data-{cid}", f"{cid}.csv")]))
    return blocks


# ----------------------------------------------------------------------------- zone 6
def definitions(country: dict, contests: list[dict], bundle: dict) -> list:
    code = country["code"]
    own = config.judgements(code)
    lines = []
    adapters = {s["adapter"]: s for k in contests for s in config.sources(k["contest_id"])
                if not bundle["polls"][bundle["polls"]["contest_id"] == k["contest_id"]].empty}
    if "dawum" in adapters:
        lines.append('Daten von <a href="https://dawum.de/">dawum.de</a> '
                     '(<a href="https://opendatacommons.org/licenses/odbl/1-0/">Open Database License (ODbL)</a>).')
    if "wikipedia" in adapters:
        used = sorted({(s["locator"]) for k in contests for s in config.sources(k["contest_id"])
                       if s["adapter"] == "wikipedia" and "=" in s["selector"]})
        links = ", ".join(f'<a href="https://en.wikipedia.org/wiki/{quote(t.replace(" ", "_"))}">{escape(t)}</a>' for t in used)
        lines.append(f"Polls from English Wikipedia contributors: {links} "
                     '(<a href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0</a>); each row links '
                     "its publication and records the article revision it was read from. Figures were produced by "
                     "the polling organisations named.")
    if any(p.get("lr_source", "").startswith("ches") or p.get("lr_source") == "inherited" for p in parties.load(code)):
        lines.append('Left-right scores: Chapel Hill Expert Survey 2024, general left-right position (0 left to 10 '
                     'right). Rovny, Polk, Bakker, Hooghe, Jolly, Marks, Steenbergen and Vachudova (2025), "The 2024 '
                     'Chapel Hill Expert Survey on political party positioning in Europe", Electoral Studies 97, '
                     '<a href="https://doi.org/10.1016/j.electstud.2025.102981">doi:10.1016/j.electstud.2025.102981</a>; '
                     'data from <a href="https://www.chesdata.eu/ches-europe">chesdata.eu</a>.')
    title = quote(f"Challenge: {code} — ")
    challenge = f"{components.REPO_URL}/issues/new?template=challenge-judgement.md&title={title}"
    html = (f"<h3>How this tab is defined ({len(own)})</h3>" + components.judgement_list_html(own)
            + f'<p><a href="{challenge}">Challenge this</a> · rules that apply to every tab are in the full '
              "register under Method.</p>"
            + ("<h4>Sources</h4>" + "".join(f"<p>{l}</p>" for l in lines) if lines else ""))
    return [_rg(html)]


# ----------------------------------------------------------------------------- the page
def build(code: str, today: dt.date | None = None, order: str = "support", data_dir: Path = data.DATA) -> list:
    today = today or _today()
    country = config.country(code)
    contests = config.contests(code)
    bundle = {"polls": data.polls(code, data_dir), "averages": data.averages(code, data_dir),
              "results": data.results(data_dir)}
    quality = data.quality(data_dir)
    blocks: list = [_rg(f"<h2>{escape(country['name'])}</h2>")]
    blocks += status_strip(country, contests, quality, bundle["results"], today)

    national = [k for k in contests if k["tier"] == "national"]
    pres = next((k for k in national if k["kind"] == "presidential"), None)
    parl = next(k for k in national if k["kind"] == "parliamentary")
    if country["headline_kind"] == "presidential" and pres is not None:
        blocks.append(_rg(f"<h3>{escape(pres['body'])}</h3>"))
        pres_polls = bundle["polls"][bundle["polls"]["contest_id"] == pres["contest_id"]]
        if logic.presidential_polled(pres_polls, today):
            blocks += contest_panel(pres, country, bundle, today, order)
        else:
            blocks.append(_rg(f'<p class="rg-muted">Not yet polled. Next presidential election: '
                              f"{escape(components.contest_when(pres))}.</p>"))
        blocks.append(Expander(f"{parl['body']} · {components.contest_when(parl)}",
                               contest_panel(parl, country, bundle, today, order, small=True), open=True))
    else:
        blocks.append(_rg(f"<h3>{escape(parl['body'])}</h3>"))
        blocks += contest_panel(parl, country, bundle, today, order)

    sub = [k for k in contests if k["tier"] == "subnational"]
    unpolled = []
    visible = []
    for k in sub:
        polls = bundle["polls"][bundle["polls"]["contest_id"] == k["contest_id"]]
        if not logic.subnational_visible(k, polls, today):
            continue
        (visible if not polls.empty else unpolled).append((k, polls))
    if visible or unpolled:
        blocks.append(_rg(f"<h3>{escape(country.get('subnational_tier') or 'Sub-national')}</h3>"))
    for k, polls in visible:
        latest = polls["fieldwork_end"].max().date()
        title = (f"{k['territory']} · {components.contest_when(k)} · {polls['poll_id'].nunique()} polls · "
                 f"latest {components.fmt_date(latest)}")
        blocks.append(Expander(title, contest_panel(k, country, bundle, today, order, small=True)))
    if unpolled:
        names = ", ".join(f"{k['territory']} ({components.contest_when(k)})" for k, _ in unpolled)
        blocks.append(_rg(f'<p class="rg-muted">Not yet polled: {escape(names)}.</p>'))
    blocks += definitions(country, contests, bundle)
    return blocks


def render(code: str, order: str = "support") -> None:
    from app.blocks import to_streamlit

    to_streamlit(build(code, order=order))
