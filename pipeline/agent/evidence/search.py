"""Budgeted Brave discovery; snippets never become evidence for the writer."""

import hashlib
import json
import logging
import os
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlencode

from agent.services import _http

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchHit:
    url: str
    title: str = ""
    description: str = ""


Search = Callable[[str], list[SearchHit]]


class SearchStopped(ValueError):
    """No more paid searches should be attempted for this candidate/run."""


class BraveSearch:
    def __init__(
        self,
        cache_dir: Path,
        api_key: str | None = None,
        *,
        max_requests: int | None = None,
        daily_limit: int | None = None,
        monthly_limit: int | None = None,
        persist_results: bool | None = None,
    ):
        self.cache_dir = cache_dir
        self.api_key = api_key if api_key is not None else os.environ.get("BRAVE_SEARCH_API_KEY", "")
        self.max_requests = self._limit(max_requests, "WEARY_SEARCH_REQUESTS_PER_RUN", 6)
        self.daily_limit = self._limit(daily_limit, "WEARY_SEARCH_REQUESTS_PER_DAY", 6)
        self.monthly_limit = self._limit(monthly_limit, "WEARY_SEARCH_REQUESTS_PER_MONTH", 100)
        self.persist_results = (
            persist_results
            if persist_results is not None
            else os.environ.get("WEARY_BRAVE_STORAGE_ALLOWED", "false").lower() == "true"
        )
        self.requests = 0
        self.memory: dict[str, list[SearchHit]] = {}
        self.stopped = False

    @staticmethod
    def _limit(value: int | None, variable: str, default: int) -> int:
        return max(0, value if value is not None else int(os.environ.get(variable, str(default))))

    def _reserve_request(self) -> None:
        # Reserve BEFORE calling the provider: failed/timed-out requests may be billed.
        # SQLite serializes reservations across processes sharing this directory.
        if self.requests >= self.max_requests:
            raise SearchStopped("search_budget_exhausted: per-run request limit")
        now = datetime.now(UTC)
        day, month = now.date().isoformat(), now.strftime("%Y-%m")
        path = self.cache_dir.parent / "search-budget" / "usage.sqlite3"
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS requests (day TEXT PRIMARY KEY, count INTEGER NOT NULL)")
            db.execute("BEGIN IMMEDIATE")
            daily = db.execute("SELECT COALESCE(SUM(count), 0) FROM requests WHERE day = ?", (day,)).fetchone()[0]
            monthly = db.execute(
                "SELECT COALESCE(SUM(count), 0) FROM requests WHERE day LIKE ?", (month + "%",)
            ).fetchone()[0]
            if daily >= self.daily_limit or monthly >= self.monthly_limit:
                raise SearchStopped("search_budget_exhausted: daily/monthly request limit")
            db.execute("INSERT INTO requests VALUES (?, 1) ON CONFLICT(day) DO UPDATE SET count = count + 1", (day,))
        self.requests += 1
        log.info(
            "brave request: run %s/%s, UTC day %s/%s, month %s/%s",
            self.requests,
            self.max_requests,
            daily + 1,
            self.daily_limit,
            monthly + 1,
            self.monthly_limit,
        )

    def __call__(self, query: str) -> list[SearchHit]:
        return self._search(query)

    def on_day(self, query: str, day: date) -> list[SearchHit]:
        """Historical discovery shares the same budget, cache and error stop."""
        return self._search(query, freshness=f"{day.isoformat()}to{day.isoformat()}")

    def _search(self, query: str, freshness: str = "") -> list[SearchHit]:
        query = " ".join(query.split())
        if not query or len(query) > 600 or len(query.split()) > 75:
            raise ValueError("search_failed: query outside Brave's length limits")
        params = {
            "q": query,
            "count": 8,
            "result_filter": "web",
            "extra_snippets": "false",
            "summary": "false",
            "text_decorations": "false",
        }
        if freshness:
            params["freshness"] = freshness
        encoded = urlencode(params)
        key = hashlib.sha256(encoded.encode()).hexdigest()
        if key in self.memory:
            log.info("brave cache hit: memory (no request)")
            return list(self.memory[key])
        cache = self.cache_dir / f"brave-{key}.json"
        if self.persist_results and cache.exists() and time.time() - cache.stat().st_mtime < 86400:
            try:
                hits = self._parse(json.loads(cache.read_text()))
                self.memory[key] = hits
                log.info("brave cache hit: disk (no request)")
                return list(hits)
            except (ValueError, OSError):
                pass
        if not self.api_key:
            raise SearchStopped("search_unavailable: BRAVE_SEARCH_API_KEY is not configured")
        if self.stopped:
            raise SearchStopped("search_stopped: an earlier request failed; using direct links/cached results only")
        self._reserve_request()
        try:
            raw = _http.get(
                "https://api.search.brave.com/res/v1/web/search?" + encoded,
                headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"},
                timeout=20,
                retries=1,
            )
            data = json.loads(raw)
            hits = self._parse(data)
        except Exception as error:
            self.stopped = True
            # Avoid repeating paid calls on errors, including uncertain timeouts.
            raise SearchStopped(
                f"search_failed: {type(error).__name__}; further requests stopped for this run"
            ) from error
        self.memory[key] = hits
        if self.persist_results:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            temporary = cache.with_suffix(".tmp")
            temporary.write_text(json.dumps(data))
            temporary.replace(cache)
        return list(hits)

    @staticmethod
    def _parse(data: object) -> list[SearchHit]:
        if not isinstance(data, dict) or "error" in data or data.get("type") == "ErrorResponse":
            raise ValueError("Invalid Brave response")
        # A valid web search with no results can omit the web section.
        web = data.get("web", {})
        if not isinstance(web, dict) or not isinstance(web.get("results", []), list):
            raise ValueError("Invalid Brave web results")
        if "web" not in data and data.get("type") != "search":
            raise ValueError("Invalid Brave response")
        return [
            SearchHit(
                row["url"],
                row["title"] if isinstance(row.get("title"), str) else "",
                row["description"] if isinstance(row.get("description"), str) else "",
            )
            for row in web.get("results", [])[:8]
            if isinstance(row, dict) and isinstance(row.get("url"), str)
        ]
