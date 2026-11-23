"""The daily run end to end on saved fixtures: writes, quiet reruns, fail closed, and the app on top."""
import datetime as dt
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from app import blocks, logic
from app.views import country, method, overview
from pipeline import config, model
from pipeline.run import run

FIX = Path(__file__).resolve().parent / "fixtures"
NOW = dt.datetime(2026, 11, 23, 9, 0, tzinfo=dt.timezone.utc)
TODAY = NOW.date()


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("data")
    result = run(["FR", "ES"], out, now=NOW, offline=FIX, log=lambda *_: None)
    assert result["failures"] == []
    return out


def html(code, data_dir, today=TODAY):
    return blocks.to_html(country.build(code, today, data_dir=data_dir))


def test_files_have_the_schema_columns(data_dir):
    assert list(pd.read_csv(data_dir / "polls_FR.csv").columns) == model.POLL_COLUMNS
    assert list(pd.read_csv(data_dir / "averages_FR.csv").columns) == model.AVERAGE_COLUMNS
    assert list(pd.read_csv(data_dir / "pollster_weights.csv").columns) == model.WEIGHT_COLUMNS
    assert list(pd.read_csv(data_dir / "results.csv").columns) == model.RESULT_COLUMNS
    q = json.loads((data_dir / "quality.json").read_text())
    entry = q["contests"]["fr-pres-2027"]
    assert entry["parser_status"] == "ok" and entry["latest_poll_date"] == "2026-11-19"
    assert entry["polls_90d"] > 0 and q["data_as_of"] == "2026-11-23T09:00:00Z"


def test_weight_shares_sum_to_one_per_contest(data_dir):
    w = pd.read_csv(data_dir / "pollster_weights.csv")
    assert not w.empty
    for _, g in w.groupby("contest_id"):
        assert g["weight_share"].sum() == pytest.approx(1.0, abs=1e-4)


def test_a_rerun_with_nothing_new_changes_no_poll_file(data_dir, tmp_path):
    copy = tmp_path / "d"
    shutil.copytree(data_dir, copy)
    again = run(["FR"], copy, now=NOW, offline=FIX, log=lambda *_: None)
    assert again["changed"] == []
    next_day = run(["FR"], copy, now=NOW + dt.timedelta(days=1), offline=FIX, log=lambda *_: None)
    assert "polls_FR.csv" not in next_day["changed"]          # unchanged rows keep their first-seen stamp
    assert "averages_FR.csv" in next_day["changed"]           # the trend gained a day


def test_failed_pull_keeps_the_last_good_rows_and_marks_the_contest_stale(data_dir, tmp_path):
    copy = tmp_path / "d"
    shutil.copytree(data_dir, copy)
    before = (copy / "polls_FR.csv").read_text()
    out = run(["FR"], copy, now=NOW + dt.timedelta(days=1), offline=FIX, fail=("fr-pres-2027",), log=lambda *_: None)
    assert out["failures"] == ["fr-pres-2027"]
    assert (copy / "polls_FR.csv").read_text() == before
    entry = json.loads((copy / "quality.json").read_text())["contests"]["fr-pres-2027"]
    assert entry["parser_status"] == "stale" and entry["last_successful_pull"] == "2026-11-23T09:00:00Z"
    page = html("FR", copy, TODAY + dt.timedelta(days=1))
    assert "<b>Stale.</b>" in page and "President of the Republic" in page
    assert "Stale: last fetch failed" in overview.page_html(TODAY, copy)


def test_failed_first_pull_publishes_nothing(tmp_path):
    out = run(["FR"], tmp_path, now=NOW, offline=FIX, fail=("fr-pres-2027", "fr-parl-next"), log=lambda *_: None)
    assert sorted(out["failures"]) == ["fr-parl-next", "fr-pres-2027"]
    assert not (tmp_path / "polls_FR.csv").exists()
    assert json.loads((tmp_path / "quality.json").read_text())["contests"]["fr-pres-2027"]["parser_status"] == "failed"


def test_france_runs_presidential_first(data_dir):
    page = html("FR", data_dir)
    assert page.index("President of the Republic</h3>") < page.index("<summary>National Assembly")
    assert '<details class="rg-fold" open><summary>National Assembly' in page       # open by default
    assert "Second-round match-ups" in page
    assert "No current average" in page                                           # Assembly: no poll in 60 days
    assert "Wikipedia contributors" in page and "CC BY-SA 4.0" in page


def test_presidential_headline_needs_three_polls(data_dir, tmp_path):
    copy = tmp_path / "d"
    shutil.copytree(data_dir, copy)
    polls = pd.read_csv(copy / "polls_FR.csv", dtype=str, keep_default_na=False)
    pres = polls[polls["contest_id"] == "fr-pres-2027"]
    keep = sorted(pres["poll_id"].unique())[:2]
    polls[(polls["contest_id"] != "fr-pres-2027") | polls["poll_id"].isin(keep)].to_csv(copy / "polls_FR.csv", index=False)
    assert "Not yet polled. Next presidential election: 18 Apr 2027 and 2 May 2027" in html("FR", copy)


def test_spain_election_called_banner(data_dir):
    assert "Election called. Congress of Deputies and Senate: 29 Nov 2026, in 6 days." in html("ES", data_dir)


def test_spain_rolls_after_polling_day(data_dir, tmp_path):
    """SPEC.md section 1: result versus final polls for the configured days, then the next cycle."""
    es = next(k for k in config.contests("ES") if k["contest_id"] == "es-parl-2026")
    days = config.settings()["contests"]["post_election_view_days"]
    none = pd.DataFrame(columns=model.RESULT_COLUMNS)
    result = pd.DataFrame([{"contest_id": "es-parl-2026", "round": 1, "party_id": p, "vote_share": v, "seats": None,
                            "source_url": "https://example.org/result"}
                           for p, v in {"es-pp": 31.0, "es-psoe": 29.5, "es-vox": 17.0}.items()])
    assert logic.phase(es, dt.date(2026, 11, 29), none) == "upcoming"
    assert logic.phase(es, dt.date(2026, 11, 30), none) == "result_pending"
    assert logic.phase(es, dt.date(2026, 11, 30), result) == "post_election"
    assert logic.phase(es, es["date"] + dt.timedelta(days=days), result) == "post_election"
    assert logic.phase(es, es["date"] + dt.timedelta(days=days + 1), result) == "rolled"

    copy = tmp_path / "d"
    shutil.copytree(data_dir, copy)
    pending = html("ES", copy, dt.date(2026, 12, 1))
    assert "Result pending." in pending and "Final polls for 2" in pending
    result.to_csv(copy / "results.csv", index=False)
    after = html("ES", copy, dt.date(2026, 12, 5))
    assert "Showing the result against the final polls." in after and "The black tick marks the official result." in after
    rolled = html("ES", copy, dt.date(2027, 1, 15))
    assert "rolled to the next cycle" in rolled and "bars-es-parl-2026" not in rolled


def test_standings_fold_small_parties_into_others(data_dir):
    es = next(k for k in config.contests("ES") if k["contest_id"] == "es-parl-2026")
    avg = pd.read_csv(data_dir / "averages_ES.csv", parse_dates=["date"], keep_default_na=False)
    rows, meta = logic.standings(es, avg, pd.DataFrame(columns=model.RESULT_COLUMNS), TODAY)
    floor = config.settings()["parties"]["own_line_min_average_pct"]
    own = rows[rows["party_id"] != model.OTHERS]
    assert (own["average"] >= floor).all() and rows["party_id"].iloc[-1] == model.OTHERS
    day = avg[(avg["contest_id"] == "es-parl-2026") & (avg["date"] == avg["date"].max())]
    assert rows["average"].sum() == pytest.approx(day["average"].sum())
    assert meta["weighting"] == "volatility" and meta["n_pollsters"] >= 3


def test_no_bloc_totals_anywhere(data_dir):
    page = html("ES", data_dir).lower()
    for phrase in ("left bloc", "right bloc", "centre bloc", "left total", "right total"):
        assert phrase not in page


def test_method_lists_weights_and_rules(data_dir):
    page = method.page_html(data_dir)
    assert "Pollster weights today" in page and "How the numbers are made" in page
    assert f'{config.settings()["average"]["window_days"]} days' in page


def test_country_without_data_still_renders(tmp_path):
    page = html("DE", tmp_path)
    assert "Not yet polled" in page and "How this tab is defined" in page
