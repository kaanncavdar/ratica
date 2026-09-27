"""Run one model on the test set through llama-server and record outputs, speed and memory.

Usage:
    uv run python bench/run_bench.py MODEL_KEY --mode gpu|cpu [--quick]

GPU mode lets llama.cpp's --fit choose how many layers go to the GPU while leaving
FIT_MARGIN_MIB of VRAM free, so the rest of the PC stays usable during translation.
CPU mode runs with no GPU device at all (-ngl 0, --device none).
"""
import argparse
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

import psutil
import requests

ROOT = Path(os.environ.get("RATICA_BENCH_DIR", "bench-work"))  # engine builds, models and test data
# LLAMA_BUILD=llama-cuda switches to the CUDA build (default: the Vulkan build in "llama").
SERVER = ROOT / os.environ.get("LLAMA_BUILD", "llama") / "llama-server.exe"
MODELS = ROOT / "models"
BENCH = Path(__file__).parent
RESULTS = BENCH / "results"
PORT = 8091
URL = f"http://127.0.0.1:{PORT}"
CTX = 4096
FIT_MARGIN_MIB = 1024

MODEL_FILES = {
    "qwen3.5-4b": "Qwen_Qwen3.5-4B-Q4_K_M.gguf",
    "qwen3.5-9b": "Qwen_Qwen3.5-9B-Q4_K_M.gguf",
    "qwen3.5-2b": "Qwen_Qwen3.5-2B-Q4_K_M.gguf",
    "gemma-4-e4b": "gemma-4-E4B-it-Q4_K_M.gguf",
    "gemma-4-e2b": "gemma-4-E2B-it-Q4_K_M.gguf",
    "translategemma-4b": "translategemma-4b-it.Q4_K_M.gguf",
}
LANG_NAMES = {"tr": "Turkish", "zh": "Simplified Chinese", "ru": "Russian", "az": "Azerbaijani", "hi": "Hindi"}
TG_CODES = {"tr": "tr", "zh": "zh-Hans", "ru": "ru", "az": "az", "hi": "hi"}


def is_translategemma(key):
    return key.startswith("translategemma")


# ---------- protection variants ----------

def make_variants(item):
    """Return [(variant, text_sent_to_model, placeholder_map)]."""
    if item["kind"] != "synthetic":
        return [("plain", item["src"], None)]
    marked = item["src_marked"]
    keep = re.sub(r"\[\[(.+?)\]\]", r"<keep>\1</keep>", marked)
    mapping, counter = {}, iter(range(1, 100))

    def ph(m):
        tok = f"⟦{next(counter)}⟧"
        mapping[tok] = m.group(1)
        return tok

    placeholder = re.sub(r"\[\[(.+?)\]\]", ph, marked)
    return [("keep", keep, None), ("placeholder", placeholder, mapping)]


def system_prompt(lang, variant):
    p = (f"You are a professional translator. Translate the user's text from English to {LANG_NAMES[lang]}. "
         "Output only the translation, with no introduction, notes or quotation marks.")
    if variant == "keep":
        p += " Copy any text inside <keep>...</keep> exactly as it is, including the tags. Do not translate it."
    if variant == "placeholder":
        p += " Tokens like ⟦1⟧ are placeholders: copy them unchanged and keep each one exactly once."
    return p


def translategemma_prompt(lang, text):
    # Mirrors the official TranslateGemma chat template (text branch); the GGUF's Jinja
    # template needs structured content that llama-server's chat endpoint can't pass.
    tgt, code = {"zh": "Chinese"}.get(lang, LANG_NAMES[lang]), TG_CODES[lang]
    return ("<start_of_turn>user\nYou are a professional English (en) to " + tgt + " (" + code + ") translator. "
            "Your goal is to accurately convey the meaning and nuances of the original English text while adhering to "
            + tgt + " grammar, vocabulary, and cultural sensitivities.\nProduce only the " + tgt + " translation, "
            "without any additional explanations or commentary. Please translate the following English text into "
            + tgt + ":\n\n\n" + text.strip() + "<end_of_turn>\n<start_of_turn>model\n")


def translate(key, lang, variant, text, max_tokens=2048):
    t0 = time.perf_counter()
    if is_translategemma(key):
        r = requests.post(f"{URL}/completion", json={
            "prompt": translategemma_prompt(lang, text), "n_predict": max_tokens, "temperature": 0,
            "cache_prompt": False}, timeout=3600).json()
        out, timings = r["content"], r["timings"]
    else:
        r = requests.post(f"{URL}/v1/chat/completions", json={
            "messages": [{"role": "system", "content": system_prompt(lang, variant)},
                         {"role": "user", "content": text}],
            "max_tokens": max_tokens, "temperature": 0, "cache_prompt": False,
            "chat_template_kwargs": {"enable_thinking": False}}, timeout=3600).json()
        out, timings = r["choices"][0]["message"]["content"], r["timings"]
    return out.strip(), timings, time.perf_counter() - t0


# ---------- resource monitoring ----------

def gpu_mem():
    q = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                       capture_output=True, text=True).stdout.strip().split(",")
    return int(q[0]), int(q[1])


class Monitor(threading.Thread):
    def __init__(self, pid):
        super().__init__(daemon=True)
        self.proc = psutil.Process(pid)
        self.peak_vram = 0
        self.peak_rss = 0
        self.cpu_samples = []
        self.stop = threading.Event()

    def run(self):
        psutil.cpu_percent(None)
        while not self.stop.is_set():
            used, _ = gpu_mem()
            self.peak_vram = max(self.peak_vram, used)
            try:
                self.peak_rss = max(self.peak_rss, self.proc.memory_info().rss)
            except psutil.Error:
                pass
            self.cpu_samples.append(psutil.cpu_percent(None))
            time.sleep(0.5)


# ---------- main ----------

def start_server(key, mode, log_path):
    args = [str(SERVER), "-m", str(MODELS / MODEL_FILES[key]), "--port", str(PORT), "-c", str(CTX), "-np", "1",
            "-fa", "on"]
    args += ["--no-jinja"] if is_translategemma(key) else ["--jinja", "-rea", "off"]
    if mode == "gpu":
        args += ["-fit", "on", "-fitt", str(FIT_MARGIN_MIB)]
    else:
        args += ["-ngl", "0", "--device", "none", "-t", str(psutil.cpu_count(logical=False))]
    log = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(300):
        if proc.poll() is not None:
            raise RuntimeError(f"server exited, see {log_path}")
        try:
            if requests.get(f"{URL}/health", timeout=2).json().get("status") == "ok":
                return proc, args
        except requests.RequestException:
            pass
        time.sleep(1)
    raise RuntimeError("server did not become ready")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model", choices=MODEL_FILES)
    ap.add_argument("--mode", choices=["gpu", "cpu"], default="gpu")
    ap.add_argument("--quick", action="store_true", help="page timing + a few Turkish sentences only (CPU mode)")
    a = ap.parse_args()

    items = json.loads((BENCH / "data" / "testset.json").read_text(encoding="utf-8"))
    if a.quick:
        items = [i for i in items if i["kind"] == "page" or i["id"] in ("flores-0-tr", "flores-50-tr", "syn-3")]

    RESULTS.mkdir(exist_ok=True)
    tag = f"{a.model}-{a.mode}"
    log_path = RESULTS / f"{tag}.server.log"
    vram_idle, vram_total = gpu_mem()
    t_load = time.perf_counter()
    proc, args = start_server(a.model, a.mode, log_path)
    load_s = time.perf_counter() - t_load
    load_vram, _ = gpu_mem()
    mon = Monitor(proc.pid)
    mon.start()
    rows = []
    try:
        # Warm-up with a long prompt: the first large batch compiles GPU pipelines (~30 s once).
        page = next(i for i in items if i["kind"] == "page")
        t_warm = time.perf_counter()
        translate(a.model, "tr", "plain", page["src"], max_tokens=8)
        warmup_s = time.perf_counter() - t_warm
        for n, item in enumerate(items, 1):
            for variant, text, mapping in make_variants(item):
                repeats = 2 if item["kind"] == "page" else 1
                for rep in range(repeats):
                    out, timings, wall = translate(a.model, item["lang"], variant, text)
                    rows.append({"id": item["id"], "variant": variant, "rep": rep, "sent": text, "out": out,
                                 "placeholders": mapping, "wall_s": round(wall, 3), "timings": timings})
            print(f"[{tag}] {n}/{len(items)} {item['id']}", flush=True)
    finally:
        mon.stop.set()
        mon.join()
        proc.terminate()
        proc.wait()

    result = {
        "model": a.model, "file": MODEL_FILES[a.model], "mode": a.mode, "server_args": args[1:],
        "load_s": round(load_s, 1), "warmup_s": round(warmup_s, 1),
        "vram_total_mib": vram_total, "vram_idle_mib": vram_idle, "vram_after_load_mib": load_vram,
        "vram_peak_mib": mon.peak_vram, "vram_headroom_mib": vram_total - mon.peak_vram,
        "ram_peak_mib": round(mon.peak_rss / 2**20),
        "cpu_avg_pct": round(sum(mon.cpu_samples) / max(1, len(mon.cpu_samples)), 1),
        "rows": rows,
    }
    out_path = RESULTS / f"{tag}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"done -> {out_path} | load {result['load_s']}s | VRAM peak {mon.peak_vram}/{vram_total} MiB "
          f"| RAM peak {result['ram_peak_mib']} MiB | CPU avg {result['cpu_avg_pct']}%")


if __name__ == "__main__":
    main()
