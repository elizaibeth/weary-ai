"""Ranking metrics and TREC file formats, in plain Python.

Definitions follow the standard literature so the numbers mean what they mean
elsewhere, and `tests/evals/test_metrics.py` pins values cross-checked once
against the reference implementation (`ir-measures`, which wraps `trec_eval`):

- Precision@k: the share of the top k that is relevant (grade >= min_grade;
  `ir-measures` writes this as P(rel=2)@1).
- Reciprocal rank: 1 / rank of the first relevant item (0 if none), RR(rel=2).
- NDCG@k (Jarvelin and Kekalainen, 2002), with linear gains as in trec_eval:
  DCG@k = sum(grade_i / log2(i + 1)) over ranks i = 1..k, divided by the DCG of
  the ideal ordering of all judged grades for that query.

Qrels hold judged grades (0-3 here); unjudged items count as grade 0.
"""

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

Qrels = dict[str, dict[str, int]]  # query -> doc -> grade
Run = dict[str, list[tuple[str, float]]]  # query -> [(doc, score)] in rank order


def precision_at(ranked: Sequence[str], grades: Mapping[str, int], k: int, min_grade: int = 1) -> float:
    return sum(1 for doc in ranked[:k] if grades.get(doc, 0) >= min_grade) / k


def reciprocal_rank(ranked: Sequence[str], grades: Mapping[str, int], min_grade: int = 1) -> float:
    return next((1 / i for i, doc in enumerate(ranked, 1) if grades.get(doc, 0) >= min_grade), 0.0)


def _dcg(gains: Iterable[int]) -> float:
    return sum(gain / math.log2(i + 1) for i, gain in enumerate(gains, 1))


def ndcg_at(ranked: Sequence[str], grades: Mapping[str, int], k: int) -> float:
    ideal = _dcg(sorted(grades.values(), reverse=True)[:k])
    return _dcg(grades.get(doc, 0) for doc in ranked[:k]) / ideal if ideal else 0.0


def evaluate(run: Run, qrels: Qrels, k: int = 5) -> dict[str, dict[str, float]]:
    """Per-query scores for every query that has judgements: is the first
    candidate the best lead (grade 3) or a strong one (grade >= 2), how soon
    the first strong lead comes, and graded NDCG@k."""
    results = {}
    for query, grades in qrels.items():
        ranked = [doc for doc, _ in run.get(query, [])]
        results[query] = {
            "P(rel=3)@1": precision_at(ranked, grades, 1, min_grade=3),
            "P(rel=2)@1": precision_at(ranked, grades, 1, min_grade=2),
            "RR(rel=2)": reciprocal_rank(ranked, grades, min_grade=2),
            f"nDCG@{k}": ndcg_at(ranked, grades, k),
        }
    return results


def mean(per_query: Mapping[str, Mapping[str, float]]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for scores in per_query.values():
        for name, value in scores.items():
            totals[name] += value
    return {name: total / len(per_query) for name, total in totals.items()} if per_query else {}


# --- TREC formats: whitespace-separated, so ids must not contain spaces. ---


def write_qrels(qrels: Qrels, path: Path) -> None:
    lines = [f"{q} 0 {doc} {grade}" for q, docs in sorted(qrels.items()) for doc, grade in docs.items()]
    path.write_text("\n".join(lines) + "\n")


def read_qrels(path: Path) -> Qrels:
    qrels: Qrels = defaultdict(dict)
    for line in path.read_text().splitlines():
        if line.strip():
            query, _, doc, grade = line.split()
            qrels[query][doc] = int(grade)
    return dict(qrels)


def write_run(run: Run, path: Path, tag: str) -> None:
    """trec_eval orders by score, not by the rank column, so scores are written
    as strictly decreasing values that preserve the given order exactly."""
    lines = [
        f"{q} Q0 {doc} {rank} {len(docs) - rank + 1} {tag}"
        for q, docs in sorted(run.items())
        for rank, (doc, _) in enumerate(docs, 1)
    ]
    path.write_text("\n".join(lines) + "\n")


def read_run(path: Path) -> Run:
    rows: dict[str, list[tuple[int, str, float]]] = defaultdict(list)
    for line in path.read_text().splitlines():
        if line.strip():
            query, _, doc, rank, score, _tag = line.split()
            rows[query].append((int(rank), doc, float(score)))
    return {q: [(doc, score) for _, doc, score in sorted(items)] for q, items in rows.items()}
