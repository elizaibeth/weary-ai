import json
import re
from pathlib import Path

import pytest

from agent.daily import Deps, run


def _research_client(headlines=("Stub AI story",)):
    def client(day: str) -> str:
        return json.dumps(
            {
                "candidates": [
                    {
                        "headline": h,
                        "url": f"https://openai.com/blog/test-{i}",
                        "evidence_summary": "e",
                        "importance_score": 1.0 - i * 0.1,
                    }
                    for i, h in enumerate(headlines)
                ]
            }
        )

    return client


def _writer_client(prompt: str) -> str:
    headline_match = re.search(r"Candidate: (.+)", prompt)
    headline = headline_match.group(1) if headline_match else "Stub AI story"
    pid = re.search(r"Passage (\S+) \|", prompt).group(1)
    return json.dumps(
        {
            "title": headline,
            "description": (
                "This stub story stands in for a real AI news event during "
                "tests, with enough words in this sentence to clear the "
                "fifteen to forty word validation bound the writer enforces."
            ),
            "category": "Models",
            "tags": ["ai"],
            "event_date": "2026-09-25",
            "image_prompt": "an editorial illustration",
            "image_alt": "An editorial illustration",
            "image_caption": "A placeholder metaphor for the stub story",
            "why_today": "This stub story stands in for whatever made today's real pick worth reading.",
            "claim_passages": {field: [pid] for field in ("title", "description", "why_today", "image_caption")},
            "paragraphs": [
                {
                    "text": (
                        f"{headline}. A stub fact fetched from the source, reported "
                        "here, with enough additional padding text included so that "
                        "this paragraph comfortably clears the minimum word count "
                        "threshold enforced by the writer module's validation pass "
                        "before publishing anything at all to the site."
                    ),
                    "passage_ids": [pid],
                }
            ],
        }
    )


class _Answer:
    def __init__(self, choice="supported", confidence=0.95):
        self.choice = choice
        self.confidence = confidence
        self.probabilities = {choice: confidence}


class _Response:
    def __init__(self, answers: dict):
        self.answers = answers


def _answer_for(name: str, default_choice: str) -> _Answer:
    # The "same_event" question (topical-relevance check) is answered
    # separately from the per-paragraph claim questions, so a stub tuned
    # for claim-verification outcomes doesn't accidentally also fail
    # every draft's relevance check.
    return _Answer("same_event") if name == "same_event" else _Answer(default_choice)


def _all_supported_system_one(state, questions):
    return _Response({name: _answer_for(name, "supported") for name in questions})


def _all_unsupported_system_one(state, questions):
    return _Response({name: _answer_for(name, "unsupported") for name in questions})


def _irrelevant_system_one(state, questions):
    return _Response({name: _Answer("different_event") for name in questions})


def _repair_response(prompt, replacement=""):
    pid = re.search(r"Passage (\S+) \|", prompt).group(1)
    original = prompt.split("Original paragraph: ", 1)[1].split("\nOriginal citation IDs:", 1)[0]
    if "Field: body\n" not in prompt:
        replacement = original
    return json.dumps(
        {
            "unsupported_assertions": [
                {"assertion_ids": [1], "reason": "The source does not establish all these assertions."}
            ],
            "replacement": replacement,
            "passage_ids": [pid] if replacement else [],
        }
    )


def _base_deps(**overrides):
    deps = Deps(
        research_client=_research_client(),
        evidence_fetch=lambda url: (
            "<article><p>Stub AI story. First story. Second story. A stub fact fetched from the source. These details give the full context of the source announcement for testing purposes.</p></article>"
        ),
        writer_client=_writer_client,
        illustrator_client=lambda prompt: b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"0" * 1000,
        verifier_system_one=_all_supported_system_one,
        repairer_client=_repair_response,
    )
    for key, value in overrides.items():
        setattr(deps, key, value)
    return deps


def test_run_produces_a_published_bundle(tmp_path):
    bundle = run(tmp_path, "2026-09-25", deps=_base_deps())
    assert (bundle / "index.md").exists()
    assert (bundle / "cover.webp").exists()
    front_matter = (bundle / "index.md").read_text()
    assert "draft: true" in front_matter


def test_run_passes_previously_used_tags_to_the_writer(tmp_path):
    posts_dir = tmp_path / "content" / "posts" / "earlier-post"
    posts_dir.mkdir(parents=True)
    (posts_dir / "index.md").write_text(
        '---\ntitle: "Earlier post"\ndraft: false\nsource_urls: []\norigin_urls: []\ntags: ["Governance"]\n---\n\nBody.'
    )
    prompts = []

    def writer_client(prompt: str) -> str:
        prompts.append(prompt)
        return _writer_client(prompt)

    run(tmp_path, "2026-09-25", deps=_base_deps(writer_client=writer_client))
    assert "Governance" in prompts[0]


def test_run_forces_a_draft_when_the_article_drifts_off_topic(tmp_path):
    bundle = run(
        tmp_path,
        "2026-09-25",
        deps=_base_deps(verifier_system_one=_irrelevant_system_one),
    )
    front_matter = (bundle / "index.md").read_text()
    assert "draft: true" in front_matter


def test_run_uses_the_run_day_not_the_models_event_date_for_the_page_date(tmp_path):
    # The stub writer client always returns event_date "2026-09-25" - a
    # run for a different day must still publish under that day, since
    # the model's own event_date is free-text extraction from evidence
    # prose and can't be trusted as the page date.
    bundle = run(tmp_path, "2026-09-01", deps=_base_deps())
    front_matter = (bundle / "index.md").read_text()
    assert "date: 2026-09-01" in front_matter


def test_run_uses_the_recent_client_when_recent_window_is_true(tmp_path):
    calls = []

    def recent_client(now):
        calls.append(now)
        return _research_client()(now.date().isoformat())

    bundle = run(
        tmp_path,
        "2026-09-25",
        recent_window=True,
        deps=_base_deps(research_client=None, research_recent_client=recent_client),
    )
    assert len(calls) == 1
    assert (bundle / "index.md").exists()


def test_run_ignores_research_client_when_recent_window_is_true(tmp_path):
    # research_client (day-based) must never be consulted in recent-window
    # mode, even if one happens to be set.
    def fail_if_called(day):
        raise AssertionError("day-based research_client should not be called")

    bundle = run(
        tmp_path,
        "2026-09-25",
        recent_window=True,
        deps=_base_deps(
            research_client=fail_if_called,
            research_recent_client=lambda now: _research_client()(now.date().isoformat()),
        ),
    )
    assert (bundle / "index.md").exists()


def test_run_raises_when_no_candidates_are_found(tmp_path):
    with pytest.raises(ValueError):
        run(
            tmp_path,
            "2026-09-25",
            deps=_base_deps(research_client=lambda p: json.dumps({"candidates": []})),
        )


def test_run_falls_back_to_the_second_candidate_when_the_first_fails_verification(tmp_path):
    def system_one(state, questions):
        answers = {}
        for name, q in questions.items():
            if name == "same_event":
                answers[name] = _Answer("same_event")
                continue
            fails = "First story" in q.instructions
            answers[name] = _Answer("unsupported" if fails else "supported")
        return _Response(answers)

    bundle = run(
        tmp_path,
        "2026-09-25",
        live=True,
        deps=_base_deps(
            research_client=_research_client(("First story", "Second story")),
            verifier_system_one=system_one,
            # An "unfixable" repair keeps the first candidate failing across
            # every attempt, forcing the fallback to the second candidate.
            repairer_client=lambda prompt: _repair_response(prompt, "First story remains unfixable."),
        ),
    )
    front_matter = (bundle / "index.md").read_text()
    assert 'title: "Second story"' in front_matter
    assert "draft: false" in front_matter


def test_run_only_generates_one_image_even_when_falling_back_to_a_later_candidate(tmp_path):
    # Image generation is real per-call spend - a candidate rejected in
    # favour of a later one must never have paid for an image that then
    # gets thrown away.
    def system_one(state, questions):
        answers = {}
        for name, q in questions.items():
            if name == "same_event":
                answers[name] = _Answer("same_event")
                continue
            fails = "First story" in q.instructions
            answers[name] = _Answer("unsupported" if fails else "supported")
        return _Response(answers)

    illustrator_calls = []

    def illustrator_client(prompt):
        illustrator_calls.append(prompt)
        return b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"0" * 1000

    run(
        tmp_path,
        "2026-09-25",
        live=True,
        deps=_base_deps(
            research_client=_research_client(("First story", "Second story")),
            verifier_system_one=system_one,
            illustrator_client=illustrator_client,
            repairer_client=lambda prompt: _repair_response(prompt, "First story remains unfixable."),
        ),
    )
    assert len(illustrator_calls) == 1


def test_run_skips_a_candidate_that_crashes_during_drafting_and_uses_the_next_one(tmp_path):
    def writer_client(prompt: str) -> str:
        if "Candidate: First story" in prompt:
            raise RuntimeError("simulated provider failure")
        return _writer_client(prompt)

    bundle = run(
        tmp_path,
        "2026-09-25",
        live=True,
        deps=_base_deps(
            research_client=_research_client(("First story", "Second story")),
            writer_client=writer_client,
        ),
    )
    front_matter = (bundle / "index.md").read_text()
    assert 'title: "Second story"' in front_matter


def test_run_raises_when_every_candidate_crashes_during_drafting(tmp_path):
    def writer_client(prompt: str) -> str:
        raise RuntimeError("simulated provider failure")

    with pytest.raises(ValueError):
        run(
            tmp_path,
            "2026-09-25",
            deps=_base_deps(
                research_client=_research_client(("First story", "Second story")),
                writer_client=writer_client,
            ),
        )


def test_run_forces_a_draft_when_every_candidate_fails_verification(tmp_path):
    bundle = run(
        tmp_path,
        "2026-09-25",
        live=True,  # even asking for live publishing must not override this
        deps=_base_deps(
            research_client=_research_client(("First story", "Second story")),
            verifier_system_one=_all_unsupported_system_one,
        ),
    )
    front_matter = (bundle / "index.md").read_text()
    assert "draft: true" in front_matter


def test_run_reports_verification_issues_to_slack_when_forced_to_draft(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.example/x")
    sent = {}
    from agent.publishing import notifier

    monkeypatch.setattr(
        notifier, "WebhookClient", lambda url: type("C", (), {"send": lambda self, *, text: sent.update(text=text)})()
    )
    run(
        tmp_path,
        "2026-09-25",
        live=True,
        deps=_base_deps(
            research_client=_research_client(("First story", "Second story")),
            verifier_system_one=_all_unsupported_system_one,
            # A repair that keeps real (still-failing) text, rather than
            # the default empty-string removal, so there's a claim left
            # to report as unverified at the end.
            repairer_client=lambda prompt: _repair_response(prompt, "Still unverifiable content."),
        ),
    )
    assert "Why it's not live" in sent["text"]
    assert "unverified claim" in sent["text"]


def test_run_skips_a_candidate_already_covered_in_the_archive(tmp_path):
    posts_dir = tmp_path / "content" / "posts"
    posts_dir.mkdir(parents=True)
    (posts_dir / "first-story").mkdir()
    (posts_dir / "first-story" / "index.md").write_text('---\ntitle: "First story"\ndraft: false\n---\n\nBody.')

    bundle = run(
        tmp_path,
        "2026-09-25",
        live=True,
        deps=_base_deps(research_client=_research_client(("First story", "Second story"))),
    )
    front_matter = (bundle / "index.md").read_text()
    assert 'title: "Second story"' in front_matter


def test_run_uses_weary_auto_publish_env_var_when_live_is_not_passed(tmp_path, monkeypatch):
    monkeypatch.setenv("WEARY_AUTO_PUBLISH", "true")
    bundle = run(tmp_path, "2026-09-25", deps=_base_deps())
    front_matter = (bundle / "index.md").read_text()
    assert "draft: false" in front_matter


def test_run_defaults_to_draft_when_weary_auto_publish_is_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("WEARY_AUTO_PUBLISH", raising=False)
    bundle = run(tmp_path, "2026-09-25", deps=_base_deps())
    front_matter = (bundle / "index.md").read_text()
    assert "draft: true" in front_matter


def test_run_auto_publish_env_true_still_forces_draft_on_total_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("WEARY_AUTO_PUBLISH", "true")
    bundle = run(
        tmp_path,
        "2026-09-25",
        deps=_base_deps(
            research_client=_research_client(("First story", "Second story")),
            verifier_system_one=_all_unsupported_system_one,
        ),
    )
    front_matter = (bundle / "index.md").read_text()
    assert "draft: true" in front_matter


def test_run_never_publishes_live_when_repair_reintroduces_a_slop_phrase(tmp_path):
    # Verification fails once (triggering repair), the repair's replacement
    # contains a banned slop phrase (an em dash would be auto-fixed by
    # repairer itself, so this uses a defect it doesn't sanitize), and
    # TypeSafe then says the repaired text is supported - the deterministic
    # re-check must still block "live".
    calls = {"n": 0}

    def system_one(state, questions):
        if "same_event" in questions:
            return _Response({"same_event": _Answer("same_event")})
        calls["n"] += 1
        choice = "unsupported" if calls["n"] == 1 else "supported"
        return _Response({name: _Answer(choice) for name in questions})

    bundle = run(
        tmp_path,
        "2026-09-25",
        live=True,
        deps=_base_deps(
            verifier_system_one=system_one,
            repairer_client=lambda prompt: _repair_response(
                prompt, "A repaired claim that is nonetheless a true game-changer for the industry."
            ),
        ),
    )
    front_matter = (bundle / "index.md").read_text()
    assert "draft: true" in front_matter


def test_no_progress_stops_after_one_repair_round(tmp_path, caplog):
    caplog.set_level("INFO")
    calls = []

    def client(prompt):
        calls.append(prompt)
        return _repair_response(prompt, "A paraphrase that still lacks support.")

    bundle = run(
        tmp_path,
        "2026-09-25",
        live=True,
        deps=_base_deps(
            verifier_system_one=_all_unsupported_system_one,
            repairer_client=client,
        ),
    )
    assert len(calls) == 5  # body plus four published summary fields, one round
    assert "draft: true" in (bundle / "index.md").read_text()
    assert "unsupported paragraph count did not improve" in caplog.text


def test_invalid_repair_stops_without_reverifying_unchanged_text(tmp_path, caplog):
    caplog.set_level("INFO")
    calls = []

    def system_one(state, questions):
        calls.append(questions)
        return _all_unsupported_system_one(state, questions)

    bundle = run(
        tmp_path,
        "2026-09-25",
        live=True,
        deps=_base_deps(
            verifier_system_one=system_one,
            repairer_client=lambda prompt: "{}",
        ),
    )
    assert len(calls) == 2  # initial relevance and verification only
    assert "draft: true" in (bundle / "index.md").read_text()
    assert "no valid change and no new evidence" in caplog.text


def test_supported_repair_must_still_report_the_original_event(tmp_path):
    relevance_calls = []
    claim_calls = []

    def system_one(state, questions):
        if "same_event" in questions:
            relevance_calls.append(state)
            return _Response({"same_event": _Answer("same_event" if len(relevance_calls) == 1 else "different_event")})
        claim_calls.append(state)
        choice = "unsupported" if len(claim_calls) == 1 else "supported"
        return _Response({name: _Answer(choice) for name in questions})

    bundle = run(
        tmp_path,
        "2026-09-25",
        live=True,
        deps=_base_deps(
            verifier_system_one=system_one,
            repairer_client=lambda prompt: _repair_response(prompt, "A supported but unrelated background fact."),
        ),
    )
    assert len(relevance_calls) == 2
    assert "draft: true" in (bundle / "index.md").read_text()


def test_repair_can_publish_after_support_and_relevance_both_pass(tmp_path):
    calls = []

    def system_one(state, questions):
        if "same_event" in questions:
            return _Response({"same_event": _Answer("same_event")})
        calls.append(state)
        choice = "unsupported" if len(calls) == 1 else "supported"
        return _Response({name: _Answer(choice) for name in questions})

    bundle = run(
        tmp_path,
        "2026-09-25",
        live=True,
        deps=_base_deps(
            verifier_system_one=system_one,
            repairer_client=lambda prompt: _repair_response(prompt, "A stub fact fetched from the source."),
        ),
    )
    assert len(calls) == 2
    assert "Proposed supporting passage" in calls[1]["evidence"]
    assert "draft: false" in (bundle / "index.md").read_text()


def test_removing_only_body_cannot_publish_supported_metadata(tmp_path):
    def system_one(state, questions):
        if "same_event" in questions:
            return _Response({"same_event": _Answer("same_event")})
        return _Response(
            {
                name: _Answer("unsupported" if "Published field: body." in q.instructions else "supported")
                for name, q in questions.items()
            }
        )

    bundle = run(tmp_path, "2026-09-25", live=True, deps=_base_deps(verifier_system_one=system_one))
    assert "draft: true" in (bundle / "index.md").read_text()


def test_brave_client_and_budget_are_shared_across_candidate_fallbacks(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")
    monkeypatch.setattr("agent.daily.notifier.notify_failure", lambda *args, **kwargs: None)
    clients = []
    requests = []

    def get(*args, **kwargs):
        requests.append(1)
        return b'{"type":"search"}'

    def write_and_verify(candidate, deps, *args, **kwargs):
        clients.append(deps.evidence_search)
        assert deps.evidence_search("same query") == []
        raise ValueError("No evidence for this candidate")

    monkeypatch.setattr("agent.evidence.search._http.get", get)
    monkeypatch.setattr("agent.daily._write_and_verify", write_and_verify)
    deps = Deps(research_client=_research_client(("First story", "Second story")))
    with pytest.raises(ValueError, match="could be drafted"):
        run(tmp_path, "2026-09-25", deps=deps)
    assert len(clients) == 2 and clients[0] is clients[1]
    assert requests == [1]


def test_missing_passage_citations_are_reverified_before_model_rewrites(monkeypatch):
    from agent import daily
    from agent.evidence.packet import EvidencePacket, Passage, Source
    from agent.research.ranking import Candidate

    packet = EvidencePacket(
        (
            Source(
                "https://openai.com/blog/test",
                "primary",
                "Stub story opening. Final disposition.",
                passages=(
                    Passage("opening", "Opening.", "Opening."),
                    Passage("outcome", "Final disposition.", "Final disposition."),
                ),
            ),
        ),
        (),
    )
    monkeypatch.setattr(daily.packet, "gather", lambda *args, **kwargs: packet)
    states = []

    def system_one(state, questions):
        if "same_event" in questions:
            return _all_supported_system_one(state, questions)
        states.append(state)
        choice = "supported" if "Final disposition." in state["evidence"] else "unsupported"
        return _Response({name: _Answer(choice) for name in questions})

    def forbidden(prompt):
        raise AssertionError("Complete existing citations before paying for a rewrite")

    draft, verified, issues = daily._write_and_verify(
        Candidate("id", "Stub AI story", ("https://openai.com/blog/test",), 1),
        _base_deps(verifier_system_one=system_one, repairer_client=forbidden),
    )
    assert verified and not issues
    assert len(states) == 2
    assert draft.paragraphs[0].passage_ids == ("opening", "outcome")
    assert "A stub fact fetched" in draft.body_text


def test_repair_citations_are_supplemented_and_checked_before_another_rewrite(monkeypatch):
    from agent import daily
    from agent.evidence.packet import EvidencePacket, Passage, Source
    from agent.research.ranking import Candidate

    packet = EvidencePacket(
        (
            Source(
                "https://openai.com/blog/test",
                "primary",
                "Stub story opening. Final disposition.",
                passages=(
                    Passage("opening", "Opening.", "Opening."),
                    Passage("outcome", "Final disposition.", "Final disposition."),
                ),
            ),
        ),
        (),
    )
    monkeypatch.setattr(daily.packet, "gather", lambda *args, **kwargs: packet)
    calls = []

    def system_one(state, questions):
        if "same_event" in questions:
            return _all_supported_system_one(state, questions)
        answers = {}
        for key, question in questions.items():
            valid = "Published field: body." not in question.instructions or (
                "Repaired story event." in question.instructions
                and "Opening." in state["evidence"]
                and "Final disposition." in state["evidence"]
            )
            answers[key] = _Answer("supported" if valid else "unsupported")
        return _Response(answers)

    def repair(prompt):
        calls.append(prompt)
        return json.dumps(
            {
                "unsupported_assertions": [{"assertion_ids": [1], "reason": "Incorrect event."}],
                "replacement": "Repaired story event.",
                "passage_ids": ["P2"],
            }
        )

    draft, verified, issues = daily._write_and_verify(
        Candidate("id", "Stub AI story", ("https://openai.com/blog/test",), 1),
        _base_deps(verifier_system_one=system_one, repairer_client=repair),
    )
    assert verified and not issues
    assert len(calls) == 1
    assert draft.paragraphs[0].passage_ids == ("opening", "outcome")


def test_manual_url_bypasses_all_research_but_still_verifies_and_deduplicates(tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("Manual URL must bypass discovery, ranking and unnecessary searches")

    origin = "https://wired.com/story/manual"
    primary = "https://openai.com/blog/test-0"
    content = "<p>Stub AI story. A stub fact fetched from the source. These details give the full context of the source announcement for testing purposes.</p>"

    def fetch(url):
        if url == origin:
            return f'<article><h1>Stub AI story</h1>{content}<a href="{primary}">Official announcement</a></article>'
        assert url == primary
        return f"<article>{content}</article>"

    deps = _base_deps(
        research_client=forbidden, research_recent_client=forbidden, evidence_search=forbidden, evidence_fetch=fetch
    )
    bundle = run(tmp_path, "2026-09-27", story_url=origin, recent_window=True, live=True, deps=deps)
    text = (bundle / "index.md").read_text()
    assert "draft: false" in text
    assert "date: 2026-09-27" in text
    assert f'origin_urls: ["{origin}"]' in text
    assert f'source_urls: ["{primary}"]' in text
    with pytest.raises(ValueError, match="No candidates available"):
        run(tmp_path, "2026-09-27", story_url=origin, deps=deps)


def test_manual_url_cannot_publish_when_claims_fail(tmp_path):
    url = "https://openai.com/blog/manual"
    deps = _base_deps(
        evidence_fetch=lambda u: (
            "<h1>Stub AI story</h1><p>Stub AI story. A stub fact fetched from the source, with enough surrounding context to examine the claim accurately.</p>"
        ),
        verifier_system_one=_all_unsupported_system_one,
        repairer_client=lambda p: "{}",
    )
    bundle = run(tmp_path, "2026-09-27", story_url=url, live=True, deps=deps)
    assert "draft: true" in (bundle / "index.md").read_text()


def test_a_crash_during_discovery_still_sends_a_slack_alert(tmp_path, monkeypatch):
    # Observed Oct 22-Nov 3: a rejected API key crashed ranking with no alert.
    import urllib.error

    sent = []
    monkeypatch.setattr(
        "agent.daily.notifier.notify_failure", lambda day, reason, costs, details=(): sent.append(reason)
    )

    def client(day):
        raise urllib.error.HTTPError("https://api.runware.ai/v1", 401, "Unauthorized", {}, None)

    with pytest.raises(urllib.error.HTTPError):
        run(tmp_path, "2026-09-25", deps=Deps(research_client=client))
    assert sent == [
        "Stopped: Runware rejected the API key: check the RUNWARE_API_KEY secret "
        "(HTTPError: HTTP Error 401: Unauthorized)"
    ]


def test_no_candidates_sends_exactly_one_slack_alert(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "agent.daily.notifier.notify_failure", lambda day, reason, costs, details=(): sent.append(reason)
    )
    with pytest.raises(ValueError, match="No candidates available"):
        run(tmp_path, "2026-09-25", deps=Deps(research_client=lambda day: '{"candidates": []}'))
    assert sent == ["No candidates available for 2026-09-25"]


def test_slack_alert_lists_why_each_candidate_failed(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "agent.daily.notifier.notify_failure",
        lambda day, reason, costs, details=(): sent.append((reason, details)),
    )

    def write_and_verify(candidate, deps, *args, **kwargs):
        raise ValueError(f"no_primary_source: {candidate.headline}")

    monkeypatch.setattr("agent.daily._write_and_verify", write_and_verify)
    with pytest.raises(ValueError, match="could be drafted"):
        run(tmp_path, "2026-09-25", deps=Deps(research_client=_research_client(("First story", "Second story"))))
    reason, details = sent[0]
    assert reason == "No candidate for 2026-09-25 could be drafted at all (2 tried)"
    assert details == (
        "First story: no_primary_source: First story",
        "Second story: no_primary_source: Second story",
    )


def test_a_rejected_verifier_key_stops_the_run_at_the_first_candidate(tmp_path, monkeypatch):
    # Nov 4: a disabled TypeSafe key failed every candidate after paying for its draft.
    import httpx2
    from typesafe_sdk import TypeSafePermissionDeniedError

    from agent.daily import RunStopped

    sent, tried = [], []
    monkeypatch.setattr(
        "agent.daily.notifier.notify_failure", lambda day, reason, costs, details=(): sent.append(reason)
    )

    def write_and_verify(candidate, deps, *args, **kwargs):
        tried.append(candidate.headline)
        raise TypeSafePermissionDeniedError(403, None, httpx2.Headers(), message="Cannot authenticate with the server")

    monkeypatch.setattr("agent.daily._write_and_verify", write_and_verify)
    with pytest.raises(RunStopped):
        run(tmp_path, "2026-09-25", deps=Deps(research_client=_research_client(("First story", "Second story"))))
    assert tried == ["First story"]
    assert sent == [
        "Stopped: TypeSafe rejected the API key: check the TYPESAFE_API_KEY secret "
        "(TypeSafePermissionDeniedError: 403 Cannot authenticate with the server)"
    ]


def _paper(headline="Stub AI story"):
    from agent.research.ranking import Candidate

    return Candidate(
        "2026-09-27-paper-0",
        headline,
        ("https://arxiv.org/abs/2609.00001", "https://arxiv.org/html/2609.00001"),
        0.9,
        "e",
        kind="paper",
    )


def test_sunday_publishes_the_research_paper_of_the_week(tmp_path):
    seen = []
    deps = _base_deps(paper_survey=lambda day: seen.append(day) or [_paper()])
    bundle = run(tmp_path, "2026-09-27", live=True, deps=deps)  # a Sunday
    text = (bundle / "index.md").read_text()
    assert seen == ["2026-09-27"]
    assert 'series: ["Research paper of the week"]' in text
    assert 'categories: ["Research"]' in text
    assert 'origin_urls: ["https://arxiv.org/abs/2609.00001", "https://arxiv.org/html/2609.00001"]' in text


def test_sunday_falls_back_to_news_when_no_paper_has_evidence(tmp_path):
    article = "<article><p>Stub AI story. A stub fact fetched from the source. These details give the full context of the source announcement for testing purposes.</p></article>"

    def fetch(url):
        if "arxiv.org" in url:
            raise ValueError("empty document")
        return article

    deps = _base_deps(paper_survey=lambda day: [_paper()], evidence_fetch=fetch)
    bundle = run(tmp_path, "2026-09-27", live=True, deps=deps)
    text = (bundle / "index.md").read_text()
    assert "series:" not in text
    assert 'origin_urls: ["https://openai.com/blog/test-0"]' in text


def test_weekdays_and_manual_stories_never_survey_papers(tmp_path):
    def forbidden(day):
        raise AssertionError("papers surveyed outside a Sunday edition")

    run(tmp_path / "friday", "2026-09-25", deps=_base_deps(paper_survey=forbidden))
    page = "<article><h1>Stub AI story</h1><p>Stub AI story. A stub fact fetched from the source. These details give the full context of the source announcement for testing purposes.</p></article>"
    run(
        tmp_path / "manual",
        "2026-09-27",
        story_url="https://openai.com/blog/manual",
        deps=_base_deps(paper_survey=forbidden, evidence_fetch=lambda url: page),
    )


def test_a_host_that_refused_access_is_not_retried_for_later_candidates(tmp_path):
    # Nov 2: openai.com returned 403 to Actions for seven candidates in a row.
    import urllib.error

    fetched = []

    def fetch(url):
        fetched.append(url)
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    deps = _base_deps(research_client=_research_client(("First story", "Second story")), evidence_fetch=fetch)
    with pytest.raises(ValueError, match="could be drafted"):
        run(tmp_path, "2026-09-25", deps=deps)
    assert fetched == ["https://openai.com/blog/test-0"]


def _column(headline="Stub AI story"):
    from agent.research.ranking import Candidate

    return Candidate(
        "2026-09-26-opinion",
        headline,
        ("https://weary.ai/posts/first/", "https://weary.ai/posts/second/"),
        1.0,
        "theme",
        kind="opinion",
        parts=(
            ("Stub AI story", ("https://openai.com/blog/one",)),
            ("Stub AI story", ("https://openai.com/blog/two",)),
        ),
    )


def _column_writer(argument=""):
    """The stub writer's draft as a column: four paragraphs of facts and argument."""

    def client(prompt):
        payload = json.loads(_writer_client(prompt))
        first = payload["paragraphs"][0]
        payload["paragraphs"] = [
            {"facts": f"{first['text']} Point {n}.", "argument": argument, "passage_ids": first["passage_ids"]}
            for n in range(1, 5)
        ]
        return json.dumps(payload)

    return client


def test_saturday_publishes_the_opinion_column_with_fenced_verification(tmp_path, monkeypatch):
    from agent.checking import verifier

    modes = []
    real_verify = verifier.verify
    monkeypatch.setattr(
        "agent.daily.verifier.verify",
        lambda *args, **kwargs: modes.append(kwargs.get("opinion")) or real_verify(*args, **kwargs),
    )
    deps = _base_deps(opinion_survey=lambda day: [_column()], writer_client=_column_writer())
    bundle = run(tmp_path, "2026-09-26", live=True, deps=deps)  # a Saturday
    text = (bundle / "index.md").read_text()
    assert 'series: ["Opinion"]' in text and 'categories: ["Opinion"]' in text
    assert 'origin_urls: ["https://weary.ai/posts/first/", "https://weary.ai/posts/second/"]' in text
    assert modes and all(modes)


def test_saturday_falls_back_to_news_when_the_column_has_no_evidence(tmp_path):
    article = "<article><p>Stub AI story. A stub fact fetched from the source. These details give the full context of the source announcement for testing purposes.</p></article>"

    def fetch(url):
        if "/blog/one" in url or "/blog/two" in url:
            raise ValueError("empty document")
        return article

    deps = _base_deps(opinion_survey=lambda day: [_column()], evidence_fetch=fetch)
    text = (run(tmp_path, "2026-09-26", live=True, deps=deps) / "index.md").read_text()
    assert "series:" not in text


def test_no_second_column_for_a_saturday_that_already_has_one(tmp_path):
    def forbidden(day):
        raise AssertionError("opinion surveyed twice for one Saturday")

    posts = tmp_path / "content" / "posts" / "existing-column"
    posts.mkdir(parents=True)
    (posts / "index.md").write_text('---\ntitle: "Old"\ndate: 2026-09-26\ndraft: false\nseries: ["Opinion"]\n---\n')
    run(tmp_path, "2026-09-26", deps=_base_deps(opinion_survey=forbidden))
    run(tmp_path / "friday", "2026-09-25", deps=_base_deps(opinion_survey=forbidden))  # Fridays never survey


class _Answer:
    def __init__(self, choice):
        self.choice = choice
        self.probabilities = {choice: 0.9}


def _fence_rejecting(phrase):
    """A verifier that rejects any claim containing `phrase` and supports the rest."""

    def system_one(state, questions):
        answers = {k: _Answer("unsupported" if phrase in q.instructions else "supported") for k, q in questions.items()}
        return type("R", (), {"answers": answers})()

    return system_one


def _argument_rewriter(rewrite):
    """The stub repairer, answering argument-rewrite prompts with `rewrite`."""
    return lambda prompt: json.dumps({"argument": rewrite}) if '{"argument"' in prompt else _repair_response(prompt)


@pytest.mark.parametrize(
    ("rewrite", "kept"),
    [
        ("That looks like a bet on scale.", "That looks like a bet on scale."),
        # The rewrite still adds the fact, so the argument is removed.
        ("It still secretly bought a chip maker.", None),
    ],
)
def test_an_opinion_argument_that_adds_a_fact_is_rewritten_or_removed(tmp_path, rewrite, kept):
    deps = _base_deps(
        opinion_survey=lambda day: [_column()],
        writer_client=_column_writer("It also secretly bought a chip maker."),
        verifier_system_one=_fence_rejecting("secretly bought"),
        repairer_client=_argument_rewriter(rewrite),
    )
    text = (run(tmp_path, "2026-09-26", live=True, deps=deps) / "index.md").read_text()
    assert 'series: ["Opinion"]' in text and "draft: false" in text
    assert "secretly bought" not in text
    assert "Point 1." in text  # the verified facts stay
    if kept:
        assert kept in text


@pytest.mark.parametrize(
    ("error", "traceback_kept"), [(ValueError("no_primary_source"), False), (KeyError("text"), True)]
)
def test_only_unexpected_candidate_failures_keep_their_traceback(tmp_path, monkeypatch, caplog, error, traceback_kept):
    def write_and_verify(candidate, deps, *args, **kwargs):
        raise error

    monkeypatch.setattr("agent.daily._write_and_verify", write_and_verify)
    with pytest.raises(ValueError, match="could be drafted"):
        run(tmp_path, "2026-09-25", deps=_base_deps())
    [failure] = [r for r in caplog.records if r.getMessage().startswith("FAILED:")]
    assert bool(failure.exc_info) is traceback_kept


def test_every_run_logs_its_ranking_tries_and_outcome(tmp_path):
    run(tmp_path, "2026-09-25", live=True, deps=_base_deps())
    [path] = (tmp_path / "pipeline" / "runs").glob("2026-09-25_*.json")
    record = json.loads(path.read_text())
    assert record["mode"] == "backfill" and record["ranking"][0]["rank"] == 1
    assert record["tries"] and record["tries"][-1]["outcome"] == "verified"
    assert record["outcome"]["live"] is True


def test_a_failed_run_still_logs_why(tmp_path, monkeypatch):
    def write_and_verify(candidate, deps, *args, **kwargs):
        raise ValueError("no_primary_source: skipping candidate before drafting")

    monkeypatch.setattr("agent.daily._write_and_verify", write_and_verify)
    with pytest.raises(ValueError):
        run(tmp_path, "2026-09-25", deps=_base_deps())
    [path] = (tmp_path / "pipeline" / "runs").glob("*.json")
    record = json.loads(path.read_text())
    assert {t["outcome"] for t in record["tries"]} == {"failed"} and "could be drafted" in record["outcome"]["error"]


# The 13 November 2026 Microsoft 365 outage, the edition the pipeline missed:
# with status pages, it publishes from the AI side.
_STATUS_FIXTURES = Path(__file__).parent / "evidence" / "fixtures" / "status"
_OUTAGE_URL = "https://www.wired.com/story/microsoft-365-crawls-back-to-life-after-a-24-hour-outage/"
_OUTAGE_HEADLINE = "Microsoft 365 Crawls Back to Life After a 24-Hour Outage"


def _outage_fetch(url):
    feeds = {
        "https://status.cloud.microsoft/api/posts/m365Consumer": "m365.json",
        "https://status.openai.com/history.rss": "openai.rss",
        "https://status.claude.com/history.rss": "claude.rss",
    }
    if url in feeds:
        return (_STATUS_FIXTURES / feeds[url]).read_text()
    if url == _OUTAGE_URL:
        return "<article><p>Microsoft 365 is recovering after a 24-hour outage.</p></article>"
    return '<?xml version="1.0"?><rss version="2.0"><channel><title>Status</title></channel></rss>'


def _outage_research(day):
    return json.dumps(
        {
            "candidates": [
                {
                    "headline": _OUTAGE_HEADLINE,
                    "url": _OUTAGE_URL,
                    "ai_related": True,
                    "evidence_summary": "OpenAI and Anthropic reported errors in their Microsoft 365 connectors.",
                    "importance_score": 0.7,
                }
            ]
        }
    )


def _ai_lead_writer(prompt):
    """Cites the first passage the outage framing names as showing the AI effect."""
    ai_alias = re.search(r"citing at least one of passages (P\d+)", " ".join(prompt.split())).group(1)
    first = re.search(r"Passage (\S+) \|", prompt).group(1)
    draft = json.loads(_writer_client(prompt).replace(f'"{first}"', f'"{ai_alias}"'))
    return json.dumps(dict(draft, title="Microsoft 365 outage cuts off OpenAI and Anthropic connectors"))


def _outage_deps(**overrides):
    return _base_deps(
        research_client=_outage_research, evidence_fetch=_outage_fetch, writer_client=_ai_lead_writer, **overrides
    )


def test_13_november_outage_publishes_live_led_by_the_ai_effect(tmp_path):
    bundle = run(tmp_path, "2026-11-13", live=True, deps=_outage_deps())
    front_matter = (bundle / "index.md").read_text()
    assert "draft: false" in front_matter
    assert "status.openai.com" in front_matter or "status.claude.com" in front_matter


def test_a_repair_that_moves_the_lead_off_the_ai_effect_is_never_live(tmp_path, monkeypatch, caplog):
    from dataclasses import replace

    from agent import daily
    from agent.checking.verify_core import ClaimResult

    def repair_drops_the_ai_lead(draft, evidence_packet, deps, opinion, title_rule=None):
        # Every claim verifies, but the repaired lead cites only Microsoft's entry.
        microsoft = next(p.id for s in evidence_packet.sources if "status.cloud.microsoft" in s.url for p in s.passages)
        lead = replace(draft.paragraphs[0], passage_ids=(microsoft,))
        return replace(draft, paragraphs=(lead, *draft.paragraphs[1:])), [ClaimResult(lead.text, True, 0.99)], True

    monkeypatch.setattr(daily, "_verify_and_repair", repair_drops_the_ai_lead)
    with caplog.at_level("INFO"):
        bundle = run(tmp_path, "2026-11-13", live=True, deps=_outage_deps())
    assert "draft: true" in (bundle / "index.md").read_text()
    assert "must lead with its effect on AI" in caplog.text
