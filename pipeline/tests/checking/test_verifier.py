from agent.checking import verifier, verify_core
from agent.evidence.packet import _MAX_SOURCE_CHARS, EvidencePacket, Source
from agent.writing.article import Citation, Draft, Paragraph


def _draft(paragraph_texts: list[str]) -> Draft:
    return Draft(
        title="T",
        description="d",
        paragraphs=tuple(Paragraph(text=t, source_ids=(1,)) for t in paragraph_texts),
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
    return EvidencePacket(
        sources=(Source("https://example.com", "primary", "A fact."),),
        fact_ledger=("A fact.",),
    )


def _system_one(answers: dict):
    class _Answer:
        def __init__(self, choice, confidence=0.9):
            self.choice = choice
            self.confidence = confidence
            self.probabilities = {choice: confidence}

    class _Response:
        def __init__(self):
            self.answers = {k: _Answer(v) for k, v in answers.items()}

    def system_one(state, questions):
        return _Response()

    return system_one


def test_verify_flags_exactly_the_unsupported_paragraph():
    draft = _draft(["This is supported.", "This is not supported at all."])
    system_one = _system_one({"claim_0": "supported", "claim_1": "unsupported"})
    results = verifier.verify(draft, _evidence(), system_one=system_one)
    assert results[0].verified is True
    assert results[1].verified is False


def test_verify_passes_a_fully_supported_draft():
    draft = _draft(["This is supported."])
    system_one = _system_one({"claim_0": "supported"})
    results = verifier.verify(draft, _evidence(), system_one=system_one)
    assert verifier.passed(results)


def test_verify_fails_closed_with_no_evidence():
    draft = _draft(["Some claim."])
    results = verifier.verify(draft, None, system_one=_system_one({}))
    assert all(not r.verified for r in results)
    assert verifier.passed(results) is False


def test_passed_is_false_for_empty_results():
    assert verifier.passed([]) is False


def test_verify_batches_paragraphs_into_multiple_calls_when_there_are_many():
    draft = _draft([f"Claim number {i}." for i in range(14)])
    calls = []

    def system_one(state, questions):
        calls.append(len(questions))

        class _Answer:
            choice = "supported"
            confidence = 0.9
            probabilities = {"supported": 0.9}

        class _Response:
            answers = {name: _Answer() for name in questions}

        return _Response()

    results = verifier.verify(draft, _evidence(), system_one=system_one)
    assert len(results) == 14
    assert len(calls) > 1  # more than one batch was needed
    assert all(c <= verify_core.BATCH_SIZE for c in calls)


def test_verify_caps_evidence_text_length_sent_per_call():
    draft = _draft(["A claim."])
    huge_evidence = EvidencePacket(
        sources=(Source("https://example.com", "primary", "x" * 50_000),),
        fact_ledger=("x" * 50_000,),
    )
    seen_lengths = []

    def system_one(state, questions):
        seen_lengths.append(len(state["evidence"]))

        class _Answer:
            choice = "supported"
            confidence = 0.9
            probabilities = {"supported": 0.9}

        class _Response:
            answers = {name: _Answer() for name in questions}

        return _Response()

    verifier.verify(draft, huge_evidence, system_one=system_one)
    assert seen_lengths[0] <= _MAX_SOURCE_CHARS * 2 + 100  # text, context, and labelled source header


def test_verify_ignores_uncited_sources_so_they_cant_crowd_out_a_cited_one():
    # A story can gather more evidence sources than any single paragraph
    # actually cites (e.g. several outbound-link discoveries, only some
    # of which end up used). Under the old whole-packet-then-truncate
    # design, a huge *uncited* source earlier in the ledger could push a
    # cited source's exact wording past the cap before Jev ever saw it.
    draft = Draft(
        title="T",
        description="d",
        paragraphs=(Paragraph(text="A specific claim only the cited source states.", source_ids=(1,)),),
        sources=(Citation(id=1, title="Cited", url="https://cited.example"),),
        category="Models",
        tags=("x",),
        event_date="2026-09-25",
        image_prompt="p",
        image_alt="a",
        image_caption="c",
        why_today="w",
    )
    evidence = EvidencePacket(
        sources=(
            Source("https://uncited.example", "primary", "x" * (_MAX_SOURCE_CHARS * 3)),
            Source("https://cited.example", "primary", "The exact detail only the cited source states."),
        ),
        fact_ledger=(
            "x" * (_MAX_SOURCE_CHARS * 3),
            "The exact detail only the cited source states.",
        ),
    )
    seen_evidence = []

    def system_one(state, questions):
        seen_evidence.append(state["evidence"])

        class _Answer:
            choice = "supported"
            confidence = 0.9
            probabilities = {"supported": 0.9}

        class _Response:
            answers = {name: _Answer() for name in questions}

        return _Response()

    verifier.verify(draft, evidence, system_one=system_one)
    assert "The exact detail only the cited source states." in seen_evidence[0]
    assert "x" * 100 not in seen_evidence[0]


def test_check_relevance_true_when_the_draft_matches_the_original_headline():
    draft = _draft(["The company launched a new model today."])
    system_one = _system_one({"same_event": "same_event"})
    assert verifier.check_relevance("Company launches new model", "e", draft, system_one) is True


def test_check_relevance_false_when_the_draft_drifted_onto_an_unrelated_topic():
    draft = _draft(["A venture capital newsletter changed hands today."])
    system_one = _system_one({"same_event": "different_event"})
    assert verifier.check_relevance("Company launches new model", "e", draft, system_one) is False


def test_check_relevance_passes_headline_summary_and_draft_text_in_state():
    draft = _draft(["The company launched a new model today."])
    seen_state = {}

    def system_one(state, questions):
        seen_state.update(state)

        class _Answer:
            choice = "same_event"
            confidence = 0.9
            probabilities = {"same_event": 0.9}

        class _Response:
            answers = {"same_event": _Answer()}

        return _Response()

    verifier.check_relevance("Company launches new model", "a concrete summary", draft, system_one)
    assert seen_state["original_headline"] == "Company launches new model"
    assert seen_state["original_summary"] == "a concrete summary"
    assert seen_state["article_title"] == draft.title
    assert "launched a new model" in seen_state["article_body"]


def test_verifier_does_not_borrow_another_paragraphs_evidence():
    from dataclasses import replace

    draft = replace(
        _draft(["Alpha claim.", "Beta claim."]),
        paragraphs=(Paragraph("Alpha claim.", (1,)), Paragraph("Beta claim.", (2,))),
        sources=(Citation(1, "Alpha", "https://alpha.example"), Citation(2, "Beta", "https://beta.example")),
    )
    packet = EvidencePacket(
        sources=(
            Source("https://alpha.example", "primary", "Alpha only."),
            Source("https://beta.example", "primary", "Beta only."),
        ),
        fact_ledger=("Alpha only.", "Beta only."),
    )
    calls = []

    def system_one(state, questions):
        calls.append((state["evidence"], [q.instructions for q in questions.values()]))
        return _system_one({name: "supported" for name in questions})(state, questions)

    verifier.verify(draft, packet, system_one)
    for text, questions in calls:
        if any("Alpha claim." in q for q in questions):
            assert "Beta only." not in text
        if any("Beta claim." in q for q in questions):
            assert "Alpha only." not in text


def test_verifier_fails_closed_on_missing_citations_instead_of_using_background():
    from dataclasses import replace

    draft = replace(_draft(["Some claim."]), paragraphs=(Paragraph("Some claim.", (99,)),))
    results = verifier.verify(draft, _evidence(), _system_one({"claim_0": "supported"}))
    assert not verifier.passed(results)


def test_verifier_fails_closed_for_secondary_or_partially_missing_citations():
    from dataclasses import replace

    def forbidden(state, questions):
        raise AssertionError("Invalid citations should fail before calling the model")

    secondary = EvidencePacket((Source("https://example.com", "reporting", "A fact."),), ("A fact.",))
    assert not verifier.passed(verifier.verify(_draft(["A fact."]), secondary, forbidden))
    for ids in [(), (1, 99)]:
        draft = replace(_draft(["A fact."]), paragraphs=(Paragraph("A fact.", ids),))
        assert not verifier.passed(verifier.verify(draft, _evidence(), forbidden))


def test_verifier_does_not_assign_missing_citation_ids_to_uncited_sources():
    from dataclasses import replace

    draft = replace(_draft(["Some claim."]), paragraphs=(Paragraph("Some claim.", (2,)),))
    packet = EvidencePacket(
        _evidence().sources + (Source("https://uncited.example", "primary", "Some claim."),), ("A fact.", "Some claim.")
    )
    assert not verifier.passed(verifier.verify(draft, packet, _system_one({"claim_0": "supported"})))


def test_verifier_keeps_all_cited_sources_instead_of_truncating_the_last_one():
    from dataclasses import replace

    sources = tuple(
        Source(f"https://source{i}.example", "primary", "x" * 7900 + f" Important fact {i}.") for i in range(3)
    )
    draft = replace(
        _draft(["All three important facts."]),
        paragraphs=(Paragraph("All three important facts.", (1, 2, 3)),),
        sources=tuple(Citation(i + 1, str(i), s.url) for i, s in enumerate(sources)),
    )
    seen = []

    def system_one(state, questions):
        seen.append(state["evidence"])
        return _system_one({"claim_0": "supported"})(state, questions)

    verifier.verify(draft, EvidencePacket(sources, tuple(s.text for s in sources)), system_one)
    assert all(f"Important fact {i}." in seen[0] for i in range(3))


def test_verifier_rejects_invalid_support_before_calling_provider():
    from dataclasses import replace

    from agent.writing.article import SupportingPassage

    for support in [(SupportingPassage(1, "Invented quote."),), (SupportingPassage(2, "A fact."),)]:
        draft = replace(_draft(["A fact."]), paragraphs=(Paragraph("A fact.", (1,), support),))
        results = verifier.verify(draft, _evidence(), _system_one({"claim_0": "supported"}))
        assert not verifier.passed(results)
        assert results[0].reason


def test_verifier_preserves_result_order_across_evidence_groups():
    from dataclasses import replace

    draft = replace(
        _draft(["Alpha.", "Beta.", "Gamma."]),
        paragraphs=(Paragraph("Alpha.", (1,)), Paragraph("Beta.", (2,)), Paragraph("Gamma.", (1,))),
        sources=(Citation(1, "A", "https://example.com"), Citation(2, "B", "https://b.example")),
    )
    packet = EvidencePacket(_evidence().sources + (Source("https://b.example", "primary", "B."),), ("A fact.", "B."))

    def system_one(state, questions):
        return _system_one(
            {k: "unsupported" if "Beta." in q.instructions else "supported" for k, q in questions.items()}
        )(state, questions)

    results = verifier.verify(draft, packet, system_one)
    assert [r.claim for r in results] == ["Alpha.", "Beta.", "Gamma."]
    assert [r.verified for r in results] == [True, False, True]
    assert results[1].confidence == 0.0  # never confuse confidence in rejection with support probability


def test_headline_and_why_today_cannot_bypass_verification():
    from dataclasses import replace

    from agent.evidence.packet import source_passages

    pid = source_passages(_evidence().sources[0])[0].id
    draft = replace(
        _draft(["A fact."]),
        title="Unsupported headline",
        why_today="Unsupported significance",
        claim_passages=(("title", (pid,)), ("why_today", (pid,))),
    )

    def system_one(state, questions):
        return _system_one(
            {key: "unsupported" if "Unsupported" in q.instructions else "supported" for key, q in questions.items()}
        )(state, questions)

    results = verifier.verify(draft, _evidence(), system_one)
    assert [r.field for r in results if not r.verified] == ["title", "why_today"]
    assert not verifier.passed(results)


def test_passage_selection_cannot_borrow_other_passages_from_same_source():
    from dataclasses import replace

    from agent.evidence.grounding import primary_sources, resolve_passages
    from agent.evidence.packet import Passage

    packet = EvidencePacket(
        (
            Source(
                "https://example.com",
                "primary",
                "Alpha. Beta.",
                passages=(Passage("alpha", "Alpha.", "Alpha context."), Passage("beta", "Beta.", "Beta context.")),
            ),
        ),
        ("Alpha. Beta.",),
    )
    draft = _draft(["Claim."])
    sources = primary_sources(draft, packet)
    draft = replace(draft, paragraphs=(resolve_passages("Claim.", ("alpha",), sources),))

    def system_one(state, questions):
        assert "Alpha context." in state["evidence"]
        assert "Beta" not in state["evidence"]
        return _system_one({"claim_0": "supported"})(state, questions)

    assert verifier.passed(verifier.verify(draft, packet, system_one))


def test_supported_cache_reuses_only_identical_claim_field_and_evidence():
    from dataclasses import replace

    calls = []
    cache = {}

    def system_one(state, questions):
        calls.append(state)
        return _system_one({key: "supported" for key in questions})(state, questions)

    draft = _draft(["A fact."])
    first = verifier.verify(draft, _evidence(), system_one, supported_cache=cache)
    assert verifier.verify(draft, _evidence(), system_one, supported_cache=cache) == first
    assert len(calls) == 1
    verifier.verify(_draft(["A different claim."]), _evidence(), system_one, supported_cache=cache)
    assert len(calls) == 2
    changed_evidence = EvidencePacket((Source("https://example.com", "primary", "A revised fact."),), ())
    verifier.verify(draft, changed_evidence, system_one, supported_cache=cache)
    assert len(calls) == 3
    invalid = replace(draft, paragraphs=(Paragraph("A fact.", (99,)),))
    assert not verifier.passed(verifier.verify(invalid, _evidence(), system_one, supported_cache=cache))
    assert len(calls) == 3


def _recording_system_one(answer_for):
    seen = []

    class _Answer:
        def __init__(self, choice):
            self.choice = choice
            self.probabilities = {choice: 0.9}

    def system_one(state, questions):
        seen.extend(q.instructions for q in questions.values())
        return type("R", (), {"answers": {k: _Answer(answer_for(q.instructions)) for k, q in questions.items()}})()

    return system_one, seen


def test_opinion_mode_checks_facts_strictly_and_fences_the_argument():
    from dataclasses import replace

    draft = _draft(["Anthropic filed an S-1."])
    draft = replace(
        draft, paragraphs=(replace(draft.paragraphs[0], argument="This looks like a bet on government money."),)
    )
    system_one, seen = _recording_system_one(lambda instructions: "supported")
    results = verifier.verify(draft, _evidence(), system_one=system_one, opinion=True)
    assert [r.field for r in results] == ["body", "argument"]
    assert results[1].claim == "This looks like a bet on government money."
    assert seen[0].startswith("Is EVERY factual assertion")
    assert seen[1].startswith("This text is the opinion part of a column")
    assert "Stated facts: Anthropic filed an S-1." in seen[1]


def test_news_mode_never_fences():
    system_one, seen = _recording_system_one(lambda instructions: "supported")
    verifier.verify(_draft(["A plain fact."]), _evidence(), system_one=system_one)
    assert all(not s.startswith("This text is the opinion part") for s in seen)
