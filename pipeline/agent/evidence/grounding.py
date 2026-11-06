"""Shared primary-source snapshots and citation checks for repair and verification.

Keep source boundaries and stable IDs. Never fall back to the mixed-role fact
ledger, and never truncate a concatenation that can lose later cited sources.
"""

from dataclasses import dataclass

from agent.evidence.packet import EvidencePacket, Passage, source_passages
from agent.writing.article import Citation, Draft, Paragraph, SupportingPassage


def normalize(text: str) -> str:
    return " ".join(text.split())


@dataclass(frozen=True)
class PrimarySource:
    citation: Citation
    text: str
    passages: tuple[Passage, ...] = ()


def primary_sources(draft: Draft, evidence: EvidencePacket | None) -> dict[int, PrimarySource]:
    if evidence is None:
        return {}
    citations = {c.url: c for c in draft.sources}
    next_id = max((c.id for c in draft.sources), default=0) + 1
    sources = {}
    seen_urls = set()
    for source in evidence.sources:
        if source.role != "primary" or source.url in seen_urls:
            continue
        seen_urls.add(source.url)
        passages = source_passages(source)
        text = normalize(" ".join(p.context for p in passages))
        if not text:
            continue
        citation = citations.get(source.url)
        if citation is None:
            citation = Citation(next_id, source.title or source.url, source.url)
            next_id += 1
        sources[citation.id] = PrimarySource(citation, text, passages)
    return sources


def format_sources(sources: dict[int, PrimarySource], display_ids: dict[str, str] | None = None) -> str:
    display_ids = display_ids or {}
    return "\n\n".join(
        f"Source {sid} ({s.citation.url}) | Passage {display_ids.get(p.id, p.id)} | page {p.page or 'HTML'}:\nText: {p.text}\nContext: {p.context}"
        for sid, s in sources.items()
        for p in s.passages
    )


def validate_support(support: tuple[SupportingPassage, ...], sources: dict[int, PrimarySource]) -> None:
    for passage in support:
        source = sources.get(passage.source_id)
        quote = normalize(passage.quote)
        if source is None or not quote or quote not in source.text:
            raise ValueError(f"Supporting quote is absent from primary source {passage.source_id}")


def paragraph_evidence(paragraph: Paragraph, sources: dict[int, PrimarySource]) -> str:
    ids = set(paragraph.source_ids)
    if not ids or not ids <= sources.keys():
        raise ValueError("Missing or unresolved primary-source citation")
    cited = {sid: s for sid, s in sources.items() if sid in ids}
    if paragraph.passage_ids:
        expected = resolve_passages(paragraph.text, paragraph.passage_ids, cited)
        if set(expected.source_ids) != ids:
            raise ValueError("Passage IDs do not match paragraph citations")
        if paragraph.support != expected.support:
            raise ValueError("Passage text does not match the evidence snapshot")
        return "\n\n".join(
            f"Source {sid} ({source.citation.url}) | Passage {p.id} | page {p.page or 'HTML'}:\n"
            f"Proposed supporting passage: {p.text}\nSource context: {p.context}"
            for sid, source in cited.items()
            for p in source.passages
            if p.id in paragraph.passage_ids
        )
    text = format_sources(cited)
    if paragraph.support:
        if {p.source_id for p in paragraph.support} != ids:
            raise ValueError("Supporting passages do not match the paragraph's citations")
        validate_support(paragraph.support, cited)
        # Retain full source context so a literal but cherry-picked quote cannot
        # hide a negation, qualification, or attribution from the verifier.
        text += "\n\nProposed supporting passages (check against the source context above):\n"
        text += "\n".join(f"Source {p.source_id}: {normalize(p.quote)}" for p in paragraph.support)
    return text


def resolve_passages(text: str, passage_ids: tuple[str, ...], sources: dict[int, PrimarySource]) -> Paragraph:
    catalog = {p.id: (sid, p) for sid, source in sources.items() for p in source.passages}
    if not passage_ids or any(pid not in catalog for pid in passage_ids):
        raise ValueError("Missing or unknown passage ID")
    support = tuple(SupportingPassage(catalog[pid][0], catalog[pid][1].text, pid) for pid in passage_ids)
    return Paragraph(text, tuple(dict.fromkeys(p.source_id for p in support)), support, passage_ids)


def verification_targets(draft: Draft, sources: dict[int, PrimarySource]) -> list[tuple[str, Paragraph]]:
    targets = [("body", p) for p in draft.paragraphs]
    for field, ids in draft.claim_passages:
        if field not in {"title", "description", "why_today", "image_caption"}:
            raise ValueError("Unexpected published claim field")
        # Unknown IDs remain a failed claim, never silently excluded from verification.
        try:
            paragraph = resolve_passages(getattr(draft, field), ids, sources)
        except ValueError:
            paragraph = Paragraph(getattr(draft, field), (), passage_ids=ids)
        targets.append((field, paragraph))
    return targets
