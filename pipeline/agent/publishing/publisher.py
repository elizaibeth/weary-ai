"""Render the final article + illustration as a Hugo content bundle.

Paragraphs read as ordinary prose - no inline citation markers - with a
"## Sources" section listing every source actually cited, rendered
deterministically by this module rather than trusted from the model's own
markdown. Generated text has markdown special characters escaped first,
so the model can't fake a link, heading, or emphasis that this renderer
didn't create itself.

`why_today` (the writer's own editorial rationale for this pick) is
written to front matter rather than the body, so the theme can render it
wherever it likes - currently directly below the headline, replacing the
opening summary there.
"""

import json
import logging
import re
from pathlib import Path

from agent.writing.article import Draft
from agent.writing.house_style import strip_passage_markers

log = logging.getLogger(__name__)

_MARKDOWN_SPECIAL_RE = re.compile(r"([\\`*_{}\[\]<>#!|])")


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "untitled"


def _escape_markdown(text: str) -> str:
    return _MARKDOWN_SPECIAL_RE.sub(r"\\\1", " ".join(text.split()))


def _yaml_string(text: str) -> str:
    """A double-quoted YAML scalar, safe even if the text contains a
    literal quote or backslash (front matter is parsed as YAML by Hugo)."""
    return json.dumps(" ".join(text.split()))


def render_front_matter(
    draft: Draft, live: bool, origin_urls: tuple = (), day: str | None = None, series: str | None = None
) -> str:
    """`day` is the pipeline's own authoritative date (the calendar day
    surveyed, or `now.date()` for the live recency-window job) - it's used
    for the page date instead of `draft.event_date`, which is only the
    model's own free-text extraction from evidence prose and can pick up
    an unrelated date mentioned inside a source rather than when the story
    itself broke. Falls back to `draft.event_date` when not given."""
    tags = ", ".join(_yaml_string(t) for t in draft.tags)
    source_urls = [s.url for s in draft.sources]
    return (
        "---\n"
        f"title: {_yaml_string(draft.title)}\n"
        f"description: {_yaml_string(draft.description)}\n"
        f"date: {day or draft.event_date}\n"
        f"draft: {str(not live).lower()}\n"
        f"categories: [{_yaml_string(draft.category)}]\n"
        f"tags: [{tags}]\n"
        f"image_alt: {_yaml_string(draft.image_alt)}\n"
        f"image_caption: {_yaml_string(draft.image_caption)}\n"
        f"why_today: {_yaml_string(draft.why_today)}\n"
        f"source_urls: {json.dumps(source_urls)}\n"
        f"origin_urls: {json.dumps(list(origin_urls))}\n"
        + (f"series: [{_yaml_string(series)}]\n" if series else "")
        + "---\n\n"
    )


def render_body(draft: Draft) -> str:
    cited_ids = {sid for p in draft.paragraphs for sid in p.source_ids}
    if draft.claim_passages:
        # Passage-based drafts have a Python-derived source list containing
        # exactly the citations used by the body and published summary fields.
        cited_ids.update(s.id for s in draft.sources)

    # Repaired paragraphs skip the writer's clean-up, so strip echoed IDs here too.
    blocks = [_escape_markdown(strip_passage_markers(p.published_text)) for p in draft.paragraphs]

    blocks.append("## Sources")
    blocks.extend(f"- [{_escape_markdown(s.title)}](<{s.url}>)" for s in draft.sources if s.id in cited_ids)
    return "\n\n".join(blocks)


def publish(
    draft: Draft,
    image: bytes,
    live: bool,
    posts_dir: Path,
    origin_urls: tuple = (),
    day: str | None = None,
    series: str | None = None,
) -> Path:
    slug = slugify(draft.title)
    bundle = posts_dir / slug
    if bundle.exists():
        raise ValueError(f"The headline slug already exists: {slug}")
    bundle.mkdir(parents=True)
    (bundle / "cover.webp").write_bytes(image)
    (bundle / "index.md").write_text(
        render_front_matter(draft, live, origin_urls, day, series) + render_body(draft) + "\n"
    )
    log.info("wrote %s", bundle)
    return bundle
