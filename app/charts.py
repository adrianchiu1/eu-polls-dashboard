"""Every chart in the app. Pure functions: data in, a Plotly figure out.

The Streamlit views and scripts/snapshot.py both call these, so a review snapshot shows exactly what
the app shows. Party colours and names come from configuration and are passed in; nothing here reads
files. Text is always drawn in ink colours, never in a party colour.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

INK = "#1b2330"
MUTED = "#5a6577"
GRID = "#e4e8ee"
SURFACE = "#ffffff"
FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'


def _base(fig: go.Figure, height: int, **layout) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=8, b=8), paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family=FONT, size=13, color=INK), hoverlabel=dict(font=dict(family=FONT, size=13)),
        showlegend=False, **layout)
    return fig


def _unit(value: float, unit: str) -> str:
    return f"{value:.0f}" if unit == "seats" else f"{value:.1f}%"


def _signed(value, unit: str) -> str:
    if value is None or pd.isna(value):
        return "–"
    return f"{value:+.0f}" if unit == "seats" else f"{value:+.1f}"


def _text_on(colour: str) -> str:
    """Black or white ink, whichever reads on the given fill."""
    r, g, b = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return "#000000" if 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2] > 0.3 else "#ffffff"


def ranked_bars(rows: pd.DataFrame, unit: str = "pct", compare_label: str | None = None) -> go.Figure:
    """Current average per party as ranked horizontal bars.

    rows: short, name, colour, average, and optionally compare (a second value per party, drawn as a
    thin marker: the election result in the post-election view), delta_election, delta_window.
    """
    rows = rows.iloc[::-1]                                  # Plotly draws the first row at the bottom
    has_delta = "delta_election" in rows or "delta_window" in rows
    label = [_unit(v, unit) for v in rows["average"]]
    hover = []
    for _, r in rows.iterrows():
        lines = [f"<b>{r['name']}</b>", f"Average: {_unit(r['average'], unit)}"]
        if "compare" in rows and pd.notna(r.get("compare")):
            lines.append(f"{compare_label or 'Compared'}: {_unit(r['compare'], unit)}")
        if "delta_election" in rows:
            lines.append(f"Since the last election: {_signed(r.get('delta_election'), unit)}")
        if "delta_window" in rows:
            lines.append(f"Over 30 days: {_signed(r.get('delta_window'), unit)}")
        hover.append("<br>".join(lines))
    fig = go.Figure(go.Bar(
        x=rows["average"], y=rows["short"], orientation="h", marker=dict(color=rows["colour"], cornerradius=4),
        width=0.62, text=label, textposition="outside", textfont=dict(color=INK, size=13), cliponaxis=False,
        hovertext=hover, hoverinfo="text"))
    if "compare" in rows and rows["compare"].notna().any():
        fig.add_trace(go.Scatter(
            x=rows["compare"], y=rows["short"], mode="markers", hoverinfo="skip",
            marker=dict(symbol="line-ns", size=20, line=dict(color=INK, width=2.5))))
    top = float(max(rows["average"].max(), rows["compare"].max() if "compare" in rows else 0))
    fig.update_xaxes(range=[0, top * 1.22], showgrid=True, gridcolor=GRID, zeroline=False,
                     tickfont=dict(color=MUTED), ticksuffix="" if unit == "seats" else "%", fixedrange=True)
    fig.update_yaxes(showgrid=False, tickfont=dict(color=INK, size=13), fixedrange=True, ticksuffix="  ")
    return _base(fig, max(170, 34 * len(rows) + 46), bargap=0.3)


def trend(points: pd.DataFrame, lines: pd.DataFrame, parties: list[dict], unit: str = "pct") -> go.Figure:
    """One dot per poll and one average line per party.

    points: date, party_id, value, pollster.   lines: date, party_id, average.
    parties: dicts with party_id, short, name, colour, in legend order.
    """
    fig = go.Figure()
    suffix = "" if unit == "seats" else "%"
    for p in parties:
        dots = points[points["party_id"] == p["party_id"]]
        if not dots.empty:
            fig.add_trace(go.Scatter(
                x=dots["date"], y=dots["value"], mode="markers", legendgroup=p["party_id"], showlegend=False,
                marker=dict(color=p["colour"], size=5, opacity=0.3), customdata=dots[["pollster"]],
                hovertemplate=f"{p['short']} %{{y}}{suffix} · %{{customdata[0]}}<extra></extra>"))
    for p in parties:
        line = lines[lines["party_id"] == p["party_id"]]
        if not line.empty:
            # a day without a value breaks the line instead of being bridged
            line = line.set_index("date")["average"].asfreq("D").rename("average").reset_index()
            fig.add_trace(go.Scatter(
                x=line["date"], y=line["average"], mode="lines", name=p["short"], legendgroup=p["party_id"],
                line=dict(color=p["colour"], width=2), connectgaps=False,
                hovertemplate=f"{p['short']} %{{y:.1f}}{suffix}<extra></extra>"))
    fig.update_xaxes(showgrid=False, tickfont=dict(color=MUTED), linecolor=GRID, hoverformat="%-d %b %Y")
    fig.update_yaxes(showgrid=True, gridcolor=GRID, zeroline=False, tickfont=dict(color=MUTED),
                     ticksuffix=suffix, rangemode="tozero")
    _base(fig, 380, hovermode="x unified")
    fig.update_layout(showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0,
                                                   font=dict(color=INK, size=12), itemsizing="constant"),
                      margin=dict(l=8, r=8, t=34, b=8))
    return fig


def spectrum_strip(rows: pd.DataFrame, unit: str = "pct") -> go.Figure:
    """One horizontal bar, each segment as wide as its party's average, in the order given.

    The caller orders rows left to right by left-right score. No totals are drawn for any group of
    segments: the strip orders parties, it does not sum blocs.
    """
    fig = go.Figure()
    total = float(rows["average"].sum()) or 1.0
    for _, r in rows.iterrows():
        wide = r["average"] / total > 0.055
        score = r.get("lr_score")
        placed = f"Left-right score: {score:.1f}" if score is not None and pd.notna(score) else "Left-right score: pending"
        fig.add_trace(go.Bar(
            x=[r["average"]], y=[""], orientation="h", name=r["short"],
            marker=dict(color=r["colour"], line=dict(color=SURFACE, width=2)),
            text=f"{r['short']} {_unit(r['average'], unit)}" if wide else "", textposition="inside",
            insidetextanchor="middle", textfont=dict(color=_text_on(r["colour"]), size=12),
            hovertext=f"<b>{r['name']}</b><br>Average: {_unit(r['average'], unit)}<br>{placed}", hoverinfo="text"))
    fig.update_xaxes(visible=False, range=[0, total], fixedrange=True)
    fig.update_yaxes(visible=False, fixedrange=True)
    return _base(fig, 64, barmode="stack", bargap=0.05, uniformtext=dict(minsize=11, mode="hide"))


def matchups(rows: pd.DataFrame) -> go.Figure:
    """Second-round match-ups: one bar per pairing, split between its two candidates.

    rows: label (the pairing), then for each side a/b: short, name, colour, average; n_polls.
    """
    rows = rows.iloc[::-1]
    fig = go.Figure()
    for side in ("a", "b"):
        fig.add_trace(go.Bar(
            x=rows[f"{side}_average"], y=rows["label"], orientation="h",
            marker=dict(color=rows[f"{side}_colour"], line=dict(color=SURFACE, width=2)),
            text=[f"{s} {v:.1f}%" for s, v in zip(rows[f"{side}_short"], rows[f"{side}_average"])],
            textposition="inside", insidetextanchor="start" if side == "a" else "end",
            textfont=dict(color=[_text_on(c) for c in rows[f"{side}_colour"]], size=12),
            hovertext=[f"<b>{n}</b>: {v:.1f}%<br>{k} poll(s) in the average"
                       for n, v, k in zip(rows[f"{side}_name"], rows[f"{side}_average"], rows["n_polls"])],
            hoverinfo="text"))
    fig.add_vline(x=50, line=dict(color=INK, width=1, dash="dot"))
    fig.update_xaxes(visible=False, range=[0, 100], fixedrange=True)
    fig.update_yaxes(showgrid=False, tickfont=dict(color=INK, size=13), fixedrange=True, ticksuffix="  ")
    return _base(fig, 40 * len(rows) + 24, barmode="stack", bargap=0.28)


# The election calendar has no parties, so its three colours are the chart's own: they separate the
# kind of contest and were checked for colour-blind separation and contrast on the chart surface.
CALENDAR_KINDS = {
    "parliamentary": {"label": "Parliament", "colour": "#2a78d6", "symbol": "circle", "size": 15},
    "presidential": {"label": "President", "colour": "#c2410c", "symbol": "square", "size": 14},
    "regional": {"label": "Sub-national", "colour": "#0d9488", "symbol": "diamond", "size": 11},
}


def election_calendar(marks: pd.DataFrame, start, end) -> go.Figure:
    """A calendar of contests: one row per country, one mark per election day, months along the top.

    marks: country, date, kind (a key of CALENDAR_KINDS), firm (True when the date is fixed, False for
    a deadline or an expected window, drawn hollow), title (the mark's hover heading) and detail
    (hover lines, already joined with <br>). `start` and `end` bound the axis; a line marks `start`.
    """
    order = list(dict.fromkeys(marks.sort_values("date")["country"]))[::-1]
    fig = go.Figure()
    for kind, look in CALENDAR_KINDS.items():
        for firm in (True, False):
            rows = marks[(marks["kind"] == kind) & (marks["firm"] == firm)]
            if rows.empty:
                continue
            fig.add_trace(go.Scatter(
                x=rows["date"], y=rows["country"], mode="markers",
                name=look["label"] + ("" if firm else ", date not fixed"), legendgroup=kind,
                marker=dict(symbol=look["symbol"] + ("" if firm else "-open"), size=look["size"],
                            color=look["colour"], line=dict(color=look["colour"] if not firm else SURFACE, width=2)),
                customdata=rows[["title", "detail"]],
                hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<extra></extra>"))
    fig.add_vline(x=pd.Timestamp(start), line=dict(color=MUTED, width=1, dash="dot"))
    fig.add_annotation(x=pd.Timestamp(start), y=0, yref="paper", text="today", showarrow=False, yanchor="top",
                       xanchor="center", font=dict(color=MUTED, size=11))
    fig.update_xaxes(range=[pd.Timestamp(start) - pd.Timedelta(days=12), pd.Timestamp(end) + pd.Timedelta(days=12)],
                     side="top", dtick="M1", tickformat="%b<br>%Y", ticklabelmode="period", showgrid=True,
                     gridcolor=GRID, tickfont=dict(color=MUTED, size=11), zeroline=False)
    fig.update_yaxes(categoryorder="array", categoryarray=order, showgrid=True, gridcolor=GRID,
                     tickfont=dict(color=INK, size=13), ticksuffix="  ", fixedrange=True)
    _base(fig, 34 * len(order) + 120, hovermode="closest")
    fig.update_layout(showlegend=True, margin=dict(l=8, r=8, t=56, b=40),
                      legend=dict(orientation="h", yanchor="top", y=-0.02, x=0, font=dict(color=INK, size=12)),
                      hoverlabel=dict(align="left", bgcolor=SURFACE, bordercolor=GRID,
                                      font=dict(family=FONT, size=13, color=INK)))
    return fig
