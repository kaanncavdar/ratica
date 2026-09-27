"""High-level operations shared by the command line and the GUI.

``prepare`` gets the machine ready (hardware probe, downloads, speed test) and saves the
result; ``translate_pdf`` runs one book from start, or from where it paused, to PDF + EPUB.
"""
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from . import hardware, install, paths
from .docmodel import Book
from .engine import Engine, EngineConfig, make_translator
from .extract import extract
from .queue import JobStore, translate_book
from .render import write_epub, write_pdf
from .tune import measure


@dataclass
class Settings:
    backend: str
    server: str
    model: str
    slots: int
    words_per_second: float
    llama_build: str
    seconds_per_block: float = 0  # fixed cost of each request, measured on short texts

    def is_current(self) -> bool:
        return (self.llama_build == install.LLAMA_BUILD and Path(self.server).exists()
                and Path(self.model).exists())

    def engine_config(self) -> EngineConfig:
        return EngineConfig(server=Path(self.server), model=Path(self.model), slots=self.slots,
                            gpu=self.backend != "cpu")


def load_settings(path=None) -> Settings | None:
    path = Path(path or paths.config_path())
    try:
        return Settings(**json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return None


def save_settings(s: Settings, path=None):
    Path(path or paths.config_path()).write_text(json.dumps(asdict(s), indent=1), encoding="utf-8")


def estimate_seconds(book: Book, words_per_second: float, done_ids=frozenset(), seconds_per_block: float = 0) -> float:
    """Words over measured speed, plus a fixed cost per paragraph (books have many short ones)."""
    todo = [b for b in book.blocks if b.translatable and b.id not in done_ids]
    return sum(len(b.text.split()) for b in todo) / words_per_second + len(todo) * seconds_per_block


def prepare(on_progress=None, should_stop=None, log=print) -> Settings:
    """Download what this machine needs and measure its speed. Safe to call again: finished steps are skipped."""
    progress = on_progress or (lambda stage, done, total: None)
    hw = hardware.probe()
    (paths.logs_dir() / "hardware.json").write_text(json.dumps(hw, indent=1), encoding="utf-8")
    log(f"Hardware: {hw['system']} {hw['machine']}, "
        f"{', '.join(g['name'] for g in hw['nvidia']) or 'no NVIDIA GPU'} -> {hw['backend']}")

    model = install.install_model(lambda d, t: progress("model", d, t), should_stop)
    # Try the best engine first; fall back if it cannot start (for example, an old driver).
    order = {"cuda": ["cuda", "vulkan", "cpu"], "vulkan": ["vulkan", "cpu"], "metal": ["metal", "cpu"],
             "cpu": ["cpu"]}[hw["backend"]]
    last_error = None
    for backend in order:
        try:
            server = install.install_engine(hw["system"], backend, lambda d, t: progress("engine", d, t),
                                            should_stop)
            cfg = EngineConfig(server=server, model=model, gpu=backend != "cpu")
            progress("speed test", 0, 1)
            result = measure(cfg, log_path=paths.logs_dir() / f"speedtest-{backend}.log",
                             on_step=lambda k, wps: log(f"  {k} at once: {wps:.1f} words/s"))
            progress("speed test", 1, 1)
        except (RuntimeError, TimeoutError, OSError) as e:
            log(f"{backend} did not work ({e}); trying the next option")
            last_error = e
            continue
        s = Settings(backend=backend, server=str(server), model=str(model), slots=result["slots"],
                     words_per_second=round(result["words_per_second"], 2), llama_build=install.LLAMA_BUILD,
                     seconds_per_block=round(result["seconds_per_block"], 3))
        save_settings(s)
        log(f"Ready: {backend}, {s.slots} paragraphs at once, {s.words_per_second:.0f} words/s")
        return s
    raise RuntimeError(f"no engine could start on this computer: {last_error}")


def work_dir(pdf: Path, out_dir: Path, lang: str) -> Path:
    d = out_dir / f"{pdf.stem}.{lang}.ratica"
    d.mkdir(parents=True, exist_ok=True)
    return d


def translate_pdf(pdf, lang: str, settings: Settings | None = None, out_dir=None, source: str = "en",
                  server_url: str | None = None, keep_terms=(), on_progress=None, should_stop=None) -> dict:
    """Translate one PDF. Returns {"finished", "pdf", "epub", "seconds"}; paused jobs resume on the next call."""
    pdf = Path(pdf)
    out_dir = Path(out_dir) if out_dir else pdf.parent
    work = work_dir(pdf, out_dir, lang)
    book = extract(pdf)
    store = JobStore(work / "job.sqlite")
    t0 = time.monotonic()

    def run(url, slots):
        return translate_book(book, store, make_translator(url, source, lang), slots=slots, keep_terms=keep_terms,
                              on_progress=on_progress, should_stop=should_stop)

    if server_url:
        finished = run(server_url, settings.slots if settings else 1)
    else:
        with Engine(settings.engine_config(), log_path=work / "llama-server.log") as engine:
            finished = run(engine.url, settings.slots)

    result = {"finished": finished, "pdf": None, "epub": None, "seconds": time.monotonic() - t0}
    if finished:
        translations = store.translations()
        first_heading = next((b.id for b in book.blocks if b.kind == "heading"), None)
        book.title = translations.get(first_heading, book.title)
        result["pdf"] = write_pdf(book, translations, out_dir / f"{pdf.stem}.{lang}.pdf", lang=lang)
        result["epub"] = write_epub(book, translations, out_dir / f"{pdf.stem}.{lang}.epub", lang=lang)
    return result
