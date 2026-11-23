"""Party configuration: config/parties/<CC>.yaml, and the mapping from source labels to party ids."""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from functools import lru_cache

import yaml

from pipeline import config
from pipeline.model import OTHERS

OTHERS_COLOUR = "#9aa0a6"


def norm_label(label: str) -> str:
    """Case, accents, spacing and punctuation folded, so 'Grüne', 'GRÜNE ' and 'Grune' match."""
    text = unicodedata.normalize("NFKD", str(label))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9+&/]+", "", text.lower())


@lru_cache(maxsize=None)
def load(country: str) -> list[dict]:
    """Party rows for a country; an empty list when no file exists yet."""
    path = config.CONFIG / "parties" / f"{country}.yaml"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)["parties"]


def by_id(country: str) -> dict[str, dict]:
    return {p["party_id"]: p for p in load(country)}


class Resolver:
    """Maps a label as a source prints it to a party id, honouring valid_from and valid_to."""

    def __init__(self, country: str, others_labels: tuple[str, ...] = ()):
        self.country = country
        self._index: dict[str, list[dict]] = {}
        for p in load(country):
            for label in {p["short"], p["name"], p.get("name_en") or "", *p.get("aliases", [])}:
                if label:
                    self._index.setdefault(norm_label(label), []).append(p)
        self._others = {norm_label(x) for x in ("others", "other", "oth", *others_labels)}

    def alliance(self, members: set[str]) -> str | None:
        """The alliance whose members are exactly these party ids (a joint list in a source table)."""
        for p in load(self.country):
            if p["type"] == "alliance" and not p.get("coalition") and set(p.get("members") or []) == set(members):
                return p["party_id"]
        return None

    def resolve(self, label: str, on: dt.date | None = None) -> str | None:
        """The party id for a label, "others" for an others column, None when unknown."""
        key = norm_label(label)
        if key in self._others:
            return OTHERS
        for p in self._index.get(key, []):
            start, end = p.get("valid_from"), p.get("valid_to")
            if on is not None and ((start and on < start) or (end and on > end)):
                continue
            return p["party_id"]
        return None


def display(country: str, party_id: str) -> dict:
    """Short name and colour for a party id, with a neutral fallback for "others"."""
    if party_id == OTHERS:
        return {"short": "Others", "name": "Others", "colour": OTHERS_COLOUR, "lr_score": None}
    p = by_id(country).get(party_id)
    if p is None:
        return {"short": party_id, "name": party_id, "colour": OTHERS_COLOUR, "lr_score": None}
    return {"short": p["short"], "name": p.get("name_en") or p["name"], "colour": p["colour"],
            "lr_score": p.get("lr_score")}


def coalitions(country: str) -> list[dict]:
    """Alliances marked `coalition: true`: separately polled lists whose total the app shows."""
    return [p for p in load(country) if p["type"] == "alliance" and p.get("coalition")]


def is_coalition(country: str, party_id: str) -> bool:
    return any(p["party_id"] == party_id for p in coalitions(country))
