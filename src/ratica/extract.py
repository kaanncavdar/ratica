"""Read a text-based PDF into a Book: headings, paragraphs and code, in reading order.

Running headers, footers and page numbers are dropped. Monospaced text becomes a code
block, which is never translated.
"""
import re
from collections import Counter
from pathlib import Path

import pymupdf

from .docmodel import Block, Book

MARGIN = 0.08  # top/bottom share of the page where running headers and footers live
HEADING_RATIO = 1.3  # font size relative to body text that makes a heading
MONO_FLAG = 8  # PyMuPDF span flag: monospaced font
MIN_IMAGE = 24  # points; smaller images are icons or decoration


def _is_mono(span) -> bool:
    name = span["font"].lower()
    return bool(span["flags"] & MONO_FLAG) or "cour" in name or "mono" in name


def _join_lines(lines: list[str]) -> str:
    text = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if text.endswith("-") and line[:1].islower():
            text = text[:-1] + line  # re-join a word hyphenated at the line end
        else:
            text = f"{text} {line}" if text else line
    return text


ITEM = re.compile(r"^\s*([•◦▪‣∙*–-]|[a-z]\.|\d{1,2}\s?\.)\s+")


def _split_items(lines: list[str]):
    """Split a block's lines into (marker, lines) segments at bullet or enumerator line starts."""
    segments = [["", []]]
    for line in lines:
        m = ITEM.match(line)
        if m:
            segments.append([m.group(1).replace(" ", ""), [line[m.end():]]])
        else:
            segments[-1][1].append(line)
    return [(marker, seg) for marker, seg in segments if any(l.strip() for l in seg)]


def _raw_blocks(doc):
    """Yield dicts with text, size, mono flag, page and vertical position for every text block."""
    for pno, page in enumerate(doc, start=1):
        height = page.rect.height
        for b in page.get_text("dict", sort=True)["blocks"]:
            if b["type"] == 1:
                x0, y0, x1, y1 = b["bbox"]
                if x1 - x0 >= MIN_IMAGE and y1 - y0 >= MIN_IMAGE:
                    yield {"image": b["image"], "ext": b["ext"], "width": x1 - x0, "page": pno,
                           "in_margin": False, "mono": False, "text": "", "size": 0, "keep": [], "marker": ""}
                continue
            if b["type"] != 0:
                continue
            spans = [s for line in b["lines"] for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            mono = all(_is_mono(s) for s in spans)
            lines = ["".join(s["text"] for s in line["spans"]) for line in b["lines"]]
            keep = [] if mono else [s["text"].strip() for s in spans if _is_mono(s) and s["text"].strip()]
            sizes = Counter()
            for s in spans:
                sizes[round(s["size"], 1)] += len(s["text"])
            y0, y1 = b["bbox"][1], b["bbox"][3]
            base = {"size": sizes.most_common(1)[0][0], "mono": mono, "page": pno,
                    "in_margin": y1 < height * MARGIN or y0 > height * (1 - MARGIN)}
            if mono:
                yield {**base, "text": "\n".join(l.rstrip() for l in lines if l.strip()), "keep": [], "marker": ""}
                continue
            for marker, seg in _split_items(lines):
                text = _join_lines(seg)
                yield {**base, "text": text, "marker": marker, "keep": [k for k in keep if k in text]}


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


def _merge(blocks: list[Block]) -> list[Block]:
    out = []
    for b in blocks:
        if out and _continues(out[-1], b):
            prev = out[-1]
            prev.text = prev.text[:-1] + b.text if prev.text.endswith("-") else f"{prev.text} {b.text}"
            prev.keep += b.keep
        else:
            out.append(b)
    return out


def extract(path) -> Book:
    path = Path(path)
    doc = pymupdf.open(path)
    raw = list(_raw_blocks(doc))
    furniture = _furniture_keys(raw, len(doc))
    raw = [r for r in raw if not _is_furniture(r, furniture)]

    body_sizes = Counter()
    for r in raw:
        if not r["mono"] and r["text"]:
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
        elif r["marker"]:
            kind, level = "item", 0
        elif r["size"] in heading_sizes and len(r["text"]) < 200:
            kind, level = "heading", heading_sizes.index(r["size"]) + 1
        else:
            kind, level = "paragraph", 0
        blocks.append(Block(id=f"b{n:05d}", kind=kind, text=r["text"], page=r["page"], level=level,
                            keep=r["keep"], marker=r["marker"]))
    blocks = _merge(blocks)

    title = doc.metadata.get("title") or next((b.text for b in blocks if b.kind == "heading"), path.stem)
    return Book(source=str(path), title=title, blocks=blocks)
