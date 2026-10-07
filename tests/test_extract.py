import pymupdf
from conftest import BODY, png_bytes, write_pages
from ratica.extract import extract


def kinds(book):
    return [(b.kind, b.text) for b in book.blocks]


def test_heading_is_detected_by_font_size(book_pdf):
    first = next(b for b in extract(book_pdf).blocks if b.kind != "header")
    assert first.kind == "heading"
    assert first.text == "Chapter 1: Hash Tables"


def test_body_text_is_one_paragraph(book_pdf):
    book = extract(book_pdf)
    assert ("paragraph", BODY) in kinds(book)


def test_monospace_text_is_code(book_pdf):
    book = extract(book_pdf)
    assert ("code", "table = {}  # empty dict") in kinds(book)


def test_running_headers_are_marked_and_page_numbers_dropped(book_pdf):
    blocks = extract(book_pdf).blocks
    assert all(b.kind == "header" for b in blocks if b.text == "A Small Book")
    assert not any(b.text.strip().isdigit() for b in blocks)


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
    texts = [b.text for b in extract(write_pages(tmp_path / "r.pdf", pages)).blocks if b.kind != "header"]
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


def test_fonts_that_are_mostly_symbols_are_math_fonts():
    from ratica.extract import symbolic_fonts
    spans = [("AdvP4C4E74", "¼"), ("AdvP4C4E74", "ð"), ("AdvP4C4E74", "Þ"), ("AdvP4C4E74", "¼ "),
             ("Times-Roman", "Execution time of the program"), ("Times-Roman", "costs ¼ of the budget"),
             ("MathematicalPi-One", "\x02")]
    assert symbolic_fonts(spans) == {"AdvP4C4E74", "MathematicalPi-One"}


def test_misencoded_math_signs_make_a_formula():
    from ratica.extract import MISENCODED_MATH
    assert MISENCODED_MATH.search("n ¼ Execution time")
    assert not MISENCODED_MATH.search("Execution time of the program")


def test_vertical_text_is_left_alone(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((300, 400), "A rotated figure label", fontname="helv", fontsize=9, rotate=90)
    page.insert_textbox(pymupdf.Rect(72, 72, 250, 120), "Normal text.", fontname="helv", fontsize=11)
    doc.save(tmp_path / "v.pdf")
    kinds = {b.text: b.kind for b in extract(tmp_path / "v.pdf").blocks}
    assert kinds["A rotated figure label"] == "figure"
    assert kinds["Normal text."] == "paragraph"


def test_running_headers_become_translatable_header_blocks(tmp_path):
    sections = ["Background", "Input/output", "Variables"]
    pages = [[(f"1.{n + 1} • {s}     {n + 9}", "notos", 9, 30), ("Body text of the page.", "helv", 11, 90),
              (str(n + 9), "helv", 9, 800)] for n, s in enumerate(sections)]
    blocks = extract(write_pages(tmp_path / "h.pdf", pages)).blocks
    headers = [b for b in blocks if b.kind == "header"]
    assert [b.text for b in headers] == [f"1.{n + 1} • {s} {n + 9}" for n, s in enumerate(sections)]
    assert all(b.translatable for b in headers)
    assert not any(b.text.strip().isdigit() for b in blocks)


def test_a_margin_label_on_the_first_line_is_its_own_block(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    tw = pymupdf.TextWriter(page.rect)
    tw.append((72, 100), "Example", font=pymupdf.Font("hebo"), fontsize=10)
    tw.append((140, 100), "Assume a small cache with the following", font=pymupdf.Font("tiro"), fontsize=10)
    tw.append((140, 112), "sizes and hit rates.", font=pymupdf.Font("tiro"), fontsize=10)
    tw.write_text(page)
    doc.save(tmp_path / "label.pdf")
    texts = [b.text for b in extract(tmp_path / "label.pdf").blocks]
    assert "Example" in texts
    assert "Assume a small cache with the following sizes and hit rates." in texts


def test_a_single_line_with_wide_gaps_splits_into_pieces(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    tw = pymupdf.TextWriter(page.rect)
    for x, label in ((80, "Model A cluster watts/node"), (260, "Model A 8 cores watts"),
                     (420, "Model B 8 cores watts")):
        tw.append((x, 100), label, font=pymupdf.Font("helv"), fontsize=8)
    tw.write_text(page)
    doc.save(tmp_path / "legend.pdf")
    texts = [b.text for b in extract(tmp_path / "legend.pdf").blocks]
    assert texts == ["Model A cluster watts/node", "Model A 8 cores watts", "Model B 8 cores watts"]


def test_block_ids_are_stable_across_runs(book_pdf):
    assert [b.id for b in extract(book_pdf).blocks] == [b.id for b in extract(book_pdf).blocks]


def _write_rows(path, rows):
    """rows: list of (y, [(x, text, font), ...]) written with one TextWriter, so PyMuPDF sees one block."""
    doc = pymupdf.open()
    page = doc.new_page()
    tw = pymupdf.TextWriter(page.rect)
    for y, cells in rows:
        for x, text, font in cells:
            tw.append((x, y), text, font=pymupdf.Font(font), fontsize=10)
    tw.write_text(page)
    doc.save(path)
    return path


def test_contents_rows_become_one_block_per_cell(tmp_path):
    pdf = _write_rows(tmp_path / "toc.pdf", [
        (100, [(100, "A.1", "hebo"), (130, "Introduction", "helv"), (455, "A-2", "helv")]),
        (114, [(100, "A.2", "hebo"), (130, "Resizing a Hash Table While Readers", "helv"), (455, "A-3", "helv")]),
        (128, [(130, "Keep Working", "helv"), (455, "A-9", "helv")]),
    ])
    blocks = extract(pdf).blocks
    texts = [b.text for b in blocks if b.translatable]
    assert texts == ["Introduction", "Resizing a Hash Table While Readers Keep Working"]
    assert {b.text for b in blocks if not b.translatable} == {"A.1", "A.2", "A-2", "A-3", "A-9"}


def test_a_wrapped_cell_continues_on_the_next_row(tmp_path):
    pdf = _write_rows(tmp_path / "wrap.pdf", [
        (100, [(100, "Appendix C", "helv"), (170, "Resizing a hash table while", "hebo")]),
        (114, [(170, "readers keep working", "hebo")]),
        (128, [(170, "by Ada Writer", "heit")]),
    ])
    texts = [b.text for b in extract(pdf).blocks if b.translatable]
    assert texts == ["Appendix C", "Resizing a hash table while readers keep working", "by Ada Writer"]


def test_words_in_separate_spans_keep_their_spaces(tmp_path):
    pdf = _write_rows(tmp_path / "sp.pdf", [(100, [(100, "Instruction", "helv"), (148, "Set", "helv")])])
    assert extract(pdf).blocks[0].text == "Instruction Set"


def test_a_line_in_another_style_is_not_joined_to_the_block_above(tmp_path):
    pdf = _write_rows(tmp_path / "by.pdf", [(100, [(100, "Hash Functions", "hebo")]),
                                            (130, [(100, "by Ada Writer", "heit")])])
    assert [b.text for b in extract(pdf).blocks] == ["Hash Functions", "by Ada Writer"]


def test_first_line_indent_starts_a_new_paragraph(tmp_path):
    pdf = _write_rows(tmp_path / "ind.pdf", [
        (100, [(84, "Chapter 3 explains how hash tables grow when", "tiro")]),
        (112, [(72, "they fill up here.", "tiro")]),
        (124, [(84, "Chapter 4 covers sorting algorithms and", "tiro")]),
        (136, [(72, "their typical running times.", "tiro")]),
    ])
    blocks = extract(pdf).blocks
    assert [b.text for b in blocks] == ["Chapter 3 explains how hash tables grow when they fill up here.",
                                        "Chapter 4 covers sorting algorithms and their typical running times."]
    assert 10 < blocks[0].parts[0].indent < 14


def test_bullet_glyph_in_its_own_span_stays_outside_the_item_box(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="notos", fontbuffer=pymupdf.Font("notos").buffer)
    page.insert_text((100, 100), "•", fontname="notos", fontsize=10)
    page.insert_text((114, 100), "Hash Tables: Chapter 2 and Chapter 5", fontname="helv", fontsize=10)
    doc.save(tmp_path / "bullet.pdf")
    item = next(b for b in extract(tmp_path / "bullet.pdf").blocks if b.translatable)
    assert item.kind == "item" and item.text == "Hash Tables: Chapter 2 and Chapter 5"
    assert item.parts[0].rect[0] >= 113 and not item.parts[0].marker_in_box


def test_page_references_and_symbols_are_not_translated(tmp_path):
    pdf = _write_rows(tmp_path / "hdr.pdf", [(100, [(38, "xiv", "hebo"), (61, "■", "helv"), (76, "Contents", "helv")])])
    blocks = extract(pdf).blocks
    assert [b.text for b in blocks if b.translatable] == ["Contents"]


def test_font_shape_decides_serif_and_bold_when_the_name_says_nothing(tmp_path):
    from ratica.extract import font_shapes
    doc = pymupdf.open()
    page = doc.new_page()
    for n, (alias, font) in enumerate((("fa", "tiro"), ("fb", "helv"), ("fc", "hebo"))):
        page.insert_font(fontname=alias, fontbuffer=pymupdf.Font(font).buffer)
        page.insert_text((72, 100 + 20 * n), "Hello world", fontname=alias, fontsize=11)
    doc.save(tmp_path / "shapes.pdf")
    doc = pymupdf.open(tmp_path / "shapes.pdf")
    names = {f[3].split("+")[-1]: f[3] for f in doc.get_page_fonts(0)}
    shapes = font_shapes(doc)
    by_look = sorted(shapes[n] for n in names)
    assert by_look == [(False, False), (False, True), (True, False)]


def test_obfuscated_font_names_still_tell_bold_and_italic():
    from ratica.extract import looks_bold, looks_italic
    assert looks_bold("AdvOT3b30f6db.B", flags=4)
    assert looks_italic("AdvOTc0286d31.I", flags=4)
    assert not looks_bold("AdvOTab62ddd1+20", flags=4)


def test_an_accent_drawn_as_its_own_glyph_is_dropped():
    from ratica.extract import drop_accents

    def span(x0, x1, text, font="AdvOTbody"):
        return {"bbox": (x0, 100, x1, 110), "text": text, "font": font, "size": 10, "flags": 4, "color": 0,
                "origin": (x0, 108)}
    spans = [span(192, 315, "written by Ada Writer and Ren"), span(314, 320, "", "AdvP4C4E59"),
             span(315, 319, "e"), span(319, 323, " "), span(323, 349, "Example")]
    assert "".join(s["text"] for s in drop_accents(spans)) == "written by Ada Writer and Rene Example"
    lone = [span(100, 140, "x "), span(141, 147, "", "AdvP4C4E59"), span(149, 160, " y")]
    assert len(drop_accents(lone)) == 3  # not over a letter: a real symbol


def test_a_title_wrapped_onto_a_row_with_a_page_number_continues(tmp_path):
    pdf = _write_rows(tmp_path / "wrap2.pdf", [
        (100, [(100, "C.5", "hebo"), (130, "Resizing a Hash Table While Readers", "helv")]),
        (114, [(130, "Keep Working", "helv"), (455, "C-45", "helv")]),
    ])
    texts = [b.text for b in extract(pdf).blocks if b.translatable]
    assert texts == ["Resizing a Hash Table While Readers Keep Working"]


def test_a_font_used_mostly_for_numbers_is_not_a_math_font():
    from ratica.extract import symbolic_fonts
    spans = [("AdvOTnum", "A.1"), ("AdvOTnum", "1.10"), ("AdvOTnum", "2.3"), ("AdvOTnum", "Appendix D")]
    assert symbolic_fonts(spans) == set()


def test_a_symbol_with_no_character_code_is_recognised_by_its_shape(tmp_path):
    from ratica.extract import identify_glyph
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((100, 100), "×", fontname="tiro", fontsize=10)
    span = {"bbox": tuple(pymupdf.Rect(99, 90, 108, 102)), "font": "AdvP4C4E74", "text": "\x01"}
    assert identify_glyph(page, span) == "×"
    blank = {"bbox": (300, 300, 308, 310), "font": "AdvP4C4E74", "text": "\x02"}
    assert identify_glyph(page, blank) is None


def test_a_recognised_symbol_in_a_sentence_keeps_the_sentence_translatable(tmp_path, monkeypatch):
    import ratica.extract as ex
    monkeypatch.setattr(ex, "identify_glyph", lambda page, span: "×")
    doc = pymupdf.open()
    page = doc.new_page()
    tiro, helv = pymupdf.Font("tiro"), pymupdf.Font("helv")  # helv sets only the unreadable sign here
    for y, parts in ((100, ("In our small test we filled a grid of 4", "¼", "4 cells before we sorted the rows.")),
                     (200, ("a", "¼", "b"))):
        tw = pymupdf.TextWriter(page.rect)
        x = tw.append((72, y), parts[0], font=tiro, fontsize=10)[1].x
        x = tw.append((x, y), parts[1], font=helv, fontsize=10)[1].x
        tw.append((x, y), parts[2], font=tiro, fontsize=10)
        tw.write_text(page)
    doc.save(tmp_path / "x.pdf")
    kinds = [(b.kind, b.text) for b in extract(tmp_path / "x.pdf").blocks]
    assert ("paragraph", "In our small test we filled a grid of 4×4 cells before we sorted the rows.") in kinds
    assert ("formula", "a×b") in kinds  # too short to be a sentence: an equation


def test_a_short_title_is_not_continued_by_the_next_row(tmp_path):
    pdf = _write_rows(tmp_path / "toc2.pdf", [
        (100, [(100, "A.1", "hebo"), (130, "A Worked Example: Building a Small Cache Library", "helv"),
               (455, "A-33", "helv")]),
        (114, [(100, "A.2", "hebo"), (130, "Further Reading and Notes", "helv"), (455, "A-47", "helv")]),
        (128, [(130, "Exercises by Ada Writer", "helv"), (455, "A-47", "helv")]),
    ])
    texts = [b.text for b in extract(pdf).blocks if b.translatable]
    assert texts[-2:] == ["Further Reading and Notes", "Exercises by Ada Writer"]


def test_mixed_styles_use_the_plain_style_unless_nearly_all_text_has_it(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    tw = pymupdf.TextWriter(page.rect)
    x = tw.append((72, 100), "Sorting Basics:", font=pymupdf.Font("tiit"), fontsize=10)[1].x
    tw.append((x, 100), " Chapter 3", font=pymupdf.Font("tiro"), fontsize=10)
    tw.write_text(page)
    doc.save(tmp_path / "mixed.pdf")
    part = extract(tmp_path / "mixed.pdf").blocks[0].parts[0]
    assert not part.italic


def test_ragged_paragraphs_are_not_marked_justified(tmp_path):
    pdf = _write_rows(tmp_path / "rag.pdf", [
        (100, [(72, "New information and communications technologies, in particular", "helv")]),
        (112, [(72, "high-speed Internet, are changing the way", "helv")]),
        (124, [(72, "companies do business and deliver public services.", "helv")]),
    ])
    assert not extract(pdf).blocks[0].parts[0].justified


def test_subscripts_do_not_decide_the_font_size_and_make_a_formula(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    tw = pymupdf.TextWriter(page.rect)
    x = tw.append((90, 200), "Power", font=pymupdf.Font("tiit"), fontsize=10)[1].x
    tw.append((x, 203), "dynamic", font=pymupdf.Font("tiit"), fontsize=7)
    tw.write_text(page)
    doc.save(tmp_path / "sub.pdf")
    block = extract(tmp_path / "sub.pdf").blocks[0]
    assert block.kind == "formula" and block.parts[0].size == 10


def test_straight_quotes_become_curly_when_the_source_uses_curly_ones():
    from ratica.queue import _clean
    assert _clean("“A classic” he said.", '"Bir klasik" dedi.') == "“Bir klasik” dedi."
    assert _clean('"Plain" quotes.', '"Düz" tırnak.') == '"Düz" tırnak.'


def test_two_rows_split_by_a_bar_of_dashes_are_a_formula(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    tw = pymupdf.TextWriter(page.rect)
    for y, x, text in ((450, 370, "Bytes Read From Disk"), (456, 368, "-" * 30), (462, 375, "Bytes Requested")):
        tw.append((x, y), text, font=pymupdf.Font("tiro"), fontsize=8)
    tw.write_text(page)
    doc.save(tmp_path / "frac.pdf")
    assert {b.kind for b in extract(tmp_path / "frac.pdf").blocks} == {"formula"}


def test_office_sans_fonts_are_not_serif_even_when_flagged():
    from ratica.extract import looks_serif
    assert not looks_serif("Aptos", flags=4)
    assert not looks_serif("ABCDEF+Aptos-Bold", flags=20)


def test_trailing_blanks_do_not_cut_the_last_letter_off_a_box(tmp_path):
    from ratica.extract import _ink_rect
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((73, 100), "Monday  ", fontname="hebo", fontsize=11)
    span = page.get_text("dict")["blocks"][0]["lines"][0]["spans"][0]
    assert span["text"] == "Monday  "
    assert _ink_rect(span).x1 >= 73 + pymupdf.get_text_length("Monday", "hebo", 11) - 0.5


def test_a_line_wrapping_back_under_an_inline_label_continues_the_sentence(tmp_path):
    pdf = _write_rows(tmp_path / "hang.pdf", [
        (100, [(73, "Monday", "hebo"), (118, "The library opened a new reading room for the", "helv")]),
        (114, [(73, "Faculty of Arts and its visiting students.", "helv")]),
        (140, [(73, "Friday", "hebo"), (118, "A short event.", "helv")]),
    ])
    texts = [b.text for b in extract(pdf).blocks if b.translatable]
    assert texts == ["Monday", "The library opened a new reading room for the Faculty of Arts and its visiting students.",
                     "Friday", "A short event."]


def test_a_bold_subject_does_not_cut_a_sentence_in_two(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    tw = pymupdf.TextWriter(page.rect)
    x = tw.append((72, 100), "OUR SCHOOL,", font=pymupdf.Font("hebo"), fontsize=11)[1].x
    tw.append((x + 8, 100), "moved up one place compared with the previous year.", font=pymupdf.Font("helv"), fontsize=11)
    tw.write_text(page)
    doc.save(tmp_path / "subj.pdf")
    texts = [b.text for b in extract(tmp_path / "subj.pdf").blocks if b.translatable]
    assert texts == ["OUR SCHOOL, moved up one place compared with the previous year."]


def test_a_wrapped_line_starting_with_a_number_is_not_a_list_item(tmp_path):
    text = "The survey placed the library at\n36. place, its best result so far."
    blocks = extract(write_pages(tmp_path / "num.pdf", [[(text, "helv", 11, 90)]])).blocks
    assert [(b.kind, b.text) for b in blocks] == [("paragraph", "The survey placed the library at 36. place, its best result so far.")]


def test_an_inline_label_set_apart_by_two_blanks_keeps_its_own_style(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    tw = pymupdf.TextWriter(page.rect)
    tw.append((73, 100), "Monday  ", font=pymupdf.Font("hebo"), fontsize=11)
    x = 73 + pymupdf.get_text_length("Monday  ", "hebo", 11)
    tw.append((x, 100), "The library opened a new reading room.", font=pymupdf.Font("helv"), fontsize=11)
    tw.write_text(page)
    doc.save(tmp_path / "lbl.pdf")
    assert [b.text for b in extract(tmp_path / "lbl.pdf").blocks] == ["Monday", "The library opened a new reading room."]
