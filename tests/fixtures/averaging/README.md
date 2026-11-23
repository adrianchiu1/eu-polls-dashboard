# Averaging fixtures

Synthetic polls and the values the headline average must produce for them. The rule itself is in
`docs/AVERAGING.md`.

| File | What it is |
| --- | --- |
| `main.csv` | Five pollsters over one year. Alpha is quiet, Gamma is noisy, Delta leans +2.5 on A and -2.5 on B, Epsilon is a newcomer with three polls |
| `main_no_lean.csv` | The same draws with Delta's lean removed |
| `low_coverage.csv` | `main.csv` with three pollsters silent after 10 Oct 2026 |
| `cap.csv` | Six pollsters, one of them twenty times steadier than the rest |
| `thin_subnational.csv` | Two pollsters, three polls: a sub-national contest |
| `expected.json` | Settings, seven cases with their full results, and two invariants |
| `reference_average.py` | Reference implementation used to produce `expected.json`. Not production code |
| `build_fixtures.py` | `--check` recomputes and compares; `--regenerate` rewrites everything |

Pollster and party names are placeholders. The numbers are simulated and describe no real election.

## Using them

`pipeline/average.py` must reproduce every case in `expected.json` within its `tolerance` (1e-6):
`weighting`, `window_days`, `flags`, `n_polls`, `n_pollsters`, every party average, and for each
pollster its `volatility`, `volatility_source`, `capped` and `weight_share`.

Write the production tests against `expected.json`, not against `reference_average.py`. The reference
is slow and simple on purpose; the production code can be vectorised or incremental.

Do not regenerate the CSVs casually. A different NumPy version may draw different noise, which would
change every expected value. `--check` never regenerates them.
