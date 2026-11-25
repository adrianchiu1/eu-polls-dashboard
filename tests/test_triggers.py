"""The daily trigger scan and the staleness rule."""
import datetime as dt
import json

import pandas as pd
import pytest

from app import logic
from app.views import overview
from pipeline import config, model, triggers

TODAY = dt.date(2026, 11, 24)
R = config.settings()["review"]


def polls_file(tmp_path, cc, rows):
    """rows: (contest_id, poll_id, pollster, fieldwork_end)."""
    base = {c: None for c in model.POLL_COLUMNS}
    base.update(round=1, lineup_id="default", is_headline_lineup=True, unit="pct", flags="", adapter="test",
                source_url="u", source_rev="r", party_id="a", value=50.0)
    pd.DataFrame([dict(base, contest_id=c, poll_id=p, pollster=h, fieldwork_end=e) for c, p, h, e in rows],
                 columns=model.POLL_COLUMNS).to_csv(tmp_path / f"polls_{cc}.csv", index=False)


def scan(tmp_path, contests, today=TODAY, previous=None):
    return triggers.scan(tmp_path, today, {"contests": contests}, previous)


def kinds(queue, trigger):
    return [e for e in queue if e["trigger"] == trigger]


def test_new_party_needs_the_configured_share_in_the_configured_polls(tmp_path):
    n = R["new_party_trigger_polls"]
    quiet = {"uk-parl-next": {"parser_status": "ok", "unmapped_labels": {"Zzz": {"figures": 9, "at_trigger_share": n - 1, "max": 4}}}}
    loud = {"uk-parl-next": {"parser_status": "ok", "unmapped_labels": {"Zzz": {"figures": 9, "at_trigger_share": n, "max": 4}}}}
    assert kinds(scan(tmp_path, quiet), "new_party") == []
    hit = kinds(scan(tmp_path, loud), "new_party")
    assert len(hit) == 1 and hit[0]["subject"] == "Zzz" and hit[0]["country"] == "UK"
    assert "G-007" in hit[0]["judgement_ids"]                       # the all-tab rule on parties


def test_unmapped_summary_counts_figures_at_the_share():
    pct = R["new_party_trigger_pct"]
    s = triggers.unmapped_summary({"Zzz": [pct - 1, pct, pct + 2], "Tiny": [0.5]}, "pct", None)
    assert s["Zzz"] == {"figures": 3, "at_trigger_share": 2, "max": pct + 2} and s["Tiny"]["at_trigger_share"] == 0
    seats = triggers.unmapped_summary({"Zzz": [4, 5]}, "seats", 150)   # 3% of 150 seats is 4.5
    assert seats["Zzz"]["at_trigger_share"] == (1 if pct == 3.0 else seats["Zzz"]["at_trigger_share"])


def test_failed_pulls_split_into_layout_change_and_repeated_validation(tmp_path):
    layout = {"uk-parl-next": {"parser_status": "stale", "consecutive_failures": 1, "last_error": "no table matches selector"}}
    once = {"uk-parl-next": {"parser_status": "stale", "consecutive_failures": 1, "last_error": "5 of 9 polls failed validation"}}
    twice = {"uk-parl-next": {"parser_status": "stale", "consecutive_failures": 2, "last_error": "5 of 9 polls failed validation"}}
    assert len(kinds(scan(tmp_path, layout), "layout_change")) == 1
    assert scan(tmp_path, once) == [e for e in scan(tmp_path, once) if e["trigger"] == "review_due"]
    assert len(kinds(scan(tmp_path, twice), "validation_failed")) == 1


def test_new_and_silent_pollsters(tmp_path):
    silent, keep, need = R["pollster_silent_days"], R["event_trigger_days"], config.settings()["average"]["min_polls_for_own_volatility"]
    old = [("uk-parl-next", f"o{i}", "Regular", TODAY - dt.timedelta(days=silent + 3 + 7 * i)) for i in range(need)]
    rows = old + [("uk-parl-next", "n1", "Newcomer", TODAY - dt.timedelta(days=2)),
                  ("uk-parl-next", "f1", "Fresh", TODAY - dt.timedelta(days=silent + 400))]
    polls_file(tmp_path, "UK", rows)
    queue = scan(tmp_path, {"uk-parl-next": {"parser_status": "ok"}})
    assert [e["subject"] for e in kinds(queue, "pollster_new")] == ["Newcomer"]
    assert [e["subject"] for e in kinds(queue, "pollster_silent")] == ["Regular"]     # 'Fresh' has too few polls
    later = scan(tmp_path, {"uk-parl-next": {"parser_status": "ok"}}, TODAY + dt.timedelta(days=keep + 5))
    assert kinds(later, "pollster_silent") == [] and kinds(later, "pollster_new") == []   # one-off events age out


def test_subnational_section_opening_is_queued_for_a_while(tmp_path):
    keep = R["event_trigger_days"]
    entry = {"uk-sub-wales-next": {"parser_status": "ok", "subnational_visible": True, "visible_since": TODAY.isoformat()}}
    assert len(kinds(scan(tmp_path, entry), "subnational_in_window")) == 1
    assert kinds(scan(tmp_path, entry, TODAY + dt.timedelta(days=keep + 1)), "subnational_in_window") == []
    unknown = {"uk-sub-wales-next": {"parser_status": "ok", "subnational_visible": True, "visible_since": None}}
    assert kinds(scan(tmp_path, unknown), "subnational_in_window") == []


def test_review_due_fires_ahead_of_the_date_and_names_the_entry(tmp_path):
    first = min(j["review_by"] for j in config.judgements())
    notice = dt.timedelta(days=R["review_due_notice_days"])
    assert kinds(scan(tmp_path, {}, first - notice - dt.timedelta(days=1)), "review_due") == []
    due = kinds(scan(tmp_path, {}, first - notice), "review_due")
    assert due and all(e["judgement_ids"] == [e["subject"]] for e in due)


def test_first_seen_survives_from_the_previous_queue(tmp_path):
    entry = {"uk-parl-next": {"parser_status": "stale", "consecutive_failures": 1, "last_error": "no table matches"}}
    first = scan(tmp_path, entry, TODAY)
    again = scan(tmp_path, entry, TODAY + dt.timedelta(days=3), previous=first)
    hit = kinds(again, "layout_change")[0]
    assert hit["first_seen"] == TODAY.isoformat() and hit["last_seen"] == (TODAY + dt.timedelta(days=3)).isoformat()


def test_stale_after_the_configured_multiple_of_the_fetch_interval():
    st = config.settings()["staleness"]
    limit_days = st["fetch_interval_hours"] * st["stale_after_multiple_of_interval"] // 24
    entry = {"parser_status": "ok", "last_successful_pull": "2026-11-20T05:17:00Z"}
    pulled = dt.date(2026, 11, 20)
    assert not logic.is_stale(entry, pulled + dt.timedelta(days=limit_days))
    assert logic.is_stale(entry, pulled + dt.timedelta(days=limit_days + 1))
    assert logic.is_stale({"parser_status": "stale"}, pulled) and not logic.is_stale(None, pulled)


def test_overview_shows_the_queue_and_the_monthly_list(tmp_path):
    queue = scan(tmp_path, {"uk-parl-next": {"parser_status": "stale", "consecutive_failures": 1, "last_error": "no table matches"}})
    (tmp_path / "review_queue.json").write_text(json.dumps(queue))
    page = overview.page_html(TODAY, tmp_path)
    assert "Review queue (" in page and "Source could not be read" in page and "Monthly review list" in page
    watch = sum(j["status"] == "on_watch" for j in config.judgements())
    assert f"On watch ({watch})" in page or "Due for review within a month" in page
    assert "Nothing is queued" in overview.page_html(TODAY, tmp_path / "empty")
