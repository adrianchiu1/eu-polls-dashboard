"""Wikipedia adapter: polling tables from a pinned revision of an English Wikipedia article (CC BY-SA 4.0).

Each contest's source entry in config/sources.yaml names the article (`locator`), says which tables
to read (`selector`) and may map header labels to party ids (`column_map`).

Selector: `key=value` pairs separated by semicolons.
    top=<heading>        tables whose outermost heading is this (several: separate with |)
    under=<heading>      tables with this heading anywhere above them
    exclude=<heading>    skip tables with this heading anywhere above them (several: |)
    round2_top=<heading> tables of second-round match-ups; each pair of candidates is a line-up
    lineups=field        every row of a poll is a tested field of candidates (French presidential);
                         default: the first row of a poll is the headline, later rows are alternatives
    sums=partial         the tables do not list every party, so share sums are not checked

A layout the parser does not recognise raises AdapterError: nothing is published from a table it
cannot read in full.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re

import pandas as pd

from pipeline import model
from pipeline.config import previous_contest_id
from pipeline.adapters import wikitable
from pipeline.adapters.base import AdapterError, ContestPull, get, session
from pipeline.parties import Resolver, norm_label

SITE = "https://en.wikipedia.org"
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
DASH = r"[–—−-]"
NOT_REPORTED = {"", "–", "—", "-", "−", "?", "n/a", "na", "tba", "tbc", "did not exist"}
RESULT_ROW = re.compile(r"\b(election|result)", re.I)


# --------------------------------------------------------------------------- fetching
def latest_revision(title: str, s=None) -> tuple[str, str]:
    """(revision id, canonical title) of the article's current revision."""
    s = s or session()
    data = get(s, f"{SITE}/w/api.php", params={
        "action": "query", "titles": title, "redirects": 1, "prop": "revisions", "rvprop": "ids",
        "format": "json", "formatversion": 2}).json()
    page = data["query"]["pages"][0]
    if page.get("missing") or not page.get("revisions"):
        raise AdapterError(f"Wikipedia: no article '{title}'")
    return str(page["revisions"][0]["revid"]), page["title"]


def fetch_html(revision: str, s=None) -> str:
    """The rendered content of one pinned revision, reduced to headings, tables and references."""
    s = s or session()
    html = get(s, f"{SITE}/w/index.php", params={"oldid": revision, "action": "render"}).text
    return wikitable.reduce(html)


def permalink(title: str, revision: str) -> str:
    return f"{SITE}/w/index.php?title={title.replace(' ', '_')}&oldid={revision}"


# --------------------------------------------------------------------------- cells
def parse_selector(selector: str) -> dict:
    out: dict = {}
    for part in selector.split(";"):
        if "=" not in part:
            if part.strip():
                raise AdapterError(f"selector part '{part.strip()}' is not key=value")
            continue
        key, value = part.split("=", 1)
        out[key.strip()] = [v.strip() for v in value.split("|")] if key.strip() != "lineups" and key.strip() != "sums" else value.strip()
    return out


def parse_value(text: str) -> float | None:
    """The first number in a cell ('31.7 130' is a share with seats beneath it). None if not reported."""
    t = text.strip()
    if t.lower() in NOT_REPORTED:
        return None
    m = re.match(r"^[<>≈~]?\s*(\d+(?:[.,]\d+)?)\s*%?", t)
    if not m:
        return None
    return float(m.group(1).replace(",", "."))


def parse_sample(text: str) -> int | None:
    m = re.match(r"^\s*(\d{1,3}(?:[,.\s]\d{3})+|\d+)", text)
    if not m:
        return None
    n = int(re.sub(r"[,.\s]", "", m.group(1)))
    return n if n > 0 else None


def _part(text: str):
    """One side of a date range: (day, month or None, year or None)."""
    m = re.match(r"^\s*(\d{1,2})?\s*([A-Za-z]{3,9})?\.?\s*(\d{4})?\s*$", text)
    if not m or not (m.group(1) or m.group(2)):
        return None
    month = MONTHS.get(m.group(2)[:3].lower()) if m.group(2) else None
    if m.group(2) and month is None:
        return None
    return (int(m.group(1)) if m.group(1) else None, month, int(m.group(3)) if m.group(3) else None)


def parse_dates(text: str, default_year: int | None) -> tuple[dt.date | None, dt.date] | None:
    """'18–20 Nov', '31 Dec–3 Jan', '16 Nov 2026' to (start, end). The year comes from the cell, else
    from the heading above the table; a range that wraps the new year starts the year before."""
    t = re.sub(r"\[.*?\]", "", text).strip()
    pieces = [p for p in re.split(rf"\s*{DASH}\s*", t) if p.strip()]
    if not 1 <= len(pieces) <= 2:
        return None
    end = _part(pieces[-1])
    if end is None or end[0] is None or end[1] is None:
        return None
    year = end[2] or default_year
    if year is None:
        return None
    try:
        end_date = dt.date(year, end[1], end[0])
        if len(pieces) == 1:
            return None, end_date
        if pieces[0].strip() == "?":                      # start of fieldwork not published
            return None, end_date
        start = _part(pieces[0])
        if start is None or start[0] is None:
            return None
        s_month = start[1] or end[1]
        s_year = start[2] or (year - 1 if s_month > end[1] else year)
        return dt.date(s_year, s_month, start[0]), end_date
    except ValueError:
        return None


def _heading_year(path: tuple[str, ...]) -> int | None:
    for heading in reversed(path):
        m = re.match(r"^\s*(?:[A-Za-z]+\s+)?(\d{4})\b", heading)
        if m:
            return int(m.group(1))
    return None


# --------------------------------------------------------------------------- columns
ROLE_WORDS = {
    "pollster": ("pollingfirm", "pollster", "pollingorganisation", "pollingorganization"),
    "date": ("fieldworkdate", "datesconducted", "dateconducted", "date"),
    "sample": ("samplesize", "sample"),
    "client": ("client", "commissioner"),
    "area": ("area",),
    "ignore": ("lead", "turnout", "notes", "majority"),
}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def classify(table: wikitable.Table, column_map: dict, resolver: Resolver, on: dt.date | None):
    """For every column: ('pollster' | 'date' | 'sample' | 'client' | 'area' | 'ignore' | 'party', party id).

    A party column that resolves to nothing is ('party', None): its figures are folded into others
    and reported.
    """
    cmap = {norm_label(k): v for k, v in (column_map or {}).items()}
    out = []
    for c in range(table.width):
        path = table.header_path(c)
        leaf = path[-1] if path else ""
        links = [l for cell in table.header_cells(c) for l in cell.links]
        group = path[0] if len(path) > 1 else ""
        mapped = cmap.get(norm_label(leaf)) if leaf else None
        if mapped is None and not leaf:
            mapped = next((cmap[norm_label(l)] for l in links if norm_label(l) in cmap), None)
        if mapped in ROLE_WORDS:
            out.append((mapped, None)); continue
        if mapped:
            out.append(("party", mapped)); continue
        n = _norm(leaf)
        role = None
        if _norm(group) in ("coalitions",):
            role = "ignore"
        elif n.startswith("pollingfirm") and "commissioner" in n:
            role = "pollster+client"
        else:
            for name, words in ROLE_WORDS.items():
                if n and any(n == w or (name in ("pollster", "sample") and n.startswith(w)) or (name == "date" and w in n) for w in words):
                    role = name
                    break
        if role:
            out.append((role, None)); continue
        if not leaf and not links:
            out.append(("ignore", None)); continue
        party = None
        for label in [leaf, *links, " ".join(path)]:
            if label:
                party = resolver.resolve(label, on)
                if party:
                    break
        out.append(("party", party))
    return out


def _label(table: wikitable.Table, c: int) -> str:
    path = table.header_path(c)
    if path:
        return path[-1]
    links = [l for cell in table.header_cells(c) for l in cell.links]
    return links[0] if links else f"column {c}"


# --------------------------------------------------------------------------- tables
def select(tables: list[wikitable.Table], sel: dict, key_top: str = "top") -> list[wikitable.Table]:
    out = []
    for t in tables:
        if not t.path:
            continue
        if key_top in sel and t.path[0] not in sel[key_top]:
            continue
        if key_top == "top" and "under" in sel and not any(h in sel["under"] for h in t.path):
            continue
        if key_top == "top" and "top" not in sel and "under" not in sel:
            continue
        if any(h in sel.get("exclude", []) for h in t.path):
            continue
        out.append(t)
    return out


def _lineup_id(parties: set[str]) -> str:
    return "f-" + hashlib.sha1("|".join(sorted(parties)).encode()).hexdigest()[:8]


def parse_table(table: wikitable.Table, contest: dict, source: dict, resolver: Resolver, sel: dict,
                cites: dict, title: str, revision: str, retrieved_at: dt.datetime, round_: int = 1):
    """One table to poll rows, result rows and warnings."""
    cid = contest["contest_id"]
    since = contest.get("previous_date")
    year = _heading_year(table.path)
    where = " / ".join(table.path)
    if table.n_header_rows == 0:
        raise AdapterError(f"{cid}: table under '{where}' has no header row")
    cols = classify(table, source.get("column_map") or {}, resolver, None)
    roles = [r for r, _ in cols]
    for needed in ("date",):
        if needed not in roles:
            raise AdapterError(f"{cid}: table under '{where}' has no {needed} column")
    if "pollster" not in roles and "pollster+client" not in roles:
        raise AdapterError(f"{cid}: table under '{where}' has no pollster column")
    party_cols = [c for c, (r, _) in enumerate(cols) if r == "party"]
    if len(party_cols) < 2:
        raise AdapterError(f"{cid}: table under '{where}' has fewer than two party columns")
    col = {r: roles.index(r) for r in set(roles) if r != "party"}
    p_col = col.get("pollster", col.get("pollster+client"))
    unmapped: dict[str, int] = {}
    warnings: list[str] = []
    polls: list[dict] = []
    results: list[dict] = []
    seen_rows: dict[tuple, int] = {}
    unread = 0

    for row in table.body():
        cells = [c for c in row if c is not None]
        if not cells:
            continue
        row = row + [None] * (table.width - len(row))     # a header may be wider than the rows
        p_cell, d_cell = row[p_col], row[col["date"]]
        if p_cell is None or d_cell is None:
            continue
        # an event row: one cell stretched over most of the party columns, or a body header
        wide = max((c.colspan for c in cells), default=1)
        if wide > max(len(party_cols) // 2, 2) and wide > 2 and not any(
                id(row[c]) != id(row[party_cols[0]]) for c in party_cols if row[c] is not None):
            continue
        if p_cell is d_cell:
            continue
        dates = parse_dates(d_cell.text, year)
        is_result = bool(RESULT_ROW.search(p_cell.text))
        values: dict[str, float] = {}
        done: set[int] = set()
        any_value = False
        for c in party_cols:
            cell = row[c]
            if cell is None or id(cell) in done or cell is p_cell:
                continue
            done.add(id(cell))
            value = parse_value(cell.text)
            if value is None:
                continue
            any_value = True
            span = [k for k in party_cols if row[k] is cell]
            if len(span) == 1:
                party = cols[c][1]
                if party is None:
                    unmapped[_label(table, c)] = unmapped.get(_label(table, c), 0) + 1
                    party = model.OTHERS
            else:
                members = {cols[k][1] for k in span}
                party = None if None in members else resolver.alliance(members)
                if party is None:
                    label = " + ".join(_label(table, k) for k in span)
                    unmapped[label] = unmapped.get(label, 0) + 1
                    party = model.OTHERS
            values[party] = round(values.get(party, 0.0) + value, 4)
        if not any_value:
            continue
        if dates is None:
            unread += 1
            continue
        start, end = dates
        if is_result:
            area = row[col["area"]].text if "area" in col and row[col["area"]] is not None else ""
            if area in ("", "GB") and end in (since, contest.get("date")):
                results.append({"values": values, "date": end})
            continue
        if since is not None and end <= since:
            continue
        if contest.get("date") and contest.get("status") == "held" and end > contest["date"]:
            continue                                      # belongs to the next cycle
        text = p_cell.text
        client = None
        if roles[p_col] == "pollster+client" and "/" in text:
            text, client = (x.strip() for x in text.split("/", 1))
        if "client" in col and row[col["client"]] is not None:
            raw = row[col["client"]].text.strip()
            client = raw if raw.lower() not in NOT_REPORTED else None
        pollster = re.sub(r"\s+", " ", text).strip()
        if not pollster or pollster in ("—", "–"):
            unread += 1
            continue
        sample = parse_sample(row[col["sample"]].text) if "sample" in col and row[col["sample"]] is not None else None
        url = next(iter(p_cell.urls), None) or next((cites[r] for r in p_cell.refs if r in cites), None)
        if url and url.startswith("//"):
            url = "https:" + url
        group = (id(p_cell), id(d_cell)) if p_cell.rowspan > 1 else (id(p_cell), id(d_cell), len(polls))
        index = seen_rows.get(group, 0)
        seen_rows[group] = index + 1
        flags = "party_commissioned" if client and _is_party(client, resolver) else ""
        polls.append({
            "poll_id": model.poll_id(cid, pollster, end, client, url or f"{where}|{p_cell.origin}"),
            "contest_id": cid, "round": round_, "lineup_id": "default" if index == 0 else f"alt-{index + 1}",
            "is_headline_lineup": index == 0, "pollster": pollster, "client": client,
            "fieldwork_start": start, "fieldwork_end": end, "sample_size": sample, "method": None,
            "unit": "pct", "flags": flags, "region": None,
            "source_url": url or permalink(title, revision), "adapter": "wikipedia",
            "source_rev": revision, "retrieved_at": retrieved_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "_values": values,
        })
    if unread:
        warnings.append(f"{unread} row(s) under '{where}' had figures but an unreadable date or pollster and were skipped")
    for label, n in sorted(unmapped.items()):
        warnings.append(f"label '{label}' under '{where}' is not in config/parties/{resolver.country}.yaml; "
                        f"{n} figure(s) folded into others")
    return polls, results, warnings


def _is_party(client: str, resolver: Resolver) -> bool:
    words = client.split()
    return any(resolver.resolve(" ".join(words[:n])) not in (None, model.OTHERS) for n in (1, 2, 3) if len(words) >= n)


def _assign_fields(polls: list[dict], window_days: int) -> None:
    """French presidential line-ups (judgement FR-001). Every row is a tested field of candidates.

    A row's line-up id names its field. Among a poll's rows the headline is the one closest to the
    field most pollsters were testing at the time: the candidates present in at least half of all
    rows whose fieldwork ended in the `window_days` before the poll. Ties go to the row listed first.
    """
    for p in polls:
        p["_field"] = frozenset(k for k in p["_values"] if k != model.OTHERS)
        p["lineup_id"] = _lineup_id(set(p["_field"]))
    by_poll: dict[str, list[dict]] = {}
    for p in polls:
        by_poll.setdefault(p["poll_id"], []).append(p)
    for rows in by_poll.values():
        end = rows[0]["fieldwork_end"]
        recent = [q for q in polls if end - dt.timedelta(days=window_days) < q["fieldwork_end"] <= end]
        count: dict[str, int] = {}
        for q in recent:
            for k in q["_field"]:
                count[k] = count.get(k, 0) + 1
        modal = {k for k, n in count.items() if 2 * n >= len(recent)}

        def distance(row):
            union = row["_field"] | modal
            return 1 - (len(row["_field"] & modal) / len(union) if union else 1)

        best = min(range(len(rows)), key=lambda i: (distance(rows[i]), i))
        seen: set[str] = set()
        for i, row in enumerate(rows):
            row["is_headline_lineup"] = i == best
            if row["lineup_id"] in seen:          # the same field twice in one poll: keep them apart
                row["lineup_id"] += f"-{i + 1}"
            seen.add(row["lineup_id"])


def parse(html: str, contest: dict, source: dict, resolver: Resolver, revision: str,
          retrieved_at: dt.datetime, window_days: int = 30) -> ContestPull:
    """All of one contest's polls in the current electoral cycle from one article revision."""
    cid = contest["contest_id"]
    sel = parse_selector(source["selector"])
    title = source["locator"]
    all_tables = wikitable.tables(html)
    cites = wikitable.citations(html)
    chosen = select(all_tables, sel)
    if not chosen:
        raise AdapterError(f"{cid}: no table matches selector '{source['selector']}' in '{title}'")
    polls, results, warnings = [], [], []
    for t in chosen:
        p, r, w = parse_table(t, contest, source, resolver, sel, cites, title, revision, retrieved_at)
        polls += p; results += r; warnings += w
    if sel.get("lineups") == "field":
        _assign_fields(polls, window_days)
    if "round2_top" in sel:
        for t in select(all_tables, sel, "round2_top"):
            p, _, w = parse_table(t, contest, source, resolver, sel, cites, title, revision, retrieved_at, round_=2)
            for row in p:
                row["lineup_id"] = "r2-" + "-vs-".join(sorted(k.split("-", 2)[-1] for k in row["_values"]))
                row["is_headline_lineup"] = False
            polls += p; warnings += w
    if not polls:
        raise AdapterError(f"{cid}: the selected tables in '{title}' hold no poll in the current cycle")

    rows = [dict({k: v for k, v in p.items() if not k.startswith("_")}, party_id=party, value=value)
            for p in polls for party, value in p["_values"].items()]
    frame = pd.DataFrame(rows, columns=model.POLL_COLUMNS)
    res = None
    if results:
        rows = []
        for r in results:
            # the contest's own result once it is held; otherwise the previous election to the body
            past = cid if r["date"] == contest.get("date") else previous_contest_id(contest)
            rows += [{"contest_id": past, "round": 1, "party_id": party, "vote_share": value,
                      "seats": None, "source_url": permalink(title, revision)}
                     for party, value in r["values"].items()]
        res = pd.DataFrame(rows, columns=model.RESULT_COLUMNS).drop_duplicates(["contest_id", "round", "party_id"])
    return ContestPull(cid, frame, results=res, warnings=warnings)
