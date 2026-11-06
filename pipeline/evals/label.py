"""Draft graded labels for every gold-set headline with a stronger model.

`uv run python -m evals.label` grades the days in `cases.jsonl` that have no
labels yet, adds them to `evals/gold.qrels` (TREC qrels) and rewrites
`evals/review.md`. Grades already in `gold.qrels`, including ones corrected by
hand, are kept; `--all` regrades every day. The judge sees only the headlines and the rubric, never a
ranker's output or what Weary published, so the labels stay independent.
They are silver labels until a person reviews `review.md` and edits the qrels.
"""

import hashlib
import json
import os
import time
import urllib.error
from pathlib import Path

from agent.services import llm
from evals.metrics import read_qrels, write_qrels

HERE = Path(__file__).parent
# Committed, so anyone can rerun the evals without an API key and get the published numbers.
CACHE = HERE / "replies"
JUDGE_MODEL = os.environ.get("WEARY_EVAL_JUDGE_MODEL", "openai:gpt@5.5")

PROMPT = """You are grading candidate lead stories for an AI news site.

{rubric}

Day: {day}
Headlines (id | title | url):
{listing}

Return strict JSON: {{"grades": {{"<id>": 0}}}} with a grade for every id."""


def cached_complete(prompt: str, model: str, sample: int = 0) -> str:
    """Model replies are cached by model, prompt and sample number, so reruns
    cost nothing. The prompt is sent unchanged; `sample` only picks a separate
    cache entry, so repeats get fresh replies to exactly the production prompt."""
    key = model + prompt + (f"\0sample={sample}" if sample else "")
    path = CACHE / f"{hashlib.sha256(key.encode()).hexdigest()}.txt"
    if path.exists():
        return path.read_text()
    if not os.environ.get("RUNWARE_API_KEY"):
        # SystemExit, not an exception the ranking would catch and fall back from.
        raise SystemExit(
            "No saved reply for this prompt and RUNWARE_API_KEY is not set: run `set -a; . ./.env; set +a`."
        )
    for attempt in range(6):
        try:
            reply = llm.complete(prompt, model)
            break
        except urllib.error.HTTPError as error:
            # Runware reserves credit per in-flight request; wait for others to finish.
            if "concurrentRequestLimitExceeded" not in str(error) or attempt == 5:
                raise
            time.sleep(10 * (attempt + 1))
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(reply)
    return reply


def load_cases() -> list[dict]:
    return [json.loads(line) for line in (HERE / "cases.jsonl").read_text().splitlines() if line.strip()]


def grade_day(case: dict, rubric: str) -> dict[str, int]:
    listing = "\n".join(f"{i} | {h['title']} | {h['url']}" for i, h in enumerate(case["headlines"]))
    prompt = PROMPT.format(rubric=rubric, day=case["day"], listing=listing)
    for _ in range(2):
        try:
            grades = json.loads(cached_complete(prompt, JUDGE_MODEL))["grades"]
            return {h["url"]: max(0, min(3, int(grades[str(i)]))) for i, h in enumerate(case["headlines"])}
        except (ValueError, KeyError, TypeError):
            prompt += "\nReturn only the JSON object, with a grade for every id."
    raise ValueError(f"judge reply unusable for {case['day']}")


def main() -> None:
    import sys

    rubric = (HERE / "rubric.md").read_text()
    gold = HERE / "gold.qrels"
    qrels = {} if "--all" in sys.argv or not gold.exists() else read_qrels(gold)
    review = ["# Gold labels to review", "", "Edit `gold.qrels` to change a grade. Grade 3 = best lead.", ""]
    for case in load_cases():
        if case["day"] not in qrels:
            qrels[case["day"]] = grade_day(case, rubric)
        grades = qrels[case["day"]]
        titles = {h["url"]: h["title"] for h in case["headlines"]}
        review.append(f"## {case['day']} (Weary published: {case['published_title']})")
        for url, grade in sorted(grades.items(), key=lambda item: -item[1]):
            if grade >= 2:
                review.append(f"- **{grade}** {titles[url]} <{url}>")
        review.append(f"- {sum(1 for g in grades.values() if g < 2)} more graded 0-1")
        review.append("")
        counts = [list(grades.values()).count(g) for g in (3, 2, 1, 0)]
        print(f"{case['day']}: {counts[0]} best, {counts[1]} strong, {counts[2]} minor, {counts[3]} not a lead")
    write_qrels(qrels, HERE / "gold.qrels")
    (HERE / "review.md").write_text("\n".join(review))


if __name__ == "__main__":
    main()
