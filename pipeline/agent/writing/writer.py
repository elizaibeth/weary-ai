"""The writer stage: ask a model for an article and keep only a valid draft.

This is the thin, side-effecting shell around pure modules:
- `prompts` builds the prompt from the candidate and its evidence;
- `draft_parser` turns the reply into a validated `Draft` (citations
  resolved in Python, house style enforced by `house_style`);
- this module calls the model and retries a rejected draft with the exact
  reason, a bounded number of times.

Claim-by-claim checking against the evidence is the verifier's job, later.
"""

import logging
import os
from collections.abc import Callable
from dataclasses import replace

from agent.evidence.packet import EvidencePacket, passage_catalog
from agent.research.candidate import Candidate
from agent.services import llm
from agent.writing.article import Draft
from agent.writing.draft_parser import parse_draft
from agent.writing.house_style import opinion_shape_issue
from agent.writing.prompts import build_prompt

log = logging.getLogger(__name__)

Client = Callable[[str], str]

# The weekly column needs stronger argument than wire-style news; one call a
# week on a larger model costs a few cents.
OPINION_MODEL = "openai:gpt@5.5"


def _default_client(prompt: str) -> str:
    model = os.environ.get("WEARY_WRITER_MODEL") or llm.DEFAULT_MODEL
    return llm.complete(prompt, model)


def _opinion_client(prompt: str) -> str:
    return llm.complete(prompt, os.environ.get("WEARY_OPINION_MODEL") or OPINION_MODEL)


def draft(
    candidate: Candidate,
    evidence: EvidencePacket,
    client: Client = _default_client,
    existing_tags: tuple[str, ...] = (),
) -> Draft:
    catalog = passage_catalog(evidence)
    if not catalog:
        raise ValueError(
            f"{evidence.outcome if evidence.outcome != 'ready' else 'no_primary_source'}: no usable primary passages"
        )
    prompt, aliases = build_prompt(candidate, catalog, existing_tags)
    opinion = candidate.kind == "opinion"
    if opinion and client is _default_client:
        client = _opinion_client
    # Columns are more complex, so they get one more corrected retry.
    result = _draft_with_retry(
        prompt,
        client,
        lambda raw: parse_draft(raw, evidence, catalog, aliases),
        retries=2 if opinion else 1,
        check=opinion_shape_issue if opinion else None,
    )
    # Each series lives in its own category whatever the model chose.
    category = {"paper": "Research", "opinion": "Opinion"}.get(candidate.kind)
    return replace(result, category=category) if category else result


def _draft_with_retry(
    prompt: str,
    client: Client,
    parse_reply: Callable[[str], Draft],
    retries: int = 1,
    check: Callable[[Draft], str | None] | None = None,
) -> Draft:
    """Format rules (word counts, caption wording, JSON shape) are cheap to fix
    with the exact reason, so a rejected draft gets bounded corrected retries.
    `check` adds a per-edition rule that returns the reason a draft fails."""

    def parse(raw: str) -> Draft:
        draft = parse_reply(raw)
        problem = check(draft) if check else None
        if problem:
            raise ValueError(problem)
        return draft

    try:
        return parse(client(prompt))
    except ValueError as error:
        last_error = error
    for attempt in range(1, retries + 1):
        log.warning("draft rejected (%s); retry %s/%s with the reason", last_error, attempt, retries)
        retry_prompt = (
            f"{prompt}\n\nYour previous response was rejected: {last_error}\n"
            "Return the complete corrected JSON document, following every rule above."
        )
        try:
            return parse(client(retry_prompt))
        except ValueError as error:
            last_error = error
    raise last_error
