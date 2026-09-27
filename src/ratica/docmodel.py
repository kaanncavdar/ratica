"""Format-independent book structure shared by extraction, translation and rendering."""
import hashlib
from dataclasses import dataclass, field

TRANSLATABLE = {"heading", "paragraph", "item"}


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


@dataclass
class Part:
    """Where (a piece of) a block sits in the source PDF, and how its text looks."""
    page: int  # 1-based
    rect: tuple[float, float, float, float]
    size: float = 10.0
    serif: bool = False
    bold: bool = False
    italic: bool = False
    color: int = 0  # sRGB as 0xRRGGBB
    chars: int = 0  # length of the source text in this part, to split the translation back
    lines: int = 1


@dataclass
class Block:
    id: str
    kind: str  # "heading" | "paragraph" | "item" | "code" | "formula" | "image"
    text: str
    page: int  # 1-based page number in the source PDF
    level: int = 0  # heading level, 1 = largest
    keep: list[str] = field(default_factory=list)  # inline code found in the text, never translated
    image: bytes | None = None  # encoded image for kind == "image"
    image_ext: str = ""  # "png", "jpeg", …
    width: float = 0  # image width on the source page, in points
    marker: str = ""  # list marker for kind == "item": "•", "a.", "3." …
    parts: list[Part] = field(default_factory=list)  # one per source box; several if merged across pages

    @property
    def translatable(self) -> bool:
        return self.kind in TRANSLATABLE

    @property
    def hash(self) -> str:
        return text_hash(self.text)


@dataclass
class Book:
    source: str
    title: str
    blocks: list[Block] = field(default_factory=list)
