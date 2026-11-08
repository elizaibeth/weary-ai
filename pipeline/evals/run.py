"""Rank every gold-set day with each ranking variant and score it.

    uv run python -m evals.run [--repeat 3] [--label nov-2026]

Each variant switches on one technique on top of the legacy ranking, then all
of them together, so each technique's effect is measured on its own. Model
replies are saved by model, prompt and sample number (`evals/replies/`), so a
rerun is free and variants that send the same prompt get the same reply: the
comparison is paired. Every sample sends the production prompt unchanged. Writes TREC run files and `summary.md` to
`evals/results/<label>/`.
"""

import argparse
import json
import logging
import statistics
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from agent.publishing.archive import stories_between
from agent.research import ranking
from agent.research.discovery import Headline
from agent.research.ranking_core import LEGACY, NEWS_PROMPT, RankingConfig, verify_rates
from evals.label import cached_complete, load_cases
from evals.metrics import evaluate, mean, read_qrels, write_run

HERE = Path(__file__).parent
POSTS = HERE.parents[1] / "content" / "posts"

# name -> (settings, what it changes in plain words)
VARIANTS = {
    "legacy": (LEGACY, "the old ranking"),
    "+cluster": (replace(LEGACY, cluster=True), "merging duplicate stories"),
    "+permutations": (replace(LEGACY, permutations=2), "ranking twice, shuffled"),
    "+expected-value": (replace(LEGACY, order="expected_value"), "expected-value order"),
    "+novelty": (replace(LEGACY, novelty_penalty=RankingConfig().novelty_penalty), "avoiding last week's topics"),
    "all": (RankingConfig(), "all of them together"),
}
# Offline there are no run logs to learn from, so every variant uses the prior pass rates.
PRIOR_RATES = verify_rates([])


def recent_titles(day: str) -> list[str]:
    start = (date.fromisoformat(day) - timedelta(days=7)).isoformat()
    end = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    return [s["title"] for s in stories_between(POSTS, start, end)]


def rank_case(
    case: dict, settings: RankingConfig, sample: int, template: str = NEWS_PROMPT
) -> tuple[list[tuple[str, float]], int]:
    """The ranked (url, key) list for one day, and how many model calls it needed."""
    calls = 0

    def complete(prompt: str, model: str) -> str:
        nonlocal calls
        calls += 1
        return cached_complete(prompt, model, sample)

    headlines = [Headline(h["title"], h["url"]) for h in case["headlines"]]
    raw = ranking.rank_headlines(case["day"], headlines, template, settings=settings, complete=complete)
    candidates = ranking.candidates_from_json(case["day"], raw, settings, recent_titles(case["day"]), rates=PRIOR_RATES)
    return [(c.urls[0], c.rank_key) for c in candidates], calls


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=3, help="samples per day, to measure model variance")
    parser.add_argument("--label", default="latest")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    qrels = read_qrels(HERE / "gold.qrels")
    cases = load_cases()
    out = HERE / "results" / args.label
    out.mkdir(parents=True, exist_ok=True)

    jobs = [(name, sample, case) for name in VARIANTS for sample in range(args.repeat) for case in cases]
    with ThreadPoolExecutor(2) as pool:  # Runware limits in-flight requests by reserved credit
        ranked = dict(
            zip(
                [(name, sample, case["day"]) for name, sample, case in jobs],
                pool.map(lambda job: rank_case(job[2], VARIANTS[job[0]][0], job[1]), jobs),
                strict=True,
            )
        )

    rows = []
    per_day: dict[str, list[dict[str, dict[str, float]]]] = {}
    for name in VARIANTS:
        samples, calls = [], []
        for sample in range(args.repeat):
            run = {case["day"]: ranked[name, sample, case["day"]][0] for case in cases}
            calls += [ranked[name, sample, case["day"]][1] for case in cases]
            write_run(run, out / f"{name.strip('+')}-{sample}.run", name.strip("+"))
            per_day.setdefault(name, []).append(evaluate(run, qrels))
            samples.append(mean(per_day[name][-1]))
        metric_names = list(samples[0])
        summary = {m: statistics.mean(s[m] for s in samples) for m in metric_names}
        spread = {m: (statistics.stdev(s[m] for s in samples) if len(samples) > 1 else 0.0) for m in metric_names}
        rows.append((name, summary, spread, statistics.mean(calls)))

    header = "| variant | " + " | ".join(rows[0][1]) + " | model calls/day |"
    lines = [
        f"# Ranking eval: {len(cases)} days x {args.repeat} samples",
        "",
        "Mean over samples (± standard deviation across samples). Gold labels: `gold.qrels`.",
        "",
        header,
        "|" + "---|" * (len(rows[0][1]) + 2),
    ]
    for name, summary, spread, calls_per_day in rows:
        cells = " | ".join(f"{summary[m]:.3f} ± {spread[m]:.3f}" for m in summary)
        lines.append(f"| {name} | {cells} | {calls_per_day:.1f} |")
    (out / "summary.md").write_text("\n".join(lines) + "\n")
    (out / "summary.json").write_text(
        json.dumps({n: {"mean": s, "sd": d, "calls": c} for n, s, d, c in rows}, indent=2) + "\n"
    )
    plain = plain_summary(per_day, len(cases), {name: c for name, _, _, c in rows})
    (out / "summary.txt").write_text(plain + "\n")
    print(plain)


def plain_summary(per_day: dict[str, list[dict[str, dict[str, float]]]], days: int, calls: dict[str, float]) -> str:
    """Old vs new ranking in plain words: how often the right story came first."""

    def day_rate(name: str, metric: str) -> dict[str, float]:
        samples = per_day[name]
        return {d: statistics.mean(sample[d][metric] for sample in samples) for d in samples[0]}

    def pct(name: str, metric: str) -> str:
        return f"{statistics.mean(day_rate(name, metric).values()):.0%}"

    old, new = day_rate("legacy", "P(rel=3)@1"), day_rate("all", "P(rel=3)@1")
    better = [d for d in old if new[d] > old[d] + 1e-9]
    worse = [d for d in old if new[d] < old[d] - 1e-9]
    lines = [
        f"Old ranking vs new ranking, on {days} past days.",
        "Answer key: every headline graded 0-3 by GPT-5.5 (evals/gold.qrels).",
        "",
        "                         Old    New",
        f"Best story first         {pct('legacy', 'P(rel=3)@1'):>4}   {pct('all', 'P(rel=3)@1'):>4}",
        f"A good story first       {pct('legacy', 'P(rel=2)@1'):>4}   {pct('all', 'P(rel=2)@1'):>4}",
        f"Model calls per day      {calls['legacy']:>4.0f}   {calls['all']:>4.0f}",
        "",
        f"The new ranking was better on {len(better)} days, worse on {len(worse)}"
        + (f" ({', '.join(worse)})" if worse else "")
        + f", the same on {days - len(better) - len(worse)}.",
        "",
        "Each new technique on its own (best story first; old ranking " + pct("legacy", "P(rel=3)@1") + "):",
    ]
    lines += [
        f"  {label:<30} {pct(name, 'P(rel=3)@1'):>4}"
        for name, (_, label) in VARIANTS.items()
        if name not in ("legacy", "all")
    ]
    lines += ["", "Full table: summary.md in this folder."]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
