"""Validation rules: share sums, date order, duplicates, swing flag."""
import datetime as dt

import pandas as pd

from pipeline import model
from pipeline.validate import validate

TODAY = dt.date(2026, 11, 23)


def poll(pid, pollster, end, values, start=None, **extra):
    base = {c: None for c in model.POLL_COLUMNS}
    base.update(poll_id=pid, contest_id="xx-parl-test", round=1, lineup_id="default",
                is_headline_lineup=True, pollster=pollster, fieldwork_start=start or end,
                fieldwork_end=end, unit="pct", flags="", adapter="test", source_url="u", source_rev="r")
    base.update(extra)
    return [dict(base, party_id=p, value=v) for p, v in values.items()]


def frame(*polls):
    return pd.DataFrame([r for p in polls for r in p], columns=model.POLL_COLUMNS)


GOOD = {"a": 40.0, "b": 35.0, "others": 25.0}


def test_good_poll_passes_untouched():
    rep = validate(frame(poll("p1", "Alpha", dt.date(2026, 11, 1), GOOD)), today=TODAY)
    assert rep.dropped == 0 and rep.checked == 1 and not rep.warnings
    assert list(rep.polls.columns) == model.POLL_COLUMNS


def test_share_sum_outside_band_is_dropped():
    rep = validate(frame(poll("p1", "Alpha", dt.date(2026, 11, 1), {"a": 40.0, "b": 30.0}),
                         poll("p2", "Beta", dt.date(2026, 11, 2), GOOD)), today=TODAY)
    assert rep.dropped == 1 and set(rep.polls["poll_id"]) == {"p2"}
    assert "shares sum to 70.0%" in rep.warnings[0]


def test_share_sum_can_be_switched_off_for_partial_tables():
    rep = validate(frame(poll("p1", "Alpha", dt.date(2026, 11, 1), {"a": 40.0, "b": 30.0})),
                   today=TODAY, check_sums=False)
    assert rep.dropped == 0


def test_seats_must_sum_to_chamber():
    seats = poll("p1", "Alpha", dt.date(2026, 11, 1), {"a": 80.0, "b": 69.0}, unit="seats")
    assert validate(frame(seats), chamber_size=150, today=TODAY).dropped == 1
    seats = poll("p1", "Alpha", dt.date(2026, 11, 1), {"a": 80.0, "b": 70.0}, unit="seats")
    assert validate(frame(seats), chamber_size=150, today=TODAY).dropped == 0


def test_future_and_reversed_dates_are_dropped():
    rep = validate(frame(poll("p1", "Alpha", dt.date(2026, 11, 24), GOOD),
                         poll("p2", "Beta", dt.date(2026, 11, 1), GOOD, start=dt.date(2026, 11, 3))), today=TODAY)
    assert rep.dropped == 2 and rep.polls.empty
    assert any("future" in w for w in rep.warnings) and any("starts after" in w for w in rep.warnings)


def test_duplicate_keeps_the_first_poll_id():
    rep = validate(frame(poll("p2", "Alpha", dt.date(2026, 11, 1), GOOD),
                         poll("p1", "Alpha", dt.date(2026, 11, 1), GOOD),
                         poll("p3", "Alpha", dt.date(2026, 11, 1), GOOD, lineup_id="alt")), today=TODAY)
    assert rep.dropped == 1 and set(rep.polls["poll_id"]) == {"p1", "p3"}


def test_swing_is_flagged_not_dropped():
    rep = validate(frame(poll("p1", "Alpha", dt.date(2026, 10, 1), GOOD),
                         poll("p2", "Alpha", dt.date(2026, 11, 1), {"a": 28.0, "b": 47.0, "others": 25.0}),
                         poll("p3", "Beta", dt.date(2026, 11, 1), {"a": 28.0, "b": 47.0, "others": 25.0})), today=TODAY)
    assert rep.dropped == 0
    flags = rep.polls.drop_duplicates("poll_id").set_index("poll_id")["flags"]
    assert flags["p2"] == "swing" and flags["p1"] == "" and flags["p3"] == ""
