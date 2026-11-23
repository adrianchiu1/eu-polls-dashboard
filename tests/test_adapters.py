"""Adapters against saved fixtures: one pinned Wikipedia revision per pilot contest, one DAWUM file.

A layout change must fail loudly, never produce quietly wrong rows.
"""
import datetime as dt
import gzip
import json
from pathlib import Path

import pytest

from pipeline import config, model
from pipeline.adapters import dawum, wikipedia, wikitable
from pipeline.adapters.base import AdapterError
from pipeline.parties import Resolver

FIX = Path(__file__).resolve().parent / "fixtures"
NOW = dt.datetime(2026, 11, 23, 9, 0, tzinfo=dt.timezone.utc)
PILOT = ["fr-pres-2027", "fr-parl-next", "it-parl-2027", "es-parl-2026", "uk-parl-next"]
PHASE2 = ["nl-parl-next", "be-parl-2029", "at-parl-2029", "pt-parl-2029", "ie-parl-next", "gr-parl-2027",
          "pl-parl-2027", "hu-parl-2030", "cz-parl-2029", "no-parl-2029", "fi-parl-2027", "dk-parl-next"]
WIKI = PILOT + PHASE2


def contest(cid):
    return next(k for k in config.contests() if k["contest_id"] == cid)


def wiki_fixture(cid):
    path = sorted((FIX / "wikipedia").glob(f"{cid}.*.html.gz"))[-1]
    return path.name.split(".")[-3], gzip.open(path, "rt", encoding="utf-8").read()


def wiki_pull(cid, html=None):
    rev, saved = wiki_fixture(cid)
    k = contest(cid)
    return wikipedia.parse(html or saved, k, config.sources(cid)[0], Resolver(k["country"]), rev, NOW,
                           unit=config.country(k["country"])["unit"])


@pytest.fixture(scope="module")
def pulls():
    return {cid: wiki_pull(cid) for cid in WIKI}


@pytest.fixture(scope="module")
def dawum_db():
    path = sorted((FIX / "dawum").glob("*.json.gz"))[-1]
    return json.loads(gzip.open(path, "rt", encoding="utf-8").read())


# ------------------------------------------------------------------ small parsers
@pytest.mark.parametrize("text, year, want", [
    ("18– 20 Nov", 2026, (dt.date(2026, 11, 18), dt.date(2026, 11, 20))),
    ("16 Nov", 2026, (None, dt.date(2026, 11, 16))),
    ("1 Sep–22 Nov", 2026, (dt.date(2026, 9, 1), dt.date(2026, 11, 22))),
    ("31 Dec–3 Jan", 2025, (dt.date(2024, 12, 31), dt.date(2025, 1, 3))),
    ("30– 31 Mar 2023", None, (dt.date(2023, 3, 30), dt.date(2023, 3, 31))),
    ("28 Oct – 2 Nov 2026", None, (dt.date(2026, 10, 28), dt.date(2026, 11, 2))),
    ("?–17 Nov", 2026, (None, dt.date(2026, 11, 17))),
])
def test_parse_dates(text, year, want):
    assert wikipedia.parse_dates(text, year) == want


@pytest.mark.parametrize("text", ["18–20 Nov", "soon", "31 Feb 2026", ""])
def test_parse_dates_refuses_what_it_cannot_read(text):
    assert wikipedia.parse_dates(text, None if "Nov" in text else 2026) is None


@pytest.mark.parametrize("text, want", [
    ("30%", 30.0), ("31.7 130", 31.7), ("2% YP 0% Other 2", 2.0), ("4.9 1.6 – Other", 4.9), ("19,5", 19.5),
    ("–", None), ("—", None), ("?", None), ("? 10/12", None), ("Did not exist", None), ("", None),
])
def test_parse_value(text, want):
    assert wikipedia.parse_value(text) == want


def test_grid_expands_spans():
    html = ('<h2>T</h2><table class="wikitable"><tr><th rowspan="2">Firm</th><th colspan="2">Bloc</th></tr>'
            "<tr><th>A</th><th>B</th></tr><tr><td rowspan=\"2\">X</td><td colspan=\"2\">40</td></tr>"
            "<tr><td>25</td><td>15</td></tr></table>")
    t = wikitable.tables(html)[0]
    assert t.n_header_rows == 2 and t.width == 3
    assert t.header_path(1) == ("Bloc", "A") and t.header_path(0) == ("Firm",)
    body = t.body()
    assert body[0][1] is body[0][2] and body[1][0] is body[0][0]


# ------------------------------------------------------------------ Wikipedia fixtures
EXPECT = {   # polls, pollsters, first and last fieldwork end in the pinned revision
    "fr-pres-2027": (80, 10, dt.date(2023, 3, 31), dt.date(2026, 11, 19)),
    "fr-parl-next": (10, 5, dt.date(2025, 2, 6), dt.date(2025, 10, 8)),
    "it-parl-2027": (1172, 31, dt.date(2022, 9, 28), dt.date(2026, 11, 19)),
    "es-parl-2026": (458, 40, dt.date(2025, 1, 3), dt.date(2026, 11, 22)),
    "uk-parl-next": (621, 28, dt.date(2024, 7, 12), dt.date(2026, 11, 20)),
    "nl-parl-next": (45, 3, dt.date(2025, 11, 7), dt.date(2026, 11, 20)),
    "be-parl-2029": (18, 2, dt.date(2024, 9, 17), dt.date(2026, 9, 15)),
    "at-parl-2029": (111, 7, dt.date(2024, 10, 1), dt.date(2026, 11, 10)),
    "pt-parl-2029": (50, 5, dt.date(2025, 6, 15), dt.date(2026, 11, 18)),
    "ie-parl-next": (45, 3, dt.date(2025, 1, 11), dt.date(2026, 10, 30)),
    "gr-parl-2027": (339, 16, dt.date(2023, 9, 26), dt.date(2026, 11, 19)),
    "pl-parl-2027": (362, 14, dt.date(2023, 10, 22), dt.date(2026, 11, 19)),
    "hu-parl-2030": (34, 8, dt.date(2026, 4, 20), dt.date(2026, 11, 13)),
    "cz-parl-2029": (28, 5, dt.date(2026, 1, 7), dt.date(2026, 11, 3)),
    "no-parl-2029": (88, 6, dt.date(2025, 10, 3), dt.date(2026, 11, 2)),
    "fi-parl-2027": (83, 3, dt.date(2023, 5, 2), dt.date(2026, 11, 11)),
    "dk-parl-next": (41, 4, dt.date(2026, 4, 5), dt.date(2026, 11, 22)),
}


@pytest.mark.parametrize("cid", WIKI)
def test_fixture_counts(pulls, cid):
    d = pulls[cid].polls
    got = (d["poll_id"].nunique(), d["pollster"].nunique(), d["fieldwork_end"].min(), d["fieldwork_end"].max())
    assert got == EXPECT[cid]
    assert list(d.columns) == model.POLL_COLUMNS


@pytest.mark.parametrize("cid", WIKI)
def test_every_row_has_provenance_and_a_known_party(pulls, cid):
    d = pulls[cid].polls
    rev, _ = wiki_fixture(cid)
    assert (d["source_rev"] == rev).all()
    assert d["source_url"].str.startswith("http").all()
    known = {p["party_id"] for p in __import__("pipeline.parties", fromlist=["load"]).load(cid[:2].upper())} | {model.OTHERS}
    assert set(d["party_id"]) <= known
    if cid != "cz-parl-2029":      # its 2025 result row gives joint lists the party file does not define
        assert not any("is not in config/parties" in w for w in pulls[cid].warnings)


def test_uk_first_row_matches_the_published_table(pulls):
    d = pulls["uk-parl-next"].polls
    row = d[(d["pollster"] == "Opinium") & (d["fieldwork_end"] == dt.date(2026, 11, 20))].set_index("party_id")
    assert dict(row["value"]) == {"uk-lab": 30, "uk-con": 21, "uk-ref": 22, "uk-ld": 9, "uk-grn": 10,
                                  "uk-snp": 3, "uk-pc": 1, "others": 5}
    assert row["client"].iloc[0] == "The Observer" and row["sample_size"].iloc[0] == 2050
    assert row["fieldwork_start"].iloc[0] == dt.date(2026, 11, 18)
    assert "opinium.com" in row["source_url"].iloc[0]


def test_uk_party_clients_are_flagged(pulls):
    d = pulls["uk-parl-next"].polls
    flagged = set(d[d["flags"].str.contains("party_commissioned")]["client"])
    assert "Restore Britain" in flagged and "The Observer" not in flagged


def test_uk_previous_result_is_the_great_britain_row(pulls):
    res = pulls["uk-parl-next"].results.set_index("party_id")
    assert set(res["contest_id"]) == {"uk-parl-2024"}
    assert res.loc["uk-lab", "vote_share"] == 34.7 and res.loc["uk-con", "vote_share"] == 24.4


def test_spain_joint_list_and_seat_figures(pulls):
    d = pulls["es-parl-2026"].polls
    row = d[(d["pollster"] == "Data10") & (d["fieldwork_end"] == dt.date(2026, 11, 22))].set_index("party_id")
    assert row["client"].iloc[0] == "Okdiario"
    assert row.loc["es-pp", "value"] == 31.7            # '31.7' with '130' seats beneath it
    assert row.loc["es-fa-fv", "value"] == 6.5          # one figure across the FA and FV columns
    assert "es-fa" not in row.index and "es-erc" not in row.index   # '–' means not reported


def test_italy_reads_a_table_whose_header_is_wider_than_its_rows(pulls):
    d = pulls["it-parl-2027"].polls
    row = d[(d["pollster"] == "Termometro Politico") & (d["fieldwork_end"] == dt.date(2026, 11, 19))].set_index("party_id")
    assert row.loc["it-fdi", "value"] == 27.9 and row.loc["it-fn", "value"] == 6.7
    assert row["source_url"].iloc[0].startswith("https://www.termometropolitico.it/")


def test_french_assembly_scenarios_and_joint_lists(pulls):
    d = pulls["fr-parl-next"].polls
    ifop = d[(d["pollster"] == "Ifop") & (d["fieldwork_end"] == dt.date(2025, 10, 8))]
    assert set(ifop["lineup_id"]) == {"default", "alt-2", "alt-3"}
    head = ifop[ifop["is_headline_lineup"]].set_index("party_id")["value"]
    assert head["fr-nfp"] == 24 and head["fr-rn-allies"] == 35 and head.sum() == 100
    second = ifop[ifop["lineup_id"] == "alt-2"].set_index("party_id")["value"]
    assert second["fr-lfi"] == 8 and second["fr-le-pcf-ps"] == 19


def test_french_presidential_lineups(pulls):
    d = pulls["fr-pres-2027"].polls
    first = d[d["round"] == 1]
    per_poll = first[first["is_headline_lineup"]].groupby("poll_id")["lineup_id"].nunique()
    assert (per_poll == 1).all() and len(per_poll) == first["poll_id"].nunique()   # one headline line-up each
    assert first.groupby("poll_id")["lineup_id"].nunique().max() > 1               # several are tested
    second = d[d["round"] == 2]
    assert "r2-le-pen-vs-philippe" in set(second["lineup_id"])
    assert (second.groupby(["poll_id", "lineup_id"])["party_id"].nunique() == 2).all()
    assert not second["lineup_id"].str.contains("bardella").any()                   # 'No longer candidates' is excluded


def test_layout_change_fails_instead_of_guessing():
    _, html = wiki_fixture("uk-parl-next")
    with pytest.raises(AdapterError, match="no table matches"):
        wiki_pull("uk-parl-next", html.replace("National poll results", "Nationwide polls"))
    with pytest.raises(AdapterError, match="no date column"):
        wiki_pull("uk-parl-next", html.replace("Date(s)", "When").replace("conducted", "asked"))
    with pytest.raises(AdapterError, match="no pollster column"):
        wiki_pull("uk-parl-next", html.replace(">Pollster", ">Who"))


def test_unknown_party_column_is_reported_and_folded_into_others():
    _, html = wiki_fixture("uk-parl-next")
    pull = wiki_pull("uk-parl-next", html.replace('title="Reform UK"', 'title="Zzz"').replace(">Ref<", ">Zzz<"))
    assert any("label 'Zzz'" in w for w in pull.warnings)
    assert "uk-ref" not in set(pull.polls["party_id"])


def test_reduce_keeps_what_the_parser_reads():
    _, html = wiki_fixture("fr-parl-next")
    assert wikitable.reduce(html) == html              # already reduced: reducing again changes nothing
    assert len(wikitable.citations(html)) >= 10


# ------------------------------------------------------------------ DAWUM
def test_dawum_parliament_ids_are_read_from_the_file(dawum_db):
    ids = {k["contest_id"]: dawum.parliament_id(dawum_db, k) for k in config.contests("DE")}
    assert ids["de-parl-2029"] == "0" and ids["de-sub-nordrhein-westfalen-2027"] == "10" and len(set(ids.values())) == 8
    with pytest.raises(AdapterError):
        dawum.parliament_id(dawum_db, dict(contest("de-sub-bayern-2028"), territory="Atlantis"))


def test_dawum_bundestag(dawum_db):
    k = contest("de-parl-2029")
    d = dawum.parse(dawum_db, k, Resolver("DE"), NOW, k["previous_date"]).polls
    assert d["poll_id"].nunique() == 426 and d["fieldwork_end"].min() > k["previous_date"]
    insa = d[(d["pollster"] == "INSA") & (d["fieldwork_end"] == dt.date(2026, 11, 20))].set_index("party_id")
    assert dict(insa["value"]) == {"de-afd": 28, "de-union": 19, "de-spd": 14, "de-gruene": 14, "de-linke": 10,
                                   "others": 7, "de-fdp": 5, "de-bsw": 3}
    assert insa["client"].iloc[0] == "BILD am Sonntag" and insa["sample_size"].iloc[0] == 1201
    assert (d["source_url"] == "https://dawum.de/Bundestag/").all()
    assert (d["source_rev"] == dawum_db["Database"]["Last_Update"]).all()


def test_dawum_flags_party_clients_and_folds_unknown_parties(dawum_db):
    k = contest("de-sub-bayern-2028")
    pull = dawum.parse(dawum_db, k, Resolver("DE"), NOW, dt.date(2023, 10, 8))
    d = pull.polls
    assert set(d[d["flags"] == "party_commissioned"]["client"]) == {"CSU"}
    assert any("Bayernpartei" in w for w in pull.warnings)
    assert "de-csu" in set(d["party_id"]) and "de-union" not in set(d["party_id"])
    assert (d["source_url"] == "https://dawum.de/Bayern/").all()


def test_dawum_layout_change_fails(dawum_db):
    broken = {k: v for k, v in dawum_db.items() if k != "Parliaments"}
    with pytest.raises(AdapterError, match="missing blocks"):
        dawum.check(broken)
    with pytest.raises(AdapterError, match="empty"):
        dawum.check(dict(dawum_db, Surveys={}))


# ------------------------------------------------------------------ Phase 2 layouts
def test_netherlands_is_read_in_seats_with_sources_from_the_ref_column(pulls):
    d = pulls["nl-parl-next"].polls
    assert set(d["unit"]) == {"seats"}
    assert (d.groupby("poll_id")["value"].sum() == 150).all()
    assert not d["source_url"].str.contains("wikipedia.org").any()
    res = pulls["nl-parl-next"].results
    assert res["seats"].sum() == 150 and res["vote_share"].isna().all()


def test_belgium_has_three_regional_panels(pulls):
    d = pulls["be-parl-2029"].polls
    assert set(d["lineup_id"]) == {"flanders", "wallonia", "brussels"}
    assert set(d["region"]) == {"Flanders", "Wallonia", "Brussels"}
    ipsos = d[(d["pollster"] == "Ipsos") & (d["fieldwork_end"] == dt.date(2026, 9, 15))]
    assert ipsos[(ipsos["lineup_id"] == "flanders") & (ipsos["party_id"] == "be-vb")]["value"].iloc[0] == 27.8
    assert ipsos[(ipsos["lineup_id"] == "wallonia") & (ipsos["party_id"] == "be-ps")]["value"].iloc[0] == 29.0
    assert not d["flags"].str.contains("party_commissioned").any()      # 'Le Soir' is not the party LE
    assert set(pulls["be-parl-2029"].results["contest_id"]) == {
        "be-parl-2024-flanders", "be-parl-2024-wallonia", "be-parl-2024-brussels"}


def test_bloc_and_coalition_columns_are_never_read(pulls):
    for cid in ("no-parl-2029", "dk-parl-next", "fi-parl-2027", "cz-parl-2029"):
        sums = pulls[cid].polls.groupby(["poll_id", "lineup_id"])["value"].sum()
        assert sums.max() < 106, cid                     # a bloc column read as a party would push sums far over 100


def test_denmark_reads_logo_headers_and_the_stretched_result_row(pulls):
    pull = pulls["dk-parl-next"]
    vox = pull.polls[(pull.polls["pollster"] == "Voxmeter") & (pull.polls["fieldwork_end"] == dt.date(2026, 11, 22))]
    assert vox.set_index("party_id").loc["dk-social-democrats", "value"] == 20.0
    assert pull.results.set_index("party_id").loc["dk-social-democrats", "vote_share"] == 21.84


def test_method_and_others_columns(pulls):
    hu = pulls["hu-parl-2030"].polls
    assert {"Online", "Phone"} <= set(hu["method"].dropna())
    ie = pulls["ie-parl-next"].polls
    assert model.OTHERS in set(ie["party_id"]) and ie["client"].notna().any()
    assert not ie["source_url"].str.contains("wikipedia.org").any()      # links come from the Sources column


def test_year_is_inferred_when_only_some_rows_print_it():
    texts = ["31 Aug – 7 Sep", "13 Apr – 4 May", "14 – 27 Oct 2025", "14 May – 1 Jun"]
    assert wikipedia.infer_years(texts, None, 2026) == [2026, 2026, None, 2025]
    assert wikipedia.infer_years(texts, 2024, 2026) == [2024] * 4


# ------------------------------------------------------------------ SwedishPolls
def test_swedishpolls():
    from pipeline.adapters import swedishpolls
    path = sorted((FIX / "swedishpolls").glob("Polls.*.csv.gz"))[-1]
    commit = path.name.split(".")[1]
    k = contest("se-parl-next")
    pull = swedishpolls.parse(gzip.open(path, "rt", encoding="utf-8").read(), commit, k, Resolver("SE"), NOW, k["previous_date"])
    d = pull.polls
    assert d["poll_id"].nunique() == 10 and d["fieldwork_end"].min() > k["previous_date"]
    sentio = d[(d["pollster"] == "Sentio") & (d["fieldwork_end"] == dt.date(2026, 11, 19))].set_index("party_id")
    assert sentio.loc["se-s", "value"] == 27.5 and sentio["sample_size"].iloc[0] == 869
    assert "others" not in sentio.index                                  # NA is not a figure
    assert (d["source_rev"] == commit).all() and d["source_url"].str.contains(commit).all()
    with pytest.raises(AdapterError, match="missing columns"):
        swedishpolls.parse("a,b\n1,2\n", commit, k, Resolver("SE"), NOW, k["previous_date"])
