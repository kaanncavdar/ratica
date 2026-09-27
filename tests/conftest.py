import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pymupdf
import pytest

BODY = ("Hash tables store key and value pairs. A hash function maps each key to a bucket, "
        "so lookups take constant time on average.")


def write_pages(path, pages):
    """pages: list of lists of (text, fontname, fontsize, y) tuples, written at x=72."""
    doc = pymupdf.open()
    for items in pages:
        page = doc.new_page(width=595, height=842)
        for text, font, size, y in items:
            if font == "notos":  # base-14 fonts cannot write "•" and other non-Latin-1 characters
                page.insert_font(fontname=font, fontbuffer=pymupdf.Font(font).buffer)
            rect = pymupdf.Rect(72, y, 523, y + 400)
            page.insert_textbox(rect, text, fontname=font, fontsize=size)
    doc.save(path)
    return path


def png_bytes(width=120, height=80):
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height), False)
    pix.set_rect(pix.irect, (40, 120, 200))
    return pix.tobytes("png")


@pytest.fixture
def book_pdf(tmp_path):
    """A 3-page book with a running header, page numbers, a heading, body text and a code line."""
    pages = []
    for n in range(1, 4):
        items = [("A Small Book", "helv", 9, 30), (str(n), "helv", 9, 800)]
        if n == 1:
            items += [("Chapter 1: Hash Tables", "hebo", 20, 90),
                      (BODY, "helv", 11, 140),
                      ("table = {}  # empty dict", "cour", 10, 200)]
        else:
            items += [(f"Page {n} explains collisions and how buckets grow when the table fills up.",
                       "helv", 11, 90)]
        pages.append(items)
    return write_pages(tmp_path / "book.pdf", pages)


@pytest.fixture
def fake_llama():
    """A tiny HTTP server that answers like llama-server's chat endpoint and records requests."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, body))
            reply = {"choices": [{"message": {"content": "  Merhaba dünya.\n"}}]}
            data = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", seen
    srv.shutdown()
