from ratica.cli import main


def test_translate_writes_pdf_and_epub(book_pdf, fake_llama, tmp_path):
    url, _ = fake_llama
    out = tmp_path / "out"
    assert main(["translate", str(book_pdf), "--to", "tr", "--server-url", url, "--out", str(out)]) == 0
    assert (out / "book.tr.pdf").exists()
    assert (out / "book.tr.epub").exists()


def test_translated_pdf_keeps_the_original_pages(book_pdf, fake_llama, tmp_path):
    import pymupdf
    url, _ = fake_llama
    out = tmp_path / "out"
    main(["translate", str(book_pdf), "--to", "tr", "--server-url", url, "--out", str(out)])
    assert len(pymupdf.open(out / "book.tr.pdf")) == len(pymupdf.open(book_pdf))


def test_second_run_reuses_saved_work(book_pdf, fake_llama, tmp_path):
    url, seen = fake_llama
    args = ["translate", str(book_pdf), "--to", "tr", "--server-url", url, "--out", str(tmp_path / "out")]
    main(args)
    first = len(seen)
    main(args)
    assert first > 0
    assert len(seen) == first


def test_info_prints_hardware_and_settings(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("RATICA_HOME", str(tmp_path))
    assert main(["info"]) == 0
    out = capsys.readouterr().out
    assert "Backend:" in out and "Not set up yet" in out


def test_missing_pdf_is_a_clear_error(tmp_path, capsys):
    assert main(["translate", str(tmp_path / "nope.pdf"), "--to", "tr", "--server-url", "http://x"]) == 2
    assert "not found" in capsys.readouterr().err


def test_the_source_language_is_detected_when_not_given(fake_llama, tmp_path, capsys):
    from conftest import write_pages
    url, seen = fake_llama
    text = ("Das Programm liest das Buch und schreibt die Übersetzung in die Seiten, die der Leser sieht. "
            "Es ist nicht schwer, und die Seiten bleiben, wie sie sind.")
    pdf = write_pages(tmp_path / "buch.pdf", [[(text, "helv", 11, 90)]])
    assert main(["translate", str(pdf), "--to", "en", "--server-url", url]) == 0
    assert "from German to English" in seen[0][1]["messages"][0]["content"]
    assert "German" in capsys.readouterr().err
