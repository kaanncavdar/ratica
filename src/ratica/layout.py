"""Write the translation into the original PDF, keeping its layout.

Each page is planned before anything changes:

1. For every translated block, find the room it may use: its own box, grown right to its
   column edge and down into free space, never touching other text, images, lines or
   filled shapes, and never leaving a coloured box it sits in.
2. Measure how much the translation must shrink to fit (as little as possible).
3. Give paragraphs of the same style on a page one common size, so the page looks even.
4. A translation that would need to shrink below MIN_SCALE is not written: that block keeps
   its original text instead of overlapping anything.

Only then is the original text of the planned blocks removed (images and drawings stay) and
the translations are written with a matching font, size, line spacing and colour. Blocks
that are not translated, such as code and formulas, are never touched.
"""
import html
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path

import pymupdf

from .docmodel import Block, Book, Part

MIN_SCALE = 0.6  # below this the text would be too small to read: keep the original instead
ONE_LINE_SCALE = 0.85  # a one-line text shrinks down to this before it may wrap onto more lines
EVEN_SCALE_FLOOR = 0.82  # paragraphs on a page are made equally small down to this size, not further
INSET = 0.8  # points; keeps the removal from touching neighbouring text
GAP = 2.0  # points kept free around other content
BODY_KINDS = {"paragraph", "item"}


def split_for_parts(text: str, parts: list[Part]) -> list[str]:
    """Split a translation over the boxes a paragraph originally spanned, in proportion to their length."""
    if len(parts) <= 1:
        return [text]
    words = text.split()
    total = sum(max(p.chars, 1) for p in parts)
    pieces, start, seen = [], 0, 0
    for p in parts[:-1]:
        seen += max(p.chars, 1)
        end = max(start + 1, min(len(words) - 1, round(len(words) * seen / total)))
        pieces.append(" ".join(words[start:end]))
        start = end
    pieces.append(" ".join(words[start:]))
    return pieces


def _leading(part: Part) -> float:
    """The original line spacing, from the box height and line count."""
    if part.lines > 1:
        leading = (part.rect[3] - part.rect[1]) / part.lines
    else:
        leading = part.size * 1.2
    return min(max(leading, part.size * 1.05), part.size * 1.6)


def _css(part: Part, block: Block, scale: float = 1.0, align: str = "") -> str:
    rgb = f"#{part.color:06x}"
    family = "Times" if part.serif else "sans-serif"  # Times sets ~9% narrower than the default serif
    align = align or ("justify" if block.kind == "paragraph" and part.lines >= 3 and part.justified else "left")
    return (f"* {{ font-family: {family}; font-size: {part.size * scale:.2f}px; "
            f"line-height: {_leading(part) * scale:.2f}px; color: {rgb}; "
            f"font-weight: {'bold' if part.bold else 'normal'}; font-style: {'italic' if part.italic else 'normal'}; "
            f"text-indent: {part.indent:.2f}px; text-align: {align}; margin: 0; padding: 0; }}")


_scratch = pymupdf.open()


def _needed_scale(body: str, css: str, rect: pymupdf.Rect) -> float:
    """How much the text must shrink to fit ``rect`` (1.0 = not at all).

    Measured by writing on a throwaway page with the very call used for the real page;
    Story.fit_scale over-estimates the height of short texts.
    """
    if rect.is_empty:
        return 0.0
    page = _scratch.new_page(width=rect.x1 + 10, height=rect.y1 + 10)
    try:
        spare, scale = page.insert_htmlbox(rect, body, css=css, scale_low=0)
    finally:
        _scratch.delete_page(-1)
    return scale if spare >= 0 else 0.0


_baselines: dict[str, float] = {}


def _baseline_offset(css: str) -> float:
    """How far below the top of its box ``insert_htmlbox`` puts the first baseline with this style."""
    if css not in _baselines:
        page = _scratch.new_page(width=400, height=200)
        try:
            page.insert_htmlbox(pymupdf.Rect(0, 0, 400, 200), "Hg", css=css)
            spans = [s for b in page.get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"]]
            _baselines[css] = spans[0]["origin"][1] if spans else 0.0
        finally:
            _scratch.delete_page(-1)
    return _baselines[css]


# --- where text may go ------------------------------------------------------------------------------------------

@dataclass
class Obstacles:
    lines: list[pymupdf.Rect]  # text lines and images
    shapes: list[pymupdf.Rect]  # vector drawings: rules, table borders, chart marks, filled boxes


def obstacles_on(page) -> Obstacles:
    """Everything on the page, read before anything is removed."""
    lines = []
    for b in page.get_text("dict")["blocks"]:
        if b["type"] == 1:
            lines.append(pymupdf.Rect(b["bbox"]))
        else:
            lines += [pymupdf.Rect(line["bbox"]) for line in b["lines"]
                      if any(s["text"].strip() for s in line["spans"])]
    shapes = [pymupdf.Rect(d["rect"]) for d in page.get_drawings()]
    return Obstacles(lines, shapes)


def room_to_the_left(rect: pymupdf.Rect, obs: Obstacles, page_rect: pymupdf.Rect) -> pymupdf.Rect | None:
    """For a one-line label set tight against something on its right ("Contents ■ xv"): the box it may
    take by growing to the left, up to the nearest content on its row. None when it is not such a label."""
    row = [o for o in obs.lines + obs.shapes if o.y1 > rect.y0 + 1 and o.y0 < rect.y1 - 1
           and (o & rect).get_area() < 0.5 * max(o.get_area(), 1)]
    size = rect.height
    if rect.x0 < page_rect.x0 + page_rect.width / 2 or not any(0 <= o.x0 - rect.x1 < 1.5 * size for o in row):
        return None
    left = max([page_rect.x0 + 36, *(o.x1 + GAP for o in row if o.x1 <= rect.x0 + 1)])
    return pymupdf.Rect(min(left, rect.x0), rect.y0, rect.x1, rect.y1) if left < rect.x0 - 1 else None


def room_for(rect: pymupdf.Rect, obs: Obstacles, page_rect: pymupdf.Rect, lines: int = 2,
             grow_down: bool = True) -> pymupdf.Rect:
    """The largest box that starts at ``rect`` and grows right to its column edge, then down into empty
    space, without touching any other content or leaving a box it sits in. A single line may grow right
    into any free space, so it stays one line."""
    page_area = page_rect.get_area()
    # Shapes that contain the text are its background (a coloured box): stay inside the smallest one.
    containers = [s for s in obs.shapes if s.contains(rect) and s.get_area() < 0.9 * page_area]
    limit = pymupdf.Rect(page_rect.x0 + min(rect.x0, 36), page_rect.y0, page_rect.x1 - min(rect.x0, 36),
                         page_rect.y1 - 36)
    if containers:
        limit &= min(containers, key=lambda s: s.get_area()) + (0, 0, -GAP, -GAP)
    others = [o for o in obs.lines if (o & rect).get_area() < 0.5 * max(o.get_area(), 1)]
    others += [s for s in obs.shapes if not s.contains(rect) and not (s & rect).get_area() >= 0.5 * rect.get_area()]
    # Right: the column edge is the widest line of similar size that starts where this block starts.
    line_h = rect.height / max(lines, 1)
    if lines == 1:
        right = limit.x1
    else:
        right = max([rect.x1, *(o.x1 for o in obs.lines if abs(o.x0 - rect.x0) < 30
                                and 0.7 * line_h <= o.height <= 1.4 * line_h)])
    right = min(right, limit.x1)
    for o in others:  # never run into something beside us
        if o.y1 > rect.y0 + 1 and o.y0 < rect.y1 - 1 and o.x0 >= rect.x1 - 1:
            right = min(right, o.x0 - GAP)
    right = max(right, rect.x1)
    # Down: until the next thing that shares any horizontal space, or the bottom margin.
    bottom = limit.y1
    for o in others:
        if o.y0 >= rect.y1 - 1 and o.x1 > rect.x0 and o.x0 < right:
            bottom = min(bottom, o.y0 - GAP)
    bottom = max(bottom, rect.y1) if grow_down else rect.y1
    return pymupdf.Rect(rect.x0, rect.y0, right, bottom)


# --- planning and writing ---------------------------------------------------------------------------------------

@dataclass
class Placement:
    part: Part
    block: Block
    body: str
    rect: pymupdf.Rect
    scale: float
    align: str = ""


def _boxes(part: Part) -> list[pymupdf.Rect]:
    return [pymupdf.Rect(b) for b in part.boxes] or [pymupdf.Rect(part.rect)]


def _text_width(text: str, part: Part) -> float:
    font = ("tibo" if part.bold else "tiro") if part.serif else ("hebo" if part.bold else "helv")
    return pymupdf.get_text_length(text, fontname=font, fontsize=part.size)


def _inline_labels(items):
    """Pair a one-line label with the text that starts beside it on the same line and wraps under it
    ("Monday  The library opened…"). The label is written at full size, and the text's first line starts
    after the translated label, however long it got. Returns {label item index: rect} and new items."""
    labels, items = {}, list(items)
    for i, (lab, lab_text, _) in enumerate(items):
        if lab.lines != 1:
            continue
        for j, (par, par_text, par_block) in enumerate(items):
            first = _boxes(par)[0]
            if (j == i or par.page != lab.page or abs(first.y0 - lab.rect[1]) > 3
                    or not (lab.rect[2] <= first.x0 + 2 and first.x0 - lab.rect[2] < 4 * par.size)):
                continue
            width = _text_width(lab_text, lab) + 1
            gap = max(first.x0 - lab.rect[2], 0.3 * par.size)
            labels[i] = pymupdf.Rect(lab.rect[0], lab.rect[1], lab.rect[0] + width, lab.rect[3] + 2)
            start = lab.rect[0] + width + gap  # where the text's first line may begin now
            if par.indent > 0 and par.rect[0] <= lab.rect[0] + 2:  # it wraps back under the label
                par = replace(par, indent=round(max(par.indent, start - par.rect[0]), 2))
            elif start > par.rect[0]:  # beside the label only: move the whole box over
                par = replace(par, rect=(round(start, 2), *par.rect[1:]))
            items[j] = (par, par_text, par_block)
            break
    return labels, items


def _plan_page(page, items: list[tuple[Part, str, Block]]) -> list[Placement]:
    obs = obstacles_on(page)
    labels, items = _inline_labels(items)
    plans = []
    for i, (part, text, block) in enumerate(items):
        body = html.escape(text)
        if i in labels:  # written whole on its line; the text beside it moves over
            plans.append(Placement(part, block, body, labels[i], 1.0))
            continue
        own = pymupdf.Rect(part.rect) + (0, 0, 1, 2)  # a little air below: line heights differ between fonts
        css = _css(part, block)
        need = _needed_scale(body, css, own)
        rect = own
        align = ""
        if need < 0.999 and part.lines == 1:  # a single line: rather stay one line, a little smaller
            room = room_for(pymupdf.Rect(part.rect), obs, page.rect, 1, grow_down=False) | own
            need, rect = max((need, rect), (_needed_scale(body, css, room), room), key=lambda c: c[0])
        if need < (ONE_LINE_SCALE if part.lines == 1 else 0.999):  # too long: use free space around it first
            room = room_for(pymupdf.Rect(part.rect), obs, page.rect, part.lines) | own
            need, rect = _needed_scale(body, css, room), room
        left = room_to_the_left(pymupdf.Rect(part.rect), obs, page.rect) if need < 0.999 and part.lines == 1 else None
        if left is not None:  # a right-aligned label: grow to the left instead
            left |= own
            left_need = _needed_scale(body, _css(part, block, align="right"), left)
            if left_need > need:
                need, rect, align = left_need, left, "right"
        plans.append(Placement(part, block, body, rect, need, align))

    # One size for all paragraphs of the same style on the page (down to EVEN_SCALE_FLOOR).
    groups = defaultdict(list)
    for p in plans:
        if p.block.kind in BODY_KINDS and p.part.lines >= 2 and p.scale >= MIN_SCALE:  # lines of a list stay
            groups[(round(p.part.size, 1), p.part.serif, p.part.bold)].append(p)
    for members in groups.values():
        even = max(EVEN_SCALE_FLOOR, min(p.scale for p in members))
        for p in members:
            p.scale = min(p.scale, even)
    return [p for p in plans if p.scale >= MIN_SCALE]


def write_layout_pdf(book: Book, translations: dict[str, str], path) -> Path:
    path = Path(path)
    doc = pymupdf.open(book.source)

    def translated(b):
        out = translations.get(b.id)
        return b.translatable and b.parts and out and out != b.text

    # Everything that stays as it is (formulas, code, untranslated text) must not be erased by accident.
    untouched: dict[int, list[pymupdf.Rect]] = defaultdict(list)
    for b in book.blocks:
        if b.parts and not translated(b):
            for p in b.parts:
                untouched[p.page].extend(_boxes(p))

    def overlaps_untouched(b):
        # Boxes of neighbouring lines touch by a point or two; only a real overlap counts.
        shrink = (0, 2, 0, -2)
        return any(((box + shrink) & (u + shrink)).get_area() > 1
                   for p in b.parts for box in _boxes(p) for u in untouched[p.page])

    per_page: dict[int, list] = defaultdict(list)
    for b in book.blocks:
        if not translated(b) or overlaps_untouched(b):
            continue
        for i, (part, piece) in enumerate(zip(b.parts, split_for_parts(translations[b.id], b.parts))):
            if b.kind == "item" and i == 0 and part.marker_in_box:
                piece = f"{b.marker} {piece}"
            per_page[part.page].append((part, piece, b))

    for pno, items in per_page.items():
        page = doc[pno - 1]
        plans = _plan_page(page, items)
        for p in plans:
            for box in _boxes(p.part):  # line by line: a label the text wraps under stays
                page.add_redact_annot(box + (0, INSET, 0, -INSET), fill=False)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
        for p in plans:
            css = _css(p.part, p.block, p.scale, p.align)
            # Put the first line on the original baseline (fonts differ in how high they sit in their box).
            dy = p.part.ascent - _baseline_offset(css) if p.part.ascent else 0.0
            page.insert_htmlbox(p.rect + (0, dy, 0, dy), p.body, css=css, scale_low=0)

    doc.set_metadata({**doc.metadata, "producer": "Ratica"})
    doc.save(path, garbage=3, deflate=True)
    doc.close()
    return path
