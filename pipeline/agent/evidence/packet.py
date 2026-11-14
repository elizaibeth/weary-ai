"""Build a bounded primary-source evidence packet before calling a writer.

Reporting supplies discovery links only. Eligibility comes from explicit origin
rules; relevance and passage selection are deterministic. Semantic support is
still decided by the verifier, not by a URL match or a search snippet.
"""

import hashlib
import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from agent.evidence import status_pages
from agent.evidence.passage_selection import select_order
from agent.evidence.retrieval import DocumentFetcher, FetchedDocument, extract
from agent.evidence.search import BraveSearch, Search, SearchStopped
from agent.evidence.source_rules import (
    SourceRule,
    canonical_url,
    eligible_rule,
    load_rules,
    mentions_subject,
    queries,
    relevance,
    terms,
)
from agent.evidence.status_pages import StatusConfig, StatusProvider
from agent.research.candidate import Candidate

log = logging.getLogger(__name__)

_MAX_SOURCE_CHARS = 8000
_CACHE_DIR = Path(__file__).resolve().parents[3] / ".weary" / "evidence"
_INSTRUCTION_RE = re.compile(
    r"\b(ignore (all|the|any|previous) instructions|disregard (the )?(above|previous)|you are now|new system prompt|act as (an?|the))\b",
    re.I,
)

REPORTING_OUTLETS = {
    "techcrunch.com": "TechCrunch",
    "theverge.com": "The Verge",
    "technologyreview.com": "MIT Technology Review",
    "wired.com": "WIRED",
    "reuters.com": "Reuters",
    "investing.com": "Investing.com",
    "apnews.com": "Associated Press",
    "bloomberg.com": "Bloomberg",
    "nytimes.com": "New York Times",
    "bbc.com": "BBC",
    "bbc.co.uk": "BBC",
    "cnn.com": "CNN",
    "forbes.com": "Forbes",
    "businessinsider.com": "Business Insider",
    "axios.com": "Axios",
    "theguardian.com": "The Guardian",
    "engadget.com": "Engadget",
    "arstechnica.com": "Ars Technica",
    "venturebeat.com": "VentureBeat",
    "cnbc.com": "CNBC",
    "wsj.com": "Wall Street Journal",
    "ft.com": "Financial Times",
    "politico.com": "Politico",
    "washingtonpost.com": "Washington Post",
    "theinformation.com": "The Information",
    "semafor.com": "Semafor",
    "vox.com": "Vox",
    "npr.org": "NPR",
    "thehackernews.com": "The Hacker News",
    "aljazeera.com": "Al Jazeera",
    "computerworld.com": "Computerworld",
    "gizmodo.com": "Gizmodo",
    "theconversation.com": "The Conversation",
    "thenextweb.com": "TNW",
    "cbsnews.com": "CBS News",
    "thenews.com.pk": "The News International",
    "insidedefense.com": "Inside Defense",
    "theregister.com": "The Register",
    "krebsonsecurity.com": "Krebs on Security",
    "bleepingcomputer.com": "BleepingComputer",
    "darkreading.com": "Dark Reading",
    "securityweek.com": "SecurityWeek",
    "therecord.media": "The Record",
}


@dataclass(frozen=True)
class Passage:
    id: str
    text: str
    context: str
    page: int | None = None


@dataclass(frozen=True)
class Source:
    url: str
    role: str
    text: str
    title: str = ""
    passages: tuple[Passage, ...] = ()
    provenance: str = ""
    retrieved_at: str = ""
    content_hash: str = ""


@dataclass(frozen=True)
class EvidencePacket:
    sources: tuple[Source, ...]
    fact_ledger: tuple[str, ...]
    outcome: str = "ready"
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceLimits:
    max_searches: int = 2
    max_fetches: int = 8
    max_sources: int = 3
    max_passages: int = 4
    max_pdf_pages: int = 120

    @classmethod
    def from_env(cls) -> "EvidenceLimits":
        return cls(
            **{
                name: max(1, min(int(os.environ.get("WEARY_" + name.upper(), str(default))), cap))
                for name, default, cap in (
                    ("max_searches", 2, 10),
                    ("max_fetches", 8, 20),
                    ("max_sources", 3, 6),
                    ("max_passages", 4, 8),
                    ("max_pdf_pages", 120, 300),
                )
            }
        )


Fetcher = Callable[[str], FetchedDocument | str]


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def is_reporting_url(url: str) -> bool:
    host = _host(url)
    return any(host == d or host.endswith("." + d) for d in REPORTING_OUTLETS)


def _quarantine(text: str) -> str:
    return _INSTRUCTION_RE.sub("[quarantined text removed]", text)


def source_passages(source: Source) -> tuple[Passage, ...]:
    if source.passages:
        return source.passages
    # In-memory callers and existing fixtures may supply already-extracted text.
    text = " ".join(source.text[:_MAX_SOURCE_CHARS].split())
    key = hashlib.sha256((source.url + "\n" + text).encode()).hexdigest()[:16]
    return (Passage(f"{key}:b1", text, text),) if text else ()


def gather(
    candidate: Candidate,
    fetch: Fetcher | None = None,
    *,
    search: Search | None = None,
    rules: tuple[SourceRule, ...] | None = None,
    limits: EvidenceLimits | None = None,
    cache_dir: Path | None = None,
    as_of_day: str | None = None,
    blocked_hosts: set[str] | None = None,
    status: StatusConfig | None = None,
) -> EvidencePacket:
    rules = rules if rules is not None else load_rules()
    status = status if status is not None else status_pages.load_config()
    limits = limits or EvidenceLimits.from_env()
    cache_dir = cache_dir or _CACHE_DIR
    network_fetch = fetch is None

    def allowed(url: str) -> bool:
        try:
            url = canonical_url(url)
        except ValueError:
            return False
        return eligible_rule(url, rules) is not None or is_reporting_url(url)

    fetch = fetch or DocumentFetcher(cache_dir / "documents", allowed)
    if search is None and network_fetch and os.environ.get("BRAVE_SEARCH_API_KEY"):
        search = BraveSearch(cache_dir / "search")
    sources: list[Source] = []
    diagnostics: list[str] = []
    queue: list[tuple[str, str]] = [(u, candidate.headline) for u in candidate.urls]
    seen: set[str] = set()
    # Shared across a run's candidates when given: a host that refused us
    # (401/403/429) for one candidate is skipped for the rest of the run.
    blocked_hosts = blocked_hosts if blocked_hosts is not None else set()
    fetch_count = 0
    pending_queries = iter(dict.fromkeys(queries(candidate.headline, rules, limits.max_searches)))

    def note(message: str) -> None:
        diagnostics.append(message)
        log.info("%s", message)

    # An outage story is told from the AI side or not at all: its status
    # pages say what broke, and an AI company's page (or a status entry that
    # names an AI product) must show the effect on AI. Only the headline
    # names the provider that failed: a summary such as "OpenAI's connector
    # broke in Microsoft's outage" names the companies affected, whose
    # unrelated incidents must not count.
    affected = status_pages.outage_providers(candidate.headline, status)
    status_sources = (
        _status_sources(
            candidate.headline,
            affected,
            status,
            rules,
            fetch,
            allowed,
            blocked_hosts,
            as_of_day,
            limits.max_passages,
            note,
        )
        if candidate.kind == "news" and affected
        else []
    )
    seen.update(s.url for s in status_sources)

    while True:
        if len(sources) >= limits.max_sources or fetch_count >= limits.max_fetches:
            break
        if not queue:
            # Direct sources and one search result batch are exhausted before
            # spending on another query. One usable primary source is enough
            # to attempt drafting; verification still decides factual support.
            if sources:
                note("search_skipped: usable primary evidence already collected")
                break
            if search is None:
                note("search_unavailable: using eligible article links only; configure BRAVE_SEARCH_API_KEY for search")
                break
            query = next(pending_queries, None)
            if query is None:
                break
            try:
                note(f"search: {query}")
                for hit in search(query):
                    if (
                        eligible_rule(hit.url, rules)
                        and _host(hit.url) not in blocked_hosts
                        and canonical_url(hit.url) not in seen
                    ):
                        queue.append((hit.url, hit.title + " " + hit.description))
            except SearchStopped as error:
                note(str(error))
                break
            except Exception as error:
                note(f"search_failed: {type(error).__name__}: {error}")
                break
            queue.sort(key=lambda item: (-relevance(item[0] + " " + item[1], candidate.headline), item[0]))
            # Reserve fetch capacity for a different query if this batch is weak.
            unique = {canonical_url(u): (u, label) for u, label in queue}
            queue = list(unique.values())[:3]
            continue
        url, _ = queue.pop(0)
        try:
            canonical = canonical_url(url)
        except ValueError:
            note(f"source_rejected: malformed URL {url}")
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        if _host(canonical) in blocked_hosts:
            note(f"source_skipped: host already denied access: {canonical}")
            continue
        if not allowed(canonical):
            note(f"source_rejected: unclassified origin/path {canonical}")
            continue
        fetch_count += 1
        try:
            raw = fetch(url)
            doc = FetchedDocument(canonical, raw.encode()) if isinstance(raw, str) else raw
            final = canonical_url(doc.url)
            if not allowed(final):
                note(f"source_rejected: redirected to unclassified origin/path {final}")
                continue
            if final != canonical and final in seen:
                continue
            seen.add(final)
            hint = parse_qs(urlsplit(url).fragment).get("page", [""])[0]
            extracted = extract(doc, int(hint) if hint.isdigit() else None, limits.max_pdf_pages)
            if as_of_day and extracted.published and extracted.published > as_of_day:
                note(f"source_rejected: published after edition date: {final}")
                continue
            rule = eligible_rule(final, rules)
            if rule is None:
                # Use body links, never menus/footer links, and don't cap them
                # before ranking. Two documents on one host remain eligible.
                links = [(u, label) for u, label in extracted.links if eligible_rule(u, rules)]
                links.sort(key=lambda item: (-relevance(item[0] + " " + item[1], candidate.headline), item[0]))
                queue.extend(links)
                note(f"reporting discovery: {final} ({len(links)} eligible body links)")
                continue
            blocks = extracted.blocks
            total_text = " ".join(b.text for b in blocks)
            if not mentions_subject(total_text, candidate.headline, rules):
                note(f"source_rejected: named subject absent from document: {final}")
                continue
            required = min(2, len(terms(candidate.headline)))
            if len(total_text) < 80 or required == 0 or relevance(total_text, candidate.headline) < required:
                note(f"source_rejected: insufficient relevant text: {final}")
                continue
            hinted_page = int(hint) if hint.isdigit() else None
            ranked, reserved, sections = select_order(blocks, candidate.headline, rule.kind, hinted_page)
            content_hash = hashlib.sha256(doc.body).hexdigest()
            key = hashlib.sha256((final + content_hash).encode()).hexdigest()[:16]
            passages: list[Passage] = []
            size = 0
            for i in ranked:
                if len(passages) >= limits.max_passages:
                    break
                block = blocks[i]
                if i not in reserved and relevance(block.text, candidate.headline) == 0:
                    continue
                context = " ".join(
                    blocks[j].text
                    for j in range(max(0, i - 1), min(len(blocks), i + 2))
                    if blocks[j].page == block.page and sections[j] == sections[i]
                )
                if sections[i]:
                    context = sections[i] + "\n" + context
                context = _quarantine(context)
                added_size = len(context) + (2 if passages else 0)
                if size + added_size > _MAX_SOURCE_CHARS:
                    continue
                size += added_size
                pid = f"{key}:p{block.page or 0}:b{i + 1}"
                passages.append(Passage(pid, _quarantine(block.text), context, block.page))
            if not passages:
                note(f"source_rejected: no relevant passages: {final}")
                continue
            text = "\n\n".join(p.context for p in passages)
            if any(s.text == text for s in sources):
                note(f"source_rejected: duplicate document text: {final}")
                continue
            sources.append(
                Source(
                    final,
                    "primary",
                    text,
                    extracted.title or final,
                    tuple(passages),
                    rule.kind,
                    doc.fetched_at,
                    content_hash,
                )
            )
            note(f"primary evidence: {final} ({rule.kind}, {len(passages)} passages)")
            # A founder's statement can point directly to the company's release.
            # Follow relevant eligible links before spending on search.
            linked_sources = [
                (u, label)
                for u, label in extracted.links
                if eligible_rule(u, rules) and relevance(u + " " + label, candidate.headline) >= 2
            ]
            linked_sources.sort(key=lambda item: (-relevance(item[0] + " " + item[1], candidate.headline), item[0]))
            queue.extend(linked_sources[:3])
        except HTTPError as error:
            if error.code in {401, 403, 429}:
                blocked_hosts.add(_host(canonical))
                note(
                    f"host_blocked: {_host(canonical)} returned HTTP {error.code}; skipping this host for this candidate"
                )
            note(f"extraction_failed: {canonical}: HTTPError: HTTP {error.code}")
        except Exception as error:
            note(f"extraction_failed: {canonical}: {type(error).__name__}: {error}")
    sources = status_sources + sources
    outcome = (
        "ready"
        if sources
        else (
            "extraction_failed" if any(d.startswith("extraction_failed:") for d in diagnostics) else "no_primary_source"
        )
    )
    if sources and candidate.kind == "news" and affected and not ai_passage_ids(sources, status):
        note(f"no_ai_source: no primary passage shows an effect on AI for this {affected[0].name} outage")
        sources, outcome = [], "no_ai_source"
    packet = EvidencePacket(tuple(sources), tuple(s.text for s in sources), outcome, tuple(diagnostics))
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256((candidate.headline + (as_of_day or "")).encode()).hexdigest()[:20]
    (cache_dir / f"packet-{key}.json").write_text(json.dumps(asdict(packet), indent=2))
    note(f"evidence outcome: {outcome}; {fetch_count}/{limits.max_fetches} fetches")
    return packet


def _status_sources(
    headline: str,
    affected: tuple[StatusProvider, ...],
    config: StatusConfig,
    rules: tuple[SourceRule, ...],
    fetch: Fetcher,
    allowed: Callable[[str], bool],
    blocked_hosts: set[str],
    as_of_day: str | None,
    max_passages: int,
    note: Callable[[str], None],
) -> list[Source]:
    """The affected providers' status entries for the outage, and the AI
    companies' entries that name an affected provider. Status feeds have
    their own budget (one fetch each), outside the article fetch limit."""
    found: list[Source] = []
    for feed, provider in status_pages.feeds_to_read(affected, config):
        if _host(feed) in blocked_hosts:
            note(f"status_skipped: host already denied access: {feed}")
            continue
        if not allowed(feed):
            note(f"status_skipped: no status_page rule allows {feed}")
            continue
        try:
            raw = fetch(feed)
            doc = FetchedDocument(canonical_url(feed), raw.encode()) if isinstance(raw, str) else raw
            final = canonical_url(doc.url)
            if not allowed(final):
                note(f"status_rejected: redirected to unclassified origin/path {final}")
                continue
            entries = status_pages.relevant_entries(status_pages.parse_feed(doc.body), provider, affected, as_of_day)
        except HTTPError as error:
            if error.code in {401, 403, 429}:
                blocked_hosts.add(_host(feed))
            note(f"status_failed: {feed}: HTTPError: HTTP {error.code}")
            continue
        except Exception as error:
            note(f"status_failed: {feed}: {type(error).__name__}: {error}")
            continue
        if not entries:
            note(f"status: nothing on this outage in {feed}")
            continue
        entries.sort(key=lambda e: -relevance(e.passage, headline))
        # Readers follow the citation, so cite each entry's incident page,
        # else the provider's status page; the raw feed only as a last resort.
        by_page: dict[str, list[status_pages.StatusEntry]] = {}
        for entry in entries[:max_passages]:
            page = next(
                (u for u in (entry.link, provider.page) if u and allowed(u) and eligible_rule(u, rules)),
                final,
            )
            by_page.setdefault(page, []).append(entry)
        for page, page_entries in by_page.items():
            content_hash = hashlib.sha256("\n".join(e.passage for e in page_entries).encode()).hexdigest()
            key = hashlib.sha256((page + content_hash).encode()).hexdigest()[:16]
            # Who posted an entry is known from the feed registry, not the
            # entry text ("Claude", never "Anthropic"); state it, so a claim
            # attributed to the company can be checked.
            passages = tuple(
                Passage(f"{key}:p0:b{i}", text, text)
                for i, e in enumerate(page_entries, 1)
                for text in [_quarantine(f"{provider.name} status page: {e.passage}")]
            )
            title = f"{provider.name} status" + (f": {page_entries[0].title}" if len(page_entries) == 1 else "")
            found.append(
                Source(
                    page,
                    "primary",
                    "\n\n".join(p.context for p in passages),
                    title,
                    passages,
                    "status_page",
                    doc.fetched_at,
                    content_hash,
                )
            )
            note(f"status evidence: {page} ({provider.name}, {len(passages)} entries, from {final})")
    return found


def ai_passage_ids(sources: list[Source] | tuple[Source, ...], status: StatusConfig) -> set[str]:
    """IDs of the primary passages that show an effect on AI."""
    return {
        p.id
        for s in sources
        if s.role == "primary"
        for p in source_passages(s)
        if status_pages.is_ai_passage(s.url, p.text, status)
    }


def read_article(url: str, cache_dir: Path | None = None, rules: tuple[SourceRule, ...] | None = None) -> str:
    """The text of a reporting article or eligible page, for a model to read
    as a lead (never as evidence). Raises for any other origin."""
    rules = rules if rules is not None else load_rules()

    def allowed(candidate_url: str) -> bool:
        try:
            candidate_url = canonical_url(candidate_url)
        except ValueError:
            return False
        return eligible_rule(candidate_url, rules) is not None or is_reporting_url(candidate_url)

    doc = DocumentFetcher((cache_dir or _CACHE_DIR) / "documents", allowed)(url)
    return " ".join(block.text for block in extract(doc).blocks)


def independent_source_count(packet: EvidencePacket) -> int:
    return len(
        {s.content_hash or hashlib.sha256(s.text.encode()).hexdigest() for s in packet.sources if s.role == "primary"}
    )


def passage_catalog(packet: EvidencePacket) -> dict[str, tuple[int, Source, Passage]]:
    result = {}
    for sid, source in enumerate((s for s in packet.sources if s.role == "primary"), 1):
        for passage in source_passages(source):
            if passage.id in result:
                raise ValueError("Duplicate passage ID in evidence packet")
            result[passage.id] = (sid, source, passage)
    return result
