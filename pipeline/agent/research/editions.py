"""The research stage: candidate search, then ranking.

1. `discovery` finds real headlines (feeds, official newsrooms, GDELT, one
   budgeted historical search, Hugging Face papers, or Weary's own week of
   stories). No model is called.
2. `ranking` has a model choose and score candidates from those headlines
   only, and orders them for the rest of the pipeline.

Each edition type below is one search plus one ranking call.
"""

import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from agent.research import discovery, ranking, ranking_core
from agent.research.candidate import Candidate

log = logging.getLogger(__name__)

Client = Callable[[str], str]


def _default_client(day: str) -> str:
    return ranking.rank_headlines(day, discovery.fetch_headlines(day))


def _default_live_client(now: datetime) -> str:
    return ranking.rank_headlines(now.date().isoformat(), discovery.fetch_recent_headlines(now))


def survey(
    day: str,
    client: Client = _default_client,
    *,
    historical_search: discovery.HistoricalSearch | None = None,
    recent_titles: Iterable[str] = (),
    trace: dict | None = None,
) -> list[Candidate]:
    """A historical backfill: the headlines published on `day`, ranked.
    `recent_titles` (the past week's stories) lowers near-repeats; `trace`, if
    given, receives every discovered headline and each ranking pass's scores."""
    raw = (
        ranking.rank_headlines(day, discovery.fetch_headlines(day, historical_search=historical_search))
        if client is _default_client and historical_search is not None
        else client(day)
    )
    _copy_trace(raw, trace)
    return ranking.candidates_from_json(day, raw, recent_titles=recent_titles)


def survey_recent(
    now: datetime,
    client: Callable[[datetime], str] = _default_live_client,
    *,
    recent_titles: Iterable[str] = (),
    trace: dict | None = None,
) -> list[Candidate]:
    """The live scheduled job: headlines from a rolling recency window (see
    `discovery.fetch_recent_headlines`), ranked."""
    raw = client(now)
    _copy_trace(raw, trace)
    return ranking.candidates_from_json(now.date().isoformat(), raw, recent_titles=recent_titles)


def _copy_trace(raw: str, trace: dict | None) -> None:
    if trace is not None:
        data = json.loads(raw)
        trace["discovered"] = data.get("discovered", [])
        trace["passes"] = data.get("passes", [])


def survey_papers(day: str, fetch: discovery.Fetch = discovery.default_fetch) -> list[Candidate]:
    """Sunday research paper of the week: the week's top papers, ranked.

    Evidence comes from the paper itself: the arXiv abstract page and, when
    arXiv has rendered one, the full-text HTML version.
    """
    log.info("Surveying research papers for the week ending %s...", day)
    papers = discovery.fetch_weekly_papers(datetime.strptime(day, "%Y-%m-%d").date(), fetch)
    candidates = ranking.candidates_from_json(
        f"{day}-paper", ranking.rank_headlines(day, papers, ranking_core.PAPER_PROMPT)
    )
    return [
        replace(c, kind="paper", urls=(c.urls[0], c.urls[0].replace("/abs/", "/html/", 1)))
        for c in sorted(candidates, key=lambda c: c.importance_score, reverse=True)
    ]


def survey_opinion(day: str, posts_dir: Path, base_url: str = "https://weary.ai/") -> list[Candidate]:
    """Saturday column: the week's live stories, then the lead story and thesis."""
    return ranking.choose_opinion(day, discovery.week_stories(posts_dir, day), base_url)
