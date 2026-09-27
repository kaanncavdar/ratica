"""The translated PDF keeps the original pages: only translated text boxes change."""
import pymupdf
from conftest import png_bytes

from ratica.extract import extract
from ratica.layout import write_layout_pdf

LONG_EN = ("Hash tables store key and value pairs. A hash function maps each key to a bucket, so lookups "
           "take constant time on average.")
LONG_TR = ("Hash tabloları anahtar ve değer çiftlerini saklar. Bir hash fonksiyonu her anahtarı bir kovaya "
           "eşler, böylece aramalar ortalama olarak sabit zaman alır ve oldukça hızlıdır.")


def make_source(path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(72, 72, 400, 110), "Chapter 1: Hash Tables", fontname="hebo", fontsize=18)
    page.insert_textbox(pymupdf.Rect(72, 120, 400, 200), LONG_EN, fontname="tiro", fontsize=11)
    page.insert_image(pymupdf.Rect(72, 210, 312, 370), stream=png_bytes())
    page.insert_textbox(pymupdf.Rect(72, 380, 400, 400), "table = {}", fontname="cour", fontsize=10)
    doc.new_page()  # a second page, left empty
    doc.save(path)
    return path


def translate_all(book, mapping):
    return {b.id: mapping.get(b.text, b.text) for b in book.blocks}


def test_page_count_and_images_stay_the_same(tmp_path):
    src = make_source(tmp_path / "src.pdf")
    book = extract(src)
    out = write_layout_pdf(book, translate_all(book, {LONG_EN: LONG_TR}), tmp_path / "out.pdf")
    doc = pymupdf.open(out)
    assert len(doc) == 2
    assert len(doc[0].get_images()) == 1


def test_translated_text_replaces_the_original_in_its_box(tmp_path):
    src = make_source(tmp_path / "src.pdf")
    book = extract(src)
    para = next(b for b in book.blocks if b.text == LONG_EN)
    out = write_layout_pdf(book, translate_all(book, {LONG_EN: LONG_TR}), tmp_path / "out.pdf")
    page = pymupdf.open(out)[0]
    text = " ".join(page.get_text().split())
    assert "Hash tabloları anahtar ve değer" in text
    assert "store key and value pairs" not in text
    box = pymupdf.Rect(para.parts[0].rect)
    hits = page.search_for("anahtar ve değer")
    assert hits and all(box + (-2, -2, 2, 2) in pymupdf.Rect(h) or box.intersects(h) for h in hits)


def test_untranslated_blocks_are_left_untouched(tmp_path):
    src = make_source(tmp_path / "src.pdf")
    book = extract(src)
    out = write_layout_pdf(book, translate_all(book, {LONG_EN: LONG_TR}), tmp_path / "out.pdf")
    page = pymupdf.open(out)[0]
    assert "Chapter 1: Hash Tables" in page.get_text()  # heading had no translation
    assert "table = {}" in page.get_text()


def test_serif_text_stays_serif(tmp_path):
    src = make_source(tmp_path / "src.pdf")
    book = extract(src)
    out = write_layout_pdf(book, translate_all(book, {LONG_EN: LONG_TR}), tmp_path / "out.pdf")
    spans = [s for b in pymupdf.open(out)[0].get_text("dict")["blocks"] if b["type"] == 0
             for l in b["lines"] for s in l["spans"] if "anahtar" in s["text"]]
    assert spans and all(s["flags"] & 4 or "serif" in s["font"].lower() and "sans" not in s["font"].lower()
                         or "charis" in s["font"].lower() for s in spans)


def _sizes(page, word):
    return [s["size"] for b in page.get_text("dict")["blocks"] if b["type"] == 0
            for l in b["lines"] for s in l["spans"] if word in s["text"]]


def test_a_longer_translation_uses_free_space_before_shrinking(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(72, 80, 520, 130), LONG_EN, fontname="helv", fontsize=11)
    page.insert_text((72, 200), "A short line.", fontname="helv", fontsize=11)
    doc.save(tmp_path / "s.pdf")
    book = extract(tmp_path / "s.pdf")
    short = next(b for b in book.blocks if b.text == "A short line.")
    tr = {short.id: "Bu, orijinalinden çok daha uzun olan ve tek satıra sığmayan bir çeviri cümlesidir."}
    out = pymupdf.open(write_layout_pdf(book, tr, tmp_path / "out.pdf"))[0]
    sizes = _sizes(out, "orijinalinden")
    assert sizes and min(sizes) >= 10
    assert len(out.search_for("orijinalinden")) == 1  # a failed first attempt writes nothing


def test_growing_never_covers_other_text(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Short.", fontname="helv", fontsize=11)
    page.insert_text((72, 140), "Next line stays.", fontname="helv", fontsize=11)
    page.insert_textbox(pymupdf.Rect(72, 60, 520, 80), LONG_EN, fontname="helv", fontsize=11)
    doc.save(tmp_path / "g.pdf")
    book = extract(tmp_path / "g.pdf")
    short = next(b for b in book.blocks if b.text == "Short.")
    tr = {short.id: "Kısa değil, epeyce uzun bir çeviri metni ki birkaç satır tutabilir ve aşağı taşmak ister."}
    out = pymupdf.open(write_layout_pdf(book, tr, tmp_path / "out.pdf"))[0]
    below = out.search_for("Next line stays.")[0]
    for h in out.search_for("aşağı"):
        assert h.y1 <= below.y0 + 1


def test_a_block_overlapping_a_formula_is_left_alone(tmp_path):
    from ratica.docmodel import Block, Book, Part
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "X is n times faster: n =", fontname="helv", fontsize=11)
    page.insert_text((220, 100), "time / time", fontname="tiro", fontsize=11)
    doc.save(tmp_path / "o.pdf")
    book = Book(str(tmp_path / "o.pdf"), "t", [
        Block("b0", "item", "X is n times faster: n =", 1, marker="2.", parts=[Part(1, (72, 90, 300, 104), 11)]),
        Block("b1", "formula", "time / time", 1, parts=[Part(1, (220, 90, 280, 104), 11)]),
    ])
    out = pymupdf.open(write_layout_pdf(book, {"b0": "X, n kat daha hızlıdır: n ="}, tmp_path / "out.pdf"))[0]
    assert "time / time" in out.get_text()
    assert "X is n times faster" in out.get_text()


def test_block_boxes_ignore_trailing_blank_space(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Label: n =" + " " * 60, fontname="helv", fontsize=11)
    doc.save(tmp_path / "t.pdf")
    rect = pymupdf.Rect(extract(tmp_path / "t.pdf").blocks[0].parts[0].rect)
    assert rect.x1 < 72 + pymupdf.get_text_length("Label: n =  ", fontname="helv", fontsize=11)


def test_a_paragraph_split_across_pages_is_written_back_on_both(tmp_path):
    doc = pymupdf.open()
    for text in ("The first part of a sentence that continues", "on the next page and ends here."):
        doc.new_page().insert_textbox(pymupdf.Rect(72, 90, 500, 130), text, fontname="helv", fontsize=11)
    doc.save(tmp_path / "split.pdf")
    book = extract(tmp_path / "split.pdf")
    assert len(book.blocks) == 1 and len(book.blocks[0].parts) == 2
    tr = {book.blocks[0].id: "Bir sonraki sayfada devam eden bir cümlenin ilk kısmı burada biter."}
    out = pymupdf.open(write_layout_pdf(book, tr, tmp_path / "out.pdf"))
    assert out[0].get_text().strip() and out[1].get_text().strip()
    assert "first part" not in out[0].get_text()
