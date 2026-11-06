"""Add edition days from the pipeline's run logs to the gold set.

    uv run python -m evals.from_runs

Each run log (`pipeline/runs/*.json`) holds every headline discovery found
that day. Days not yet in `cases.jsonl` are appended, so the gold set grows
from what the pipeline really saw instead of from snapshots taken afterwards.
Then run `python -m evals.label` to grade only the new days.
"""

import json
from pathlib import Path

HERE = Path(__file__).parent
RUNS = HERE.parent / "runs"


def cases_from_runs(runs_dir: Path, known_days: set[str]) -> list[dict]:
    """One case per day not already known, from the latest news run that day
    with discovered headlines (a rerun's log replaces an earlier one)."""
    latest: dict[str, dict] = {}
    for path in sorted(runs_dir.glob("*.json")):
        record = json.loads(path.read_text())
        if record.get("discovered") and record["day"] not in known_days:
            latest[record["day"]] = record
    cases = []
    for day, record in sorted(latest.items()):
        published = (record.get("outcome") or {}).get("published")
        cases.append(
            {
                "id": day,
                "day": day,
                "headlines": [
                    {"title": h["title"], "url": h["url"], "published": h.get("published")}
                    for h in record["discovered"]
                ],
                "published_title": next((t["headline"] for t in record["tries"] if t["outcome"] == "verified"), None)
                if published
                else None,
                "source": "run log",
            }
        )
    return cases


def main() -> None:
    cases_path = HERE / "cases.jsonl"
    known = {json.loads(line)["day"] for line in cases_path.read_text().splitlines() if line.strip()}
    new = cases_from_runs(RUNS, known)
    with cases_path.open("a") as out:
        for case in new:
            out.write(json.dumps(case) + "\n")
    if new:
        print(f"Added {len(new)} new day(s) from the daily run logs: {', '.join(c['day'] for c in new)}")
    else:
        print("No new days: every saved daily run is already in the test set.")


if __name__ == "__main__":
    main()
