"""Country tab. Phase 0 shows zone 1 (next contests) and zone 6 (how this tab is defined).

Zones 2 to 5 (headline, recent polls, parliamentary subsection, sub-national) arrive in Phase 1.
"""
from __future__ import annotations

from html import escape

from app import components
from pipeline import config


def page_html(code: str) -> str:
    country = config.country(code)
    own = config.judgements(code)
    headline = "Presidential" if country["headline_kind"] == "presidential" else country["parliament"]
    return (
        f'<div class="rg"><h2>{escape(country["name"])}</h2>'
        f'<p class="rg-muted">Headline: {escape(headline)} · unit: '
        f'{"seats" if country["unit"] == "seats" else "vote share"}. Polling panels arrive in Phase 1.</p>'
        "<h3>Next contests</h3></div>"
        + components.calendar_html(config.contests(code), config.countries(), show_country=False)
        + f'<div class="rg"><h3>How this tab is defined ({len(own)})</h3>'
        + components.judgement_list_html(own)
        + '<p class="rg-muted">Rules that apply to every tab are in the full register under Method.</p></div>'
    )


def render(code: str) -> None:
    import streamlit as st

    st.html(page_html(code))
