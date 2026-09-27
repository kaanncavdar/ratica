import zipfile

import pymupdf
from conftest import png_bytes

from ratica.docmodel import Block, Book
from ratica.render import write_epub, write_pdf

BOOK = Book(source="x.pdf", title="Hash Tables", blocks=[
    Block("b0", "heading", "Chapter 1: Hash Tables", 1, level=1),
    Block("b1", "paragraph", "Hash tables store pairs.", 1),
    Block("b2", "code", "table = {}\ntable['a'] = 1", 1),
    Block("b3", "heading", "Chapter 2: Trees", 2, level=1),
    Block("b4", "paragraph", "Trees are hierarchical.", 2),
])
TR = {"b0": "Bölüm 1: Hash Tabloları", "b1": "Hash tabloları çiftleri saklar. Işık, ğ, İ.",
      "b2": "table = {}\ntable['a'] = 1", "b3": "Bölüm 2: Ağaçlar", "b4": "Ağaçlar hiyerarşiktir."}


def test_pdf_contains_translated_text_with_turkish_letters(tmp_path):
    out = write_pdf(BOOK, TR, tmp_path / "out.pdf", lang="tr")
    text = "".join(p.get_text() for p in pymupdf.open(out))
    assert "Hash tabloları çiftleri saklar. Işık, ğ, İ." in " ".join(text.split())
    assert "Ağaçlar hiyerarşiktir." in text


def test_pdf_keeps_code_in_a_monospaced_font(tmp_path):
    out = write_pdf(BOOK, TR, tmp_path / "out.pdf", lang="tr")
    spans = [s for p in pymupdf.open(out) for b in p.get_text("dict")["blocks"] if b["type"] == 0
             for l in b["lines"] for s in l["spans"]]
    code = [s for s in spans if "table['a']" in s["text"]]
    assert code and code[0]["flags"] & 8 or "mono" in code[0]["font"].lower()


def test_long_code_lines_wrap_inside_the_page(tmp_path):
    long = Block("c", "code", "print(" + ", ".join(f"value_{i}" for i in range(40)) + ")", 1)
    book = Book(source="x.pdf", title="t", blocks=[long])
    doc = pymupdf.open(write_pdf(book, {}, tmp_path / "out.pdf", lang="en"))
    page = doc[0]
    right = max(s["bbox"][2] for b in page.get_text("dict")["blocks"] if b["type"] == 0
                for l in b["lines"] for s in l["spans"])
    assert right <= page.rect.width - 40
    assert "value_39" in page.get_text()


IMG_BOOK = Book(source="x.pdf", title="t", blocks=[
    Block("b0", "paragraph", "Before.", 1),
    Block("b1", "image", "", 1, image=png_bytes(), image_ext="png", width=240),
    Block("b2", "paragraph", "After.", 1),
])


def test_pdf_includes_images(tmp_path):
    doc = pymupdf.open(write_pdf(IMG_BOOK, {}, tmp_path / "out.pdf", lang="en"))
    assert doc[0].get_images()


def test_epub_includes_images(tmp_path):
    out = write_epub(IMG_BOOK, {}, tmp_path / "out.epub", lang="en")
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        html = "".join(z.read(n).decode() for n in names if n.endswith(".xhtml") and "chap" in n)
    assert any(n.endswith("b1.png") for n in names)
    assert "<img" in html and "b1.png" in html


ITEM_BOOK = Book(source="x.pdf", title="t", blocks=[
    Block("b0", "item", "three", 1, marker="a."), Block("b1", "item", "four", 1, marker="•")])


def test_list_items_keep_their_markers(tmp_path):
    tr = {"b0": "üç", "b1": "dört"}
    text = pymupdf.open(write_pdf(ITEM_BOOK, tr, tmp_path / "o.pdf", lang="tr"))[0].get_text()
    assert "a. üç" in " ".join(text.split())
    assert "• dört" in " ".join(text.split())
    with zipfile.ZipFile(write_epub(ITEM_BOOK, tr, tmp_path / "o.epub", lang="tr")) as z:
        html = "".join(z.read(n).decode() for n in z.namelist() if "chap" in n)
    assert "a. üç" in html


def test_pdf_has_a_bookmark_per_chapter(tmp_path):
    out = write_pdf(BOOK, TR, tmp_path / "out.pdf", lang="tr")
    assert [t[1] for t in pymupdf.open(out).get_toc()] == ["Bölüm 1: Hash Tabloları", "Bölüm 2: Ağaçlar"]


def test_epub_has_one_chapter_per_top_heading(tmp_path):
    out = write_epub(BOOK, TR, tmp_path / "out.epub", lang="tr")
    with zipfile.ZipFile(out) as z:
        chapters = [n for n in z.namelist() if n.endswith(".xhtml") and "chap" in n]
        html = "".join(z.read(n).decode("utf-8") for n in chapters)
    assert len(chapters) == 2
    assert "Ağaçlar hiyerarşiktir." in html
    assert "<pre>" in html


def test_epub_declares_the_target_language(tmp_path):
    out = write_epub(BOOK, TR, tmp_path / "out.epub", lang="tr")
    with zipfile.ZipFile(out) as z:
        opf = next(z.read(n).decode() for n in z.namelist() if n.endswith(".opf"))
    assert "<dc:language>tr</dc:language>" in opf
