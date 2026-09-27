"""Build the demo book used for Ratica's screenshots and video (all text written for this demo).

    uv run python docs/demo/make_demo.py
"""
from pathlib import Path

import pymupdf

OUT = Path(__file__).parent / "sample-book.pdf"
TEAL = (0.11, 0.42, 0.53)
GREY = (0.35, 0.35, 0.35)

CSS = """
* { margin: 0; padding: 0; }
h1 { font-family: sans-serif; font-size: 26px; font-weight: bold; color: #1c6a86; }
h2 { font-family: sans-serif; font-size: 14px; font-weight: bold; color: #222; }
p  { font-family: serif; font-size: 10.5px; line-height: 14px; text-align: justify; color: #111; }
li { font-family: serif; font-size: 10.5px; line-height: 14px; color: #111; }
"""

PAGE1 = [
    ((60, 60, 540, 100), "<h1>2&#8195;How Maps Are Made</h1>"),
    ((60, 112, 540, 230),
     "<p>Every map starts as a set of measurements. Surveyors walk the land with instruments that record "
     "angles and distances, satellites send down photographs taken from hundreds of kilometres above, and "
     "volunteers trace roads from those photographs on their home computers. None of these sources is "
     "complete on its own, so mapmakers combine them, check them against each other and decide what the "
     "reader really needs to see.</p>"
     "<p>&#8195;This chapter follows a map from the first measurement to the printed page. We look at how "
     "positions are measured, why a flat map can never show the round Earth without distortion, and how "
     "symbols, colours and labels turn raw data into something a person can read at a glance.</p>"),
    ((60, 244, 540, 270), "<h2>2.1&#8195;Measuring the ground</h2>"),
    ((60, 274, 540, 334),
     "<p>A position on Earth is written as a pair of numbers: latitude, the angle north or south of the "
     "equator, and longitude, the angle east or west of a chosen line. Modern receivers find both by timing "
     "signals from several satellites. The table of methods below shows how accurate each approach is.</p>"),
    ((78, 338, 540, 400),
     "<ul><li>Handheld receiver: a few metres, good for walking routes.</li>"
     "<li>Survey receiver with a base station: a few centimetres.</li>"
     "<li>Aerial photographs: about half a metre, fast for large areas.</li></ul>"),
]

CHART = [("Handheld", 300), ("Base station", 3), ("Aerial photo", 50), ("Tape and compass", 120)]


def draw_chart(page, top):
    page.insert_text((60, top), "Figure 2.1  Typical error of each method (centimetres)", fontname="hebo", fontsize=9,
                     color=GREY)
    x0, y0, bar_h, scale = 170, top + 14, 16, 1.1
    for i, (label, value) in enumerate(CHART):
        y = y0 + i * (bar_h + 8)
        page.insert_text((60, y + 12), label, fontname="helv", fontsize=9)
        page.draw_rect(pymupdf.Rect(x0, y, x0 + value * scale, y + bar_h), color=None, fill=TEAL)
        page.insert_text((x0 + value * scale + 6, y + 12), f"{value}", fontname="helv", fontsize=9, color=GREY)
    page.draw_line((x0, y0 - 4), (x0, y0 + len(CHART) * (bar_h + 8)), color=GREY, width=0.6)


def draw_note(page, rect):
    page.draw_rect(rect, color=None, fill=(0.91, 0.95, 0.97))
    page.draw_rect(pymupdf.Rect(rect.x0, rect.y0, rect.x0 + 4, rect.y1), color=None, fill=TEAL)
    page.insert_htmlbox(rect + (16, 10, -12, -8),
                        "<h2>Note</h2><p>A map is always a choice. Leaving out small paths makes a city map "
                        "easier to read, but a hiking map needs exactly those paths.</p>", css=CSS)


def main():
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((60, 36), "Maps and Measurements", fontname="helv", fontsize=8, color=GREY)
    page.insert_text((520, 36), "17", fontname="helv", fontsize=8, color=GREY)
    page.draw_line((60, 42), (535, 42), color=GREY, width=0.4)
    for rect, html in PAGE1:
        page.insert_htmlbox(pymupdf.Rect(*rect), html, css=CSS)
    draw_chart(page, 430)
    draw_note(page, pymupdf.Rect(60, 556, 535, 640))
    page.insert_htmlbox(pymupdf.Rect(60, 650, 540, 780),
                        "<h2>2.2&#8195;From a round Earth to a flat page</h2>"
                        "<p>Peel an orange and try to press the peel flat: it tears or stretches. A map "
                        "projection is a rule for doing the same with the Earth's surface, and every rule "
                        "has to give something up. Some keep the shapes of countries, some keep their areas, "
                        "and some keep the directions a sailor needs.</p>", css=CSS)
    doc.set_metadata({"title": "Maps and Measurements (Ratica demo)", "author": "Ratica demo"})
    doc.subset_fonts()
    doc.save(OUT, garbage=3, deflate=True)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
