#!/usr/bin/env python3
"""Validate config/ against schemas/ and check cross-references.

Usage:  python tools/validate_config.py
Exits 0 and prints OK when everything passes, 1 with a list of problems otherwise.
Requires: pyyaml, jsonschema.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
SCHEMAS = ROOT / "schemas"

PRESIDENTIAL_FIRST = {"FR", "AT", "PT", "IE", "FI", "CZ", "PL"}


def iso(obj):
    """PyYAML turns bare dates into date objects; schemas expect ISO strings."""
    if isinstance(obj, (dt.date, dt.datetime)):
        return obj.isoformat()[:10]
    if isinstance(obj, dict):
        return {k: iso(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [iso(v) for v in obj]
    return obj


def load(name: str):
    with open(CONFIG / name, encoding="utf-8") as fh:
        return iso(yaml.safe_load(fh))


def check_schema(doc, schema_name: str, label: str, problems: list[str]) -> None:
    schema = json.loads((SCHEMAS / schema_name).read_text(encoding="utf-8"))
    for err in sorted(Draft202012Validator(schema).iter_errors(doc), key=lambda e: list(e.path)):
        where = "/".join(str(p) for p in err.path) or "(root)"
        problems.append(f"{label}: {where}: {err.message}")


def duplicates(values) -> list[str]:
    return [v for v, n in Counter(values).items() if n > 1]


def main() -> int:
    problems: list[str] = []

    settings = load("settings.yaml")
    countries = load("countries.yaml")
    contests = load("contests.yaml")
    judgements = load("judgements.yaml")
    sources = load("sources.yaml")

    check_schema(settings, "settings.schema.json", "settings.yaml", problems)
    check_schema(countries, "countries.schema.json", "countries.yaml", problems)
    check_schema(contests, "contests.schema.json", "contests.yaml", problems)
    check_schema(judgements, "judgements.schema.json", "judgements.yaml", problems)
    check_schema(sources, "sources.schema.json", "sources.yaml", problems)

    # ---- countries
    clist = countries.get("countries", [])
    codes = [c.get("code") for c in clist]
    for d in duplicates(codes):
        problems.append(f"countries.yaml: duplicate country code {d}")
    orders = sorted(c.get("tab_order", 0) for c in clist)
    if orders != list(range(1, len(clist) + 1)):
        problems.append("countries.yaml: tab_order must run 1..N without gaps or repeats")
    for c in clist:
        expected = "presidential" if c.get("code") in PRESIDENTIAL_FIRST else "parliamentary"
        if c.get("headline_kind") != expected:
            problems.append(
                f"countries.yaml: {c.get('code')} headline_kind is {c.get('headline_kind')}, "
                f"rule G-002 expects {expected}"
            )
    code_set = set(codes)

    # ---- contests
    klist = contests.get("contests", [])
    ids = [k.get("contest_id") for k in klist]
    for d in duplicates(ids):
        problems.append(f"contests.yaml: duplicate contest_id {d}")
    id_set = set(ids)
    for k in klist:
        cid, cc = k.get("contest_id", "?"), k.get("country")
        if cc not in code_set:
            problems.append(f"contests.yaml: {cid}: unknown country {cc}")
        if isinstance(cc, str) and not cid.startswith(cc.lower() + "-"):
            problems.append(f"contests.yaml: {cid}: id must start with '{cc.lower()}-'")
        kind_tag = {"presidential": "pres", "parliamentary": "parl", "regional": "sub"}.get(k.get("kind"))
        if kind_tag and f"-{kind_tag}-" not in cid:
            problems.append(f"contests.yaml: {cid}: id does not match kind {k.get('kind')}")
        if k.get("rounds") == 2 and k.get("date") and "round_dates" in k and k["round_dates"][0] != k["date"]:
            problems.append(f"contests.yaml: {cid}: round_dates[0] must equal date")
        if k.get("previous_date") and k.get("date") and k["previous_date"] >= k["date"]:
            problems.append(f"contests.yaml: {cid}: previous_date is not before date")
    for c in clist:
        cc = c.get("code")
        national = [k for k in klist if k.get("country") == cc and k.get("tier") == "national"]
        kinds = {k.get("kind") for k in national}
        if "parliamentary" not in kinds:
            problems.append(f"contests.yaml: {cc} has no national parliamentary contest")
        if c.get("headline_kind") == "presidential" and "presidential" not in kinds:
            problems.append(f"contests.yaml: {cc} is presidential-first but has no presidential contest")
        if c.get("headline_kind") == "parliamentary" and "presidential" in kinds:
            problems.append(f"contests.yaml: {cc} has a presidential contest but a parliamentary headline")

    # ---- sources
    for s in sources.get("sources", []):
        if s.get("contest_id") not in id_set:
            problems.append(f"sources.yaml: unknown contest_id {s.get('contest_id')}")
    pairs = [(s.get("contest_id"), s.get("priority")) for s in sources.get("sources", [])]
    for d in duplicates(pairs):
        problems.append(f"sources.yaml: two sources share contest and priority {d}")

    # ---- judgements
    jlist = judgements.get("judgements", [])
    for d in duplicates(j.get("id") for j in jlist):
        problems.append(f"judgements.yaml: duplicate id {d}")
    for j in jlist:
        jid, cc = j.get("id", "?"), j.get("country")
        if cc != "ALL" and cc not in code_set:
            problems.append(f"judgements.yaml: {jid}: unknown country {cc}")
        prefix = "G" if cc == "ALL" else cc
        if isinstance(prefix, str) and not jid.startswith(prefix + "-"):
            problems.append(f"judgements.yaml: {jid}: id prefix does not match country {cc}")
        if j.get("decided_on") and j.get("review_by") and j["review_by"] <= j["decided_on"]:
            problems.append(f"judgements.yaml: {jid}: review_by is not after decided_on")

    # ---- party files (none are seeded; validate any that exist)
    party_files = sorted(p for p in (CONFIG / "parties").glob("*.yaml") if not p.name.startswith("_"))
    for path in party_files:
        doc = iso(yaml.safe_load(path.read_text(encoding="utf-8")))
        check_schema(doc, "parties.schema.json", f"parties/{path.name}", problems)
        if doc.get("country") != path.stem:
            problems.append(f"parties/{path.name}: country must equal the file name")
        if doc.get("country") not in code_set:
            problems.append(f"parties/{path.name}: unknown country {doc.get('country')}")
        for d in duplicates(p.get("party_id") for p in doc.get("parties", [])):
            problems.append(f"parties/{path.name}: duplicate party_id {d}")

    # ---- report
    statuses = Counter(j.get("status") for j in jlist)
    unverified_sources = sum(1 for s in sources.get("sources", []) if not s.get("verified"))
    unopened = sum(1 for k in klist if k.get("verification") != "opened")
    print(f"countries:  {len(clist)}")
    print(f"contests:   {len(klist)}  ({unopened} not verified on an opened page)")
    print(f"judgements: {len(jlist)}  ({statuses.get('on_watch', 0)} on watch)")
    print(f"sources:    {len(sources.get('sources', []))}  ({unverified_sources} with verified: false)")
    print(f"party files: {len(party_files)}")

    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
