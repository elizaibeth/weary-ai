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

from agent.evidence import status_pages
from agent.evidence.packet import read_article as _read_article
from agent.evidence.source_rules import eligible_rule, load_rules
from agent.research import second_look
from agent.research.candidate import Candidate
from agent.research.discovery import Headline, likely_ai
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
    read_article: Callable[[str], str] | None = None,
) -> str:
    """Ranked candidates for these real headlines, as JSON for `candidates_from_json`.
    News gets a second look at a few left-out stories (see `second_look`):
    with `read_article` when given, and always in a real run (no `complete`)."""
    settings = settings or config()
    news = template is not PAPER_PROMPT
    if not real_headlines:
        log.info("no real headlines to rank")
        return json.dumps({"candidates": []})
    rules = load_rules()
    coverage: dict[str, int] = {}
    headlines = real_headlines
    event_of = {h.url: h.url for h in real_headlines}
    if settings.cluster and news:
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

    def rank(angles: Mapping[str, str] | None = None) -> list[list[dict]]:
        replies = []
        for k in range(max(1, settings.permutations)):
            # The first prompt keeps feed order; later ones shuffle it to cancel position bias.
            order = headlines if k == 0 else shuffled(headlines, f"{day_label}-{k}")
            prompt = ranking_prompt(day_label, order, rules, template, coverage, angles)
            proposed = _ask(prompt, parse_ranking_reply, "ranking", complete)
            if proposed is not None:
                kept = grounded(proposed, headlines)
                if news:
                    before = len(kept)
                    kept = on_topic(kept)
                    if len(kept) < before:
                        log.info("dropped %s candidate(s) the model marked as not about AI", before - len(kept))
                if len(kept) != len(proposed):
                    log.info("ranking model proposed %s, %s grounded in real headlines", len(proposed), len(kept))
                replies.append(kept)
        return replies

    replies = rank()
    passes = [{c["url"]: c.get("importance_score") for c in reply} for reply in replies]
    if not replies:
        # Real headlines are still real: an unranked list beats losing the day.
        # Without the model's ai_related flag, security-feed items need an AI
        # title. The filter runs before picking one headline per event, so an
        # AI report is not lost when an official non-AI advisory represents it.
        fallback = headlines
        if news:
            seen: set[str] = set()
            fallback = []
            for h in real_headlines:
                if likely_ai(h) and event_of[h.url] not in seen:
                    seen.add(event_of[h.url])
                    fallback.append(h)
        log.warning("ranking unavailable; using %s headline(s) unranked in feed order", len(fallback))
        return json.dumps({"candidates": unranked(fallback), "discovered": discovered, "passes": passes})
    merged = average(replies) if len(replies) > 1 else replies[0]
    candidates = [dict(c, coverage=coverage.get(c["url"], 1)) for c in merged]
    looked: list[dict] = []
    reader = read_article or (_read_article if complete is None else None)
    if news and reader is not None:
        kept, looked = _second_look(headlines, merged, coverage, reader, complete)
        if kept:
            candidates = _rerank_with_angles(kept, rank, coverage, passes) or candidates + kept
    # `discovered`, `passes` and `second_look` are for the run log: everything
    # ranking could have chosen from, each pass's own scores, and what the
    # second look read and decided.
    return json.dumps({"candidates": candidates, "discovered": discovered, "passes": passes, "second_look": looked})


def _rerank_with_angles(
    kept: list[dict],
    rank: Callable[[Mapping[str, str] | None], list[list[dict]]],
    coverage: Mapping[str, int],
    passes: list[dict],
) -> list[dict]:
    """Rank the day again with the second look's AI angles shown, so a kept
    story is scored against the other stories rather than on its own (its
    standalone score swung from 0.44 to 0.82 between runs of one day). A kept
    story keeps its angle as the summary: evidence and writing frame by it.
    Empty if the new ranking failed, so the caller keeps the first one."""
    angles = {c["url"]: c["evidence_summary"] for c in kept}
    replies = rank(angles)
    if not replies:
        return []
    passes.extend({c["url"]: c.get("importance_score") for c in reply} for reply in replies)
    merged = average(replies) if len(replies) > 1 else replies[0]
    by_url = {c["url"]: c for c in kept}
    ranked = [
        dict(c, coverage=coverage.get(c["url"], 1))
        | (
            {"evidence_summary": by_url[c["url"]]["evidence_summary"], "ai_related": True, "second_look": True}
            if c["url"] in by_url
            else {}
        )
        for c in merged
    ]
    # A kept story the new ranking still left out keeps its standalone score.
    ranked += [c for c in kept if c["url"] not in {r["url"] for r in ranked}]
    log.info("ranked again with %s AI angle(s) from the second look", len(angles))
    return ranked


def _second_look(
    headlines: list[Headline],
    proposed: list[dict],
    coverage: Mapping[str, int],
    read: Callable[[str], str],
    complete: Complete | None,
) -> tuple[list[dict], list[dict]]:
    """Candidates for left-out stories whose article shows an AI effect, and
    a log entry for every story looked at."""
    status = status_pages.load_config()
    kept: list[dict] = []
    trace: list[dict] = []
    for h in second_look.overlooked(headlines, (c["url"] for c in proposed), coverage, status):
        entry = {"headline": h.title, "url": h.url}
        try:
            article = read(h.url)
        except Exception as error:
            trace.append({**entry, "outcome": f"unreadable: {type(error).__name__}: {error}"[:200]})
            continue

        def parse(raw: str, article: str = article) -> dict:
            # {} is a usable reply with no AI effect; _ask's None is no usable reply.
            return second_look.parse_angle_reply(raw, article, status) or {}

        angle = _ask(second_look.angle_prompt(h.title, article), parse, "second look", complete)
        if angle is None:
            trace.append({**entry, "outcome": "no usable reply"})
        elif not angle:
            trace.append({**entry, "outcome": "no AI effect"})
        else:
            kept.append(second_look.rescued(h, angle, coverage.get(h.url, 1)))
            trace.append({**entry, "outcome": "kept", "angle": angle["angle"], "quote": angle["quote"]})
            log.info("second look kept %r: %s", h.title, angle["angle"])
    return kept, trace


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
    proposals = json.loads(raw).get("candidates", [])
    return to_candidates(
        id_prefix, proposals, load_rules(), settings, rates, recent_titles, status=status_pages.load_config()
    )


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
