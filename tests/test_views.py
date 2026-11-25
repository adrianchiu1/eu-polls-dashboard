"""Every page renders from configuration, and the register shows every entry."""
import datetime as dt
from html import escape
from pathlib import Path

import pytest

from app import blocks, components
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
def test_country_page_renders_own_entries_only(code, tmp_path):
    html = blocks.to_html(country.build(code, dt.date(2026, 11, 23), data_dir=tmp_path))
    for j in config.judgements():
        assert (f'id="{j["id"]}"' in html) == (j["country"] == code)
    for k in config.contests(code):
        if k["tier"] == "national":
            assert escape(k["body"]) in html


def test_presidential_first_listing_order():
    """On a presidential-first tab the national contests come before any sub-national one."""
    tiers = [k["tier"] for k in config.contests("FR")]
    assert tiers == sorted(tiers, key=lambda t: t != "national")


def test_overview_window_comes_from_settings():
    today = dt.date(2026, 11, 23)
    html = overview.page_html(today)
    assert "Data freshness" not in overview.page_html(today, Path("/nonexistent"))
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


def test_spectrum_order_puts_unscored_parties_last():
    from app import logic
    rows = [dict(party_id="a", lr_score=7.0, average=30), dict(party_id="b", lr_score=None, average=20),
            dict(party_id="c", lr_score=2.0, average=10), dict(party_id="others", lr_score=None, average=5)]
    assert [r["party_id"] for r in logic.spectrum_order(rows)] == ["c", "a", "b", "others"]


def test_joint_list_lookup_ignores_coalitions(monkeypatch):
    from pipeline import parties
    rows = [dict(party_id="xx-a", type="party", short="A", name="A"), dict(party_id="xx-b", type="party", short="B", name="B"),
            dict(party_id="xx-bloc", type="alliance", short="Bloc", name="Bloc", members=["xx-a", "xx-b"], coalition=True),
            dict(party_id="xx-a-b", type="alliance", short="A+B", name="A+B", members=["xx-a", "xx-b"])]
    monkeypatch.setattr(parties, "load", lambda cc: rows)
    assert parties.Resolver("XX").alliance({"xx-a", "xx-b"}) == "xx-a-b"
    assert [c["party_id"] for c in parties.coalitions("XX")] == ["xx-bloc"]


def test_expected_windows_place_a_contest_in_time():
    assert config.window_end("about 2027-09-26 (likely, not fixed)") == dt.date(2027, 9, 26)
    assert config.window_end("September 2027, date to confirm") == dt.date(2027, 9, 30)
    assert config.window_end("autumn 2028") == dt.date(2028, 12, 31)
    assert config.window_end("spring 2029") == dt.date(2029, 6, 30)
    assert config.window_end("2029") == dt.date(2029, 12, 31)
    assert config.window_end("not known") is None


def test_calendar_marks_group_contests_sharing_a_day_and_split_rounds():
    today = dt.date(2026, 11, 25)
    ahead = [k for k in config.contests() if today <= config.contest_sort_date(k) <= dt.date(2028, 5, 25)]
    marks = overview.calendar_marks(ahead, today)
    spain = marks[(marks["country"] == "Spain") & (marks["kind"] == "regional")]
    assert len(spain) == 1 and spain["title"].iloc[0].startswith("10 contests: ")      # ten communities, one mark
    france = marks[(marks["country"] == "France") & (marks["kind"] == "presidential")]
    assert sorted(france["date"].dt.date) == [dt.date(2027, 4, 18), dt.date(2027, 5, 2)]   # both rounds
    greece = marks[marks["country"] == "Greece"]
    assert not greece["firm"].iloc[0] and "at the latest" in greece["detail"].iloc[0]   # a deadline is hollow
    fig = overview.charts.election_calendar(marks, today, dt.date(2028, 5, 25))
    assert sum(len(t.x) for t in fig.data) == len(marks)
