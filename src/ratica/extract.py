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
                       r"fira|ubuntu|montserrat|poppins|ibm ?plex ?sans|gothic", re.I)
SERIF_NAME = re.compile(r"serif|times|roman|garamond|georgia|minion|palatino|caslon|cambria|baskerville|bodoni|"
                        r"book ?antiqua|century|charter|charis|utopia|libertin|lucida ?bright|cmr\d|lmroman|"
                        r"nimbus ?rom|stix|sabon|plantin|janson|bembo|constantia", re.I)
BOLD_NAME = re.compile(r"bold|black|heavy|semibold|demi|extrabold|ultra", re.I)


def looks_serif(font: str, flags: int) -> bool:
    """PDF serif flags are often wrong; the font's name is a better hint when it has one."""
    name = font.split("+")[-1]
    if SANS_NAME.search(name):
        return False
    if SERIF_NAME.search(name):
        return True
    return bool(flags & SERIF)


def looks_bold(font: str, flags: int) -> bool:
    return bool(BOLD_NAME.search(font.split("+")[-1])) or bool(flags & BOLD)


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


ITEM = re.compile(r"^\s*([•◦▪‣∙*–-]|[a-z]\.|\d{1,2}\s?\.)\s+")


def _split_items(lines: list[dict]):
    """Split a block's lines into (marker, lines) segments at bullet or enumerator line starts."""
    segments = [["", []]]
    for line in lines:
        m = ITEM.match(line["text"])
        if m:
            segments.append([m.group(1).replace(" ", ""), [{**line, "text": line["text"][m.end():]}]])
        else:
            segments[-1][1].append(line)
    return [(marker, seg) for marker, seg in segments if any(l["text"].strip() for l in seg)]


def _style(spans, page: int, rect, text: str, lines: int) -> Part:
    """The look of the text that makes up most of the characters."""
    weight = Counter()
    for s in spans:
        weight[(round(s["size"], 1), looks_serif(s["font"], s["flags"]), looks_bold(s["font"], s["flags"]),
                bool(s["flags"] & ITALIC), s["color"])] += len(s["text"].strip())
    (size, serif, bold, italic, color), _ = weight.most_common(1)[0]
    return Part(page=page, rect=tuple(round(v, 2) for v in rect), size=size, serif=serif, bold=bold, italic=italic,
                color=color, chars=len(text), lines=lines)


def _ink_rect(span) -> pymupdf.Rect:
    """The span's box without leading/trailing blanks (estimated in proportion to the character count)."""
    text = span["text"]
    x0, y0, x1, y1 = span["bbox"]
    n = max(len(text), 1)
    lead, trail = len(text) - len(text.lstrip()), len(text) - len(text.rstrip())
    w = x1 - x0
    return pymupdf.Rect(x0 + w * lead / n, y0, x1 - w * trail / n, y1)


def _script_spans(lines) -> int:
    """Count sub- and superscripts: spans clearly smaller than their line and off its baseline."""
    count = 0
    for line in lines:
        spans = line["spans"]
        if len(spans) < 2:
            continue
        main = max(spans, key=lambda s: len(s["text"].strip()))
        for s in spans:
            if s["size"] <= SCRIPT_RATIO * main["size"] and abs(s["origin"][1] - main["origin"][1]) > 1:
                count += 1
    return count


def _font(span) -> str:
    return span["font"].split("+")[-1]


def symbolic_fonts(spans) -> set[str]:
    """Fonts that set mathematics: named like one, or mostly symbols rather than letters.

    Such fonts often map their glyphs to wrong characters (``¼`` for "=", ``ð Þ`` for parentheses),
    so text set in them can never be re-typeset safely. ``spans`` is (font name, text) pairs.
    """
    letters, total = Counter(), Counter()
    for font, text in spans:
        font = font.split("+")[-1]
        chars = [c for c in text if not c.isspace()]
        total[font] += len(chars)
        letters[font] += sum(c.isascii() and c.isalpha() for c in chars)
    return {f for f in total if MATH_FONT.search(f) or (total[f] and letters[f] < 0.5 * total[f])}


def _is_vertical(line) -> bool:
    dx, dy = line["dir"]
    return abs(dx - 1) > 0.01 or abs(dy) > 0.01


LABEL_GAP = 1.5  # a gap wider than this many font sizes separates a margin label from its paragraph
LABEL_MAX_CHARS = 30


def _split_label(lines: list[dict]):
    """Split off a short label that starts the first line and is set apart by a wide gap
    ("Example   Assume a disk…"), so it keeps its own place on the page."""
    first = lines[0]
    if len(lines) > 1 and first["spans"]:
        # The label may be a line of its own, on the same baseline as the paragraph's first line.
        nxt = lines[1]
        same_row = abs(nxt["bbox"][1] - first["bbox"][1]) < 2
        gap = nxt["bbox"][0] - _ink_rect(first["spans"][-1]).x1
        short = sum(len(s["text"].strip()) for s in first["spans"]) <= LABEL_MAX_CHARS
        if same_row and short and gap > LABEL_GAP * first["spans"][-1]["size"]:
            return first, lines[1:]
    spans = first["spans"]
    for i in range(len(spans) - 1):
        gap = _ink_rect(spans[i + 1]).x0 - _ink_rect(spans[i]).x1  # blanks often fill the gap
        if gap > LABEL_GAP * spans[i]["size"]:
            head, rest = spans[: i + 1], spans[i + 1:]
            if sum(len(s["text"].strip()) for s in head) > LABEL_MAX_CHARS:
                break
            label = {"text": "".join(s["text"] for s in head), "bbox": head[0]["bbox"], "spans": head}
            first = {"text": "".join(s["text"] for s in rest), "bbox": rest[0]["bbox"], "spans": rest}
            return label, [first, *lines[1:]]
    return None, lines


def _split_row(lines: list[dict]) -> list[dict] | None:
    """A block that is a single row with wide gaps (legend entries, table cells) becomes one piece per
    gap-separated run of text. Returns None for ordinary blocks."""
    if not lines or any(abs(l["bbox"][1] - lines[0]["bbox"][1]) > 2 for l in lines):
        return None
    spans = sorted((s for l in lines for s in l["spans"]), key=lambda s: s["bbox"][0])
    runs, current = [], [spans[0]]
    for s in spans[1:]:
        if _ink_rect(s).x0 - _ink_rect(current[-1]).x1 > LABEL_GAP * current[-1]["size"]:
            runs.append(current)
            current = []
        current.append(s)
    runs.append(current)
    if len(runs) < 2:
        return None
    return [{"text": "".join(s["text"] for s in run), "bbox": run[0]["bbox"], "spans": run} for run in runs]


def _raw_blocks(doc, page_dicts, symbolic: set[str]):
    """Yield one dict per text segment or image, with its text, style and position."""
    for pno, (page, content) in enumerate(zip(doc, page_dicts), start=1):
        height = page.rect.height
        for b in content["blocks"]:
            if b["type"] == 1:
                x0, y0, x1, y1 = b["bbox"]
                if x1 - x0 >= MIN_IMAGE and y1 - y0 >= MIN_IMAGE:
                    yield {"image": b["image"], "ext": b["ext"], "width": x1 - x0, "page": pno, "in_margin": False,
                           "mono": False, "formula": False, "figure": False, "text": "", "size": 0, "keep": [],
                           "marker": "", "part": None}
                continue
            if b["type"] != 0:
                continue
            lines = [{"text": "".join(s["text"] for s in l["spans"]), "bbox": l["bbox"],
                      "spans": [s for s in l["spans"] if s["text"].strip()]} for l in b["lines"]]
            spans = [s for l in lines for s in l["spans"]]
            if not spans:
                continue
            chars = sum(len(s["text"].strip()) for s in spans)
            math_spans = [s for s in spans if _font(s) in symbolic]
            math_chars = sum(len(s["text"].strip()) for s in math_spans)
            misencoded = any(MISENCODED_MATH.search(s["text"]) or UNMAPPED.search(s["text"]) for s in math_spans)
            mono = all(_is_mono(s) for s in spans)
            keep = [] if mono else [s["text"].strip() for s in spans if _is_mono(s)]
            y0, y1 = b["bbox"][1], b["bbox"][3]
            base = {"mono": mono, "page": pno, "in_margin": y1 < height * MARGIN or y0 > height * (1 - MARGIN),
                    "figure": any(_is_vertical(l) for l in b["lines"])}
            scripted = _script_spans(lines) >= FORMULA_SCRIPTS and chars < FORMULA_MAX_CHARS
            if mono or base["figure"] or misencoded or math_chars >= FORMULA_SHARE * chars or scripted:
                text = "\n".join(l["text"].rstrip() for l in lines if l["text"].strip())
                part = _style(spans, pno, b["bbox"], text, len(lines))
                yield {**base, "text": text, "keep": [], "marker": "", "formula": not mono and not base["figure"],
                       "size": part.size, "part": part}
                continue
            label, lines = _split_label(lines)
            pieces = _split_row(lines)
            segments = ([("", [label])] if label else []) + (
                [("", [p]) for p in pieces] if pieces else _split_items(lines))
            for marker, seg in segments:
                text = _join_lines([l["text"] for l in seg])
                seg_spans = [s for l in seg for s in l["spans"]]
                rect = _ink_rect(seg_spans[0])
                for s in seg_spans[1:]:
                    rect |= _ink_rect(s)
                part = _style(seg_spans, pno, rect, text, len(seg))
                seg_misencoded = any(_font(s) in symbolic and MISENCODED_MATH.search(s["text"]) for s in seg_spans)
                yield {**base, "text": text, "marker": marker, "keep": [k for k in keep if k in text],
                       "formula": has_unmapped_chars(text) or seg_misencoded, "size": part.size, "part": part}


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
    return (prev.kind == cur.kind == "paragraph" and not re.search(r"[.!?:;\"”')\]]$", prev.text)
            and cur.text[:1].islower())


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
    raw = list(_raw_blocks(doc, page_dicts, symbolic))
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
