"""A candidate story: what ranking hands to the rest of the pipeline."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    id: str
    headline: str
    urls: tuple[str, ...]
    importance_score: float
    evidence_summary: str = ""
    kind: str = "news"  # "paper" (Sunday research paper) or "opinion" (Saturday column)
    # Opinion only: (story title, its primary source URLs) for each story the
    # column discusses; evidence is gathered per story.
    parts: tuple[tuple[str, tuple[str, ...]], ...] = ()
    # Ranking signals, kept for the run log: outlets that covered the event,
    # whether the URL is an official (allowlisted) source, and the sort key.
    coverage: int = 1
    official: bool = False
    rank_key: float = 0.0
