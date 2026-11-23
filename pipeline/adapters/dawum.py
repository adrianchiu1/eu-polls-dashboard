"""DAWUM adapter: German federal and state polls from https://api.dawum.de/ (ODbL 1.0).

The whole database is one JSON file. Parliament ids are read from its Parliaments block on every
run; none are stored in configuration.
"""
from __future__ import annotations

import datetime as dt
import re

import pandas as pd

from pipeline import model
from pipeline.adapters.base import AdapterError, ContestPull, get, session
from pipeline.parties import Resolver, norm_label

URL = "https://api.dawum.de/"
BLOCKS = ("Database", "Parliaments", "Institutes", "Taskers", "Methods", "Parties", "Surveys")
_TRANSLIT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})


def fetch(s=None) -> dict:
    db = get(s or session(), URL).json()
    check(db)
    return db


def check(db: dict) -> None:
    """Fail closed on a layout change or an empty database."""
    missing = [b for b in BLOCKS if b not in db]
    if missing:
        raise AdapterError(f"DAWUM: missing blocks {missing}")
    if not db["Surveys"] or not db["Parliaments"]:
        raise AdapterError("DAWUM: empty Surveys or Parliaments block")
    if "Last_Update" not in db["Database"]:
        raise AdapterError("DAWUM: Database block has no Last_Update")


def parliament_id(db: dict, contest: dict) -> str:
    """The Parliaments key for a contest: the Bundestag by name, a Land by its Shortcut."""
    want = "Bundestag" if contest["body"] == "Bundestag" else contest["territory"]
    hits = [pid for pid, p in db["Parliaments"].items()
            if p["Shortcut"] == want or p["Shortcut"].startswith(want + " (")]
    if len(hits) != 1:
        raise AdapterError(f"DAWUM: {len(hits)} parliaments match '{want}' for {contest['contest_id']}")
    return hits[0]


def parliament_url(shortcut: str) -> str:
    """DAWUM's page for a parliament, which lists every poll with its details."""
    slug = re.sub(r"\s*\(.*\)$", "", shortcut).translate(_TRANSLIT).replace(" ", "_")
    return f"https://dawum.de/{slug}/"


def _is_party_client(client: str | None, resolver: Resolver) -> bool:
    """True when the client is a party or a party branch ('CDU Sachsen', 'Die Linke Brandenburg')."""
    if not client:
        return False
    words = client.split()
    return any(resolver.resolve(" ".join(words[:n])) not in (None, model.OTHERS) for n in (1, 2))


def parse(db: dict, contest: dict, resolver: Resolver, retrieved_at: dt.datetime, since: dt.date) -> ContestPull:
    """One contest's polls with fieldwork ending after `since`, as long rows."""
    check(db)
    cid = contest["contest_id"]
    pid = parliament_id(db, contest)
    shortcut = db["Parliaments"][pid]["Shortcut"]
    source_url = parliament_url(shortcut)
    source_rev = db["Database"]["Last_Update"]
    others_keys = {k for k, p in db["Parties"].items() if norm_label(p["Shortcut"]) == "sonstige"}

    rows, unmapped = [], {}
    for sid, sv in db["Surveys"].items():
        if sv["Parliament_ID"] != pid:
            continue
        end = dt.date.fromisoformat(sv["Survey_Period"]["Date_End"])
        if end <= since:
            continue
        start = dt.date.fromisoformat(sv["Survey_Period"]["Date_Start"])
        pollster = db["Institutes"][sv["Institute_ID"]]["Name"]
        client = db["Taskers"].get(sv["Tasker_ID"], {}).get("Name") or None
        method = db["Methods"].get(sv["Method_ID"], {}).get("Name") or None
        persons = str(sv.get("Surveyed_Persons") or "")
        flags = "party_commissioned" if _is_party_client(client, resolver) else ""
        values: dict[str, float] = {}
        for key, value in sv["Results"].items():
            label = db["Parties"][key]["Shortcut"]
            party = model.OTHERS if key in others_keys else resolver.resolve(label, end)
            if party is None:
                unmapped[label] = unmapped.get(label, 0) + 1
                party = model.OTHERS
            values[party] = values.get(party, 0.0) + float(value)
        base = {
            "poll_id": model.poll_id(cid, pollster, end, client, f"dawum:{sid}"),
            "contest_id": cid, "round": 1, "lineup_id": "default", "is_headline_lineup": True,
            "pollster": pollster, "client": client, "fieldwork_start": start, "fieldwork_end": end,
            "sample_size": int(persons) if persons.isdigit() and int(persons) > 0 else None,
            "method": method, "unit": "pct", "flags": flags, "region": None,
            "source_url": source_url, "adapter": "dawum", "source_rev": source_rev,
            "retrieved_at": retrieved_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        rows += [dict(base, party_id=party, value=round(v, 2)) for party, v in values.items()]

    warnings = [f"label '{label}' is not in config/parties/DE.yaml; {n} figure(s) folded into others"
                for label, n in sorted(unmapped.items())]
    polls = pd.DataFrame(rows, columns=model.POLL_COLUMNS)
    return ContestPull(cid, polls, warnings=warnings)
