# European election polling dashboard

A Streamlit dashboard of election polling in 17 European countries plus the UK, built by Claude Code
from the agreed spec. Phase 2 is in place: every one of the 18 tabs has its national panel. A daily
pipeline fetches polls from DAWUM, Wikipedia and SwedishPolls, validates them and computes the
volatility-weighted average, and the app shows each country in six zones. Sub-national contests
outside Germany arrive in Phase 3.

## Run it

```bash
pip install -r requirements-dev.txt
python -m pytest -q
streamlit run app/streamlit_app.py
python scripts/snapshot.py --out snapshots/review.html overview DE FR method
python -m pipeline.run                              # live fetch into data/
python -m pipeline.run --offline tests/fixtures --data-dir /tmp/data   # same run on saved fixtures
```

## How to use it

1. Create a **public** GitHub repository and push this folder's contents to it.
2. Open the repository in Claude Code and say:
   *"Read CLAUDE.md and SPEC.md, run tools/validate_config.py, then start Phase 0."*
3. Review the rendered artifact Claude Code produces at the end of each phase before it continues.

## What is in the kit

| Path | What it is |
| --- | --- |
| `SPEC.md` | The full build spec: scope, calendar, per-country judgements, data model, architecture, review process, build plan, decisions |
| `CLAUDE.md` | Standing instructions Claude Code reads on every session |
| `docs/AVERAGING.md` | The volatility-weighted 30-day average, with every edge case pinned down |
| `docs/DATA_SOURCES.md` | Sources, access routes, licences, and what is still unverified |
| `docs/PLATFORM_NOTES.md` | Streamlit Community Cloud limits; how review artifacts are produced |
| `config/settings.yaml` | Every threshold |
| `config/countries.yaml` | The 18 tabs, their unit and headline kind |
| `config/contests.yaml` | The election calendar as of 23 Nov 2026, each row with its source and verification status |
| `config/judgements.yaml` | The seeded judgement register: 42 entries, 8 on watch |
| `config/sources.yaml` | Which source feeds which contest (pilot countries first) |
| `config/parties/` | Template and notes for party files; none are seeded |
| `schemas/` | JSON Schemas for the configuration, column list for the data files |
| `tools/validate_config.py` | Validates configuration against the schemas and checks cross-references |
| `tests/fixtures/averaging/` | Synthetic polls, a reference implementation, and expected values |
| `ops/weekly-check-prompt.md` | The prompt for the weekly judgement check (a Claude scheduled task) |
| `.github/` | Issue template for challenging a judgement; pull-request template for proposing a change |
| `NOTICE-DATA.md` | Draft data attribution and licence notice |

## Before the build starts

- [ ] Confirm the team may use a public URL hosted outside work systems.
- [ ] Link a Streamlit Community Cloud account to the repository.
- [ ] Download the Chapel Hill Expert Survey 2024 file; confirm its terms of use.
- [ ] Accept that the app sleeps after 12 idle hours and takes one click to wake.
- [ ] Choose a licence for the code (`LICENSE` is deliberately absent).

## Check the kit

```bash
pip install pyyaml jsonschema pandas numpy
python tools/validate_config.py
python tests/fixtures/averaging/build_fixtures.py --check
```

Both commands should end with `OK`. `requirements-dev.txt` installs the same packages, pinned.
