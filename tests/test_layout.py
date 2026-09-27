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


def test_lines_and_boxes_are_obstacles_too(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Short.", fontname="helv", fontsize=11)
    page.draw_line((60, 130), (540, 130), width=1.5)  # a rule under the paragraph
    page.insert_textbox(pymupdf.Rect(72, 60, 520, 80), LONG_EN, fontname="helv", fontsize=11)
    doc.save(tmp_path / "rule.pdf")
    book = extract(tmp_path / "rule.pdf")
    short = next(b for b in book.blocks if b.text == "Short.")
    tr = {short.id: "Kısa değil, epeyce uzun bir çeviri metni ki birkaç satır tutabilir ve aşağı taşmak ister, "
                    "hatta çizginin altına kadar inmek ister ama inmemeli."}
    out = pymupdf.open(write_layout_pdf(book, tr, tmp_path / "out.pdf"))[0]
    words = out.get_text("words")
    assert all(w[3] <= 130 for w in words if w[4] in ("inmemeli.", "ister,", "Kısa"))


def test_text_stays_inside_its_coloured_box(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(60, 80, 320, 140), color=None, fill=(0.85, 0.9, 0.95))
    page.insert_text((72, 100), "Checkpoint", fontname="helv", fontsize=11)
    page.insert_textbox(pymupdf.Rect(60, 200, 540, 260), LONG_EN, fontname="helv", fontsize=11)
    doc.save(tmp_path / "box.pdf")
    book = extract(tmp_path / "box.pdf")
    label = next(b for b in book.blocks if b.text == "Checkpoint")
    tr = {label.id: "Kontrol noktası ve kutunun içinde kalması gereken epey uzun bir etiket metni"}
    out = pymupdf.open(write_layout_pdf(book, tr, tmp_path / "out.pdf"))[0]
    for w in out.get_text("words"):
        if w[4] in ("Kontrol", "metni", "etiket"):
            assert 60 <= w[0] and w[2] <= 321 and w[3] <= 141


def test_paragraphs_of_the_same_style_get_the_same_size(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(72, 72, 520, 130), LONG_EN, fontname="tiro", fontsize=11)
    page.insert_textbox(pymupdf.Rect(72, 140, 520, 198), LONG_EN.replace("Hash", "Search"), fontname="tiro",
                        fontsize=11)
    page.insert_textbox(pymupdf.Rect(72, 205, 520, 260), "A third paragraph keeps the space below busy.",
                        fontname="tiro", fontsize=11)
    doc.save(tmp_path / "same.pdf")
    book = extract(tmp_path / "same.pdf")
    first, second = book.blocks[0], book.blocks[1]
    tr = {first.id: LONG_TR, second.id: "Arama tabloları kısa bir çeviri."}
    out = pymupdf.open(write_layout_pdf(book, tr, tmp_path / "out.pdf"))[0]
    a, b = _sizes(out, "anahtar"), _sizes(out, "Arama")
    assert a and b and abs(min(a) - min(b)) < 0.2


def test_a_translation_that_cannot_fit_leaves_the_original(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(68, 86, 112, 104), color=(0, 0, 0), width=0.8)  # a small table cell
    page.draw_rect(pymupdf.Rect(112, 86, 300, 104), color=(0, 0, 0), width=0.8)  # its neighbour
    page.draw_rect(pymupdf.Rect(68, 104, 300, 122), color=(0, 0, 0), width=0.8)  # the row below
    page.insert_text((72, 100), "Label", fontname="helv", fontsize=11)
    page.insert_text((116, 100), "Value", fontname="helv", fontsize=11)
    doc.save(tmp_path / "tight.pdf")
    book = extract(tmp_path / "tight.pdf")
    label = next(b for b in book.blocks if b.text.startswith("Label"))
    tr = {label.id: "Bu etiket çok çok çok uzun bir çeviriye dönüştü ve asla oraya sığmaz " * 3}
    out = pymupdf.open(write_layout_pdf(book, tr, tmp_path / "out.pdf"))[0]
    assert "Label" in out.get_text() and "etiket" not in out.get_text()


def test_indented_items_may_grow_to_the_column_edge_of_the_text_above(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(72, 72, 520, 120), LONG_EN, fontname="tiro", fontsize=11)
    for i, y in enumerate((140, 154, 168)):
        page.insert_text((130, y), f"{i + 1} table, sized at 1,000,000 slots", fontname="tiro", fontsize=11)
    doc.save(tmp_path / "items.pdf")
    book = extract(tmp_path / "items.pdf")
    first = next(b for b in book.blocks if b.text.startswith("1 table"))
    tr = {first.id: "1 tablo, her biri 1.000.000 yuva kapasitesiyle ayrı ayrı boyutlandırılmış ve derecelendirilmiş"}
    out = pymupdf.open(write_layout_pdf(book, tr, tmp_path / "out.pdf"))[0]
    sizes = _sizes(out, "derecelendirilmiş")
    assert sizes and min(sizes) >= 10.8


def test_serif_text_uses_a_times_like_font(tmp_path):
    src = make_source(tmp_path / "src.pdf")
    book = extract(src)
    out = pymupdf.open(write_layout_pdf(book, translate_all(book, {LONG_EN: LONG_TR}), tmp_path / "out.pdf"))[0]
    fonts = {s["font"] for b in out.get_text("dict")["blocks"] if b["type"] == 0
             for l in b["lines"] for s in l["spans"] if "anahtar" in s["text"]}
    assert fonts and all("Roman" in f or "Times" in f for f in fonts)


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


def test_a_single_line_keeps_the_top_of_its_original_line(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((150, 100), "Introduction", fontname="helv", fontsize=10)
    doc.save(tmp_path / "one.pdf")
    book = extract(tmp_path / "one.pdf")
    out = write_layout_pdf(book, {book.blocks[0].id: "Giriş bölümü"}, tmp_path / "out.pdf")
    before = pymupdf.open(tmp_path / "one.pdf")[0].search_for("Introduction")[0]
    after = pymupdf.open(out)[0].search_for("Giriş")[0]
    assert abs(after.y1 - before.y1) < 1.0


def test_a_right_aligned_label_grows_to_the_left(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    tw = pymupdf.TextWriter(page.rect)
    tw.append((431, 40), "Contents", font=pymupdf.Font("tiro"), fontsize=10)
    tw.append((477, 40), "|", font=pymupdf.Font("helv"), fontsize=10)
    tw.append((491, 40), "xv", font=pymupdf.Font("hebo"), fontsize=10)
    tw.write_text(page)
    doc.save(tmp_path / "hdr.pdf")
    book = extract(tmp_path / "hdr.pdf")
    label = next(b for b in book.blocks if b.text == "Contents")
    out = write_layout_pdf(book, {label.id: "İçindekiler Listesi"}, tmp_path / "out.pdf")
    spans = [s for b in pymupdf.open(out)[0].get_text("dict")["blocks"] for l in b.get("lines", [])
             for s in l["spans"] if "İçindekiler" in s["text"]]
    assert spans and spans[0]["size"] > 9.5
    assert spans[0]["bbox"][2] < 477


def test_the_translation_sits_on_the_original_baseline(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="notos", fontbuffer=pymupdf.Font("notos").buffer)  # tall ascender, like many books
    page.insert_text((150, 100), "Introduction", fontname="notos", fontsize=10)
    doc.save(tmp_path / "one.pdf")
    book = extract(tmp_path / "one.pdf")
    out = write_layout_pdf(book, {book.blocks[0].id: "Giriş"}, tmp_path / "out.pdf")
    spans = [s for b in pymupdf.open(out)[0].get_text("dict")["blocks"] for l in b.get("lines", [])
             for s in l["spans"] if "Giriş" in s["text"]]
    assert abs(spans[0]["origin"][1] - 100) < 0.5


def test_a_paragraph_does_not_widen_to_the_edge_of_a_much_larger_title(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((255, 100), "Hash Tables in Practice", fontname="helv", fontsize=24)
    page.insert_textbox(pymupdf.Rect(255, 200, 450, 260), LONG_EN, fontname="helv", fontsize=10)
    doc.save(tmp_path / "title.pdf")
    book = extract(tmp_path / "title.pdf")
    para = next(b for b in book.blocks if b.text == LONG_EN)
    out = pymupdf.open(write_layout_pdf(book, {para.id: LONG_TR}, tmp_path / "out.pdf"))[0]
    hits = [r for w in ("tabloları", "fonksiyonu", "ortalama") for r in out.search_for(w)]
    assert hits and max(r.x1 for r in hits) <= 452


def test_a_single_line_grows_right_into_free_space_instead_of_wrapping(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((350, 300), "A Sample Source, May 3, 2021", fontname="helv", fontsize=10)
    doc.save(tmp_path / "attr.pdf")
    book = extract(tmp_path / "attr.pdf")
    out = pymupdf.open(write_layout_pdf(book, {book.blocks[0].id: "Örnek Kaynak, 3 Mayıs 2021 günü"},
                                        tmp_path / "out.pdf"))[0]
    lines = [l for b in out.get_text("dict")["blocks"] for l in b.get("lines", [])]
    assert len(lines) == 1 and lines[0]["spans"][0]["size"] > 9.5


def test_a_single_line_is_not_shrunk_to_match_paragraphs(monkeypatch):
    from ratica import layout
    from ratica.docmodel import Block, Part
    need = {"long": 0.7, "short": 1.0, "line": 1.0}
    monkeypatch.setattr(layout, "_needed_scale", lambda body, css, rect: need[body])
    page = pymupdf.open().new_page()
    items = [(Part(1, (72, 72 + 40 * n, 300, 100 + 40 * n), size=11, lines=lines), text, Block(f"b{n}", "paragraph", text, 1))
             for n, (text, lines) in enumerate((("long", 3), ("short", 3), ("line", 1)))]
    scales = {p.body: p.scale for p in layout._plan_page(page, items)}
    assert scales == {"long": 0.7, "short": layout.EVEN_SCALE_FLOOR, "line": 1.0}


def test_only_labels_on_the_right_of_the_page_grow_to_the_left(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    tw = pymupdf.TextWriter(page.rect)
    tw.append((89, 115), "A is k times larger than B: k =", font=pymupdf.Font("tiro"), fontsize=10)
    tw.append((212, 115), "Size of A", font=pymupdf.Font("tiit"), fontsize=10)
    tw.write_text(page)
    doc.save(tmp_path / "left.pdf")
    book = extract(tmp_path / "left.pdf")
    label = next(b for b in book.blocks if b.text.startswith("A is"))
    out = pymupdf.open(write_layout_pdf(book, {label.id: "A, B'den k kat daha büyüktür: k ="}, tmp_path / "o.pdf"))
    assert out[0].search_for("büyüktür")[0].x0 > 88
