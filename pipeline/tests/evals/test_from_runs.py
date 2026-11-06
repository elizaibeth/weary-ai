import json

from evals.from_runs import cases_from_runs


def _record(day, stamp, titles, outcome):
    return {
        "day": day,
        "started_at": stamp,
        "discovered": [{"title": t, "url": f"https://x.example/{t}", "published": None} for t in titles],
        "tries": [{"headline": titles[0], "outcome": "verified"}] if outcome else [],
        "outcome": {"published": "slug", "live": True} if outcome else {"error": "no story"},
    }


def test_new_days_come_from_the_latest_run_and_known_days_are_skipped(tmp_path):
    (tmp_path / "2026-11-05_130000.json").write_text(json.dumps(_record("2026-11-05", "t1", ["Old"], False)))
    (tmp_path / "2026-11-05_150000.json").write_text(json.dumps(_record("2026-11-05", "t2", ["New", "B"], True)))
    (tmp_path / "2026-11-04_130000.json").write_text(json.dumps(_record("2026-11-04", "t0", ["Known"], True)))
    (tmp_path / "2026-11-06_130000.json").write_text(json.dumps({"day": "2026-11-06", "discovered": [], "tries": []}))

    [case] = cases_from_runs(tmp_path, known_days={"2026-11-04"})

    assert case["day"] == "2026-11-05" and case["source"] == "run log"
    assert [h["title"] for h in case["headlines"]] == ["New", "B"]  # the rerun replaced the earlier log
    assert case["published_title"] == "New"
