"""Build the benchmark test set (bench/data/testset.json).

Sources (all openly licensed, no copyrighted books):
- FLORES-200 devtest (CC BY-SA 4.0), with reference translations.
- English Wikipedia technical articles (CC BY-SA 4.0), revision ids recorded for attribution.
- Synthetic sentences written for this project (code, URLs, formulas, names, table cells).

Spans that must survive untranslated are marked [[like this]] in synthetic items.
"""
import json
import os
import re
from pathlib import Path

import requests

# Unpacked from https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz
FLORES_DIR = Path(os.environ.get("RATICA_BENCH_DIR", "bench-work")) / "data" / "flores200_dataset" / "devtest"
OUT = Path(__file__).parent / "data" / "testset.json"

# English -> target; FLORES file codes.
LANGS = {"tr": "tur_Latn", "zh": "zho_Hans", "ru": "rus_Cyrl", "az": "azj_Latn", "hi": "hin_Deva"}

FLORES_IDX = list(range(0, 1012, 50))[:20]  # 20 evenly spaced sentences
FLORES_RATED = FLORES_IDX[:12]  # subset shown to the human rater (Turkish)
FLORES_AUTO_OTHER = FLORES_IDX[:15]  # other languages, automatic scoring only

WIKI_PARAGRAPHS = ["Hash table", "Transmission Control Protocol", "Garbage collection (computer science)"]
WIKI_PAGE = "Compiler"  # ~450 words used as "one book page" for timing
PAGE_WORDS = 450

SYNTHETIC = [
    "Run [[pip install requests]] before importing the library.",
    "The function [[parse_config()]] returns [[None]] if the file is missing.",
    "See [[https://docs.python.org/3/library/json.html]] for the full list of options.",
    "Python's [[list.sort()]] method sorts the list in place and is stable.",
    "Set the environment variable [[PYTHONPATH]] to include the [[src/]] directory.",
    "The time complexity of binary search is [[O(log n)]], compared to [[O(n)]] for linear search.",
    "Einstein's equation [[E = mc^2]] relates mass and energy.",
    "Linus Torvalds released the first version of Linux in 1991.",
    "In the table, the column labeled Latency (ms) shows the median over 1,000 requests.",
    "Throughput | Requests per second | Higher is better",
    "Press [[Ctrl+C]] to stop the server, then run [[git status]] to check your changes.",
    "The class [[HttpClient]] wraps a connection pool and retries failed requests three times.",
    "Kubernetes schedules pods onto nodes based on the resources they request.",
    "If [[x > 0]], the loop exits; otherwise [[count]] is incremented by one.",
    "Donald Knuth's The Art of Computer Programming is often cited as a classic reference.",
]
SYNTHETIC_RATED = [0, 1, 3, 5, 7, 8, 10, 13]


def flores_line(code, idx):
    return (FLORES_DIR / f"{code}.devtest").read_text(encoding="utf-8").splitlines()[idx]


def wiki_extract(title):
    r = requests.get(
        "https://en.wikipedia.org/w/api.php",
        params={"action": "query", "prop": "extracts|revisions", "rvprop": "ids", "explaintext": 1,
                "titles": title, "format": "json", "formatversion": 2},
        headers={"User-Agent": "ratica-bench/0.1 (open-source research)"},
        timeout=30,
    )
    page = r.json()["query"]["pages"][0]
    rev = page["revisions"][0]["revid"]
    url = f"https://en.wikipedia.org/w/index.php?title={title.replace(' ', '_')}&oldid={rev}"
    paras = [p.strip() for p in page["extract"].split("\n") if len(p.strip().split()) > 40 and not p.startswith("=")]
    return paras, url


def main():
    items = []
    for i in FLORES_IDX:
        src = flores_line("eng_Latn", i)
        for lang, code in LANGS.items():
            if lang != "tr" and i not in FLORES_AUTO_OTHER:
                continue
            items.append({
                "id": f"flores-{i}-{lang}", "kind": "flores", "lang": lang, "src": src,
                "ref": flores_line(code, i), "rated": lang == "tr" and i in FLORES_RATED,
                "source": "FLORES-200 devtest (CC BY-SA 4.0)",
            })

    for title in WIKI_PARAGRAPHS:
        paras, url = wiki_extract(title)
        items.append({"id": f"wiki-{title}", "kind": "wiki", "lang": "tr", "src": paras[0],
                      "rated": True, "source": f"Wikipedia (CC BY-SA 4.0): {url}"})

    paras, url = wiki_extract(WIKI_PAGE)
    words, page = 0, []
    for p in paras:
        page.append(p)
        words += len(p.split())
        if words >= PAGE_WORDS:
            break
    items.append({"id": "page", "kind": "page", "lang": "tr", "src": "\n\n".join(page), "words": words,
                  "rated": False, "source": f"Wikipedia (CC BY-SA 4.0): {url}"})

    for n, s in enumerate(SYNTHETIC):
        items.append({"id": f"syn-{n}", "kind": "synthetic", "lang": "tr", "src_marked": s,
                      "keep": re.findall(r"\[\[(.+?)\]\]", s), "rated": n in SYNTHETIC_RATED,
                      "source": "Synthetic, written for this project"})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(items)} items, {sum(i['rated'] for i in items)} rated, page = {words} words -> {OUT}")


if __name__ == "__main__":
    main()
