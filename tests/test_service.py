import pytest

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


def test_estimate_adds_a_fixed_cost_per_block():
    book = Book("x.pdf", "x", [Block("b0", "item", "a. true", 1), Block("b1", "item", "b. false", 1),
                               Block("b2", "code", "x = 1", 1)])
    assert estimate_seconds(book, words_per_second=4.0, seconds_per_block=0.5) == 2.0


def test_settings_saved_before_the_block_cost_existed_still_load(tmp_path):
    (tmp_path / "old.json").write_text('{"backend": "cuda", "server": "s", "model": "m", "slots": 4, '
                                       '"words_per_second": 60.0, "llama_build": "b11211"}', encoding="utf-8")
    assert load_settings(tmp_path / "old.json").seconds_per_block == 0


def test_book_estimate_adds_real_text_margin_and_engine_start():
    from ratica.service import ENGINE_START_SECONDS, REAL_TEXT_FACTOR, book_estimate
    s = Settings(backend="cuda", server="s", model="m", slots=4, words_per_second=10.0, llama_build="b11211",
                 seconds_per_block=0.5)
    book = Book("x.pdf", "x", [Block("b0", "paragraph", " ".join(["w"] * 100), 1)])
    assert book_estimate(book, s) == (10 + 0.5) * REAL_TEXT_FACTOR + ENGINE_START_SECONDS


def test_real_translation_speed_is_learned():
    from ratica.service import learn_speed
    s = Settings(backend="cuda", server="s", model="m", slots=8, words_per_second=80.0, llama_build="b11211",
                 seconds_per_block=0.1)
    s2 = learn_speed(s, words=72000, seconds=2520)  # a real book: ~28.6 words/s
    assert s2.real_words_per_second == pytest.approx(28.57, abs=0.1)
    s3 = learn_speed(s2, words=70000, seconds=1750)  # next book: 40 words/s, averaged with the first
    assert 28.6 < s3.real_words_per_second < 40


def test_book_estimate_uses_the_learned_speed():
    from ratica.service import ENGINE_START_SECONDS, book_estimate
    s = Settings(backend="cuda", server="s", model="m", slots=8, words_per_second=80.0, llama_build="b11211",
                 seconds_per_block=0.1, real_words_per_second=20.0)
    book = Book("x.pdf", "x", [Block("b0", "paragraph", " ".join(["w"] * 200), 1)])
    assert book_estimate(book, s) == pytest.approx(10 + ENGINE_START_SECONDS)


def test_estimate_skips_blocks_already_done():
    book = Book("x.pdf", "x", [Block("b0", "paragraph", "one two", 1), Block("b1", "paragraph", "three four", 1)])
    assert estimate_seconds(book, words_per_second=1.0, done_ids={"b0"}) == 2.0
