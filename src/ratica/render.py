"""Write the translated book as a reflowed PDF and as an EPUB.

Both are built from the same HTML per block. The PDF embeds Noto Sans for text and
Cascadia Mono for code (both SIL Open Font License), so every Latin, Cyrillic and Greek
letter renders, and only the glyphs that are used end up in the file.
"""
import html
from pathlib import Path

import pymupdf
from ebooklib import epub

from .docmodel import Book

PAGE = pymupdf.Rect(0, 0, 504, 684)  # 7 x 9.5 inches, a common technical-book trim
MARGIN = 54
FONTS = {"body.ttf": "notos", "body-bold.ttf": "notosbo", "body-italic.ttf": "notosit", "mono.ttf": "cascadia"}

CSS = """
@font-face { font-family: body; src: url(body.ttf); }
@font-face { font-family: body; font-weight: bold; src: url(body-bold.ttf); }
@font-face { font-family: body; font-style: italic; src: url(body-italic.ttf); }
@font-face { font-family: mono; src: url(mono.ttf); }
body { font-family: body; font-size: 10.5pt; line-height: 1.45; }
h1 { font-size: 18pt; margin: 0 0 12pt 0; }
h2 { font-size: 14pt; margin: 14pt 0 8pt 0; }
h3, h4, h5, h6 { font-size: 11.5pt; margin: 12pt 0 6pt 0; }
p { margin: 0 0 7pt 0; }
p.item { margin: 0 0 4pt 16pt; text-indent: -12pt; }
pre { font-family: mono; font-size: 8.5pt; line-height: 1.3; background-color: #f3f4f6; padding: 6pt; margin: 0 0 8pt 0;
      white-space: pre-wrap; }
"""


CONTENT_WIDTH = PAGE.width - 2 * MARGIN


def _image_name(block) -> str:
    return f"{block.id}.{block.image_ext or 'png'}"


def _block_html(block, text: str, image_dir: str = "") -> str:
    if block.kind == "image":
        width = min(block.width or CONTENT_WIDTH, CONTENT_WIDTH)
        return f'<p><img src="{image_dir}{_image_name(block)}" width="{width:.0f}" alt=""/></p>'
    t = html.escape(text)
    if block.kind == "heading":
        n = min(max(block.level, 1), 6)
        return f"<h{n}>{t}</h{n}>"
    if block.kind == "code":
        return f"<pre>{t}</pre>"
    if block.kind == "item":
        return f'<p class="item">{html.escape(block.marker)} {t}</p>'
    return f"<p>{t}</p>"


def _text(block, translations) -> str:
    return translations.get(block.id, block.text)


def write_pdf(book: Book, translations: dict[str, str], path, lang: str) -> Path:
    path = Path(path)
    archive = pymupdf.Archive()
    for fname, font in FONTS.items():
        archive.add(pymupdf.Font(font).buffer, fname)
    for b in book.blocks:
        if b.kind == "image":
            archive.add(b.image, _image_name(b))
    body = "".join(_block_html(b, _text(b, translations)) for b in book.blocks)
    story = pymupdf.Story(html=f"<html lang='{lang}'><body>{body}</body></html>", user_css=CSS, archive=archive)

    headings = []

    def record(pos):
        if pos.heading and pos.open_close & 1 and pos.text:
            headings.append((pos.heading, " ".join(pos.text.split()), pos.page_num))

    writer = pymupdf.DocumentWriter(str(path))
    where = PAGE + (MARGIN, MARGIN, -MARGIN, -MARGIN)
    more, page_num = 1, 0
    while more:
        page_num += 1
        device = writer.begin_page(PAGE)
        more, _ = story.place(where)
        story.element_positions(record, {"page_num": page_num})
        story.draw(device)
        writer.end_page()
    writer.close()

    # Bookmarks: levels must start at 1 and never skip a level.
    toc, prev = [], 0
    for level, text, page in headings:
        level = min(level, prev + 1)
        toc.append([level, text, page])
        prev = level
    doc = pymupdf.open(path)
    doc.set_toc(toc)
    doc.set_metadata({"title": book.title, "producer": "Ratica"})
    doc.saveIncr()
    doc.close()
    return path


def write_epub(book: Book, translations: dict[str, str], path, lang: str) -> Path:
    path = Path(path)
    ebook = epub.EpubBook()
    ebook.set_identifier(f"ratica-{Path(book.source).stem}-{lang}")
    ebook.set_title(book.title)
    ebook.set_language(lang)

    # One chapter per top-level heading; anything before the first heading opens the book.
    chapters, current = [], None
    for b in book.blocks:
        if current is None or (b.kind == "heading" and b.level == 1 and current["blocks"]):
            current = {"title": None, "blocks": []}
            chapters.append(current)
        if b.kind == "heading" and b.level == 1 and current["title"] is None:
            current["title"] = _text(b, translations)
        current["blocks"].append(b)

    style = epub.EpubItem(uid="style", file_name="style/book.css", media_type="text/css",
                          content="pre { white-space: pre-wrap; font-family: monospace; }")
    ebook.add_item(style)
    for b in book.blocks:
        if b.kind == "image":
            ext = b.image_ext or "png"
            ebook.add_item(epub.EpubImage(uid=f"img-{b.id}", file_name=f"images/{_image_name(b)}",
                                          media_type=f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext}",
                                          content=b.image))
    items = []
    for n, ch in enumerate(chapters, start=1):
        item = epub.EpubHtml(title=ch["title"] or book.title, file_name=f"chap_{n:03d}.xhtml", lang=lang)
        item.content = "".join(_block_html(b, _text(b, translations), image_dir="images/") for b in ch["blocks"])
        item.add_item(style)
        ebook.add_item(item)
        items.append(item)

    ebook.toc = items
    ebook.add_item(epub.EpubNcx())
    ebook.add_item(epub.EpubNav())
    ebook.spine = ["nav", *items]
    epub.write_epub(str(path), ebook)
    return path
