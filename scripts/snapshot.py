#!/usr/bin/env python3
"""Render app pages to one self-contained HTML file for review.

Usage:  python scripts/snapshot.py method                 # the register and calendar
        python scripts/snapshot.py overview DE FR method  # several pages in one file
        python scripts/snapshot.py --out snapshots/phase0.html method

Each page is built by the same view code the Streamlit app runs, so the file is a picture of the
app. Nothing is fetched: charts carry their data and the Plotly library is inlined.
"""
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from plotly.offline import get_plotlyjs  # noqa: E402

from app import components, data  # noqa: E402
from app.blocks import Html, has_figure, to_html  # noqa: E402
from app.views import country, method, overview  # noqa: E402
from pipeline import config  # noqa: E402

PAGE_CSS = """
body { background: var(--rg-bg); color: var(--rg-fg); font-family: var(--rg-sans); }
.snap { max-width: 60rem; margin: 0 auto; padding-block: 1.5rem 3rem;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
.snap > header h1 { font-size: 1.6rem; margin: 0; text-wrap: balance; }
.snap > header p { margin: 0.3rem 0 0; color: var(--rg-muted); font-size: 0.85rem; }
.snap > section { margin-top: 1.5rem; padding-top: 0.5rem; border-top: 2px solid var(--rg-line); }
"""


def commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def page_blocks(name: str, today: dt.date, data_dir: Path) -> list:
    if name == "overview":
        return [Html(overview.page_html(today, data_dir))]
    if name == "method":
        return [Html(method.page_html(data_dir))]
    codes = {c["code"] for c in config.countries()}
    if name.upper() in codes:
        return country.build(name.upper(), today, data_dir=data_dir)
    raise SystemExit(f"unknown page '{name}': use overview, method or a country code")


def build(pages: list[str], title: str, today: dt.date | None = None, data_dir: Path = data.DATA) -> str:
    """One self-contained page. Charts need Plotly, which is inlined once so nothing is fetched."""
    now = dt.datetime.now(dt.timezone.utc)
    today = today or now.date()
    built = [page_blocks(p, today, data_dir) for p in pages]
    sections = "".join(f"<section>{to_html(b)}</section>" for b in built)
    charts = any(has_figure(b) for b in built)
    script = f"<script>{get_plotlyjs()}</script>\n" if charts else ""
    as_of = data.quality(data_dir).get("data_as_of")
    stamp = f"data as of {as_of[:16].replace('T', ' ')} UTC" if as_of else "configuration only, no polling data"
    # Charts are drawn for a light surface, as in the app, so a page with charts stays light.
    return (
        '<meta charset="utf-8">\n'
        f"<title>{escape(title)}</title>\n"
        '<meta name="claude:viewport-fit-sides" content="cover">\n'
        f"<style>{components.css(dark=not charts)}{PAGE_CSS}</style>\n{script}"
        '<div class="snap"><header>'
        f"<h1>{escape(title)}</h1>"
        f"<p>Snapshot of the app at commit {escape(commit())}, rendered {now:%Y-%m-%d %H:%M} UTC; {stamp}.</p>"
        f"</header>{sections}</div>\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pages", nargs="+", help="overview, method, or country codes")
    ap.add_argument("--out", default="snapshots/snapshot.html")
    ap.add_argument("--title", default="European election polling")
    ap.add_argument("--data-dir", type=Path, default=data.DATA)
    ap.add_argument("--today", help="ISO date to render as (default: today, UTC)")
    args = ap.parse_args()
    out = Path(args.out) if Path(args.out).is_absolute() else ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    today = dt.date.fromisoformat(args.today) if args.today else None
    out.write_text(build(args.pages, args.title, today, args.data_dir), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size // 1024} KB, {len(args.pages)} page(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
