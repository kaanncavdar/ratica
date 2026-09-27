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


def test_block_ids_are_stable_across_runs(book_pdf):
    assert [b.id for b in extract(book_pdf).blocks] == [b.id for b in extract(book_pdf).blocks]
