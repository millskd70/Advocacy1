"""Client for the Kansas Legislature REST API (https://www.kslegislature.gov/api/v1/).

The API is free and read-only. An API key is optional; without one the
limit is 30 requests/minute, with one it is 300/minute. Set the
KS_LEG_API_KEY environment variable (a GitHub secret) to use a key.

Field names are read defensively (upper- or lower-case, a few aliases),
because the API mirrors the older "v13" shape for bill status.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Iterable

import requests

BASE_URL = os.environ.get("KS_LEG_API_BASE", "https://www.kslegislature.gov/api/v1/")
USER_AGENT = "ks-leg-tracker (GitHub Actions; personal legislative tracking)"


def pick(d: Any, *names: str, default: Any = None) -> Any:
    """Return the first present, non-empty value among keys (case-insensitive)."""
    if not isinstance(d, dict):
        return default
    lower = {str(k).lower(): v for k, v in d.items()}
    for n in names:
        v = lower.get(n.lower())
        if v not in (None, "", [], {}):
            return v
    return default


class KansasLegAPI:
    def __init__(self, api_key: str | None = None, biennium: str | None = None,
                 fixtures_dir: str | None = None):
        self.api_key = api_key or os.environ.get("KS_LEG_API_KEY") or None
        self.biennium = biennium
        self.fixtures_dir = Path(fixtures_dir) if fixtures_dir else None
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.session.headers["Accept"] = "application/json"
        if self.api_key:
            self.session.headers["Authorization"] = f"Api-Key {self.api_key}"
        # Stay safely under the published limits.
        self.min_interval = 0.25 if self.api_key else 2.1
        self._last = 0.0
        self.request_count = 0

    # ------------------------------------------------------------ core
    def get(self, path: str, params: dict | None = None) -> Any:
        params = dict(params or {})
        if self.biennium and "biennium" not in params:
            params["biennium"] = self.biennium
        if self.fixtures_dir:
            return self._fixture(path, params)
        url = path if path.startswith("http") else BASE_URL + path.lstrip("/")
        for attempt in range(6):
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            self.request_count += 1
            try:
                r = self.session.get(url, params=params if not path.startswith("http") else None,
                                     timeout=60)
            except requests.RequestException as e:
                print(f"  network error on {url}: {e}; retrying")
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code == 429:
                retry = int(r.headers.get("Retry-After", "30") or 30)
                print(f"  rate limited; waiting {retry}s")
                time.sleep(min(retry, 120))
                continue
            if r.status_code >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"Giving up on {url} after repeated failures")

    def get_all(self, path: str, params: dict | None = None, max_pages: int = 200) -> list:
        """Follow DRF pagination (`results` + `next`) or the legacy `content` wrapper."""
        params = dict(params or {})
        params.setdefault("page_size", 1000)
        out: list = []
        data = self.get(path, params)
        pages = 0
        while data is not None and pages < max_pages:
            pages += 1
            if isinstance(data, list):
                out.extend(data)
                break
            items = pick(data, "results", "content", default=None)
            if items is None:
                # A single object rather than a list
                out.append(data)
                break
            out.extend(items if isinstance(items, list) else [items])
            nxt = data.get("next") if isinstance(data, dict) else None
            if not nxt:
                break
            data = self.get(nxt)
        return out

    # ------------------------------------------------------------ endpoints
    def bill_status_list(self) -> list[dict]:
        return self.get_all("bill_status/")

    def bill_status_detail(self, bill_no: str) -> dict | None:
        data = self.get(f"bill_status/{bill_no.lower()}/")
        if isinstance(data, dict):
            content = pick(data, "content", "results")
            if isinstance(content, list) and content:
                return content[0]
            return data
        if isinstance(data, list) and data:
            return data[0]
        return None

    def search_bills(self, query: str) -> list[dict]:
        data = self.get("search/", {"q": query, "type": "bills"})
        if data is None:
            return []
        if isinstance(data, list):
            return data
        items = pick(data, "results", "content", "bills", default=[])
        if isinstance(items, dict):  # grouped by type
            items = pick(items, "bills", default=[])
        return items if isinstance(items, list) else []

    def hearings(self, date_from: str, date_to: str) -> list[dict]:
        return self.get_all("hearings/", {"from": date_from, "to": date_to, "limit": 500})

    def hearing_detail(self, slug: str) -> dict | None:
        return self.get(f"hearings/{slug}/")

    def chamber_status(self) -> Any:
        try:
            return self.get("chamber_status/")
        except Exception as e:  # informational only
            print(f"  chamber_status unavailable: {e}")
            return None

    # ------------------------------------------------------------ offline testing
    def _fixture(self, path: str, params: dict) -> Any:
        """Read canned responses from tests/fixtures (used by the offline test)."""
        if path.startswith("http"):
            return None
        name = path.strip("/").replace("/", "__") or "root"
        q = params.get("q")
        candidates = []
        if q:
            candidates.append(f"{name}__q={q.lower().replace(' ', '_')}.json")
        candidates.append(f"{name}.json")
        for c in candidates:
            p = self.fixtures_dir / c
            if p.exists():
                return json.loads(p.read_text())
        if q or name.startswith("bill_status__"):
            return None
        return {"count": 0, "next": None, "results": []}


def biennium_for(year: int) -> str:
    start = year if year % 2 == 1 else year - 1
    return f"b{start}_{(start + 1) % 100:02d}"


def bill_url(bill_no: str, biennium: str) -> str:
    return f"https://www.kslegislature.gov/li/{biennium}/measures/{bill_no.lower()}/"


def iter_text(*vals: Iterable) -> str:
    parts = []
    for v in vals:
        if v is None:
            continue
        if isinstance(v, (list, tuple)):
            parts.extend(str(x) for x in v if x)
        else:
            parts.append(str(v))
    return " ".join(parts)
