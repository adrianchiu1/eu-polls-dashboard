"""The shape of the data files. Column lists come from schemas/data_columns.yaml, never from code."""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

OTHERS = "others"


@lru_cache(maxsize=None)
def _schema() -> dict:
    with open(ROOT / "schemas" / "data_columns.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)["files"]


def columns(file_key: str) -> list[str]:
    """Column names of one data file, in the order they are written."""
    return list(_schema()[file_key]["columns"])


POLL_COLUMNS = columns("data/polls_<CC>.csv")
AVERAGE_COLUMNS = columns("data/averages_<CC>.csv")
WEIGHT_COLUMNS = columns("data/pollster_weights.csv")
RESULT_COLUMNS = columns("data/results.csv")
POLL_KEY = ["poll_id", "lineup_id", "round", "party_id"]


def poll_id(contest_id: str, pollster: str, fieldwork_end, client, source) -> str:
    """Stable id for one poll: the same inputs give the same id on every run."""
    raw = "|".join(str(x or "") for x in (contest_id, pollster, fieldwork_end, client, source))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def empty_polls() -> pd.DataFrame:
    return pd.DataFrame(columns=POLL_COLUMNS)


def read_polls(country: str, data_dir: Path = DATA) -> pd.DataFrame:
    """One country's polls, or an empty frame if none has been written yet."""
    path = data_dir / f"polls_{country}.csv"
    if not path.exists():
        return empty_polls()
    return pd.read_csv(path, dtype={"poll_id": str, "lineup_id": str, "source_rev": str, "flags": str},
                       keep_default_na=False, na_values=[""]).assign(
        flags=lambda d: d["flags"].fillna(""))


def add_flag(flags: str, flag: str) -> str:
    parts = [f for f in (flags or "").split(";") if f]
    if flag not in parts:
        parts.append(flag)
    return ";".join(parts)


def has_flag(flags: pd.Series, flag: str) -> pd.Series:
    return flags.fillna("").str.split(";").apply(lambda parts: flag in parts)
