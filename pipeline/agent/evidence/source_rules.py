"""Explicit origin/path eligibility and deterministic search vocabulary."""

import re
import tomllib
from collections import Counter
from dataclasses import dataclass
from fnmatch import fnmatchcase
from math import log
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_STOP_WORDS = set(
    "a an the this that its of for to in on at with and or as by from over after before into is are has have will new says said ai".split()
)
_TRACKING = {"fbclid", "gclid"}


@dataclass(frozen=True)
class SourceRule:
    domain: str
    paths: tuple[str, ...]
    kind: str
    aliases: tuple[str, ...] = ()
    # fnmatch's "*" also matches "/", so nested paths are excluded explicitly
    # (e.g. Hugging Face community posts at /blog/<user>/<post>).
    exclude_paths: tuple[str, ...] = ()

    def matches(self, url: str) -> bool:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        return (
            parts.scheme in {"https", "http"}
            and not parts.username
            and not parts.password
            and parts.port in {None, 80, 443}
            and (host == self.domain or host.endswith("." + self.domain))
            and any(fnmatchcase(parts.path or "/", pattern) for pattern in self.paths)
            and not any(fnmatchcase(parts.path or "/", pattern) for pattern in self.exclude_paths)
        )


def load_rules(path: Path | None = None) -> tuple[SourceRule, ...]:
    data = tomllib.loads((path or Path(__file__).with_name("source_rules.toml")).read_text())
    return tuple(
        SourceRule(
            s["domain"],
            tuple(s["paths"]),
            s["kind"],
            tuple(s.get("aliases", [])),
            tuple(s.get("exclude_paths", [])),
        )
        for s in data["sources"]
    )


def eligible_rule(url: str, rules: tuple[SourceRule, ...]) -> SourceRule | None:
    try:
        path = urlsplit(url).path.lower().rstrip("/")
        if path in {"", "/about", "/privacy", "/terms", "/contact", "/careers", "/news", "/blog"}:
            return None
        return next((rule for rule in rules if rule.matches(url)), None)
    except ValueError:
        return None


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Unsupported source URL")
    if parts.port not in {None, 80, 443}:
        raise ValueError("Unsupported source port")
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING
    ]
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or "/", urlencode(query), ""))


def terms(text: str) -> set[str]:
    # Retrieval aliases only: these never become assertions in the evidence.
    text = re.sub(r"\blie[\s-]+detect(?:or|ors|ion)\b", "polygraph", text.lower())
    text = re.sub(r"\b(?:pentagon|dod|department of defense)\b", "defense", text)
    return {t for t in re.findall(r"[a-z0-9]+", text) if (len(t) > 2 or t.isdigit()) and t not in _STOP_WORDS}


def passage_scores(texts: list[str], headline: str) -> list[float]:
    """Weight rare topic terms above vocabulary repeated throughout a document."""
    vocabulary = [terms(text) for text in texts]
    frequencies = Counter(term for block in vocabulary for term in block)
    topic = terms(headline)
    return [sum(log(1 + len(texts) / frequencies[t]) for t in block & topic) for block in vocabulary]


def relevance(text: str, headline: str) -> int:
    return len(terms(text) & terms(headline))


def mentions_subject(text: str, headline: str, rules: tuple[SourceRule, ...]) -> bool:
    """A named company/product must occur in the document, not just a search snippet.

    Curated aliases provide a conservative entity check without guessing proper
    names from title case. Headlines without a known entity retain topic scoring.
    """
    subjects = {
        alias
        for rule in rules
        if rule.kind == "company_statement"
        for alias in rule.aliases
        if re.search(r"\b" + re.escape(alias) + r"\b", headline, re.I)
    }
    return not subjects or any(re.search(r"\b" + re.escape(alias) + r"\b", text, re.I) for alias in subjects)


def queries(headline: str, rules: tuple[SourceRule, ...], limit: int = 3) -> list[str]:
    # Strip search operators/punctuation from input; policy supplies the domains.
    topic = " ".join(re.findall(r"[\w-]+", headline))[:240]
    matches = [r for r in rules if any(re.search(r"\b" + re.escape(a) + r"\b", headline, re.I) for a in r.aliases)]
    # Match the event's institution before broad entity aliases such as Pentagon.
    # A federal appeals story needs court records, not DCSA personnel guidance.
    court_story = bool(re.search(r"\b(court|appeals?|judge|ruling)\b", headline, re.I))
    supreme_story = bool(re.search(r"\bsupreme court\b", headline, re.I))
    preferred_court = "supremecourt.gov" if supreme_story else "uscourts.gov"
    matches.sort(
        key=lambda r: (
            court_story and r.kind != "court_document",
            court_story and r.kind == "court_document" and r.domain != preferred_court,
            r.kind == "company_statement",
            r.domain,
        )
    )
    domains = list(dict.fromkeys(r.domain for r in matches))
    result = [f"{topic} site:{domain}" for domain in domains[: max(0, limit - 1)]]
    documentary = bool(re.search(r"\b(court|appeals|budget|filing|paper)\b", headline, re.I))
    result.append(topic + (" filetype:pdf" if documentary else " official announcement"))
    return result[:limit]
