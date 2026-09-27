"""Write the translation into the original PDF, keeping its layout.

For every translated block, the original text is removed from its box (images, lines and
other text stay) and the translation is set in the same box with a similar font, size and
colour, shrinking the font when the translation is longer. Blocks that were not translated,
such as code and formulas, are left exactly as they were.
"""
import html
from collections import defaultdict
from pathlib import Path

import pymupdf

from .docmodel import Block, Book, Part

MIN_SCALE = 0.55  # shrink the font down to 55% before letting text run over the box
INSET = 0.8  # points; keeps the removal from touching neighbouring text


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


def _css(part: Part, block: Block) -> str:
    rgb = f"#{part.color:06x}"
    family = "serif" if part.serif else "sans-serif"
    align = "justify" if block.kind == "paragraph" and part.lines >= 3 else "left"
    return (f"* {{ font-family: {family}; font-size: {part.size:.1f}px; line-height: 1.18; color: {rgb}; "
            f"font-weight: {'bold' if part.bold else 'normal'}; font-style: {'italic' if part.italic else 'normal'}; "
            f"text-align: {align}; margin: 0; padding: 0; }}")


GAP = 2.0  # points kept free around other content


def _obstacles(page) -> list[pymupdf.Rect]:
    """Every text line and image on the page, read before anything is removed."""
    found = []
    for b in page.get_text("dict")["blocks"]:
        if b["type"] == 1:
            found.append(pymupdf.Rect(b["bbox"]))
        else:
            found += [pymupdf.Rect(line["bbox"]) for line in b["lines"]
                      if any(s["text"].strip() for s in line["spans"])]
    return found


def room_for(rect: pymupdf.Rect, obstacles: list[pymupdf.Rect], page_rect: pymupdf.Rect) -> pymupdf.Rect:
    """The largest box that starts at ``rect`` and grows right to its column edge, then down into empty
    space, without touching any other block."""
    others = [o for o in obstacles if (o & rect).get_area() < 0.5 * max(o.get_area(), 1)]
    margin = min(rect.x0, 36)
    # Right: the column edge is the widest block that starts where this one starts.
    column = [o.x1 for o in obstacles if abs(o.x0 - rect.x0) < 30]
    right = max([rect.x1, *column])
    right = min(right, page_rect.x1 - margin)
    for o in others:  # never run into something beside us
        if o.y1 > rect.y0 and o.y0 < rect.y1 and o.x0 >= rect.x1 - 1:
            right = min(right, o.x0 - GAP)
    right = max(right, rect.x1)
    # Down: until the next block that shares any horizontal space, or the bottom margin.
    bottom = page_rect.y1 - 36
    for o in others:
        if o.y0 >= rect.y1 - 1 and o.x1 > rect.x0 and o.x0 < right:
            bottom = min(bottom, o.y0 - GAP)
    bottom = max(bottom, rect.y1)
    return pymupdf.Rect(rect.x0, rect.y0, right, bottom)


def _write_box(page, part: Part, text: str, block: Block, room: pymupdf.Rect):
    rect = pymupdf.Rect(part.rect) + (0, 0, 1, 2)  # a little air below: line heights differ between fonts
    body = html.escape(text)
    spare, _ = page.insert_htmlbox(rect, body, css=_css(part, block), scale_low=1)
    if spare >= 0:
        return
    # Too long for the original box: use free space around it before making the font smaller.
    rect = room | rect
    spare, _ = page.insert_htmlbox(rect, body, css=_css(part, block), scale_low=MIN_SCALE)
    if spare < 0:  # still too long: allow any shrink rather than dropping text
        page.insert_htmlbox(rect, body, css=_css(part, block), scale_low=0)


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
                untouched[p.page].append(pymupdf.Rect(p.rect))

    def overlaps_untouched(b):
        # Boxes of neighbouring lines touch by a point or two; only a real overlap counts.
        shrink = (0, 2, 0, -2)
        return any(((pymupdf.Rect(p.rect) + shrink) & (u + shrink)).get_area() > 1
                   for p in b.parts for u in untouched[p.page])

    per_page: dict[int, list] = defaultdict(list)
    for b in book.blocks:
        if not translated(b) or overlaps_untouched(b):
            continue
        out = translations[b.id]
        for i, (part, piece) in enumerate(zip(b.parts, split_for_parts(out, b.parts))):
            if b.kind == "item" and i == 0:
                piece = f"{b.marker} {piece}"
            per_page[part.page].append((part, piece, b))

    for pno, items in per_page.items():
        page = doc[pno - 1]
        obstacles = _obstacles(page)
        rooms = [room_for(pymupdf.Rect(part.rect), obstacles, page.rect) for part, _, _ in items]
        for part, _, _ in items:
            r = pymupdf.Rect(part.rect) + (0, INSET, 0, -INSET)
            page.add_redact_annot(r, fill=False)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
        for (part, text, block), room in zip(items, rooms):
            _write_box(page, part, text, block, room)

    doc.set_metadata({**doc.metadata, "producer": "Ratica"})
    doc.save(path, garbage=3, deflate=True)
    doc.close()
    return path
