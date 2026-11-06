import pytest


@pytest.fixture(autouse=True)
def _no_real_run_history(tmp_path, monkeypatch):
    """Rank against an empty run history, so observed pass rates on disk never change a test."""
    monkeypatch.setattr("agent.research.ranking.RUNS_DIR", tmp_path / "runs")
