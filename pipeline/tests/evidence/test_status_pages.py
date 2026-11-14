"""Status pages as evidence for outage stories (`agent.evidence.status_pages`
and its use in `packet.gather`).

The fixtures are the real feeds from the Microsoft 365 outage of 12-13
November 2026, trimmed to a few entries: the edition the pipeline missed.
"""

from pathlib import Path

import pytest

from agent.evidence import status_pages
from agent.evidence.packet import ai_passage_ids, gather
from agent.evidence.status_pages import StatusEntry, outage_providers, parse_feed, relevant_entries
from agent.research.candidate import Candidate

FIXTURES = Path(__file__).parent / "fixtures" / "status"
CONFIG = status_pages.load_config()
DAY = "2026-11-13"
MICROSOFT_HEADLINE = "Microsoft 365 Crawls Back to Life After a 24-Hour Outage"
FEEDS = {
    "https://status.cloud.microsoft/api/posts/m365Consumer": "m365.json",
    "https://status.openai.com/history.rss": "openai.rss",
    "https://status.claude.com/history.rss": "claude.rss",
}
EMPTY_RSS = '<?xml version="1.0"?><rss version="2.0"><channel><title>Status</title></channel></rss>'


def provider(name):
    return next(p for p in CONFIG.providers if p.name == name)


def feed_fetcher(served: dict[str, str], fetched: list[str] | None = None):
    """Serve fixture feeds; every other status feed is empty, anything else 404s."""

    def fetch(url):
        if fetched is not None:
            fetched.append(url)
        if url in served:
            return (FIXTURES / served[url]).read_text()
        if any(url in p.feeds for p in CONFIG.providers):
            return EMPTY_RSS
        raise ValueError(f"unexpected fetch {url}")

    return fetch


def outage(headline=MICROSOFT_HEADLINE, url="https://www.wired.com/story/outage/", summary=""):
    return Candidate("id", headline, (url,), 0.8, summary)


@pytest.mark.parametrize(
    ("headline", "expected"),
    [
        (MICROSOFT_HEADLINE, ["Microsoft"]),
        ("Microsoft Struggles to Restore Email and Other Services in a Global Outage", ["Microsoft"]),
        ("AWS outage takes Bedrock offline for hours", ["Amazon Web Services"]),
        ("ChatGPT is down for millions of users", ["OpenAI"]),
        ("Cloudflare disruption knocks websites offline", ["Cloudflare"]),
        # Not outages, so no status page is read.
        ("Jensen Huang steps down as Nvidia CEO", []),
        ("Microsoft shuts down its Skype service for good", []),
        ("Microsoft releases a new Copilot model", []),
        # An outage of a service with no status feed on the list.
        ("Regional bank suffers an outage", []),
    ],
)
def test_outage_providers_from_headline(headline, expected):
    assert [p.name for p in outage_providers(headline, CONFIG)] == expected


def test_github_copilot_does_not_count_as_a_microsoft_alias():
    entry = StatusEntry("Copilot experiencing degraded model availability for some GPT models", "", DAY)
    assert relevant_entries([entry], provider("GitHub"), [provider("Microsoft")], DAY) == []


def test_parses_microsoft_json_and_keeps_only_services_with_an_incident():
    entries = parse_feed((FIXTURES / "m365.json").read_bytes())
    assert len(entries) == 1
    assert entries[0].title.startswith("Microsoft 365 (Consumer): Users may be unable to access")
    assert "Start time: Thursday, November 12, 2026, at 10:05 AM UTC" in entries[0].text
    assert entries[0].published == "2026-11-14"


def test_parses_statuspage_rss_as_plain_text_with_utc_days():
    entries = parse_feed((FIXTURES / "claude.rss").read_bytes())
    assert [e.title for e in entries][0] == "Elevated errors affecting the Microsoft 365 connector"
    assert entries[0].published == DAY
    assert "<" not in entries[0].text and "16:03 UTC on November 12" in entries[0].text


def test_parses_atom_with_the_entry_page_not_the_feed_link():
    atom = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>GCP</title>
    <entry><title>Vertex AI errors</title><updated>2026-11-13T10:00:00+00:00</updated>
    <link href="https://status.cloud.google.com/en/feed.atom" rel="self"/>
    <link href="https://status.cloud.google.com/incidents/abc" rel="alternate" type="text/html"/>
    <content type="html">&lt;p&gt;Gemini API requests failed.&lt;/p&gt;</content></entry></feed>"""
    assert parse_feed(atom) == [
        StatusEntry(
            "Vertex AI errors", "Gemini API requests failed.", DAY, "https://status.cloud.google.com/incidents/abc"
        )
    ]


@pytest.mark.parametrize("body", [b"<html><body>Status</body></html>", b"not a feed", b'{"a": 1}'])
def test_rejects_anything_that_is_not_a_status_feed(body):
    with pytest.raises(ValueError):
        parse_feed(body)


def test_entries_outside_the_outage_window_are_dropped():
    old = StatusEntry("Microsoft 365 outage", "", "2026-11-01")
    late = StatusEntry("Microsoft 365 outage", "", "2026-11-20")
    recent = StatusEntry("Microsoft 365 outage", "", "2026-11-12")
    microsoft = provider("Microsoft")
    assert relevant_entries([old, late, recent], microsoft, [microsoft], DAY) == [recent]


def test_an_ai_company_incident_counts_only_when_it_names_the_affected_provider():
    named = StatusEntry("Elevated errors affecting the Microsoft 365 connector", "", DAY)
    same_hours = StatusEntry("Elevated errors on claude.ai", "", DAY)
    assert relevant_entries([named, same_hours], provider("Anthropic"), [provider("Microsoft")], DAY) == [named]


def test_ai_passages_come_from_ai_status_pages_or_name_ai():
    assert status_pages.is_ai_passage("https://status.claude.com/history.rss", "Elevated errors", CONFIG)
    assert status_pages.is_ai_passage("https://status.cloud.microsoft/api/posts/x", "Copilot is unavailable", CONFIG)
    assert not status_pages.is_ai_passage("https://status.cloud.microsoft/api/posts/x", "Email is delayed", CONFIG)
    # "AI" must be a whole word: "mail" and "said" do not count.
    assert not status_pages.is_ai_passage("https://www.cloudflarestatus.com/history.rss", "Mail said it failed", CONFIG)


# The edition the pipeline missed: with status pages, it has a primary source
# for what broke (Microsoft) and for the AI effect (OpenAI and Anthropic).
def test_13_november_outage_gets_microsoft_and_ai_company_status_evidence(tmp_path):
    fetched: list[str] = []
    # The second look's angle names OpenAI and Anthropic; that must not make
    # their unrelated incidents count as evidence.
    summary = "OpenAI and Anthropic said a Microsoft 365 outage was disrupting their connectors."
    packet = gather(
        outage(summary=summary), feed_fetcher(FEEDS, fetched), cache_dir=tmp_path, as_of_day=DAY, status=CONFIG
    )

    assert packet.outcome == "ready"
    assert all(s.provenance == "status_page" for s in packet.sources)
    # Each source is the page a reader can open: the entry's incident page
    # (OpenAI's doubled slash collapsed), or Microsoft's status page for its
    # JSON entries, which link nowhere.
    by_host = {s.url.split("/")[2]: s for s in packet.sources}
    assert set(by_host) == {"status.cloud.microsoft", "status.openai.com", "status.claude.com"}
    assert by_host["status.cloud.microsoft"].url == "https://status.cloud.microsoft/m365consumer"
    assert by_host["status.openai.com"].url == "https://status.openai.com/incidents/01M78GAT3AK9P9W8Z230KHFVE8"
    assert by_host["status.claude.com"].url.startswith("https://status.claude.com/incidents/")
    assert by_host["status.openai.com"].title == "OpenAI status: Elevated errors affecting the Microsoft 365 connector"
    assert "Microsoft 365 services" in by_host["status.cloud.microsoft"].text
    for host in ("status.openai.com", "status.claude.com"):
        texts = [p.text for p in by_host[host].passages]
        assert texts and all("Microsoft 365 connector" in t for t in texts)
    # Each passage says who posted it: Anthropic's entries say "Claude", never "Anthropic".
    assert by_host["status.claude.com"].passages[0].text.startswith("Anthropic status page: Elevated errors")
    assert by_host["status.cloud.microsoft"].passages[0].text.startswith("Microsoft status page: ")
    # Unrelated incidents on the AI pages that day are not evidence.
    assert "Sites: Publishing failing" not in by_host["status.openai.com"].text
    assert "Claude Code" not in by_host["status.claude.com"].text
    # The AI passages are the OpenAI and Anthropic entries, not Microsoft's.
    ai_ids = ai_passage_ids(packet.sources, CONFIG)
    microsoft_ids = {p.id for p in by_host["status.cloud.microsoft"].passages}
    assert ai_ids and not ai_ids & microsoft_ids
    # Each status feed is read once, before the article.
    assert fetched.index("https://www.wired.com/story/outage/") > fetched.index("https://status.claude.com/history.rss")


def test_an_outage_with_no_ai_effect_is_dropped(tmp_path):
    # Cloudflare's own page reports the outage; no AI company's page names it.
    cloudflare = """<?xml version="1.0"?><rss version="2.0"><channel><title>Cloudflare Status</title>
      <item><title>Cloudflare network outage</title><description>Websites returned 500 errors.</description>
      <pubDate>Fri, 13 Nov 2026 12:00:00 +0000</pubDate></item></channel></rss>"""

    def fetch(url):
        if url == "https://www.cloudflarestatus.com/history.rss":
            return cloudflare
        return feed_fetcher({})(url)

    packet = gather(
        outage("Cloudflare outage knocks websites offline", "https://www.theverge.com/cloudflare"),
        fetch,
        cache_dir=tmp_path,
        as_of_day=DAY,
        status=CONFIG,
    )
    assert packet.outcome == "no_ai_source"
    assert not packet.sources
    assert any(d.startswith("no_ai_source") for d in packet.diagnostics)


def test_stories_that_are_not_outages_never_read_status_pages(tmp_path):
    fetched: list[str] = []
    gather(
        outage("Microsoft releases a new Copilot model", "https://www.wired.com/story/copilot/"),
        feed_fetcher({}, fetched),
        cache_dir=tmp_path,
        status=CONFIG,
    )
    assert not any("status" in u for u in fetched)


def test_a_status_feed_that_fails_is_skipped_and_the_rest_still_count(tmp_path):
    served = dict(FEEDS)
    del served["https://status.claude.com/history.rss"]

    def fetch(url):
        if url == "https://status.claude.com/history.rss":
            raise TimeoutError("timed out")
        return feed_fetcher(served)(url)

    packet = gather(outage(), fetch, cache_dir=tmp_path, as_of_day=DAY, status=CONFIG)
    assert packet.outcome == "ready"
    assert "status.openai.com" in {s.url.split("/")[2] for s in packet.sources}
    assert any(d.startswith("status_failed: https://status.claude.com") for d in packet.diagnostics)


def test_a_status_host_that_refuses_access_is_blocked_for_the_rest_of_the_run(tmp_path):
    from urllib.error import HTTPError

    def fetch(url):
        if url == "https://status.openai.com/history.rss":
            raise HTTPError(url, 403, "Forbidden", {}, None)
        return feed_fetcher(FEEDS)(url)

    blocked: set[str] = set()
    packet = gather(outage(), fetch, cache_dir=tmp_path, as_of_day=DAY, status=CONFIG, blocked_hosts=blocked)
    assert "status.openai.com" in blocked
    assert packet.outcome == "ready"  # Anthropic's entry still shows the AI effect
    again = gather(outage(), fetch, cache_dir=tmp_path, as_of_day=DAY, status=CONFIG, blocked_hosts=blocked)
    assert any(d.startswith("status_skipped: host already denied access") for d in again.diagnostics)


def test_a_status_feed_without_an_allowlist_rule_is_never_fetched(tmp_path):
    from agent.evidence.source_rules import SourceRule

    fetched: list[str] = []
    rules = (SourceRule("status.claude.com", ("/history.rss",), "status_page"),)
    packet = gather(
        outage(), feed_fetcher(FEEDS, fetched), rules=rules, cache_dir=tmp_path, as_of_day=DAY, status=CONFIG
    )
    assert "https://status.openai.com/history.rss" not in fetched
    assert any(
        d == "status_skipped: no status_page rule allows https://status.openai.com/history.rss"
        for d in packet.diagnostics
    )
    # Its incident pages have no rule either, so the feed itself is cited.
    assert [s.url for s in packet.sources] == ["https://status.claude.com/history.rss"]


def test_a_status_feed_redirected_off_the_allowlist_is_rejected(tmp_path):
    from agent.evidence.retrieval import FetchedDocument

    def fetch(url):
        if url == "https://status.claude.com/history.rss":
            return FetchedDocument("https://elsewhere.example/feed", (FIXTURES / "claude.rss").read_bytes())
        return feed_fetcher(FEEDS)(url)

    packet = gather(outage(), fetch, cache_dir=tmp_path, as_of_day=DAY, status=CONFIG)
    assert "status.claude.com" not in {s.url.split("/")[2] for s in packet.sources}
    assert any(d.startswith("status_rejected: redirected") for d in packet.diagnostics)


def test_read_article_reads_reporting_pages_and_refuses_unknown_origins(tmp_path, monkeypatch):
    from agent.evidence import packet as packet_module
    from agent.evidence.retrieval import DocumentFetcher, FetchedDocument

    def fake_call(self, url):
        if not self.allowed(url):
            raise ValueError("source_rejected: origin/path is not eligible")
        return FetchedDocument(url, b"<article><p>Copilot was down for hours.</p></article>")

    monkeypatch.setattr(DocumentFetcher, "__call__", fake_call)
    assert (
        packet_module.read_article("https://www.wired.com/story/x/", cache_dir=tmp_path)
        == "Copilot was down for hours."
    )
    with pytest.raises(ValueError):
        packet_module.read_article("https://unknown.example/story", cache_dir=tmp_path)
