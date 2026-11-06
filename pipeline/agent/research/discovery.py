"""Candidate search: find real headlines. No model is called here.

Discovery starts free: headlines come straight from AI-focused RSS/Atom feeds
and official newsrooms (no API key, no per-call cost). Only items on the
primary-source allowlist are kept from official feeds, so their own page can
serve as evidence later.

The feeds carry only a rolling window of recent items (roughly the last one
to two weeks). If nothing on a requested day survives the date filter,
GDELT's free DOC 2.0 API (a real historical search, though limited to about
three months and heavily rate limited) is tried next. GDELT responses are
cached in `.weary/gdelt_cache/` for 24h (15m when empty), since indexing can
lag. Historical backfills may then use one budgeted Brave query; publisher
pages must confirm the target date.

`ranking` orders what this module finds; `editions` runs the two in turn.
"""

import gzip
import html
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from agent.evidence.retrieval import DocumentFetcher, FetchedDocument, extract
from agent.evidence.search import SearchHit
from agent.evidence.source_rules import canonical_url, eligible_rule, load_rules
from agent.services import _http

log = logging.getLogger(__name__)

Fetch = Callable[[str], bytes]
HistoricalSearch = Callable[[str, date], list[SearchHit]]

# Reporting feeds supply leads only. BBC Technology is a general feed, so
# only AI titles are kept (see _GENERAL_FEEDS).
_BBC_TECH_FEED = "https://feeds.bbci.co.uk/news/technology/rss.xml"
_REPORTING_FEEDS = (
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://www.technologyreview.com/topic/artificial-intelligence/feed",
    "https://www.wired.com/feed/tag/ai/latest/rss",
    _BBC_TECH_FEED,
    # Security outlets, unfiltered: a major incident can lead the day even
    # without an AI angle (PHP2Shell, Oct 2026, was missed entirely).
    "https://www.theregister.com/security/headlines.atom",
    "https://krebsonsecurity.com/feed/",
    "https://www.bleepingcomputer.com/feed/",
    "https://www.darkreading.com/rss.xml",
    "https://www.securityweek.com/feed/",
    "https://therecord.media/feed",
)
# Article domains for the one-query historical Brave fallback (feed hosts
# such as feeds.bbci.co.uk are not where the articles live).
_HISTORICAL_SEARCH_DOMAINS = ("techcrunch.com", "theverge.com", "technologyreview.com", "wired.com")
# Official newsrooms on the primary-source allowlist (source_rules.toml).
# Their own articles pass the evidence gate without a search; reporting
# candidates mostly failed it (no_primary_source). Anthropic has no feed.
# OpenAI's feed was removed: openai.com returns 403 to GitHub Actions, and
# its feed carries only one-sentence summaries, so its posts never verified.
_ANTHROPIC_NEWS = "https://www.anthropic.com/news"  # no feed; read by _parse_anthropic_news
_FEDERAL_REGISTER_AI_FEED = (
    "https://www.federalregister.gov/api/v1/documents.rss?conditions%5Bterm%5D=%22artificial+intelligence%22"
    "&conditions%5Btype%5D%5B%5D=RULE&conditions%5Btype%5D%5B%5D=PRORULE&conditions%5Btype%5D%5B%5D=PRESDOCU"
    "&order=newest"
)
_WHITE_HOUSE_FEED = "https://www.whitehouse.gov/news/feed/"
_NIST_FEED = "https://www.nist.gov/news-events/news/rss.xml"
_UK_GOV_AI_FEED = "https://www.gov.uk/search/news-and-communications.atom?keywords=artificial+intelligence"
_PRIMARY_FEEDS = (
    # AI labs and companies
    _ANTHROPIC_NEWS,
    "https://blog.google/technology/ai/rss/",
    "https://deepmind.google/blog/rss.xml",
    "https://research.google/blog/rss/",
    "https://blogs.microsoft.com/feed/",
    "https://www.microsoft.com/en-us/research/feed/",
    "https://about.fb.com/news/feed/",
    "https://blogs.nvidia.com/feed/",
    "https://machinelearning.apple.com/rss.xml",
    "https://huggingface.co/blog/feed.xml",
    "https://allenai.org/rss.xml",
    "https://www.salesforce.com/blog/category/ai-research/feed/",
    "https://metr.org/blog/rss.xml",
    "https://aws.amazon.com/blogs/machine-learning/feed/",
    "https://www.amazon.science/index.rss",
    "https://developer.nvidia.com/blog/feed/",
    "https://cloudblog.withgoogle.com/products/ai-machine-learning/rss/",
    "https://bair.berkeley.edu/blog/feed.xml",
    "https://news.mit.edu/rss/topic/artificial-intelligence2",
    # Government: US rules, proposed rules and presidential documents that
    # mention AI (meeting notices excluded), plus AI-titled items below.
    _FEDERAL_REGISTER_AI_FEED,
    _WHITE_HOUSE_FEED,
    _NIST_FEED,
    _UK_GOV_AI_FEED,
    # Security advisories: CISA alerts (including Known Exploited
    # Vulnerabilities additions) and joint advisories, the UK NCSC, the PHP
    # project, and Google Project Zero. CISA's industrial-control advisories
    # are left out as routine.
    "https://www.cisa.gov/cybersecurity-advisories/alerts.xml",
    "https://www.cisa.gov/cybersecurity-advisories/cybersecurity-advisories.xml",
    "https://www.ncsc.gov.uk/api/1/services/v1/all-rss-feed.xml",
    "https://www.php.net/feed.atom",
    "https://googleprojectzero.blogspot.com/feeds/posts/default",
)
# Feeds that also carry non-AI posts: keep AI titles only. (The gov.uk search
# matches any page mentioning AI, so most of its titles are unrelated.)
_GENERAL_FEEDS = frozenset(
    {
        "https://blogs.microsoft.com/feed/",
        "https://about.fb.com/news/feed/",
        _WHITE_HOUSE_FEED,
        _NIST_FEED,
        _UK_GOV_AI_FEED,
        _BBC_TECH_FEED,
    }
)
FEEDS = _REPORTING_FEEDS + _PRIMARY_FEEDS
_AI_TOPIC_RE = re.compile(
    r"\b(AI|artificial intelligence|machine learning|agents?|agentic|models?|OpenAI|Anthropic|ChatGPT|Claude|"
    r"Gemini|Copilot|Llama|GPT|LLMs?|chatbots?|superintelligence)\b",
    re.I,
)
_MAX_ITEMS_PER_FEED = 30
_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
# Community-upvoted AI papers; free, no key. Each item links to arXiv.
_HF_DAILY_PAPERS_URL = "https://huggingface.co/api/daily_papers"
PAPER_POOL_SIZE = 15
_ARXIV_ID_RE = re.compile(r"\d{4}\.\d{4,5}")


@dataclass(frozen=True)
class Headline:
    title: str
    url: str
    published: datetime | None = None
    feed: str = ""  # the feed or page it came from, for the run log


def _parse_date(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _parse_feed(xml_bytes: bytes) -> list[Headline]:
    try:
        if xml_bytes[:2] == b"\x1f\x8b":  # some feeds (DeepMind) are always gzip-encoded
            xml_bytes = gzip.decompress(xml_bytes)
        root = ElementTree.fromstring(xml_bytes)
    except (ElementTree.ParseError, OSError, EOFError):
        return []

    headlines = []
    for item in root.findall(".//item")[:_MAX_ITEMS_PER_FEED]:
        title_el = item.find("title")
        link_el = item.find("link")
        date_el = item.find("pubDate")
        if title_el is not None and link_el is not None and title_el.text and link_el.text:
            headlines.append(
                Headline(
                    # Some feeds double-escape entities (The Verge: "hasn&#8217;t").
                    title=html.unescape(title_el.text.strip()),
                    url=link_el.text.strip(),
                    published=_parse_date(date_el.text if date_el is not None else None),
                )
            )
    if headlines:
        return headlines

    for entry in root.findall(f".//{_ATOM_NS}entry")[:_MAX_ITEMS_PER_FEED]:
        title_el = entry.find(f"{_ATOM_NS}title")
        link_el = entry.find(f"{_ATOM_NS}link")
        date_el = entry.find(f"{_ATOM_NS}published")
        if date_el is None:
            date_el = entry.find(f"{_ATOM_NS}updated")
        url = link_el.get("href") if link_el is not None else None
        if title_el is not None and title_el.text and url:
            headlines.append(
                Headline(
                    title=html.unescape(title_el.text.strip()),
                    url=url.strip(),
                    published=_parse_date(date_el.text if date_el is not None else None),
                )
            )
    return headlines


_CARD_DATE_RE = re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2}, \d{4}\b")


def _parse_anthropic_news(html_bytes: bytes) -> list[Headline]:
    """Article cards from anthropic.com/news, which publishes no feed.

    Category links (/news/announcements) have short labels; article links
    carry the title as their first text. The card's date sits next to the
    link, so the nearest enclosing element with a date supplies it. Dates
    have no time, so they are set to the end of that UTC day; the article
    page's own date is still checked during evidence collection.
    """
    soup = BeautifulSoup(html_bytes, "html.parser")
    headlines: dict[str, Headline] = {}
    for link in soup.find_all("a", href=re.compile(r"^/news/[a-z0-9-]+$")):
        texts = list(link.stripped_strings)
        url = "https://www.anthropic.com" + str(link["href"])
        if not texts or len(texts[0]) < 20 or url in headlines:
            continue
        published = None
        for node in [link, *list(link.parents)[:3]]:
            match = _CARD_DATE_RE.search(" ".join(node.stripped_strings))
            if match:
                day = datetime.strptime(match.group(0).replace(",", ""), "%b %d %Y")
                published = day.replace(hour=23, minute=59, second=59, tzinfo=UTC)
                break
        headlines[url] = Headline(html.unescape(texts[0]), url, published)
    return list(headlines.values())[:_MAX_ITEMS_PER_FEED]


_PAGE_READERS: dict[str, Callable[[bytes], list[Headline]]] = {_ANTHROPIC_NEWS: _parse_anthropic_news}


def default_fetch(url: str) -> bytes:
    return _http.get(url, headers={"User-Agent": "weary-news/0.1"}, timeout=20)


def fetch_all_feed_headlines(feeds: tuple[str, ...], fetch: Fetch) -> list[Headline]:
    headlines: dict[str, Headline] = {}
    rules = load_rules()
    for url in feeds:
        try:
            feed_headlines = _PAGE_READERS.get(url, _parse_feed)(fetch(url))
            if url in _PRIMARY_FEEDS:
                # Only items the allowlist accepts can pass the evidence gate
                # (e.g. Hugging Face community posts are excluded there).
                feed_headlines = [h for h in feed_headlines if eligible_rule(h.url, rules)]
            if url in _GENERAL_FEEDS:
                total = len(feed_headlines)
                feed_headlines = [h for h in feed_headlines if _AI_TOPIC_RE.search(h.title)]
                log.info("feed %s: %s AI item(s) of %s", url, len(feed_headlines), total)
            else:
                log.info("feed %s: %s item(s)", url, len(feed_headlines))
            for h in feed_headlines:
                headlines.setdefault(h.url, replace(h, feed=url))
        except Exception as e:
            log.warning("feed %s: FAILED (%s: %s)", url, type(e).__name__, e)
            continue
    return list(headlines.values())


def _feed_headlines_for_day(day: date, feeds: tuple[str, ...], fetch: Fetch) -> list[Headline]:
    headlines = fetch_all_feed_headlines(feeds, fetch)
    return [h for h in headlines if h.published is not None and h.published.date() == day]


# A bare relative path here would resolve against the process's current
# working directory, not this package's location - fine as long as
# everything is always run from the Hugo project root, but that stopped
# being guaranteed once the pipeline moved into its own subdirectory.
# Anchoring on __file__ keeps this pointed at the same place (the Hugo
# project's own `.weary/`, alongside `daily.py`'s image cache) regardless
# of cwd.
_GDELT_CACHE_DIR = Path(__file__).resolve().parents[3] / ".weary" / "gdelt_cache"


def _gdelt_cache_path(day: date, cache_dir: Path) -> Path:
    return cache_dir / f"{day.isoformat()}.json"


def _default_gdelt_fetch(day: date, cache_dir: Path = _GDELT_CACHE_DIR) -> list[Headline]:
    """Cache results for 24h, empty results for 15m as indexing can lag."""
    cache_path = _gdelt_cache_path(day, cache_dir)
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text())
            if not isinstance(cached, list):
                raise ValueError("Invalid GDELT cache")
            headlines = [Headline(title=h["title"], url=h["url"]) for h in cached]
            if time.time() - cache_path.stat().st_mtime < (86400 if headlines else 900):
                log.info("GDELT cache hit: %s item(s)", len(headlines))
                return headlines
        except (ValueError, TypeError, KeyError, OSError):
            pass

    start = day.strftime("%Y%m%d000000")
    end = (day + timedelta(days=1)).strftime("%Y%m%d000000")
    query = (
        f"{_GDELT_URL}?query=artificial%20intelligence&mode=artlist&format=json"
        f"&maxrecords=40&startdatetime={start}&enddatetime={end}"
    )
    body = json.loads(_http.get(query, timeout=30, retries=1))
    if not isinstance(body, dict) or "error" in body or not isinstance(body.get("articles"), list):
        raise ValueError("Invalid GDELT article response")
    headlines = []
    for article in body.get("articles", []):
        if not isinstance(article, dict):
            continue
        title, url = article.get("title"), article.get("url")
        if isinstance(title, str) and isinstance(url, str) and title.strip() and url.strip():
            headlines.append(Headline(title=title.strip(), url=url.strip(), published=None))

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps([{"title": h.title, "url": h.url} for h in headlines]))
    return headlines


def fetch_headlines(
    day: str,
    feeds: tuple[str, ...] = FEEDS,
    fetch: Fetch = default_fetch,
    gdelt_fetch: Callable[[date], list[Headline]] = _default_gdelt_fetch,
    *,
    historical_search: HistoricalSearch | None = None,
) -> list[Headline]:
    target_day = datetime.strptime(day, "%Y-%m-%d").date()
    headlines = _feed_headlines_for_day(target_day, feeds, fetch)
    log.info("RSS: %s item(s) dated %s", len(headlines), day)
    if headlines:
        return headlines
    try:
        log.info("no same-day RSS items, falling back to GDELT...")
        headlines = gdelt_fetch(target_day)
        log.info("GDELT: %s item(s)", len(headlines))
        if headlines:
            return headlines
    except Exception as error:
        log.warning("GDELT: FAILED (%s: %s)", type(error).__name__, error)
    if historical_search is not None:
        return search_historical_headlines(target_day, historical_search)
    log.info("historical search unavailable; no dated candidates found")
    return []


def search_historical_headlines(
    day: date,
    search: HistoricalSearch,
    fetch: Callable[[str], FetchedDocument] | None = None,
) -> list[Headline]:
    """One bounded search; validate publication dates and titles on publisher pages.

    Brave's date filter can match modification dates. Its snippets and dates
    therefore never establish a candidate's actual publication date.
    """
    domains = _HISTORICAL_SEARCH_DOMAINS

    def allowed(url: str) -> bool:
        try:
            host = urlsplit(canonical_url(url)).hostname or ""
            return any(host == d or host.endswith("." + d) for d in domains)
        except ValueError:
            return False

    fetch = fetch or DocumentFetcher(_GDELT_CACHE_DIR.parent / "evidence" / "documents", allowed)
    query = '"artificial intelligence" (' + " OR ".join("site:" + d for d in domains) + ")"
    log.info("historical Brave discovery: one query for %s", day)
    try:
        hits = search(query, day)
    except Exception as error:
        log.warning("historical search failed: %s: %s", type(error).__name__, error)
        return []
    log.info("historical search: %s discovery link(s) returned", len(hits))
    headlines = []
    seen = set()
    for hit in hits[:8]:
        if not allowed(hit.url):
            log.info("discovery skipped: result outside configured publishers")
            continue
        url = canonical_url(hit.url)
        if url in seen:
            continue
        seen.add(url)
        try:
            document = fetch(url)
            if not allowed(document.url):
                continue
            extracted = extract(document)
            if extracted.published != day.isoformat():
                log.info("discovery skipped: publication date %s: %s", extracted.published or "unknown", url)
                continue
            topic_text = extracted.title + " " + " ".join(b.text for b in extracted.blocks)[:3000]
            if not extracted.title or not _AI_TOPIC_RE.search(topic_text):
                continue
            headlines.append(
                Headline(extracted.title, canonical_url(document.url), datetime.combine(day, datetime.min.time(), UTC))
            )
        except Exception as error:
            log.warning("discovery extraction failed: %s: %s: %s", url, type(error).__name__, error)
    log.info("historical search: %s publication-date-confirmed item(s)", len(headlines))
    return headlines


PREFER_HOURS = 12
FALLBACK_HOURS = 24
# Official newsrooms post a few times a day in total, so they always get the
# wider window; reporting feeds keep the preferred 12h freshness.
PRIMARY_HOURS = 24


def fetch_recent_headlines(
    now: datetime,
    feeds: tuple[str, ...] = FEEDS,
    fetch: Fetch = default_fetch,
    gdelt_fetch: Callable[[date], list[Headline]] = _default_gdelt_fetch,
) -> list[Headline]:
    """For the live scheduled job (not a historical backfill): headlines
    published in the last `PREFER_HOURS`; if none, widen to the last
    `FALLBACK_HOURS`; if still none, fall back to GDELT for today's
    calendar day before giving up."""
    log.info("fetching feeds...")
    all_headlines = fetch_all_feed_headlines(feeds, fetch)
    log.info("%s total feed item(s) fetched", len(all_headlines))

    rules = load_rules()
    primary_cutoff = now - timedelta(hours=PRIMARY_HOURS)
    for hours in (PREFER_HOURS, FALLBACK_HOURS):
        cutoff = now - timedelta(hours=hours)
        recent = [
            h
            for h in all_headlines
            if h.published is not None and h.published >= (primary_cutoff if eligible_rule(h.url, rules) else cutoff)
        ]
        log.info(
            "%s item(s) published in the last %sh (official newsrooms: last %sh)", len(recent), hours, PRIMARY_HOURS
        )
        if recent:
            return recent

    log.info("no recent items in either window, falling back to GDELT...")
    try:
        gdelt = gdelt_fetch(now.date())
        log.info("GDELT: %s item(s)", len(gdelt))
        return gdelt
    except Exception as e:
        log.warning("GDELT: FAILED (%s: %s)", type(e).__name__, e)
        return []


def fetch_weekly_papers(end_day: date, fetch: Fetch = default_fetch, days: int = 7) -> list[Headline]:
    """The week's most upvoted Hugging Face Daily Papers, as arXiv abstract links."""
    papers: dict[str, tuple[int, Headline]] = {}
    for offset in range(days):
        day = end_day - timedelta(days=offset)
        try:
            body = json.loads(fetch(f"{_HF_DAILY_PAPERS_URL}?date={day.isoformat()}&limit=100"))
        except Exception as error:
            log.warning("papers %s: FAILED (%s: %s)", day, type(error).__name__, error)
            continue
        count = 0
        for item in body if isinstance(body, list) else []:
            paper = item.get("paper") if isinstance(item, dict) else None
            if not isinstance(paper, dict):
                continue
            paper_id, title, upvotes = paper.get("id"), paper.get("title"), paper.get("upvotes")
            if not (isinstance(paper_id, str) and _ARXIV_ID_RE.fullmatch(paper_id) and isinstance(title, str)):
                continue
            if not title.strip():
                continue
            votes = upvotes if isinstance(upvotes, int) else 0
            headline = Headline(
                " ".join(title.split()),
                f"https://arxiv.org/abs/{paper_id}",
                datetime.combine(day, datetime.min.time(), UTC),
            )
            if paper_id not in papers or votes > papers[paper_id][0]:
                papers[paper_id] = (votes, headline)
            count += 1
        log.info("papers %s: %s item(s)", day, count)
    pool = sorted(papers.values(), key=lambda item: -item[0])[:PAPER_POOL_SIZE]
    log.info("%s distinct paper(s) this week; top %s by upvotes kept", len(papers), len(pool))
    return [headline for _, headline in pool]


def week_stories(posts_dir: Path, day: str) -> list[dict]:
    """Weary's own live news stories from the Sunday to Friday before `day`."""
    from agent.publishing.archive import stories_between  # archive imports ranking, which imports this module

    end = datetime.strptime(day, "%Y-%m-%d").date()
    return stories_between(posts_dir, (end - timedelta(days=6)).isoformat(), (end - timedelta(days=1)).isoformat())
