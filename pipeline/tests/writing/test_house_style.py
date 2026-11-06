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
