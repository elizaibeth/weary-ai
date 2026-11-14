"""The repair stage: ask a model to fix rejected claims, keep only valid fixes.

This is the shell around `repair_core`, which builds every prompt and checks
every reply. This module calls the model, allows one retry for a summary of
the wrong length, and logs what changed. The caller re-verifies the result.
"""

import logging
import os
from collections.abc import Callable
from dataclasses import replace

from agent.checking.repair_core import (
    apply_repairs,
    argument_prompt,
    length_problem,
    length_retry_prompt,
    parse_argument_reply,
    parse_repair_reply,
    passage_aliases,
    repair_prompt,
    supplement_citations,
)
from agent.checking.verify_core import ClaimResult
from agent.evidence.grounding import primary_sources, verification_targets
from agent.evidence.packet import EvidencePacket
from agent.services import llm
from agent.writing.article import Draft, Paragraph

log = logging.getLogger(__name__)

__all__ = ["MAX_ATTEMPTS", "Client", "repair", "repair_arguments", "supplement_citations"]

MAX_ATTEMPTS = 3
Client = Callable[[str], str]


def _default_client(prompt: str) -> str:
    return llm.complete(prompt, os.environ.get("WEARY_REPAIRER_MODEL") or llm.DEFAULT_MODEL)


def repair_arguments(draft: Draft, issues: list[ClaimResult], client: Client = _default_client) -> Draft:
    """Rewrite each opinion argument the fence rejected so it keeps its
    judgement but drops the fact it added. A rewrite that cannot be used
    keeps the original, which the caller then removes if it fails again."""
    failed = {r.claim: r.reason for r in issues if r.field == "argument" and not r.verified}
    if not failed:
        return draft
    paragraphs = []
    for p in draft.paragraphs:
        if p.argument not in failed:
            paragraphs.append(p)
            continue
        try:
            rewritten = parse_argument_reply(client(argument_prompt(p, failed[p.argument])))
        except (ValueError, KeyError, TypeError) as error:
            log.warning("rejected argument rewrite: %s", error)
            rewritten = p.argument
        if rewritten != p.argument:
            log.info("reargue: %r\n         -> %r", p.argument, rewritten)
        paragraphs.append(replace(p, argument=rewritten))
    return replace(draft, paragraphs=tuple(paragraphs))


def repair(
    draft: Draft,
    issues: list[ClaimResult],
    evidence: EvidencePacket | None,
    client: Client = _default_client,
    title_rule: str = "",
    title_check: Callable[[str], str | None] | None = None,
) -> Draft:
    """`title_rule` adds an edition's requirement to a title repair (an
    outage story names what failed and the AI side); `title_check` says why
    a repaired title breaks it. A breaking title gets one corrected retry,
    then stands: a supported title beats losing the story."""
    failed = {(r.field, r.claim): r for r in issues if not r.verified}
    if not failed:
        return draft
    sources = primary_sources(draft, evidence)
    if not sources:
        log.warning("cannot repair: no usable primary-source evidence")
        return draft
    aliases = passage_aliases(sources)
    results: dict[tuple[str, str], Paragraph | None] = {}
    for field, paragraph in verification_targets(draft, sources):
        issue = failed.get((field, paragraph.text))
        if not issue:
            continue
        prompt = repair_prompt(draft, field, paragraph, issue, sources, aliases, title_rule)
        try:
            proposed, diagnoses = parse_repair_reply(client(prompt), field, paragraph, sources, aliases)
            # Reject an overlong summary before installing it or paying to
            # verify it. Allow one bounded retry with exact Python feedback.
            problem = length_problem(field, proposed)
            if problem and proposed is not None:
                log.info("retrying repair [%s]: %s", field, problem)
                retry = length_retry_prompt(prompt, proposed, problem)
                proposed, diagnoses = parse_repair_reply(client(retry), field, paragraph, sources, aliases)
                if length_problem(field, proposed):
                    raise ValueError(f"{field} length still wrong after bounded retry")
            if field == "title" and title_check is not None and proposed is not None:
                shape = title_check(proposed.text)
                if shape:
                    log.info("retrying repair [title]: %s", shape)
                    retried, retried_diagnoses = parse_repair_reply(
                        client(length_retry_prompt(prompt, proposed, shape)), field, paragraph, sources, aliases
                    )
                    if retried is not None and not length_problem(field, retried):
                        proposed, diagnoses = retried, retried_diagnoses
                    if title_check(proposed.text):
                        log.info("repaired title still breaks the edition rule; keeping it: %r", proposed.text)
        except ValueError as error:
            log.warning("rejected repair [%s]: %s", field, error)
            continue
        results[field, paragraph.text] = proposed
        for text, reason in diagnoses:
            log.info("repair diagnosis [%s]: %r: %s", field, text, reason)
        if proposed is None:
            log.info("dropped: %r", paragraph.text)
        else:
            log.info("reedit [%s]: %r\n         -> %r", field, paragraph.text, proposed.text)
            for passage in proposed.support:
                log.info("support %s [%s]: %r", passage.passage_id, passage.source_id, passage.quote)
    return apply_repairs(draft, sources, results)
