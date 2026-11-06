import json

import pytest

from agent.evidence.packet import EvidencePacket, Source, source_passages
from agent.research.candidate import Candidate
from agent.writing import prompts as writer_prompts
from agent.writing import writer

CANDIDATE = Candidate("id-1", "Some story", ("https://example.com",), 1.0)
EVIDENCE = EvidencePacket(
    sources=(Source("https://example.com", "primary", "The company launched a new model today."),),
    fact_ledger=("The company launched a new model today.",),
)

PID = source_passages(EVIDENCE.sources[0])[0].id


def _client(payload: dict):
    return lambda prompt: json.dumps(payload)


def test_draft_rejects_a_draft_with_no_sources_when_no_primary_source_was_retrieved():
    no_primary_evidence = EvidencePacket(
        sources=(Source("https://reporting.example", "reporting", "A news outlet covered this."),),
        fact_ledger=("A news outlet covered this.",),
    )
    # The model has nothing citable, so an empty sources list is the only
    # honest output - and that must still fail validation, not silently
    # publish an uncited article.
    bad = _valid_payload(sources=[])
    with pytest.raises(ValueError):
        writer.draft(CANDIDATE, no_primary_evidence, client=_client(bad))


def _valid_payload(**overrides):
    payload = {
        "title": "Company launches new model",
        "description": (
            "The company's new model extends its product lineup and arrives as "
            "competitors race to release comparable systems before year end."
        ),
        "category": "Models",
        "tags": ["ai"],
        "event_date": "2026-09-25",
        "image_prompt": "an editorial illustration",
        "image_alt": "An editorial illustration of a launch",
        "image_caption": "A rocket rising past a company logo",
        "why_today": "This launch is the clearest sign yet of a shift in how the company competes.",
        "claim_passages": {field: [PID] for field in ("title", "description", "why_today", "image_caption")},
        "paragraphs": [
            {
                "text": (
                    "The company launched a new model today, according to sources "
                    "familiar with the matter, extending a run of product "
                    "announcements this quarter. The launch follows several months "
                    "of internal testing and comes as competitors race to release "
                    "comparable systems of their own before the end of the year."
                ),
                "passage_ids": [PID],
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_draft_passes_existing_tags_to_the_prompt_so_the_model_can_reuse_them():
    prompts = []

    def client(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps(_valid_payload())

    writer.draft(CANDIDATE, EVIDENCE, client, existing_tags=("Governance", "Anthropic"))
    assert "Governance, Anthropic" in prompts[0]


def test_draft_produces_all_required_fields():
    d = writer.draft(CANDIDATE, EVIDENCE, client=_client(_valid_payload()))
    assert d.title
    assert d.category == "Models"
    assert d.tags == ("ai",)
    assert d.event_date == "2026-09-25"
    assert d.image_prompt
    assert d.image_alt
    assert d.image_caption
    assert len(d.paragraphs) == 1
    assert d.paragraphs[0].source_ids == (1,)
    assert d.sources[0].url == "https://example.com"


def test_draft_rejects_a_why_it_matters_section():
    bad = _valid_payload(
        paragraphs=[
            {
                "text": "The company launched a new model today. Why it matters: it changes everything.",
                "passage_ids": [PID],
            }
        ]
    )
    with pytest.raises(ValueError):
        writer.draft(CANDIDATE, EVIDENCE, client=_client(bad))


def test_draft_rejects_a_body_ungrounded_in_evidence():
    bad = _valid_payload(
        paragraphs=[
            {
                "text": (
                    "Completely unrelated sentence about nothing in the evidence at "
                    "all whatsoever, describing an entirely different topic with no "
                    "connection to anything retrieved, padded out here purely so "
                    "this paragraph clears the minimum word count on its own merits."
                ),
                "passage_ids": [PID],
            }
        ]
    )
    with pytest.raises(ValueError):
        writer.draft(CANDIDATE, EVIDENCE, client=_client(bad))


def test_draft_rejects_banned_caption_framing():
    bad = _valid_payload(image_caption="This image represents a rocket launch today")
    with pytest.raises(ValueError):
        writer.draft(CANDIDATE, EVIDENCE, client=_client(bad))


def test_draft_rejects_an_invalid_category():
    bad = _valid_payload(category="Gossip")
    with pytest.raises(ValueError):
        writer.draft(CANDIDATE, EVIDENCE, client=_client(bad))


def test_draft_rejects_a_paragraph_with_no_citation():
    bad = _valid_payload(
        paragraphs=[{"text": "The company launched a new model today, per sources.", "passage_ids": []}]
    )
    with pytest.raises(ValueError):
        writer.draft(CANDIDATE, EVIDENCE, client=_client(bad))


def test_draft_rejects_a_paragraph_citing_an_unknown_source_id():
    bad = _valid_payload(
        paragraphs=[{"text": "The company launched a new model today, per sources.", "passage_ids": ["invented"]}]
    )
    with pytest.raises(ValueError):
        writer.draft(CANDIDATE, EVIDENCE, client=_client(bad))


def test_model_supplied_source_urls_cannot_override_python_citations():
    payload = _valid_payload(sources=[{"id": 1, "title": "Fabricated", "url": "https://fabricated.example"}])
    result = writer.draft(CANDIDATE, EVIDENCE, client=_client(payload))
    assert result.sources[0].url == EVIDENCE.sources[0].url


def test_draft_accepts_a_cited_url_with_extra_tracking_parameters():
    # EVIDENCE's real source is "https://example.com" - a model citing it
    # with a tracking suffix is citing the same real page, not fabricating.
    payload = _valid_payload(
        sources=[{"id": 1, "title": "Example report", "url": "https://example.com?utm_source=newsletter"}]
    )
    d = writer.draft(CANDIDATE, EVIDENCE, client=_client(payload))
    # Stored canonically, not as the model's decorated copy.
    assert d.sources[0].url == "https://example.com"


def test_draft_accepts_a_cited_url_missing_the_www_subdomain():
    # A model citing "casrai.org/x" when the retrieved evidence URL is
    # "www.casrai.org/x" is citing the same real page - evidence.py's own
    # domain matching already treats these hosts as equivalent.
    www_evidence = EvidencePacket(
        sources=(Source("https://www.example.com/story", "primary", "The company launched a new model today."),),
        fact_ledger=("The company launched a new model today.",),
    )
    payload = _valid_payload(sources=[{"id": 1, "title": "Example report", "url": "https://example.com/story"}])
    pid = source_passages(www_evidence.sources[0])[0].id
    payload["paragraphs"][0]["passage_ids"] = [pid]
    payload["claim_passages"] = {field: [pid] for field in ("title", "description", "why_today", "image_caption")}
    d = writer.draft(CANDIDATE, www_evidence, client=_client(payload))
    assert d.sources[0].url == "https://www.example.com/story"


def test_draft_rejects_an_overused_ai_cliche_phrase():
    bad = _valid_payload(
        paragraphs=[
            {
                "text": (
                    "The company launched a new model today, according to sources "
                    "familiar with the matter, calling it a true game-changer in "
                    "an ever-evolving landscape of announcements from major AI labs "
                    "racing to outdo one another this quarter and beyond."
                ),
                "passage_ids": [PID],
            }
        ]
    )
    with pytest.raises(ValueError):
        writer.draft(CANDIDATE, EVIDENCE, client=_client(bad))


def test_draft_rejects_the_article_narrating_its_own_sourcing_method():
    bad = _valid_payload(
        description=(
            "Primary-source analyses describe the company's new model, extending its "
            "product lineup as competitors race to release comparable systems."
        )
    )
    with pytest.raises(ValueError):
        writer.draft(CANDIDATE, EVIDENCE, client=_client(bad))


def test_draft_rejects_a_sensational_headline():
    bad = _valid_payload(title="Company launches shocking new model!")
    with pytest.raises(ValueError):
        writer.draft(CANDIDATE, EVIDENCE, client=_client(bad))


def test_draft_rejects_citing_a_reporting_source_instead_of_a_primary_one():
    mixed_evidence = EvidencePacket(
        sources=(
            Source("https://reporting.example", "reporting", "A news outlet covered the launch today."),
            Source("https://company.example", "primary", "The company launched a new model today."),
        ),
        fact_ledger=(
            "A news outlet covered the launch today.",
            "The company launched a new model today.",
        ),
    )
    # Cites the reporting source (id 1) directly, which is never allowed -
    # only the retrieved primary source (id 2) may ever be cited.
    bad = _valid_payload(
        sources=[
            {"id": 1, "title": "Reporting outlet", "url": "https://reporting.example"},
            {"id": 2, "title": "Company announcement", "url": "https://company.example"},
        ],
        paragraphs=[
            {
                "text": (
                    "A news outlet reported today that the company launched a "
                    "new model, describing the rollout as its biggest yet this year."
                ),
                "passage_ids": [PID],
            },
            {
                "text": (
                    "The company itself confirmed the new model launched today, "
                    "according to its own announcement of the rollout."
                ),
                "source_ids": [2],
            },
        ],
    )
    with pytest.raises(ValueError):
        writer.draft(CANDIDATE, mixed_evidence, client=_client(bad))


def test_draft_rejects_naming_an_uncited_reporting_outlet_in_the_body():
    bad = _valid_payload(
        paragraphs=[
            {
                "text": (
                    "The company launched a new model today, an executive told "
                    "WIRED, extending a run of product announcements this quarter "
                    "and drawing early reactions from several outside observers."
                ),
                "passage_ids": [PID],
            }
        ]
    )
    with pytest.raises(ValueError):
        writer.draft(CANDIDATE, EVIDENCE, client=_client(bad))


def test_draft_allows_an_outlet_names_ordinary_english_homograph_lowercase():
    # "The Conversation" is a real outlet name, but "a live conversation"
    # or "the conversation draws on..." is ordinary English that happens
    # to share the word - only a properly capitalized mention is a real
    # leak of the outlet's name.
    ok = _valid_payload(
        paragraphs=[
            {
                "text": (
                    "The company's new assistant answers questions in a live "
                    "conversation, drawing on information the company itself "
                    "provided, extending a run of product announcements this week "
                    "and following a broader pattern of similar releases from "
                    "competitors racing to add comparable conversational features "
                    "to their own products before the end of the quarter."
                ),
                "passage_ids": [PID],
            }
        ]
    )
    writer.draft(CANDIDATE, EVIDENCE, client=_client(ok))


def test_draft_produces_a_description_field():
    d = writer.draft(CANDIDATE, EVIDENCE, client=_client(_valid_payload()))
    assert d.description


def test_draft_rejects_a_description_that_is_too_short():
    bad = _valid_payload(description="Too short.")
    with pytest.raises(ValueError):
        writer.draft(CANDIDATE, EVIDENCE, client=_client(bad))


def test_draft_produces_a_why_today_field():
    d = writer.draft(CANDIDATE, EVIDENCE, client=_client(_valid_payload()))
    assert d.why_today


def test_draft_rejects_a_why_today_that_is_too_short():
    bad = _valid_payload(why_today="Too short.")
    with pytest.raises(ValueError):
        writer.draft(CANDIDATE, EVIDENCE, client=_client(bad))


def test_draft_replaces_an_em_dash_in_the_description_with_a_comma():
    # An em dash is fixed programmatically (replaced with a comma) rather
    # than rejecting the whole draft and forcing an expensive retry over
    # a single punctuation mark.
    payload = _valid_payload(
        description=(
            "The company's new model — extends its product lineup and "
            "arrives as competitors race to release comparable systems."
        )
    )
    d = writer.draft(CANDIDATE, EVIDENCE, client=_client(payload))
    assert "—" not in d.description
    assert "extends its product lineup" in d.description


def test_draft_replaces_an_em_dash_in_a_paragraph_with_a_comma():
    payload = _valid_payload(
        paragraphs=[
            {
                "text": (
                    "The company launched a new model today — extending a run "
                    "of product announcements this quarter and drawing early "
                    "reactions from several outside observers this week, "
                    "following a broader pattern of similar releases from "
                    "competitors racing to add comparable features to their "
                    "own products before the end of the quarter."
                ),
                "passage_ids": [PID],
            }
        ]
    )
    d = writer.draft(CANDIDATE, EVIDENCE, client=_client(payload))
    assert "—" not in d.paragraphs[0].text
    assert "extending a run" in d.paragraphs[0].text


def test_draft_rejects_an_inline_citation_marker():
    bad = _valid_payload(
        paragraphs=[
            {
                "text": (
                    "The company launched a new model today [1], extending a run "
                    "of product announcements this quarter and drawing early "
                    "reactions from several outside observers this week."
                ),
                "passage_ids": [PID],
            }
        ]
    )
    with pytest.raises(ValueError):
        writer.draft(CANDIDATE, EVIDENCE, client=_client(bad))


def test_secondary_text_never_reaches_the_writer():
    from dataclasses import replace

    mixed = replace(
        EVIDENCE, sources=EVIDENCE.sources + (Source("https://news.example", "reporting", "SECRET BACKGROUND CLAIM"),)
    )
    seen = []

    def client(prompt):
        seen.append(prompt)
        return json.dumps(_valid_payload())

    writer.draft(CANDIDATE, mixed, client)
    assert "SECRET BACKGROUND CLAIM" not in seen[0]
    assert "Passage P1 |" in seen[0]
    assert PID not in seen[0]


def test_each_published_summary_requires_valid_passage_ids():
    for field in ("title", "description", "why_today", "image_caption"):
        data = _valid_payload()
        data["claim_passages"][field] = ["invented"]
        with pytest.raises(ValueError, match="passage ID"):
            writer.draft(CANDIDATE, EVIDENCE, _client(data))


def test_invalid_writer_json_has_an_actionable_failure():
    for raw in ("", "```json\n{}\n```", "null"):
        with pytest.raises(ValueError, match="writer_invalid_json"):
            writer.draft(CANDIDATE, EVIDENCE, lambda prompt, raw=raw: raw)


def test_writer_short_ids_are_resolved_for_body_and_summary_fields():
    payload = _valid_payload()
    payload["paragraphs"][0]["passage_ids"] = ["P1"]
    payload["claim_passages"] = {field: ["P1"] for field in payload["claim_passages"]}
    draft = writer.draft(CANDIDATE, EVIDENCE, client=_client(payload))
    assert draft.paragraphs[0].passage_ids == (PID,)
    assert draft.paragraphs[0].support[0].quote == EVIDENCE.sources[0].text
    assert all(ids == (PID,) for field, ids in draft.claim_passages)


def test_a_rejected_draft_is_retried_once_with_the_rejection_reason():
    bad = _valid_payload(description="Too short.")
    replies = iter([json.dumps(bad), json.dumps(_valid_payload())])
    prompts = []

    def client(prompt):
        prompts.append(prompt)
        return next(replies)

    result = writer.draft(CANDIDATE, EVIDENCE, client)

    assert result.title == "Company launches new model"
    assert len(prompts) == 2
    assert "description must be a plain 15-40 word sentence" in prompts[1]


def test_a_draft_rejected_twice_still_fails():
    prompts = []
    bad = json.dumps(_valid_payload(description="Too short."))
    with pytest.raises(ValueError, match="description"):
        writer.draft(CANDIDATE, EVIDENCE, lambda prompt: prompts.append(prompt) or bad)
    assert len(prompts) == 2


def test_a_paper_candidate_gets_paper_framing_and_the_research_category():
    from dataclasses import replace

    prompts = []
    paper = replace(CANDIDATE, kind="paper")
    result = writer.draft(paper, EVIDENCE, lambda prompt: prompts.append(prompt) or json.dumps(_valid_payload()))
    assert writer_prompts.PAPER_FRAMING in prompts[0]
    assert result.category == "Research"
    assert _valid_payload()["category"] != "Research"  # the override, not the model, set it


def test_echoed_passage_ids_are_removed_from_published_text():
    # gpt-5.4-mini wrote "...validation. [P1][P6]" into paragraphs on Nov 4.
    payload = _valid_payload()
    payload["paragraphs"][0]["text"] = payload["paragraphs"][0]["text"] + " [P1][P1, P2]"
    payload["description"] = payload["description"] + " [P1]"
    result = writer.draft(CANDIDATE, EVIDENCE, _client(payload))
    assert "[P" not in result.paragraphs[0].text and "[P" not in result.description


def _column_payload(**overrides):
    """A payload with the 4-7 paragraphs a column needs."""
    payload = _valid_payload(**overrides)
    first = payload["paragraphs"][0]
    payload["paragraphs"] = [dict(first, text=f"{first['text']} Point {n}.") for n in range(1, 5)]
    return payload


def test_an_opinion_candidate_gets_the_column_voice_and_opinion_category():
    from dataclasses import replace

    prompts = []
    column = replace(CANDIDATE, kind="opinion", headline="The pitch is reach, not capability.")
    result = writer.draft(column, EVIDENCE, lambda prompt: prompts.append(prompt) or json.dumps(_column_payload()))
    assert prompts[0].startswith("Write Weary.ai's Saturday opinion column")
    assert "wire-service reporter" not in prompts[0]
    assert "Thesis to argue: The pitch is reach, not capability." in prompts[0]
    assert "Only the numbered PRIMARY PASSAGES" in prompts[0]  # evidence rules kept
    assert result.category == "Opinion"


def test_an_opinion_draft_gets_two_corrected_retries():
    from dataclasses import replace

    replies = iter(["not json", "still not json", json.dumps(_column_payload())])
    prompts = []
    column = replace(CANDIDATE, kind="opinion")
    writer.draft(column, EVIDENCE, lambda prompt: prompts.append(prompt) or next(replies))
    assert len(prompts) == 3


@pytest.mark.parametrize(
    ("title", "paragraphs", "reason"),
    [
        # Two October columns were published as "Opinion: ..." under the page's own label.
        ("Opinion: AI got easier to buy, not to trust", 4, 'must not start with "Opinion"'),
        ("Google's agent week shows control is still the unfinished product today", 4, "at most 10 words"),
        ("Google is selling AI agents it cannot yet control", 10, "4-7 paragraphs"),
    ],
)
def test_a_column_that_breaks_the_shape_rules_is_retried_with_the_reason(title, paragraphs, reason):
    from dataclasses import replace

    bad = _column_payload(title=title)
    first = bad["paragraphs"][0]
    bad["paragraphs"] = [dict(first, text=f"{first['text']} Point {n}.") for n in range(paragraphs)]
    good = _column_payload(title="Google is selling AI agents it cannot yet control")
    replies = iter([json.dumps(bad), json.dumps(good)])
    prompts = []
    result = writer.draft(replace(CANDIDATE, kind="opinion"), EVIDENCE, lambda p: prompts.append(p) or next(replies))
    assert reason in prompts[1]
    assert result.title == "Google is selling AI agents it cannot yet control"


def test_the_shape_rules_apply_only_to_columns():
    payload = _valid_payload(title="Opinion polling firm reports a long and detailed headline about AI use")
    assert writer.draft(CANDIDATE, EVIDENCE, _client(payload)).title.startswith("Opinion polling")


def test_column_paragraphs_keep_facts_and_argument_separately():
    payload = _valid_payload()
    payload["paragraphs"] = [
        {"facts": p["text"], "argument": "That looks like a bet on scale [P1].", "passage_ids": p["passage_ids"]}
        for p in payload["paragraphs"]
    ]
    result = writer.draft(CANDIDATE, EVIDENCE, _client(payload))
    first = result.paragraphs[0]
    assert first.text == _valid_payload()["paragraphs"][0]["text"]
    assert first.argument == "That looks like a bet on scale."
    assert first.published_text == f"{first.text} {first.argument}"
    assert first.argument in result.body_text
