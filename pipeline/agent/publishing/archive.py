"""Check a candidate against previously published stories.

The primary signal is the candidate's origin URL (the RSS feed link it was
discovered from), stored separately from `source_urls` in front matter -
`source_urls` is only ever the article's *cited* (primary-role) sources,
which routinely excludes the origin URL entirely, since a reporting
outlet's own URL is never citable under the primary-sources-only rule. The
same real news item keeps the same origin URL every time it's picked up
from a feed, regardless of how differently the model phrases the headline
on a rerun - which headline-text similarity alone cannot reliably catch.
Headline-text similarity is kept as a secondary signal, for the case where
a genuinely different origin URL (e.g. a different outlet's near-identical
wire copy) covers the same event. A missing or unreadable archive is
treated as "no duplicates found", never as a crash or a blanket rejection
of every candidate.
"""

import difflib
import json
from pathlib import Path

from agent.research.candidate import Candidate

_DUPLICATE_THRESHOLD = 0.8


def _published_posts(posts_dir: Path) -> list[tuple[str, tuple[str, ...], tuple[str, ...]]]:
    """Returns a list of (title, urls, tags) for every published post, where
    `urls` is `origin_urls` if present, else `source_urls` - older posts
    published before `origin_urls` existed still get a best-effort URL
    check instead of falling through to headline-similarity alone."""
    if not posts_dir.exists():
        return []
    posts = []
    for index_file in posts_dir.glob("*/index.md"):
        try:
            text = index_file.read_text()
        except OSError:
            continue
        title = ""
        source_urls: tuple[str, ...] = ()
        origin_urls: tuple[str, ...] = ()
        tags: tuple[str, ...] = ()
        for line in text.splitlines():
            if line.startswith("title:"):
                title = line.split(":", 1)[1].strip().strip('"')
            elif line.startswith("origin_urls:"):
                try:
                    origin_urls = tuple(json.loads(line.split(":", 1)[1].strip()))
                except (ValueError, json.JSONDecodeError):
                    origin_urls = ()
            elif line.startswith("source_urls:"):
                try:
                    source_urls = tuple(json.loads(line.split(":", 1)[1].strip()))
                except (ValueError, json.JSONDecodeError):
                    source_urls = ()
            elif line.startswith("tags:"):
                try:
                    tags = tuple(json.loads(line.split(":", 1)[1].strip()))
                except (ValueError, json.JSONDecodeError):
                    tags = ()
        posts.append((title, origin_urls or source_urls, tags))
    return posts


def is_duplicate(candidate: Candidate, posts_dir: Path) -> bool:
    posts = _published_posts(posts_dir)
    candidate_urls = set(candidate.urls)

    if any(candidate_urls & set(urls) for _, urls, _ in posts):
        return True

    headline = candidate.headline.lower()
    return any(
        difflib.SequenceMatcher(None, title.lower(), headline).ratio() >= _DUPLICATE_THRESHOLD for title, _, _ in posts
    )


def published_tags(posts_dir: Path) -> tuple[str, ...]:
    """Every tag used by any previously published post, sorted by how often
    it's been used (most-used first) - handed to `writer.draft` so it can
    reuse an existing tag (e.g. "Governance") instead of minting a
    near-duplicate of its own phrasing (e.g. "AI Governance") for the same
    concept."""
    counts: dict[str, int] = {}
    for _, _, tags in _published_posts(posts_dir):
        for tag in tags:
            counts[tag] = counts.get(tag, 0) + 1
    return tuple(sorted(counts, key=lambda t: (-counts[t], t)))


def _series(fields: dict[str, object]) -> list[str]:
    series = fields.get("series")
    return [str(s) for s in series] if isinstance(series, list) else []


def _front_matter(text: str) -> dict[str, object]:
    """The simple one-line fields publisher.render_front_matter writes."""
    fields: dict[str, object] = {}
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return fields
    for line in lines[1:]:
        if line == "---":
            break
        key, _, value = line.partition(":")
        value = value.strip()
        try:
            fields[key] = json.loads(value)
        except (ValueError, json.JSONDecodeError):
            fields[key] = value
    return fields


def stories_between(posts_dir: Path, first_day: str, last_day: str) -> list[dict]:
    """Live stories dated first_day..last_day inclusive, oldest first.

    Opinion pieces are left out, so a column never argues from another column.
    """
    stories = []
    for index_file in posts_dir.glob("*/index.md") if posts_dir.exists() else ():
        try:
            fields = _front_matter(index_file.read_text())
        except OSError:
            continue
        day = str(fields.get("date", ""))
        if fields.get("draft") is not False or not (first_day <= day <= last_day):
            continue
        if "Opinion" in _series(fields):
            continue
        sources = fields.get("source_urls")
        stories.append(
            {
                "slug": index_file.parent.name,
                "date": day,
                "title": str(fields.get("title", "")),
                "description": str(fields.get("description", "")),
                "source_urls": tuple(sources) if isinstance(sources, list) else (),
            }
        )
    return sorted(stories, key=lambda s: (s["date"], s["slug"]))


def has_series_post(posts_dir: Path, day: str, series: str) -> bool:
    """Whether a live post in `series` already exists for `day`.

    Unverified drafts do not count, so a later run can still publish one."""
    for index_file in posts_dir.glob("*/index.md") if posts_dir.exists() else ():
        try:
            fields = _front_matter(index_file.read_text())
        except OSError:
            continue
        if fields.get("draft") is False and str(fields.get("date", "")) == day and series in _series(fields):
            return True
    return False
