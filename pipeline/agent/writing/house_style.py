"""Weary's written house style, checked in Python rather than trusted to the model.

Everything here is a pure function of text: the banned-phrase list, dash and
citation-marker clean-up, headline and length rules, and the shape rules for
Saturday columns. The writer, repairer and final checks all use it.
"""

import re

from agent.evidence.packet import REPORTING_OUTLETS
from agent.writing.article import Draft

ALLOWED_CATEGORIES = {
    "Models",
    "Products",
    "Research",
    "Policy",
    "Business",
    "Safety",
    "Society",
    "Security",
    "Opinion",
}

# Overused AI-generated-writing tells. Checked deterministically (plain
# substring match) rather than trusting the model to police its own tone.
SLOP_PHRASES = (
    "delve into",
    "ever-evolving",
    "rapidly evolving landscape",
    "game-changer",
    "game changing",
    "revolutionary leap",
    "marks a significant milestone",
    "it remains to be seen",
    "only time will tell",
    "at the forefront",
    "paves the way",
    "paradigm shift",
    "testament to",
    "in conclusion",
    "in today's digital age",
    # Our own internal sourcing terminology, not something real reporting
    # ever narrates about itself - a leak of the prompt's own language
    # ("PRIMARY SOURCES", "primary-source facts") into reader-facing text.
    "primary source",
    "primary-source",
)

SUMMARY_WORD_LIMITS = {"description": (15, 40), "why_today": (12, 30), "image_caption": (5, 12)}

CAPTION_BANNED_RE = re.compile(r"\b(represents|symbolises|symbolizes|image|illustration)\b", re.IGNORECASE)

# Citation is handled entirely via each paragraph's own `source_ids` field -
# `publisher` renders a Sources list, never inline links - so a bracketed
# or parenthesised reference number in the prose itself (e.g. "[1]", "(2)")
# is always a leftover citation-marker habit, never something intentional.
_INLINE_CITATION_RE = re.compile(r"[\[(]\s*\d{1,2}\s*[\])]")
# Passage IDs are metadata; models sometimes echo them into prose, in square
# or round brackets: "[P1][P6]", "(P1, P2, P4)", "(P1-P3)", "(see P2)". Only a
# bracket holding nothing but IDs matches, so "(P2 class)" stays.
_PASSAGE_ID = r"P\d{1,3}(?:\s*[-–]\s*P?\d{1,3})?"
_PASSAGE_IDS = rf"\s*(?:(?:see|passages?)\s+)?{_PASSAGE_ID}(?:\s*(?:,|;|&|\band\b)\s*{_PASSAGE_ID})*\s*"
PASSAGE_MARKER_RE = re.compile(rf"\s*(?:\[{_PASSAGE_IDS}\]|\({_PASSAGE_IDS}\))", re.IGNORECASE)


def strip_passage_markers(text: str) -> str:
    return PASSAGE_MARKER_RE.sub("", text)


# Em/en dashes are the single most common overused-AI-writing tell, and
# unlike the other slop checks there's an unambiguous, safe fix rather than
# just rejecting the draft and forcing a full, expensive retry: replace the
# dash with a comma. `style_issues`'s own dash check stays in place as a
# backstop for anything this substitution doesn't catch (e.g. some other
# dash-like character), not as the primary defense.
_DASH_RE = re.compile(r"\s*[—–]\s*|\s+--\s+")


def replace_dashes(text: str) -> str:
    return _DASH_RE.sub(", ", text)


OPINION_TITLE_MAX_WORDS = 10
OPINION_PARAGRAPHS = (4, 7)


def opinion_shape_issue(draft: Draft) -> str | None:
    """The column rules a model most often ignores: a short headline with no
    label, and a focused length. Returns the reason, or None when it fits."""
    title_words = len(draft.title.split())
    if draft.title.lower().startswith("opinion"):
        return 'title must not start with "Opinion"; the page already labels the column'
    if title_words > OPINION_TITLE_MAX_WORDS:
        return f"title must be at most {OPINION_TITLE_MAX_WORDS} words, got {title_words}"
    low, high = OPINION_PARAGRAPHS
    if not low <= len(draft.paragraphs) <= high:
        return f"column must have {low}-{high} paragraphs, got {len(draft.paragraphs)}"
    return None


def style_issues(title: str, paragraphs: list[dict], description: str = "", why_today: str = "") -> list[str]:
    text = " ".join(
        [title, description, why_today] + [f"{p.get('text', '')} {p.get('argument', '')}" for p in paragraphs]
    )
    lowered = text.lower()
    issues = [f"overused AI phrase: {phrase!r}" for phrase in SLOP_PHRASES if phrase in lowered]

    if "!" in title or title.count("?") > 1:
        issues.append("sensational headline punctuation")
    letters = [c for c in title if c.isalpha()]
    if letters and len(letters) >= 12 and sum(c.isupper() for c in letters) / len(letters) > 0.65:
        issues.append("headline uses excessive capital letters")

    normalised = [" ".join(p.get("text", "").lower().split()) for p in paragraphs]
    if len(normalised) != len(set(normalised)):
        issues.append("duplicate paragraph")

    if "—" in text or "–" in text or " -- " in text:
        issues.append("em dash or en dash (a common AI-writing tell)")

    if _INLINE_CITATION_RE.search(text):
        issues.append('inline citation marker (e.g. "[1]") - citation is source_ids only')

    # Under the primary-only citation rule, no reporting outlet is ever
    # citable, so its name should never appear in the article at all - if
    # it does, that's background reporting (an exclusive quote, "X told
    # OUTLET") leaking into a paragraph attributed to a primary source.
    # Case-sensitive: some outlet names (e.g. "The Conversation") are also
    # ordinary English phrases ("the conversation draws on...") that only
    # collide in lowercase - a genuine citation of the outlet is written
    # capitalized, in the same wire-style voice as the rest of the article.
    for name in set(REPORTING_OUTLETS.values()):
        if re.search(rf"\b{re.escape(name)}\b", text):
            issues.append(f"names an uncited reporting outlet: {name!r}")
    return issues


def deterministic_issues(draft: Draft) -> list[str]:
    """The same deterministic style/slop checks `draft_parser` runs on a fresh
    draft, re-run on a `Draft` object - used to catch a defect (e.g. an
    em dash) introduced by `repairer`, which only re-sends flagged
    paragraphs to a model and never re-runs this module's own checks."""
    paragraphs = [{"text": p.published_text} for p in draft.paragraphs]
    issues = style_issues(draft.title, paragraphs, draft.description, draft.why_today)
    if draft.claim_passages:
        for field, (minimum, maximum) in SUMMARY_WORD_LIMITS.items():
            if not minimum <= len(getattr(draft, field).split()) <= maximum:
                issues.append(f"{field} must contain {minimum}-{maximum} words")
        if CAPTION_BANNED_RE.search(draft.image_caption):
            issues.append("image_caption uses banned meta-framing language")
    return issues
