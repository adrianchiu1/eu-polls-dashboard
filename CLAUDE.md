# CLAUDE.md — standing instructions for this repository

You are building a Streamlit dashboard of European election polling from an agreed spec. The owner (AC)
wants the spec implemented, not redesigned. Read this file, then `SPEC.md`, before writing code.

## What this is

- 18 country tabs (17 European countries + UK), polling for national and sub-national elections.
- A daily GitHub Actions pipeline fetches open polling data, normalises it and commits data files.
- A Streamlit app on Streamlit Community Cloud reads those files and redeploys on each push.
- Every classification call lives in `config/judgements.yaml` and changes only by pull request.

## Where the truth is

1. `SPEC.md` — what to build. If code and spec disagree, the spec wins until AC changes it.
2. `docs/AVERAGING.md` — the headline average, every edge case. Fixtures in `tests/fixtures/averaging/`.
3. `docs/DATA_SOURCES.md` — sources, access, licences, and what is still unverified.
4. `docs/PLATFORM_NOTES.md` — Streamlit Community Cloud limits and how review artifacts are made.
5. `config/` — seeded configuration. `schemas/` — its JSON Schemas. `tools/validate_config.py` checks it.

Current state: Phase 0 scaffold. The app shell (`app/`) shows the calendar and the judgement register
from configuration, `scripts/snapshot.py` renders the same pages to HTML, and `tests.yml` runs the
checks. `pipeline/` holds only the configuration loader: no adapter, validation or averaging code
exists yet, and `data/` is empty.

## Rules that do not bend

- **Judgements change by pull request only.** Never edit `config/judgements.yaml`, the tier or kind of a
  contest, a headline rule, or a party's left-right score in a commit of your own. Open a pull request
  using `.github/PULL_REQUEST_TEMPLATE/judgement_proposal.md` and stop for AC's approval.
- **Presidential-first.** In FR, AT, PT, IE, FI, CZ and PL the presidential contest headlines the tab.
  The parliamentary contest is the first foldable subsection, open by default. With fewer than three
  presidential polls the headline shows the next date and "not yet polled".
- **Open data only.** Wikipedia (CC BY-SA 4.0), DAWUM (ODbL), SwedishPolls. Do not add Europe Elects,
  PolitPro or scraped aggregator data. Keep `NOTICE-DATA.md` and the app's attribution lines current.
- **Fail closed.** Never commit an empty or partially parsed dataset. On a failed pull, keep the last
  good file and mark the contest stale in `data/quality.json`.
- **Provenance on every row.** Publication link plus pinned source revision.
- **No bloc totals.** The spectrum module orders parties left to right. It never sums left, centre and
  right.
- **Settings are settings.** Thresholds come from `config/settings.yaml`. Do not hard-code them.
- **One chart code path.** Charts are pure functions in `app/charts.py` returning figures. The Streamlit
  views and `scripts/snapshot.py` both call them.
- **Only the open country loads.** Do not read or draw 18 countries on every rerun.

## Order of work

Phase 0 (set-up), then Phase 1 (pilot: DE, FR, IT, ES, UK). Full plan in `SPEC.md` section 9.

1. Run `python tools/validate_config.py`. It must pass before and after any config change.
2. DAWUM adapter (Germany, Bundestag and Länder) to prove the data model end to end.
3. Wikipedia adapter against saved fixtures, one pilot country at a time: FR, IT, ES, UK.
4. `pipeline/validate.py`, then `pipeline/average.py`. The average must reproduce
   `tests/fixtures/averaging/expected.json` to 1e-6 before anything else uses it.
5. App: country view (six zones), then Overview and Method.
6. `scripts/snapshot.py`, then the first review artifact.
7. Workflows: `tests.yml` first, `fetch.yml` once the pipeline is green locally.

## Verify before relying on it

These are flagged because nobody has checked them yet:

- Entries in `config/sources.yaml` with `verified: false`: the Wikipedia article titles are best
  guesses. Resolve each through the MediaWiki API and correct the file in your first pull request.
- Entries in `config/contests.yaml` with `verification` other than `opened`: re-check the date.
- DAWUM parliament ids: read them from the API's `Parliaments` block; none are stored here.
- The Chapel Hill 2024 file: column names, party ids, terms of use. Until it is checked, leave
  `lr_score` empty and `lr_source: pending`; do not invent scores.
- The current Streamlit API for tabs. If `st.tabs` runs every tab's code on each rerun, use a
  tab-styled selector bound to a URL query parameter instead.
- Python and Streamlit versions that Community Cloud currently supports. Pin both.

## Review artifacts

AC reviews rendered output, not code. At each phase gate:

1. Run `scripts/snapshot.py` to render the tabs in scope to self-contained HTML (charts inlined, real
   data, no server needed).
2. Publish the HTML as a private Claude artifact and give AC the link, or attach the file if no
   artifact tool is available in your session.
3. Say in three lines what changed since the last one and what you want AC to look at.

Do not start the next phase until AC has answered.

## Testing

- Averaging: reproduce every scenario in `tests/fixtures/averaging/expected.json`.
- Parsers: one pinned Wikipedia revision per pilot contest, saved under `tests/fixtures/wikipedia/`.
  A layout change must fail a test.
- Validation: share sums, date order, duplicates, swing flag.
- Config: `tools/validate_config.py` in CI.

## When to ask AC, when to decide

Decide yourself: code structure, library choices, chart details, naming, test design, anything
reversible. Say what you chose in the pull request.

Ask AC first: anything that changes what a reader sees as the definition of a tab (tiers, headline,
party grouping, pollster inclusion, left-right placement), any new data source, anything that touches
licences, and anything that makes the repository or app less public or more public than it is.

## Conventions

- Country codes as in `config/countries.yaml` (UK, not GB; SE, not SW).
- Dates ISO 8601, UTC. A poll's date is its `fieldwork_end`.
- Contest ids as in `config/contests.yaml`: `<cc>-<pres|parl|sub>-...`.
- Commit data and code separately. Data commits by the workflow start with `data:`.
