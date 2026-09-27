import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ratica import gui  # noqa: E402
from ratica.service import Settings  # noqa: E402

READY = Settings(backend="cuda", server="s", model="m", slots=2, words_per_second=10.0, llama_build="b11211")


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setattr(gui, "load_settings", lambda: READY)
    monkeypatch.setattr(Settings, "is_current", lambda self: True)


def test_setup_panel_shows_when_not_ready(qtbot, monkeypatch):
    monkeypatch.setattr(gui, "load_settings", lambda: None)
    w = gui.MainWindow()
    qtbot.addWidget(w)
    assert w.setup_box.isVisibleTo(w)
    assert not w.start_button.isEnabled()


def test_choosing_a_pdf_shows_its_size_and_an_estimate(qtbot, ready, book_pdf):
    w = gui.MainWindow()
    qtbot.addWidget(w)
    w.open_pdf(book_pdf)
    assert "3 pages" in w.book_info.text()
    assert "min" in w.estimate.text()
    assert w.start_button.isEnabled()


def test_translation_runs_to_the_end(qtbot, ready, book_pdf, fake_llama, tmp_path):
    url, _ = fake_llama
    w = gui.MainWindow(server_url=url)
    qtbot.addWidget(w)
    w.open_pdf(book_pdf)
    w.set_target("tr")
    with qtbot.waitSignal(w.job_done, timeout=20000):
        w.start_button.click()
    assert w.open_pdf_button.isEnabled()
    assert (book_pdf.parent / "book.tr.pdf").exists()
    assert w.start_button.text() == "Translate again"


def test_pause_keeps_work_and_offers_resume(qtbot, ready, book_pdf, fake_llama):
    url, _ = fake_llama
    w = gui.MainWindow(server_url=url)
    qtbot.addWidget(w)
    w.open_pdf(book_pdf)
    w.set_target("tr")
    w.pause_requested = True  # pause before the first paragraph is sent
    with qtbot.waitSignal(w.job_done, timeout=20000):
        w.start()
    assert w.start_button.text() == "Resume"
    assert not (book_pdf.parent / "book.tr.pdf").exists()


def test_a_one_page_book_says_page(qtbot, ready, tmp_path):
    from conftest import write_pages
    pdf = write_pages(tmp_path / "one.pdf", [[("A single page of text.", "helv", 11, 90)]])
    w = gui.MainWindow()
    qtbot.addWidget(w)
    w.open_pdf(pdf)
    assert w.book_info.text().startswith("1 page ·")


GERMAN = ("Das Programm liest das Buch und schreibt die Übersetzung in die Seiten, die der Leser sieht. "
          "Es ist nicht schwer, und die Seiten bleiben, wie sie sind.")


def test_the_book_language_is_detected_and_used(qtbot, ready, tmp_path, fake_llama):
    from conftest import write_pages
    url, seen = fake_llama
    pdf = write_pages(tmp_path / "buch.pdf", [[(GERMAN, "helv", 11, 90)]])
    w = gui.MainWindow(server_url=url)
    qtbot.addWidget(w)
    w.open_pdf(pdf)
    assert w.source() == "de"
    w.set_target("en")
    with qtbot.waitSignal(w.job_done, timeout=20000):
        w.start_button.click()
    system = seen[0][1]["messages"][0]["content"]
    assert "from German to English" in system


def test_the_same_language_on_both_sides_cannot_start(qtbot, ready, book_pdf):
    w = gui.MainWindow()
    qtbot.addWidget(w)
    w.open_pdf(book_pdf)
    assert w.source() == "en"
    w.set_target("en")
    assert not w.start_button.isEnabled()
    assert "different" in w.estimate.text()
