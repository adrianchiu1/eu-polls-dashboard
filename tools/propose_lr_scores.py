#!/usr/bin/env python3
"""Propose left-right scores for config/parties/<CC>.yaml from the Chapel Hill Expert Survey.

Usage:  python tools/propose_lr_scores.py --ches CHES_2024_final_v2.csv --partyfacts external-parties.csv
                                          [--write] [CC ...]

A party is scored when the 2024 wave rates it: the score is its `lrgen` (general left-right, 0 to
10), rounded to two decimals, with lr_source ches2024. The party is found (1) through its Party
Facts id, or, because Party Facts has not linked the 2024 wave's new parties yet, (2) by the survey
printing the same label for a party in the same country as our short name or an alias, or (3) by
the short list in LABELS below. A joint list takes the mean of its members' scores weighted by
their vote share at the last election (data/results.csv), and only when every member has both. A
candidate inherits the party the source tables print beside the candidate's name. Nothing else is
scored: parties the survey does not rate stay pending for a hand-set proposal of their own.

Without --write it prints the proposal. With --write it edits the party files in place; commit
that only on a judgement-proposal branch (CLAUDE.md, "Rules that do not bend").

Sources: chesdata.eu (CHES 2024, Rovny et al. 2025) and partyfacts.org (external parties table).
Neither file is stored in this repository.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import config  # noqa: E402

from pipeline.parties import Resolver, norm_label  # noqa: E402

WAVE = "ches2024"
# CHES numeric country codes, checked against the 2024 file's party lists.
CHES_COUNTRY = {1: "BE", 2: "DK", 3: "DE", 5: "ES", 6: "FR", 8: "IT", 11: "UK", 16: "SE", 35: "NO"}
# CHES labels that differ from the label the polling tables use for the same party.
LABELS = {("UK", "REF UK"): "uk-ref", ("FR", "LE/EELV"): "fr-le"}


def ches_labels(ches_csv: Path) -> dict[str, dict[str, tuple[float, str]]]:
    """Country -> normalised CHES label -> (lrgen, label)."""
    out: dict[str, dict] = {}
    for r in pd.read_csv(ches_csv).itertuples():
        cc = CHES_COUNTRY.get(int(r.country))
        if cc and pd.notna(r.lrgen):
            out.setdefault(cc, {})[norm_label(r.party)] = (float(r.lrgen), str(r.party))
    return out


def ches_scores(ches_csv: Path, partyfacts_csv: Path) -> dict[int, tuple[float, str]]:
    """Party Facts id -> (lrgen, CHES party label) for parties the 2024 wave rates."""
    ches = pd.read_csv(ches_csv)
    rated = {int(r.party_id): (float(r.lrgen), str(r.party)) for r in ches.itertuples() if pd.notna(r.lrgen)}
    out: dict[int, tuple[float, str]] = {}
    with open(partyfacts_csv, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["dataset_key"] != "ches" or not row["partyfacts_id"] or not row["dataset_party_id"].isdigit():
                continue
            hit = rated.get(int(row["dataset_party_id"]))
            if hit:
                out[int(row["partyfacts_id"])] = hit
    return out


def propose(cc: str, scores: dict, results: pd.DataFrame, labels: dict | None = None) -> list[dict]:
    """One row per party in the file: party_id, short, score or None, source, why."""
    path = config.CONFIG / "parties" / f"{cc}.yaml"
    parties = yaml.safe_load(path.read_text(encoding="utf-8"))["parties"]
    out, by_id = [], {}
    for p in parties:
        if p["type"] != "party":
            continue
        hit = scores.get(p.get("partyfacts_id")) if p.get("partyfacts_id") else None
        why = f"CHES 2024 '{hit[1]}' via Party Facts {p['partyfacts_id']}" if hit else None
        if hit is None:
            mine = {norm_label(x) for x in [p["short"], *p.get("aliases", [])]}
            for key, found in (labels or {}).get(cc, {}).items():
                if key in mine or LABELS.get((cc, found[1])) == p["party_id"]:
                    hit, why = found, f"CHES 2024 '{found[1]}' by label"
        row = {"party_id": p["party_id"], "short": p["short"], "score": round(hit[0], 2) if hit else None,
               "source": WAVE if hit else "pending",
               "why": why or ("Party Facts id has no CHES 2024 rating" if p.get("partyfacts_id") else "no Party Facts id")}
        out.append(row)
        by_id[p["party_id"]] = row
    share = results.groupby("party_id")["vote_share"].max() if not results.empty else pd.Series(dtype=float)
    for p in parties:
        if p["type"] != "alliance":
            continue
        members = p.get("members") or []
        rows = [by_id.get(m) for m in members]
        row = {"party_id": p["party_id"], "short": p["short"], "score": None, "source": "pending"}
        if not members or any(r is None or r["score"] is None for r in rows):
            row["why"] = "a member has no score"
        elif not all(m in share.index for m in members):
            row["why"] = "a member has no vote share at the last election in data/results.csv"
        else:
            total = sum(share[m] for m in members)
            row.update(score=round(sum(by_id[m]["score"] * share[m] for m in members) / total, 2), source=WAVE,
                       why="mean of members weighted by last election vote share")
        out.append(row)
    resolver = Resolver(cc)
    for p in parties:
        if p["type"] == "candidate":
            nominating = p.get("party_id_nominating")
            tag = None
            if nominating is None:                       # the party printed beside the name: 'Name (LFI)', 'Name LFI'
                for alias in p.get("aliases", []):
                    m = re.search(r"\(([^)]+)\)$|\s([A-Z!]{2,5})$", alias)
                    found = resolver.resolve(m.group(1) or m.group(2)) if m else None
                    if found and by_id.get(found):
                        nominating, tag = found, m.group(1) or m.group(2)
                        break
            nominee = by_id.get(nominating)
            ok = nominee is not None and nominee["score"] is not None
            out.append({"party_id": p["party_id"], "short": p["short"], "score": nominee["score"] if ok else None,
                        "source": "inherited" if ok else "pending", "nominating": nominating if tag else None,
                        "why": (f"inherits {nominating}" + (f" (table label '{tag}')" if tag else "")) if ok else (
                            f"{nominating} has no score" if nominating else "the tables print no party we can match")})
    return out


def write(cc: str, rows: list[dict]) -> int:
    """Edit lr_score and lr_source in place, leaving the rest of the file byte for byte."""
    path = config.CONFIG / "parties" / f"{cc}.yaml"
    text = path.read_text(encoding="utf-8")
    changed = 0
    for r in rows:
        if r.get("nominating"):
            link = re.compile(rf"(- party_id: {re.escape(r['party_id'])}\n(?:(?!  - party_id:).*\n)*?\s+party_id_nominating: )null")
            text = link.sub(rf"\g<1>{r['nominating']}", text, count=1)
        if r["score"] is None:
            continue
        block = re.compile(
            rf"(- party_id: {re.escape(r['party_id'])}\n(?:(?!  - party_id:).*\n)*?\s+lr_score: )null(\n\s+lr_source: )pending")
        text, n = block.subn(rf"\g<1>{r['score']}\g<2>{r['source']}", text, count=1)
        changed += n
    path.write_text(text, encoding="utf-8")
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("countries", nargs="*")
    ap.add_argument("--ches", type=Path, required=True)
    ap.add_argument("--partyfacts", type=Path, required=True)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    scores = ches_scores(args.ches, args.partyfacts)
    labels = ches_labels(args.ches)
    results_path = ROOT / "data" / "results.csv"
    results = pd.read_csv(results_path) if results_path.exists() else pd.DataFrame(columns=["party_id", "vote_share"])
    files = args.countries or sorted(p.stem for p in (config.CONFIG / "parties").glob("[A-Z][A-Z].yaml"))
    for cc in files:
        rows = propose(cc, scores, results, labels)
        scored = [r for r in rows if r["score"] is not None]
        print(f"\n{cc}: {len(scored)} of {len(rows)} scored")
        for r in rows:
            score = f"{r['score']:.2f}" if r["score"] is not None else "  –  "
            print(f"  {r['party_id']:32} {score}  {r['source']:9} {r['why']}")
        if args.write:
            print(f"  wrote {write(cc, rows)} score(s) to config/parties/{cc}.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
