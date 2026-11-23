"""European election polling dashboard. Run with: streamlit run app/streamlit_app.py

One tab strip: Overview, the 18 countries, Method. The strip is bound to the `tab` query parameter,
so a link opens on a country, and only the open tab's code runs.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from app import components  # noqa: E402
from app.views import country, method, overview  # noqa: E402
from pipeline import config  # noqa: E402

st.set_page_config(page_title="European election polling", layout="wide")
st.html(components.STATIC / "register.css")  # a .css path is applied to the app as a stylesheet
st.title("European election polling")

countries = config.countries()
labels = ["Overview"] + [c["name"] for c in countries] + ["Method"]
tabs = st.tabs(labels, key="tab", bind="query-params", default="Overview")

for label, tab in zip(labels, tabs):
    if not tab.open:
        continue  # only the open tab loads or draws anything
    with tab:
        if label == "Overview":
            overview.render()
        elif label == "Method":
            method.render()
        else:
            country.render(next(c["code"] for c in countries if c["name"] == label))
