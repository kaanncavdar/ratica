"""Render Ratica's icon (packaging/icon.svg: an original page and its translation in the same layout)
to the PNG, ICO and ICNS files the app and installers use.

    uv run --group build python packaging/make_icon.py
"""
from pathlib import Path

import pymupdf
from PIL import Image

HERE = Path(__file__).parent
ASSETS = HERE.parent / "src" / "ratica" / "assets"


def draw(size: int = 1024) -> bytes:
    page = pymupdf.open(HERE / "icon.svg")[0]
    return page.get_pixmap(alpha=True, matrix=pymupdf.Matrix(size / page.rect.width, size / page.rect.width)).tobytes("png")


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    big = HERE / "icon-1024.png"
    big.write_bytes(draw(1024))
    img = Image.open(big)
    img.resize((512, 512), Image.LANCZOS).save(ASSETS / "icon.png")
    img.save(HERE / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.save(HERE / "icon.icns")
    big.unlink()
    print(f"wrote {ASSETS / 'icon.png'}, {HERE / 'icon.ico'}, {HERE / 'icon.icns'}")


if __name__ == "__main__":
    main()
