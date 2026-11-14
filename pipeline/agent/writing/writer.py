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
from functools import partial

from agent.evidence import status_pages
from agent.evidence.packet import EvidencePacket, ai_passage_ids, passage_catalog
from agent.research.candidate import Candidate
from agent.services import llm
from agent.writing.article import Draft
from agent.writing.draft_parser import parse_draft
from agent.writing.house_style import opinion_shape_issue
from agent.writing.prompts import OUTAGE_REPAIR_TITLE, build_prompt

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
    ai_ids = ai_lead_passages(candidate, evidence)
    failed = _failed_providers(candidate)
    prompt, aliases = build_prompt(
        candidate, catalog, existing_tags, ai_passages=ai_ids, outage_of=tuple(p.name for p in failed)
    )
    opinion = candidate.kind == "opinion"
    if opinion and client is _default_client:
        client = _opinion_client
    check: Callable[[Draft], str | None] | None = opinion_shape_issue if opinion else None
    if ai_ids is not None:
        check = partial(outage_issue, ai_ids=ai_ids, aliases=aliases, failed=failed)
    # Columns are more complex, so they get one more corrected retry.
    result = _draft_with_retry(
        prompt,
        client,
        lambda raw: parse_draft(raw, evidence, catalog, aliases),
        retries=2 if opinion else 1,
        check=check,
    )
    # Each series lives in its own category whatever the model chose.
    category = {"paper": "Research", "opinion": "Opinion"}.get(candidate.kind)
    return replace(result, category=category) if category else result


def _failed_providers(candidate: Candidate) -> tuple[status_pages.StatusProvider, ...]:
    """The providers whose outage this news story reports; empty otherwise."""
    if candidate.kind != "news":
        return ()
    return status_pages.outage_providers(candidate.headline, status_pages.load_config())


def ai_lead_passages(candidate: Candidate, evidence: EvidencePacket) -> set[str] | None:
    """For an outage story, the passage IDs that show an effect on AI (the
    article must lead with one); None for any other story."""
    if not _failed_providers(candidate):
        return None
    return ai_passage_ids(evidence.sources, status_pages.load_config())


def title_issue(title: str, failed: tuple[status_pages.StatusProvider, ...]) -> str | None:
    """Why an outage story's title fails to say what failed and how it touched
    AI, or None. Checked at drafting only: a repair may rename a title the
    verifier rejects, and the verified text then wins."""
    status = status_pages.load_config()
    names_failure = any(p.named_in(title) for p in failed)
    names_ai = status.mentions_ai(title) or any(p.ai and p.named_in(title) for p in status.providers)
    if names_failure and names_ai:
        return None
    missing = [
        part
        for part, present in (("the service that failed", names_failure), ("the AI products or companies", names_ai))
        if not present
    ]
    return f"the title of this outage story must name {' and '.join(missing)}"


def repair_title_rule(candidate: Candidate) -> tuple[str, Callable[[str], str | None]] | None:
    """For an outage story, the title requirement and check for the repairer."""
    failed = _failed_providers(candidate)
    if not failed:
        return None
    rule = OUTAGE_REPAIR_TITLE.format(providers=", ".join(p.name for p in failed))
    return " ".join(rule.split()), partial(title_issue, failed=failed)


def outage_issue(
    draft: Draft,
    ai_ids: set[str],
    aliases: dict[str, str] | None = None,
    failed: tuple[status_pages.StatusProvider, ...] = (),
) -> str | None:
    """The first problem with an outage story's shape: its lead, then its title."""
    return lead_issue(draft, ai_ids, aliases) or (title_issue(draft.title, failed) if failed else None)


def lead_issue(draft: Draft, ai_ids: set[str], aliases: dict[str, str] | None = None) -> str | None:
    """Why an outage story's lead fails to report the AI effect, or None.
    `aliases` (P1 -> passage ID) names the passages the way the writer saw them."""
    if not draft.paragraphs or set(draft.paragraphs[0].passage_ids) & ai_ids:
        return None
    names = [alias for alias, pid in (aliases or {}).items() if pid in ai_ids] or sorted(ai_ids)
    return "this outage story must lead with its effect on AI: the first paragraph has to report it and cite " + (
        f"at least one of {', '.join(names)}" if names else "a passage that shows it"
    )


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
