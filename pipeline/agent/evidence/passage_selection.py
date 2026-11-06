"""Bounded passage selection with court-document structure preserved."""

import re

from agent.evidence.retrieval import Block
from agent.evidence.source_rules import passage_scores, relevance

_SEPARATE_OPINION = re.compile(
    r"^(?:\d+\s+)?[\w .,’'-]{1,100},\s*(?:(?:Circuit|Chief|Senior)\s+)?Judge,\s*"
    r"(?:dissenting|concurring)\b|^JUSTICE [\w .,’'-]{1,100},\s*(?:dissenting|concurring)\b",
    re.I,
)
_DISPOSITION = re.compile(
    r"\bwe\s+(?:(?:therefore|accordingly|thus)\s+)?(?:deny|grant|affirm|reverse|vacate|dismiss|remand)\b",
    re.I,
)


def select_order(
    blocks: tuple[Block, ...], headline: str, kind: str, hinted_page: int | None
) -> tuple[list[int], set[int], list[str]]:
    """Return ranking, structural reservations, and attribution for each block.

    Legal outcomes often omit the parties' names. Reserve an opening, final
    disposition, date and separate-opinion opening before keyword-heavy detail.
    This is a retrieval heuristic; claim verification still determines support.
    """
    scores = passage_scores([b.text for b in blocks], headline)
    ranked = sorted(range(len(blocks)), key=lambda i: (-scores[i], i))
    hints = [i for i in ranked if blocks[i].page == hinted_page and hinted_page is not None and scores[i] > 0]
    sections = [""] * len(blocks)
    reserved: list[int] = []
    if kind == "court_document":
        section = "Court opinion; before any identified separate opinion"
        boundaries = []
        for i, block in enumerate(blocks):
            match = _SEPARATE_OPINION.match(block.text)
            if match:
                section = "Separate opinion: " + match.group()
                boundaries.append(i)
            sections[i] = section
        end = boundaries[0] if boundaries else len(blocks)
        opening = next(
            (
                i
                for i in range(end)
                if re.search(r"\bthis (?:case|appeal) (?:arises|concerns|presents)\b", blocks[i].text, re.I)
            ),
            None,
        )
        dispositions = [i for i in range(end) if _DISPOSITION.search(blocks[i].text)]
        dated = next((i for i in range(min(end, 20)) if re.search(r"\bDecided\s+\w+\s+\d", blocks[i].text)), None)
        reserved = [i for i in (opening, dispositions[-1] if dispositions else None, dated) if i is not None]
        if boundaries:
            start = boundaries[0]
            stop = boundaries[1] if len(boundaries) > 1 else len(blocks)
            separate = next((i for i in range(start, stop) if relevance(blocks[i].text, headline) > 0), start)
            reserved.append(separate)
    order = list(dict.fromkeys(hints + reserved + ranked))
    return order, set(reserved), sections
