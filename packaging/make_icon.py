"""Draw Ratica's icon (a page with a folded corner and an "R") and save PNG + ICO.

    uv run --group build python packaging/make_icon.py
"""
from pathlib import Path

import pymupdf
from PIL import Image

HERE = Path(__file__).parent
ASSETS = HERE.parent / "src" / "ratica" / "assets"
TEAL = (0x1C / 255, 0x6A / 255, 0x86 / 255)
WHITE = (1, 1, 1)
FOLD = (0.78, 0.86, 0.9)
S = 512


def draw() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=S, height=S)
    sh = page.new_shape()
    sh.draw_rect(pymupdf.Rect(16, 16, S - 16, S - 16), radius=0.18)  # rounded tile
    sh.finish(fill=TEAL, color=None)
    # a white page with its top-right corner folded
    x0, y0, x1, y1, f = 132, 92, 380, 420, 70
    sh.draw_polyline([(x0, y0), (x1 - f, y0), (x1, y0 + f), (x1, y1), (x0, y1), (x0, y0)])
    sh.finish(fill=WHITE, color=None, closePath=True)
    sh.draw_polyline([(x1 - f, y0), (x1 - f, y0 + f), (x1, y0 + f)])
    sh.finish(fill=FOLD, color=None, closePath=True)
    sh.commit()
    page.insert_font(fontname="nb", fontbuffer=pymupdf.Font("notosbo").buffer)
    page.insert_text((178, 356), "R", fontname="nb", fontsize=230, color=TEAL)
    return page.get_pixmap(alpha=True, clip=page.rect).tobytes("png")


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    png = ASSETS / "icon.png"
    png.write_bytes(draw())
    img = Image.open(png)
    img.save(HERE / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.save(HERE / "icon.icns")
    print(f"wrote {png}, {HERE / 'icon.ico'}, {HERE / 'icon.icns'}")


if __name__ == "__main__":
    main()
