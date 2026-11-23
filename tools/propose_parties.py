#!/usr/bin/env python3
"""Draft config/parties/<CC>.yaml rows from the party columns of a saved Wikipedia fixture.

Usage:  python tools/propose_parties.py CONTEST_ID [--candidates] [--europolls PATH/TO/europolls]

Prints YAML rows for every party column the contest's selector reaches, and an alliance row for
every joint list (one figure spanning several columns). Short names, full names and colours are
read from the table headers; Party Facts ids come from a local clone of github.com/gfrt0/europolls
when --europolls is given. Left-right scores are always left pending. Review before committing.
"""
from __future__ import annotations

import argparse
import gzip
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import config  # noqa: E402
from pipeline.adapters import wikipedia as W  # noqa: E402
from pipeline.adapters import wikitable  # noqa: E402

META = ("polling", "fieldwork", "date", "sample", "lead", "turnout", "client", "area", "pollster", "others")


def slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.replace("+", "plus"))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def label_of(table, c) -> tuple[str, list[str]]:
    cell = table.leaf(c)
    if cell is None:
        return "", []
    links = cell.links if not cell.text else [l for h in table.header_cells(c) for l in h.links]
    return cell.text or cell.links[0], links


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("contest_id")
    ap.add_argument("--candidates", action="store_true")
    ap.add_argument("--europolls")
    args = ap.parse_args()
    source = config.sources(args.contest_id)[0]
    cc = args.contest_id[:2]
    fixture = sorted((ROOT / "tests" / "fixtures" / "wikipedia").glob(f"{args.contest_id}.*.html.gz"))[-1]
    html = gzip.open(fixture, "rt", encoding="utf-8").read()
    sel = W.parse_selector(source["selector"])
    all_tables = wikitable.tables(html)
    tables = W.select(all_tables, sel) + (W.select(all_tables, sel, "round2_top") if "round2_top" in sel else [])
    tables = [t for t in tables if t.n_header_rows > 0 and ("panels" not in sel or t.path[-1] in sel["panels"])]
    blank = type("NoParties", (), {"resolve": staticmethod(lambda *a, **k: None)})()

    pf = {}
    if args.europolls:
        mapping = Path(args.europolls) / "config" / "party_mappings" / f"{cc.upper()}.yaml"
        if mapping.exists():
            for row in yaml.safe_load(mapping.read_text(encoding="utf-8"))["mappings"]:
                if row.get("partyfacts_id"):
                    pf.setdefault(row["party_short"].lower(), int(row["partyfacts_id"]))

    info: dict[str, dict] = {}
    spans: Counter = Counter()
    for t in tables:
        roles = W.classify(t, source.get("column_map") or {}, blank, None)
        for c in range(t.width):
            leaf, links = label_of(t, c)
            if not leaf or roles[c] != ("party", None):     # a role column, or one mapped in column_map
                continue
            key = links[0] if args.candidates and links else leaf
            d = info.setdefault(key, {"links": [], "colour": None, "labels": []})
            if leaf not in d["labels"]:
                d["labels"].append(leaf)
            d["links"] += [l for l in links if l not in d["links"]]
            colours = [cell.colour for cell in t.header_cells(c) if cell.colour]
            d["colour"] = d["colour"] or (colours[-1] if colours else None)
        for row in t.body():
            done = set()
            for cell in row:
                if cell is None or id(cell) in done or cell.colspan == 1 or cell.is_header:
                    continue
                done.add(id(cell))
                cols = [k for k in range(len(row)) if row[k] is cell]
                cols = [k for k in cols if roles[k] == ("party", None)]
                if W.parse_value(cell.text) is not None and 1 < len(cols) <= 6:
                    spans[tuple(label_of(t, k)[0] for k in cols)] += 1

    rows = []
    for key, d in info.items():
        name = re.sub(r"\s*\(.*\)$", "", next((l for l in d["links"] if l != key), key))
        if args.candidates:
            surname = key.split()[-1] if len(key.split()) < 3 else " ".join(key.split()[1:])
            row = {"party_id": f"{cc}-cand-{slug(surname)}", "type": "candidate", "short": surname, "name": key,
                   "colour": d["colour"] or "#888888", "party_id_nominating": None, "partyfacts_id": None,
                   "lr_score": None, "lr_source": "pending",
                   "aliases": [l for l in d["labels"] if l != key]}
        else:
            row = {"party_id": f"{cc}-{slug(key)}", "type": "party", "short": key, "name": name,
                   "colour": d["colour"] or "#888888", "partyfacts_id": pf.get(key.lower()),
                   "lr_score": None, "lr_source": "pending"}
        rows.append(row)
    for labels, n in spans.most_common():
        if all(l in info for l in labels):
            rows.append({"party_id": f"{cc}-" + "-".join(slug(l) for l in labels), "type": "alliance",
                         "short": "+".join(labels), "name": "Joint list: " + ", ".join(labels),
                         "colour": info[labels[0]]["colour"] or "#888888", "partyfacts_id": None,
                         "lr_score": None, "lr_source": "pending",
                         "members": [f"{cc}-{slug(l)}" for l in labels]})
    print(yaml.safe_dump(rows, sort_keys=False, allow_unicode=True, width=110))
    return 0


if __name__ == "__main__":
    sys.exit(main())
