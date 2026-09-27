"""Guess the language a book is written in, so the window can preselect it.

The writing system decides most languages on its own (Cyrillic, Greek, Chinese, Japanese, Korean,
Devanagari). Languages written in Latin letters are told apart by their most common short words and a few
letters only they use. The result is a suggestion; the user can always change it.
"""
import re
from collections import Counter

COMMON_WORDS = {
    "en": "the and of to in is that it for with as are this be on by from which",
    "tr": "ve bir bu da de ile için olarak gibi daha çok olan her ne ki veya",
    "az": "və bir bu da ilə üçün olan kimi daha çox isə",
    "de": "der die das und ist nicht mit den zu ein eine sie auf dem des im wird",
    "fr": "le la les et des est une que dans pour pas sur qui du au ce",
    "es": "el la los las y de que en un una es por con para del se",
    "it": "il la di che e un una per non con del della sono le gli nel nelle",
    "pt": "o a os as e de que um uma para com não do da em no na é nas",
    "nl": "de het een en van is dat op te in niet zijn met voor die",
    "pl": "i w na nie się że to z do jest jak od za co",
    "ro": "și în de la cu nu este pe un o care din pentru mai",
    "cs": "a v se na je že to s z do jako pro ale není",
    "sv": "och att det som en är på för med av den inte till",
    "id": "yang dan di ini itu dengan untuk dari tidak ke pada adalah",
    "vi": "của và là có không những được trong một các người cho",
}
WORDS = {code: set(words.split()) for code, words in COMMON_WORDS.items()}
LETTERS = {"tr": "ğı", "az": "ə", "de": "ßä", "pl": "łąęśżź", "cs": "řěů", "ro": "șțăâ", "sv": "å", "es": "ñ",
           "pt": "ãõ", "fr": "èêœ", "vi": "ơưạảấầẩậắằẳặẹẻẽếềểệỉịọỏốồổộớờởợụủứừửựỳỷỹđ"}
MIN_LETTERS = 10

SCRIPTS = [
    ("hangul", re.compile(r"[가-힯ᄀ-ᇿ]")),
    ("kana", re.compile(r"[぀-ヿ]")),
    ("han", re.compile(r"[一-鿿]")),
    ("cyrillic", re.compile(r"[Ѐ-ӿ]")),
    ("greek", re.compile(r"[Ͱ-Ͽ]")),
    ("devanagari", re.compile(r"[ऀ-ॿ]")),
    ("latin", re.compile(r"[A-Za-zÀ-ɏḀ-ỿ]")),
]


def _cyrillic(text: str) -> str:
    if re.search(r"[іїєґІЇЄҐ]", text):
        return "uk"
    # Bulgarian has no "ы" or "э"; almost any Russian text of some length has them.
    russian_only = text.count("ы") + text.count("э")
    return "bg" if russian_only == 0 or text.count("ъ") > 2 * russian_only else "ru"


def _latin(text: str) -> str | None:
    words = re.findall(r"[^\W\d_]+", text.lower())
    counts = Counter(words)
    scores = {code: sum(counts[w] for w in common) for code, common in WORDS.items()}
    for code, letters in LETTERS.items():
        scores[code] += 0.5 * sum(text.lower().count(ch) for ch in letters)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else None


def detect_language(text: str) -> str | None:
    """The code of the language ``text`` is written in (see engine.LANGUAGES), or None if unclear."""
    found = Counter({name: len(pattern.findall(text)) for name, pattern in SCRIPTS})
    if sum(found.values()) < MIN_LETTERS:
        return None
    if found["hangul"] > 0.2 * sum(found.values()):
        return "ko"
    if found["kana"] > 0.05 * sum(found.values()):
        return "ja"
    script = max(found, key=found.get)
    return {"han": "zh", "greek": "el", "devanagari": "hi", "hangul": "ko", "kana": "ja"}.get(script) or (
        _cyrillic(text) if script == "cyrillic" else _latin(text))
