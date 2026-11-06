# 0002: An independent verifier gates every published claim

**Status:** accepted

## Context

A writer model can state things its sources do not say, and it is a poor judge
of its own output. Asking the same model to check itself tends to repeat the
same mistake.

## Decision

Every paragraph, the headline and why_today are checked by a separate service,
TypeSafe's `system_one` classifier ("Jev", `checking/verifier.py`), against only
the passages that paragraph cites. The check fails closed: no evidence, missing
citations or secondary sources count as unsupported. A story goes live only if
every check passes; otherwise it is saved as a draft and Slack is alerted.
Failed paragraphs go to a repairer that may use only the same passages, and its
output is verified again.

## Consequences

- One mistake has to fool two different systems to reach the site. This is
  also the main defence against prompt injection (see `docs/security/`).
- Some days publish nothing live, because no candidate verifies. That is the
  intended trade: no story is better than a wrong one.
- It adds a paid dependency and a second API key.
