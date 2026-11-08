"""Turn the writer model's JSON reply into a validated `Draft`, or say why not.

Pure: no model calls and no I/O. Passage IDs are resolved to retrieved
sources here, so the model never controls citations or URLs. Every rejection
is a `ValueError` whose message the writer sends back for a corrected retry.
"""

import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from agent.evidence.packet import EvidencePacket
from agent.writing.article import Citation, Draft, Paragraph, SupportingPassage
from agent.writing.house_style import (
    ALLOWED_CATEGORIES,
    CAPTION_BANNED_RE,
    replace_dashes,
    strip_passage_markers,
    style_issues,
)

_MIN_SOURCES = 1  # raise to 2+ once research supplies corroborating URLs
_MIN_WORDS = 40
_MAX_WORDS = 1200
_BOILERPLATE_RE = re.compile(r"why it matters", re.IGNORECASE)
_EVENT_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_WORD_RE = re.compile(r"[a-z]{4,}")

_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"}


def _normalize_url(url: str) -> str:
    """Compares URLs ignoring harmless differences that a model routinely
    reproduces differently from how the evidence URL happens to be stored:
    a tracking-parameter suffix (?utm_source=...), or a "www." subdomain
    the model dropped (or added) when citing an otherwise-identical page -
    `evidence.packet`'s own domain matching already treats these as the same
    host, so a citation shouldn't be rejected as unretrieved over it."""
    parts = urlsplit(url)
    netloc = parts.netloc.removeprefix("www.")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in _TRACKING_PARAMS]
    return urlunsplit((parts.scheme, netloc, parts.path.rstrip("/"), urlencode(query), ""))


def _validate(data: dict, evidence: EvidencePacket) -> None:
    paragraphs = data.get("paragraphs") or []
    if not paragraphs:
        raise ValueError("Draft has no paragraphs")
    for p in paragraphs:
        if not p.get("text", "").strip():
            raise ValueError("Every paragraph needs text")

    sources = data.get("sources") or []
    if len(sources) < _MIN_SOURCES:
        raise ValueError(f"Need at least {_MIN_SOURCES} source(s)")
    source_ids = {s["id"] for s in sources}
    if len(source_ids) != len(sources):
        raise ValueError("Source ids must be unique")

    # Every citable source must be an actual primary source - never the
    # reporting/background article, which is context only and never citable.
    # Matched ignoring tracking-parameter differences, but always stored
    # back as the canonical evidence URL, never the model's own copy.
    primary_urls_by_norm = {_normalize_url(s.url): s.url for s in evidence.sources if s.role == "primary"}
    for s in sources:
        norm = _normalize_url(s.get("url", ""))
        if norm not in primary_urls_by_norm:
            raise ValueError(f"Source url is not a retrieved primary source: {s.get('url')!r}")
        s["url"] = primary_urls_by_norm[norm]

    for p in paragraphs:
        if not p.get("source_ids"):
            raise ValueError("Every paragraph needs at least one citation")
        if not set(p["source_ids"]) <= source_ids:
            raise ValueError("Paragraph cites an unknown source id")

    if data.get("category") not in ALLOWED_CATEGORIES:
        raise ValueError(f"Invalid category: {data.get('category')!r}")
    if not _EVENT_DATE_RE.match(data.get("event_date", "")):
        raise ValueError("event_date must be ISO YYYY-MM-DD")

    caption = data.get("image_caption", "")
    if CAPTION_BANNED_RE.search(caption):
        raise ValueError("image_caption uses banned meta-framing language")
    if not (5 <= len(caption.split()) <= 12):
        raise ValueError("image_caption must be a concise 5-12 word visual metaphor")

    description = data.get("description", "").strip()
    if not (15 <= len(description.split()) <= 40):
        raise ValueError("description must be a plain 15-40 word sentence")

    why_today = data.get("why_today", "").strip()
    if not (12 <= len(why_today.split()) <= 30):
        raise ValueError("why_today must be a plain 12-30 word sentence")

    full_text = " ".join(f"{p['text']} {p.get('argument', '')}".strip() for p in paragraphs)
    if _BOILERPLATE_RE.search(full_text):
        raise ValueError("Draft contains a 'Why it matters' section")

    word_count = len(full_text.split())
    if not (_MIN_WORDS <= word_count <= _MAX_WORDS):
        raise ValueError(f"Expected {_MIN_WORDS}-{_MAX_WORDS} words, got {word_count}")

    issues = style_issues(data.get("title", ""), paragraphs, description, why_today)
    if issues:
        raise ValueError("Slop check failed: " + "; ".join(issues))

    primary_text = " ".join(s.text for s in evidence.sources if s.role == "primary")
    evidence_words = set(_WORD_RE.findall(primary_text.lower()))
    body_words = set(_WORD_RE.findall(full_text.lower()))
    if evidence_words and not (body_words & evidence_words):
        raise ValueError("Draft shares no grounded terms with the retrieved primary sources")


def parse_draft(raw: str, evidence: EvidencePacket, catalog: dict, aliases: dict[str, str]) -> Draft:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("writer_invalid_json: response was not a JSON document") from error
    if not isinstance(data, dict):
        raise ValueError("writer_invalid_json: expected an object")
    for paragraph in data.get("paragraphs", []) if isinstance(data.get("paragraphs"), list) else []:
        # Opinion columns return {"facts", "argument"}; facts are the verified text.
        if isinstance(paragraph, dict) and "text" not in paragraph and isinstance(paragraph.get("facts"), str):
            paragraph["text"] = paragraph.pop("facts")
            if not isinstance(paragraph.get("argument"), str):
                paragraph["argument"] = ""
    claim_passages = data.get("claim_passages")
    if not isinstance(claim_passages, dict):
        raise ValueError("Every published summary field needs passage IDs")
    used_sources = {}

    def resolve(ids, where):
        if not isinstance(ids, list) or not ids or any(not isinstance(pid, str) for pid in ids):
            # Name the field so a corrected retry knows what to fix.
            raise ValueError(f"Missing or unknown passage ID for {where}: give it at least one listed passage ID")
        normalized = [aliases[pid] if pid in aliases else pid for pid in ids]
        unknown = [pid for pid in normalized if pid not in catalog]
        if unknown:
            raise ValueError(f"Unknown writer passage IDs: {repr(unknown)[:240]}; allowed: {', '.join(aliases)}")
        source_ids = []
        for pid in normalized:
            sid, source, passage = catalog[pid]
            source_ids.append(sid)
            used_sources[sid] = {"id": sid, "title": source.title or source.url, "url": source.url}
        return list(dict.fromkeys(source_ids)), list(dict.fromkeys(normalized))

    for field in ("title", "description", "why_today", "image_caption"):
        _, claim_passages[field] = resolve(claim_passages.get(field), f"claim_passages.{field}")
    for number, paragraph in enumerate(data.get("paragraphs", []), start=1):
        paragraph["source_ids"], paragraph["passage_ids"] = resolve(paragraph.get("passage_ids"), f"paragraph {number}")
    data["sources"] = list(used_sources.values())
    for field in ("title", "description", "why_today", "image_caption", "image_alt"):
        if isinstance(data.get(field), str):
            data[field] = strip_passage_markers(data[field])
            if field not in ("image_caption", "image_alt"):
                data[field] = replace_dashes(data[field])
    for p in data.get("paragraphs", []):
        for key in ("text", "argument"):
            if isinstance(p.get(key), str):
                p[key] = replace_dashes(strip_passage_markers(p[key]))
    _validate(data, evidence)
    return Draft(
        title=data["title"],
        description=data["description"].strip(),
        paragraphs=tuple(
            Paragraph(
                text=p["text"],
                argument=p.get("argument", ""),
                source_ids=tuple(p["source_ids"]),
                passage_ids=tuple(p["passage_ids"]),
                support=tuple(
                    SupportingPassage(catalog[pid][0], catalog[pid][2].text, pid) for pid in p["passage_ids"]
                ),
            )
            for p in data["paragraphs"]
        ),
        sources=tuple(Citation(id=s["id"], title=s["title"], url=s["url"]) for s in data["sources"]),
        category=data["category"],
        tags=tuple(data.get("tags", [])),
        event_date=data["event_date"],
        image_prompt=data["image_prompt"],
        image_alt=data["image_alt"],
        image_caption=data["image_caption"],
        why_today=data["why_today"].strip(),
        claim_passages=tuple(
            (field, tuple(claim_passages[field])) for field in ("title", "description", "why_today", "image_caption")
        ),
    )
