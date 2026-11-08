"""Ranking: candidates only from real headlines, retries and the unranked fallback,
primary-first ordering, and the paper and opinion choices (`agent.ranking`,
through `agent.research`)."""

import json
from datetime import UTC, datetime

from agent.research import discovery, editions
from agent.research.discovery import Headline
from agent.research.editions import _default_client
from agent.research.ranking_core import RankingConfig


def _client(candidates):
    def client(day: str) -> str:
        return json.dumps({"candidates": candidates})

    return client


def test_survey_returns_multiple_candidates():
    candidates = editions.survey(
        "2026-09-25",
        client=_client(
            [
                {"headline": "A", "url": "https://a.example", "evidence_summary": "e", "importance_score": 0.5},
                {"headline": "B", "url": "https://b.example", "evidence_summary": "e", "importance_score": 0.9},
                {"headline": "C", "url": "https://c.example", "evidence_summary": "e", "importance_score": 0.2},
                {"headline": "D", "url": "https://d.example", "evidence_summary": "e", "importance_score": 0.7},
            ]
        ),
    )
    assert len(candidates) == 4


def test_survey_ranks_by_importance_not_order_returned():
    candidates = editions.survey(
        "2026-09-25",
        client=_client(
            [
                {
                    "headline": "Popular but thin",
                    "url": "https://a.example",
                    "evidence_summary": "widely shared, no concrete consequence",
                    "importance_score": 0.3,
                },
                {
                    "headline": "Less popular but well-evidenced",
                    "url": "https://b.example",
                    "evidence_summary": "concrete regulatory consequence, well-sourced",
                    "importance_score": 0.9,
                },
            ]
        ),
    )
    assert candidates[0].headline == "Less popular but well-evidenced"
    assert candidates[0].importance_score > candidates[1].importance_score


def test_survey_returns_empty_list_when_no_candidates_found():
    candidates = editions.survey("2026-09-25", client=_client([]))
    assert candidates == []


def test_survey_recent_ranks_candidates_from_a_datetime_client():

    now = datetime(2026, 9, 27, 18, 0, tzinfo=UTC)

    def client(when):
        assert when == now
        return json.dumps(
            {
                "candidates": [
                    {"headline": "A", "url": "https://a.example", "evidence_summary": "e", "importance_score": 0.4},
                    {"headline": "B", "url": "https://b.example", "evidence_summary": "e", "importance_score": 0.8},
                ]
            }
        )

    candidates = editions.survey_recent(now, client=client)
    assert [c.headline for c in candidates] == ["B", "A"]
    assert candidates[0].id == "2026-09-27-1"  # "B" was index 1 before sorting by importance


def test_important_candidates_with_a_primary_source_url_are_tried_before_reporting(monkeypatch):
    monkeypatch.setenv("WEARY_RANKING", "legacy")
    raw = json.dumps(
        {
            "candidates": [
                {
                    "headline": "Reported",
                    "url": "https://techcrunch.com/x",
                    "evidence_summary": "e",
                    "importance_score": 0.9,
                },
                {
                    "headline": "Official",
                    "url": "https://openai.com/index/y",
                    "evidence_summary": "e",
                    "importance_score": 0.4,
                },
                {
                    "headline": "Official 2",
                    "url": "https://openai.com/index/z",
                    "evidence_summary": "e",
                    "importance_score": 0.6,
                },
            ]
        }
    )
    candidates = editions.survey("2026-09-25", client=lambda day: raw)
    # 0.4 is below PRIMARY_FIRST_MIN_IMPORTANCE, so it keeps its importance order.
    assert [c.headline for c in candidates] == ["Official 2", "Reported", "Official"]

    # Expected-value order: importance - 0.1 / pass rate (0.25 reporting, 0.8 official
    # before any run history), so a 0.9 reporting lead (0.50) edges out official 0.6 (0.475).
    monkeypatch.delenv("WEARY_RANKING")
    candidates = editions.survey("2026-09-25", client=lambda day: raw)
    assert [c.headline for c in candidates] == ["Reported", "Official 2", "Official"]
    assert [round(c.rank_key, 3) for c in candidates] == [0.5, 0.475, 0.275]


def _fake_runware_text_post(content: str):
    def fake_post(url, payload, headers, timeout):
        return json.dumps({"data": [{"text": content, "usage": {"promptTokens": 1, "completionTokens": 1}}]}).encode()

    return fake_post


def test_default_client_drops_candidates_with_a_url_not_in_the_real_feed(monkeypatch):
    monkeypatch.setattr(
        "agent.research.discovery.fetch_headlines",
        lambda day: [Headline("Real headline", "https://real.example/story")],
    )
    monkeypatch.setenv("RUNWARE_API_KEY", "test-key")

    content = json.dumps(
        {
            "candidates": [
                {
                    "headline": "Real headline",
                    "url": "https://real.example/story",
                    "evidence_summary": "e",
                    "importance_score": 0.9,
                },
                {
                    "headline": "Fabricated headline",
                    "url": "https://fabricated.example/not-a-real-feed-item",
                    "evidence_summary": "e",
                    "importance_score": 0.8,
                },
            ]
        }
    )
    monkeypatch.setattr("agent.services.llm._http.post", _fake_runware_text_post(content))

    raw = _default_client("2026-09-25")
    data = json.loads(raw)
    assert len(data["candidates"]) == 1
    assert data["candidates"][0]["headline"] == "Real headline"


def test_default_client_drops_a_candidate_whose_headline_was_not_copied_verbatim(monkeypatch):
    # A real URL paired with fabricated headline text (e.g. the model
    # editorializing about a sourcing gap instead of copying the actual
    # headline) must be dropped - URL membership alone isn't grounding.
    monkeypatch.setattr(
        "agent.research.discovery.fetch_headlines",
        lambda day: [Headline("Real headline", "https://real.example/story")],
    )
    monkeypatch.setenv("RUNWARE_API_KEY", "test-key")

    content = json.dumps(
        {
            "candidates": [
                {
                    "headline": "No primary documents available for this story",
                    "url": "https://real.example/story",
                    "evidence_summary": "e",
                    "importance_score": 0.9,
                }
            ]
        }
    )
    monkeypatch.setattr("agent.services.llm._http.post", _fake_runware_text_post(content))

    data = json.loads(_default_client("2026-09-25"))
    assert data["candidates"] == []
    # The run log still shows what discovery found, so a dropped story can be reviewed later.
    assert [d["url"] for d in data["discovered"]] == ["https://real.example/story"]
    assert data["passes"] == [{}, {}]  # both ranking passes kept nothing


def test_default_client_returns_no_candidates_when_no_headlines_are_found(monkeypatch):
    monkeypatch.setattr("agent.research.discovery.fetch_headlines", lambda day: [])
    raw = _default_client("2026-09-25")
    assert json.loads(raw) == {"candidates": []}


def test_unparseable_ranking_reply_is_retried_then_falls_back_to_unranked_headlines(monkeypatch):
    # Observed Oct 15-21: one non-JSON ranking reply discarded a day's real headlines.
    headlines = [Headline("First", "https://real.example/1"), Headline("Second", "https://real.example/2")]
    monkeypatch.setattr("agent.research.discovery.fetch_headlines", lambda day: headlines)
    calls = []
    monkeypatch.setattr("agent.research.ranking.llm.complete", lambda prompt, model: calls.append(1) or "")

    data = json.loads(_default_client("2026-09-25"))

    assert len(calls) == 2 * RankingConfig().permutations  # one retry per shuffled prompt
    assert [(c["headline"], c["url"]) for c in data["candidates"]] == [(h.title, h.url) for h in headlines]


def test_a_retried_ranking_reply_is_used_when_it_parses(monkeypatch):
    monkeypatch.setattr(
        "agent.research.discovery.fetch_headlines", lambda day: [Headline("Real", "https://real.example/r")]
    )
    good = json.dumps(
        {
            "candidates": [
                {"headline": "Real", "url": "https://real.example/r", "evidence_summary": "e", "importance_score": 0.7}
            ]
        }
    )
    replies = iter(["null", good, good])  # the first prompt's retry, then the shuffled prompt
    monkeypatch.setattr("agent.research.ranking.llm.complete", lambda prompt, model: next(replies))

    data = json.loads(_default_client("2026-09-25"))

    assert data["candidates"][0]["importance_score"] == 0.7


def test_ranking_prompt_marks_official_sources(monkeypatch):
    monkeypatch.setattr(
        "agent.research.discovery.fetch_headlines",
        lambda day: [
            Headline("Reported story", "https://techcrunch.com/2026/09/25/story/"),
            Headline("Official story", "https://openai.com/index/official-story"),
        ],
    )
    prompts = []
    monkeypatch.setattr(
        "agent.research.ranking.llm.complete", lambda prompt, model: prompts.append(prompt) or '{"candidates": []}'
    )
    _default_client("2026-09-25")
    assert "- Official story (https://openai.com/index/official-story) [official source]" in prompts[0]
    assert "- Reported story (https://techcrunch.com/2026/09/25/story/)\n" in prompts[0]


def test_survey_papers_returns_paper_candidates_with_full_text_links(monkeypatch):
    monkeypatch.setattr(
        discovery,
        "fetch_weekly_papers",
        lambda day, fetch: [Headline("Big result", "https://arxiv.org/abs/2611.00002")],
    )
    prompts = []
    reply = json.dumps(
        {
            "candidates": [
                {
                    "headline": "Big result",
                    "url": "https://arxiv.org/abs/2611.00002",
                    "evidence_summary": "e",
                    "importance_score": 0.8,
                }
            ]
        }
    )
    monkeypatch.setattr("agent.research.ranking.llm.complete", lambda prompt, model: prompts.append(prompt) or reply)

    [candidate] = editions.survey_papers("2026-11-01")

    assert candidate.kind == "paper"
    assert candidate.urls == ("https://arxiv.org/abs/2611.00002", "https://arxiv.org/html/2611.00002")
    assert "Research paper of the week" in prompts[0] and "[official source]" not in prompts[0]


def test_survey_opinion_picks_listed_stories_and_links_weary_posts(monkeypatch, tmp_path):
    stories = [
        {
            "slug": "s-1",
            "date": "2026-10-26",
            "title": "Story one",
            "description": "d",
            "source_urls": ("https://www.anthropic.com/news/a",),
        },
        {
            "slug": "s-2",
            "date": "2026-10-27",
            "title": "Story two",
            "description": "d",
            "source_urls": ("https://blog.google/b",),
        },
        {"slug": "s-3", "date": "2026-10-28", "title": "Story three", "description": "d", "source_urls": ()},
    ]
    seen = {}
    monkeypatch.setattr(
        "agent.publishing.archive.stories_between",
        lambda posts_dir, first, last: seen.update(range=(first, last)) or stories,
    )
    reply = json.dumps(
        {
            "theme": "Labs sell to governments",
            "thesis": "The pitch is reach, not capability.",
            "stories": ["s-2", "invented", "s-1"],
        }
    )
    monkeypatch.setattr("agent.research.ranking.llm.complete", lambda prompt, model: reply)

    [candidate] = editions.survey_opinion("2026-10-31", tmp_path)

    assert seen["range"] == ("2026-10-25", "2026-10-30")  # Sunday to Friday
    assert candidate.kind == "opinion" and candidate.headline == "The pitch is reach, not capability."
    assert candidate.urls == ("https://weary.ai/posts/s-2/", "https://weary.ai/posts/s-1/")
    assert candidate.parts == (
        ("Story two", ("https://blog.google/b",)),
        ("Story one", ("https://www.anthropic.com/news/a",)),
    )


def test_survey_opinion_keeps_the_lead_story_and_at_most_two_more(monkeypatch, tmp_path):
    stories = [
        {
            "slug": f"s-{n}",
            "date": "2026-10-26",
            "title": f"Story {n}",
            "description": "d",
            "source_urls": (f"https://blog.google/{n}",),
        }
        for n in range(1, 6)
    ]
    monkeypatch.setattr("agent.publishing.archive.stories_between", lambda posts_dir, first, last: stories)
    reply = json.dumps(
        {"theme": "t", "thesis": "Google is selling agents it cannot control.", "stories": ["s-4", "s-1", "s-2", "s-3"]}
    )
    prompts = []
    monkeypatch.setattr("agent.research.ranking.llm.complete", lambda prompt, model: prompts.append(prompt) or reply)

    [candidate] = editions.survey_opinion("2026-10-31", tmp_path)

    assert candidate.urls == tuple(f"https://weary.ai/posts/s-{n}/" for n in (4, 1, 2))
    assert "ONE story" in prompts[0] and "lead story first" in prompts[0]


def test_survey_opinion_needs_two_stories(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "agent.publishing.archive.stories_between",
        lambda *args: [{"slug": "only", "date": "d", "title": "t", "description": "d", "source_urls": ("u",)}],
    )
    monkeypatch.setattr(
        "agent.research.ranking.llm.complete", lambda prompt, model: (_ for _ in ()).throw(AssertionError("no call"))
    )
    assert editions.survey_opinion("2026-10-31", tmp_path) == []


def test_observed_pass_rates_count_only_news_tries(tmp_path, monkeypatch):
    from agent.research import ranking

    runs = tmp_path / "logs"
    runs.mkdir()
    tries = [
        {"kind": "news", "official": True, "outcome": "verified"},
        {"kind": "news", "official": False, "outcome": "failed"},
        {"kind": "paper", "official": False, "outcome": "verified"},
    ]
    (runs / "2026-11-05_130000.json").write_text(json.dumps({"tries": tries}))
    (runs / "broken.json").write_text("{")
    assert ranking.observed_attempts(runs) == [(True, True), (False, False)]


def test_observed_attempts_reads_runs_dir_at_call_time(tmp_path, monkeypatch):
    from agent.research import ranking

    tries = [{"kind": "news", "official": True, "outcome": "verified"}]
    (tmp_path / "2026-11-05_130000.json").write_text(json.dumps({"tries": tries}))
    monkeypatch.setattr(ranking, "RUNS_DIR", tmp_path)
    assert ranking.observed_attempts() == [(True, True)]


def test_explicit_pass_rates_override_the_run_logs(tmp_path, monkeypatch):
    from agent.research import ranking
    from agent.research.ranking_core import RankingConfig

    tries = [{"kind": "news", "official": False, "outcome": "verified"}] * 50  # reporting would look certain
    (tmp_path / "2026-11-05_130000.json").write_text(json.dumps({"tries": tries}))
    monkeypatch.setattr(ranking, "RUNS_DIR", tmp_path)
    raw = json.dumps(
        {
            "candidates": [
                {"headline": "Lab ships model", "url": "https://openai.com/index/model/", "importance_score": 0.6},
                {
                    "headline": "Outlet reports model",
                    "url": "https://www.theverge.com/ai/model",
                    "importance_score": 0.7,
                },
            ]
        }
    )
    settings = RankingConfig(cluster=False, permutations=1, novelty_penalty=0.0)
    from_logs = ranking.candidates_from_json("d", raw, settings)
    from_priors = ranking.candidates_from_json("d", raw, settings, rates={"official": 0.8, "reporting": 0.25})
    assert from_logs[0].urls[0] != from_priors[0].urls[0]


def test_survey_hands_discovered_headlines_and_pass_scores_to_the_run_log():
    raw = json.dumps(
        {
            "candidates": [{"headline": "A", "url": "https://a.example/1", "importance_score": 0.7}],
            "discovered": [{"title": "A", "url": "https://a.example/1"}, {"title": "B", "url": "https://b.example/2"}],
            "passes": [{"https://a.example/1": 0.8}, {"https://a.example/1": 0.6}],
        }
    )
    trace: dict = {}
    [candidate] = editions.survey("2026-09-25", client=lambda day: raw, trace=trace)
    assert candidate.headline == "A"
    assert [d["url"] for d in trace["discovered"]] == ["https://a.example/1", "https://b.example/2"]
    assert trace["passes"] == [{"https://a.example/1": 0.8}, {"https://a.example/1": 0.6}]


def _rank_with_reply(monkeypatch, candidates):
    headlines = [
        Headline("CISA adds a CVE", "https://www.cisa.gov/a"),
        Headline("OpenAI raises", "https://t.example/o"),
    ]
    monkeypatch.setattr("agent.research.discovery.fetch_headlines", lambda day: headlines)
    monkeypatch.setattr(
        "agent.research.ranking.llm.complete", lambda prompt, model: json.dumps({"candidates": candidates})
    )
    return json.loads(_default_client("2026-11-06"))["candidates"]


def test_a_story_marked_not_about_ai_never_becomes_a_candidate(monkeypatch):
    kept = _rank_with_reply(
        monkeypatch,
        [
            {
                "headline": "CISA adds a CVE",
                "url": "https://www.cisa.gov/a",
                "ai_related": False,
                "importance_score": 0.9,
            },
            {"headline": "OpenAI raises", "url": "https://t.example/o", "ai_related": True, "importance_score": 0.6},
        ],
    )
    assert [c["url"] for c in kept] == ["https://t.example/o"]


def test_a_day_with_no_ai_story_has_no_candidates_rather_than_the_unranked_feed(monkeypatch):
    kept = _rank_with_reply(
        monkeypatch,
        [
            {
                "headline": "CISA adds a CVE",
                "url": "https://www.cisa.gov/a",
                "ai_related": False,
                "importance_score": 0.9,
            }
        ],
    )
    assert kept == []
