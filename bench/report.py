"""Write bench/RESULTS.md (English) from summary.json, ratings.json and parallel-*.json.

    uv run python bench/score.py && uv run python bench/report.py
"""
import collections
import json
from pathlib import Path

BENCH = Path(__file__).parent
RESULTS = BENCH / "results"
PAGES = 200

NAMES = {"gemma-4-e4b": "Gemma-4-E4B-it", "qwen3.5-4b": "Qwen3.5-4B", "qwen3.5-9b": "Qwen3.5-9B",
         "translategemma-4b": "TranslateGemma-4B"}
ORDER = ["gemma-4-e4b", "translategemma-4b", "qwen3.5-4b", "qwen3.5-9b"]


def load(name):
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def minutes(page_s):
    return round(page_s * PAGES / 60)


def main():
    summary = {(s["model"], s["mode"]): s for s in load("summary.json")}
    ratings = load("ratings.json")
    wins = collections.Counter()
    ties = 0
    for v in ratings.values():
        if v["winners"] == "tie":
            ties += 1
        else:
            wins.update(v["winners"])
    decided = len(ratings) - ties

    out = ["# Model benchmark results", "",
           "Which local model should the app use by default? Measured on a machine with a 6 GB GPU, the low "
           "end of what Ratica targets. All models are GGUF Q4_K_M, run with "
           "llama.cpp build b11211, temperature 0, 4096-token context per slot, and `--fit` keeping 1 GB of VRAM free "
           "so the computer stays usable while translating.", "",
           "**Result: Gemma-4-E4B-it is the default model.** It won the most blind Turkish comparisons, had the best "
           "automatic score in Turkish, Russian and Hindi, kept 100% of protected code/URLs intact, and fits "
           "comfortably in 6 GB.", "",
           "## Quality", "",
           f"| Model | Turkish: blind human preference (wins of {decided}) | chrF TR | chrF RU | chrF HI | chrF AZ "
           "| chrF ZH | Protected spans kept (`<keep>` tags) | Protected spans kept (`⟦n⟧` placeholders) |",
           "|---|---|---|---|---|---|---|---|---|"]
    for m in ORDER:
        s = summary[(m, "gpu")]
        c = s["chrf"]
        out.append(f"| {NAMES[m]} | {wins[m]} | {c['tr']} | {c['ru']} | {c['hi']} | {c['az']} | {c['zh']} "
                   f"| {s['protect_keep_pct']}% | {s['protect_placeholder_pct']}% |")
    out += ["", f"Ties (all outputs judged equal) are not counted: {ties} of {len(ratings)} rated sentences. No model added "
            "introductions or notes to its output.", "",
            "## Speed and load on the 6 GB baseline", "",
            f"Time for a {PAGES}-page book (450 words per page), the whole page sent as one request, one request "
            "at a time, Vulkan backend.", "",
            "| Model | VRAM used by the model | VRAM left free | Avg. CPU load | Generation speed | "
            f"{PAGES} pages |", "|---|---|---|---|---|---|"]
    for m in ORDER:
        s = summary[(m, "gpu")]
        out.append(f"| {NAMES[m]} | {s['vram_used_by_model_mib'] / 1024:.1f} GB | {s['vram_headroom_mib'] / 1024:.1f} GB "
                   f"| {s['cpu_avg_pct']:.0f}% | {s['gen_tok_s']} tok/s | {minutes(s['page_s'])} min |")
    out += ["", "Qwen3.5-9B does not fit in 6 GB with the 1 GB safety margin, so part of it runs on the CPU: "
            "it is ~6x slower and uses much more CPU, without better Turkish quality.", ""]

    # parallel slots and backend
    rows = {}
    for f, backend in (("parallel-gemma-4-e4b-gpu_base2.json", "Vulkan"),
                       ("parallel-gemma-4-e4b-gpu_cuda.json", "CUDA")):
        p = RESULTS / f
        if p.exists():
            for r in load(f):
                rows[(backend, r["slots"])] = r
    if rows:
        slots = sorted({k[1] for k in rows})
        out += ["## Making it faster: parallel paragraphs and the CUDA backend", "",
                f"Gemma-4-E4B-it translating a page split into paragraphs, with several paragraphs in flight at once. "
                f"Minutes for {PAGES} pages.", "",
                "| Backend | " + " | ".join(f"{n} at once" for n in slots) + " |",
                "|---|" + "---|" * len(slots)]
        for backend in ("Vulkan", "CUDA"):
            cells = [f"{minutes(rows[(backend, n)]['page_s'])} min" if (backend, n) in rows else "–" for n in slots]
            out.append(f"| {backend} | " + " | ".join(cells) + " |")
        out += ["", "Both backends are equally fast one paragraph at a time, but CUDA scales much better with "
                "parallel paragraphs on this NVIDIA card. The app therefore uses CUDA on NVIDIA GPUs and Vulkan "
                "elsewhere, and picks the number of parallel paragraphs from the measured hardware. "
                "Speculative decoding (MTP, draft length 2) made Qwen3.5-4B slower here: only ~55% of drafted "
                "tokens were accepted.", ""]

    cpu = [m for m in ORDER if (m, "cpu") in summary]
    if cpu:
        out += ["## Without a GPU", "", f"CPU only (6 cores), {PAGES} pages, one request at a time:", "",
                "| Model | " + " | ".join(NAMES[m] for m in cpu) + " |", "|---|" + "---|" * len(cpu),
                "| Time | " + " | ".join(f"{minutes(summary[(m, 'cpu')]['page_s']) / 60:.1f} h" for m in cpu) + " |",
                "", "CPU-only use is possible but not a supported target: the app shows an honest time estimate "
                "before starting.", ""]

    out += ["## How this was measured", "",
            "- **Human preference (Turkish):** 23 sentences — 12 from FLORES-200, 3 Wikipedia paragraphs and 8 "
            "synthetic technical sentences. One native Turkish speaker saw the English source "
            "and all outputs side by side, in shuffled order with model names hidden, and picked the best one. "
            "Identical outputs were shown once. This is a small, single-rater sample: treat small differences "
            "between models as noise.",
            "- **chrF** (sacrebleu) compares each output with one FLORES-200 reference translation: 20 sentences "
            "for Turkish, 15 for each other language. It rewards character overlap, so a correct translation with "
            "different wording scores lower. Scores are **not comparable across languages** (Chinese is always "
            "low) — compare models within one column only. Non-Turkish languages were not checked by a human.",
            "- **Protected spans:** 10 synthetic sentences with code, URLs, formulas and commands. A sentence "
            "passes only if every protected span appears unchanged in the output.",
            "- **Speed:** a 570-word Wikipedia passage, scaled to a 450-word page, after a warm-up run. Book times "
            "cover translation only; PDF reading and writing are not included. One machine, one run per setting.",
            "- **Memory:** peak GPU memory from `nvidia-smi` during the run, minus the idle desktop usage.", "",
            "Test data: [FLORES-200](https://github.com/facebookresearch/flores) devtest (CC BY-SA 4.0) and "
            "English Wikipedia (CC BY-SA 4.0, exact revisions in `bench/data/testset.json`). No copyrighted "
            "books were used. Everything is reproducible with the scripts in `bench/`.", ""]

    (BENCH / "RESULTS.md").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
