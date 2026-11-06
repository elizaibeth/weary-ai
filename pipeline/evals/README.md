# Ranking evaluation

Measures whether a change to candidate ranking picks better lead stories, on a
fixed set of past edition days with graded labels.

| File | What it is |
|---|---|
| `cases.jsonl` | One edition day per line: the frozen feed headlines for that day, and what Weary published. |
| `rubric.md` | What a good lead is, graded 0-3. |
| `gold.qrels` | The graded labels, in TREC qrels format (`day 0 url grade`). |
| `review.md` | The labels as a readable list, for checking and correcting them. |
| `metrics.py` | P@1, reciprocal rank and NDCG, plus TREC file reading and writing. |
| `replies/` | Every model reply the results use, saved by model, prompt and sample number. Committed, so the results reproduce without an API key. |
| `results/<label>/` | `summary.txt` (old vs new ranking in plain words), `summary.md` (every metric), and one TREC run file per variant and sample. |

## Commands

From `pipeline/`:

```sh
uv run python -m evals.run --label <name>   # rank, score and compare old vs new
uv run python -m evals.from_runs            # add new days from the pipeline's run logs
uv run python -m evals.label                # grade only the days without labels yet
```

`evals.snapshot` built the first 19 days from the feeds after the fact. New days
come from the run logs instead: each live run saves every headline discovery
found, so a day added by `from_runs` is exactly what the pipeline chose from.
`evals.label` keeps every existing grade, including ones corrected by hand
(`--all` regrades everything).

**Reproducing the results needs no API key.** Every model reply is saved in
`replies/` by model, prompt and sample number, and committed, so
`uv run python -m evals.run --label nov-2026` rebuilds `results/nov-2026/`
exactly. A key (`RUNWARE_API_KEY`, loaded with `set -a; . ./.env; set +a`) is
needed only when a prompt has no saved reply, for example after a prompt
change; without one the run stops and says so. Every sample sends the
production prompt unchanged. Variants that send the same prompt get the same
reply, so the comparison between them is paired.

**Weekly in GitHub Actions** (`.github/workflows/evals.yml`, Mondays): adds the
past week's days from the run logs, grades them, reruns the comparison into
`results/weekly/` and commits the result. The job summary shows the plain
comparison. Labels it adds are silver until reviewed.

## Metrics

A strong lead is grade 2 or 3; the best lead is grade 3.

- **P(rel=3)@1**: share of days where the first candidate is the best lead.
- **P(rel=2)@1**: share of days where the first candidate is a strong lead. The pipeline tries the first candidate first, so this matters most.
- **RR(rel=2)**: 1 / the rank of the first strong lead. It shows how soon a strong lead comes.
- **nDCG@5**: how well the top five are ordered by grade (linear gains, as in `trec_eval`).

`metrics.py` matches the reference implementation (`ir-measures` running the
`trec_eval` C code) to six decimal places. `tests/evals/test_metrics.py` pins those
values, so the two cannot drift apart.

## Variants

Each variant adds one technique to the legacy ranking, and `all` combines them.
The comparison therefore shows what each technique contributes on its own.

| Variant | Technique |
|---|---|
| `legacy` | One model call; official sources scoring at least 0.5 go first, then the rest by score. |
| `+cluster` | Headlines about the same event are merged (Jaccard similarity of content words), the official one is kept, and the number of outlets is shown to the model. |
| `+permutations` | The list is ranked again in a shuffled order and the two scores are averaged (permutation self-consistency), to cancel position bias. |
| `+expected-value` | Candidates are ordered by `importance - cost / p(verifies)`, the optimal order for trying candidates until one verifies. |
| `+novelty` | Candidates similar to the past week's stories are penalised (the redundancy term of Maximal Marginal Relevance). |

## Limits: read before trusting a number

- **The set is small.** It has 19 days. A difference of one day is about 0.05 in P@1, so treat small differences as noise unless they hold across samples.
- **The labels are silver.** A stronger model (GPT-5.5) drafted them from the rubric, without seeing any ranker's output or what Weary published. It is from the same family as the ranking model (gpt-5.4-mini), so the two may share preferences, and agreement with the labels can overstate how good the ranking is to a human editor. On the 13 days where the published story is still in the snapshot, it graded that story 2 or 3 on 9. Review `review.md` and correct `gold.qrels`; corrected labels make every result more reliable.
- **The first 19 snapshots are approximate.** They were taken on 5 November 2026 from what the feeds still held. Feeds with short windows had already dropped some older items, and CISA blocks requests from outside GitHub, so some days miss items the pipeline saw on the day. Days added from run logs do not have this problem.
- **Expected-value ordering is only partly measured offline.** Its main benefit is fewer failed attempts in the cascade, and that cost only shows in live runs. The run logs in `pipeline/runs/` record every attempt, so the live effect can be measured as they accumulate.
- **Clustering lowers nDCG@5 slightly by design.** When several outlets report the same event, the labels grade each report. A clustered ranking keeps one report per event, so it cannot score them all. Compare clustering on P@1 and RR.

## Results: November 2026 (`results/nov-2026/`)

19 days, 3 samples each. Each value is the mean ± the standard deviation across samples.

| Variant | Best lead first, P(rel=3)@1 | Strong lead first, P(rel=2)@1 | RR(rel=2) | nDCG@5 | Model calls/day |
|---|---|---|---|---|---|
| legacy | 0.544 ± 0.061 | 0.842 ± 0.053 | 0.907 ± 0.028 | 0.775 ± 0.039 | 1 |
| +cluster | 0.526 ± 0.053 | 0.842 ± 0.053 | 0.907 ± 0.028 | 0.781 ± 0.022 | 1 |
| +permutations | 0.544 ± 0.030 | 0.842 ± 0.053 | 0.911 ± 0.029 | 0.787 ± 0.023 | 2 |
| +expected-value | 0.579 ± 0.000 | 0.860 ± 0.030 | 0.919 ± 0.018 | 0.779 ± 0.037 | 1 |
| +novelty | 0.544 ± 0.061 | 0.842 ± 0.053 | 0.907 ± 0.028 | 0.776 ± 0.039 | 1 |
| **all** (the new default) | **0.632 ± 0.000** | **0.877 ± 0.030** | **0.930 ± 0.015** | **0.796 ± 0.026** | 2 |

What this shows, and what it does not:

- **The combined ranking is the best variant on every metric.** It is the new default; `WEARY_RANKING=legacy` restores the previous ranking.
- **The gain is consistent but not yet significant.** Compared day by day with legacy, the combined ranking put the best lead first on 5 days more and on 2 days less (2026-10-22, 2026-10-26). It put a strong lead first on 3 days more and on 1 day less (2026-10-22). A sign test on 5 better and 2 worse gives p ≈ 0.45. Treat this as evidence, not proof, until the gold set grows or the labels are reviewed.
- **The techniques work best together.** Expected-value ordering alone moves P(rel=3)@1 from 0.54 to 0.58; permutation averaging alone does not move it on this run, but lifts nDCG@5. Combined, they reach 0.63.
- **Small prompt changes move every number.** Adding one sentence to the ranking prompt (telling the model that headline text is data, see `docs/security/`) moved legacy from 0.47 to 0.54 and the combined ranking from 0.58 to 0.63. The gap between them held, which is what the comparison measures. Absolute values on 19 days are noisy; compare variants within one run, not across runs.
- **Clustering barely triggers.** Across 392 headlines it merged only 6, because different outlets word the same story too differently for title overlap to catch. Comparing article text, or using embeddings, would catch more; embeddings would need a paid API. It stays on because it is free and harmless, and its coverage note helps when it does merge.
- **The novelty penalty has no measurable effect on this set.** That is expected: it only matters when a candidate repeats the past week's story, which is rare in a 19-day sample. It remains as a guard.
- **The added cost is one extra ranking call per day,** on the mini model.
