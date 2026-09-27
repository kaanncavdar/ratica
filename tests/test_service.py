from ratica.docmodel import Block, Book
from ratica.service import Settings, estimate_seconds, load_settings, save_settings


def test_settings_round_trip(tmp_path):
    s = Settings(backend="cuda", server="/e/llama-server", model="/m/g.gguf", slots=6, words_per_second=42.0,
                 llama_build="b11211")
    save_settings(s, tmp_path / "config.json")
    assert load_settings(tmp_path / "config.json") == s


def test_missing_or_broken_settings_mean_not_set_up(tmp_path):
    assert load_settings(tmp_path / "none.json") is None
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    assert load_settings(tmp_path / "bad.json") is None


def test_settings_from_another_engine_build_are_stale(tmp_path):
    s = Settings(backend="cuda", server="s", model="m", slots=4, words_per_second=40.0, llama_build="b0001")
    save_settings(s, tmp_path / "config.json")
    assert load_settings(tmp_path / "config.json").is_current() is False


def test_estimate_counts_only_translatable_words():
    book = Book("x.pdf", "x", [Block("b0", "paragraph", "one two three four", 1),
                               Block("b1", "code", "x = 1 + 2 + 3", 1),
                               Block("b2", "heading", "five six", 1)])
    assert estimate_seconds(book, words_per_second=2.0) == 3.0


def test_estimate_skips_blocks_already_done():
    book = Book("x.pdf", "x", [Block("b0", "paragraph", "one two", 1), Block("b1", "paragraph", "three four", 1)])
    assert estimate_seconds(book, words_per_second=1.0, done_ids={"b0"}) == 2.0
