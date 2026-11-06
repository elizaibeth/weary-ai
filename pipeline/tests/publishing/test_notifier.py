from agent.publishing import notifier
from agent.services import costs
from agent.writing.article import Citation, Draft, Paragraph


def _draft():
    return Draft(
        title="Some Headline",
        description="A one-sentence reason this story matters, long enough to be realistic.",
        paragraphs=(Paragraph("Body text.", (1,)),),
        sources=(Citation(id=1, title="Primary Source", url="https://example.com"),),
        category="Models",
        tags=("x",),
        event_date="2026-09-25",
        image_prompt="p",
        image_alt="a",
        image_caption="c",
        why_today="A plain-enough reason this story was picked over everything else today.",
    )


def test_notify_published_does_nothing_without_a_webhook_url(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    calls = []
    monkeypatch.setattr(notifier, "WebhookClient", lambda url: calls.append(url) or None)
    notifier.notify_published(_draft(), "some-slug", True, costs.RunCosts())
    assert calls == []


def test_notify_published_sends_title_description_and_link(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.example/x")
    sent = {}

    class _FakeClient:
        def __init__(self, url):
            sent["url"] = url

        def send(self, *, text):
            sent["text"] = text

    monkeypatch.setattr(notifier, "WebhookClient", _FakeClient)
    notifier.notify_published(_draft(), "some-slug", True, costs.RunCosts())

    assert sent["url"] == "https://hooks.slack.example/x"
    assert "Some Headline" in sent["text"]
    assert "https://weary.ai/posts/some-slug/" in sent["text"]
    assert "A one-sentence reason this story matters" in sent["text"]
    assert "Published live" in sent["text"]


def test_notify_published_reports_draft_status_when_not_live(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.example/x")
    sent = {}
    monkeypatch.setattr(
        notifier, "WebhookClient", lambda url: type("C", (), {"send": lambda self, *, text: sent.update(text=text)})()
    )
    notifier.notify_published(_draft(), "some-slug", False, costs.RunCosts())
    assert "Saved as draft" in sent["text"]


def test_notify_published_uses_weary_base_url_override(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.example/x")
    monkeypatch.setenv("WEARY_BASE_URL", "https://staging.example.com")
    sent = {}
    monkeypatch.setattr(
        notifier, "WebhookClient", lambda url: type("C", (), {"send": lambda self, *, text: sent.update(text=text)})()
    )
    notifier.notify_published(_draft(), "some-slug", True, costs.RunCosts())
    assert "https://staging.example.com/posts/some-slug/" in sent["text"]


def test_notify_published_includes_cost_breakdown(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.example/x")
    sent = {}
    monkeypatch.setattr(
        notifier, "WebhookClient", lambda url: type("C", (), {"send": lambda self, *, text: sent.update(text=text)})()
    )
    with costs.tracking() as run_costs:
        costs.record_text_usage({"prompt_tokens": 100, "completion_tokens": 50})
        costs.record_text_cost(0.0123)
        costs.record_typesafe(type("U", (), {"input_tokens": 30, "output_tokens": 10})())
        costs.record_image_cost(0.015)
    notifier.notify_published(_draft(), "some-slug", True, run_costs)

    assert "Text model tokens:* 150" in sent["text"]
    assert "Text model cost:* $0.0123" in sent["text"]
    assert "40" in sent["text"]  # typesafe total tokens
    assert "$0.0150" in sent["text"]
    assert "Time:" in sent["text"]


def test_notify_published_never_raises_if_slack_send_fails(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.example/x")

    class _FailingClient:
        def __init__(self, url):
            pass

        def send(self, *, text):
            raise RuntimeError("network down")

    monkeypatch.setattr(notifier, "WebhookClient", _FailingClient)
    notifier.notify_published(_draft(), "some-slug", True, costs.RunCosts())  # must not raise


def test_notify_failure_sends_the_day_and_reason(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.example/x")
    sent = {}
    monkeypatch.setattr(
        notifier, "WebhookClient", lambda url: type("C", (), {"send": lambda self, *, text: sent.update(text=text)})()
    )
    notifier.notify_failure("2026-09-25", "No candidates available", costs.RunCosts())
    assert "2026-09-25" in sent["text"]
    assert "No candidates available" in sent["text"]


def test_notify_published_includes_verification_issues_when_not_live(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.example/x")
    sent = {}
    monkeypatch.setattr(
        notifier, "WebhookClient", lambda url: type("C", (), {"send": lambda self, *, text: sent.update(text=text)})()
    )
    notifier.notify_published(
        _draft(),
        "some-slug",
        False,
        costs.RunCosts(),
        issues=["unverified claim: The sky is green.", "em dash or en dash (a common AI-writing tell)"],
    )
    assert "Why it's not live" in sent["text"]
    assert "The sky is green." in sent["text"]
    assert "em dash" in sent["text"]


def test_notify_published_truncates_a_long_issue_list(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.example/x")
    sent = {}
    monkeypatch.setattr(
        notifier, "WebhookClient", lambda url: type("C", (), {"send": lambda self, *, text: sent.update(text=text)})()
    )
    notifier.notify_published(_draft(), "some-slug", False, costs.RunCosts(), issues=[f"issue {i}" for i in range(8)])
    assert "issue 0" in sent["text"]
    assert "issue 4" in sent["text"]
    assert "issue 7" not in sent["text"]
    assert "3 more" in sent["text"]


def test_notify_published_omits_issues_section_when_live(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.example/x")
    sent = {}
    monkeypatch.setattr(
        notifier, "WebhookClient", lambda url: type("C", (), {"send": lambda self, *, text: sent.update(text=text)})()
    )
    notifier.notify_published(_draft(), "some-slug", True, costs.RunCosts(), issues=[])
    assert "Why it's not live" not in sent["text"]


def test_failure_alert_lists_details_links_the_run_and_marks_it_reported(monkeypatch, tmp_path):
    sent = {}

    class FakeClient:
        def __init__(self, url):
            pass

        def send(self, text):
            sent["text"] = text
            return type("Response", (), {"status_code": 200})()

    marker = tmp_path / ".weary" / "slack-notified"
    monkeypatch.setattr(notifier, "WebhookClient", FakeClient)
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example/x")
    monkeypatch.setenv("WEARY_NOTIFIED_MARKER", str(marker))
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")

    notifier.notify_failure(
        "2026-11-04", "No candidate could be drafted", costs.RunCosts(), details=["A: no_primary_source"]
    )

    assert "*Why:*\n- A: no_primary_source" in sent["text"]
    assert "<https://github.com/owner/repo/actions/runs/42|View run logs>" in sent["text"]
    assert marker.exists()


def test_a_success_message_does_not_mark_the_run_as_reported(monkeypatch, tmp_path):
    # A later step (container build, git push) can still fail after publishing.
    class FakeClient:
        def __init__(self, url):
            pass

        def send(self, text):
            return type("Response", (), {"status_code": 200})()

    marker = tmp_path / "slack-notified"
    monkeypatch.setattr(notifier, "WebhookClient", FakeClient)
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example/x")
    monkeypatch.setenv("WEARY_NOTIFIED_MARKER", str(marker))
    assert notifier._send("Published live") is True
    assert not marker.exists()
