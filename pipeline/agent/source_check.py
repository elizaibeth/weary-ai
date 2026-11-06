"""Report which discovery sources this machine can reach: `python -m agent.source_check`.

A site can work locally and still refuse GitHub Actions (openai.com returns
403 there), so CI runs this to show reachability from the runner. For each
feed it fetches the feed, then the first article the allowlist accepts.
Informational only: it always exits 0.
"""

import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agent.evidence.retrieval import DocumentFetcher, extract
from agent.evidence.source_rules import eligible_rule, load_rules
from agent.research import discovery


def check(feed: str, fetcher: DocumentFetcher) -> tuple[str, str]:
    """Returns (status, detail); status is OK, LEAD, NONE or FAIL."""
    try:
        raw = discovery.default_fetch(feed)
    except Exception as error:
        return "FAIL", f"feed: {type(error).__name__}: {str(error)[:60]}"
    headlines = discovery.fetch_all_feed_headlines((feed,), lambda url: raw)
    if feed not in discovery._PRIMARY_FEEDS:
        return "LEAD", f"{len(headlines)} items (reporting: leads only)"
    if not headlines:
        return "NONE", "feed reachable; no AI or allowlisted items right now"
    rules = load_rules()
    article = next((h for h in headlines if eligible_rule(h.url, rules)), headlines[0])
    try:
        blocks = len(extract(fetcher(article.url)).blocks)
    except Exception as error:
        return "FAIL", f"{len(headlines)} items; article: {type(error).__name__}: {str(error)[:60]}"
    return "OK", f"{len(headlines)} items; article read ({blocks} text blocks)"


def main() -> int:
    fetcher = DocumentFetcher(Path(tempfile.mkdtemp()), lambda url: True)
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda feed: check(feed, fetcher), discovery.FEEDS))
    print("\nSource reachability:")
    for feed, (status, detail) in zip(discovery.FEEDS, results, strict=True):
        print(f"  {status:4} {feed[:70]:70} {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
