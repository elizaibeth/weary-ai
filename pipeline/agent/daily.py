"""Orchestrates one day's run: research -> evidence -> write -> illustrate
-> verify -> repair -> publish, falling back to the next ranked candidate
if one can't be verified. Contains no editorial logic of its own - that
lives in the modules it composes.

`Deps` bundles every external-provider override the modules below accept,
so tests can substitute fakes for Runware/OpenAI/TypeSafe without a long
parameter list on `run`.
"""

import logging
import os
import urllib.error
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from typesafe_sdk import TypeSafeAuthenticationError, TypeSafePermissionDeniedError

from agent import run_log
from agent.checking import repairer, verifier
from agent.evidence import packet
from agent.evidence.grounding import primary_sources
from agent.evidence.search import BraveSearch, Search
from agent.publishing import archive, illustrator, notifier, publisher
from agent.research import editions
from agent.research.candidate import Candidate
from agent.research.manual import candidate_from_url
from agent.services import costs
from agent.writing import house_style, writer

log = logging.getLogger(__name__)


class NoStory(ValueError):
    """A normal day without a publishable story; `details` say why."""

    def __init__(self, message: str, details: tuple[str, ...] = ()):
        super().__init__(message)
        self.details = details


class RunStopped(RuntimeError):
    """A credentials or configuration error that would fail every candidate."""


def _fatal_reason(error: Exception) -> str | None:
    """Name the service and setting to fix when retrying another candidate is pointless."""
    if isinstance(error, (TypeSafeAuthenticationError, TypeSafePermissionDeniedError)):
        return "TypeSafe rejected the API key: check the TYPESAFE_API_KEY secret"
    if isinstance(error, urllib.error.HTTPError) and "runware.ai" in (error.url or ""):
        if error.code in {401, 403}:
            return "Runware rejected the API key: check the RUNWARE_API_KEY secret"
        if error.code == 402:
            return "Runware account has no credit: top up the Runware balance"
        if error.code == 400:
            return "Runware rejected the request (often a retired model ID): check the WEARY_*_MODEL variables"
    return None


def _given(**overrides):
    """Keyword arguments for the overrides that are set, so each module keeps its own default."""
    return {name: value for name, value in overrides.items() if value is not None}


def _describe(error: Exception) -> str:
    return str(error) if isinstance(error, ValueError) else f"{type(error).__name__}: {error}"


def _auto_publish_default() -> bool:
    return os.environ.get("WEARY_AUTO_PUBLISH", "false").strip().lower() == "true"


@dataclass
class Deps:
    research_client: editions.Client | None = None
    research_recent_client: Callable[[datetime], str] | None = None
    evidence_fetch: packet.Fetcher | None = None
    evidence_search: Search | None = None
    writer_client: writer.Client | None = None
    illustrator_client: illustrator.Client | None = None
    verifier_system_one: verifier.SystemOne | None = None
    repairer_client: repairer.Client | None = None
    # Sunday paper discovery. When unset, it runs only with real discovery
    # (no injected research client), so tests never reach the network.
    paper_survey: Callable[[str], list[Candidate]] | None = None
    # Saturday opinion column, under the same rule as paper_survey.
    opinion_survey: Callable[[str], list[Candidate]] | None = None
    # Hosts that refused access during this run; shared by every candidate.
    blocked_hosts: set[str] = field(default_factory=set)


PAPER_SERIES = "Research paper of the week"
OPINION_SERIES = "Opinion"
_SERIES = {"paper": PAPER_SERIES, "opinion": OPINION_SERIES}


def _is_saturday(day: str) -> bool:
    return date.fromisoformat(day).weekday() == 5


def _check_relevance(candidate, draft, deps: Deps) -> bool:
    # A column argues across several stories; there is no single event to match.
    if candidate.kind == "opinion":
        return True
    return verifier.check_relevance(
        candidate.headline, candidate.evidence_summary, draft, **_given(system_one=deps.verifier_system_one)
    )


def _opinion_evidence(candidate, deps: Deps, as_of_day: str | None) -> packet.EvidencePacket:
    """Each discussed story's primary sources, gathered under its own headline
    so relevance checks match, then merged into one packet."""
    sources: list[packet.Source] = []
    diagnostics: list[str] = []
    limits = replace(packet.EvidenceLimits.from_env(), max_sources=2, max_searches=1)
    for i, (title, urls) in enumerate(candidate.parts):
        part = Candidate(f"{candidate.id}-{i}", title, urls, 1.0, kind="news")
        gathered = packet.gather(
            part,
            deps.evidence_fetch,
            search=None,  # the published story already found its primary sources
            as_of_day=as_of_day,
            limits=limits,
            blocked_hosts=deps.blocked_hosts,
        )
        known = {s.url for s in sources}
        sources.extend(s for s in gathered.sources if s.url not in known)
        diagnostics.extend(gathered.diagnostics)
    outcome = "ready" if sources else "no_primary_source"
    return packet.EvidencePacket(tuple(sources), tuple(s.text for s in sources), outcome, tuple(diagnostics))


def _is_sunday(day: str) -> bool:
    return date.fromisoformat(day).weekday() == 6


def _log_judgments(results) -> None:
    for r in results:
        verdict = "SUPPORTED" if r.verified else "UNSUPPORTED"
        log.info("[%s field=%s support_probability=%.2f] %r", verdict, r.field, r.confidence, r.claim[:120])
        if r.reason:
            log.info("reason: %s", r.reason)


def _drop_failed_arguments(draft, results):
    """An opinion argument that adds a fact is removed; its verified facts stay."""
    failed = {r.claim for r in results if r.field == "argument" and not r.verified}
    if not failed:
        return draft
    log.info("removing %s opinion argument(s) that added facts", len(failed))
    return replace(
        draft, paragraphs=tuple(replace(p, argument="") if p.argument in failed else p for p in draft.paragraphs)
    )


def _verify_and_repair(draft, evidence_packet, deps: Deps, opinion: bool):
    """Verify every claim, then repair and re-verify until the draft passes or
    stops improving. Returns (draft, results, repaired)."""
    # Reuse successful checks only for identical fields, text and evidence in
    # this candidate. A repaired claim or changed citation always gets checked.
    supported_cache: dict[tuple[str, str, str], verifier.ClaimResult] = {}

    def verify_once(d):
        results = verifier.verify(
            d,
            evidence_packet,
            supported_cache=supported_cache,
            opinion=opinion,
            **_given(system_one=deps.verifier_system_one),
        )
        _log_judgments(results)
        return results

    def verify_with_citations(d):
        results = verify_once(d)
        if opinion:
            # Rewrite arguments that added a fact; remove any that still do.
            for fence in (
                lambda d, r: repairer.repair_arguments(d, r, **_given(client=deps.repairer_client)),
                _drop_failed_arguments,
            ):
                fenced = fence(d, results)
                if fenced != d:
                    d = fenced
                    results = verify_once(d)
        supplemented = repairer.supplement_citations(d, results, evidence_packet)
        if supplemented != d:
            log.info("checking additional collected passages from the failed claims' cited sources...")
            d = supplemented
            results = verify_once(d)
        return d, results

    draft, results = verify_with_citations(draft)
    original_draft = draft
    attempts = 0
    while not verifier.passed(results) and attempts < repairer.MAX_ATTEMPTS and draft.paragraphs:
        unverified_count = sum(1 for r in results if not r.verified)
        log.info(
            "%s unverified claim(s), repairing (attempt %s/%s)...",
            unverified_count,
            attempts + 1,
            repairer.MAX_ATTEMPTS,
        )
        repaired = repairer.repair(draft, results, evidence_packet, **_given(client=deps.repairer_client))
        if repaired == draft:
            log.info("stopping repair: no valid change and no new evidence")
            break
        draft, results = verify_with_citations(repaired)
        attempts += 1
        remaining = sum(1 for r in results if not r.verified)
        if not verifier.passed(results) and remaining >= unverified_count:
            log.info("stopping repair: unsupported paragraph count did not improve; evidence is unchanged")
            break
    return draft, results, draft != original_draft


def _write_and_verify(candidate, deps: Deps, existing_tags: tuple[str, ...] = (), as_of_day: str | None = None):
    """Evidence -> write -> verify -> repair for one candidate. Returns
    (draft, verified, issues) - `issues` is a list of human-readable
    reasons, empty when `verified` is True. Deliberately does not generate
    an image: that's a real per-call cost, and every candidate rejected in
    favour of a later one would otherwise have paid for one and thrown it
    away. `run()` generates exactly one image, for whichever draft it
    ultimately keeps."""
    log.info("gathering packet...")
    # A paper is its own evidence: the abstract and full-text pages only, not
    # the cited papers its HTML links to.
    limits = replace(packet.EvidenceLimits.from_env(), max_sources=2) if candidate.kind == "paper" else None
    evidence_packet = (
        _opinion_evidence(candidate, deps, as_of_day)
        if candidate.kind == "opinion"
        else packet.gather(
            candidate,
            deps.evidence_fetch,
            search=deps.evidence_search,
            as_of_day=as_of_day,
            limits=limits,
            blocked_hosts=deps.blocked_hosts,
        )
    )
    if not any(s.role == "primary" and packet.source_passages(s) for s in evidence_packet.sources):
        raise ValueError(f"{evidence_packet.outcome}: skipping candidate before drafting")
    log.info("evidence: %s source(s)", len(evidence_packet.sources))

    log.info("drafting article...")
    draft = writer.draft(candidate, evidence_packet, existing_tags=existing_tags, **_given(client=deps.writer_client))
    log.info("draft: %r (%s paragraphs)", draft.title, len(draft.paragraphs))
    for sid, source in primary_sources(draft, evidence_packet).items():
        log.info("primary evidence [%s]: %s (%s chars)", sid, source.citation.url, len(source.text))

    log.info("checking topical relevance...")
    relevant = _check_relevance(candidate, draft, deps)
    if not relevant:
        # Grounded and verifiable isn't the same as on-topic - don't waste
        # a claim-verification/repair pass on an article that answered the
        # wrong question.
        log.info("-> drifted off-topic, skipping claim verification")
        deterministic = house_style.deterministic_issues(draft)
        issues = ["article drifted from the surveyed headline onto an unrelated topic"] + list(deterministic)
        return draft, False, issues

    log.info("verifying claims...")
    draft, results, repaired = _verify_and_repair(draft, evidence_packet, deps, opinion=candidate.kind == "opinion")

    # A repair can remove the actual news and leave only supported background.
    # Do not let a matching title alone keep such an article eligible for live publication.
    if repaired and draft.paragraphs and verifier.passed(results):
        relevant = _check_relevance(candidate, draft, deps)

    # `repairer` only re-sends flagged paragraphs to a model - it never
    # re-runs writer's own deterministic checks, so a repair could
    # reintroduce something like an em dash undetected. Re-check the final
    # draft here: a claim-verified but deterministically-flawed draft must
    # still never count as verified (never publish live).
    deterministic = house_style.deterministic_issues(draft)
    verified = bool(draft.paragraphs) and verifier.passed(results) and not deterministic and relevant
    log.info("verified=%s%s", verified, f" (deterministic issues: {deterministic})" if deterministic else "")

    issues = list(deterministic)
    if not relevant:
        issues.append("repaired article no longer reports the surveyed event")
    if not draft.paragraphs:
        issues.append("no supported paragraphs remain after repair")
    issues.extend(f"unverified claim [{r.field}]: {r.claim}" for r in results if not r.verified)
    return draft, verified, issues


def run(
    root: Path,
    day: str,
    live: bool | None = None,
    deps: Deps | None = None,
    recent_window: bool = False,
    story_url: str | None = None,
) -> Path:
    """`recent_window=True` is for the live scheduled job: candidates come
    from a rolling recency window (last 12h, widening to 24h) ending now,
    rather than matching `day` as a calendar date - see
    `discovery.fetch_recent_headlines`. `day` is still used to label
    candidate ids and notifications either way."""
    deps = deps or Deps()
    if deps.evidence_search is None and deps.evidence_fetch is None and os.environ.get("BRAVE_SEARCH_API_KEY"):
        # Share the budget, in-memory cache and error stop across every candidate.
        deps.evidence_search = BraveSearch(root / ".weary" / "evidence" / "search")
    live = _auto_publish_default() if live is None else live
    mode = "manual" if story_url else "live" if recent_window else "backfill"
    record = run_log.new_record(day, mode)
    with costs.tracking() as run_costs:
        try:
            bundle = _run(root, day, live, deps, run_costs, recent_window, story_url, record)
            return bundle
        except Exception as error:
            record["outcome"] = {"error": _describe(error)[:500]}
            # One alert for every outcome without a story, including crashes such
            # as a rejected API key, which previously failed with no notification.
            if isinstance(error, (ValueError, RunStopped)):
                reason = str(error)
            else:
                fatal = _fatal_reason(error)
                reason = f"Stopped: {fatal}" if fatal else "Run crashed"
                reason += f" ({_describe(error)})"
            notifier.notify_failure(day, reason, run_costs, details=getattr(error, "details", ()))
            raise
        finally:
            try:
                log.info("run log: %s", run_log.write(root, record).name)
            except OSError as error:
                log.warning("could not write the run log: %s", error)


def _run(
    root: Path,
    day: str,
    live: bool,
    deps: Deps,
    run_costs: costs.RunCosts,
    recent_window: bool,
    story_url: str | None,
    record: dict,
) -> Path:
    posts_dir = root / "content" / "posts"
    week_before = (date.fromisoformat(day) - timedelta(days=7)).isoformat()
    yesterday = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    recent_titles = [s["title"] for s in archive.stories_between(posts_dir, week_before, yesterday)]

    if story_url:
        log.info("Selecting manual story for %s: %s", day, story_url)
        survey = [
            candidate_from_url(
                story_url, day, fetch=deps.evidence_fetch, cache_dir=root / ".weary" / "evidence" / "documents"
            )
        ]
    elif recent_window:
        log.info("Surveying candidates for %s (recent_window=True)...", day)
        now = datetime.now(UTC)
        survey = editions.survey_recent(
            now, recent_titles=recent_titles, trace=record, **_given(client=deps.research_recent_client)
        )
    else:
        log.info("Surveying candidates for %s (recent_window=False)...", day)
        historical_search = deps.evidence_search.on_day if isinstance(deps.evidence_search, BraveSearch) else None
        survey = editions.survey(
            day,
            historical_search=historical_search,
            recent_titles=recent_titles,
            trace=record,
            **_given(client=deps.research_client),
        )
    papers: list[Candidate] = []
    real_discovery = deps.research_client is None and deps.research_recent_client is None
    if not story_url and _is_sunday(day) and (deps.paper_survey or real_discovery):
        # Sunday is the research paper of the week; the day's news follows
        # as the fallback in case no paper can be verified.
        try:
            papers = (deps.paper_survey or editions.survey_papers)(day)
        except Exception as error:
            log.warning("paper survey FAILED: %s: %s; using news only", type(error).__name__, error, exc_info=True)
            if _fatal_reason(error):
                raise
        survey = papers + list(survey)
    if (
        not story_url
        and _is_saturday(day)
        and (deps.opinion_survey or real_discovery)
        and not archive.has_series_post(posts_dir, day, OPINION_SERIES)
    ):
        # Saturday is the opinion column on the week's stories; the day's
        # news follows as the fallback.
        try:
            base_url = os.environ.get("WEARY_BASE_URL", "https://weary.ai/")
            survey_opinion = deps.opinion_survey or (lambda d: editions.survey_opinion(d, posts_dir, base_url=base_url))
            opinions = survey_opinion(day)
        except Exception as error:
            log.warning("opinion survey FAILED: %s: %s; using news only", type(error).__name__, error, exc_info=True)
            if _fatal_reason(error):
                raise
            opinions = []
        survey = opinions + list(survey)
    candidates = []
    for c in survey:
        if archive.is_duplicate(c, posts_dir):
            log.info("duplicate, skipping: %r", c.headline)
            continue
        candidates.append(c)
    log.info("Found %s candidate(s) after dedup (%s surveyed)", len(candidates), len(survey))
    record["ranking"] = run_log.ranking_entries(candidates)
    if not candidates:
        raise NoStory(
            f"No candidates available for {day}",
            (
                f"all {len(survey)} ranked headline(s) were already published"
                if survey
                else "no headlines survived discovery and ranking (see the feed counts in the run log)",
            ),
        )

    cache_dir = root / ".weary" / "images"
    existing_tags = archive.published_tags(posts_dir)
    draft = origin_urls = None
    series: str | None = None
    verified = False
    issues: list[str] = []
    failures: list[str] = []
    for i, candidate in enumerate(candidates, start=1):
        log.info("[%s/%s] %r", i, len(candidates), candidate.headline)
        try:
            candidate_draft, candidate_verified, candidate_issues = _write_and_verify(
                candidate, deps, existing_tags, as_of_day=day
            )
        except Exception as e:
            # This candidate couldn't even produce a draft (a provider
            # error, a malformed model response, ...) - it's unusable, not
            # merely unverified. Move on to the next candidate rather than
            # aborting the whole day.
            # A ValueError is an expected skip (no primary source, bad model reply);
            # anything else is a bug or outage, so keep its traceback.
            log.warning("FAILED: %s: %s", type(e).__name__, e, exc_info=not isinstance(e, ValueError))
            fatal = _fatal_reason(e)
            if fatal:
                # Every remaining candidate would fail the same way; stop
                # before spending more model calls.
                raise RunStopped(f"Stopped: {fatal} ({_describe(e)})") from e
            failures.append(f"{candidate.headline[:90]}: {_describe(e)[:240]}")
            record["tries"].append(run_log.try_entry(candidate, "failed", _describe(e)))
            continue
        outcome = "verified" if candidate_verified else "unverified"
        record["tries"].append(run_log.try_entry(candidate, outcome, "; ".join(candidate_issues)))
        if not candidate_verified:
            failures.append(f"{candidate.headline[:90]}: drafted but not verified: {'; '.join(candidate_issues)[:240]}")
        draft, verified, issues = candidate_draft, candidate_verified, candidate_issues
        origin_urls = candidate.urls
        series = _SERIES.get(candidate.kind)
        if verified:
            break

    if draft is None:
        raise NoStory(f"No candidate for {day} could be drafted at all ({len(candidates)} tried)", tuple(failures))
    # `origin_urls` is always set in the same loop iteration as `draft`, so
    # this is never actually false - just making that invariant explicit
    # for the type checker (and as a safety net if that ever changes).
    assert origin_urls is not None

    log.info("generating image...")
    image = illustrator.illustrate(draft.image_prompt, cache_dir=cache_dir, **_given(client=deps.illustrator_client))

    # Every surveyed candidate failed verification: still publish, but only
    # ever as a forced draft, regardless of the `live` flag.
    is_live = live and verified
    log.info("Publishing (live=%s)...", is_live)
    bundle = publisher.publish(
        draft, image, live=is_live, posts_dir=posts_dir, origin_urls=origin_urls, day=day, series=series
    )
    record["outcome"] = {"published": bundle.name, "live": is_live}
    notifier.notify_published(draft, bundle.name, is_live, run_costs, issues=issues)
    return bundle
