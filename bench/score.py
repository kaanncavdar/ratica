"""Compute automatic scores from bench/results/*.json -> bench/results/summary.json.

- chrF (sacrebleu) against FLORES-200 references, per language.
- Script check: share of letters in the expected writing system (catches wrong-script or garbled output).
- Protection: keep-tag and placeholder variants, share of sentences where every protected span survives.
- Extra text: outputs that add an introduction, notes or wrapping quotes.
- Speed and memory: time per book page and estimated hours for 100 / 1000 pages.
"""
import json
import re
import statistics
import unicodedata
from pathlib import Path

from sacrebleu.metrics import CHRF

BENCH = Path(__file__).parent
RESULTS = BENCH / "results"
PAGE_WORDS = 450  # a typical technical book page; the timing text is scaled to this

SCRIPTS = {"tr": "LATIN", "az": "LATIN", "ru": "CYRILLIC", "hi": "DEVANAGARI", "zh": "CJK"}
PREAMBLE = re.compile(r"^(here is|here's|translation|sure|işte|çeviri|tercüme|note)\b|\n\s*(note|not):", re.I)


def script_share(text, lang):
    want = SCRIPTS[lang]
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    ok = sum(1 for c in letters if want in unicodedata.name(c, ""))
    return ok / len(letters)


def keep_ok(out, spans):
    return all(s in out for s in spans)


def placeholder_ok(out, mapping):
    return all(out.count(tok) == 1 for tok in mapping)


def score_file(path, testset):
    r = json.loads(path.read_text(encoding="utf-8"))
    rows = r["rows"]
    by_id = {i["id"]: i for i in testset}
    s = {k: r[k] for k in ("model", "mode", "load_s", "vram_total_mib", "vram_idle_mib", "vram_peak_mib",
                           "vram_headroom_mib", "ram_peak_mib", "cpu_avg_pct")}
    s["vram_used_by_model_mib"] = r["vram_peak_mib"] - r["vram_idle_mib"]

    # chrF + script share per language
    s["chrf"], s["script"] = {}, {}
    for lang in SCRIPTS:
        pairs = [(x["out"], by_id[x["id"]]["ref"]) for x in rows
                 if by_id[x["id"]]["kind"] == "flores" and by_id[x["id"]]["lang"] == lang]
        if not pairs:
            continue
        hyp, ref = zip(*pairs)
        s["chrf"][lang] = round(CHRF().corpus_score(list(hyp), [list(ref)]).score, 1)
        s["script"][lang] = round(100 * statistics.mean(script_share(h, lang) for h in hyp), 1)

    # protection
    for variant, check in (("keep", lambda x: keep_ok(x["out"], by_id[x["id"]]["keep"])),
                           ("placeholder", lambda x: placeholder_ok(x["out"], x["placeholders"]))):
        vs = [x for x in rows if x["variant"] == variant and by_id[x["id"]]["keep"]]
        if vs:
            s[f"protect_{variant}_pct"] = round(100 * sum(map(check, vs)) / len(vs))

    # extra text (introductions / notes)
    s["extra_text_pct"] = round(100 * sum(bool(PREAMBLE.search(x["out"])) for x in rows) / len(rows), 1)

    # speed
    gen = [x["timings"]["predicted_per_second"] for x in rows if x["timings"].get("predicted_n", 0) > 10]
    s["gen_tok_s"] = round(statistics.median(gen), 1) if gen else None
    page_rows = [x for x in rows if x["id"] == "page"]
    words = by_id["page"]["words"]
    page_s = statistics.mean(x["wall_s"] for x in page_rows) * PAGE_WORDS / words
    s["page_s"] = round(page_s, 1)
    s["hours_100_pages"] = round(page_s * 100 / 3600, 1)
    s["hours_1000_pages"] = round(page_s * 1000 / 3600, 1)
    return s


def main():
    testset = json.loads((BENCH / "data" / "testset.json").read_text(encoding="utf-8"))
    summary = [score_file(p, testset) for p in sorted(RESULTS.glob("*.json"))
               if not p.name.startswith(("summary", "ratings", "parallel-"))]
    (RESULTS / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    for s in summary:
        print(json.dumps(s, ensure_ascii=False))


if __name__ == "__main__":
    main()
