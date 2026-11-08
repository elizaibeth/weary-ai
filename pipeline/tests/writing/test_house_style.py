"""House style rules that are checked in Python (`agent.house_style`)."""

from agent.writing import house_style


def test_replace_dashes_substitutes_em_and_en_dashes_and_double_hyphens():
    assert house_style.replace_dashes("word—word") == "word, word"
    assert house_style.replace_dashes("word — word") == "word, word"
    assert house_style.replace_dashes("word–word") == "word, word"
    assert house_style.replace_dashes("word -- word") == "word, word"
    assert house_style.replace_dashes("no dashes here") == "no dashes here"


def test_security_is_an_allowed_category():
    assert "Security" in house_style.ALLOWED_CATEGORIES


def test_passage_markers_are_removed_in_square_or_round_brackets():
    strip = house_style.strip_passage_markers
    assert strip("He pleaded guilty. [P1][P6]") == "He pleaded guilty."
    # Leaked into a published post on 2026-11-04.
    assert (
        strip("worked at the Justice Department, it said. (P1, P2, P4)") == "worked at the Justice Department, it said."
    )
    assert strip("Court documents say so (P3) and more.") == "Court documents say so and more."
    assert strip("A [ P2 , P10 ] mid-sentence") == "A mid-sentence"


def test_passage_markers_in_other_shapes_are_removed():
    strip = house_style.strip_passage_markers
    for marker in (
        "(P1 and P2)",
        "(P1; P2)",
        "(P1-P3)",
        "(P1–P3)",
        "(passage P1)",
        "(Passages P1, P2)",
        "(see P2)",
        "(p1)",
        "(P1 & P2)",
    ):
        assert strip(f"It said so {marker}.") == "It said so.", marker


def test_text_that_only_looks_like_a_marker_is_kept():
    strip = house_style.strip_passage_markers
    assert strip("the P100 respirator (P2 class) and PS5") == "the P100 respirator (P2 class) and PS5"
    assert strip("an (OPEC) quota") == "an (OPEC) quota"
