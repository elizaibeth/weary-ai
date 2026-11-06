"""Metrics pinned to the reference implementation.

The expected values were produced once with `ir-measures` 0.4 (pytrec_eval, the
trec_eval C code) on exactly these files:
    uvx --python 3.12 --from ir-measures ir_measures q.qrels r.run \\
        'P(rel=3)@1' 'P(rel=2)@1' 'RR(rel=2)' 'nDCG@5' --by_query --places 6
"""

import pytest

from evals import metrics

QRELS = """d1 0 a 3
d1 0 b 2
d1 0 c 0
d1 0 e 1
d2 0 x 1
d2 0 y 3
d2 0 z 2
d3 0 m 0
d3 0 n 2
"""
RUN = """d1 Q0 c 1 4 t
d1 Q0 b 2 3 t
d1 Q0 a 3 2 t
d1 Q0 u 4 1 t
d2 Q0 y 1 3 t
d2 Q0 x 2 2 t
d2 Q0 z 3 1 t
d3 Q0 m 1 2 t
d3 Q0 q 2 1 t
"""
REFERENCE = {
    "d1": {"P(rel=3)@1": 0.0, "P(rel=2)@1": 0.0, "RR(rel=2)": 0.5, "nDCG@5": 0.579996},
    "d2": {"P(rel=3)@1": 1.0, "P(rel=2)@1": 1.0, "RR(rel=2)": 1.0, "nDCG@5": 0.972504},
    "d3": {"P(rel=3)@1": 0.0, "P(rel=2)@1": 0.0, "RR(rel=2)": 0.0, "nDCG@5": 0.0},
}


@pytest.fixture
def files(tmp_path):
    (tmp_path / "q.qrels").write_text(QRELS)
    (tmp_path / "r.run").write_text(RUN)
    return metrics.read_qrels(tmp_path / "q.qrels"), metrics.read_run(tmp_path / "r.run")


def test_per_query_scores_match_trec_eval(files):
    qrels, run = files
    for query, scores in metrics.evaluate(run, qrels).items():
        assert scores == pytest.approx(REFERENCE[query], abs=1e-6), query


def test_means_match_trec_eval(files):
    qrels, run = files
    assert metrics.mean(metrics.evaluate(run, qrels)) == pytest.approx(
        {"P(rel=3)@1": 0.333333, "P(rel=2)@1": 0.333333, "RR(rel=2)": 0.5, "nDCG@5": 0.5175}, abs=1e-6
    )


def test_run_files_round_trip_in_rank_order_with_decreasing_scores(tmp_path, files):
    _, run = files
    metrics.write_run(run, tmp_path / "out.run", "t")
    lines = (tmp_path / "out.run").read_text().splitlines()
    assert lines[0] == "d1 Q0 c 1 4 t" and lines[3] == "d1 Q0 u 4 1 t"  # trec_eval sorts by score
    assert [d for d, _ in metrics.read_run(tmp_path / "out.run")["d1"]] == ["c", "b", "a", "u"]


def test_qrels_round_trip(tmp_path, files):
    qrels, _ = files
    metrics.write_qrels(qrels, tmp_path / "out.qrels")
    assert metrics.read_qrels(tmp_path / "out.qrels") == qrels
