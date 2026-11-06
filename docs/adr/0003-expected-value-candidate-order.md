# 0003: Try candidates in expected-value order

**Status:** accepted; supersedes the rule "official sources scoring at least 0.5 first"

## Context

The pipeline tries ranked candidates one at a time until one passes
verification, and each failed attempt costs model calls and time. Official
sources pass far more often than reporting, so the old ranking put official
candidates scoring at least 0.5 first. The 0.5 was a guess, and the rule
ignored how much more likely an official source is to verify.

## Decision

Order candidates by `v − c / p`: `v` is the model's importance score, `p` the
chance a candidate of that source type verifies, and `c` the cost of one
attempt (0.1). Swapping two adjacent candidates changes the expected payoff by
`p_j·a_i − p_i·a_j` (with `a = p·v − c`), which gives this order: the
interchange argument behind Smith's rule. `p` starts at 0.8 for official and
0.25 for reporting sources, as a Beta prior of strength 4, and moves towards
the pass rates recorded in `pipeline/runs/`.

## Consequences

- On the gold set, this alone raised "best story first" from 54% to 58%,
  and to 63% combined with permutation averaging
  (`pipeline/evals/`). Its main benefit, fewer failed attempts, only shows in
  live runs, which the run logs now record.
- `c` is a judgement, not a measured value.
- `WEARY_RANKING=legacy` restores the old rule.
