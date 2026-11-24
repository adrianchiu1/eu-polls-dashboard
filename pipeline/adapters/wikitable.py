"""Wikipedia tables as grids: sections, spans, header paths, cell text and citations.

No polling knowledge lives here; pipeline/adapters/wikipedia.py builds on it. The approach follows
Europolls (github.com/gfrt0/europolls, MIT), which classifies header cells the same way but reads
wikitext; this reads the rendered HTML of a pinned revision, so templates are already expanded.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

HEADINGS = ("h2", "h3", "h4", "h5")


@dataclass
class Cell:
    text: str = ""
    is_header: bool = False
    colspan: int = 1
    rowspan: int = 1
    links: list[str] = field(default_factory=list)      # titles of wiki links in the cell
    refs: list[str] = field(default_factory=list)       # ids of the citations attached to the cell
    urls: list[str] = field(default_factory=list)       # external links inside the cell itself
    sort_value: str | None = None
    colour: str | None = None                           # background colour, as #rrggbb, if the cell sets one
    origin: tuple[int, int] = (0, 0)                    # grid position where the cell starts


@dataclass
class Table:
    path: tuple[str, ...]                               # headings above the table, outermost first
    grid: list[list[Cell | None]]                       # spans expanded: every position holds its cell
    n_header_rows: int
    caption: str = ""

    @property
    def width(self) -> int:
        return max((len(r) for r in self.grid), default=0)

    def header_path(self, col: int) -> tuple[str, ...]:
        """The header texts above a column, top to bottom, blanks and repeats removed."""
        out: list[str] = []
        for row in self.grid[: self.n_header_rows]:
            cell = row[col] if col < len(row) else None
            if cell is not None and cell.text and (not out or out[-1] != cell.text):
                out.append(cell.text)
        return tuple(out)

    def leaf(self, col: int) -> Cell | None:
        """The lowest header cell above a column that says something (text or a link).

        Colour bars under a header are skipped; a logo-only header is found through its link.
        """
        for cell in reversed(self.header_cells(col)):
            if cell.text or cell.links:
                return cell
        return None

    def header_cells(self, col: int) -> list[Cell]:
        return [row[col] for row in self.grid[: self.n_header_rows] if col < len(row) and row[col] is not None]

    def body(self) -> list[list[Cell | None]]:
        return self.grid[self.n_header_rows:]


def clean_text(node: Tag) -> str:
    """Visible text of a cell: citations, hidden spans and styles removed, whitespace folded."""
    node = BeautifulSoup(str(node), "lxml")
    for junk in node.select("sup.reference, style, link, .sr-only, .sortkey, .mw-ref, span[style*='display:none']"):
        junk.decompose()
    for br in node.find_all("br"):
        br.replace_with(" ")
    return re.sub(r"\s+", " ", node.get_text(" ")).replace(" ,", ",").strip()


def _cell(node: Tag, origin: tuple[int, int]) -> Cell:
    def span(name: str) -> int:
        raw = re.match(r"\d+", str(node.get(name, "1")).strip())
        return max(int(raw.group()), 1) if raw else 1

    refs = []
    for sup in node.select("sup.reference a[href], sup.mw-ref a[href]"):
        href = sup.get("href", "")
        if "#" in href:
            refs.append(href.split("#", 1)[1])
    links = [a.get("title", "") for a in node.select("a[title]") if not a.find_parent("sup")]
    urls = [a["href"] for a in node.select("a.external[href]") if not a.find_parent("sup")]
    for img in node.select("img[alt]"):
        if img.get("alt") and not img.find_parent("sup"):
            links.append(img["alt"])
    bg = re.search(r"background(?:-color)?\s*:\s*(#[0-9A-Fa-f]{6})\b", node.get("style", "") or "")
    return Cell(text=clean_text(node), is_header=node.name == "th", colspan=span("colspan"),
                rowspan=span("rowspan"), links=links, refs=refs, urls=urls,
                sort_value=node.get("data-sort-value"), colour=bg.group(1).upper() if bg else None,
                origin=origin)


def expand(table: Tag) -> list[list[Cell | None]]:
    """Rows of cells with rowspan and colspan expanded, so position (r, c) always has its cell."""
    grid: list[list[Cell | None]] = []
    carry: dict[int, tuple[Cell, int]] = {}             # column -> (cell, rows still to fill)
    rows = [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]
    for r, tr in enumerate(rows):
        row: list[Cell | None] = []
        cells = [c for c in tr.find_all(["th", "td"]) if c.find_parent("tr") is tr]
        c = 0
        it = iter(cells)
        pending = next(it, None)
        while pending is not None or any(col >= c for col in carry):
            if c in carry:
                cell, left = carry[c]
                row.append(cell)
                if left > 1:
                    carry[c] = (cell, left - 1)
                else:
                    del carry[c]
                c += 1
                continue
            if pending is None:
                row.append(None)
                c += 1
                continue
            cell = _cell(pending, (r, c))
            for k in range(cell.colspan):
                row.append(cell)
                if cell.rowspan > 1:
                    carry[c + k] = (cell, cell.rowspan - 1)
            c += cell.colspan
            pending = next(it, None)
        grid.append(row)
    return grid


def _header_rows(grid: list[list[Cell | None]]) -> int:
    """The number of leading rows made only of header cells."""
    n = 0
    for row in grid:
        cells = [c for c in row if c is not None]
        if not cells or not all(c.is_header for c in cells):
            break
        n += 1
    return n


def tables(html: str) -> list[Table]:
    """Every wikitable in an article, each with the headings it sits under."""
    soup = BeautifulSoup(html, "lxml")
    out: list[Table] = []
    path: dict[str, str] = {}
    for el in soup.find_all([*HEADINGS, "table"]):
        if el.name in HEADINGS:
            level = HEADINGS.index(el.name)
            for deeper in HEADINGS[level:]:
                path.pop(deeper, None)
            path[el.name] = clean_text(el)
            continue
        if "wikitable" not in (el.get("class") or []) or el.find_parent("table") is not None:
            continue
        grid = expand(el)
        caption = el.find("caption")
        out.append(Table(tuple(path[h] for h in HEADINGS if h in path), grid, _header_rows(grid),
                         clean_text(caption) if caption else ""))
    return out


KEEP_ATTRS = {"colspan", "rowspan", "class", "style", "href", "title", "alt", "data-sort-value"}


def reduce(html: str) -> str:
    """An article cut down to what the parser reads: headings, wikitables and the reference lists.

    Drops prose, images' sources and the editing metadata that makes up most of the rendered page.
    The adapter parses the reduced form, and test fixtures store it, so both see the same input.
    """
    soup = BeautifulSoup(html, "lxml")
    parts: list[str] = []
    for el in soup.find_all([*HEADINGS, "table", "ol"]):
        if el.name == "table":
            if "wikitable" not in (el.get("class") or []) or el.find_parent("table") is not None:
                continue
        elif el.name == "ol":
            if "references" not in (el.get("class") or []):
                continue
        for node in [el, *el.find_all(True)]:
            keep_id = node.name == "li" and str(node.get("id", "")).startswith("cite_note")
            for attr in list(node.attrs):
                if attr not in KEEP_ATTRS and not (attr == "id" and keep_id):
                    del node.attrs[attr]
            if node.name == "img":
                node.attrs = {"alt": node.get("alt", "")}
        for junk in el.select("style, link, script"):
            junk.decompose()
        parts.append(str(el))
    return "\n".join(parts)


def citations(html: str) -> dict[str, str]:
    """Citation id -> the first external link in that reference."""
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, str] = {}
    for li in soup.select("ol.references li[id], li[id^='cite_note']"):
        link = li.select_one("a.external[href]")
        if link is not None:
            href = link["href"]
            out[li["id"]] = "https:" + href if href.startswith("//") else href
    return out
