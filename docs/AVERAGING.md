# The headline average

The headline number for a party is a **30-day rolling mean weighted by pollster volatility**. This file
is the precise definition. `tests/fixtures/averaging/` holds synthetic polls, a reference
implementation and expected values; `pipeline/average.py` must reproduce them to 1e-6.

All numbers below are settings in `config/settings.yaml` under `average` and `thin_polling`.

## Inputs

One contest, one electoral cycle. A poll is **eligible** when:

- its `fieldwork_end` is after the previous election to the same body;
- it is not flagged `party_commissioned`;
- for presidential contests, it is the pollster's headline line-up (judgement FR-001);
- it is not a regional cut of a national contest.

A poll's date is its `fieldwork_end`. "In the N days to t" means `t - N days < fieldwork_end <= t`.

## Steps, for a national contest on day t

1. **Consensus.** For each eligible poll *i* by pollster *h* that ended on day *d*: take every *other*
   pollster's latest poll in the 30 days to *d* (ties broken by later `fieldwork_start`, then higher
   `poll_id`). The consensus for party *p* is the unweighted mean of those polls' figures for *p*. It
   needs at least 2 other pollsters reporting *p*; otherwise the poll has no residual for *p*.
2. **Residual.** `r(i,p) = x(i,p) - consensus(i,p)`.
3. **Noise only.** Over the lookback (the 365 days to *t*), subtract from each residual the mean
   residual of the same pollster and party: `e(i,p) = r(i,p) - mean_{h,p}(r)`.
4. **Volatility.** Pooled standard deviation across parties:
   `sigma_h = sqrt( sum_p sum_i e(i,p)^2 / sum_p (n(h,p) - 1) )`, floored at 0.1 points. A pollster
   needs at least 6 polls with a defined residual in the lookback to get its own `sigma`.
5. **Weights.** Let the window be the 30 days to *t*. For each pollster present in the window:
   - `sigma_h` is its own estimate, or the **median of all own estimates in the contest** if it has none;
   - raw weight `sigma_h^-2`;
   - cap: `min(raw, 3 x median of the raw weights of pollsters present in the window)`;
   - each of its `n_h` polls in the window gets `weight_h / n_h`.
6. **Average.** `A(p,t) = sum_i w_i x(i,p) / sum_i w_i` over window polls that report *p*.

Everything is **point in time**: nothing dated after *t* enters the value for *t*. The trend line is
this statistic for every day of the cycle.

## Fallbacks

| Condition on day t | What happens | `weighting` | `window_days` | Flag |
| --- | --- | --- | --- | --- |
| Fewer than 3 pollsters in the 30-day window | Window widens to 60 days; weights still apply | volatility | 60 | `low_coverage` |
| Fewer than 3 pollsters in the contest hold an own volatility estimate | Unweighted mean of each pollster's latest poll in the window | unweighted | 30 or 60 | `unweighted_no_volatility` |
| The contest is sub-national | Unweighted mean of each pollster's latest poll in 90 days | unweighted | 90 | `thin_polling` |
| No poll in the window | No value for that day | | | |

## Not done, on purpose

- Shares are **not** rescaled to sum to 100.
- No house-effect correction. A pollster's lean is neither penalised nor removed.
- No sample-size weighting and no time decay inside the window.
- A party a pollster does not report is skipped for that poll, not treated as zero.
- "Others" gets no residual and does not enter the volatility.

## Properties worth knowing

These came out of running the reference implementation, not from the design discussion.

- **A pollster's own steady lean costs it nothing.** Shift every figure of one pollster by a constant
  per party and its volatility is unchanged, exactly.
- **But a lean leaks into the others, slightly.** When a leaning pollster drops in and out of another
  pollster's 30-day consensus (because it publishes less often than monthly), its lean looks like noise
  to them. In the `main` fixture a lean of 2.5 points moves the other pollsters' volatilities by less
  than 0.01 points and weight shares by about 0.003. The test bounds it at 0.05 points.
- **Measured volatility is floored by the consensus.** A perfectly steady pollster still shows
  residual noise equal to the noise of the others' mean. With four or five pollsters the weights are
  therefore much closer together than the pollsters' true noise would imply, and the 3x cap seldom
  binds. In the `cap` fixture it takes six pollsters, one of them twenty times steadier, to bind it.
- **Smoothing is rewarded.** A rolling tracker with overlapping samples looks quieter than it is. This
  is judgement G-004, on watch.

## Outputs

`data/averages_<CC>.csv` and `data/pollster_weights.csv`; columns in `schemas/data_columns.yaml`.
`weight_share` is the pollster's share of total weight in the window after the cap, and sums to 1.

## Fixtures

| Case | File | What it proves |
| --- | --- | --- |
| `main_latest` | `main.csv` | The ordinary case: five pollsters, one newcomer on the median volatility |
| `main_midcycle` | `main.csv` | Point in time: the value for 1 June uses nothing after 1 June |
| `main_no_lean_latest` | `main_no_lean.csv` | Same polls without Delta's lean: Delta's volatility is identical |
| `early_cycle_unweighted` | `main.csv` | A month into the cycle nobody has six polls: unweighted, flagged |
| `low_coverage_widened` | `low_coverage.csv` | Two pollsters in 30 days: window widens to 60, flagged |
| `cap_binds` | `cap.csv` | One pollster hits the 3x cap |
| `thin_subnational` | `thin_subnational.csv` | Sub-national: unweighted latest per pollster over 90 days |

Check them with `python tests/fixtures/averaging/build_fixtures.py --check`.

If this file and the reference implementation disagree, or a real case is not covered here, ask AC
before choosing.
