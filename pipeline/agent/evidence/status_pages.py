"""Status pages as evidence for outage stories, and what counts as an AI effect.

Status pages never find stories: an outage is a candidate only when outlets
report it. When one is, `packet.gather` reads the named provider's status
feed for what broke, and the AI companies' feeds for entries that name that
provider, which is the AI angle. Everything here is pure: parsing, matching
and the rules; `packet` does the fetching.
"""

import json
import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree

from bs4 import BeautifulSoup

# Headline wording that reports a service failing. Kept narrow on purpose:
# "steps down" or "shuts down a product" is not an outage.
_OUTAGE_RE = re.compile(
    r"\b(outages?|downtime|disruptions?|disrupted|offline|went down|goes down|go down|"
    r"(?:is|are|was|were) down|restor(?:e|es|ed|ing)|back to life|back online|"
    r"service (?:issues|problems|failures?))\b",
    re.I,
)
# An entry can be published a little after the day it reports, and a long
# outage starts before the day it is reported on.
WINDOW_DAYS_BEFORE = 2
WINDOW_DAYS_AFTER = 1
_MAX_ENTRY_CHARS = 1500


@dataclass(frozen=True)
class StatusProvider:
    name: str
    aliases: tuple[str, ...]
    feeds: tuple[str, ...]
    ai: bool = False
    # The human-readable status page, cited for entries without their own link.
    page: str = ""

    def named_in(self, text: str) -> bool:
        return any(re.search(r"(?<!\w)" + re.escape(a) + r"(?!\w)", text) for a in self.aliases)

    def owns(self, url: str) -> bool:
        host = (urlsplit(url).hostname or "").lower()
        return any(host == (urlsplit(f).hostname or "").lower() for f in self.feeds)


@dataclass(frozen=True)
class StatusConfig:
    providers: tuple[StatusProvider, ...]
    ai_terms: tuple[str, ...]

    def mentions_ai(self, text: str) -> bool:
        return any(re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", text) for t in self.ai_terms)


@dataclass(frozen=True)
class StatusEntry:
    title: str
    text: str
    # YYYY-MM-DD in UTC, or "" when the feed gives none. Feeds date an entry
    # by its latest update, which can be the day after the incident.
    published: str = ""
    link: str = ""  # the entry's own incident page, when the feed gives one

    @property
    def passage(self) -> str:
        dated = f" (updated {self.published})" if self.published else ""
        return f"{self.title}{dated}: {self.text}" if self.text else f"{self.title}{dated}"


def load_config(path: Path | None = None) -> StatusConfig:
    data = tomllib.loads((path or Path(__file__).with_name("status_pages.toml")).read_text())
    return StatusConfig(
        tuple(
            StatusProvider(
                p["provider"], tuple(p["aliases"]), tuple(p["feeds"]), bool(p.get("ai", False)), p.get("page", "")
            )
            for p in data["providers"]
        ),
        tuple(data["ai"]["terms"]),
    )


NO_STATUS = StatusConfig((), ())


def is_outage_story(text: str) -> bool:
    return bool(_OUTAGE_RE.search(text))


def outage_providers(text: str, config: StatusConfig) -> tuple[StatusProvider, ...]:
    """The providers an outage story names; empty when it is not an outage story."""
    if not is_outage_story(text):
        return ()
    return tuple(p for p in config.providers if p.named_in(text))


def feeds_to_read(named: Iterable[StatusProvider], config: StatusConfig) -> list[tuple[str, StatusProvider]]:
    """The named providers' feeds, then every AI provider's, each once."""
    named = list(named)
    if not named:
        return []
    chosen = named + [p for p in config.providers if p.ai and p not in named]
    return list(dict.fromkeys((feed, p) for p in chosen for feed in p.feeds))


def _plain(markup: str) -> str:
    text = BeautifulSoup(markup, "html.parser").get_text(" ", strip=True) if "<" in markup else markup
    return " ".join(text.split())[:_MAX_ENTRY_CHARS]


def _link(url: str | None) -> str:
    """A feed entry's link, with doubled slashes in the path collapsed
    (OpenAI's feed links to https://status.openai.com//incidents/...)."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    return parts._replace(path=re.sub(r"/{2,}", "/", parts.path)).geturl()


def _atom_link(item: ElementTree.Element, atom: str) -> str:
    for link in item.iter(atom + "link"):
        if link.get("rel") in (None, "alternate"):
            return _link(link.get("href"))
    return ""


def _utc_day(text: str | None) -> str:
    """The UTC calendar day of an RFC 822 or ISO 8601 timestamp."""
    if not text:
        return ""
    text = text.strip()
    if re.match(r"\d{4}-\d{2}-\d{2}", text):
        return text[:10]
    try:
        moment = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return ""
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC)
    return moment.date().isoformat()


def parse_feed(body: bytes) -> list[StatusEntry]:
    """Entries from an RSS 2.0 or Atom feed, or Microsoft's status JSON.
    Raises ValueError for anything else."""
    stripped = body.lstrip()
    if stripped.startswith((b"[", b"{")):
        return _parse_microsoft_json(stripped)
    try:
        root = ElementTree.fromstring(stripped)
    except ElementTree.ParseError as error:
        raise ValueError(f"not a status feed: {error}") from error
    atom = "{http://www.w3.org/2005/Atom}"
    entries = []
    for item in root.iter("item"):
        entries.append(
            StatusEntry(
                _plain(item.findtext("title") or ""),
                _plain(item.findtext("description") or ""),
                _utc_day(item.findtext("pubDate")),
                _link(item.findtext("link")),
            )
        )
    for item in root.iter(atom + "entry"):
        entries.append(
            StatusEntry(
                _plain(item.findtext(atom + "title") or ""),
                _plain(item.findtext(atom + "content") or item.findtext(atom + "summary") or ""),
                _utc_day(item.findtext(atom + "updated") or item.findtext(atom + "published")),
                _atom_link(item, atom),
            )
        )
    if root.tag not in {"rss", atom + "feed"}:
        raise ValueError(f"not a status feed: root element {root.tag}")
    return [e for e in entries if e.title]


def _parse_microsoft_json(body: bytes) -> list[StatusEntry]:
    """status.cloud.microsoft/api/posts/<area>: one post per service; only
    services with an incident message carry one."""
    try:
        posts = json.loads(body)
    except ValueError as error:
        raise ValueError(f"not a status feed: {error}") from error
    if not isinstance(posts, list):
        raise ValueError("not a status feed: expected a list of posts")
    entries = []
    for post in posts:
        if not isinstance(post, dict) or not str(post.get("Message") or "").strip():
            continue
        service = str(post.get("ServiceDisplayName") or "").strip()
        title = str(post.get("Title") or "").strip()
        entries.append(
            StatusEntry(
                f"{service}: {title}" if service and title else title or service,
                _plain(str(post["Message"])),
                _utc_day(str(post.get("LastUpdatedTime") or "")),
            )
        )
    return entries


def in_window(entry: StatusEntry, day: str | None) -> bool:
    """Whether an entry may report the outage of `day`. Undated entries and
    runs without a day are kept: the verifier still checks every claim."""
    if not day or not entry.published:
        return True
    edition = date.fromisoformat(day)
    first = (edition - timedelta(days=WINDOW_DAYS_BEFORE)).isoformat()
    last = (edition + timedelta(days=WINDOW_DAYS_AFTER)).isoformat()
    return first <= entry.published <= last


def relevant_entries(
    entries: Iterable[StatusEntry],
    provider: StatusProvider,
    named: Iterable[StatusProvider],
    day: str | None,
) -> list[StatusEntry]:
    """A named provider's own entries from the outage window. Any other
    provider's entries count only when they name an affected provider: an AI
    company's incident in the same hours is not, by itself, a link."""
    named = list(named)
    dated = [e for e in entries if in_window(e, day)]
    if provider in named:
        return dated
    return [e for e in dated if any(p.named_in(e.passage) for p in named)]


def is_ai_passage(source_url: str, text: str, config: StatusConfig) -> bool:
    """A passage shows an effect on AI when it comes from an AI company's
    status page or names an AI product or company."""
    return any(p.ai and p.owns(source_url) for p in config.providers) or config.mentions_ai(text)
