"""The article a writer produces: a draft, its paragraphs and their citations.

Plain immutable data shared by every stage after the writer (verifier,
repairer, publisher, notifier). No behaviour beyond derived text.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Citation:
    id: int
    title: str
    url: str


@dataclass(frozen=True)
class SupportingPassage:
    source_id: int
    quote: str
    passage_id: str = ""


@dataclass(frozen=True)
class Paragraph:
    text: str  # in an opinion column, the cited facts only
    source_ids: tuple[int, ...]
    support: tuple[SupportingPassage, ...] = ()
    passage_ids: tuple[str, ...] = ()
    # Opinion columns only: the writer's interpretation, published after the
    # facts. Checked for added facts, not for support (verifier opinion mode).
    argument: str = ""

    @property
    def published_text(self) -> str:
        return f"{self.text} {self.argument}".strip()


@dataclass(frozen=True)
class Draft:
    title: str
    description: str
    paragraphs: tuple[Paragraph, ...]
    sources: tuple[Citation, ...]
    category: str
    tags: tuple[str, ...]
    event_date: str
    image_prompt: str
    image_alt: str
    image_caption: str
    why_today: str
    claim_passages: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def body_text(self) -> str:
        return " ".join(p.published_text for p in self.paragraphs)
