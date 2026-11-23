"""Read data/ for the app. One country at a time; a file is re-read only when it changes on disk."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

from pipeline import model

DATA = model.DATA


def _mtime(path: Path) -> float:
    return path.stat().st_mtime if path.exists() else 0.0


@lru_cache(maxsize=8)
def _csv(path: str, mtime: float, kind: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        cols = {"polls": model.POLL_COLUMNS, "averages": model.AVERAGE_COLUMNS,
                "weights": model.WEIGHT_COLUMNS, "results": model.RESULT_COLUMNS}[kind]
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(p, keep_default_na=False, na_values=[""], dtype={"poll_id": str, "source_rev": str, "flags": str})
    if "flags" in df:
        df["flags"] = df["flags"].fillna("")
    for col in ("fieldwork_start", "fieldwork_end", "date"):
        if col in df:
            df[col] = pd.to_datetime(df[col])
    return df


def polls(country: str, data_dir: Path = DATA) -> pd.DataFrame:
    path = data_dir / f"polls_{country}.csv"
    return _csv(str(path), _mtime(path), "polls")


def averages(country: str, data_dir: Path = DATA) -> pd.DataFrame:
    path = data_dir / f"averages_{country}.csv"
    return _csv(str(path), _mtime(path), "averages")


def weights(data_dir: Path = DATA) -> pd.DataFrame:
    path = data_dir / "pollster_weights.csv"
    return _csv(str(path), _mtime(path), "weights")


def results(data_dir: Path = DATA) -> pd.DataFrame:
    path = data_dir / "results.csv"
    return _csv(str(path), _mtime(path), "results")


@lru_cache(maxsize=2)
def _quality(path: str, mtime: float) -> dict:
    p = Path(path)
    if not p.exists():
        return {"data_as_of": None, "contests": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def quality(data_dir: Path = DATA) -> dict:
    path = data_dir / "quality.json"
    return _quality(str(path), _mtime(path))
