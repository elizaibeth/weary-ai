"""Verify a draft's claims against its evidence packet (Jev).

TypeSafe AI's `system_one` classifier must support every assertion in a
paragraph using only that paragraph's primary-source citations. This is a
hard gate: any unverifiable paragraph (including the case of no evidence at
all, which fails closed rather than passing by default) blocks the draft
from publishing live.

This is the shell: it sends the batches `verify_core` prepares to TypeSafe
and reads the answers back through `verify_core`.
"""

from collections.abc import Callable

from typesafe_sdk import TypeSafeClient

from agent.checking.verify_core import (
    ClaimResult,
    batches,
    checks_for,
    passed,
    questions_for,
    relevance_request,
    result_from_answer,
)
from agent.evidence.packet import EvidencePacket
from agent.services import costs
from agent.writing.article import Draft

__all__ = ["ClaimResult", "SystemOne", "check_relevance", "passed", "verify"]

# Typed as `object`, not `typesafe_sdk.SystemOneResponse`, deliberately:
# its `.answers` values are a NoulAnswer | ChoiceAnswer | ScoreAnswer union
# and only ChoiceAnswer carries `.choice`/`.probabilities` (the only kind
# this module ever asks for) - properly narrowing that would mean adding
# isinstance checks into this module's verification logic itself, which is
# out of scope for a tooling/type-checking setup pass. Known mypy gap.
SystemOne = Callable[[dict, dict], object]


def _default_system_one(state: dict, questions: dict) -> object:
    with TypeSafeClient() as client:
        response = client.system_one(state=state, questions=questions)
    costs.record_typesafe(response.usage)
    return response


def verify(
    draft: Draft,
    evidence: EvidencePacket | None,
    system_one: SystemOne = _default_system_one,
    *,
    supported_cache: dict[tuple[str, str, str], ClaimResult] | None = None,
    opinion: bool = False,
) -> list[ClaimResult]:
    """Check every published claim against its cited primary evidence (see
    `verify_core.checks_for` for what opinion mode changes). Supported answers
    are stored in `supported_cache`, so an unchanged claim is not re-asked."""
    checks, sources = checks_for(draft, evidence, opinion)
    results, pending, keys = batches(checks, sources, supported_cache if supported_cache is not None else {})
    for evidence_text, indices in pending:
        response = system_one({"evidence": evidence_text}, questions_for([checks[i] for i in indices]))
        for i, index in enumerate(indices):
            # `SystemOne` is typed `object` deliberately (see its definition
            # above): only ChoiceAnswer, the kind asked for, has these fields.
            answer = response.answers[f"claim_{i}"]  # type: ignore[attr-defined]
            results[index] = result_from_answer(
                checks[index], answer.choice, answer.probabilities.get("supported", 0.0)
            )
            if results[index].verified and supported_cache is not None:
                supported_cache[keys[index]] = results[index]
    return [results[i] for i in range(len(checks))]


def check_relevance(
    headline: str,
    evidence_summary: str,
    draft: Draft,
    system_one: SystemOne = _default_system_one,
) -> bool:
    """Whether the drafted article reports the surveyed candidate's event."""
    response = system_one(*relevance_request(headline, evidence_summary, draft))
    return response.answers["same_event"].choice == "same_event"  # type: ignore[attr-defined]
