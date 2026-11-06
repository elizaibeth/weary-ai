"""Candidate search: feed parsing, date windows, GDELT and historical fallbacks,
the allowlist filter and the weekly paper and story pools (`agent.discovery`)."""

import gzip
import json
from datetime import UTC, date, datetime, timedelta

from agent.research import discovery
from agent.research.discovery import (
    Headline,
    _default_gdelt_fetch,
    _parse_feed,
    fetch_headlines,
    fetch_recent_headlines,
)


def _rss(pub_date: str = "") -> bytes:
    date_tag = f"<pubDate>{pub_date}</pubDate>" if pub_date else ""
    return f"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><title>Real RSS headline one</title><link>https://real.example/one</link>{date_tag}</item>
<item><title>Real RSS headline two</title><link>https://real.example/two</link>{date_tag}</item>
</channel></rss>""".encode()


_ATOM_XML = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Real Atom headline</title><link href="https://real.example/atom"/>
<updated>2026-09-19T10:00:00Z</updated></entry>
</feed>"""


def _rss_single(title: str, url: str, published: datetime) -> bytes:
    pub_date = published.strftime("%a, %d %b %Y %H:%M:%S GMT")
    return f"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><title>{title}</title><link>{url}</link><pubDate>{pub_date}</pubDate></item>
</channel></rss>""".encode()


def _papers_day(*papers):
    return json.dumps(
        [{"paper": {"id": pid, "title": title, "upvotes": votes}} for pid, title, votes in papers]
    ).encode()


def test_parse_feed_handles_rss_2_0_with_pubdate():
    headlines = _parse_feed(_rss("Fri, 19 Sep 2026 10:00:00 GMT"))
    assert headlines[0].title == "Real RSS headline one"
    assert headlines[0].url == "https://real.example/one"
    assert headlines[0].published.date().isoformat() == "2026-09-19"


def test_parse_feed_handles_atom_with_iso_date():
    headlines = _parse_feed(_ATOM_XML)
    assert len(headlines) == 1
    assert headlines[0].title == "Real Atom headline"
    assert headlines[0].url == "https://real.example/atom"
    assert headlines[0].published.date().isoformat() == "2026-09-19"


def test_parse_feed_returns_empty_list_for_unparseable_content():
    assert _parse_feed(b"not xml at all") == []


def test_parse_feed_leaves_published_none_when_no_date_present():
    headlines = _parse_feed(_rss())
    assert headlines[0].published is None


def test_fetch_headlines_filters_to_the_requested_day():
    def fetch(url: str) -> bytes:
        return _rss("Fri, 19 Sep 2026 10:00:00 GMT")

    same_day = fetch_headlines("2026-09-19", feeds=("https://a.example/feed",), fetch=fetch)
    assert len(same_day) == 2

    other_day = fetch_headlines(
        "2026-09-20",
        feeds=("https://a.example/feed",),
        fetch=fetch,
        gdelt_fetch=lambda day: [],  # feeds have nothing for this day either
    )
    assert other_day == []


def test_fetch_headlines_skips_a_feed_that_fails_to_fetch():
    def fetch(url: str) -> bytes:
        if url == "https://down.example/feed":
            raise TimeoutError("unreachable")
        return _rss("Fri, 19 Sep 2026 10:00:00 GMT")

    headlines = fetch_headlines(
        "2026-09-19", feeds=("https://down.example/feed", "https://up.example/feed"), fetch=fetch
    )
    assert len(headlines) == 2


def test_fetch_headlines_falls_back_to_gdelt_when_feeds_have_nothing_for_that_day():
    gdelt_headline = Headline("A GDELT headline", "https://real.example/gdelt-story")

    headlines = fetch_headlines(
        "2020-01-01",  # long before any feed's rolling window
        feeds=("https://a.example/feed",),
        fetch=lambda url: _rss(),  # no pubDate, so nothing matches any day
        gdelt_fetch=lambda day: [gdelt_headline],
    )
    assert headlines == [gdelt_headline]


def test_default_gdelt_fetch_caches_to_disk_by_day(tmp_path, monkeypatch):
    calls = []

    def fake_get(url, timeout=20, retries=3):
        calls.append(url)
        return json.dumps({"articles": [{"title": "A cached headline", "url": "https://real.example/cached"}]}).encode()

    monkeypatch.setattr("agent.research.discovery._http.get", fake_get)

    day = date(2026, 1, 1)
    first = _default_gdelt_fetch(day, cache_dir=tmp_path)
    second = _default_gdelt_fetch(day, cache_dir=tmp_path)

    assert first == second == [Headline("A cached headline", "https://real.example/cached")]
    assert len(calls) == 1  # the second call was served entirely from disk


def test_default_gdelt_fetch_caches_an_empty_result_too(tmp_path, monkeypatch):
    calls = []

    def fake_get(url, timeout=20, retries=3):
        calls.append(url)
        return json.dumps({"articles": []}).encode()

    monkeypatch.setattr("agent.research.discovery._http.get", fake_get)

    day = date(2026, 1, 2)
    assert _default_gdelt_fetch(day, cache_dir=tmp_path) == []
    assert _default_gdelt_fetch(day, cache_dir=tmp_path) == []
    assert len(calls) == 1


def test_fetch_headlines_returns_empty_when_gdelt_also_fails():
    def failing_gdelt(day):
        raise TimeoutError("rate limited")

    headlines = fetch_headlines(
        "2020-01-01",
        feeds=("https://a.example/feed",),
        fetch=lambda url: _rss(),
        gdelt_fetch=failing_gdelt,
    )
    assert headlines == []


def test_fetch_recent_headlines_prefers_the_last_12_hours():
    now = datetime(2026, 9, 27, 18, 0, tzinfo=UTC)

    def fetch(url: str) -> bytes:
        return _rss_single("Recent story", "https://real.example/recent", now - timedelta(hours=6))

    headlines = fetch_recent_headlines(now, feeds=("https://a.example/feed",), fetch=fetch)
    assert [h.title for h in headlines] == ["Recent story"]


def test_fetch_recent_headlines_widens_to_24_hours_when_nothing_in_12(monkeypatch):
    now = datetime(2026, 9, 27, 18, 0, tzinfo=UTC)

    def fetch(url: str) -> bytes:
        # 18 hours old: outside the 12h window, inside the 24h window.
        return _rss_single("Older story", "https://real.example/older", now - timedelta(hours=18))

    headlines = fetch_recent_headlines(now, feeds=("https://a.example/feed",), fetch=fetch)
    assert [h.title for h in headlines] == ["Older story"]


def test_fetch_recent_headlines_falls_back_to_gdelt_when_nothing_within_24_hours():
    now = datetime(2026, 9, 27, 18, 0, tzinfo=UTC)
    gdelt_headline = Headline("A GDELT headline", "https://real.example/gdelt-story")

    def fetch(url: str) -> bytes:
        return _rss_single("Stale story", "https://real.example/stale", now - timedelta(days=3))

    headlines = fetch_recent_headlines(
        now,
        feeds=("https://a.example/feed",),
        fetch=fetch,
        gdelt_fetch=lambda day: [gdelt_headline],
    )
    assert headlines == [gdelt_headline]


def test_fetch_recent_headlines_returns_empty_when_gdelt_also_fails():
    now = datetime(2026, 9, 27, 18, 0, tzinfo=UTC)

    def failing_gdelt(day):
        raise TimeoutError("rate limited")

    headlines = fetch_recent_headlines(
        now,
        feeds=("https://a.example/feed",),
        fetch=lambda url: _rss_single("Stale story", "https://x.example", now - timedelta(days=3)),
        gdelt_fetch=failing_gdelt,
    )
    assert headlines == []


def test_historical_fallback_logs_provider_error_and_uses_one_search(monkeypatch, caplog):
    caplog.set_level("INFO")
    calls = []
    expected = [Headline("AI story", "https://wired.com/story/ai")]

    def gdelt(day):
        raise TimeoutError("rate limited")

    def fallback(day, search):
        calls.append(day)
        return expected

    monkeypatch.setattr(discovery, "search_historical_headlines", fallback)
    found = fetch_headlines("2026-09-27", feeds=(), gdelt_fetch=gdelt, historical_search=lambda q, d: [])
    assert found == expected
    assert calls == [date(2026, 9, 27)]
    assert "GDELT: FAILED (TimeoutError: rate limited)" in caplog.text


def test_historical_search_requires_article_publication_date_not_search_snippet():
    from agent.evidence.retrieval import FetchedDocument
    from agent.evidence.search import SearchHit

    calls = []
    fetched = []
    pages = {
        "https://wired.com/story/good": '<meta property="article:published_time" content="2026-09-27T12:00:00Z"><article><h1>AI lab releases a new model</h1><p>The model was released by an artificial intelligence laboratory.</p></article>',
        "https://wired.com/story/old": '<meta property="article:published_time" content="2026-09-25"><meta property="article:modified_time" content="2026-09-27"><h1>AI older story</h1>',
        "https://wired.com/story/undated": "<h1>AI undated story</h1>",
    }

    def search(query, day):
        calls.append((query, day))
        return [SearchHit(u, "Misleading search title", "Published September 27") for u in pages] + [
            SearchHit("https://evil.example/story")
        ]

    def fetch(url):
        fetched.append(url)
        return FetchedDocument(url, pages[url].encode())

    result = discovery.search_historical_headlines(date(2026, 9, 27), search, fetch)
    assert len(calls) == 1 and len(fetched) == 3
    assert [(h.title, h.url) for h in result] == [("AI lab releases a new model", "https://wired.com/story/good")]


def test_gdelt_error_response_is_not_cached_as_empty(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr("agent.research.discovery._http.get", lambda *args, **kwargs: b'{"error":"rate limited"}')
    with pytest.raises(ValueError, match="Invalid GDELT"):
        _default_gdelt_fetch(date(2026, 9, 27), cache_dir=tmp_path)
    assert not list(tmp_path.glob("*.json"))


def test_empty_gdelt_cache_expires(tmp_path, monkeypatch):
    import os
    import time

    cache = tmp_path / "2026-09-27.json"
    cache.write_text("[]")
    os.utime(cache, (time.time() - 3600,) * 2)
    monkeypatch.setattr(
        "agent.research.discovery._http.get",
        lambda *args, **kwargs: (
            b'{"articles":[{"title":"Newly indexed AI story","url":"https://wired.com/story/new"}]}'
        ),
    )
    assert len(_default_gdelt_fetch(date(2026, 9, 27), cache_dir=tmp_path)) == 1


def test_historical_search_is_not_spent_when_a_free_source_has_candidates():
    def forbidden(*args):
        raise AssertionError("Free candidates must skip paid discovery")

    expected = [Headline("A real headline", "https://wired.com/story/real")]
    assert (
        fetch_headlines("2026-09-27", feeds=(), gdelt_fetch=lambda day: expected, historical_search=forbidden)
        == expected
    )
    assert fetch_headlines(
        "2026-09-19",
        feeds=("feed",),
        fetch=lambda u: _rss("Sat, 19 Sep 2026 10:00:00 GMT"),
        gdelt_fetch=forbidden,
        historical_search=forbidden,
    )


def test_historical_search_budget_failure_does_not_retry_or_fetch_pages(caplog):
    caplog.set_level("INFO")
    from agent.evidence.search import SearchStopped

    calls = []

    def search(query, day):
        calls.append(query)
        raise SearchStopped("search_budget_exhausted")

    def forbidden(url):
        raise AssertionError("There are no results to fetch")

    assert discovery.search_historical_headlines(date(2026, 9, 27), search, forbidden) == []
    assert len(calls) == 1
    assert "search_budget_exhausted" in caplog.text


def test_atom_uses_publication_date_before_modified_date_for_backfills():
    xml = _ATOM_XML.replace(b"<updated>", b"<published>2026-09-27T10:00:00Z</published><updated>")
    assert _parse_feed(xml)[0].published.date() == date(2026, 9, 27)


def test_gzip_encoded_feeds_are_parsed():
    # deepmind.google serves its feed gzip-encoded regardless of Accept-Encoding.

    headlines = _parse_feed(gzip.compress(_rss("Fri, 19 Sep 2026 10:00:00 GMT")))
    assert [h.title for h in headlines] == ["Real RSS headline one", "Real RSS headline two"]


def test_general_company_feeds_keep_only_ai_titles():
    general = next(iter(discovery._GENERAL_FEEDS))
    xml = b"""<?xml version="1.0"?><rss><channel>
<item><title>New Copilot agents for teams</title><link>https://blogs.microsoft.com/blog/a</link></item>
<item><title>Quarterly earnings call schedule</title><link>https://blogs.microsoft.com/blog/b</link></item>
</channel></rss>"""
    headlines = discovery.fetch_all_feed_headlines((general,), lambda url: xml)
    assert [h.title for h in headlines] == ["New Copilot agents for teams"]


def test_the_same_url_from_two_feeds_is_listed_once():
    headlines = discovery.fetch_all_feed_headlines(("https://a.example/1", "https://a.example/2"), lambda url: _rss())
    assert [h.url for h in headlines] == ["https://real.example/one", "https://real.example/two"]


def test_primary_newsroom_articles_pass_the_allowlist():
    from agent.evidence.source_rules import eligible_rule, load_rules

    # One real article link per primary feed (sampled 2026-11-04).
    samples = {
        "https://blog.google/technology/ai/rss/": "https://blog.google/innovation-and-ai/technology/ai/google-ai-updates-october-2026/",
        "https://deepmind.google/blog/rss.xml": "https://deepmind.google/discover/blog/some-post/",
        "https://blogs.microsoft.com/feed/": "https://blogs.microsoft.com/blog/2026/10/28/introducing-the-microsoft-copilot-harness/",
        "https://about.fb.com/news/feed/": "https://about.fb.com/news/2026/10/the-future-is-for-everyone/",
        "https://blogs.nvidia.com/feed/": "https://blogs.nvidia.com/blog/ai-semiconductor-fabs/",
        discovery._ANTHROPIC_NEWS: "https://www.anthropic.com/news/s1-sec",
        "https://research.google/blog/rss/": "https://research.google/blog/the-sleep-framework-a-new-way-for-llms-to-retain-knowledge-in-continual-learning/",
        "https://www.microsoft.com/en-us/research/feed/": "https://www.microsoft.com/en-us/research/blog/from-synthetic-enterprise-data-evaluations-to-real-microsoft-copilot-ai-confidence/",
        "https://machinelearning.apple.com/rss.xml": "https://machinelearning.apple.com/research/mlx-distributed-inference",
        "https://huggingface.co/blog/feed.xml": "https://huggingface.co/blog/cwe-bench",
        "https://allenai.org/rss.xml": "https://allenai.org/blog/olmocr-2-historical-archives",
        "https://www.salesforce.com/blog/category/ai-research/feed/": "https://www.salesforce.com/blog/agentforce-memory-update/",
        "https://metr.org/blog/rss.xml": "https://metr.org/blog/2026-10-22-red-teaming-openai-agent-monitoring/",
        discovery._FEDERAL_REGISTER_AI_FEED: "https://www.federalregister.gov/documents/2026/11/03/2026-22443/streamlining-contested-adjudications-in-licensing-proceedings",
        discovery._WHITE_HOUSE_FEED: "https://www.whitehouse.gov/presidential-actions/2026/11/the-american-declaration-of-freedom-in-space/",
        discovery._NIST_FEED: "https://www.nist.gov/news-events/news/2026/10/nist-report-provides-guidelines-transition-post-quantum-cryptography",
        discovery._UK_GOV_AI_FEED: "https://www.gov.uk/government/news/new-nhs-blood-test-trial-to-help-spot-cancers-earlier",
        "https://aws.amazon.com/blogs/machine-learning/feed/": "https://aws.amazon.com/blogs/machine-learning/bring-structured-and-unstructured-data-together/",
        "https://www.amazon.science/index.rss": "https://www.amazon.science/blog/speeding-up-language-models-for-travel-applications",
        "https://developer.nvidia.com/blog/feed/": "https://developer.nvidia.com/blog/diagnose-distributed-ai-workload-failures/",
        "https://cloudblog.withgoogle.com/products/ai-machine-learning/rss/": "https://cloud.google.com/blog/topics/financial-services/how-nammu21-automates-syndicated-loans",
        "https://bair.berkeley.edu/blog/feed.xml": "http://bair.berkeley.edu/blog/2026/07/29/cuda-to-mlx-k-search/",
        "https://news.mit.edu/rss/topic/artificial-intelligence2": "https://news.mit.edu/2026/building-connections-across-research-infrastructure",
        "https://www.cisa.gov/cybersecurity-advisories/alerts.xml": "https://www.cisa.gov/news-events/alerts/2026/11/03/cisa-adds-one-known-exploited-vulnerability-catalog",
        "https://www.cisa.gov/cybersecurity-advisories/cybersecurity-advisories.xml": "https://www.cisa.gov/news-events/cybersecurity-advisories/aa26-292a",
        "https://www.ncsc.gov.uk/api/1/services/v1/all-rss-feed.xml": "https://www.ncsc.gov.uk/blogs/managing-the-cyber-risk-of-agentic-ai",
        "https://www.php.net/feed.atom": "https://www.php.net/index.php#2026-07-30-4",
        "https://googleprojectzero.blogspot.com/feeds/posts/default": "https://projectzero.google/2026/10/emergency-patching.html",
    }
    rules = load_rules()
    assert set(samples) == set(discovery._PRIMARY_FEEDS) and set(samples) <= set(discovery.FEEDS)
    assert all(eligible_rule(url, rules) for url in samples.values())


def test_official_newsroom_items_get_the_wider_window_while_reporting_stays_fresh():
    now = datetime(2026, 9, 25, 18, 0, tzinfo=UTC)
    old = (now - timedelta(hours=20)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    fresh = (now - timedelta(hours=2)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    feeds = {
        "https://reporting.example/feed": f"""<rss><channel>
<item><title>Fresh report</title><link>https://techcrunch.com/fresh</link><pubDate>{fresh}</pubDate></item>
<item><title>Older report</title><link>https://techcrunch.com/older</link><pubDate>{old}</pubDate></item>
</channel></rss>""",
        "https://official.example/feed": f"""<rss><channel>
<item><title>Older official post</title><link>https://openai.com/index/older</link><pubDate>{old}</pubDate></item>
</channel></rss>""",
    }
    headlines = fetch_recent_headlines(now, feeds=tuple(feeds), fetch=lambda url: feeds[url].encode())
    assert [h.title for h in headlines] == ["Fresh report", "Older official post"]


def test_double_escaped_feed_titles_are_unescaped():
    # The Verge's feed yielded "hasn&#8217;t", which broke search queries.
    xml = b"""<rss><channel><item><title>Google hasn&amp;#8217;t figured it out</title>
<link>https://www.theverge.com/x</link></item></channel></rss>"""
    assert _parse_feed(xml)[0].title == "Google hasn’t figured it out"


def test_weekly_papers_keep_the_most_upvoted_distinct_arxiv_papers(monkeypatch):
    monkeypatch.setattr(discovery, "PAPER_POOL_SIZE", 2)
    days = {
        "2026-11-01": _papers_day(("2611.00001", "Small result", 3)),
        "2026-10-31": _papers_day(("2611.00002", "Big result", 90), ("not-an-id", "Bad id", 999)),
        "2026-10-30": _papers_day(("2611.00001", "Small result", 40)),  # same paper, more votes
    }

    def fetch(url):
        day = url.split("date=")[1].split("&")[0]
        if day not in days:
            raise TimeoutError("no data")
        return days[day]

    papers = discovery.fetch_weekly_papers(date(2026, 11, 1), fetch)
    assert [(h.title, h.url) for h in papers] == [
        ("Big result", "https://arxiv.org/abs/2611.00002"),
        ("Small result", "https://arxiv.org/abs/2611.00001"),
    ]


_ANTHROPIC_PAGE = b"""<html><body>
<div><a href="/news/announcements">Announcements</a><span>Oct 26, 2026</span>
  <a href="/news/s1-sec"><h3>Anthropic files S-1 with the SEC for proposed initial public offering</h3><p>Today...</p></a></div>
<div><span>Oct 22, 2026</span><a href="/news/agent-skills"><h3>Donating Agent Skills to the Agentic AI Foundation</h3></a></div>
<a href="/news/features">Features</a>
</body></html>"""


def test_anthropic_news_page_yields_dated_articles_not_category_links():
    headlines = discovery._parse_anthropic_news(_ANTHROPIC_PAGE)
    assert [(h.title, h.url, h.published.isoformat()) for h in headlines] == [
        (
            "Anthropic files S-1 with the SEC for proposed initial public offering",
            "https://www.anthropic.com/news/s1-sec",
            "2026-10-26T23:59:59+00:00",
        ),
        (
            "Donating Agent Skills to the Agentic AI Foundation",
            "https://www.anthropic.com/news/agent-skills",
            "2026-10-22T23:59:59+00:00",
        ),
    ]


def test_official_feeds_keep_only_allowlisted_items():
    # Hugging Face's feed mixes its own posts with community posts by any user.
    xml = b"""<rss><channel>
<item><title>Official post about a model release</title><link>https://huggingface.co/blog/cwe-bench</link></item>
<item><title>Community post about a model release</title><link>https://huggingface.co/blog/someone/post</link></item>
</channel></rss>"""
    feed = "https://huggingface.co/blog/feed.xml"
    assert feed in discovery._PRIMARY_FEEDS
    headlines = discovery.fetch_all_feed_headlines((feed,), lambda url: xml)
    assert [h.url for h in headlines] == ["https://huggingface.co/blog/cwe-bench"]


def test_the_anthropic_page_is_read_by_its_page_reader():
    headlines = discovery.fetch_all_feed_headlines((discovery._ANTHROPIC_NEWS,), lambda url: _ANTHROPIC_PAGE)
    assert len(headlines) == 2


def test_exclude_paths_reject_nested_paths_the_pattern_would_otherwise_match():
    from agent.evidence.source_rules import SourceRule

    rule = SourceRule("huggingface.co", ("/blog/*",), "company_statement", (), ("/blog/*/*",))
    assert rule.matches("https://huggingface.co/blog/release")
    assert not rule.matches("https://huggingface.co/blog/user/post")


def test_source_check_distinguishes_failures_leads_and_quiet_feeds(monkeypatch):
    from agent import source_check

    def fetch(url):
        if "whitehouse" in url:
            return b"<rss><channel><item><title>Anti-communism week</title><link>https://www.whitehouse.gov/briefings-statements/x/</link></item></channel></rss>"
        if "techcrunch" in url:
            return _rss()
        raise TimeoutError("blocked")

    monkeypatch.setattr(discovery, "default_fetch", fetch)
    fetcher = lambda url: (_ for _ in ()).throw(AssertionError("no article fetch expected"))  # noqa: E731
    assert source_check.check(discovery._WHITE_HOUSE_FEED, fetcher)[0] == "NONE"
    assert source_check.check(discovery._REPORTING_FEEDS[0], fetcher)[0] == "LEAD"
    assert source_check.check("https://metr.org/blog/rss.xml", fetcher)[0] == "FAIL"


def test_bbc_is_an_ai_filtered_reporting_lead():
    from agent.evidence.packet import is_reporting_url

    feed = discovery._BBC_TECH_FEED
    assert feed in discovery._REPORTING_FEEDS and feed in discovery._GENERAL_FEEDS
    assert feed not in discovery._PRIMARY_FEEDS
    assert is_reporting_url("https://www.bbc.co.uk/news/articles/abc")
    assert "feeds.bbci.co.uk" not in discovery._HISTORICAL_SEARCH_DOMAINS


def test_security_outlets_are_unfiltered_leads_and_advisories_are_primary():
    from agent.evidence.packet import is_reporting_url
    from agent.evidence.source_rules import eligible_rule, load_rules

    register = "https://www.theregister.com/security/headlines.atom"
    assert register in discovery._REPORTING_FEEDS and register not in discovery._GENERAL_FEEDS
    for url in (
        "https://www.theregister.com/security/2026/10/27/php2shell/",
        "https://krebsonsecurity.com/2026/10/php/",
    ):
        assert is_reporting_url(url)
    rules = load_rules()
    assert eligible_rule("https://www.cisa.gov/news-events/alerts/2026/10/27/cisa-adds-two-kev", rules)
    assert eligible_rule("https://www.ncsc.gov.uk/news/critical-security-issue-affecting-php", rules)
    assert not eligible_rule("https://www.php.net/conferences/index.php#2026-09-02-1", rules)
    assert not eligible_rule("https://www.cisa.gov/news-events/ics-advisories/icsa-26-307-01", rules)


def test_each_headline_remembers_which_feed_it_came_from():
    headlines = discovery.fetch_all_feed_headlines(("https://a.example/feed",), lambda url: _rss())
    assert {h.feed for h in headlines} == {"https://a.example/feed"}
