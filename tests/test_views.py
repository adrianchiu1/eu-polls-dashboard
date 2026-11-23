"""Every page renders from configuration, and the register shows every entry."""
import datetime as dt

import pytest

from app import components
from app.views import country, method, overview
from pipeline import config

CODES = [c["code"] for c in config.countries()]


def test_eighteen_tabs_in_order():
    assert len(CODES) == 18
    assert CODES[0] == "DE" and CODES[-1] == "UK"


def test_register_shows_every_entry_once_per_group():
    html = method.page_html()
    for j in config.judgements():
        assert html.count(f'id="{j["id"]}"') == 1, j["id"]
    watch = [j for j in config.judgements() if j["status"] == "on_watch"]
    assert html.count('id="watch-') == len(watch)


def test_calendar_shows_every_contest():
    html = method.page_html()
    for k in config.contests():
        assert k["contest_id"] in html


@pytest.mark.parametrize("code", CODES)
def test_country_page_renders_own_entries_only(code):
    html = country.page_html(code)
    for j in config.judgements():
        assert (f'id="{j["id"]}"' in html) == (j["country"] == code)
    for k in config.contests():
        # match the calendar cell; an entry's text may name another country's contest
        assert (f'>{k["contest_id"]}</span>' in html) == (k["country"] == code)


def test_presidential_first_listing_order():
    """On a presidential-first tab the national contests come before any sub-national one."""
    tiers = [k["tier"] for k in config.contests("FR")]
    assert tiers == sorted(tiers, key=lambda t: t != "national")


def test_overview_window_comes_from_settings():
    today = dt.date(2026, 11, 23)
    html = overview.page_html(today)
    assert "es-parl-2026" in html          # 29 Nov 2026, inside the window
    assert "de-parl-2029" not in html      # spring 2029, outside it
    months = config.settings()["contests"]["subnational_window_months"]
    assert f"next {months} months" in html


def test_contest_when_variants():
    assert components.contest_when({"date": dt.date(2027, 4, 18)}) == "18 Apr 2027"
    both = components.contest_when({"date": dt.date(2027, 4, 18), "round_dates": [dt.date(2027, 4, 18), dt.date(2027, 5, 2)]})
    assert both == "18 Apr 2027 and 2 May 2027"
    assert components.contest_when({"date": None, "deadline": dt.date(2027, 7, 25)}) == "By 25 Jul 2027"
    assert components.contest_when({"date": None}) == "No date known"


def test_html_is_escaped():
    j = dict(config.judgements()[0], question="<script>x</script>")
    assert "<script>" not in components.judgement_html(j)


def test_stylesheets_hold_no_markup():
    """Streamlit's HTML sanitiser drops a whole stylesheet that contains an angle bracket."""
    assert "<" not in components.css(dark=True)
