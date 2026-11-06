"""Select one URL in Python, without discovery or a ranking-model call."""

import hashlib
import logging
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from agent.evidence.packet import EvidenceLimits, Fetcher, is_reporting_url
from agent.evidence.retrieval import DocumentFetcher, FetchedDocument, extract
from agent.evidence.source_rules import canonical_url, eligible_rule, load_rules
from agent.research.candidate import Candidate

log = logging.getLogger(__name__)


def candidate_from_url(url: str, day: str, *, fetch: Fetcher | None = None, cache_dir: Path | None = None) -> Candidate:
    """Use the fetched headline as discovery context, never as primary evidence.

    Manual selection can choose an older story for an edition, but cannot
    make a future-dated article eligible or override source classification.
    """
    date.fromisoformat(day)
    requested = canonical_url(url.strip())
    rules = load_rules()

    def allowed(target: str) -> bool:
        try:
            target = canonical_url(target)
            return is_reporting_url(target) or eligible_rule(target, rules) is not None
        except ValueError:
            return False

    if not allowed(requested):
        raise ValueError("Unsupported story URL: use a configured reporting publisher or eligible primary source")
    cache_dir = cache_dir or Path(__file__).resolve().parents[3] / ".weary" / "evidence" / "documents"
    fetch = fetch or DocumentFetcher(cache_dir, allowed)
    raw = fetch(requested)
    document = FetchedDocument(requested, raw.encode()) if isinstance(raw, str) else raw
    if not allowed(document.url):
        raise ValueError("Story URL redirected to an unsupported origin")
    final = canonical_url(document.url)
    hint = parse_qs(urlsplit(url).fragment).get("page", [""])[0]
    page = int(hint) if hint.isdigit() else None
    extracted = extract(document, page_hint=page, max_pdf_pages=EvidenceLimits.from_env().max_pdf_pages)
    headline = " ".join(extracted.title.split())
    if not headline or len(headline) > 500:
        raise ValueError("Could not read a usable headline; supply the article page rather than an untitled document")
    if len(" ".join(b.text for b in extracted.blocks)) < 80:
        raise ValueError("Story URL has too little readable article text")
    if extracted.published and extracted.published > day:
        raise ValueError(f"Story publication date {extracted.published} is after edition date {day}")
    log.info("manual headline: %r", headline)
    log.info("article publication date: %s; edition date: %s", extracted.published or "unknown", day)
    # Keep both redirect aliases for duplicate detection, and a linked PDF page
    # hint for evidence collection. DocumentFetcher caches the canonical URL.
    hinted = final + (f"#page={page}" if page is not None else "")
    urls = tuple(dict.fromkeys((hinted, final, requested)))
    key = hashlib.sha256((final + day).encode()).hexdigest()[:16]
    return Candidate(f"manual-{key}", headline, urls, 1.0)
