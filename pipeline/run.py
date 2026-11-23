"""The daily run: fetch every configured source, validate, average, and write data/.

    python -m pipeline.run                         fetch live sources for every runnable country
    python -m pipeline.run --countries DE FR       only these
    python -m pipeline.run --offline tests/fixtures   read saved fixtures instead of the network
    python -m pipeline.run --fail fr-pres-2027     simulate a failed pull for one contest

Fail closed: a contest whose pull fails keeps its rows from the last good file and is marked stale in
data/quality.json. A file is rewritten only when its content changes, and a row that has not changed
keeps the revision and retrieval time it was first seen with, so a quiet day produces no diff.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import io
import json
import sys
from pathlib import Path

import pandas as pd

from pipeline import average, config, model
from pipeline.adapters import dawum, wikipedia
from pipeline.adapters.base import AdapterError, ContestPull, session
from pipeline.parties import Resolver, load as load_parties
from pipeline.validate import validate

PROVENANCE = ["source_rev", "retrieved_at"]


def _add_months(day: dt.date, months: int) -> dt.date:
    y, m = divmod(day.month - 1 + months, 12)
    return dt.date(day.year + y, m + 1, min(day.day, 28))


def runnable(source: dict) -> bool:
    """A source the pipeline can read today."""
    if source["adapter"] == "dawum":
        return True
    return source["adapter"] == "wikipedia" and "=" in source["selector"]


def runnable_countries() -> list[str]:
    """Countries with a party file and at least one readable source, in tab order."""
    out = []
    for c in config.countries():
        if load_parties(c["code"]) and any(
                runnable(s) for k in config.contests(c["code"]) for s in config.sources(k["contest_id"])):
            out.append(c["code"])
    return out


class Context:
    """Where pulls come from (network or saved fixtures) and the clock they are stamped with."""

    def __init__(self, now: dt.datetime, offline: Path | None = None, fail: tuple[str, ...] = ()):
        self.now, self.offline, self.fail = now, offline, set(fail)
        self.today = now.date()
        self._session = None
        self._dawum = None

    @property
    def http(self):
        if self._session is None:
            self._session = session()
        return self._session

    def dawum_db(self) -> dict:
        if self._dawum is None:
            if self.offline:
                files = sorted((self.offline / "dawum").glob("*.json.gz"))
                if not files:
                    raise AdapterError("no DAWUM fixture")
                self._dawum = json.loads(gzip.open(files[-1], "rt", encoding="utf-8").read())
            else:
                self._dawum = dawum.fetch(self.http)
        return self._dawum

    def wikipedia_page(self, contest_id: str, title: str) -> tuple[str, str]:
        """(revision id, reduced html) for an article."""
        if self.offline:
            files = sorted((self.offline / "wikipedia").glob(f"{contest_id}.*.html.gz"))
            if not files:
                raise AdapterError(f"no Wikipedia fixture for {contest_id}")
            return files[-1].name.split(".")[-3], gzip.open(files[-1], "rt", encoding="utf-8").read()
        revision, _ = wikipedia.latest_revision(title, self.http)
        return revision, wikipedia.fetch_html(revision, self.http)


def cycle_start(contest: dict, today: dt.date) -> tuple[dt.date, str | None]:
    """The day after which a poll belongs to this contest, and a warning when it had to be assumed."""
    if contest.get("previous_date"):
        return contest["previous_date"], None
    months = config.settings()["contests"]["trend_min_history_months"]
    return _add_months(today, -months), (
        f"no previous election date in config/contests.yaml; polls from the last {months} months are used")


def pull_contest(contest: dict, source: dict, ctx: Context) -> ContestPull:
    cid = contest["contest_id"]
    if cid in ctx.fail:
        raise AdapterError(f"{cid}: failure forced with --fail")
    resolver = Resolver(contest["country"])
    since, note = cycle_start(contest, ctx.today)
    if source["adapter"] == "dawum":
        pull = dawum.parse(ctx.dawum_db(), contest, resolver, ctx.now, since)
    else:
        revision, html = ctx.wikipedia_page(cid, source["locator"])
        pull = wikipedia.parse(html, contest, source, resolver, revision, ctx.now,
                               window_days=config.settings()["average"]["window_days"])
    if contest.get("date"):
        polls = pull.polls
        pull.polls = polls[pd.to_datetime(polls["fieldwork_end"]).dt.date <= contest["date"]]
    if note:
        pull.warnings.insert(0, note)
    return pull


def check_pull(pull: ContestPull, contest: dict, source: dict, country: dict, last_good: pd.DataFrame,
               today: dt.date):
    """Validate one pull. Returns (rows, warnings); raises AdapterError when it must not be published."""
    v = config.settings()["validation"]
    partial = source["adapter"] == "wikipedia" and wikipedia.parse_selector(source["selector"]).get("sums") == "partial"
    rep = validate(pull.polls, chamber_size=country.get("chamber_size"), today=today, check_sums=not partial)
    cid = contest["contest_id"]
    n = rep.polls["poll_id"].nunique() if not rep.polls.empty else 0
    if n == 0:
        raise AdapterError(f"{cid}: no valid poll in the pull")
    if rep.checked and 100.0 * rep.dropped / rep.checked > v["fail_pull_if_dropped_above_pct"]:
        raise AdapterError(f"{cid}: {rep.dropped} of {rep.checked} polls failed validation")
    before = last_good["poll_id"].nunique() if not last_good.empty else 0
    if before and 100.0 * n / before < v["fail_pull_if_polls_below_last_good_pct"]:
        raise AdapterError(f"{cid}: {n} polls, down from {before} in the last good file")
    return rep.polls, pull.warnings + rep.warnings


def keep_provenance(new: pd.DataFrame, old: pd.DataFrame) -> pd.DataFrame:
    """Rows identical to the last file keep the revision and time they were first seen with."""
    if old.empty or new.empty:
        return new
    compare = [c for c in model.POLL_COLUMNS if c not in PROVENANCE]

    def sig(frame: pd.DataFrame) -> pd.Series:
        # compare rows as they are written to disk, so types read back from CSV cannot differ
        text = pd.read_csv(io.StringIO(frame[compare].to_csv(index=False)), dtype=str, keep_default_na=False)
        return text.agg("|".join, axis=1).set_axis(frame.index)

    seen = dict(zip(sig(old), zip(old["source_rev"], old["retrieved_at"])))
    out = new.copy()
    keys = sig(out)
    hit = keys.isin(seen.keys())
    out.loc[hit, "source_rev"] = [seen[k][0] for k in keys[hit]]
    out.loc[hit, "retrieved_at"] = [seen[k][1] for k in keys[hit]]
    return out


def normalise(frame: pd.DataFrame) -> pd.DataFrame:
    """Stable types, order and formats, so the same data always writes the same bytes."""
    out = frame.copy()
    for col in ("fieldwork_start", "fieldwork_end"):
        out[col] = pd.to_datetime(out[col]).dt.strftime("%Y-%m-%d")
    out["sample_size"] = pd.to_numeric(out["sample_size"]).astype("Int64")
    out["round"] = out["round"].astype(int)
    out["is_headline_lineup"] = out["is_headline_lineup"].astype(bool)
    out["flags"] = out["flags"].fillna("")
    out["source_rev"] = out["source_rev"].astype(str)
    out = out.sort_values(["contest_id", "fieldwork_end", "pollster", "poll_id", "round", "lineup_id", "party_id"],
                          ascending=[True, False, True, True, True, True, True])
    return out[model.POLL_COLUMNS].reset_index(drop=True)


def write_if_changed(path: Path, text: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def series_groups(polls: pd.DataFrame) -> list[tuple[str, int, pd.DataFrame]]:
    """The series to average in one contest: the headline line-up, then each second-round match-up."""
    out = []
    first = polls[(polls["round"] == 1) & polls["is_headline_lineup"].astype(bool)]
    if not first.empty:
        varied = first["lineup_id"].nunique() > 1
        out.append(("headline" if varied else first["lineup_id"].iloc[0], 1, first))
    for lineup, group in polls[polls["round"] == 2].groupby("lineup_id", sort=True):
        out.append((lineup, 2, group))
    return out


def averages_for(contest: dict, polls: pd.DataFrame, today: dt.date):
    """(average rows, weight rows) for one contest's validated polls."""
    s = average.settings()
    frames, weights = [], []
    last_day = min(today, contest["date"]) if contest.get("date") else today
    for lineup, round_, group in series_groups(polls):
        wide = average.eligible_wide(group, s)
        if wide.empty:
            continue
        averager = average.Averager(wide, s, tier=contest["tier"])
        series = averager.series(wide["fieldwork_end"].min(), last_day)
        frames.append(average.average_rows(contest["contest_id"], lineup, round_, series))
        if round_ == 1 and series:
            weights.append(average.weight_rows(contest["contest_id"], series[-1]))
    avg = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=model.AVERAGE_COLUMNS)
    wts = pd.concat(weights, ignore_index=True) if weights else pd.DataFrame(columns=model.WEIGHT_COLUMNS)
    return avg, wts


def run(countries: list[str] | None = None, data_dir: Path = model.DATA, *, now: dt.datetime | None = None,
        offline: Path | None = None, fail: tuple[str, ...] = (), log=print) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    ctx = Context(now, offline, fail)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    quality_path = data_dir / "quality.json"
    quality = json.loads(quality_path.read_text(encoding="utf-8")) if quality_path.exists() else {"contests": {}}
    weights_path, results_path = data_dir / "pollster_weights.csv", data_dir / "results.csv"
    all_weights = pd.read_csv(weights_path) if weights_path.exists() else pd.DataFrame(columns=model.WEIGHT_COLUMNS)
    all_results = pd.read_csv(results_path) if results_path.exists() else pd.DataFrame(columns=model.RESULT_COLUMNS)
    changed, failures = [], []
    window = dt.timedelta(days=90)

    for cc in countries or runnable_countries():
        country = config.country(cc)
        old = model.read_polls(cc, data_dir)
        kept, avg_frames = [], []
        for contest in config.contests(cc):
            cid = contest["contest_id"]
            source = next((s for s in config.sources(cid) if runnable(s)), None)
            if source is None:
                continue
            last_good = old[old["contest_id"] == cid]
            entry = dict(quality["contests"].get(cid, {}), contest_id=cid)
            try:
                pull = pull_contest(contest, source, ctx)
                rows, warnings = check_pull(pull, contest, source, country, last_good, ctx.today)
                rows = keep_provenance(normalise(rows), normalise(last_good) if not last_good.empty else last_good)
                entry.update(parser_status="ok", validation_warnings=warnings, last_successful_pull=stamp)
                if pull.results is not None and not pull.results.empty:
                    ids = set(pull.results["contest_id"])
                    all_results = pd.concat([all_results[~all_results["contest_id"].isin(ids)], pull.results],
                                            ignore_index=True)
                log(f"ok      {cid}: {rows['poll_id'].nunique()} polls, {len(warnings)} warning(s)")
            except AdapterError as exc:
                failures.append(cid)
                rows = normalise(last_good) if not last_good.empty else last_good
                entry.update(parser_status="stale" if not last_good.empty else "failed",
                             validation_warnings=[f"pull failed: {exc}"],
                             last_successful_pull=entry.get("last_successful_pull"))
                log(f"FAILED  {cid}: {exc}")
            if not rows.empty:
                ends = pd.to_datetime(rows["fieldwork_end"]).dt.date
                recent = rows[ends > ctx.today - window]
                entry.update(latest_poll_date=ends.max().isoformat(), polls_90d=int(recent["poll_id"].nunique()),
                             pollsters_90d=int(recent["pollster"].nunique()))
                kept.append(rows)
                avg, wts = averages_for(contest, rows, ctx.today)
                avg_frames.append(avg)
                all_weights = pd.concat([all_weights[all_weights["contest_id"] != cid], wts], ignore_index=True)
            else:
                entry.update(latest_poll_date=None, polls_90d=0, pollsters_90d=0)
            entry["data_as_of"] = stamp
            quality["contests"][cid] = entry
        if kept:
            polls = pd.concat(kept, ignore_index=True)
            if write_if_changed(data_dir / f"polls_{cc}.csv", polls.to_csv(index=False)):
                changed.append(f"polls_{cc}.csv")
            avg = pd.concat(avg_frames, ignore_index=True).sort_values(
                ["contest_id", "round", "lineup_id", "date", "party_id"])
            if write_if_changed(data_dir / f"averages_{cc}.csv", avg.to_csv(index=False)):
                changed.append(f"averages_{cc}.csv")

    all_weights = all_weights.sort_values(["contest_id", "pollster"])[model.WEIGHT_COLUMNS]
    all_results = all_results.sort_values(["contest_id", "round", "party_id"])[model.RESULT_COLUMNS]
    if len(all_weights) and write_if_changed(weights_path, all_weights.to_csv(index=False)):
        changed.append("pollster_weights.csv")
    if len(all_results) and write_if_changed(results_path, all_results.to_csv(index=False)):
        changed.append("results.csv")
    quality["data_as_of"] = stamp
    quality["contests"] = dict(sorted(quality["contests"].items()))
    write_if_changed(quality_path, json.dumps(quality, indent=1, ensure_ascii=False) + "\n")
    return {"changed": changed, "failures": failures, "quality": quality}


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch, validate, average and write data/.")
    ap.add_argument("--countries", nargs="*")
    ap.add_argument("--offline", type=Path, help="read fixtures from this folder instead of the network")
    ap.add_argument("--fail", nargs="*", default=[], help="contest ids whose pull should fail (a drill)")
    ap.add_argument("--data-dir", type=Path, default=model.DATA)
    ap.add_argument("--now", help="ISO date-time to run as, for reproducible offline runs")
    args = ap.parse_args()
    now = dt.datetime.fromisoformat(args.now).replace(tzinfo=dt.timezone.utc) if args.now else None
    out = run(args.countries, args.data_dir, now=now, offline=args.offline, fail=tuple(args.fail))
    print(f"changed: {', '.join(out['changed']) or 'nothing'}")
    if out["failures"]:
        print(f"failed pulls: {', '.join(out['failures'])}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
