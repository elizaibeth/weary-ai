import pytest

from agent.evidence.retrieval import FetchedDocument
from agent.research.manual import candidate_from_url

URL = "https://wired.com/story/ai-release/"
HTML = '<meta property="article:published_time" content="2026-09-26"><article><h1>AI lab releases a model</h1><p>An artificial intelligence laboratory released its latest model with new evaluation results and a published technical report.</p></article>'


def test_manual_candidate_uses_page_title_and_preserves_original_and_redirect_urls(tmp_path):
    final = "https://www.wired.com/story/ai-release/"
    candidate = candidate_from_url(
        URL + "?utm_source=test",
        "2026-09-27",
        fetch=lambda u: FetchedDocument(final, HTML.encode()),
        cache_dir=tmp_path,
    )
    assert candidate.headline == "AI lab releases a model"
    assert set(candidate.urls) == {URL, final}
    assert candidate.importance_score == 1
    assert candidate.evidence_summary == ""


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/story",
        "http://localhost/story",
        "https://unknown.example/story",
        "https://wired.com.evil.example/story",
    ],
)
def test_unsupported_manual_urls_fail_before_fetch(url, tmp_path):
    def forbidden(url):
        raise AssertionError("Must not fetch an unsupported origin")

    with pytest.raises(ValueError):
        candidate_from_url(url, "2026-09-27", fetch=forbidden, cache_dir=tmp_path)


@pytest.mark.parametrize(
    "html,message",
    [
        (HTML.replace("2026-09-26", "2026-09-28"), "after edition date"),
        (HTML.replace("<h1>AI lab releases a model</h1>", ""), "headline"),
        ("<h1>Access denied</h1>", "access/error"),
    ],
)
def test_unusable_manual_articles_are_rejected(html, message, tmp_path):
    with pytest.raises(ValueError, match=message):
        candidate_from_url(URL, "2026-09-27", fetch=lambda u: html, cache_dir=tmp_path)


def test_manual_redirect_must_still_be_an_eligible_origin(tmp_path):
    with pytest.raises(ValueError, match="redirect"):
        candidate_from_url(
            URL,
            "2026-09-27",
            fetch=lambda u: FetchedDocument("https://unknown.example/story", HTML.encode()),
            cache_dir=tmp_path,
        )


def test_manual_primary_source_keeps_pdf_page_hint(tmp_path):
    url = "https://comptroller.war.gov/Portals/budget.pdf#page=53"
    candidate = candidate_from_url(url, "2026-09-27", fetch=lambda u: HTML, cache_dir=tmp_path)
    assert candidate.urls[0].endswith("#page=53")


def test_investing_url_is_reporting_not_primary_evidence(tmp_path):
    from agent.evidence.packet import is_reporting_url
    from agent.evidence.source_rules import eligible_rule, load_rules

    url = "https://www.investing.com/news/stock-market-news/nvidia-chips-4919047"
    candidate = candidate_from_url(url, "2026-09-27", fetch=lambda u: HTML, cache_dir=tmp_path)
    assert candidate.urls == (url,)
    assert is_reporting_url(url)
    assert eligible_rule(url, load_rules()) is None
