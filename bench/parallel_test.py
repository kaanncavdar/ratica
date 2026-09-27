"""Measure throughput when several paragraphs are translated at once (llama-server slots).

    uv run python bench/parallel_test.py MODEL_KEY --mode gpu|cpu --slots 1 2 4 8
"""
import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor

import run_bench as rb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model", choices=rb.MODEL_FILES)
    ap.add_argument("--mode", choices=["gpu", "cpu"], default="gpu")
    ap.add_argument("--slots", type=int, nargs="+", default=[1, 2, 4, 8])
    ap.add_argument("--extra", default="", help="extra llama-server args, e.g. '--spec-type draft-mtp'")
    ap.add_argument("--tag", default="", help="suffix for output file names")
    a = ap.parse_args()
    global EXTRA, TAG
    EXTRA, TAG = a.extra.split(), a.tag

    items = json.loads((rb.BENCH / "data" / "testset.json").read_text(encoding="utf-8"))
    page = next(i for i in items if i["kind"] == "page")
    paras = page["src"].split("\n\n")  # translate the page paragraph by paragraph, like the app will
    out = []
    for n in a.slots:
        rb.CTX = 4096 * n  # each slot keeps a 4096-token window
        proc, _ = start(a.model, a.mode, n)
        try:
            # Warm-up: a long prompt plus one full concurrent round, so one-time GPU pipeline
            # compilation for every batch size is not counted in the measurement.
            rb.translate(a.model, "tr", "plain", page["src"], max_tokens=8)
            with ThreadPoolExecutor(n) as ex:
                list(ex.map(lambda p: rb.translate(a.model, "tr", "plain", p, max_tokens=64), paras[:n]))
            mon = rb.Monitor(proc.pid)
            mon.start()
            t0 = time.perf_counter()
            with ThreadPoolExecutor(n) as ex:
                list(ex.map(lambda p: rb.translate(a.model, "tr", "plain", p), paras * 2))
            wall = time.perf_counter() - t0
            mon.stop.set()
            mon.join()
        finally:
            proc.terminate()
            proc.wait()
        page_s = wall / 2 * 450 / page["words"]  # scaled to a 450-word page, as in score.py
        row = {"model": a.model, "mode": a.mode, "extra": a.extra, "slots": n, "page_s": round(page_s, 1),
               "hours_200_pages": round(page_s * 200 / 3600, 2), "vram_peak_mib": mon.peak_vram,
               "cpu_avg_pct": round(sum(mon.cpu_samples) / max(1, len(mon.cpu_samples)), 1)}
        print(json.dumps(row), flush=True)
        out.append(row)
    path = rb.RESULTS / f"parallel-{a.model}-{a.mode}{a.tag}.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")


def start(model, mode, slots):
    # Reuse run_bench's server launcher, but with N slots.
    import subprocess
    import requests
    args = [str(rb.SERVER), "-m", str(rb.MODELS / rb.MODEL_FILES[model]), "--port", str(rb.PORT),
            "-c", str(rb.CTX), "-np", str(slots), "-fa", "on"] + EXTRA
    args += ["--no-jinja"] if rb.is_translategemma(model) else ["--jinja", "-rea", "off"]
    if mode == "gpu":
        args += ["-fit", "on", "-fitt", str(rb.FIT_MARGIN_MIB)]
    else:
        import psutil
        args += ["-ngl", "0", "--device", "none", "-t", str(psutil.cpu_count(logical=False))]
    log = open(rb.RESULTS / f"parallel-{model}-{mode}-{slots}{TAG}.server.log", "w",
               encoding="utf-8")
    proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(300):
        if proc.poll() is not None:
            raise RuntimeError("server exited")
        try:
            if requests.get(f"{rb.URL}/health", timeout=2).json().get("status") == "ok":
                return proc, args
        except requests.RequestException:
            pass
        time.sleep(1)
    raise RuntimeError("server did not become ready")


if __name__ == "__main__":
    main()
