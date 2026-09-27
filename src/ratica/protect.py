"""Mark spans that must survive translation unchanged with <keep>…</keep> tags.

Kept: URLs, function calls such as ``parse_config()``, snake_case identifiers and any
terms from the user's do-not-translate list. After translation, ``is_intact`` checks that
every kept span came back verbatim.
"""
import re

KEEP_OPEN, KEEP_CLOSE = "<keep>", "</keep>"

URL = re.compile(r"https?://[^\s<>\"']+")
CALL = re.compile(r"\b[A-Za-z_][\w.]*\(\)")
SNAKE = re.compile(r"\b[A-Za-z]\w*_\w+\b")


def _trim_url(url: str) -> str:
    """Drop sentence punctuation and unbalanced closing parentheses from a URL's end."""
    while url and url[-1] in ".,;:!?)":
        if url[-1] == ")" and url.count("(") >= url.count(")"):
            break
        url = url[:-1]
    return url


def _find_spans(text: str, keep_terms) -> list[tuple[int, int]]:
    found = []
    for m in URL.finditer(text):
        found.append((m.start(), m.start() + len(_trim_url(m.group()))))
    for pattern in (CALL, SNAKE):
        found += [(m.start(), m.end()) for m in pattern.finditer(text)]
    for term in keep_terms:
        # Terms never start or end inside a word ("x" must not match the x in "index").
        pattern = r"(?<!\w)" + re.escape(term) + r"(?!\w)"
        found += [(m.start(), m.end()) for m in re.finditer(pattern, text)]
    # Keep the earliest, then longest, span; drop anything overlapping it.
    found.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    spans, end = [], -1
    for start, stop in found:
        if start >= end:
            spans.append((start, stop))
            end = stop
    return spans


def protect(text: str, keep_terms=()) -> tuple[str, list[str]]:
    """Return the text with kept spans wrapped in <keep> tags, and the list of kept spans."""
    spans = _find_spans(text, keep_terms)
    out, last = [], 0
    for start, stop in spans:
        out += [text[last:start], KEEP_OPEN, text[start:stop], KEEP_CLOSE]
        last = stop
    out.append(text[last:])
    return "".join(out), [text[a:b] for a, b in spans]


def is_intact(translation: str, spans: list[str]) -> bool:
    return all(s in translation for s in spans)


def unprotect(text: str) -> str:
    return text.replace(KEEP_OPEN, "").replace(KEEP_CLOSE, "")
