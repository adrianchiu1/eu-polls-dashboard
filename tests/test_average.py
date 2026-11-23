"""pipeline/average.py reproduces every case in tests/fixtures/averaging/expected.json."""
import json
from pathlib import Path

import pandas as pd
import pytest

from pipeline import average, model

FIX = Path(__file__).resolve().parent / "fixtures" / "averaging"
EXPECTED = json.loads((FIX / "expected.json").read_text(encoding="utf-8"))
TOL = EXPECTED["tolerance"]


def load(name: str) -> pd.DataFrame:
    return pd.read_csv(FIX / name, parse_dates=["fieldwork_start", "fieldwork_end"])


def test_settings_file_matches_the_fixture_settings():
    """The fixtures were built with the thresholds in config/settings.yaml."""
    s = average.settings()
    for key, value in EXPECTED["settings"].items():
        assert s[key] == value, key


@pytest.mark.parametrize("name", sorted(EXPECTED["cases"]))
def test_case(name):
    case = EXPECTED["cases"][name]
    want = case["result"]
    got = average.Averager(load(case["fixture"]), tier=case["tier"]).at(case["date"])
    for key in ("date", "weighting", "window_days", "flags", "n_polls", "n_pollsters"):
        assert got[key] == want[key], key
    assert set(got["averages"]) == set(want["averages"])
    for party, value in want["averages"].items():
        assert got["averages"][party] == pytest.approx(value, abs=TOL), party
    assert set(got["pollsters"]) == set(want["pollsters"])
    for h, exp in want["pollsters"].items():
        mine = got["pollsters"][h]
        assert mine["volatility"] == pytest.approx(exp["volatility"], abs=TOL), h
        assert mine["weight_share"] == pytest.approx(exp["weight_share"], abs=TOL), h
        for key in ("volatility_source", "capped", "n_polls_in_window"):
            assert mine[key] == exp[key], (h, key)


def test_point_in_time_ignores_later_polls():
    polls = load("main.csv")
    cut = pd.Timestamp("2026-06-01")
    full = average.Averager(polls).at(cut)
    truncated = average.Averager(polls[polls["fieldwork_end"] <= cut]).at(cut)
    assert full == truncated


def test_own_lean_costs_no_weight():
    a = average.Averager(load("main.csv")).at("2026-11-20")["pollsters"]["Delta"]["volatility"]
    b = average.Averager(load("main_no_lean.csv")).at("2026-11-20")["pollsters"]["Delta"]["volatility"]
    assert a == pytest.approx(b, abs=1e-9)


def test_weight_shares_sum_to_one():
    got = average.Averager(load("cap.csv")).at("2026-11-20")
    assert sum(p["weight_share"] for p in got["pollsters"].values()) == pytest.approx(1.0)
    assert any(p["capped"] for p in got["pollsters"].values())


def test_series_skips_days_without_polls_and_rows_have_the_schema_columns():
    polls = load("thin_subnational.csv")
    series = average.Averager(polls, tier="subnational").series("2026-01-01", "2026-11-20")
    assert series and all(r["flags"] == ["thin_polling"] for r in series)
    rows = average.average_rows("xx-sub-test", "default", 1, series)
    assert list(rows.columns) == model.AVERAGE_COLUMNS
