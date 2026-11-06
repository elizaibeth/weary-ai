from agent.evidence.passage_selection import select_order
from agent.evidence.retrieval import Block


def test_separate_opinion_attribution_persists_across_pages_and_changes_at_next_heading():
    blocks = (
        Block("Dissenting opinion filed by Circuit Judge Henderson.", 4),
        Block("The court denies the petition concerning Anthropic.", 4),
        Block("HENDERSON, Circuit Judge, dissenting:", 44),
        Block("My reading of the statute differs.", 45),
        Block("The Anthropic designation concerns a supply chain risk.", 50),
        Block("SMITH, Circuit Judge, concurring:", 51),
        Block("I agree with the result for different reasons.", 52),
    )
    _, _, sections = select_order(blocks, "Anthropic court ruling", "court_document", None)
    assert "Separate opinion" not in sections[0]
    assert sections[2] == sections[3] == sections[4]
    assert "HENDERSON" in sections[4] and "dissenting" in sections[4]
    assert sections[5] == sections[6] != sections[4]
    assert "concurring" in sections[6]


def test_dissent_disposition_cannot_replace_the_courts_disposition():
    blocks = (
        Block("This case concerns Anthropic. We affirm the judgment.", 4),
        Block("Accordingly, we deny the petitions for review.", 43),
        Block("JUSTICE SMITH, dissenting:", 44),
        Block("Anthropic should prevail. I would hold that we reverse this decision.", 45),
    )
    order, reserved, _ = select_order(blocks, "Anthropic court decision", "court_document", None)
    assert order[:2] == [0, 1]
    assert 1 in reserved
