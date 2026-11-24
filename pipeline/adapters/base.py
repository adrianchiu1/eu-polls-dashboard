"""What every adapter shares: the failure type, the HTTP session and the result container."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import pandas as pd
import requests

USER_AGENT = "eu-polls-dashboard/0.1 (https://github.com/adrianchiu1/eu-polls-dashboard; daily poll fetch)"


class AdapterError(Exception):
    """A pull that must not be published. The runner keeps the last good file and marks the contest stale."""


@dataclass
class ContestPull:
    """One contest's rows from one source, before validation."""
    contest_id: str
    polls: pd.DataFrame
    results: pd.DataFrame | None = None       # official result rows found in the source, if any
    warnings: list[str] = field(default_factory=list)
    unmapped: dict[str, list[float]] = field(default_factory=dict)   # label not in the party file -> its figures


def session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def get(s: requests.Session, url: str, *, params: dict | None = None, tries: int = 6, timeout: int = 90):
    """GET with backoff on 429 and 5xx. Raises AdapterError when the source keeps refusing."""
    last = "no attempt"
    for attempt in range(tries):
        try:
            r = s.get(url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            last = repr(exc)
        else:
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
            if r.status_code not in (429, 500, 502, 503, 504):
                break
            retry_after = r.headers.get("Retry-After", "")
            if retry_after.isdigit():
                time.sleep(min(int(retry_after), 120))
                continue
        time.sleep(min(10 * (attempt + 1), 60))
    raise AdapterError(f"{url}: {last}")
