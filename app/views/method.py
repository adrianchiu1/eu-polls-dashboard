"""Method tab: the full judgement register and the election calendar it rests on.

Phase 0 content. The averaging and inclusion rules and the change log join it in Phase 1.
"""
from __future__ import annotations

from app import components
from pipeline import config


def page_html() -> str:
    countries = config.countries()
    return (
        '<div class="rg"><h2>Judgement register</h2>'
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
