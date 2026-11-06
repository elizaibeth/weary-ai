"""The pure ranking core: plain inputs and outputs, no model, no fakes (`agent.ranking_core`)."""

import json

import pytest

from agent.evidence.source_rules import load_rules
from agent.research import ranking_core
from agent.research.discovery import Headline

RULES = load_rules()
OFFICIAL = Headline("Anthropic ships a model", "https://www.anthropic.com/news/model")
REPORTING = Headline("Startup raises money", "https://techcrunch.com/2026/10/01/startup")


def test_only_news_prompts_mark_official_sources():
    news = ranking_core.ranking_prompt("2026-10-01", [OFFICIAL, REPORTING], RULES, ranking_core.NEWS_PROMPT)
    papers = ranking_core.ranking_prompt("2026-10-01", [OFFICIAL], RULES, ranking_core.PAPER_PROMPT)
    assert f"- {OFFICIAL.title} ({OFFICIAL.url}) [official source]" in news
    assert f"- {REPORTING.title} ({REPORTING.url})\n" in news + "\n"
    assert "[official source]" not in papers
    assert "Do not settle on the first one." in news


@pytest.mark.parametrize("raw", ["not json", "[]", '{"candidates": "none"}'])
def test_a_reply_without_a_candidates_list_is_rejected(raw):
    with pytest.raises(ValueError):
        ranking_core.parse_ranking_reply(raw)


def test_proposals_must_copy_a_real_url_and_its_exact_title():
    proposed = [
        {"headline": OFFICIAL.title, "url": OFFICIAL.url},
        {"headline": "Anthropic ships a model, sources say", "url": OFFICIAL.url},  # rewritten title
        {"headline": "Invented story", "url": "https://example.com/invented"},
    ]
    assert ranking_core.grounded(proposed, [OFFICIAL, REPORTING]) == proposed[:1]


def test_unranked_keeps_every_real_headline_in_feed_order():
    assert [c["url"] for c in ranking_core.unranked([REPORTING, OFFICIAL])] == [REPORTING.url, OFFICIAL.url]


def test_important_official_candidates_are_tried_first_then_by_importance():
    proposals = [
        {"headline": "a", "url": REPORTING.url, "importance_score": 0.9},
        {"headline": "b", "url": OFFICIAL.url, "importance_score": 0.6},
        {"headline": "c", "url": "https://www.anthropic.com/news/minor", "importance_score": 0.3},
        {"headline": "d", "url": "https://techcrunch.com/x", "importance_score": 0.4},
    ]
    ordered = ranking_core.to_candidates("2026-10-01", proposals, RULES)
    assert [c.headline for c in ordered] == ["b", "a", "d", "c"]
    assert ordered[0].id == "2026-10-01-1"


def _story(slug, sources=("https://blog.google/x",)):
    return {"slug": slug, "date": "2026-10-26", "title": slug.title(), "description": "d", "source_urls": sources}


def test_an_opinion_reply_keeps_listed_stories_with_sources_lead_first():
    stories = [_story("lead"), _story("two"), _story("no-sources", ()), _story("three"), _story("four")]
    reply = json.dumps(
        {
            "theme": "t",
            "thesis": "Google oversells.",
            "stories": ["lead", "made-up", "no-sources", "two", "three", "four"],
        }
    )
    column = ranking_core.parse_opinion_reply(reply, "2026-10-31", stories, "https://weary.ai/")
    assert column.kind == "opinion" and column.headline == "Google oversells."
    assert column.urls == tuple(f"https://weary.ai/posts/{s}/" for s in ("lead", "two", "three"))


def test_an_opinion_reply_needs_a_thesis_and_two_listed_stories():
    stories = [_story("one"), _story("two")]
    with pytest.raises(ValueError):
        ranking_core.parse_opinion_reply(
            json.dumps({"theme": "t", "thesis": "x", "stories": ["one"]}), "d", stories, ""
        )
    with pytest.raises(KeyError):
        ranking_core.parse_opinion_reply(json.dumps({"theme": "t", "stories": ["one", "two"]}), "d", stories, "")


def test_headlines_about_the_same_event_cluster_and_prefer_the_official_source():
    reports = [
        Headline("Critical PHP flaw exploited at scale, CISA warns", "https://www.bleepingcomputer.com/php"),
        Headline("CISA warns critical PHP flaw exploited at scale", "https://www.cisa.gov/news-events/alerts/php"),
        Headline("Startup raises money for robots", "https://techcrunch.com/robots"),
    ]
    clusters = ranking_core.cluster(reports)
    assert sorted(len(c) for c in clusters) == [1, 2]
    reps = dict((h.url, n) for h, n in ranking_core.representatives(clusters, RULES))
    assert reps == {"https://www.cisa.gov/news-events/alerts/php": 2, "https://techcrunch.com/robots": 1}


def test_coverage_is_shown_to_the_ranker_only_when_several_outlets_reported_it():
    prompt = ranking_core.ranking_prompt(
        "d", [OFFICIAL, REPORTING], RULES, ranking_core.NEWS_PROMPT, {OFFICIAL.url: 3, REPORTING.url: 1}
    )
    assert (
        "Anthropic ships a model (https://www.anthropic.com/news/model) [official source] [reported by 3 outlets]"
        in prompt
    )
    assert "[reported by 1" not in prompt


def test_shuffles_are_reproducible_per_seed():
    items = [Headline(str(i), f"https://x.example/{i}") for i in range(8)]
    assert ranking_core.shuffled(items, "2026-10-21-1") == ranking_core.shuffled(items, "2026-10-21-1")
    assert sorted(ranking_core.shuffled(items, "a"), key=lambda h: h.title) == items


def test_averaging_counts_a_proposal_missing_from_one_reply_as_zero():
    first = [
        {"headline": "A", "url": "a", "importance_score": 0.8},
        {"headline": "B", "url": "b", "importance_score": 0.6},
    ]
    second = [{"headline": "B", "url": "b", "importance_score": 0.8}]
    assert [(c["url"], c["importance_score"]) for c in ranking_core.average([first, second])] == [
        ("b", 0.7),
        ("a", 0.4),
    ]


def test_pass_rates_start_at_the_prior_and_move_with_evidence():
    assert ranking_core.verify_rates([]) == ranking_core.PRIOR_VERIFY_RATE
    rates = ranking_core.verify_rates([(False, True)] * 4)  # four reporting candidates all verified
    assert rates["reporting"] == (4 + 0.25 * 4) / 8 and rates["official"] == 0.8


def test_expected_value_order_weighs_importance_against_the_cost_of_a_likely_failure():
    # 0.8 reporting (p=0.25) vs 0.6 official (p=0.8): 0.8 - c/0.25 = 0.40 < 0.6 - c/0.8 = 0.475 at c=0.1.
    assert ranking_core.expected_value_key(0.8, 0.25, 0.1) < ranking_core.expected_value_key(0.6, 0.8, 0.1)
    assert ranking_core.expected_value_key(0.8, 0.25, 0.0) > ranking_core.expected_value_key(0.6, 0.8, 0.0)


def test_a_near_repeat_of_last_weeks_story_drops_below_a_fresh_one():
    proposals = [
        {
            "headline": "Google rolls out Gemini agents to testers",
            "url": "https://techcrunch.com/a",
            "importance_score": 0.7,
        },
        {
            "headline": "EU fines chipmaker over AI export breach",
            "url": "https://techcrunch.com/b",
            "importance_score": 0.65,
        },
    ]
    config = ranking_core.RankingConfig()
    fresh = ranking_core.to_candidates("d", proposals, RULES, config)
    assert fresh[0].headline.startswith("Google")
    repeat = ranking_core.to_candidates("d", proposals, RULES, config, recent_titles=["Google rolls out Gemini agents"])
    assert repeat[0].headline.startswith("EU")
