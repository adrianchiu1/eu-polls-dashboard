# Data notice (draft)

> Phase 1 status: `data/` now holds DAWUM-derived rows (`polls_DE.csv`) and Wikipedia-derived rows
> (`polls_FR.csv`, `polls_IT.csv`, `polls_ES.csv`, `polls_UK.csv`). No file mixes the two. Party
> files under `config/parties/` reuse Europolls' Party Facts ids and take names and colours from
> Wikipedia table headers; `tests/fixtures/wikipedia/` holds reduced copies of five article
> revisions and `tests/fixtures/dawum/` a cut of the DAWUM database, each under its source's licence.

Draft for the owner to confirm before the repository is published. It records what each source's
licence asks for as read on 23 Nov 2026. It is not legal advice.

## Sources and their terms

| Source | Used for | Licence | What it asks |
| --- | --- | --- | --- |
| English Wikipedia, opinion-polling articles | Polls for most contests | CC BY-SA 4.0 | Credit Wikipedia contributors, link the article revision, state changes, release derived data under the same licence |
| Europolls (Giuseppe Forte), github.com/gfrt0/europolls | Parser approach and party mappings | Code MIT; data CC BY-SA 4.0 | Keep the MIT notice with reused code; credit and share-alike for reused data |
| DAWUM, dawum.de | German federal and state polls | ODC Open Database License (ODbL) 1.0 | Name and link dawum.de and the licence; a published derived database is itself under ODbL |
| SwedishPolls, github.com/MansMeg/SwedishPolls | Swedish polls | MIT and CC0 badges in its README | Credit as good practice |
| Chapel Hill Expert Survey | Left-right scores | None stated on its page (read 23 Nov 2026); it asks for a citation | Not used yet. Republishing scores needs the owner's decision |

## What this repository does about it

- Every poll row carries its `source_url` and pinned `source_rev`.
- The dashboard shows an attribution line per source on every tab that uses it. For DAWUM the wording
  is "Daten von dawum.de (Open Database License (ODbL))", with both links.
- The normalised files under `data/` are released under the licence of the source they derive from:
  CC BY-SA 4.0 for Wikipedia-derived rows, ODbL 1.0 for DAWUM-derived rows. The `adapter` column says
  which is which.
- The individual poll figures were produced by the polling organisations named in each row.

## Still to decide

- The licence for the code in this repository (`LICENSE` is not included in the starter kit).
- Whether mixing CC BY-SA and ODbL rows in one file is acceptable, or whether DAWUM-derived data should
  sit in files of its own. The safe default is separate files per adapter. So far no file mixes them:
  each country file comes from one adapter. `averages_<CC>.csv` and `pollster_weights.csv` are computed
  from those rows and carry the same terms; `pollster_weights.csv` and `results.csv` hold rows from
  both sources, keyed by contest, and need this decision before Phase 5.
