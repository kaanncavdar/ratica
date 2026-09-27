"""Command line.

    ratica setup                      download the engine and model, run the speed test
    ratica translate book.pdf --to tr translate (sets itself up on first use)
    ratica info                       hardware and settings, for bug reports

Work is saved as it goes, so running the same translate command again continues where it stopped.
"""
import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__, hardware, paths
from .extract import extract
from .service import Settings, estimate_seconds, load_settings, prepare, translate_pdf


def _err(msg):
    print(msg, file=sys.stderr)


def _progress_printer():
    start, first = time.monotonic(), None

    def show(done, total):
        nonlocal first
        if first is None:
            first = done  # blocks already done before this run (resume, code)
        elapsed = time.monotonic() - start
        rate = (done - first) / elapsed if elapsed > 0 else 0
        eta = f", about {int((total - done) / rate // 60) + 1} min left" if rate and done < total else ""
        print(f"\rTranslated {done}/{total} blocks{eta}   ", end="", file=sys.stderr, flush=True)

    return show


def _download_printer():
    def show(stage, done, total):
        if total > 1:
            print(f"\r{stage}: {done / 2**20:,.0f} / {total / 2**20:,.0f} MB   ", end="", file=sys.stderr, flush=True)
        elif stage == "speed test" and done == 0:
            print("\nMeasuring speed (about a minute)...", file=sys.stderr)
    return show


def _ready_settings() -> Settings:
    s = load_settings()
    if s and s.is_current():
        return s
    _err("First run: getting Ratica ready. This downloads about 5 GB once.")
    return prepare(on_progress=_download_printer(), log=_err)


def setup_command(a) -> int:
    prepare(on_progress=_download_printer(), log=_err)
    return 0


def info_command(a) -> int:
    hw = hardware.probe()
    s = load_settings()
    print(f"Ratica {__version__}")
    print(f"System: {hw['system']} {hw['machine']}")
    print(f"NVIDIA GPUs: {', '.join(f'{g['name']} ({g['total_mib']} MiB)' for g in hw['nvidia']) or 'none'}")
    print(f"Backend: {s.backend if s else hw['backend']}")
    print(json.dumps(s.__dict__, indent=1) if s else "Not set up yet: run `ratica setup`.")
    print(f"Data folder: {paths.data_dir()}")
    return 0


def translate_command(a) -> int:
    pdf = Path(a.pdf)
    if not pdf.exists():
        _err(f"error: {pdf} not found")
        return 2
    keep = [t.strip() for t in a.keep.split(",")] if a.keep else []

    if a.server_url:
        settings = Settings("external", "", "", a.slots or 1, 0, "")
    elif a.llama_server and a.model:
        settings = Settings("cpu" if a.cpu else "gpu", a.llama_server, a.model, a.slots or 1, 0, "")
    else:
        settings = _ready_settings()
        if a.slots:
            settings.slots = a.slots
        seconds = estimate_seconds(extract(pdf), settings.words_per_second,
                                   seconds_per_block=settings.seconds_per_block)
        minutes = (seconds + 45) / 60  # + engine start
        _err(f"Estimated time on this computer: about {max(1, round(minutes))} min")

    result = translate_pdf(pdf, a.to, settings, out_dir=a.out, source=a.source, server_url=a.server_url,
                           keep_terms=keep, on_progress=_progress_printer())
    _err("")
    _err(f"Wrote {result['pdf']}\nWrote {result['epub']}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ratica", description="Translate PDF books on your own computer.")
    ap.add_argument("--version", action="version", version=f"ratica {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="download the engine and model and measure this computer's speed")
    sub.add_parser("info", help="show hardware and settings (useful for bug reports)")

    t = sub.add_parser("translate", help="translate a PDF into PDF + EPUB")
    t.add_argument("pdf")
    t.add_argument("--to", required=True, help="target language code, e.g. tr, de, zh")
    t.add_argument("--source", default="en", help="source language code (default: en)")
    t.add_argument("--out", help="output folder (default: next to the PDF)")
    t.add_argument("--keep", help="comma-separated names that must not be translated")
    t.add_argument("--slots", type=int, help="paragraphs translated at once (default: measured)")
    adv = t.add_argument_group("advanced: use your own engine")
    adv.add_argument("--server-url", help="URL of a running llama-server")
    adv.add_argument("--llama-server", help="path to a llama-server executable")
    adv.add_argument("--model", help="path to a .gguf model")
    adv.add_argument("--cpu", action="store_true", help="with --llama-server: do not use the GPU")

    a = ap.parse_args(argv)
    return {"setup": setup_command, "info": info_command, "translate": translate_command}[a.command](a)


if __name__ == "__main__":
    sys.exit(main())
