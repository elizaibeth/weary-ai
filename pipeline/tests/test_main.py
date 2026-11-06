from datetime import date

import pytest

from agent import __main__ as cli


def test_main_uses_recent_window_by_default(monkeypatch, tmp_path):
    calls = {}

    def fake_run(root, day, recent_window=False, live=None, story_url=None):
        calls["day"] = day
        calls["recent_window"] = recent_window
        return tmp_path / "some-slug"

    monkeypatch.setattr(cli, "run", fake_run)
    exit_code = cli.main([])
    assert exit_code == 0
    assert calls["day"] == date.today().isoformat()
    assert calls["recent_window"] is True


def test_main_uses_historical_mode_with_date_flag(monkeypatch, tmp_path):
    calls = {}

    def fake_run(root, day, recent_window=False, live=None, story_url=None):
        calls["day"] = day
        calls["recent_window"] = recent_window
        return tmp_path / "some-slug"

    monkeypatch.setattr(cli, "run", fake_run)
    exit_code = cli.main(["--date", "2026-09-01"])
    assert exit_code == 0
    assert calls["day"] == "2026-09-01"
    assert calls["recent_window"] is False


def test_main_treats_no_story_as_a_normal_exit_not_an_error(monkeypatch):
    def fake_run(root, day, recent_window=False, live=None, story_url=None):
        raise ValueError("No candidates available for 2026-09-01")

    monkeypatch.setattr(cli, "run", fake_run)
    exit_code = cli.main(["--date", "2026-09-01"])
    assert exit_code == 0


def test_main_lets_an_unexpected_error_propagate(monkeypatch):
    def fake_run(root, day, recent_window=False, live=None, story_url=None):
        raise RuntimeError("something genuinely broke")

    monkeypatch.setattr(cli, "run", fake_run)
    with pytest.raises(RuntimeError):
        cli.main(["--date", "2026-09-01"])


@pytest.mark.parametrize("request_limit,expected", [("6", "2"), ("1", "1"), ("0", "0")])
@pytest.mark.parametrize("selection", [[], ["--url", "https://wired.com/story/example"]])
def test_local_mode_overrides_live_notifications_and_image_spending(
    monkeypatch, tmp_path, request_limit, expected, selection
):
    import os

    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://example.test/webhook")
    monkeypatch.setenv("WEARY_GENERATE_IMAGES", "true")
    monkeypatch.setenv("WEARY_AUTO_PUBLISH", "true")
    monkeypatch.setenv("WEARY_SEARCH_REQUESTS_PER_RUN", request_limit)
    calls = []

    def fake_run(root, day, recent_window, live, story_url=None):
        calls.append(day)
        assert live is False
        assert recent_window is False
        assert os.environ["SLACK_WEBHOOK_URL"] == ""
        assert os.environ["WEARY_GENERATE_IMAGES"] == "false"
        assert os.environ["WEARY_SEARCH_REQUESTS_PER_RUN"] == expected
        return tmp_path / "draft"

    monkeypatch.setattr(cli, "run", fake_run)
    assert cli.main(["--date", "2026-09-28", "--local", *selection]) == 0
    assert calls == ["2026-09-28"]


def test_manual_url_and_date_are_forwarded_without_survey(monkeypatch, tmp_path):
    def fake_run(root, day, recent_window, live, story_url):
        assert day == "2026-09-27"
        assert story_url == "https://wired.com/story/example"
        assert recent_window is False
        return tmp_path / "story"

    monkeypatch.setattr(cli, "run", fake_run)
    assert cli.main(["--url", "https://wired.com/story/example", "--date", "2026-09-27"]) == 0


def test_manual_failure_exits_nonzero(monkeypatch):
    def fake_run(*args, **kwargs):
        raise ValueError("Manual page has no headline")

    monkeypatch.setattr(cli, "run", fake_run)
    assert cli.main(["--url", "https://wired.com/story/example"]) == 1


def test_invalid_edition_date_stops_before_pipeline(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid date must be rejected before pipeline work")

    monkeypatch.setattr(cli, "run", forbidden)
    with pytest.raises(SystemExit) as error:
        cli.main(["--url", "https://wired.com/story/example", "--date", "2026-09-31"])
    assert error.value.code == 2


def test_main_exits_non_zero_when_a_credentials_error_stops_the_run(monkeypatch):
    from agent.daily import RunStopped

    def fake_run(root, day, recent_window=False, live=None, story_url=None):
        raise RunStopped("Stopped: TypeSafe rejected the API key")

    monkeypatch.setattr(cli, "run", fake_run)
    assert cli.main(["--date", "2026-09-01"]) == 1


def test_log_lines_show_level_and_module_and_hide_debug(capsys):
    import logging

    cli._configure_logging()
    try:
        logging.getLogger("agent.daily").info("Publishing (live=%s)...", True)
        logging.getLogger("agent.research.discovery").warning("GDELT: FAILED (%s)", "TimeoutError")
        logging.getLogger("agent.research.discovery").debug("hidden at the default level")
        lines = capsys.readouterr().out.splitlines()
        # %(module)s is the calling module: this test here, "discovery" etc. in the pipeline.
        assert [line.split(maxsplit=2) for line in lines] == [
            ["INFO", "test_main", "Publishing (live=True)..."],
            ["WARNING", "test_main", "GDELT: FAILED (TimeoutError)"],
        ]
    finally:
        logging.getLogger().handlers.clear()  # the handler holds this test's captured stdout
