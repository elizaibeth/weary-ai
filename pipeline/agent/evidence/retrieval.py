"""Fetch bounded document snapshots and extract article/PDF blocks without a model."""

import hashlib
import io
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib import request
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from pypdf import PdfReader

from agent.evidence.source_rules import canonical_url


@dataclass(frozen=True)
class FetchedDocument:
    url: str
    body: bytes
    content_type: str = "text/html"
    fetched_at: str = ""


@dataclass(frozen=True)
class Block:
    text: str
    page: int | None = None


@dataclass(frozen=True)
class ExtractedDocument:
    title: str
    blocks: tuple[Block, ...]
    links: tuple[tuple[str, str], ...] = ()
    published: str = ""


class _CheckedRedirect(request.HTTPRedirectHandler):
    def __init__(self, allowed: Callable[[str], bool]):
        self.allowed = allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not self.allowed(newurl):
            raise ValueError("redirect_rejected: destination is not an eligible source")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class DocumentFetcher:
    def __init__(self, cache_dir: Path, allowed: Callable[[str], bool], max_bytes: int = 20_000_000):
        self.cache_dir, self.allowed, self.max_bytes = cache_dir, allowed, max_bytes

    def __call__(self, url: str) -> FetchedDocument:
        url = canonical_url(url)
        if not self.allowed(url):
            raise ValueError("source_rejected: origin/path is not eligible")
        key = hashlib.sha256(url.encode()).hexdigest()
        metadata = self.cache_dir / f"{key}.json"
        body_path = self.cache_dir / f"{key}.bin"
        if metadata.exists() and body_path.exists() and time.time() - metadata.stat().st_mtime < 86400:
            try:
                data = json.loads(metadata.read_text())
                body = body_path.read_bytes()
                if (
                    self.allowed(data["url"])
                    and len(body) <= self.max_bytes
                    and hashlib.sha256(body).hexdigest() == data["sha256"]
                ):
                    return FetchedDocument(data["url"], body, data["content_type"], data["fetched_at"])
            except (ValueError, TypeError, KeyError, OSError):
                pass
        opener = request.build_opener(_CheckedRedirect(self.allowed))
        req = request.Request(
            url, headers={"User-Agent": "weary-news/0.1", "Accept": "text/html,application/pdf,text/plain"}
        )
        with opener.open(req, timeout=20) as response:
            final_url = canonical_url(response.url)
            if not self.allowed(final_url):
                raise ValueError("redirect_rejected: final URL is not eligible")
            body = response.read(self.max_bytes + 1)
            if len(body) > self.max_bytes:
                raise ValueError("extraction_failed: document exceeds byte limit")
            content_type = response.headers.get_content_type()
        fetched_at = datetime.now(UTC).isoformat()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        temporary = body_path.with_suffix(".tmp")
        temporary.write_bytes(body)
        temporary.replace(body_path)
        data = {
            "url": final_url,
            "content_type": content_type,
            "fetched_at": fetched_at,
            "sha256": hashlib.sha256(body).hexdigest(),
        }
        temporary = metadata.with_suffix(".tmp")
        temporary.write_text(json.dumps(data))
        temporary.replace(metadata)
        return FetchedDocument(final_url, body, content_type, fetched_at)


def _chunks(text: str, page: int | None = None) -> list[Block]:
    # Keep adjacent words together. A long HTML paragraph/PDF region becomes
    # bounded blocks; callers preserve neighbouring blocks as context.
    words = text.split()
    blocks: list[Block] = []
    current: list[str] = []
    size = 0
    for word in words:
        if size + len(word) > 1400 and current:
            blocks.append(Block(" ".join(current), page))
            current, size = [], 0
        current.append(word)
        size += len(word) + 1
    if current:
        blocks.append(Block(" ".join(current), page))
    return blocks


# Below this share of the surrounding <main> (or page body), the largest
# <article> is a teaser card, not the story: CISA, DeepMind and The Hacker
# News pages yielded one 70-150 character block from 10,000-character pages.
_ARTICLE_SHARE = 0.3


def _content_root(soup: BeautifulSoup) -> Tag:
    def size(tag: Tag) -> int:
        return len(tag.get_text(" ", strip=True))

    mains = soup.find_all("main")
    container = max(mains, key=size) if mains else soup.body or soup
    articles = soup.find_all("article")
    if not articles:
        return container
    article = max(articles, key=size)
    return article if size(article) >= _ARTICLE_SHARE * size(container) else container


def extract(document: FetchedDocument, page_hint: int | None = None, max_pdf_pages: int = 120) -> ExtractedDocument:
    if document.body.lstrip().startswith(b"%PDF-") or document.content_type == "application/pdf":
        try:
            reader = PdfReader(io.BytesIO(document.body))
            if reader.is_encrypted:
                raise ValueError("encrypted PDF")
            total = len(reader.pages)
            preferred = list(range(max(0, (page_hint or 1) - 2), min(total, (page_hint or 1) + 1)))
            indices = list(dict.fromkeys(preferred + list(range(total))))[:max_pdf_pages]
            blocks = []
            for index in sorted(indices):
                page = reader.pages[index]
                contents = page.get_contents()
                if contents is not None and len(contents.get_data()) > 10_000_000:
                    continue
                text = page.extract_text(extraction_mode="layout") or ""
                for part in re.split(r"\n\s*\n", text):
                    blocks.extend(_chunks(part, index + 1))
            if not blocks:
                raise ValueError("PDF has no extractable text; OCR is required")
            title = str(reader.metadata.title or "") if reader.metadata else ""
            return ExtractedDocument(title, tuple(blocks))
        except Exception as error:
            raise ValueError(f"extraction_failed: PDF: {error}") from error
    if document.content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
        raise ValueError(f"extraction_failed: unsupported content type {document.content_type}")
    if document.content_type == "text/plain":
        return ExtractedDocument("", tuple(_chunks(document.body.decode("utf-8", errors="replace"))))
    soup = BeautifulSoup(document.body, "html.parser")
    title_node = soup.find("h1") or soup.title
    title = title_node.get_text(" ", strip=True) if title_node else ""
    # Scholarly pages (arXiv, journals) name the work here; their first <h1>
    # can be a breadcrumb such as "Computer Science > Information Retrieval".
    citation_title = soup.find("meta", attrs={"name": "citation_title"})
    if citation_title and str(citation_title.get("content") or "").strip():
        title = " ".join(str(citation_title["content"]).split())
    if re.search(r"^(access denied|just a moment|page not found|403 forbidden|404 not found)", title, re.I):
        raise ValueError("extraction_failed: access/error page")
    published = ""
    for attrs in ({"property": "article:published_time"}, {"itemprop": "datePublished"}, {"name": "date"}):
        meta = soup.find("meta", attrs=dict(attrs))
        if meta and isinstance(meta.get("content"), str):
            published = str(meta["content"])[:10]
            break
    for tag in soup.select('script, style, noscript, nav, footer, aside, form, header, [hidden], [aria-hidden="true"]'):
        tag.decompose()
    root = _content_root(soup)
    links = tuple(
        (urljoin(document.url, str(a["href"])), a.get_text(" ", strip=True)) for a in root.find_all("a", href=True)
    )
    blocks = []
    tags = root.find_all(["p", "h1", "h2", "h3", "li", "blockquote", "tr", "pre"])
    for tag in tags:
        if tag.find(["p", "li", "tr", "pre"]):
            continue  # do not duplicate nested blocks
        blocks.extend(_chunks(tag.get_text(" ", strip=True)))
    if not blocks:
        blocks = _chunks(root.get_text(" ", strip=True))
    if not blocks:
        raise ValueError("extraction_failed: empty document")
    return ExtractedDocument(title, tuple(blocks), links, published)
