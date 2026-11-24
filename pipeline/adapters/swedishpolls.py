"""SwedishPolls adapter: Swedish national polls from github.com/MansMeg/SwedishPolls (MIT and CC0).

One CSV, Data/Polls.csv. The pinned revision is the repository commit the file was read at.
"""
from __future__ import annotations

import datetime as dt
import io
import subprocess

import pandas as pd

from pipeline import model
from pipeline.adapters.base import AdapterError, ContestPull, get, session
from pipeline.parties import Resolver

REPO = "https://github.com/MansMeg/SwedishPolls"
PATH = "Data/Polls.csv"
NEEDED = ("house", "collectPeriodFrom", "collectPeriodTo", "n", "PublDate")
NOT_PARTIES = {"PublYearMonth", "Company", "Uncertain", "n", "PublDate", "collectPeriodFrom", "collectPeriodTo",
               "approxPeriod", "house"}


def head_commit() -> str:
    """The commit the repository's default branch points at."""
    try:
        out = subprocess.run(["git", "ls-remote", REPO, "HEAD"], capture_output=True, text=True, timeout=60, check=True)
        sha = out.stdout.split()[0]
    except (OSError, subprocess.SubprocessError, IndexError) as exc:
        raise AdapterError(f"SwedishPolls: cannot read the repository head: {exc}") from exc
    if len(sha) != 40:
        raise AdapterError(f"SwedishPolls: unexpected head '{sha}'")
    return sha


def fetch(s=None) -> tuple[str, str]:
    """(commit, csv text) of Data/Polls.csv at the current head."""
    sha = head_commit()
    url = f"https://raw.githubusercontent.com/MansMeg/SwedishPolls/{sha}/{PATH}"
    return sha, get(s or session(), url).text


def parse(csv_text: str, commit: str, contest: dict, resolver: Resolver, retrieved_at: dt.datetime,
          since: dt.date) -> ContestPull:
    """Polls whose collection period ended after `since`, as long rows. `NA` means not reported."""
    cid = contest["contest_id"]
    frame = pd.read_csv(io.StringIO(csv_text), dtype=str, keep_default_na=False)
    missing = [c for c in NEEDED if c not in frame.columns]
    if missing:
        raise AdapterError(f"SwedishPolls: missing columns {missing}")
    party_cols = [c for c in frame.columns if c not in NOT_PARTIES]
    if len(party_cols) < 2:
        raise AdapterError("SwedishPolls: fewer than two party columns")
    source_url = f"{REPO}/blob/{commit}/{PATH}"
    rows, unmapped, undated = [], {}, 0
    for i, r in enumerate(frame.to_dict("records")):
        try:
            end = dt.date.fromisoformat(r["collectPeriodTo"])
        except ValueError:
            undated += 1
            continue
        if end <= since or (contest.get("date") and contest.get("status") == "held" and end > contest["date"]):
            continue
        try:
            start = dt.date.fromisoformat(r["collectPeriodFrom"])
        except ValueError:
            start = None
        pollster = r["house"].strip() or r.get("Company", "").strip()
        if not pollster:
            undated += 1
            continue
        values: dict[str, float] = {}
        for col in party_cols:
            if r[col] in ("NA", ""):
                continue
            party = resolver.resolve(col, end)
            if party is None:
                unmapped[col] = unmapped.get(col, 0) + 1
                party = model.OTHERS
            values[party] = round(values.get(party, 0.0) + float(r[col]), 2)
        if not values:
            continue
        base = {
            "poll_id": model.poll_id(cid, pollster, end, None, f"swedishpolls:{r['PublDate']}:{start}"),
            "contest_id": cid, "round": 1, "lineup_id": "default", "is_headline_lineup": True,
            "pollster": pollster, "client": None, "fieldwork_start": start, "fieldwork_end": end,
            "sample_size": int(r["n"]) if r["n"].isdigit() and int(r["n"]) > 0 else None, "method": None,
            "unit": "pct", "flags": "", "region": None, "source_url": source_url, "adapter": "swedishpolls",
            "source_rev": commit, "retrieved_at": retrieved_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        rows += [dict(base, party_id=party, value=v) for party, v in values.items()]
    warnings = [f"column '{c}' is not in config/parties/SE.yaml; {n} figure(s) folded into others"
                for c, n in sorted(unmapped.items())]
    if undated:
        warnings.append(f"{undated} row(s) without a collection end date or a pollster were skipped")
    return ContestPull(cid, pd.DataFrame(rows, columns=model.POLL_COLUMNS), warnings=warnings)
