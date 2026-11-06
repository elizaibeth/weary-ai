import pytest

from agent.publishing import publisher
from agent.writing.article import Citation, Draft, Paragraph


def _draft(**overrides):
    defaults = dict(
        title="Some Headline!",
        description="A description of why this story matters.",
        paragraphs=(
            Paragraph("First fact, from the first source.", (1,)),
            Paragraph("Second fact, corroborated by both sources.", (1, 2)),
        ),
        sources=(
            Citation(id=1, title="Example Source", url="https://a.example/story"),
            Citation(id=2, title="Another Outlet", url="https://b.example/story"),
        ),
        category="Models",
        tags=("x",),
        event_date="2026-09-25",
        image_prompt="p",
        image_alt="a",
        image_caption="c",
        why_today="w",
    )
    defaults.update(overrides)
    return Draft(**defaults)


def test_publish_writes_bundle_as_draft_by_default(tmp_path):
    bundle = publisher.publish(_draft(), b"\x89PNG\r\n\x1a\ndata", live=False, posts_dir=tmp_path)
    front_matter = (bundle / "index.md").read_text()
    assert "draft: true" in front_matter
    assert (bundle / "cover.webp").exists()


def test_publish_writes_bundle_as_live_when_requested(tmp_path):
    bundle = publisher.publish(_draft(), b"\x89PNG\r\n\x1a\ndata", live=True, posts_dir=tmp_path)
    front_matter = (bundle / "index.md").read_text()
    assert "draft: false" in front_matter


def test_publish_rejects_slug_collision(tmp_path):
    publisher.publish(_draft(), b"data", live=False, posts_dir=tmp_path)
    with pytest.raises(ValueError):
        publisher.publish(_draft(), b"data", live=False, posts_dir=tmp_path)


def test_publish_records_source_urls_in_front_matter(tmp_path):
    bundle = publisher.publish(_draft(), b"data", live=False, posts_dir=tmp_path)
    front_matter = (bundle / "index.md").read_text()
    assert '"https://a.example/story"' in front_matter
    assert '"https://b.example/story"' in front_matter


def test_publish_writes_description_and_categories_as_a_plural_array(tmp_path):
    bundle = publisher.publish(_draft(), b"data", live=False, posts_dir=tmp_path)
    front_matter = (bundle / "index.md").read_text()
    assert 'description: "A description of why this story matters."' in front_matter
    assert 'categories: ["Models"]' in front_matter
    assert "category:" not in front_matter.replace("categories:", "")


def test_render_front_matter_escapes_an_embedded_quote():
    front_matter = publisher.render_front_matter(_draft(title='A "quoted" headline'), live=False)
    assert 'title: "A \\"quoted\\" headline"' in front_matter


def test_render_front_matter_includes_why_today():
    front_matter = publisher.render_front_matter(
        _draft(why_today="The specific reason this story was picked."), live=False
    )
    assert 'why_today: "The specific reason this story was picked."' in front_matter


def test_render_body_no_longer_includes_a_why_today_section():
    body = publisher.render_body(_draft(why_today="Should not appear in the body."))
    assert "Why this is today's story" not in body
    assert "Should not appear in the body." not in body


def test_render_body_has_no_inline_citation_markers():
    body = publisher.render_body(_draft())
    assert "[1](" not in body
    assert "[2](" not in body
    assert "First fact, from the first source." in body
    assert "Second fact, corroborated by both sources." in body


def test_render_body_lists_cited_sources_at_the_end():
    body = publisher.render_body(_draft())
    assert "## Sources" in body
    assert "- [Example Source](<https://a.example/story>)" in body
    assert "- [Another Outlet](<https://b.example/story>)" in body


def test_render_body_omits_uncited_sources_from_the_sources_section():
    draft = _draft(
        paragraphs=(Paragraph("Only cites the first source.", (1,)),),
    )
    body = publisher.render_body(draft)
    assert "Example Source" in body
    assert "Another Outlet" not in body


def test_render_body_escapes_markdown_special_characters_in_generated_text():
    draft = _draft(
        paragraphs=(Paragraph("A [fake link](evil.example) and *bold* claim.", (1,)),),
    )
    body = publisher.render_body(draft)
    # Escaping the brackets alone is enough to stop a markdown link from
    # forming, even though the parentheses are left untouched.
    assert "[fake link]" not in body
    assert "\\[fake link\\](evil.example)" in body
    assert "*bold*" not in body
    assert "\\*bold\\*" in body


def test_render_body_lists_sources_used_only_in_summary_fields():
    draft = _draft(
        paragraphs=(Paragraph("Body cites the first source.", (1,)),),
        claim_passages=(("title", ("source-two-passage",)),),
    )
    body = publisher.render_body(draft)
    assert "Example Source" in body
    assert "Another Outlet" in body


def test_series_is_written_to_front_matter_only_when_given():
    assert 'series: ["Research paper of the week"]\n---' in publisher.render_front_matter(
        _draft(), live=True, series="Research paper of the week"
    )
    assert "series:" not in publisher.render_front_matter(_draft(), live=True)


def test_rendered_body_never_shows_passage_ids():
    draft = _draft(paragraphs=(Paragraph("A repaired fact. [P3]", (1,)),))
    assert "P3" not in publisher.render_body(draft)
