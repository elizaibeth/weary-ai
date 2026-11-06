import json
import os
import sqlite3
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

from agent.evidence.search import BraveSearch, SearchStopped
from agent.evidence.source_rules import SourceRule, queries

RESULT = {
    "web": {"results": [{"url": "https://official.example/order", "title": "Order", "description": "Discovery only"}]}
}


def responder(monkeypatch, response=RESULT):
    calls = []

    def get(url, headers, timeout, retries):
        calls.append((url, headers, retries))
        return json.dumps(response).encode()

    monkeypatch.setattr("agent.evidence.search._http.get", get)
    return calls


def test_brave_request_is_minimal_and_reuses_normalized_query_in_memory(tmp_path, monkeypatch):
    calls = responder(monkeypatch)
    search = BraveSearch(tmp_path / "search", "test-key")
    first = search(" Anthropic   court order site:uscourts.gov ")
    assert search("Anthropic court order site:uscourts.gov") == first
    assert len(calls) == 1
    assert parse_qs(urlsplit(calls[0][0]).query) == {
        "q": ["Anthropic court order site:uscourts.gov"],
        "count": ["8"],
        "result_filter": ["web"],
        "extra_snippets": ["false"],
        "summary": ["false"],
        "text_decorations": ["false"],
    }
    assert calls[0][1]["X-Subscription-Token"] == "test-key"
    assert calls[0][2] == 1  # no automatic paid retries
    assert not list(tmp_path.rglob("*.json"))  # no API response retained by default
    first.clear()
    assert len(search("Anthropic court order site:uscourts.gov")) == 1


def test_persistent_cache_is_opt_in_and_survives_new_client_and_budget_exhaustion(tmp_path, monkeypatch):
    calls = responder(monkeypatch)
    cache = tmp_path / "search"
    expected = BraveSearch(cache, "test-key", persist_results=True)("query")
    assert BraveSearch(cache, "", max_requests=0, persist_results=True)("query") == expected
    assert len(calls) == 1
    assert all("test-key" not in p.read_text() for p in cache.glob("*.json"))
    # Storage-disabled clients do not reuse disk results.
    with pytest.raises(SearchStopped, match="per-run"):
        BraveSearch(cache, "test-key", max_requests=0, persist_results=False)("query")


@pytest.mark.parametrize("response", [{"type": "search"}, {"web": {"results": []}}])
def test_empty_search_is_cached_without_another_paid_request(tmp_path, monkeypatch, response):
    calls = responder(monkeypatch, response)
    search = BraveSearch(tmp_path / "search", "test-key")
    assert search("query") == search("query") == []
    assert len(calls) == 1


@pytest.mark.parametrize("response", [None, {}, {"error": "denied"}, {"web": None}, {"web": {"results": None}}])
def test_invalid_responses_stop_further_paid_requests(tmp_path, monkeypatch, response):
    calls = responder(monkeypatch, response)
    search = BraveSearch(tmp_path / "search", "test-key", persist_results=True)
    with pytest.raises(SearchStopped, match="search_failed"):
        search("query")
    with pytest.raises(SearchStopped, match="search_stopped"):
        search("different query")
    assert len(calls) == 1
    assert not list(tmp_path.rglob("*.json"))


def test_http_failure_is_counted_and_stops_further_requests(tmp_path, monkeypatch):
    calls = []

    def get(*args, **kwargs):
        calls.append(1)
        raise HTTPError("https://api.search.brave.com/", 429, "quota", {}, None)

    monkeypatch.setattr("agent.evidence.search._http.get", get)
    search = BraveSearch(tmp_path / "search", "test-key", daily_limit=1)
    with pytest.raises(SearchStopped, match="search_failed"):
        search("query")
    with pytest.raises(SearchStopped):
        search("another")
    with pytest.raises(SearchStopped, match="daily/monthly"):
        BraveSearch(tmp_path / "search", "test-key", daily_limit=1)("third")
    assert len(calls) == 1


def test_limits_apply_across_queries_clients_and_days(tmp_path, monkeypatch):
    calls = responder(monkeypatch)
    cache = tmp_path / "search"
    search = BraveSearch(cache, "test-key", max_requests=1)
    search("first")
    with pytest.raises(SearchStopped, match="per-run"):
        search("second")
    with pytest.raises(SearchStopped, match="daily/monthly"):
        BraveSearch(cache, "test-key", daily_limit=1)("third")
    # Simulate previous requests earlier in this month: the monthly cap still applies.
    with sqlite3.connect(tmp_path / "search-budget" / "usage.sqlite3") as db:
        db.execute("UPDATE requests SET day = substr(day, 1, 7) || '-00'")
    with pytest.raises(SearchStopped, match="daily/monthly"):
        BraveSearch(cache, "test-key", monthly_limit=1)("fourth")
    assert len(calls) == 1


def test_missing_key_and_zero_limit_cannot_send_requests(tmp_path, monkeypatch):
    calls = responder(monkeypatch)
    with pytest.raises(SearchStopped, match="BRAVE_SEARCH_API_KEY"):
        BraveSearch(tmp_path / "search", "")("query")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "environment-key")
    monkeypatch.setenv("WEARY_SEARCH_REQUESTS_PER_RUN", "0")
    with pytest.raises(SearchStopped, match="per-run"):
        BraveSearch(tmp_path / "search")("query")
    assert not calls


def test_expired_or_corrupt_disk_cache_refetches_within_budget(tmp_path, monkeypatch):
    calls = responder(monkeypatch)
    cache = tmp_path / "search"
    BraveSearch(cache, "test-key", persist_results=True)("query")
    path = next(cache.glob("brave-*.json"))
    os.utime(path, (time.time() - 90000,) * 2)
    BraveSearch(cache, "test-key", persist_results=True)("query")
    path.write_text("invalid")
    BraveSearch(cache, "test-key", persist_results=True)("query")
    assert len(calls) == 3


def test_queries_are_bounded_and_preserve_entity_names():
    rules = (
        SourceRule("uscourts.gov", ("/*",), "court_document", ("court",)),
        SourceRule("anthropic.com", ("/news/*",), "company_statement", ("Anthropic",)),
    )
    result = queries("Appeals Court Lets Pentagon Designate Anthropic a Supply-Chain Risk", rules)
    assert len(result) == 3
    assert result[0].endswith("site:uscourts.gov")
    assert result[1].endswith("site:anthropic.com")
    assert result[2].endswith("filetype:pdf")


def test_appeals_story_prioritizes_court_records_over_pentagon_aliases():
    from agent.evidence.source_rules import load_rules

    result = queries("Appeals Court Lets the Pentagon Designate Anthropic a Supply-Chain Risk", load_rules(), 2)
    assert result[0].endswith("site:uscourts.gov")


def test_historical_queries_share_budget_but_date_filters_have_distinct_cache_keys(tmp_path, monkeypatch):
    from datetime import date

    calls = responder(monkeypatch)
    search = BraveSearch(tmp_path / "search", "test-key", max_requests=2)
    search.on_day("AI news", date(2026, 9, 27))
    search.on_day("AI news", date(2026, 9, 27))
    search("AI news")
    assert len(calls) == 2
    assert parse_qs(urlsplit(calls[0][0]).query)["freshness"] == ["2026-09-27to2026-09-27"]
    assert "freshness" not in parse_qs(urlsplit(calls[1][0]).query)
    with pytest.raises(SearchStopped, match="per-run"):
        search.on_day("AI news", date(2026, 9, 26))
