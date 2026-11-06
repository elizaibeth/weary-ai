"""CLI entry point: `python -m agent [--date YYYY-MM-DD] [--url URL]`.

Without `--date`, runs the live scheduled job: candidates come from a
rolling recency window (last 12h, widening to 24h) ending now - see
`discovery.fetch_recent_headlines`. With `--date`, runs a historical
backfill matching that exact calendar day instead.
`--url` selects one article directly, bypassing discovery and ranking.

"No story today" (research found nothing, or nothing could be verified
enough to draft at all) is a normal, expected outcome - not a bug - so it
exits 0 after `daily.run`'s own Slack failure notification has already
fired. A failed explicit `--url` selection exits 1 instead. Anything else
is a real error and propagates normally.
"""

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

from agent.daily import RunStopped, run

# Level and module on every line, e.g. "INFO    discovery     feed ...: 20 item(s)";
# GitHub Actions adds its own timestamps.
LOG_FORMAT = "%(levelname)-7s %(module)-13s %(message)s"


def _configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logging.basicConfig(level=os.environ.get("WEARY_LOG_LEVEL", "INFO").upper(), handlers=[handler], force=True)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    parser = argparse.ArgumentParser(description="Run the daily Weary.ai pipeline.")
    parser.add_argument(
        "--date",
        type=lambda value: date.fromisoformat(value).isoformat(),
        help="Edition date (YYYY-MM-DD). Without --url, selects historical discovery; omit for today.",
    )
    parser.add_argument("--url", help="Select a supported article URL directly, skipping discovery and ranking.")
    parser.add_argument(
        "--local",
        action="store_true",
        help="Save a draft locally, disable Slack/generated images, and allow at most two Brave requests.",
    )
    args = parser.parse_args(argv)
    if args.local:
        os.environ["SLACK_WEBHOOK_URL"] = ""
        os.environ["WEARY_GENERATE_IMAGES"] = "false"
        os.environ["WEARY_SEARCH_REQUESTS_PER_RUN"] = str(
            min(2, max(0, int(os.environ.get("WEARY_SEARCH_REQUESTS_PER_RUN", "2"))))
        )

    # This file is pipeline/agent/__main__.py - the Hugo project root (where
    # content/ and .weary/ live) is two directories further up.
    root = Path(__file__).resolve().parent.parent.parent

    try:
        bundle = run(
            root,
            args.date or date.today().isoformat(),
            recent_window=not bool(args.date or args.url),
            live=False if args.local else None,
            story_url=args.url,
        )
    except RunStopped as e:
        # Already reported to Slack; exit non-zero so the Actions run is red.
        print(f"Run stopped: {e}")
        return 1
    except ValueError as e:
        if args.url:
            print(f"Manual story failed: {e}")
            return 1
        print(f"No story published: {e}")
        return 0

    print(f"{'Saved local draft' if args.local else 'Saved edition'}: {bundle}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
