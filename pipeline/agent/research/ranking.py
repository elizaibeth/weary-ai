"""Ranking: a model orders the real headlines that `discovery` found.

This is the shell: it loads the allowlist and run history, calls the model
(one retry per prompt), logs, and falls back to the real headlines unranked if
no reply is usable. Clustering, prompts, checking replies against the real
headlines, averaging and ordering are pure functions in `ranking_core`, so a
reply can never invent a story. `WEARY_RANKING=legacy` restores the ranking
from before November 2026.
"""

import json
import logging
import os
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

from agent.evidence.source_rules import eligible_rule, load_rules
from agent.research.candidate import Candidate
from agent.research.discovery import Headline
from agent.research.ranking_core import (
    LEGACY,
    NEWS_PROMPT,
    PAPER_PROMPT,
    RankingConfig,
    average,
    cluster,
    grounded,
    on_topic,
    opinion_prompt,
    parse_opinion_reply,
    parse_ranking_reply,
    ranking_prompt,
    representatives,
    shuffled,
    to_candidates,
    unranked,
    verify_rates,
)
from agent.services import llm

log = logging.getLogger(__name__)

_RANK_ATTEMPTS = 2
# Each run's ranking and outcomes (written by `daily`); the source of observed pass rates.
RUNS_DIR = Path(__file__).resolve().parents[2] / "runs"
Complete = Callable[[str, str], str]


def config() -> RankingConfig:
    return LEGACY if os.environ.get("WEARY_RANKING", "").strip().lower() == "legacy" else RankingConfig()


def _ask(prompt: str, parse: Callable[[str], object], label: str, complete: Complete | None = None):
    """The first usable parsed reply in `_RANK_ATTEMPTS` model calls, else None."""
    model = os.environ.get("WEARY_RESEARCH_MODEL") or llm.DEFAULT_MODEL
    for attempt in range(1, _RANK_ATTEMPTS + 1):
        try:
            return parse((complete or llm.complete)(prompt, model))
        except (ValueError, KeyError, TypeError) as error:
            log.warning("%s reply %s/%s unusable (%s: %s)", label, attempt, _RANK_ATTEMPTS, type(error).__name__, error)
    return None


def rank_headlines(
    day_label: str,
    real_headlines: list[Headline],
    template: str = NEWS_PROMPT,
    settings: RankingConfig | None = None,
    complete: Complete | None = None,
) -> str:
    """Ranked candidates for these real headlines, as JSON for `candidates_from_json`."""
    settings = settings or config()
    if not real_headlines:
        log.info("no real headlines to rank")
        return json.dumps({"candidates": []})
    rules = load_rules()
    coverage: dict[str, int] = {}
    headlines = real_headlines
    event_of = {h.url: h.url for h in real_headlines}
    if settings.cluster and template is not PAPER_PROMPT:
        groups = cluster(real_headlines)
        reps = representatives(groups, rules)
        headlines = [h for h, _ in reps]
        coverage = {h.url: n for h, n in reps}
        event_of = {member.url: rep.url for group, (rep, _) in zip(groups, reps, strict=True) for member in group}
        log.info("clustered %s headline(s) into %s event(s)", len(real_headlines), len(headlines))
    discovered = [
        {
            "title": h.title,
            "url": h.url,
            "feed": h.feed,
            "published": h.published.isoformat() if h.published else None,
            "official": eligible_rule(h.url, rules) is not None,
            "event": event_of[h.url],
        }
        for h in real_headlines
    ]
    replies = []
    for k in range(max(1, settings.permutations)):
        # The first prompt keeps feed order; later ones shuffle it to cancel position bias.
        order = headlines if k == 0 else shuffled(headlines, f"{day_label}-{k}")
        proposed = _ask(
            ranking_prompt(day_label, order, rules, template, coverage), parse_ranking_reply, "ranking", complete
        )
        if proposed is not None:
            kept = grounded(proposed, headlines)
            if template is not PAPER_PROMPT:
                before = len(kept)
                kept = on_topic(kept)
                if len(kept) < before:
                    log.info("dropped %s candidate(s) the model marked as not about AI", before - len(kept))
            if len(kept) != len(proposed):
                log.info("ranking model proposed %s, %s grounded in real headlines", len(proposed), len(kept))
            replies.append(kept)
    passes = [{c["url"]: c.get("importance_score") for c in reply} for reply in replies]
    if not replies:
        # Real headlines are still real: an unranked list beats losing the day.
        log.warning("ranking unavailable; using %s headline(s) unranked in feed order", len(headlines))
        return json.dumps({"candidates": unranked(headlines), "discovered": discovered, "passes": passes})
    merged = average(replies) if len(replies) > 1 else replies[0]
    candidates = [dict(c, coverage=coverage.get(c["url"], 1)) for c in merged]
    # `discovered` and `passes` are for the run log: everything ranking could
    # have chosen from, and each ranking pass's own scores.
    return json.dumps({"candidates": candidates, "discovered": discovered, "passes": passes})


def observed_attempts(runs_dir: Path | None = None) -> list[tuple[bool, bool]]:
    """(official, verified) for every candidate tried in logged runs. The
    default is read at call time, so tests can point `RUNS_DIR` elsewhere."""
    attempts: list[tuple[bool, bool]] = []
    for path in sorted((runs_dir or RUNS_DIR).glob("*.json")):
        try:
            record = json.loads(path.read_text())
            attempts.extend(
                (bool(t["official"]), t["outcome"] == "verified")
                for t in record.get("tries", [])
                if t.get("kind", "news") == "news"  # papers and columns have their own sources
            )
        except (ValueError, KeyError, TypeError, OSError) as error:
            log.warning("skipping unreadable run log %s: %s", path.name, error)
    return attempts


def candidates_from_json(
    id_prefix: str,
    raw: str,
    settings: RankingConfig | None = None,
    recent_titles: Iterable[str] = (),
    rates: Mapping[str, float] | None = None,
) -> list[Candidate]:
    """`rates` are pass rates per source kind; by default they come from the run logs."""
    settings = settings or config()
    if settings.order != "expected_value":
        rates = None
    elif rates is None:
        rates = verify_rates(observed_attempts())
    return to_candidates(id_prefix, json.loads(raw).get("candidates", []), load_rules(), settings, rates, recent_titles)


def choose_opinion(day: str, stories: list[dict], base_url: str = "https://weary.ai/") -> list[Candidate]:
    """Saturday column: the model picks the lead story, up to two supporting
    stories and the thesis, from the week's published stories only."""
    log.info("Choosing the week's opinion theme from %s published stor(ies)...", len(stories))
    if len(stories) < 2:
        log.info("fewer than two stories this week; no opinion column")
        return []
    column = _ask(
        opinion_prompt(day, stories), lambda raw: parse_opinion_reply(raw, day, stories, base_url), "opinion theme"
    )
    if column is None:
        return []
    log.info(
        "theme: %s\n  thesis: %s\n  stories: %s",
        column.evidence_summary,
        column.headline,
        [url.rstrip("/").rsplit("/", 1)[-1] for url in column.urls],
    )
    return [column]
