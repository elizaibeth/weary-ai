# 0004: Discovery uses free, public sources only

**Status:** accepted

## Context

Paid data sources, such as the X API, would give earlier and wider coverage
but add a fixed monthly cost to a project that runs once a day.

## Decision

Candidate discovery uses only free, public sources: RSS and official
newsroom feeds, GDELT and Hugging Face Daily Papers. Brave Search is optional and capped at a few
requests per run (`WEARY_SEARCH_REQUESTS_PER_RUN`).
Paid services are limited to the models that write and check the story.

## Consequences

- No social-media signal. Wide coverage is estimated by counting the outlets
  that report the same event instead.
- Some sources cannot be read from GitHub Actions: openai.com returns 403, so
  OpenAI news arrives through reporting. `python -m agent.source_check` shows what is
  reachable.
- Duplicate stories are matched by word overlap, not embeddings, which would
  need a paid API. It catches few duplicates (see `pipeline/evals/README.md`).
