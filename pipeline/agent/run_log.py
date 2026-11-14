"""A JSON record of each run: the ranking, every candidate tried, and the outcome.

`daily` writes one file per run to `pipeline/runs/`, which the daily workflow
commits. The records are the ranking's memory: `ranking.observed_attempts`
turns them into observed verification pass rates, and they show offline
evaluation what actually happened on each edition day.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from agent.research.candidate import Candidate


def new_record(day: str, mode: str) -> dict:
    return {
        "day": day,
        "mode": mode,
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "discovered": [],  # every headline discovery found, ranked or not
        "passes": [],  # each ranking pass's scores, by URL
        "second_look": [],  # left-out stories read again for an AI angle
        "ranking": [],  # the candidates in the order they were tried
        "tries": [],
    }


def ranking_entries(candidates: list[Candidate]) -> list[dict]:
    """The candidates in the order they will be tried, with their ranking signals."""
    return [
        {
            "rank": i,
            "headline": c.headline,
            "url": c.urls[0] if c.urls else "",
            "kind": c.kind,
            "importance": round(c.importance_score, 4),
            "official": c.official,
            "coverage": c.coverage,
            "rank_key": round(c.rank_key, 4),
        }
        for i, c in enumerate(candidates, 1)
    ]


def try_entry(candidate: Candidate, outcome: str, reason: str = "") -> dict:
    """`outcome` is "verified", "unverified" (drafted but failed checks) or "failed"."""
    return {
        "headline": candidate.headline,
        "url": candidate.urls[0] if candidate.urls else "",
        "kind": candidate.kind,
        "official": candidate.official,
        "outcome": outcome,
        "reason": reason[:300],
    }


def write(root: Path, record: dict) -> Path:
    runs = root / "pipeline" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    stamp = record["started_at"].replace(":", "").replace("+0000", "Z")
    path = runs / f"{record['day']}_{stamp[11:17]}.json"
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    return path
