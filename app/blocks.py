"""A page is a list of blocks. Views build the list once; two renderers draw it.

`to_streamlit` draws blocks with Streamlit widgets and `to_html` writes them as static HTML for
scripts/snapshot.py. Because both walk the same list, the snapshot cannot drift from the app.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html import escape

import pandas as pd

PLOTLY_CONFIG = {"displayModeBar": False, "responsive": True}
SNAPSHOT_TABLE_ROWS = 25


@dataclass
class Html:
    html: str


@dataclass
class Figure:
    fig: object
    key: str


@dataclass
class Columns:
    columns: list[list]
    widths: list[int] = field(default_factory=lambda: [1, 1])


@dataclass
class Table:
    """The rows behind a chart, with a CSV download in the app."""
    frame: pd.DataFrame
    key: str
    file_name: str


@dataclass
class Expander:
    title: str
    blocks: list
    open: bool = False


def to_streamlit(blocks: list) -> None:
    import streamlit as st

    for b in blocks:
        if isinstance(b, Html):
            st.html(b.html)
        elif isinstance(b, Figure):
            st.plotly_chart(b.fig, key=b.key, config=PLOTLY_CONFIG)
        elif isinstance(b, Columns):
            for col, inner in zip(st.columns(b.widths), b.columns):
                with col:
                    to_streamlit(inner)
        elif isinstance(b, Table):
            st.dataframe(b.frame, hide_index=True, key=b.key)
            st.download_button("Download CSV", b.frame.to_csv(index=False), file_name=b.file_name,
                               mime="text/csv", key=b.key + "-csv")
        elif isinstance(b, Expander):
            with st.expander(b.title, expanded=b.open):
                to_streamlit(b.blocks)


def to_html(blocks: list) -> str:
    out = []
    for b in blocks:
        if isinstance(b, Html):
            out.append(b.html)
        elif isinstance(b, Figure):
            out.append('<div class="rg-fig">' + b.fig.to_html(
                full_html=False, include_plotlyjs=False, config=PLOTLY_CONFIG, div_id=b.key) + "</div>")
        elif isinstance(b, Columns):
            cells = "".join(f'<div style="flex:{w} 1 {18 * w}rem;min-width:0">{to_html(inner)}</div>'
                            for w, inner in zip(b.widths, b.columns))
            out.append(f'<div class="rg-cols">{cells}</div>')
        elif isinstance(b, Table):
            head = "".join(f"<th>{escape(str(c))}</th>" for c in b.frame.columns)
            body = "".join("<tr>" + "".join(f"<td>{'' if pd.isna(v) else escape(str(v))}</td>" for v in row) + "</tr>"
                           for row in b.frame.head(SNAPSHOT_TABLE_ROWS).itertuples(index=False))
            note = (f'<p class="rg-muted">First {SNAPSHOT_TABLE_ROWS} of {len(b.frame):,} rows. '
                    "The app shows them all and offers a CSV download.</p>") if len(b.frame) > SNAPSHOT_TABLE_ROWS else ""
            out.append(f'<div class="rg"><div class="rg-scroll"><table class="rg-table rg-small"><thead><tr>{head}'
                       f"</tr></thead><tbody>{body}</tbody></table></div>{note}</div>")
        elif isinstance(b, Expander):
            out.append(f'<details class="rg-fold"{" open" if b.open else ""}><summary>{escape(b.title)}</summary>'
                       f'<div class="rg-fold-body">{to_html(b.blocks)}</div></details>')
    return "".join(out)


def has_figure(blocks: list) -> bool:
    for b in blocks:
        if isinstance(b, Figure):
            return True
        inner = b.blocks if isinstance(b, Expander) else [x for col in b.columns for x in col] if isinstance(b, Columns) else []
        if inner and has_figure(inner):
            return True
    return False
