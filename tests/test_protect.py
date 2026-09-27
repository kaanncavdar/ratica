from ratica.protect import is_intact, protect, unprotect


def test_urls_are_kept():
    text, spans = protect("See https://docs.python.org/3/library/json.html for details.")
    assert text == "See <keep>https://docs.python.org/3/library/json.html</keep> for details."
    assert spans == ["https://docs.python.org/3/library/json.html"]


def test_function_calls_and_identifiers_are_kept():
    text, spans = protect("Call parse_config() or list.sort() on my_list.")
    assert spans == ["parse_config()", "list.sort()", "my_list"]
    assert "<keep>parse_config()</keep>" in text


def test_plain_words_are_not_kept():
    text, spans = protect("Hash tables map keys to values. Python is popular.")
    assert spans == []
    assert text == "Hash tables map keys to values. Python is popular."


def test_user_terms_are_kept():
    _, spans = protect("Linus Torvalds wrote Linux.", keep_terms=["Linus Torvalds"])
    assert spans == ["Linus Torvalds"]


def test_short_terms_match_whole_words_only():
    text, spans = protect("Set x to the next index.", keep_terms=["x"])
    assert text == "Set <keep>x</keep> to the next index."
    assert spans == ["x"]


def test_url_with_parentheses_is_one_span():
    _, spans = protect("Read https://en.wikipedia.org/wiki/Hash_(disambiguation) now.")
    assert spans == ["https://en.wikipedia.org/wiki/Hash_(disambiguation)"]


def test_trailing_sentence_punctuation_is_not_part_of_url():
    _, spans = protect("Visit https://example.com.")
    assert spans == ["https://example.com"]


def test_intact_when_every_span_survives():
    assert is_intact("Python'ın <keep>list.sort()</keep> metodu", ["list.sort()"])


def test_not_intact_when_a_span_is_changed():
    assert not is_intact("Python'ın liste.sırala() metodu", ["list.sort()"])


def test_unprotect_removes_tags():
    assert unprotect("Run <keep>git status</keep> now.") == "Run git status now."
