## Contributing

See `CONTRIBUTING.md` for commit/PR conventions and verification commands (all Python lives under `pipeline/`).

## Context7

When Context7 is available, query documentation only for exact IDs listed in `.context7lib`. Match documentation to installed versions. During planning, check API capabilities or constraints that affect the approach. During implementation, verify uncertain signatures, configuration, and behavior. During review, verify library-dependent findings against relevant documentation. Reuse evidence already gathered for the same version and question. For an unlisted library or unavailable service, use installed sources or official documentation and report unresolved uncertainty. Do not automatically add IDs, substitute another ID, or treat a library's presence on the list as approval to install it.

## Agent skills

### Issue tracker

Issues and specs live in GitHub Issues; use the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`) are unchanged. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout: `CONTEXT.md` + `docs/adr/` at the repo root, created lazily as decisions are made. See `docs/agents/domain.md`.
