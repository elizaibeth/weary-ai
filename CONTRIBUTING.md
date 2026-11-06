# Contributing

## Commits and branches

Use concise imperative subjects:

```text
type(scope): change
```

Examples: `fix(auth): refresh expired tokens`, `docs: explain local setup`.

Use `type/short-topic` branch names, such as `feat/password-reset` or `fix/token-refresh`.

## Pull requests

Keep the title in commit-subject format. Explain the outcome, why it matters, and how it was verified. Link the issue when one exists. Keep unrelated cleanup out of the change.

## Attribution

Do not add AI or agent `Co-authored-by` trailers, generated-by messages, or agent signatures to commit messages (including squash and merge commits) or PR titles and descriptions. Preserve genuine human authorship and co-author credit.

## Issues

Issues and specs live in GitHub Issues. See `docs/agents/issue-tracker.md` for how agents use them and `docs/agents/triage-labels.md` for the triage labels.

Write an outcome-focused title. A bug ticket needs: the problem, expected behavior, reproduction steps, evidence (logs, versions, a minimal failing case), and acceptance criteria including a regression test. A feature ticket needs: the outcome, brief context on why it's needed, and observable acceptance criteria. Keep bug reproduction steps separate from feature acceptance criteria.

## Verification

All Python code lives under `pipeline/` (a Hugo static site occupies the repo root). Run these from `pipeline/` before requesting review:

```sh
uv sync --locked        # install locked dependencies
uv run pytest -q        # tests
uv run pytest --cov=agent --cov-report=term-missing -q   # tests with coverage
uv run ruff check .     # lint
uv run ruff format .    # format
uv run mypy             # type-check (agent/ only; tests/ is untyped)
uv run pip-audit        # dependency vulnerability audit
```

Report what ran and what could not run.

## Reviews and changelogs

Review comments state the location, problem, effect, and suggested correction. Changelog entries describe user-visible impact and follow the project's release process.
