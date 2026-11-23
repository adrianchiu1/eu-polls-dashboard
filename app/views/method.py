"""Method tab: the averaging and inclusion rules, current pollster weights, the full judgement
register and the election calendar it rests on."""
from __future__ import annotations

from html import escape
from pathlib import Path

from app import components, data
from pipeline import config


def rules_html() -> str:
    s = config.settings()
    a, t, p, v = s["average"], s["thin_polling"], s["parties"], s["validation"]
    items = [
        f"The headline is a weighted mean of polls whose fieldwork ended in the last {a['window_days']} days. "
        "A poll's date is the last day of its fieldwork.",
        "Each pollster's weight is one over its volatility squared, capped at "
        f"{a['weight_cap_multiple_of_median']:g} times the median, and split equally across its polls in the window.",
        "Volatility is the spread of a pollster's figures around the other pollsters' consensus over the last "
        f"{a['lookback_days']} days, with its own steady lean removed. A pollster with fewer than "
        f"{a['min_polls_for_own_volatility']} polls takes the median volatility.",
        f"With fewer than {a['min_pollsters_in_window']} pollsters in the window it widens to "
        f"{a['widened_window_days']} days and is flagged. Sub-national contests use the unweighted mean of each "
        f"pollster's latest poll in {t['window_days']} days, flagged.",
        "Polls count from the day after the previous election to the same body. Party-commissioned polls are "
        "shown in the table and left out of the average.",
        f"A party has its own line at an average of {p['own_line_min_average_pct']:g}% or more; the rest are summed "
        "into Others. Shares are not rescaled to 100.",
        f"A poll is left out when its shares sum outside {v['share_sum_min_pct']:g}–{v['share_sum_max_pct']:g}%, "
        "its dates are out of order or in the future, or it duplicates another poll. A swing above "
        f"{v['swing_flag_points']:g} points from a pollster's previous poll is flagged, not removed.",
    ]
    return ('<div class="rg"><h2>How the numbers are made</h2><ul>' + "".join(f"<li>{escape(i)}</li>" for i in items)
            + '</ul><p class="rg-muted">The exact rule and its edge cases are in docs/AVERAGING.md.</p></div>')


def weights_html(data_dir: Path = data.DATA) -> str:
    w = data.weights(data_dir)
    if w.empty:
        return ""
    names = {k["contest_id"]: f'{config.country(k["country"])["name"]} · {k["body"]}' for k in config.contests()}
    out = ['<div class="rg"><h2>Pollster weights today</h2>'
           '<p class="rg-muted">Contests whose headline is volatility-weighted. Weight shares sum to 100% per contest.</p>']
    for cid, g in w.groupby("contest_id", sort=False):
        g = g.sort_values("weight_share", ascending=False)
        rows = "".join(
            f"<tr><td>{escape(r.pollster)}</td><td class='rg-num'>{r.volatility:.2f}</td>"
            f"<td>{'Own' if r.volatility_source == 'own' else 'Median (too few polls)'}</td>"
            f"<td class='rg-num'>{r.n_polls_lookback}</td><td class='rg-num'>{r.n_polls_in_window}</td>"
            f"<td class='rg-num'>{100 * r.weight_share:.1f}%</td></tr>" for r in g.itertuples())
        out.append(f'<details class="rg-entry"><summary><span class="rg-q">{escape(names.get(cid, cid))}</span>'
                   f'<span class="rg-short">{len(g)} pollsters in the window on {escape(str(g["date"].iloc[0])[:10])}</span></summary>'
                   '<div class="rg-body"><div class="rg-scroll"><table class="rg-table rg-small"><thead><tr><th>Pollster</th>'
                   '<th class="rg-num">Volatility (points)</th><th>Estimate</th><th class="rg-num">Polls in 12 months</th>'
                   '<th class="rg-num">Polls in window</th><th class="rg-num">Weight share</th></tr></thead>'
                   f"<tbody>{rows}</tbody></table></div></div></details>")
    return "".join(out) + "</div>"


def page_html(data_dir: Path = data.DATA) -> str:
    countries = config.countries()
    return (
        rules_html() + weights_html(data_dir)
        + '<div class="rg"><h2>Judgement register</h2>'
        "<p>Every classification call the dashboard makes is one entry here. Entries change only by "
        "pull request approved by the owner.</p></div>"
        + components.register_html(config.judgements(), countries)
        + '<div class="rg"><h2>Election calendar</h2>'
        "<p>Every contest in configuration, with how its date was checked.</p></div>"
        + components.calendar_html(config.contests(), countries)
    )


def render() -> None:
    import streamlit as st

    st.html(page_html())
