import io
from urllib import request

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from agent.evidence.retrieval import DocumentFetcher, FetchedDocument, _CheckedRedirect, extract


def pdf_bytes(pages):
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    reference = writer._add_object(font)
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): reference})}
        )
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 12 Tf 50 700 Td ({escaped}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_magic_and_page_hint_reach_page_53_with_small_page_budget():
    pages = ["Ordinary background page."] * 60
    pages[52] = "Polygraph Next budget request seeks 30.3 million over five years."
    result = extract(
        FetchedDocument("https://official.example/budget.pdf", pdf_bytes(pages), "application/octet-stream"),
        page_hint=53,
        max_pdf_pages=3,
    )
    assert {b.page for b in result.blocks} == {52, 53, 54}
    assert any("Polygraph Next" in b.text and b.page == 53 for b in result.blocks)


def test_image_only_and_invalid_pdfs_fail_explicitly():
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    stream = io.BytesIO()
    writer.write(stream)
    for body in (stream.getvalue(), b"%PDF-this is invalid"):
        with pytest.raises(ValueError, match="extraction_failed: PDF"):
            extract(FetchedDocument("https://official.example/file", body, "application/pdf"))


def test_html_excludes_navigation_footer_and_scripts_and_preserves_body_links():
    html = b'<html><head><title>Official ruling</title><script>secret</script></head><body><nav><a href="https://shop.example/">Shop</a></nav><article><h1>Ruling</h1><p>The court stayed the order.</p><p><a href="/opinion?id=1&amp;view=full">Read opinion</a></p></article><footer>Junk</footer></body></html>'
    result = extract(FetchedDocument("https://official.example/news/order", html))
    assert result.title == "Ruling"
    assert result.links == (("https://official.example/opinion?id=1&view=full", "Read opinion"),)
    assert "secret" not in str(result.blocks)
    assert "Shop" not in str(result.blocks)
    assert "Junk" not in str(result.blocks)


def test_access_pages_empty_html_and_wrong_content_types_fail():
    for doc in (
        FetchedDocument("https://official.example", b"<title>Access denied</title>"),
        FetchedDocument("https://official.example", b""),
        FetchedDocument("https://official.example", b"data", "image/png"),
    ):
        with pytest.raises(ValueError, match="extraction_failed"):
            extract(doc)


def test_fetch_cache_preserves_final_url_hash_and_type(tmp_path, monkeypatch):
    calls = []

    class Response:
        url = "https://official.example/final"
        headers = type("Headers", (), {"get_content_type": lambda self: "application/pdf"})()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            return b"%PDF-snapshot"

    class Opener:
        def open(self, req, timeout):
            calls.append(req.full_url)
            return Response()

    monkeypatch.setattr("agent.evidence.retrieval.request.build_opener", lambda handler: Opener())
    fetch = DocumentFetcher(tmp_path, lambda url: url.startswith("https://official.example/"))
    first = fetch("https://official.example/request#page=53")
    second = fetch("https://official.example/request#page=54")
    assert first == second
    assert first.url == Response.url
    assert len(calls) == 1
    assert first.content_type == "application/pdf"
    assert first.fetched_at


def test_redirect_and_response_size_limits(tmp_path, monkeypatch):
    handler = _CheckedRedirect(lambda url: url.startswith("https://official.example/"))
    with pytest.raises(ValueError, match="redirect_rejected"):
        handler.redirect_request(
            request.Request("https://official.example/origin"), None, 302, "", {}, "https://unclassified.example/"
        )

    class Response:
        url = "https://official.example/file"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            return b"x" * size

    class Opener:
        def open(self, req, timeout):
            return Response()

    monkeypatch.setattr("agent.evidence.retrieval.request.build_opener", lambda handler: Opener())
    with pytest.raises(ValueError, match="byte limit"):
        DocumentFetcher(tmp_path, lambda url: True, max_bytes=10)("https://official.example/file")


def test_scholarly_citation_title_beats_a_breadcrumb_heading():
    from agent.evidence.retrieval import FetchedDocument, extract

    html = b"""<html><head><meta name="citation_title" content="UserArena:  A Benchmark">
<title>[2610.30932] UserArena</title></head><body><h1>Computer Science &gt; Information Retrieval</h1>
<p>We introduce UserArena, a benchmark for long-horizon shopping agents with production validation.</p></body></html>"""
    assert extract(FetchedDocument("https://arxiv.org/abs/2610.30932", html)).title == "UserArena: A Benchmark"


def test_a_teaser_article_card_does_not_hide_the_main_content():
    # CISA, DeepMind and The Hacker News pages yielded one teaser-card block.
    from agent.evidence.retrieval import FetchedDocument, extract

    story = "".join(
        f"<p>Paragraph {i} of the advisory explains the exploited vulnerability in detail.</p>" for i in range(12)
    )
    html = f"""<html><body><main><h1>Advisory</h1>{story}
<article><a href="/x">Related: another advisory</a></article></main></body></html>""".encode()
    blocks = extract(FetchedDocument("https://www.cisa.gov/news-events/alerts/x", html)).blocks
    assert len(blocks) >= 12


def test_a_real_article_element_is_still_preferred_over_page_chrome():
    from agent.evidence.retrieval import FetchedDocument, extract

    story = "".join(f"<p>Story paragraph {i} with the reported facts.</p>" for i in range(10))
    html = f"""<html><body><main><article><h1>Story</h1>{story}</article>
<p>Short sidebar note.</p></main></body></html>""".encode()
    texts = [b.text for b in extract(FetchedDocument("https://example.com/story", html)).blocks]
    assert "Short sidebar note." not in " ".join(texts)
