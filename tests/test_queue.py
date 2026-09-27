import pytest

from ratica.docmodel import Block, Book
from ratica.queue import JobStore, translate_book


def make_book(*texts, kinds=None):
    kinds = kinds or ["paragraph"] * len(texts)
    return Book(source="x.pdf", title="x",
                blocks=[Block(id=f"b{i}", kind=k, text=t, page=1) for i, (t, k) in enumerate(zip(texts, kinds))])


class Recorder:
    """A stand-in translator: uppercases the text and remembers what it was asked."""

    def __init__(self, fail_after=None):
        self.calls = []
        self.fail_after = fail_after

    def __call__(self, text):
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise ConnectionError("engine stopped")
        self.calls.append(text)
        return text.upper()


def test_every_translatable_block_is_translated(tmp_path):
    book = make_book("one", "two")
    store = JobStore(tmp_path / "job.sqlite")
    translate_book(book, store, Recorder())
    assert store.translations() == {"b0": "ONE", "b1": "TWO"}


def test_code_blocks_are_not_sent_and_stay_unchanged(tmp_path):
    book = make_book("intro", "x = 1", kinds=["paragraph", "code"])
    rec = Recorder()
    store = JobStore(tmp_path / "job.sqlite")
    translate_book(book, store, rec)
    assert rec.calls == ["intro"]
    assert store.translations()["b1"] == "x = 1"


def test_identical_text_is_translated_once(tmp_path):
    book = make_book("same", "other", "same")
    rec = Recorder()
    translate_book(book, JobStore(tmp_path / "job.sqlite"), rec)
    assert sorted(rec.calls) == ["other", "same"]


def test_resumes_where_it_stopped(tmp_path):
    book = make_book("a", "b", "c", "d")
    db = tmp_path / "job.sqlite"
    with pytest.raises(ConnectionError):
        translate_book(book, JobStore(db), Recorder(fail_after=2))
    rec = Recorder()
    translate_book(book, JobStore(db), rec)
    assert sorted(rec.calls) == ["c", "d"]
    assert len(JobStore(db).translations()) == 4


def test_changed_block_text_is_translated_again(tmp_path):
    db = tmp_path / "job.sqlite"
    translate_book(make_book("old text"), JobStore(db), Recorder())
    rec = Recorder()
    store = JobStore(db)
    translate_book(make_book("new text"), store, rec)
    assert rec.calls == ["new text"]
    assert store.translations() == {"b0": "NEW TEXT"}


def test_shifted_blocks_reuse_earlier_translations(tmp_path):
    db = tmp_path / "job.sqlite"
    translate_book(make_book("alpha", "beta"), JobStore(db), Recorder())
    rec = Recorder()
    store = JobStore(db)
    translate_book(make_book("new first", "alpha", "beta"), store, rec)
    assert rec.calls == ["new first"]
    assert store.translations() == {"b0": "NEW FIRST", "b1": "ALPHA", "b2": "BETA"}


def test_parallel_slots_translate_everything(tmp_path):
    book = make_book(*[f"p{i}" for i in range(20)])
    store = JobStore(tmp_path / "job.sqlite")
    translate_book(book, store, Recorder(), slots=4)
    assert store.translations() == {f"b{i}": f"P{i}" for i in range(20)}


def test_broken_protection_is_retried_then_falls_back_to_source(tmp_path):
    book = make_book("Call parse_config() now.")
    calls = []

    def breaks_code(text):
        calls.append(text)
        return "Şimdi yapılandırmayı_ayrıştır() çağır."

    store = JobStore(tmp_path / "job.sqlite")
    translate_book(book, store, breaks_code)
    assert len(calls) == 2
    assert store.translations()["b0"] == "Call parse_config() now."
    assert store.status("b0") == "kept_source"


def test_an_answer_instead_of_a_translation_is_rejected(tmp_path):
    book = make_book("Explain why Python is a good programming language.")
    calls = []

    def answers_the_question(text):
        calls.append(text)
        return "Python'un öğrenilmesi kolaydır. " * 20 + "**Sonuç:** Python harika."

    store = JobStore(tmp_path / "job.sqlite")
    translate_book(book, store, answers_the_question)
    assert len(calls) == 2
    assert store.status("b0") == "kept_source"


def test_bold_markers_the_source_does_not_have_are_removed(tmp_path):
    book = make_book("Example input in bold.")
    store = JobStore(tmp_path / "job.sqlite")
    translate_book(book, store, lambda t: "Örnek girdi **kalın** olarak.")
    assert store.status("b0") == "done"
    assert store.translations()["b0"] == "Örnek girdi kalın olarak."


def test_keep_tags_are_removed_from_the_saved_translation(tmp_path):
    book = make_book("Call parse_config() now.")
    store = JobStore(tmp_path / "job.sqlite")
    translate_book(book, store, lambda t: t.replace("Call", "Çağır").replace(" now", " şimdi"))
    assert store.translations()["b0"] == "Çağır parse_config() şimdi."


def test_inline_code_found_in_the_pdf_is_protected(tmp_path):
    book = Book(source="x.pdf", title="x", blocks=[
        Block("b0", "paragraph", 'The statement print("Hi") greets.', 1, keep=['print("Hi")'])])
    rec = Recorder()
    translate_book(book, JobStore(tmp_path / "job.sqlite"), rec)
    assert rec.calls[0] == 'The statement <keep>print("Hi")</keep> greets.'


def test_stopping_leaves_the_rest_pending_and_resumes_later(tmp_path):
    book = make_book(*[f"p{i}" for i in range(10)])
    db = tmp_path / "job.sqlite"
    rec = Recorder()
    finished = translate_book(book, JobStore(db), rec, should_stop=lambda: len(rec.calls) >= 3)
    assert finished is False
    assert len(rec.calls) == 3
    rest = Recorder()
    assert translate_book(book, JobStore(db), rest) is True
    assert len(rest.calls) == 7


def test_progress_is_reported(tmp_path):
    seen = []
    translate_book(make_book("a", "b"), JobStore(tmp_path / "job.sqlite"), Recorder(),
                   on_progress=lambda done, total: seen.append((done, total)))
    assert seen[-1] == (2, 2)


def test_quotation_marks_around_the_source_are_kept():
    from ratica.queue import _clean
    assert _clean("“Simple ideas last.”", "Basit fikirler kalıcıdır.") == "“Basit fikirler kalıcıdır.”"
    assert _clean("“Hash Tables” is a short guide.", "“Hash Tabloları” kısa bir rehberdir.") == \
        "“Hash Tabloları” kısa bir rehberdir."
    assert _clean("Plain text.", "Düz metin.") == "Düz metin."


def test_a_section_number_before_a_short_title_is_kept_as_it_is():
    from ratica.queue import _translate_one
    seen = []

    def translate(text):
        seen.append(text)
        return "Haritalar Nasıl Yapılır"
    assert _translate_one("2 How Maps Are Made", translate, ()) == ("2 Haritalar Nasıl Yapılır", "done")
    assert seen == ["How Maps Are Made"]
    assert _translate_one("2.1 Measuring the ground", lambda t: "Zemini ölçmek", ())[0] == "2.1 Zemini ölçmek"
