# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub:
**Security → Report a vulnerability** on this repository. Do not open a public
issue for a vulnerability.

Useful reports include a prompt injection that gets an unsupported claim
published, a way to make a non-allowlisted page count as evidence, or a leaked
secret.

## How Weary handles untrusted input

Weary gives text from the open web to language models. How it stops that text
from steering what is published, and which tests prove each defence, is in
[`docs/security/README.md`](docs/security/README.md).

## Secrets

API keys are kept in a local `.env` (gitignored) and in GitHub Actions secrets.
`gitleaks` scans every commit for secrets through pre-commit.
