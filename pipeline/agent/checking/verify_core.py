"""The pure core of verification: what to check, the questions, reading the answers.

No TypeSafe calls happen here; `verifier` makes them. Each published claim
is paired with only the evidence it cites, grouped into batches that share
that evidence, and every answer is turned into a `ClaimResult`.
"""

from dataclasses import dataclass

from typesafe_sdk import Choice

from agent.evidence.grounding import paragraph_evidence, primary_sources, verification_targets
from agent.evidence.packet import EvidencePacket
from agent.writing.article import Draft, Paragraph

# Only paragraphs with identical evidence may share a batch.
BATCH_SIZE = 6
_MAX_BODY_CHARS = 3000


@dataclass(frozen=True)
class ClaimResult:
    claim: str
    verified: bool
    confidence: float
    reason: str = ""
    field: str = "body"


@dataclass(frozen=True)
class Check:
    """One claim to judge: the field it publishes in, the paragraph whose
    citations supply the evidence, the text to judge, and whether it is
    fenced (opinion: may judge freely, must add no fact)."""

    field: str
    paragraph: Paragraph
    claim: str
    fenced: bool

    @property
    def published(self) -> str:
        return _claim_text(self.field, self.paragraph, self.claim)


_FACT_QUESTION = (
    "Is EVERY factual assertion in this paragraph supported by the provided primary evidence? "
    "Check dates, entities, scope, legal outcomes, attribution, and claimed implications. "
    "A dissent or concurrence is a separate opinion, not the court's holding. "
    "One unsupported assertion makes the paragraph unsupported. Do not use outside knowledge. "
    "If proposed supporting passages are present, they must support the whole replacement "
    "and faithfully reflect the full source context, including qualifications and negation. "
)
# Opinion columns: argument is fenced, not fact-checked. It may interpret and
# judge freely but must not smuggle in a fact the evidence does not contain.
_FENCE_QUESTION = (
    "This text is the opinion part of a column. Does it state or imply any specific fact "
    "(an event, number, name, date, quotation, or claim about what someone did, said or decided) "
    "that is NOT established by the provided evidence or the paragraph's stated facts? "
    "Opinions, interpretations, judgements, predictions framed as the writer's view and rhetorical "
    "questions are allowed and are not facts. A verdict stated plainly (for example 'X is not ready', "
    "'the pitch is hype', 'X is selling Y before Z') is the writer's judgement, not a fact, when the "
    "stated facts give it a basis. Answer supported only if it adds no specific, checkable fact. "
    "Do not use outside knowledge. "
)
_FENCE_CRITERIA = {
    "supported": "It adds no fact beyond the evidence and the stated facts.",
    "unsupported": "It states or implies at least one fact absent from the evidence or stated facts.",
}
_FACT_CRITERIA = {
    "supported": "Every assertion is established by this evidence.",
    "unsupported": "At least one assertion is missing, contradicted, or stronger than this evidence.",
}


def checks_for(draft: Draft, evidence: EvidencePacket | None, opinion: bool = False) -> tuple[list[Check], dict]:
    """Every claim to judge, in publication order, and the cited sources.

    `opinion=True` (Saturday column): each paragraph's facts get the strict
    check; its argument, and the summary fields, get the fence check. A
    column's headline and summaries sum up the whole argument, so they are
    fenced against every stated fact in the column."""
    declared_ids = {c.id for c in draft.sources}
    sources = {sid: s for sid, s in primary_sources(draft, evidence).items() if sid in declared_ids}
    checks: list[Check] = []
    body = iter(draft.paragraphs)
    all_facts = " ".join(p.text for p in draft.paragraphs)
    for field, p in verification_targets(draft, sources):
        if field != "body":
            claim = f"Stated facts: {all_facts}\nArgument: {p.text}" if opinion else p.text
            checks.append(Check(field, p, claim, opinion))
            continue
        checks.append(Check(field, p, p.text, False))
        argument = next(body).argument
        if opinion and argument:
            checks.append(Check("argument", p, f"Stated facts: {p.text}\nArgument: {argument}", True))
    return checks, sources


def cache_key(check: Check, evidence_text: str) -> tuple[str, str, str]:
    return (check.field + (":fence" if check.fenced else ""), check.claim, evidence_text)


def batches(
    checks: list[Check], sources: dict, known: dict[tuple[str, str, str], ClaimResult]
) -> tuple[dict[int, ClaimResult], list[tuple[str, list[int]]], dict[int, tuple[str, str, str]]]:
    """Split checks into results already decided (evidence missing, or a
    supported answer in `known`) and batches still to ask, each sharing one
    evidence text. Also returns each asked check's cache key."""
    decided: dict[int, ClaimResult] = {}
    groups: dict[str, list[int]] = {}
    keys: dict[int, tuple[str, str, str]] = {}
    for index, check in enumerate(checks):
        try:
            text = paragraph_evidence(check.paragraph, sources)
        except ValueError as error:
            decided[index] = ClaimResult(check.published, False, 0.0, str(error), check.field)
            continue
        keys[index] = cache_key(check, text)
        if keys[index] in known:
            decided[index] = known[keys[index]]
            continue
        groups.setdefault(text, []).append(index)
    pending = [
        (text, indices[start : start + BATCH_SIZE])
        for text, indices in groups.items()
        for start in range(0, len(indices), BATCH_SIZE)
    ]
    return decided, pending, keys


def questions_for(checks: list[Check]) -> dict[str, Choice]:
    return {
        f"claim_{i}": Choice(
            instructions=(_FENCE_QUESTION if c.fenced else _FACT_QUESTION)
            + f"Published field: {c.field}. Claim: {c.claim}",
            criteria=_FENCE_CRITERIA if c.fenced else _FACT_CRITERIA,
        )
        for i, c in enumerate(checks)
    }


def result_from_answer(check: Check, choice: str, supported_probability: float) -> ClaimResult:
    verified = choice == "supported"
    reason = (
        "It adds a fact absent from the evidence."
        if check.fenced
        else "At least one assertion is not supported by the cited primary evidence."
    )
    return ClaimResult(
        claim=check.published,
        field=check.field,
        verified=verified,
        confidence=supported_probability,
        reason="" if verified else reason,
    )


def _claim_text(field: str, paragraph: Paragraph, claim: str) -> str:
    # Repairs and logs match results by the published text of their field.
    return claim.split("\nArgument: ", 1)[1] if field == "argument" else paragraph.text  # fields: their own text


def passed(results: list[ClaimResult]) -> bool:
    return bool(results) and all(r.verified for r in results)


def relevance_request(headline: str, evidence_summary: str, draft: Draft) -> tuple[dict, dict[str, Choice]]:
    """Ask whether the article reports the surveyed event, not a tangent the
    evidence trail wandered onto. A well-sourced draft can still be off-topic."""
    state = {
        "original_headline": headline,
        "original_summary": evidence_summary,
        "article_title": draft.title,
        "article_body": draft.body_text[:_MAX_BODY_CHARS],
    }
    questions = {
        "same_event": Choice(
            instructions=(
                "Does the article (title and body) report on the same real-world "
                "news event described by the original headline and summary? Answer "
                "different_event if the article drifted onto an unrelated topic, "
                "even if the article itself is internally well-sourced."
                " The body must retain the central event; a matching title alone is insufficient."
                " Reporting a pending review or filing does not report a completed ruling."
                " A court story must retain the specific disposition, and a budget story the new request;"
                " related background or procedural history alone is different_event."
            ),
            criteria={"same_event": None, "different_event": None},
        )
    }
    return state, questions
