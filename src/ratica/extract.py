"""Read a text-based PDF into a Book: headings, paragraphs, list items, code, formulas and images,
in reading order.

Running headers, footers and page numbers are dropped. Monospaced text becomes a code block
and text set in math/symbol fonts becomes a formula; neither is translated. Every block
remembers where it sits on the page and how it looks, so the translation can be written back
into the original layout.
"""
import re
from collections import Counter
from pathlib import Path

import pymupdf

from .docmodel import Block, Book, Part

MARGIN = 0.08  # top/bottom share of the page where running headers and footers live
HEADING_RATIO = 1.3  # font size relative to body text that makes a heading
MIN_IMAGE = 24  # points; smaller images are icons or decoration
FORMULA_SHARE = 0.3  # a block with this share of math-font characters is a formula
# PyMuPDF span flags
ITALIC, SERIF, MONO, BOLD = 2, 4, 8, 16
MATH_FONT = re.compile(r"symbol|math|cmsy|cmmi|cmex|msam|msbm|mt ?extra|euclid|stix|mathpi|mtsy|mtmi|wasy",
                       re.I)
# Control codes, private-use code points and replacement characters: glyphs a font maps to no real character.
UNMAPPED = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f-�]")
# Latin-1 characters that math fonts commonly (mis)map their "=" and parentheses to.
MISENCODED_MATH = re.compile("[¼½¾ðÞþÐ]")
SCRIPT_RATIO = 0.8  # a span this much smaller than its line, on a shifted baseline, is a sub- or superscript
FORMULA_SCRIPTS = 2  # short blocks with this many sub/superscripts are formulas
FORMULA_MAX_CHARS = 300
FRAGMENT_MAX_CHARS = 60  # short pieces right above/below a formula (numerators, denominators) belong to it


SANS_NAME = re.compile(r"sans|arial|helvet|avenir|frutiger|myriad|calibri|verdana|tahoma|segoe|roboto|lato|"
                       r"inter\b|open ?sans|futura|gill|univers|franklin|trebuchet|dejavu ?sans|source ?sans|"
                       r"fira|ubuntu|montserrat|poppins|ibm ?plex ?sans|gothic|aptos|corbel|candara|bahnschrift|grandview|"
                       r"seaford|tenorite|nunito|raleway|source ?han ?sans|noto ?sans|manrope|work ?sans", re.I)
SERIF_NAME = re.compile(r"serif|times|roman|garamond|georgia|minion|palatino|caslon|cambria|baskerville|bodoni|"
                        r"book ?antiqua|century|charter|charis|utopia|libertin|lucida ?bright|cmr\d|lmroman|"
                        r"nimbus ?rom|stix|sabon|plantin|janson|bembo|constantia", re.I)
BOLD_NAME = re.compile(r"bold|black|heavy|semibold|demi|extrabold|ultra|\.B$|\.BI$", re.I)
ITALIC_NAME = re.compile(r"italic|oblique|\.I$|\.BI$", re.I)
SUBSET = re.compile(r"^[A-Z]{6}\+")  # "ABCDEF+" marks an embedded subset of a font


def _base_name(font: str) -> str:
    return SUBSET.sub("", font)


def _shape(font: str, shapes: dict | None):
    """(serif, bold) measured from the glyphs, for fonts whose name is meaningless ("AdvOT3b30f6db")."""
    if not shapes:
        return None
    name = _base_name(font)
    return shapes.get(name) or shapes.get(re.sub(r"\+\d+$", "", name))  # "+20": an extra encoding of a font


def looks_serif(font: str, flags: int, shapes: dict | None = None) -> bool:
    """PDF serif flags are often wrong; the font's name, then its glyph shapes, are better hints."""
    name = _base_name(font)
    if SANS_NAME.search(name):
        return False
    if SERIF_NAME.search(name):
        return True
    shape = _shape(font, shapes)
    return shape[0] if shape else bool(flags & SERIF)


def looks_bold(font: str, flags: int, shapes: dict | None = None) -> bool:
    shape = _shape(font, shapes)
    return bool(BOLD_NAME.search(_base_name(font))) or bool(flags & BOLD) or bool(shape and shape[1])


def looks_italic(font: str, flags: int) -> bool:
    return bool(ITALIC_NAME.search(_base_name(font))) or bool(flags & ITALIC)


SERIF_FOOT = 1.3  # a stem this much wider at its foot than in its middle ends in a serif
BOLD_STEM = 0.15  # stem width relative to the letter's height, above which a font is bold


def _glyph_shape(buffer: bytes):
    """(serif, bold) from how an "l", "I" or "i" of the font is drawn, or None if it has none of them."""
    try:
        font = pymupdf.Font(fontbuffer=buffer)
    except (RuntimeError, ValueError):
        return None
    for ch in "lIi":
        if not font.has_glyph(ord(ch)):
            continue
        doc = pymupdf.open()
        page = doc.new_page(width=200, height=200)
        try:
            page.insert_font(fontname="F", fontbuffer=buffer)
            page.insert_text((50, 150), ch, fontname="F", fontsize=120)
        except (RuntimeError, ValueError):
            return None
        pix = page.get_pixmap(dpi=72, colorspace=pymupdf.csGRAY)
        widths = []
        for y in range(pix.height):
            row = pix.samples[y * pix.stride: y * pix.stride + pix.width]
            ink = [x for x, v in enumerate(row) if v < 128]
            widths.append(ink[-1] - ink[0] + 1 if ink else 0)
        rows = [y for y, w in enumerate(widths) if w]
        if len(rows) < 20:
            continue
        top, bottom = rows[0], rows[-1]
        middle = widths[top + (bottom - top) * 6 // 10]
        if not middle:
            continue
        return widths[bottom - 2] >= SERIF_FOOT * middle, middle / (bottom - top) >= BOLD_STEM
    return None


def font_shapes(doc) -> dict[str, tuple[bool, bool]]:
    """(serif, bold) for every embedded font of ``doc``, judged by the shape of its letters."""
    shapes, seen = {}, set()
    for pno in range(len(doc)):
        for xref, _, _, basefont, *_ in doc.get_page_fonts(pno):
            name = _base_name(basefont)
            if name in seen:
                continue
            seen.add(name)
            try:
                buffer = doc.extract_font(xref)[3]
            except (RuntimeError, ValueError):
                continue
            shape = _glyph_shape(buffer) if buffer else None
            if shape:
                shapes[name] = shape
    return shapes


def has_unmapped_chars(text: str) -> bool:
    """True when the PDF's font maps glyphs to no real character: re-typesetting it would show boxes."""
    return bool(UNMAPPED.search(text))


def _is_mono(span) -> bool:
    name = span["font"].lower()
    return bool(span["flags"] & MONO) or "cour" in name or "mono" in name


def _join_lines(lines: list[str]) -> str:
    text = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        line = " ".join(line.split())  # runs of blanks used for positioning become one space
        if text.endswith("-") and line[:1].islower():
            text = text[:-1] + line  # re-join a word hyphenated at the line end
        else:
            text = f"{text} {line}" if text else line
    return text


BULLETS = "•◦▪‣∙*–■□●○◆►-"
ITEM = re.compile(r"^\s*([•◦▪‣∙*–■□●○◆►-]|[a-z]\.|\d{1,2}\s?\.)\s+")


def _split_items(lines: list[dict]):
    """Split a block's lines into (marker, lines) segments at bullet or enumerator line starts.

    A marker drawn as a span of its own is left out of the item's spans, so the item's box starts at
    its text and the original marker stays on the page untouched."""
    segments = [["", []]]
    for i, line in enumerate(lines):
        m = ITEM.match(line["text"])
        # "36. place" right after a line that did not end its sentence is a wrapped line, not item 36.
        if m and m.group(1)[0].isdigit() and i and not re.search(r"[.:!?)]\s*$", lines[i - 1]["text"]):
            m = None
        if m:
            marker = m.group(1).replace(" ", "")
            spans = line["spans"]
            own = len(spans) > 1 and spans[0]["text"].strip() == marker
            segments.append([marker, [{**line, "text": line["text"][m.end():], "spans": spans[1:] if own else spans,
                                       "own_marker": own}]])
        else:
            segments[-1][1].append(line)
    return [(marker, seg) for marker, seg in segments if any(l["text"].strip() for l in seg)]


def _split_disjoint(lines: list[dict]) -> list[list[dict]]:
    """Lines that do not overlap side to side (a number at the right edge, a label at the left) are not
    one paragraph."""
    groups = [[lines[0]]] if lines else []
    for prev, line in zip(lines, lines[1:]):
        if line["bbox"][0] > prev["bbox"][2] or line["bbox"][2] < prev["bbox"][0]:
            groups.append([])
        groups[-1].append(line)
    return groups


def _split_indents(lines: list[dict]) -> list[list[dict]]:
    """Split a block at first-line indents: books often set paragraphs without space between them."""
    if len(lines) < 3:
        return [lines]
    left = min(l["bbox"][0] for l in lines)
    right = max(l["bbox"][2] for l in lines)
    size = lines[0]["spans"][0]["size"]
    pieces = [[lines[0]]]
    for i in range(1, len(lines)):
        line, prev = lines[i], lines[i - 1]
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        starts = (line["bbox"][0] > left + INDENT * size and nxt is not None and nxt["bbox"][0] < left + 0.3 * size
                  and prev["bbox"][2] < right - size)
        if starts:
            pieces.append([])
        pieces[-1].append(line)
    return pieces


STYLE_SHARE = 0.8  # bold or italic only when nearly all of a text has it (not for an emphasised word)


def _style(spans, page: int, rect, text: str, lines: int, shapes=None) -> Part:
    """The look of the text that makes up most of the characters."""
    weight, bold, italic = Counter(), 0, 0
    largest = max(s["size"] for s in spans)
    spans = [s for s in spans if s["size"] >= SCRIPT_RATIO * largest] or spans  # sub/superscripts do not count
    for s in spans:
        font, flags, n = s["font"], s["flags"], len(s["text"].strip())
        weight[(round(s["size"], 1), looks_serif(font, flags, shapes), s["color"])] += n
        bold += n * looks_bold(font, flags, shapes)
        italic += n * looks_italic(font, flags)
    (size, serif, color), _ = weight.most_common(1)[0]
    total = max(sum(weight.values()), 1)
    return Part(page=page, rect=tuple(round(v, 2) for v in rect), size=size, serif=serif,
                bold=bold >= STYLE_SHARE * total, italic=italic >= STYLE_SHARE * total, color=color,
                chars=len(text), lines=lines)


BLANK = 0.28  # width of a blank, in font sizes (blanks are much narrower than letters)


def _line_box(line) -> pymupdf.Rect:
    box = _ink_rect(line["spans"][0])
    for s in line["spans"][1:]:
        box |= _ink_rect(s)
    return box


def _ink_rect(span) -> pymupdf.Rect:
    """The span's box without leading/trailing blanks."""
    text = span["text"]
    x0, y0, x1, y1 = span["bbox"]
    n = max(len(text), 1)
    lead, trail = len(text) - len(text.lstrip()), len(text) - len(text.rstrip())
    w = x1 - x0
    blank = min(BLANK * span["size"], w / n)
    return pymupdf.Rect(x0 + blank * lead, y0, x1 - blank * trail, y1)


def _script_spans(lines) -> int:
    """Count sub- and superscripts: spans clearly smaller than their line and off its baseline."""
    count = 0
    for line in lines:
        spans = line["spans"]
        if len(spans) < 2:
            continue
        main = max(spans, key=lambda s: (s["size"], len(s["text"].strip())))
        for s in spans:
            if s["size"] <= SCRIPT_RATIO * main["size"] and abs(s["origin"][1] - main["origin"][1]) > 1:
                count += 1
    return count


def _font(span) -> str:
    return _base_name(span["font"])


def symbolic_fonts(spans) -> set[str]:
    """Fonts that set mathematics: named like one, or mostly symbols rather than letters.

    Such fonts often map their glyphs to wrong characters (``¼`` for "=", ``ð Þ`` for parentheses),
    so text set in them can never be re-typeset safely. ``spans`` is (font name, text) pairs.
    """
    letters, total = Counter(), Counter()
    for font, text in spans:
        font = _base_name(font)
        chars = [c for c in text if not c.isspace()]
        total[font] += len(chars)
        letters[font] += sum(c.isascii() and c.isalnum() for c in chars)  # numbers are text too ("A.1")
    return {f for f in total if MATH_FONT.search(f) or (total[f] and letters[f] < 0.5 * total[f])}


def _is_vertical(line) -> bool:
    dx, dy = line["dir"]
    return abs(dx - 1) > 0.01 or abs(dy) > 0.01


LABEL_GAP = 1.5  # a gap wider than this many font sizes separates cells of a row (table, contents, label)
STYLE_GAP = 0.45  # a narrower gap is enough when the style changes too ("xiv ■ Contents", "Monday  The…")
WORD_GAP = 0.15  # spans further apart than this many font sizes have a space between them
INDENT = 0.8  # a first line indented this many font sizes starts a new paragraph
# Text with nothing to translate: symbols, numbers, page references ("A-12", "R-1"), roman page numbers.
NO_WORDS = re.compile(r"^[\W\d_]*$|^[ivxlc]{1,7}$|^[A-Z]{1,2}[-.]\d+(\.\d+)*$")


def _looks(span):
    return _font(span), round(span["size"], 1), span["color"]


def _span_text(spans) -> str:
    text, prev = "", None
    for s in spans:
        if (prev is not None and not text.endswith(" ") and not s["text"].startswith(" ")
                and _ink_rect(s).x0 - _ink_rect(prev).x1 > WORD_GAP * prev["size"]):
            text += " "
        text += s["text"]
        prev = s
    return text


def _rows(lines: list[dict]) -> list[dict]:
    """Group PyMuPDF lines that share a baseline into visual rows (tables and contents pages often
    store every cell as a line of its own)."""
    groups = []
    for line in lines:
        if not line["spans"]:
            continue
        y0, y1 = line["bbox"][1], line["bbox"][3]
        for g in groups[-3:]:
            gy0, gy1 = g[0]["bbox"][1], g[0]["bbox"][3]
            if min(y1, gy1) - max(y0, gy0) > 0.5 * min(y1 - y0, gy1 - gy0):
                g.append(line)
                break
        else:
            groups.append([line])
    rows = []
    for g in groups:
        g.sort(key=lambda l: l["bbox"][0])
        bbox = pymupdf.Rect(g[0]["bbox"])
        for l in g[1:]:
            bbox |= l["bbox"]
        rows.append({"text": " ".join(l["text"].strip() for l in g), "bbox": tuple(bbox),
                     "spans": [s for l in g for s in l["spans"]]})
    return rows


def _cells(row: dict) -> list[dict]:
    """Split a row at wide gaps into cells; a row without such gaps is one cell."""
    spans = row["spans"]
    runs = [[spans[0]]]
    for s in spans[1:]:
        last = runs[-1][-1]
        gap = _ink_rect(s).x0 - _ink_rect(last).x1
        bullet = len(runs) == 1 and len(runs[0]) == 1 and last["text"].strip() in BULLETS  # a list item
        # A bold subject ("OUR SCHOOL, moved up…") is part of the sentence, not a label of its own.
        sentence_goes_on = last["text"].rstrip()[-1:] in ",;:" or s["text"].lstrip()[:1].islower()
        # A number set apart from words is a cell of its own ("Units.   1.258   1.397").
        number_edge = bool(NO_WORDS.match(_span_text(runs[-1]).strip())) != bool(NO_WORDS.match(s["text"].strip()))
        if not bullet and (gap > LABEL_GAP * last["size"]
                           or (gap > STYLE_GAP * last["size"] and (number_edge or _looks(s) != _looks(last))
                               and not sentence_goes_on)):
            runs.append([])
        runs[-1].append(s)
    if len(runs) == 1:
        return [row]
    cells = []
    for run in runs:
        bbox = _ink_rect(run[0])
        for s in run[1:]:
            bbox |= _ink_rect(s)
        cells.append({"text": _span_text(run), "bbox": tuple(bbox), "spans": run})
    return cells


def _wraps_into(seg: list[dict], cell: dict, cells: list[dict], row_x0: float | None = None) -> bool:
    """True when ``cell`` is the rest of ``seg`` wrapped onto the next row: same style, the same left edge
    (or, after an inline label like "Monday  The library…", the left edge of the label's row), and its
    first word would not have fitted on the line above."""
    last = seg[-1]
    x = cell["bbox"][0]
    aligned = abs(seg[0]["bbox"][0] - x) < 3 or (row_x0 is not None and abs(row_x0 - x) < 3)
    if not aligned or _looks(last["spans"][-1]) != _looks(cell["spans"][0]):
        return False
    starts = [seg[0]["bbox"][0], x]
    edge = max(c["bbox"][2] for c in cells if any(abs(c["bbox"][0] - x0) < 3 for x0 in starts))
    word = (cell["text"].split() or [""])[0]
    return last["bbox"][2] + len(word) * 0.45 * cell["spans"][0]["size"] > edge - 1


def _cell_segments(rows: list[list[dict]], page_cells: list[dict] | None = None) -> list[list[dict]]:
    """Blocks laid out as rows of cells: every cell is its own piece of text, except that a cell that
    wraps the text of the cell above it (a long title) continues it. Only a row's single cell, or a cell
    that does not start in the first column, can continue."""
    everything = [c for cells in rows for c in cells] + (page_cells or [])  # column edges span blocks
    segments, columns = [], []
    for cells in rows:
        first = cells[0]
        row_x0 = columns[0][0] if columns else None
        last_seg = columns[-1][1] if columns else None
        target = next((seg for k, (x0, seg) in enumerate(columns)
                       if (len(cells) == 1 or k > 0)
                       and _wraps_into(seg, first, everything, row_x0 if seg is last_seg and k > 0 else None)), None)
        if target is not None:
            target.append(first)
            if len(cells) == 1:
                continue
            cells = cells[1:]
        columns = [(x0, seg) for x0, seg in columns if seg is target]
        for cell in cells:
            segments.append([cell])
            columns.append((cell["bbox"][0], segments[-1]))
        columns.sort(key=lambda c: c[0])
    return segments


GLYPH_GRID = 24
GLYPH_CANDIDATES = "×−±≤≥÷→←↑↓∞≈≠·•°µ′″–—≡∑∏√∂∆=+<>/()[]%*"
GLYPH_MATCH = 0.5  # similarity needed to trust a recognised symbol (1.0 = identical)
PROSE_WORDS = 12  # a recognised symbol makes text translatable only inside a sentence at least this long


def _ink_grid(pix):
    """The inked pixels, cropped and scaled into a square grid (keeping proportions), and the aspect ratio."""
    w, h, stride, data = pix.width, pix.height, pix.stride, pix.samples
    pts = [(x, y) for y in range(h) for x in range(w) if data[y * stride + x] < 128]
    if not pts:
        return None
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    side = max(bw, bh)
    ox, oy = (side - bw) / 2, (side - bh) / 2
    return {(int((x - x0 + ox) * GLYPH_GRID / side), int((y - y0 + oy) * GLYPH_GRID / side)) for x, y in pts}, bw / bh


_candidate_grids = {}


def _candidates():
    if not _candidate_grids:
        doc = pymupdf.open()
        for ch in GLYPH_CANDIDATES:
            page = doc.new_page(width=100, height=100)
            page.insert_text((20, 75), ch, fontname="tiro", fontsize=60)
            grid = _ink_grid(page.get_pixmap(dpi=72, colorspace=pymupdf.csGRAY))
            if grid:
                _candidate_grids[ch] = grid
    return _candidate_grids


def _similarity(a, b) -> float:
    (ga, ra), (gb, rb) = a, b
    return len(ga & gb) / max(len(ga | gb), 1) * min(ra, rb) / max(ra, rb)


_identified = {}


def identify_glyph(page, span) -> str | None:
    """Recognise a symbol whose font maps it to no real character (a "×" stored as "\x01") by comparing
    its drawn shape with common symbols. Returns None when no symbol is a clear match."""
    key = (_font(span), span["text"])
    if key not in _identified:
        pix = page.get_pixmap(clip=pymupdf.Rect(span["bbox"]), dpi=600, colorspace=pymupdf.csGRAY)
        grid = _ink_grid(pix)
        found = None
        if grid:
            ranked = sorted(((_similarity(grid, g), ch) for ch, g in _candidates().items()), reverse=True)
            (best, ch), (second, _) = ranked[0], ranked[1]
            if best >= GLYPH_MATCH and best >= 2 * second:
                found = ch
        if not grid:  # nothing drawn here (yet): do not remember, another page may show it
            return None
        _identified[key] = found
    return _identified[key]


def drop_accents(spans: list[dict]) -> list[dict]:
    """Remove accents that a PDF draws as glyphs of their own over a letter ("Jos" + "´" + "e"):
    they are not characters of the text, and in symbol fonts they look like mathematics."""
    kept = []
    for i, s in enumerate(spans):
        mark = s["text"].strip()
        if len(mark) == 1 and not mark.isalnum():
            x0, x1 = s["bbox"][0], s["bbox"][2]
            width = max(x1 - x0, 0.1)
            over = [min(x1, n["bbox"][2]) - max(x0, n["bbox"][0]) for n in (spans[i - 1:i] + spans[i + 1:i + 2])
                    if any(c.isalpha() for c in n["text"])]
            if over and max(over) >= 0.5 * width:
                continue
        kept.append(s)
    return kept


def _recognise(page, span, symbolic):
    """A single unreadable symbol inside text gets its real character back when its shape is recognised."""
    text = span["text"].strip()
    if len(text) == 1 and _font(span) in symbolic and (UNMAPPED.search(text) or MISENCODED_MATH.search(text)):
        ch = identify_glyph(page, span)
        if ch:
            return {**span, "text": span["text"].replace(text, ch), "recognised": True}
    return span


FRACTION_BAR = re.compile(r"^[-–—_─]{4,}$")  # some PDFs draw a fraction bar as a row of dashes


def _has_fraction_bar(rows: list[dict]) -> bool:
    """True when a row of dashes sits between two rows of text: a fraction."""
    return any(FRACTION_BAR.match(r["text"].replace(" ", "")) for r in rows[1:-1])


def _page_cells(content) -> list[dict]:
    """Every cell of every row on a page (to know how far each column reaches)."""
    cells = []
    for b in content["blocks"]:
        if b["type"] == 0:
            lines = [{"text": "".join(s["text"] for s in l["spans"]), "bbox": l["bbox"],
                      "spans": [s for s in l["spans"] if s["text"].strip()]} for l in b["lines"]]
            cells += [c for r in _rows(lines) for c in _cells(r)]
    return cells


def _raw_blocks(doc, page_dicts, symbolic: set[str], shapes=None):
    """Yield one dict per text segment or image, with its text, style and position."""
    for pno, (page, content) in enumerate(zip(doc, page_dicts), start=1):
        height = page.rect.height
        page_cells = None
        for b in content["blocks"]:
            if b["type"] == 1:
                x0, y0, x1, y1 = b["bbox"]
                if x1 - x0 >= MIN_IMAGE and y1 - y0 >= MIN_IMAGE:
                    yield {"image": b["image"], "ext": b["ext"], "width": x1 - x0, "page": pno, "in_margin": False,
                           "mono": False, "formula": False, "figure": False, "mark": False, "text": "", "size": 0,
                           "keep": [], "marker": "", "part": None}
                continue
            if b["type"] != 0:
                continue
            lines = []
            for l in b["lines"]:
                line_spans = [_recognise(page, sp, symbolic) for sp in drop_accents(l["spans"])]
                lines.append({"text": "".join(s["text"] for s in line_spans), "bbox": l["bbox"],
                              "spans": [s for s in line_spans if s["text"].strip()]})
            spans = [s for l in lines for s in l["spans"]]
            if not spans:
                continue
            chars = sum(len(s["text"].strip()) for s in spans)
            math_spans = [s for s in spans if _font(s) in symbolic and not s.get("recognised")]
            math_chars = sum(len(s["text"].strip()) for s in math_spans)
            misencoded = any(MISENCODED_MATH.search(s["text"]) or UNMAPPED.search(s["text"]) for s in math_spans)
            if any(s.get("recognised") for s in spans) and sum(len(l["text"].split()) for l in lines) < PROSE_WORDS:
                misencoded = True  # a recognised symbol in a short text: an equation, keep it as it is
            mono = all(_is_mono(s) for s in spans)
            keep = [] if mono else [s["text"].strip() for s in spans if _is_mono(s)]
            y0, y1 = b["bbox"][1], b["bbox"][3]
            base = {"mono": mono, "page": pno, "in_margin": y1 < height * MARGIN or y0 > height * (1 - MARGIN),
                    "figure": any(_is_vertical(l) for l in b["lines"])}
            scripted = _script_spans(lines) >= FORMULA_SCRIPTS and chars < FORMULA_MAX_CHARS
            rows = _rows(lines)
            fraction = len(rows) >= 3 and chars < FORMULA_MAX_CHARS and _has_fraction_bar(
                sorted(rows, key=lambda r: r["bbox"][1]))
            if mono or base["figure"] or misencoded or math_chars >= FORMULA_SHARE * chars or scripted or fraction:
                text = "\n".join(l["text"].rstrip() for l in lines if l["text"].strip())
                part = _style(spans, pno, b["bbox"], text, len(lines), shapes)
                yield {**base, "text": text, "keep": [], "marker": "", "mark": False,
                       "formula": not mono and not base["figure"], "size": part.size, "part": part}
                continue
            cells = [_cells(r) for r in rows]
            if any(len(c) > 1 for c in cells):
                if page_cells is None:
                    page_cells = _page_cells(content)
                segments = [("", seg) for seg in _cell_segments(cells, page_cells)]
            else:
                segments = [(marker, piece) for group in _split_disjoint([c[0] for c in cells])
                            for marker, seg in _split_items(group)
                            for piece in (_split_indents(seg) if not marker else [seg])]
            for marker, seg in segments:
                text = _join_lines([l["text"] for l in seg])
                seg_spans = [s for l in seg for s in l["spans"]]
                rect = _ink_rect(seg_spans[0])
                for s in seg_spans[1:]:
                    rect |= _ink_rect(s)
                part = _style(seg_spans, pno, rect, text, len(seg), shapes)
                part.indent = round(max(0.0, seg[0]["bbox"][0] - min(l["bbox"][0] for l in seg)), 2)
                part.marker_in_box = not seg[0].get("own_marker")
                part.boxes = [tuple(round(v, 2) for v in _line_box(l)) for l in seg if l["spans"]]
                part.ascent = round(seg_spans[0]["origin"][1] - rect.y0, 2)
                if len(seg) >= 3:
                    rights = [l["bbox"][2] for l in seg[:-1]]
                    part.justified = max(rights) - min(rights) < 0.5 * part.size
                seg_misencoded = any(_font(s) in symbolic and not s.get("recognised") and MISENCODED_MATH.search(s["text"])
                                     for s in seg_spans)
                # A short text with sub- or superscripts ("Power" + "dynamic") is part of an equation.
                seg_scripted = _script_spans(seg) > 0 and len(text.split()) < PROSE_WORDS
                yield {**base, "text": text, "marker": marker, "keep": [k for k in keep if k in text],
                       "formula": has_unmapped_chars(text) or seg_misencoded or seg_scripted, "mark": not marker and bool(NO_WORDS.match(text)),
                       "size": part.size, "part": part}


def _furniture_keys(raw, pages: int) -> set[str]:
    """Texts in the page margins that repeat on many pages (digits normalized)."""
    if pages < 2:
        return set()
    seen = Counter()
    for r in raw:
        if r["in_margin"]:
            seen[(re.sub(r"\d+", "#", r["text"]))] += 1
    return {k for k, n in seen.items() if n >= max(2, pages // 2)}


PAGE_LABEL = re.compile(r"^\d+\s|\s\d+$|^\d+$")  # a page number at the start or end of a short margin line


def _is_furniture(r, furniture) -> bool:
    if not r["in_margin"]:
        return False
    text = r["text"]
    return re.sub(r"\d+", "#", text) in furniture or (len(text) < 80 and bool(PAGE_LABEL.search(text)))


def _continues(prev: Block, cur: Block) -> bool:
    """True when ``cur`` is the rest of a paragraph that ``prev`` left unfinished."""
    if not (prev.kind == cur.kind == "paragraph" and prev.parts and cur.parts):
        return False
    a, b = prev.parts[-1], cur.parts[0]
    return (not re.search(r"[.!?:;\"”')\]]$", prev.text) and cur.text[:1].islower()
            and (a.size, a.serif, a.bold, a.italic) == (b.size, b.serif, b.bold, b.italic))


def _absorb_fragments(blocks: list[Block]):
    """Short text pieces within a line's height above or below a formula (numerators, denominators,
    labels of a fraction) are part of that formula and must not be translated on their own."""
    for _ in range(2):  # a second pass catches stacked fractions
        formulas = [(b.page, pymupdf.Rect(b.parts[0].rect)) for b in blocks if b.kind == "formula" and b.parts]
        for b in blocks:
            if b.kind not in ("paragraph", "heading") or not b.parts or len(b.text) > FRAGMENT_MAX_CHARS:
                continue
            r = pymupdf.Rect(b.parts[0].rect)
            mid = (r.y0 + r.y1) / 2
            for page, f in formulas:
                reach = max(f.height, 8)
                if page == b.page and f.y0 - reach <= mid <= f.y1 + reach:
                    b.kind, b.level = "formula", 0
                    break


def _merge(blocks: list[Block]) -> list[Block]:
    out = []
    for b in blocks:
        if out and _continues(out[-1], b):
            prev = out[-1]
            prev.text = prev.text[:-1] + b.text if prev.text.endswith("-") else f"{prev.text} {b.text}"
            prev.keep += b.keep
            prev.parts += b.parts
        else:
            out.append(b)
    return out


def extract(path) -> Book:
    path = Path(path)
    doc = pymupdf.open(path)
    page_dicts = [page.get_text("dict", sort=True) for page in doc]
    symbolic = symbolic_fonts((s["font"], s["text"]) for d in page_dicts for b in d["blocks"]
                              for l in b.get("lines", []) for s in l["spans"])
    raw = list(_raw_blocks(doc, page_dicts, symbolic, font_shapes(doc)))
    furniture = _furniture_keys(raw, len(doc))
    # Running headers are translated in place; bare page numbers are dropped.
    for r in raw:
        r["header"] = _is_furniture(r, furniture)
    raw = [r for r in raw if not (r["header"] and not any(c.isalpha() for c in r["text"]))]

    body_sizes = Counter()
    for r in raw:
        if not r["mono"] and r["text"] and not r["header"]:
            body_sizes[r["size"]] += len(r["text"])
    body = body_sizes.most_common(1)[0][0] if body_sizes else 0
    heading_sizes = sorted({r["size"] for r in raw
                            if not r["mono"] and r["text"] and r["size"] >= body * HEADING_RATIO},
                           reverse=True)

    blocks = []
    for n, r in enumerate(raw):
        if "image" in r:
            blocks.append(Block(id=f"b{n:05d}", kind="image", text="", page=r["page"], image=r["image"],
                                image_ext=r["ext"], width=round(r["width"])))
            continue
        if r["mono"]:
            kind, level = "code", 0
        elif r["figure"]:
            kind, level = "figure", 0
        elif r["formula"]:
            kind, level = "formula", 0
        elif r["mark"]:
            kind, level = "mark", 0
        elif r["header"]:
            kind, level = "header", 0
        elif r["marker"]:
            kind, level = "item", 0
        elif r["size"] in heading_sizes and len(r["text"]) < 200:
            kind, level = "heading", heading_sizes.index(r["size"]) + 1
        else:
            kind, level = "paragraph", 0
        blocks.append(Block(id=f"b{n:05d}", kind=kind, text=r["text"], page=r["page"], level=level,
                            keep=r["keep"], marker=r["marker"], parts=[r["part"]]))
    _absorb_fragments(blocks)
    blocks = _merge(blocks)

    title = doc.metadata.get("title") or next((b.text for b in blocks if b.kind == "heading"), path.stem)
    return Book(source=str(path), title=title, blocks=blocks)
