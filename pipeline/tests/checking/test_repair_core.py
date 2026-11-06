"""The pure repair core: prompts, reply checks and applying fixes, with no model (`agent.repair_core`)."""

import json

import pytest

from agent.checking import repair_core
from agent.evidence.grounding import primary_sources
from agent.evidence.packet import EvidencePacket, Source, source_passages
from agent.writing.article import Citation, Draft, Paragraph

EVIDENCE = EvidencePacket(sources=(Source("https://example.com", "primary", "A fact."),), fact_ledger=("A fact.",))
DRAFT = Draft(
    title="T",
    description="d",
    paragraphs=(Paragraph("This claim is fine.", (1,)), Paragraph("This claim is wrong.", (1,))),
    sources=(Citation(id=1, title="Example", url="https://example.com"),),
    category="Models",
    tags=("x",),
    event_date="2026-09-25",
    image_prompt="p",
    image_alt="a",
    image_caption="c",
    why_today="w",
)
SOURCES = primary_sources(DRAFT, EVIDENCE)
ALIASES = repair_core.passage_aliases(SOURCES)
PID = source_passages(EVIDENCE.sources[0])[0].id


def _reply(replacement, passage_ids):
    diagnosis = [{"assertion_ids": [1], "reason": "Not in the source."}]
    return json.dumps({"unsupported_assertions": diagnosis, "replacement": replacement, "passage_ids": passage_ids})


def test_aliases_are_short_selectors_for_existing_passages():
    assert ALIASES == {"P1": PID}


def test_a_reply_using_a_short_selector_resolves_to_the_passage():
    proposed, diagnoses = repair_core.parse_repair_reply(
        _reply("A fact.", ["P1"]), "body", DRAFT.paragraphs[1], SOURCES, ALIASES
    )
    assert proposed is not None and proposed.passage_ids == (PID,)
    assert diagnoses == [("This claim is wrong.", "Not in the source.")]


@pytest.mark.parametrize(
    ("field", "reply", "message"),
    [
        ("body", _reply("A fact.", ["P9"]), "Unknown passage IDs"),
        ("body", _reply("A fact.", []), "no passage IDs"),
        ("title", _reply("", []), "cannot be removed"),
    ],
)
def test_unusable_repair_replies_are_rejected(field, reply, message):
    with pytest.raises(ValueError, match=message):
        repair_core.parse_repair_reply(reply, field, DRAFT.paragraphs[1], SOURCES, ALIASES)


def test_a_body_paragraph_mapped_to_none_is_removed_and_the_rest_kept():
    repaired = repair_core.apply_repairs(DRAFT, SOURCES, {("body", "This claim is wrong."): None})
    assert [p.text for p in repaired.paragraphs] == ["This claim is fine."]
    assert repair_core.apply_repairs(DRAFT, SOURCES, {}) is DRAFT


def test_summary_length_problems_are_named_exactly():
    short = Paragraph("Too short.", (1,))
    assert repair_core.length_problem("description", short) == "description has 2 words; it must contain 15-40 words."
    assert repair_core.length_problem("body", short) is None


def test_an_argument_rewrite_reply_has_its_dashes_replaced():
    assert repair_core.parse_argument_reply('{"argument": "Bold — and wrong."}') == "Bold, and wrong."
    with pytest.raises(KeyError):
        repair_core.parse_argument_reply('{"text": "x"}')
