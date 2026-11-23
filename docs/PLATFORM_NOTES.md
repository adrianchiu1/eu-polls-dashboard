# Platform notes

Facts about where this runs, checked on 23 Nov 2026 against the Streamlit documentation. Platforms
change; re-read the linked pages before designing around a limit.

## Streamlit Community Cloud

Sources: [Manage your app](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app),
[Status and limitations](https://docs.streamlit.io/deploy/streamlit-community-cloud/status).

- **Deploys from GitHub.** The repository is the app's source. A pushed change shows almost at once.
  A change to `requirements.txt` triggers a slower full redeploy. So the daily data commit is the
  refresh; nothing else is needed.
- **Sleeps when idle.** An app with no traffic for 12 hours goes to sleep. Any visitor wakes it with
  one click and a short wait. Tell the team to expect this.
- **Resources.** Roughly 2.7 GB of memory, 2 CPU cores and 50 GB of storage at most, as documented in
  February 2024 and subject to change. Keep data in per-country files and cache loads.
- **Location.** All apps are hosted in the United States.
- **Versions.** Pin Streamlit in `requirements.txt`; an unpinned version can upgrade without warning.
  Only Python versions still receiving security updates are supported.
- **Config.** `.streamlit/config.toml` at the repository root is read. The platform overrides some
  settings.
- **Update rate.** Updates from GitHub are limited to five per minute. One data commit a day is far
  inside it; do not commit per country.

## Checked in Phase 0 (23 Nov 2026)

- **Tabs.** `st.tabs` in Streamlit 1.67 takes `key`, `default` and `bind="query-params"`. With the
  binding set, each returned tab has an `open` property and the app skips the code of closed tabs.
  `app/streamlit_app.py` uses this: the open tab is in the URL as `?tab=<label>`, for example
  `?tab=France`, and only that tab's view runs. Confirmed in a browser against a local run. No
  substitute selector is needed.
- **Versions.** Streamlit 1.67.0 (released 5 Nov 2026) needs Python 3.11 or later. Community Cloud
  defaults to Python 3.12 and supports only releases still receiving security updates. The Python
  version is chosen in the deploy dialog, not in a file: choose 3.12. CI runs on 3.12 as well.
  `requirements.txt` pins the app's packages; `requirements-dev.txt` adds the pipeline and test ones.
- **Custom HTML.** `st.html` sanitises its input. A stylesheet passed as a `.css` path is applied to
  the app, but a stylesheet containing an angle bracket anywhere, a comment included, is dropped
  whole and silently. A test guards this.
- **Theme.** `.streamlit/config.toml` pins the light theme, so the app's own styles carry light
  values only. Snapshot pages add dark values and follow the viewer's theme.

## Implications for the app

- Read data from the repository checkout (`data/*.csv`), not over the network.
- Cache with a key that includes the file's modification time or the commit, so a redeploy shows new
  data without a manual cache clear.
- Load one country at a time. Check how the current Streamlit tab component behaves: if it runs every
  tab's code on each rerun, use a tab-styled selector bound to a URL query parameter.
- Show "data as of" from `data/quality.json`, not from the clock.

## GitHub Actions

- `fetch.yml`: once a day on a schedule, and on manual dispatch. Fetch, normalise, validate, average,
  scan triggers, then one commit prefixed `data:` if and only if a file changed.
- `tests.yml`: on every push and pull request. Config validation, averaging fixtures, parser fixtures.
- A failed fetch must fail the job visibly and commit nothing.
- Scheduled workflows in a public repository stop after a long period without repository activity.
  The daily data commits normally count as activity; confirm this in GitHub's current documentation.

## Review artifacts

AC reviews rendered pages. `scripts/snapshot.py` should:

1. Take a list of country codes (or `overview`, `method`).
2. Build each page from the same figure functions the app uses (`app/charts.py`) and the same data.
3. Write one self-contained HTML file per page, or one file with all pages: charts inlined, no network
   requests, readable at phone width.
4. Stamp the commit hash and "data as of" at the top.

Publish the result as a private Claude artifact when the session has an artifact tool; otherwise
attach the HTML file. The snapshot is a picture of the app, not a second front end: no interactivity
beyond what the charts carry, and no logic that the app does not have.

## Weekly check

A Claude scheduled task, Mondays. Its prompt is `ops/weekly-check-prompt.md`. It needs push access to
this repository to open pull requests and web search to verify calendar rows. It never merges.
