"""The headline average: a 30-day rolling mean weighted by pollster volatility.

The rule is docs/AVERAGING.md. This module must reproduce tests/fixtures/averaging/expected.json to
1e-6. Every number comes from config/settings.yaml through `settings()`.

Input is a wide frame, one row per eligible poll:
    poll_id, pollster, fieldwork_start, fieldwork_end, <one column per party, NaN if not reported>
`eligible_wide` builds it from the long rows of data/polls_<CC>.csv.
"""
from __future__ import annotations

import math
from statistics import median

import numpy as np
import pandas as pd

from pipeline import config, model

META = ["poll_id", "pollster", "fieldwork_start", "fieldwork_end"]


def settings() -> dict:
    """The averaging thresholds, flattened from config/settings.yaml."""
    s = config.settings()
    return dict(s["average"], thin_window_days=s["thin_polling"]["window_days"])


def eligible_wide(polls: pd.DataFrame, s: dict | None = None) -> pd.DataFrame:
    """Long poll rows of ONE contest, line-up and round, to the wide frame of eligible polls.

    Drops party-commissioned polls (when the setting says so) and regional cuts. The caller picks the
    contest, line-up and round, and has already limited rows to the current electoral cycle.
    """
    s = s or settings()
    rows = polls
    if s.get("exclude_party_commissioned", True):
        rows = rows[~model.has_flag(rows["flags"], "party_commissioned")]
    rows = rows[rows["region"].isna() | (rows["region"] == "")]
    if rows.empty:
        return pd.DataFrame(columns=META)
    meta = rows.drop_duplicates("poll_id").set_index("poll_id")[["pollster", "fieldwork_start", "fieldwork_end"]]
    values = rows.pivot_table(index="poll_id", columns="party_id", values="value", aggfunc="first")
    wide = meta.join(values).reset_index()
    wide["fieldwork_end"] = pd.to_datetime(wide["fieldwork_end"])
    wide["fieldwork_start"] = pd.to_datetime(wide["fieldwork_start"]).fillna(wide["fieldwork_end"])
    return wide


class Averager:
    """Point-in-time averages for one contest. Residuals are computed once; `at(t)` is then cheap."""

    def __init__(self, polls: pd.DataFrame, s: dict | None = None, tier: str = "national",
                 no_volatility: tuple[str, ...] = (model.OTHERS,)):
        self.s = s or settings()
        self.tier = tier
        polls = polls.copy()
        polls["fieldwork_end"] = pd.to_datetime(polls["fieldwork_end"])
        polls["fieldwork_start"] = pd.to_datetime(polls["fieldwork_start"]).fillna(polls["fieldwork_end"])
        polls["poll_id"] = polls["poll_id"].astype(str)
        # Sorted so that, among any subset, the last row of a pollster is its latest poll.
        polls = polls.sort_values(["fieldwork_end", "fieldwork_start", "poll_id"]).reset_index(drop=True)
        self.polls = polls
        self.parties = [c for c in polls.columns if c not in META]
        self.n = len(polls)
        epoch = pd.Timestamp("1970-01-01")
        self.end = ((polls["fieldwork_end"] - epoch) // pd.Timedelta(days=1)).to_numpy(dtype=np.int64)
        self.pollsters = sorted(polls["pollster"].unique())
        code = {h: i for i, h in enumerate(self.pollsters)}
        self.code = polls["pollster"].map(code).to_numpy(dtype=np.int64) if self.n else np.zeros(0, np.int64)
        self.x = polls[self.parties].to_numpy(dtype=float) if self.parties else np.zeros((self.n, 0))
        self._vol_party = np.array([p not in no_volatility for p in self.parties], dtype=bool)
        self._res = None

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _day(t) -> int:
        return int((pd.Timestamp(t).normalize() - pd.Timestamp("1970-01-01")) // pd.Timedelta(days=1))

    def _window(self, day: int, days: int) -> np.ndarray:
        """Row indices with fieldwork_end in (day - days, day]. Rows are sorted by date."""
        lo = np.searchsorted(self.end, day - days, side="right")
        hi = np.searchsorted(self.end, day, side="right")
        return np.arange(lo, hi)

    def _latest_per_pollster(self, idx: np.ndarray) -> np.ndarray:
        """Of the given (ascending) rows, the last one of each pollster."""
        if len(idx) == 0:
            return idx
        codes = self.code[idx][::-1]
        _, first = np.unique(codes, return_index=True)
        return np.sort(idx[::-1][first])

    # ------------------------------------------------------------------ steps 1 and 2
    def residuals(self):
        """Each poll's figure minus the leave-one-out consensus, per party.

        Returns arrays sorted by date: (day, pollster code, party index, poll row, residual).
        """
        if self._res is not None:
            return self._res
        s = self.s
        days, codes, parties, rows, values = [], [], [], [], []
        for i in range(self.n):
            idx = self._window(int(self.end[i]), s["consensus_window_days"])
            idx = idx[self.code[idx] != self.code[i]]
            latest = self._latest_per_pollster(idx)
            if len(latest) < s["min_other_pollsters_for_consensus"]:
                continue
            others = self.x[latest]
            count = (~np.isnan(others)).sum(axis=0)
            ok = (count >= s["min_other_pollsters_for_consensus"]) & ~np.isnan(self.x[i]) & self._vol_party
            if not ok.any():
                continue
            mean = np.nansum(others[:, ok], axis=0) / count[ok]
            p_idx = np.nonzero(ok)[0]
            days += [self.end[i]] * len(p_idx)
            codes += [self.code[i]] * len(p_idx)
            parties += list(p_idx)
            rows += [i] * len(p_idx)
            values += list(self.x[i, ok] - mean)
        self._res = (np.array(days, np.int64), np.array(codes, np.int64), np.array(parties, np.int64),
                     np.array(rows, np.int64), np.array(values, float))
        return self._res

    # ------------------------------------------------------------------ steps 3 and 4
    def volatilities(self, t) -> dict:
        """Pooled standard deviation of demeaned residuals per pollster, as of day t."""
        s = self.s
        day = self._day(t)
        r_day, r_code, r_party, r_row, r_val = self.residuals()
        lo = np.searchsorted(r_day, day - s["lookback_days"], side="right")
        hi = np.searchsorted(r_day, day, side="right")
        if hi <= lo:
            return {}
        code, party, row, val = r_code[lo:hi], r_party[lo:hi], r_row[lo:hi], r_val[lo:hi]
        n_parties = max(len(self.parties), 1)
        cell = code * n_parties + party
        size = len(self.pollsters) * n_parties
        n = np.bincount(cell, minlength=size).astype(float)
        total = np.bincount(cell, weights=val, minlength=size)
        squares = np.bincount(cell, weights=val * val, minlength=size)
        with np.errstate(invalid="ignore", divide="ignore"):
            ss = np.where(n > 0, squares - total * total / n, 0.0)
        ss = np.clip(ss, 0.0, None).reshape(len(self.pollsters), n_parties).sum(axis=1)
        dof = np.clip(n - 1, 0, None).reshape(len(self.pollsters), n_parties).sum(axis=1)
        out = {}
        for h in np.unique(code):
            n_polls = int(len(np.unique(row[code == h])))
            if n_polls < s["min_polls_for_own_volatility"] or dof[h] <= 0:
                continue
            sigma = math.sqrt(float(ss[h]) / float(dof[h]))
            out[self.pollsters[h]] = {"sigma": max(sigma, s["volatility_floor_points"]),
                                      "n_polls_lookback": n_polls}
        return out

    # ------------------------------------------------------------------ the average
    def _unweighted(self, t, window: int, flags: list[str]):
        idx = self._window(self._day(t), window)
        if len(idx) == 0:
            return None
        latest = self._latest_per_pollster(idx)
        x = self.x[latest]
        averages = {p: float(np.nanmean(x[:, j])) for j, p in enumerate(self.parties)
                    if not np.isnan(x[:, j]).all()}
        return {"date": pd.Timestamp(t).date().isoformat(), "weighting": "unweighted",
                "window_days": window, "flags": flags, "n_polls": int(len(latest)),
                "n_pollsters": int(len(np.unique(self.code[latest]))), "averages": averages,
                "pollsters": {}}

    def at(self, t):
        """The headline average on day t, or None when no poll is in the window."""
        s = self.s
        if self.n == 0:
            return None
        if self.tier == "subnational":
            return self._unweighted(t, s["thin_window_days"], ["thin_polling"])

        day = self._day(t)
        window, flags = s["window_days"], []
        idx = self._window(day, window)
        if len(np.unique(self.code[idx])) < s["min_pollsters_in_window"]:
            window = s["widened_window_days"]
            flags.append("low_coverage")
            idx = self._window(day, window)
        if len(idx) == 0:
            return None

        vol = self.volatilities(t)
        if len(vol) < s["min_pollsters_with_volatility"]:
            return self._unweighted(t, window, flags + ["unweighted_no_volatility"])

        median_sigma = median(v["sigma"] for v in vol.values())
        present_codes = np.unique(self.code[idx])
        present = [self.pollsters[c] for c in present_codes]
        sigma = {h: (vol[h]["sigma"] if h in vol else median_sigma) for h in present}
        raw = {h: sigma[h] ** -2 for h in present}
        cap = s["weight_cap_multiple_of_median"] * median(raw.values())
        weight = {h: min(raw[h], cap) for h in present}
        counts = np.bincount(self.code[idx], minlength=len(self.pollsters))
        per_poll = np.array([weight[self.pollsters[c]] / counts[c] for c in self.code[idx]])

        x = self.x[idx]
        averages = {}
        for j, party in enumerate(self.parties):
            reported = ~np.isnan(x[:, j])
            if reported.any():
                averages[party] = float((per_poll[reported] * x[reported, j]).sum() / per_poll[reported].sum())
        total = sum(weight.values())
        return {
            "date": pd.Timestamp(t).date().isoformat(), "weighting": "volatility",
            "window_days": window, "flags": flags, "n_polls": int(len(idx)),
            "n_pollsters": int(len(present)), "averages": averages,
            "pollsters": {
                h: {"volatility": sigma[h], "volatility_source": "own" if h in vol else "median",
                    "n_polls_lookback": int(vol[h]["n_polls_lookback"]) if h in vol else 0,
                    "n_polls_in_window": int(counts[c]), "capped": bool(raw[h] > cap),
                    "weight_share": weight[h] / total}
                for h, c in zip(present, present_codes)
            },
        }

    def series(self, start, end) -> list[dict]:
        """The statistic for every day from start to end inclusive; days without a value are skipped."""
        out = []
        for t in pd.date_range(pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize(), freq="D"):
            value = self.at(t)
            if value is not None:
                out.append(value)
        return out


def average_rows(contest_id: str, lineup_id: str, round_: int, results: list[dict]) -> pd.DataFrame:
    """`Averager.series` output as rows of data/averages_<CC>.csv."""
    rows = [
        {"contest_id": contest_id, "lineup_id": lineup_id, "round": round_, "date": r["date"],
         "party_id": party, "average": round(value, 4), "n_polls": r["n_polls"],
         "n_pollsters": r["n_pollsters"], "window_days": r["window_days"],
         "weighting": r["weighting"], "flags": ";".join(r["flags"])}
        for r in results for party, value in r["averages"].items()
    ]
    return pd.DataFrame(rows, columns=model.AVERAGE_COLUMNS)


def weight_rows(contest_id: str, result: dict | None) -> pd.DataFrame:
    """One date's pollster weights as rows of data/pollster_weights.csv."""
    rows = [] if result is None else [
        {"contest_id": contest_id, "date": result["date"], "pollster": h,
         "volatility": round(p["volatility"], 4), "volatility_source": p["volatility_source"],
         "n_polls_lookback": p["n_polls_lookback"], "n_polls_in_window": p["n_polls_in_window"],
         "weight_share": round(p["weight_share"], 6)}
        for h, p in result["pollsters"].items()
    ]
    return pd.DataFrame(rows, columns=model.WEIGHT_COLUMNS)
