"""The pure verification core: which claims to check, batching, questions and answers (`agent.verify_core`)."""

from dataclasses import replace

from agent.checking import verify_core
from agent.evidence.packet import EvidencePacket, Source
from agent.writing.article import Citation, Draft, Paragraph

EVIDENCE = EvidencePacket(sources=(Source("https://example.com", "primary", "A fact."),), fact_ledger=("A fact.",))
DRAFT = Draft(
    title="T",
    description="d",
    paragraphs=(Paragraph("Fact one.", (1,), argument="That looks like a bet."), Paragraph("Fact two.", (1,))),
    sources=(Citation(id=1, title="Example", url="https://example.com"),),
    category="Opinion",
    tags=("x",),
    event_date="2026-09-25",
    image_prompt="p",
    image_alt="a",
    image_caption="c",
    why_today="w",
)


def test_news_mode_checks_each_paragraph_strictly_and_ignores_arguments():
    checks, _ = verify_core.checks_for(DRAFT, EVIDENCE)
    assert [(c.field, c.published, c.fenced) for c in checks] == [
        ("body", "Fact one.", False),
        ("body", "Fact two.", False),
    ]


def test_opinion_mode_fences_arguments_against_their_paragraphs_facts():
    checks, _ = verify_core.checks_for(DRAFT, EVIDENCE, opinion=True)
    argument = next(c for c in checks if c.field == "argument")
    assert argument.fenced and argument.published == "That looks like a bet."
    assert argument.claim == "Stated facts: Fact one.\nArgument: That looks like a bet."
    assert not any(c.fenced for c in checks if c.field == "body")


def test_opinion_summaries_are_fenced_against_every_stated_fact():
    column = replace(DRAFT, paragraphs=DRAFT.paragraphs, claim_passages=())
    checks, _ = verify_core.checks_for(column, EVIDENCE, opinion=True)
    for check in (c for c in checks if c.field not in ("body", "argument")):
        assert check.fenced and check.claim.startswith("Stated facts: Fact one. Fact two.")


def test_known_supported_answers_are_reused_and_the_rest_batched_by_evidence():
    checks, sources = verify_core.checks_for(DRAFT, EVIDENCE)
    _, first_pending, keys = verify_core.batches(checks, sources, {})
    assert len(first_pending) == 1 and first_pending[0][1] == [0, 1]
    known = {keys[0]: verify_core.ClaimResult("Fact one.", True, 0.9)}
    decided, pending, _ = verify_core.batches(checks, sources, known)
    assert decided == {0: known[keys[0]]} and pending[0][1] == [1]


def test_batches_never_exceed_the_batch_size():
    many = replace(DRAFT, paragraphs=tuple(Paragraph(f"Fact {n}.", (1,)) for n in range(14)))
    checks, sources = verify_core.checks_for(many, EVIDENCE)
    _, pending, _ = verify_core.batches(checks, sources, {})
    assert [len(indices) for _, indices in pending] == [6, 6, 2]


def test_fenced_and_strict_checks_get_their_own_question_and_reason():
    strict = verify_core.Check("body", DRAFT.paragraphs[0], "Fact one.", False)
    fenced = verify_core.Check("argument", DRAFT.paragraphs[0], "Stated facts: Fact one.\nArgument: Bold.", True)
    questions = verify_core.questions_for([strict, fenced])
    assert questions["claim_0"].instructions.startswith("Is EVERY factual assertion")
    assert questions["claim_1"].instructions.startswith("This text is the opinion part")
    assert (
        verify_core.result_from_answer(fenced, "unsupported", 0.2).reason == "It adds a fact absent from the evidence."
    )
    assert verify_core.result_from_answer(strict, "supported", 0.9) == verify_core.ClaimResult("Fact one.", True, 0.9)
