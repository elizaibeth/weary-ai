"""Freeze the discovery input for each gold-set day into `evals/cases.jsonl`.

Run once: `uv run python -m evals.snapshot`. Feeds only keep recent items, so
the snapshot is what the feeds hold on the day it is taken, not exactly what
the pipeline saw on each edition day. Freezing it makes every later eval run
rank the same input, so only the ranking changes between versions.
"""

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from agent.publishing.archive import stories_between
from agent.research import discovery

CASES = Path(__file__).with_name("cases.jsonl")
POSTS = Path(__file__).resolve().parents[2] / "content" / "posts"
# Weekdays with at least seven feed items when the snapshot was taken (5 Nov 2026).
DAYS = (
    "2026-10-06 2026-10-08 2026-10-12 2026-10-13 2026-10-14 2026-10-15 2026-10-19 2026-10-20 2026-10-21 "
    "2026-10-22 2026-10-23 2026-10-26 2026-10-27 2026-10-28 2026-10-29 2026-10-30 2026-11-02 2026-11-03 2026-11-04"
).split()


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    headlines = discovery.fetch_all_feed_headlines(discovery.FEEDS, discovery.default_fetch)
    by_day = defaultdict(list)
    for h in headlines:
        if h.published:
            by_day[h.published.date().isoformat()].append(h)
    with CASES.open("w") as out:
        for day in DAYS:
            published = [s["title"] for s in stories_between(POSTS, day, day)]
            case: dict[str, Any] = {
                "id": day,
                "day": day,
                "headlines": [
                    {"title": h.title, "url": h.url, "published": h.published.isoformat() if h.published else None}
                    for h in by_day[day]
                ],
                "published_title": published[0] if published else None,
            }
            out.write(json.dumps(case) + "\n")
            print(f"{day}: {len(case['headlines'])} headlines; published: {case['published_title']}")


if __name__ == "__main__":
    main()
