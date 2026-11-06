import json
from pathlib import Path

from agent.publishing import archive
from agent.research.candidate import Candidate


def _publish_post(
    posts_dir: Path,
    slug: str,
    title: str,
    origin_urls: tuple = (),
    source_urls: tuple = (),
    tags: tuple = (),
) -> None:
    bundle = posts_dir / slug
    bundle.mkdir(parents=True)
    (bundle / "index.md").write_text(
        f'---\ntitle: "{title}"\ndraft: false\n'
        f"source_urls: {json.dumps(list(source_urls))}\n"
        f"origin_urls: {json.dumps(list(origin_urls))}\n"
        f"tags: {json.dumps(list(tags))}\n---\n\nBody."
    )


def test_is_duplicate_true_for_an_already_published_event(tmp_path: Path):
    _publish_post(
        tmp_path,
        "openai-launches-a-new-model",
        "OpenAI launches a new model",
        origin_urls=("https://example.com",),
    )
    candidate = Candidate("id-1", "OpenAI launches a new model", ("https://example.com",), 1.0)
    assert archive.is_duplicate(candidate, tmp_path) is True


def test_is_duplicate_false_for_a_genuinely_new_event_sharing_a_topic(tmp_path: Path):
    _publish_post(
        tmp_path,
        "openai-launches-a-new-model",
        "OpenAI launches a new model",
        origin_urls=("https://example.com",),
    )
    candidate = Candidate("id-2", "OpenAI settles a lawsuit over data use", ("https://other.example",), 1.0)
    assert archive.is_duplicate(candidate, tmp_path) is False


def test_is_duplicate_false_for_an_empty_or_missing_archive(tmp_path: Path):
    candidate = Candidate("id-1", "Some story", ("https://example.com",), 1.0)
    assert archive.is_duplicate(candidate, tmp_path / "does-not-exist") is False


def test_is_duplicate_true_for_the_same_origin_url_even_with_a_reworded_headline(tmp_path: Path):
    _publish_post(
        tmp_path,
        "openai-launches-a-new-model",
        "OpenAI launches a new model",
        origin_urls=("https://real.example/the-actual-story",),
    )
    candidate = Candidate(
        "id-2",
        "OpenAI's brand new model has arrived, here's everything you need to know",
        ("https://real.example/the-actual-story",),
        1.0,
    )
    assert archive.is_duplicate(candidate, tmp_path) is True


def test_is_duplicate_true_when_origin_url_matches_even_though_cited_source_urls_differ(tmp_path: Path):
    # `source_urls` (cited, primary-role-only sources) almost never
    # contains the original reporting-outlet URL - dedup must key off
    # `origin_urls`, not `source_urls`, or this case silently regresses.
    _publish_post(
        tmp_path,
        "openai-launches-a-new-model",
        "OpenAI launches a new model",
        origin_urls=("https://techcrunch.com/the-actual-story",),
        source_urls=("https://openai.com/blog/the-announcement",),
    )
    candidate = Candidate(
        "id-2",
        "OpenAI's brand new model has arrived, here's everything you need to know",
        ("https://techcrunch.com/the-actual-story",),
        1.0,
    )
    assert archive.is_duplicate(candidate, tmp_path) is True


def test_is_duplicate_false_for_a_different_url_and_different_headline(tmp_path: Path):
    _publish_post(
        tmp_path,
        "openai-launches-a-new-model",
        "OpenAI launches a new model",
        origin_urls=("https://real.example/the-actual-story",),
    )
    candidate = Candidate(
        "id-2", "Anthropic settles a lawsuit over training data", ("https://real.example/other-story",), 1.0
    )
    assert archive.is_duplicate(candidate, tmp_path) is False


def test_published_tags_sorts_by_frequency_then_alphabetically(tmp_path: Path):
    _publish_post(tmp_path, "post-1", "Post one", tags=("Anthropic", "Governance"))
    _publish_post(tmp_path, "post-2", "Post two", tags=("Anthropic", "Safety"))
    assert archive.published_tags(tmp_path) == ("Anthropic", "Governance", "Safety")


def test_published_tags_empty_for_a_missing_archive(tmp_path: Path):
    assert archive.published_tags(tmp_path / "does-not-exist") == ()


def _post(posts_dir, slug, day, draft=False, series=None, sources=("https://a.example/1",)):
    bundle = posts_dir / slug
    bundle.mkdir(parents=True)
    lines = [
        "---",
        f'title: "{slug} title"',
        f'description: "{slug} summary"',
        f"date: {day}",
        f"draft: {str(draft).lower()}",
    ]
    lines.append(f"source_urls: {json.dumps(list(sources))}")
    if series:
        lines.append(f"series: {json.dumps([series])}")
    (bundle / "index.md").write_text("\n".join(lines + ["---", "", "Body."]) + "\n")


def test_stories_between_returns_live_non_opinion_stories_in_range(tmp_path):
    from agent.publishing.archive import stories_between

    _post(tmp_path, "sunday-paper", "2026-10-25", series="Research paper of the week")
    _post(tmp_path, "monday-news", "2026-10-26")
    _post(tmp_path, "a-draft", "2026-10-27", draft=True)
    _post(tmp_path, "last-column", "2026-10-28", series="Opinion")
    _post(tmp_path, "saturday-before", "2026-10-24")
    stories = stories_between(tmp_path, "2026-10-25", "2026-10-30")
    assert [s["slug"] for s in stories] == ["sunday-paper", "monday-news"]
    assert stories[1]["source_urls"] == ("https://a.example/1",)


def test_has_series_post_matches_day_and_series(tmp_path):
    from agent.publishing.archive import has_series_post

    _post(tmp_path, "column", "2026-10-31", series="Opinion")
    _post(tmp_path, "failed-column", "2026-10-24", draft=True, series="Opinion")
    assert has_series_post(tmp_path, "2026-10-31", "Opinion")
    assert not has_series_post(tmp_path, "2026-10-24", "Opinion")  # a draft does not block a retry
