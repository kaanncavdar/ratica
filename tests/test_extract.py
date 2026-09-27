import pymupdf
from conftest import BODY, png_bytes, write_pages
from ratica.extract import extract


def kinds(book):
    return [(b.kind, b.text) for b in book.blocks]


def test_heading_is_detected_by_font_size(book_pdf):
    book = extract(book_pdf)
    assert book.blocks[0].kind == "heading"
    assert book.blocks[0].text == "Chapter 1: Hash Tables"


def test_body_text_is_one_paragraph(book_pdf):
    book = extract(book_pdf)
    assert ("paragraph", BODY) in kinds(book)


def test_monospace_text_is_code(book_pdf):
    book = extract(book_pdf)
    assert ("code", "table = {}  # empty dict") in kinds(book)


def test_running_headers_and_page_numbers_are_dropped(book_pdf):
    texts = [b.text for b in extract(book_pdf).blocks]
    assert "A Small Book" not in texts
    assert not any(t.strip().isdigit() for t in texts)


def test_blocks_keep_reading_order_and_page(book_pdf):
    book = extract(book_pdf)
    assert [b.page for b in book.blocks] == sorted(b.page for b in book.blocks)
    assert book.blocks[-1].page == 3


def test_hyphenated_line_breaks_are_joined(tmp_path):
    pdf = write_pages(tmp_path / "h.pdf", [[("The algorithm is deter-\nministic and fast.", "helv", 11, 90)]])
    assert extract(pdf).blocks[0].text == "The algorithm is deterministic and fast."


def test_running_header_with_section_name_and_page_number_is_dropped(tmp_path):
    sections = ["Background", "Input/output", "Variables"]
    pages = [[(f"1.{n + 1} • {s}     {n + 9}", "helv", 9, 30), ("Body text of the page.", "helv", 11, 90)]
             for n, s in enumerate(sections)]
    texts = [b.text for b in extract(write_pages(tmp_path / "r.pdf", pages)).blocks]
    assert texts == ["Body text of the page."] * 3


def test_paragraph_split_across_pages_is_merged(tmp_path):
    pages = [[("The first part of a sentence that continues", "helv", 11, 90)],
             [("on the next page and ends here.", "helv", 11, 90)]]
    blocks = extract(write_pages(tmp_path / "s.pdf", pages)).blocks
    assert [b.text for b in blocks] == ["The first part of a sentence that continues on the next page and ends here."]


def test_inline_code_in_a_paragraph_is_recorded_for_protection(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "The statement ", fontname="helv", fontsize=11)
    x = 72 + pymupdf.get_text_length("The statement ", fontname="helv", fontsize=11)
    page.insert_text((x, 100), 'print("Hi")', fontname="cour", fontsize=11)
    x += pymupdf.get_text_length('print("Hi")', fontname="cour", fontsize=11)
    page.insert_text((x, 100), " shows a greeting.", fontname="helv", fontsize=11)
    doc.save(tmp_path / "i.pdf")
    block = extract(tmp_path / "i.pdf").blocks[0]
    assert block.kind == "paragraph"
    assert block.text == 'The statement print("Hi") shows a greeting.'
    assert block.keep == ['print("Hi")']


def test_images_become_blocks_in_reading_order(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(72, 72, 520, 120), "Text before the figure.", fontname="helv", fontsize=11)
    page.insert_image(pymupdf.Rect(72, 130, 312, 290), stream=png_bytes())
    page.insert_textbox(pymupdf.Rect(72, 300, 520, 350), "Text after the figure.", fontname="helv", fontsize=11)
    doc.save(tmp_path / "img.pdf")
    blocks = extract(tmp_path / "img.pdf").blocks
    assert [b.kind for b in blocks] == ["paragraph", "image", "paragraph"]
    assert blocks[1].image and blocks[1].width == 240


def test_tiny_images_are_ignored(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(pymupdf.Rect(72, 72, 80, 80), stream=png_bytes(8, 8))
    page.insert_textbox(pymupdf.Rect(72, 100, 520, 150), "Only text.", fontname="helv", fontsize=11)
    doc.save(tmp_path / "tiny.pdf")
    assert [b.kind for b in extract(tmp_path / "tiny.pdf").blocks] == ["paragraph"]


def test_bullet_lines_become_separate_list_items(tmp_path):
    text = "• Name two examples of computer\nprograms in everyday life.\n• Explain why Python is a good choice."
    blocks = extract(write_pages(tmp_path / "l.pdf", [[(text, "notos", 11, 90)]])).blocks
    assert [(b.kind, b.marker, b.text) for b in blocks] == [
        ("item", "•", "Name two examples of computer programs in everyday life."),
        ("item", "•", "Explain why Python is a good choice."),
    ]


def test_lettered_options_become_separate_items(tmp_path):
    text = "How many types of programs were described?\na. 3\nb. 4\nc. 5"
    blocks = extract(write_pages(tmp_path / "o.pdf", [[(text, "helv", 11, 90)]])).blocks
    assert [(b.kind, b.marker, b.text) for b in blocks] == [
        ("paragraph", "", "How many types of programs were described?"),
        ("item", "a.", "3"), ("item", "b.", "4"), ("item", "c.", "5"),
    ]


def test_symbol_font_text_is_a_formula_and_not_translated(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(72, 72, 520, 100), "Speedup = 1 / (1 - f)", fontname="symb", fontsize=11)
    page.insert_textbox(pymupdf.Rect(72, 110, 520, 150), "Amdahl's law limits the speedup.", fontname="helv",
                        fontsize=11)
    doc.save(tmp_path / "f.pdf")
    blocks = extract(tmp_path / "f.pdf").blocks
    assert blocks[0].kind == "formula" and not blocks[0].translatable
    assert blocks[1].kind == "paragraph"


def test_private_use_characters_keep_the_block_untranslated():
    from ratica.extract import has_unmapped_chars
    assert has_unmapped_chars("CPU time = count  cycles")
    assert has_unmapped_chars("broken � glyph")
    assert has_unmapped_chars("Instruction count \x02 Clock cycles")  # a math font's × read as a control code
    assert not has_unmapped_chars("Işık × π ≈ 3.14\ttab")


def _write_spans(page, x, y, spans):
    """spans: (text, fontname, size, dy); dy shifts the baseline (subscripts go down)."""
    for text, font, size, dy in spans:
        page.insert_text((x, y + dy), text, fontname=font, fontsize=size)
        x += pymupdf.get_text_length(text, fontname=font, fontsize=size)


def test_text_with_subscripts_is_a_formula(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    _write_spans(page, 72, 100, [("Speedup", "tiro", 11, 0), ("overall", "tiro", 7, 3), (" = Execution time", "tiro", 11, 0),
                                  ("old", "tiro", 7, 3), (" / Execution time", "tiro", 11, 0), ("new", "tiro", 7, 3)])
    page.insert_textbox(pymupdf.Rect(72, 150, 520, 200), "Amdahl's law limits the speedup of a program.",
                        fontname="tiro", fontsize=11)
    doc.save(tmp_path / "sub.pdf")
    blocks = extract(tmp_path / "sub.pdf").blocks
    assert blocks[0].kind == "formula"
    assert blocks[-1].kind == "paragraph"


def test_one_footnote_mark_does_not_make_a_paragraph_a_formula(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    _write_spans(page, 72, 100, [("Moore's law has slowed down in recent years, as many authors note", "tiro", 11, 0),
                                  ("1", "tiro", 7, -4), (".", "tiro", 11, 0)])
    doc.save(tmp_path / "fn.pdf")
    assert extract(tmp_path / "fn.pdf").blocks[0].kind == "paragraph"


def test_fraction_parts_next_to_a_formula_stay_with_it(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((200, 92), "Execution time", fontname="tiro", fontsize=9)   # numerator
    page.insert_text((72, 100), "Speedup = \x02", fontname="tiro", fontsize=11)   # the line with the unmapped sign
    page.insert_text((200, 110), "Execution time", fontname="tiro", fontsize=9)  # denominator
    page.insert_textbox(pymupdf.Rect(72, 160, 520, 200), "A normal paragraph far below the formula.",
                        fontname="tiro", fontsize=11)
    doc.save(tmp_path / "frac.pdf")
    kinds = {b.text: b.kind for b in extract(tmp_path / "frac.pdf").blocks}
    assert kinds.get("Execution time") in ("formula", None)  # merged into the formula or marked as one
    assert all(k == "formula" for t, k in kinds.items() if "Execution" in t or "Speedup" in t)
    assert kinds["A normal paragraph far below the formula."] == "paragraph"


def test_blocks_remember_their_box_and_style(tmp_path):
    pdf = write_pages(tmp_path / "s.pdf", [[("A serif paragraph.", "tiro", 11, 90)]])
    part = extract(pdf).blocks[0].parts[0]
    assert part.page == 1 and part.serif and round(part.size) == 11
    assert pymupdf.Rect(part.rect).y0 >= 88


def test_font_name_decides_serif_before_the_unreliable_flag():
    from ratica.extract import looks_serif
    assert not looks_serif("NotoSans-Regular", flags=4)
    assert not looks_serif("ABCDEF+Arial-BoldMT", flags=4)
    assert looks_serif("MMADLM+Times-Roman", flags=0)
    assert looks_serif("NotoSerif-Italic", flags=0)
    assert looks_serif("GCIIFE+AdvOTce3d9a73", flags=4)  # obfuscated name: trust the flag
    assert not looks_serif("GCIIFE+AdvOTce3d9a73", flags=0)


def test_font_name_marks_bold():
    from ratica.extract import looks_bold
    assert looks_bold("NotoSans-Bold", flags=0)
    assert looks_bold("Avenir-Heavy", flags=0)
    assert not looks_bold("NotoSans-Regular", flags=0)
    assert looks_bold("X+AdvOT123", flags=16)


def test_block_ids_are_stable_across_runs(book_pdf):
    assert [b.id for b in extract(book_pdf).blocks] == [b.id for b in extract(book_pdf).blocks]
