"""Format-independent book structure shared by extraction, translation and rendering."""
import hashlib
from dataclasses import dataclass, field

TRANSLATABLE = {"heading", "paragraph", "item"}


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


@dataclass
class Block:
    id: str
    kind: str  # "heading" | "paragraph" | "item" | "code" | "image"
    text: str
    page: int  # 1-based page number in the source PDF
    level: int = 0  # heading level, 1 = largest
    keep: list[str] = field(default_factory=list)  # inline code found in the text, never translated
    image: bytes | None = None  # encoded image for kind == "image"
    image_ext: str = ""  # "png", "jpeg", …
    width: float = 0  # image width on the source page, in points
    marker: str = ""  # list marker for kind == "item": "•", "a.", "3." …

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
