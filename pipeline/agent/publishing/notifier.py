"""Sends a Slack notification after each `daily.run()` call, via the
official `slack_sdk` WebhookClient. Best-effort throughout: nothing here
ever fails the run itself - no `SLACK_WEBHOOK_URL` means no notification,
and any error sending one is swallowed, not raised.
"""

import logging
import os
from collections.abc import Sequence
from pathlib import Path

from slack_sdk.webhook import WebhookClient

from agent.services.costs import RunCosts
from agent.writing.article import Draft

log = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://weary.ai/"
_MAX_ISSUES_SHOWN = 5
_MAX_DETAILS_SHOWN = 8


def _base_url() -> str:
    return os.environ.get("WEARY_BASE_URL", _DEFAULT_BASE_URL).rstrip("/") + "/"


def _format_cost(run_costs: RunCosts) -> str:
    lines = [f"*Time:* {run_costs.elapsed_seconds():.1f}s"]

    text_total = run_costs.text_prompt_tokens + run_costs.text_completion_tokens
    if text_total:
        lines.append(
            f"*Text model tokens:* {text_total:,} "
            f"({run_costs.text_prompt_tokens:,} prompt / "
            f"{run_costs.text_completion_tokens:,} completion)"
        )
    if run_costs.text_usd:
        lines.append(f"*Text model cost:* ${run_costs.text_usd:.4f}")

    typesafe_total = run_costs.typesafe_input_tokens + run_costs.typesafe_output_tokens
    if typesafe_total:
        lines.append(f"*TypeSafe tokens:* {typesafe_total:,}")

    if run_costs.image_calls:
        cost = f"${run_costs.image_usd:.4f}" if run_costs.image_usd else "not reported"
        calls = run_costs.image_calls
        lines.append(f"*Image cost:* {cost} ({calls} call{'s' if calls != 1 else ''})")

    return "\n".join(lines)


def _run_link() -> str:
    """Link to the GitHub Actions run, when running there."""
    server, repo, run_id = (os.environ.get(k) for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    return f"<{server}/{repo}/actions/runs/{run_id}|View run logs>\n" if server and repo and run_id else ""


def _send(text: str) -> bool:
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        log.info("no SLACK_WEBHOOK_URL set, skipping Slack notification")
        return False
    try:
        response = WebhookClient(webhook_url).send(text=text + _footer())
        log.info("Slack notification sent (status=%s)", response.status_code)
        return response.status_code == 200
    except Exception as e:
        # Notifications are best-effort - never fail the run over one - but
        # a swallowed failure here must still be visible in the run's own
        # log, or a broken webhook looks identical to a working one.
        log.warning("Slack notification FAILED: %s: %s", type(e).__name__, e)
        return False


def _footer() -> str:
    link = _run_link()
    return f"\n{link}" if link else ""


def _format_details(details: Sequence[str]) -> str:
    if not details:
        return ""
    shown = list(details[:_MAX_DETAILS_SHOWN])
    lines = ["*Why:*"] + [f"- {detail}" for detail in shown]
    if len(details) > len(shown):
        lines.append(f"- ...and {len(details) - len(shown)} more (see run logs)")
    return "\n".join(lines) + "\n\n"


def _format_issues(issues: Sequence[str]) -> str:
    if not issues:
        return ""
    shown = list(issues[:_MAX_ISSUES_SHOWN])
    lines = ["*Why it's not live:*"] + [f"- {issue}" for issue in shown]
    remaining = len(issues) - len(shown)
    if remaining > 0:
        lines.append(f"- ...and {remaining} more")
    return "\n".join(lines) + "\n\n"


def notify_published(
    draft: Draft,
    slug: str,
    live: bool,
    run_costs: RunCosts,
    issues: Sequence[str] | None = None,
) -> None:
    url = f"{_base_url()}posts/{slug}/"
    status = "Published live" if live else "Saved as draft (not yet live)"
    text = (
        f"*{status}:* <{url}|{draft.title}>\n"
        f"{draft.description}\n\n"
        f"{_format_issues(issues or [])}"
        f"{_format_cost(run_costs)}"
    )
    _send(text)


def notify_failure(day: str, reason: str, run_costs: RunCosts, details: Sequence[str] = ()) -> None:
    text = f"*No story published for {day}:* {reason}\n\n{_format_details(details)}{_format_cost(run_costs)}"
    marker = os.environ.get("WEARY_NOTIFIED_MARKER")
    if _send(text) and marker:
        # Only a delivered failure alert marks the run as reported, so the
        # workflow's last-resort alert still fires for later step failures.
        try:
            Path(marker).parent.mkdir(parents=True, exist_ok=True)
            Path(marker).touch()
        except OSError as e:
            log.warning("could not write notification marker: %s", e)
