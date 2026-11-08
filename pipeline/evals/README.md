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

- **The set is small.** It has 20 days. A difference of one day is about 0.05 in P@1, so treat small differences as noise unless they hold across samples.
- **The labels are silver.** A stronger model (GPT-5.5) drafted them from the rubric, without seeing any ranker's output or what Weary published. It is from the same family as the ranking model (gpt-5.4-mini), so the two may share preferences, and agreement with the labels can overstate how good the ranking is to a human editor. On the 13 days where the published story is still in the snapshot, it graded that story 2 or 3 on 9. Review `review.md` and correct `gold.qrels`; corrected labels make every result more reliable.
- **The first 19 snapshots are approximate.** They were taken on 5 November 2026 from what the feeds still held. Feeds with short windows had already dropped some older items, and CISA blocks requests from outside GitHub, so some days miss items the pipeline saw on the day. Days added from run logs do not have this problem.
- **Expected-value ordering is only partly measured offline.** Its main benefit is fewer failed attempts in the cascade, and that cost only shows in live runs. The run logs in `pipeline/runs/` record every attempt, so the live effect can be measured as they accumulate.
- **Clustering lowers nDCG@5 slightly by design.** When several outlets report the same event, the labels grade each report. A clustered ranking keeps one report per event, so it cannot score them all. Compare clustering on P@1 and RR.

## Results: November 2026 (`results/nov-2026/`)

20 days, 3 samples each, AI-only labels (see "Prompt changes" below). Each value is the mean ± the standard deviation across samples.

| Variant | Best lead first, P(rel=3)@1 | Strong lead first, P(rel=2)@1 | RR(rel=2) | nDCG@5 | Model calls/day |
|---|---|---|---|---|---|
| legacy | 0.450 ± 0.087 | 0.767 ± 0.058 | 0.861 ± 0.028 | 0.846 ± 0.010 | 1 |
| +cluster | 0.433 ± 0.076 | 0.783 ± 0.076 | 0.869 ± 0.035 | 0.840 ± 0.010 | 1 |
| +permutations | 0.483 ± 0.076 | 0.767 ± 0.029 | 0.869 ± 0.026 | 0.855 ± 0.021 | 2 |
| +expected-value | 0.467 ± 0.104 | 0.850 ± 0.000 | 0.906 ± 0.009 | 0.853 ± 0.013 | 1 |
| +novelty | 0.450 ± 0.087 | 0.750 ± 0.050 | 0.854 ± 0.023 | 0.843 ± 0.012 | 1 |
| **all** (the default) | **0.500 ± 0.050** | 0.833 ± 0.058 | 0.901 ± 0.032 | 0.850 ± 0.014 | 2 |

What this shows, and what it does not:

- **The combined ranking puts the best lead first most often** (0.50 against 0.45 for legacy). It is the default; `WEARY_RANKING=legacy` restores the previous ranking.
- **It is not best on every metric.** Expected-value ordering alone is slightly ahead on strong lead first and RR, and permutation averaging alone on nDCG@5. The differences are within one standard deviation.
- **The gain is small and not significant.** Day by day, the combined ranking was better than legacy on 4 days and worse on 2 (2026-10-08, 2026-10-21). A sign test on 4 against 2 gives p ≈ 0.69. Treat it as weak evidence until the gold set grows or the labels are reviewed.
- **The prompt matters far more than the ranking technique.** Making the prompt AI-only moved best lead first from 0.22 to 0.50; the ranking techniques together add about 0.05.
- **Clustering barely triggers.** Across 392 headlines it merged only 6, because different outlets word the same story too differently for title overlap to catch. Comparing article text, or using embeddings, would catch more; embeddings would need a paid API. It stays on because it is free and harmless, and its coverage note helps when it does merge.
- **The novelty penalty has no measurable effect on this set.** That is expected: it only matters when a candidate repeats the past week's story, which is rare in a 20-day sample. It remains as a guard.
- **The added cost is one extra ranking call per day,** on the mini model.

Before the AI-only change, with the old labels (security stories in scope) and 19 days, the combined ranking scored 0.63 against 0.54 for legacy. Those numbers are in git history; they are not comparable with the table above, because the labels changed.

## Prompt changes (`results/ai-only-prompt/`)

`uv run python -m evals.prompts` ranks every day with the production settings once per prompt in `PROMPTS`, and also counts **off-topic first**: days where the first candidate is graded 0. `picks.md` lists each prompt's first pick per day.

Until November 2026 the prompt let a "major" security incident with no AI angle lead. In practice the model treated routine advisories as major: a CISA vulnerability notice led on 2026-11-06 and a spying plea on 2026-11-04. The rubric was changed to AI-only, every day was regraded, and three prompts were compared (20 days, 3 samples):

| Prompt | Best lead first | Strong lead first | nDCG@5 | Off-topic first |
|---|---|---|---|---|
| previous (security allowed) | 0.217 | 0.417 | 0.502 | 0.583 |
| AI-only rule | 0.533 | 0.850 | 0.816 | 0.033 |
| **current**: AI-only rule, `ai_related` flag and code check | 0.500 | 0.833 | **0.850** | **0.000** |

The current prompt picked a better first story than the previous one on 15 days and a worse one on 2 (2026-10-22 and 2026-10-27, where the previous prompt had led with a top AI-security story). The previous prompt is partly marked down by definition, because the labels now follow the AI-only policy; off-topic first is the cleanest measure. The code check costs nothing measurable and removes the remaining off-topic picks.
