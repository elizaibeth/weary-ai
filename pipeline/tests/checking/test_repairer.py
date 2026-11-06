import json

from agent.checking import repairer
from agent.checking.verify_core import ClaimResult
from agent.evidence.packet import EvidencePacket, Source, source_passages
from agent.writing.article import Citation, Draft, Paragraph


def _draft() -> Draft:
    return Draft(
        title="T",
        description="d",
        paragraphs=(
            Paragraph("This claim is fine.", (1,)),
            Paragraph("This claim is wrong.", (1,)),
            Paragraph("This one is also fine.", (1,)),
        ),
        sources=(Citation(id=1, title="Example", url="https://example.com"),),
        category="Models",
        tags=("x",),
        event_date="2026-09-25",
        image_prompt="p",
        image_alt="a",
        image_caption="c",
        why_today="w",
    )


def _evidence() -> EvidencePacket:
    return EvidencePacket(sources=(Source("https://example.com", "primary", "A fact."),), fact_ledger=("A fact.",))


def test_repair_returns_draft_unchanged_when_nothing_is_flagged():
    d = _draft()
    repaired = repairer.repair(d, [], _evidence())
    assert repaired == d


def test_repair_only_changes_the_flagged_paragraph():
    d = _draft()
    issues = [
        ClaimResult("This claim is fine.", verified=True, confidence=1.0),
        ClaimResult("This claim is wrong.", verified=False, confidence=0.1),
        ClaimResult("This one is also fine.", verified=True, confidence=1.0),
    ]

    def client(prompt):
        return json.dumps(
            {
                "unsupported_assertions": [{"assertion_ids": [1], "reason": "The source only supports a fact."}],
                "replacement": "This claim is now correct.",
                "passage_ids": [source_passages(_evidence().sources[0])[0].id],
            }
        )

    repaired = repairer.repair(d, issues, _evidence(), client=client)
    texts = [p.text for p in repaired.paragraphs]
    assert texts == ["This claim is fine.", "This claim is now correct.", "This one is also fine."]
    # Unaffected paragraphs are the exact same objects, not re-sent to a model.
    assert repaired.paragraphs[0] is d.paragraphs[0]
    assert repaired.paragraphs[2] is d.paragraphs[2]


def test_repair_removes_a_paragraph_when_replacement_is_empty():
    d = _draft()
    issues = [ClaimResult("This claim is wrong.", verified=False, confidence=0.1)]

    def client(prompt):
        return json.dumps(
            {
                "unsupported_assertions": [{"assertion_ids": [1], "reason": "No support."}],
                "replacement": "",
                "passage_ids": [],
            }
        )

    repaired = repairer.repair(d, issues, _evidence(), client=client)
    texts = [p.text for p in repaired.paragraphs]
    assert texts == ["This claim is fine.", "This one is also fine."]


def test_repair_never_receives_secondary_reporting():
    packet = EvidencePacket(
        sources=(
            Source("https://example.com", "primary", "The court stayed the order."),
            Source("https://news.example", "reporting", "BACKGROUND ONLY: the court upheld the ban."),
        ),
        fact_ledger=("The court stayed the order.", "BACKGROUND ONLY: the court upheld the ban."),
    )
    prompts = []

    def client(prompt):
        prompts.append(prompt)
        return json.dumps({"replacement": ""})

    repairer.repair(_draft(), [ClaimResult("This claim is wrong.", False, 0)], packet, client)
    assert "BACKGROUND ONLY" not in prompts[0]
    assert "https://example.com" in prompts[0]


def test_repair_updates_citation_to_the_source_of_the_supporting_passage():
    packet = EvidencePacket(
        sources=(
            _evidence().sources[0],
            Source("https://court.example/order", "primary", "The court stayed the order."),
        ),
        fact_ledger=("A fact.", "The court stayed the order."),
    )
    payload = {
        "unsupported_assertions": [{"assertion_ids": [1], "reason": "The ruling only grants a stay."}],
        "replacement": "The court stayed the order.",
        "passage_ids": [source_passages(packet.sources[1])[0].id],
    }
    result = repairer.repair(
        _draft(), [ClaimResult("This claim is wrong.", False, 0)], packet, lambda prompt: json.dumps(payload)
    )
    assert result.paragraphs[1].source_ids == (2,)
    assert result.sources[-1].url == "https://court.example/order"


def test_repair_rejects_a_fabricated_passage_id():
    payload = {
        "unsupported_assertions": [{"assertion_ids": [1], "reason": "Missing evidence."}],
        "replacement": "The court upheld the ban.",
        "passage_ids": ["invented-passage"],
    }
    original = _draft()
    result = repairer.repair(
        original, [ClaimResult("This claim is wrong.", False, 0)], _evidence(), lambda prompt: json.dumps(payload)
    )
    assert result == original


def test_repaired_citations_and_passages_reach_the_independent_verifier():
    from dataclasses import replace

    from agent.checking import verifier

    original = replace(_draft(), paragraphs=(Paragraph("The court upheld the ban.", (1,)),))
    packet = EvidencePacket(
        sources=(
            Source("https://example.com", "primary", "The case is pending."),
            Source(
                "https://court.example/order", "primary", "The court stayed the order. The merits remain undecided."
            ),
        ),
        fact_ledger=("The case is pending.", "The court stayed the order. The merits remain undecided."),
    )
    payload = {
        "unsupported_assertions": [{"assertion_ids": [1], "reason": "The order is a stay, not a merits ruling."}],
        "replacement": "The court stayed the order.",
        "passage_ids": [source_passages(packet.sources[1])[0].id],
    }
    repaired = repairer.repair(
        original, [ClaimResult(original.paragraphs[0].text, False, 0)], packet, lambda prompt: json.dumps(payload)
    )
    states = []

    def system_one(state, questions):
        states.append(state)
        assert "The court stayed the order." in state["evidence"]
        assert "The merits remain undecided." in state["evidence"]
        assert "The case is pending." not in state["evidence"]
        assert "Proposed supporting passage" in state["evidence"]
        assert "Source 2" in state["evidence"]
        assert "The court stayed the order." in questions["claim_0"].instructions
        answer = type("Answer", (), {"choice": "supported", "probabilities": {"supported": 0.99}})()
        return type("Response", (), {"answers": {"claim_0": answer}})()

    assert verifier.passed(verifier.verify(repaired, packet, system_one))
    assert len(states) == 1
    assert [c.url for c in repaired.sources] == ["https://court.example/order"]


def test_repair_skips_model_when_only_secondary_evidence_exists():
    def forbidden(prompt):
        raise AssertionError("No usable primary evidence: must not call a model")

    packet = EvidencePacket((Source("https://news.example", "reporting", "A fact."),), ("A fact.",))
    original = _draft()
    assert repairer.repair(original, [ClaimResult("This claim is wrong.", False, 0)], packet, forbidden) is original


def test_malformed_repairs_cannot_silently_delete_a_paragraph():
    original = _draft()
    issues = [ClaimResult("This claim is wrong.", False, 0)]
    responses = ["{}", "null", "[]", "{invalid", json.dumps({"replacement": ""})]
    for response in responses:
        assert repairer.repair(original, issues, _evidence(), lambda prompt, response=response: response) is original


def test_repair_rejects_invalid_diagnoses_and_citations():
    original = _draft()
    issues = [ClaimResult("This claim is wrong.", False, 0)]
    valid = {
        "unsupported_assertions": [{"assertion_ids": [1], "reason": "Not supported."}],
        "replacement": "A fact.",
        "passage_ids": [source_passages(_evidence().sources[0])[0].id],
    }
    changes = [
        {"unsupported_assertions": []},
        {"unsupported_assertions": [{"text": "Invented original assertion.", "reason": "Unsupported."}]},
        {"unsupported_assertions": [{"assertion_ids": [1], "reason": ""}]},
        {"passage_ids": []},
        {"passage_ids": ["invented"]},
        {"passage_ids": [True]},
        {"passage_ids": [""]},
        {"replacement": ""},
    ]
    for change in changes:
        response = json.dumps(valid | change)
        assert repairer.repair(original, issues, _evidence(), lambda prompt, response=response: response) is original


def test_summary_repairs_update_passage_references_and_cannot_delete_required_fields():
    from dataclasses import replace

    pid = source_passages(_evidence().sources[0])[0].id
    original = replace(_draft(), claim_passages=(("title", (pid,)),))
    issues = [ClaimResult("T", False, 0, field="title")]
    payload = {
        "unsupported_assertions": [{"assertion_ids": [1], "reason": "Unsupported headline."}],
        "replacement": "A fact.",
        "passage_ids": [pid],
    }
    corrected = repairer.repair(original, issues, _evidence(), lambda prompt: json.dumps(payload))
    assert corrected.title == "A fact."
    assert corrected.paragraphs == original.paragraphs
    assert corrected.claim_passages == (("title", (pid,)),)
    payload.update(replacement="", passage_ids=[])
    assert repairer.repair(original, issues, _evidence(), lambda prompt: json.dumps(payload)) is original


def test_unknown_passage_diagnostic_identifies_returned_id(caplog):
    caplog.set_level("INFO")
    payload = {
        "unsupported_assertions": [{"assertion_ids": [1], "reason": "Unsupported."}],
        "replacement": "A fact.",
        "passage_ids": ["invented-id"],
    }
    original = _draft()
    result = repairer.repair(
        original, [ClaimResult("This claim is wrong.", False, 0)], _evidence(), lambda p: json.dumps(payload)
    )
    assert result is original
    assert "invented-id" in caplog.text


def test_short_repair_selectors_resolve_to_snapshot_ids_before_verification():
    from dataclasses import replace

    from agent.checking import verifier

    packet = EvidencePacket(
        (
            Source("https://example.com", "primary", "The case is pending."),
            Source(
                "https://court.example/order", "primary", "The court stayed the order. The merits remain undecided."
            ),
        ),
        (),
    )
    original = replace(_draft(), paragraphs=(Paragraph("The court upheld the ban.", (1,)),))
    pid = source_passages(packet.sources[1])[0].id

    def client(prompt):
        assert 'Allowed passage_ids: ["P1", "P2"]' in prompt
        assert "Passage P2 |" in prompt
        assert pid not in prompt
        return json.dumps(
            {
                "unsupported_assertions": [{"assertion_ids": [1], "reason": "This was a stay, not a merits ruling."}],
                "replacement": "The court stayed the order.",
                "passage_ids": ["P2"],
            }
        )

    corrected = repairer.repair(original, [ClaimResult(original.paragraphs[0].text, False, 0)], packet, client)
    assert corrected.paragraphs[0].passage_ids == (pid,)
    assert corrected.paragraphs[0].source_ids == (2,)

    def system_one(state, questions):
        assert pid in state["evidence"]
        assert "The merits remain undecided." in state["evidence"]
        assert "The case is pending." not in state["evidence"]
        answer = type("Answer", (), {"choice": "supported", "probabilities": {"supported": 1.0}})()
        return type("Response", (), {"answers": {key: answer for key in questions}})()

    assert verifier.passed(verifier.verify(corrected, packet, system_one))


def test_short_selector_outside_catalog_is_rejected(caplog):
    caplog.set_level("INFO")
    original = _draft()
    payload = {
        "unsupported_assertions": [{"assertion_ids": [1], "reason": "Unsupported."}],
        "replacement": "A fact.",
        "passage_ids": ["P99"],
    }
    corrected = repairer.repair(
        original, [ClaimResult("This claim is wrong.", False, 0)], _evidence(), lambda p: json.dumps(payload)
    )
    assert corrected is original
    assert "P99" in caplog.text


def test_summary_repair_retries_length_failure_before_accepting():
    from dataclasses import replace

    packet = _evidence()
    pid = source_passages(packet.sources[0])[0].id
    original = replace(
        _draft(), image_caption="Unsupported caption about a court ruling", claim_passages=(("image_caption", (pid,)),)
    )
    prompts = []

    def client(prompt):
        prompts.append(prompt)
        return json.dumps(
            {
                "unsupported_assertions": [{"assertion_ids": [1], "reason": "Scope not established."}],
                "replacement": "word " * 40 if len(prompts) == 1 else "Court leaves the merits of the case undecided",
                "passage_ids": ["P1"],
            }
        )

    result = repairer.repair(
        original, [ClaimResult(original.image_caption, False, 0, field="image_caption")], packet, client
    )
    assert result.image_caption == "Court leaves the merits of the case undecided"
    assert len(prompts) == 2
    assert "40 words" in prompts[1] and "5-12" in prompts[1]
    assert result.claim_passages == original.claim_passages


def test_repeated_overlong_summary_repair_keeps_original_with_bounded_calls():
    from dataclasses import replace

    packet = _evidence()
    pid = source_passages(packet.sources[0])[0].id
    original = replace(_draft(), description="Original description", claim_passages=(("description", (pid,)),))
    calls = []

    def client(prompt):
        calls.append(prompt)
        return json.dumps(
            {
                "unsupported_assertions": [{"assertion_ids": [1], "reason": "Missing support."}],
                "replacement": "word " * 75,
                "passage_ids": ["P1"],
            }
        )

    result = repairer.repair(
        original, [ClaimResult(original.description, False, 0, field="description")], packet, client
    )
    assert result is original
    assert len(calls) == 2


def test_citation_supplement_changes_only_failed_valid_references_within_cited_sources():
    from dataclasses import replace

    from agent.evidence.grounding import primary_sources, resolve_passages
    from agent.evidence.packet import Passage

    packet = EvidencePacket(
        (
            Source(
                "https://example.com",
                "primary",
                "Opening. Outcome.",
                passages=(Passage("opening", "Opening.", "Opening."), Passage("outcome", "Outcome.", "Outcome.")),
            ),
            Source("https://uncited.example", "primary", "Unrelated evidence."),
        ),
        (),
    )
    original = _draft()
    sources = primary_sources(original, packet)
    good = resolve_passages("Already supported.", ("opening",), sources)
    failed = resolve_passages("Needs the outcome.", ("opening",), sources)
    invalid = Paragraph("Invalid reference.", (1,), passage_ids=("invented",))
    original = replace(original, paragraphs=(good, failed, invalid))
    issues = [ClaimResult(good.text, True, 1), ClaimResult(failed.text, False, 0), ClaimResult(invalid.text, False, 0)]
    proposed = repairer.supplement_citations(original, issues, packet)
    assert proposed.body_text == original.body_text
    assert proposed.paragraphs[0] == good
    assert proposed.paragraphs[1].passage_ids == ("opening", "outcome")
    assert proposed.paragraphs[1].source_ids == (1,)
    assert proposed.paragraphs[2] == invalid
    assert proposed.sources == original.sources
    assert repairer.supplement_citations(proposed, issues, packet) is proposed


def test_an_opinion_title_repair_keeps_the_verdict_not_a_news_summary():
    # Oct 10 trial: "Google is selling agents before they are ready" was repaired
    # to "Google is introducing agents and agentic features".
    from dataclasses import replace

    pid = source_passages(_evidence().sources[0])[0].id
    payload = {"unsupported_assertions": [], "replacement": "A fact.", "passage_ids": [pid]}
    issues = [ClaimResult("T", False, 0, field="title")]
    prompts: list[str] = []

    def client(prompt):
        prompts.append(prompt)
        return json.dumps(payload)

    column = replace(_draft(), category="Opinion", claim_passages=(("title", (pid,)),))
    repairer.repair(column, issues, _evidence(), client)
    repairer.repair(replace(column, category="Models"), issues, _evidence(), client)
    assert "keep it a sharp verdict" in prompts[0] and "plain and measured" not in prompts[0]
    assert "keep it a sharp verdict" not in prompts[1] and "plain and measured" in prompts[1]


def test_argument_rewrite_keeps_the_original_when_the_reply_is_unusable():
    from dataclasses import replace

    column = replace(_draft(), paragraphs=(Paragraph("A fact.", (1,), argument="It also bought a chip maker."),))
    issues = [ClaimResult("It also bought a chip maker.", False, 0, "adds a purchase", field="argument")]
    prompts: list[str] = []
    unchanged = repairer.repair_arguments(column, issues, lambda p: prompts.append(p) or "not json")
    assert unchanged.paragraphs[0].argument == "It also bought a chip maker."
    assert "adds a purchase" in prompts[0] and "Stated facts: A fact." in prompts[0]
    rewritten = repairer.repair_arguments(column, issues, lambda p: json.dumps({"argument": "That looks like a bet."}))
    assert rewritten.paragraphs[0].argument == "That looks like a bet."
