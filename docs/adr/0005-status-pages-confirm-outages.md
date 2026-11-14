# 0005: Status pages confirm outages; they never find stories

**Status:** accepted

## Context

On 13 November 2026 Microsoft 365 was down for about 30 hours, and Weary
published a minor Google Cloud post instead. Discovery had found the outage
(WIRED's AI feed and SecurityWeek), but two rules stopped it:

1. The ranking sees headlines only, and "Microsoft 365 Crawls Back to Life
   After a 24-Hour Outage" does not read as AI news. Under the AI-only rule
   the model left it out. The articles said Copilot went down and that OpenAI
   and Anthropic could not reach Microsoft 365, which is an AI story.
2. No status page was on the allowlist, so the outage had no primary source.

Status pages publish dozens of minor incidents a day. As discovery sources
they would turn Weary into an outage tracker.

## Decision

- **Status pages are evidence only.** An outage is a candidate only when
  outlets report it. The provider's status feed then says what broke
  (`evidence/status_pages.toml` lists the providers, their feeds and
  aliases; `source_rules.toml` allows the domains).
- **An outage story is told from the AI side or not at all.** For an outage
  headline that names a listed provider, `packet.gather` also reads every AI
  company's status feed and keeps only the entries that name the failed
  provider. The packet must contain a passage that shows an effect on AI:
  one from an AI company's status page, or one that names an AI product. If
  not, the candidate fails with `no_ai_source`. Incidents at the same time
  that do not name the provider are not a link.
- **The article leads with the AI effect.** The writer is told to, and a
  draft whose first paragraph cites no AI passage is rejected, both at
  drafting and again after repair. The title names the service that failed
  and the AI companies, side by side in time ("Microsoft, OpenAI and
  Anthropic report errors during Microsoft 365 outage"), not as cause and
  effect unless a company's own entry says so. A draft title that misses
  either side gets a corrected retry, and so does a repaired one.
- **Status passages say who posted them** ("Anthropic status page: ..."),
  from the feed registry. Anthropic's entries say "Claude", so without this
  the verifier could not check a sentence attributed to Anthropic.
- **Citations are incident pages.** Each entry is cited by its own incident
  page, else the provider's status page (`page` in `status_pages.toml`), and
  the raw feed only as a last resort.
- **The ranking gets a second look.** For up to three headlines the ranking
  left out (outages of a listed provider first, then events covered by
  several outlets), a model reads the article and says whether it reports a
  concrete effect on AI. A "yes" counts only with a quote that is in the
  article and names AI. The day is then ranked again with each kept story's
  AI angle shown, so it is scored against the other stories, not on its own
  (`research/second_look.py`).
- **An outage of a listed provider is tried as an official candidate.** Its
  evidence is the providers' own status pages, so the low pass rate of
  reporting candidates (ADR 0003) does not apply to it.

## Consequences

- 13 November now gets Microsoft's incident record and the OpenAI and
  Anthropic "Microsoft 365 connector" entries as evidence
  (`tests/evidence/test_status_pages.py`, from the real feeds). Replays of
  that day with the logged headlines published the outage in 3 of the last 4; in
  context the ranking scored it 0.33 to 0.72, so a quiet day's official
  story can still lead.
- Up to three extra model calls and article fetches a day, plus two ranking
  calls on days with a kept story, all on the mini model.
- Some status pages have no readable feed. Microsoft's status page is a
  JavaScript app; its JSON endpoint (`/api/posts/m365Consumer`) is used
  instead and covers consumer Microsoft 365 only. Azure's feed shows current
  incidents only, so a backfill sees nothing there. Fastly, Mistral and
  Hugging Face have no usable feed.
- Feeds date an entry by its latest update, so an entry can be dated the day
  after the incident. Entries from two days before to one day after the
  edition count.
- An outage that hit no AI product is still not covered. That is the AI-only
  rule working, not a gap.
- The ranking prompt is unchanged except on days with a kept story, so the
  ranking eval is unaffected (its results reproduce exactly).
