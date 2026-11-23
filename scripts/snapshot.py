#!/usr/bin/env python3
"""Render app pages to one self-contained HTML file for review.

Usage:  python scripts/snapshot.py method                 # the register and calendar
        python scripts/snapshot.py overview DE FR method  # several pages in one file
        python scripts/snapshot.py --out snapshots/phase0.html method

Each page comes from the same page_html function its Streamlit view shows, so the file is a picture
of the app. No scripts, no network requests.
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

from app import components  # noqa: E402
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


def render_page(name: str) -> str:
    if name == "overview":
        return overview.page_html()
    if name == "method":
        return method.page_html()
    codes = {c["code"] for c in config.countries()}
    if name.upper() in codes:
        return country.page_html(name.upper())
    raise SystemExit(f"unknown page '{name}': use overview, method or a country code")


def build(pages: list[str], title: str) -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sections = "".join(f"<section>{render_page(p)}</section>" for p in pages)
    return (
        f"<title>{escape(title)}</title>\n"
        '<meta name="claude:viewport-fit-sides" content="cover">\n'
        f"<style>{components.css(dark=True)}{PAGE_CSS}</style>\n"
        '<div class="snap"><header>'
        f"<h1>{escape(title)}</h1>"
        f"<p>Snapshot of the app at commit {escape(commit())}, rendered {stamp}. "
        "Configuration only: no polling data is loaded yet.</p>"
        f"</header>{sections}</div>\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pages", nargs="+", help="overview, method, or country codes")
    ap.add_argument("--out", default="snapshots/snapshot.html")
    ap.add_argument("--title", default="European election polling")
    args = ap.parse_args()
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(args.pages, args.title), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB, {len(args.pages)} page(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
