# Architecture

Ratica is a desktop app that translates long technical PDF books **entirely on your computer**. It reads a PDF, translates it paragraph by paragraph with a local language model, and writes the translation as both PDF and EPUB. No text leaves the machine.

This document describes the app as of v0.1.3.

![Translation pipeline](images/pipeline.svg)

## Design principles

- **Local only.** No cloud, no account, no API key. The model runs through [llama.cpp](https://github.com/ggml-org/llama.cpp).
- **Works for non-technical users.** Installing the app and translating a book happens in the GUI with no terminal and no manual model setup.
- **Honest about time.** Before a book starts, the app shows how long it will take on this machine.
- **Never lose work.** Every translated paragraph is saved at once, so a closed laptop or a crash resumes where it stopped.
- **The computer stays usable.** The engine always leaves GPU memory free (1 GB by default) and runs at below-normal priority.
- **One code path.** Hardware differences live in the engine build and a few measured numbers, not in `if vendor == ...` branches.

## Modules

All modules live in `src/ratica/`.

| Module | Responsibility | Main library |
|---|---|---|
| `extract.py` | Read text, fonts, positions and images from the PDF and remember each block's box and style. Rows of tables and contents pages are split into cells; paragraphs are split at first-line indents. Marks what must not be translated: code (monospaced), formulas (math fonts, sub- and superscripts, unreadable glyphs, fraction pieces), page references and symbols. Serif/bold are judged from the glyph shapes when font names are meaningless. | PyMuPDF |
| `docmodel.py` | Format-independent book: blocks (heading, paragraph, item, header, code, formula, figure, mark, image), each with a stable ID, a hash of its text and its boxes on the page. | dataclasses |
| `detect.py` | Guess the book's language from its script and most common words. | – |
| `protect.py` | Wrap spans that must survive unchanged in `<keep>…</keep>` (URLs, code, identifiers, the user's do-not-translate list) and check them after translation. | regex |
| `queue.py` | SQLite job store: every block's state and translation, a cache keyed by text hash, parallel dispatch, one retry, fallback to the source text. Section numbers and quotation marks are kept. | sqlite3 |
| `engine.py` | Start, watch and stop `llama-server` on `127.0.0.1`; the translation prompt. | subprocess, requests |
| `hardware.py`, `install.py`, `tune.py` | Probe the GPU, download the matching llama.cpp build and the model (pinned by SHA-256, resumable), and measure how many paragraphs to run at once. | requests, psutil |
| `layout.py` | Write the translation into the original pages (see below). | PyMuPDF |
| `render.py` | Reflowed EPUB (and an optional reflowed PDF with `--reflow`). | PyMuPDF, ebooklib |
| `service.py` | The operations shared by the window and the command line: setup, translate, time estimate, freeing disk space. | – |
| `gui.py`, `cli.py` | Desktop window and command line. | PySide6, argparse |

**Keeping the layout (`layout.py`).** Each page is planned before it changes: every translated block gets the room
it may use (its own box, grown right to its column edge and down into free space, never over other text, images,
lines or coloured boxes), and the size it needs is measured by writing on a scratch page. Paragraphs of one style
on a page share one size. A translation that could only fit below a readable size keeps the original. Then the
original text of the planned blocks is removed (images and drawings stay) and the translations are written on the
original baseline, in a matching serif or sans-serif font, size, colour, weight and indent.

The engine is a separate process on purpose: llama.cpp ships ready-made builds for every platform and GPU, so the app never compiles native code, and a crash in the engine cannot take the GUI down.

## Engine and hardware

![Choosing the inference backend](images/backends.svg)

| Hardware | Engine build | Notes |
|---|---|---|
| NVIDIA GPU | CUDA | Fastest on NVIDIA: CUDA scales with parallel paragraphs much better than Vulkan. The CUDA runtime (~370 MB) is downloaded on first launch, only on NVIDIA machines. |
| Apple Silicon | Metal | Signed and notarized builds. |
| AMD or Intel GPU | Vulkan | Not tested yet; community reports welcome. |
| No usable GPU | CPU | Supported but slow: a 200-page book can take many hours. The app says so before starting. |

**Default model:** Gemma-4-E4B-it, GGUF Q4_K_M (≈ 4.6 GB). It was chosen by a blind human comparison and automatic scores; the benchmark scripts are in [`bench/`](../bench/). A choice of larger models for GPUs with more memory is planned.

**Parallel slots:** the first-launch speed test runs 1, 2, 4… paragraphs at once and keeps the smallest setting within 5% of the fastest. The result is saved; after each finished book the real speed is learned and used for the next estimate.

**Memory:** llama.cpp's `--fit` places as much of the model on the GPU as fits while keeping 1 GB free; there are no hard-coded thresholds.

## First launch

![First launch](images/first-run.svg)

## Translating a book

1. `extract` + `docmodel` build the book structure. Blocks that will not be translated are marked.
2. The app estimates the time: *remaining words × measured seconds per word*, and shows it.
3. `queue` sends blocks to the engine in reading order, N at a time. Each result goes through `protect`'s check and is saved immediately.
4. When all blocks are done, `layout` writes `book.<lang>.pdf` into the original pages and `render` writes `book.<lang>.epub`.

A project folder next to the book keeps the SQLite queue, so reopening the same PDF continues the job. The source-text hash detects a changed PDF.

**Prompt:** one short system instruction ("translate from X to Y, output only the translation, copy `<keep>` spans unchanged") and one block per request, with temperature 0. Tested: no model in the benchmark added introductions or notes.

## Languages and fonts

- v1 targets left-to-right scripts: Latin (including Turkish and Azerbaijani letters), Cyrillic, Greek, CJK, Devanagari and others.
- The translated PDF uses the renderer's built-in serif and sans-serif fonts; the EPUB embeds Noto Sans. Chinese, Japanese and Korean output depends on the fonts available to the renderer — check the output.
- Right-to-left scripts are out of scope for v1.

## Project layout

```
ratica/
├─ src/ratica/     # the app (modules above), assets/icon.png
├─ tests/          # pytest suite (fake llama-server, generated PDFs; no copyrighted text)
├─ bench/          # model benchmark scripts
├─ packaging/      # PyInstaller spec, Inno Setup script, icons, macOS entitlements
├─ docs/           # this document, images, demo book and intro video
└─ .github/        # CI (tests on Windows, macOS, Linux) and the release workflow
```

## Build and release

- GitHub Actions runs the tests on Windows, macOS and Linux for every push, and builds the installers with
  PyInstaller: Windows (Inno Setup `.exe`), macOS (`.dmg`, Apple Silicon) and Linux (`.tar.gz`). A `v*` tag
  publishes them as a release.
- Installers contain the app only. The llama.cpp build and the model are downloaded on first launch, so the
  installers stay small (~55–105 MB).
- The macOS app is signed with a Developer ID certificate and notarized by Apple. The Windows installer is not
  code-signed yet, so SmartScreen may warn once.
- Uninstalling on Windows offers to delete the downloaded engine and model; the window can delete them too.
- License: **AGPL-3.0** (required by PyMuPDF, and it keeps derivatives open).

## Scope

| v1 | v2 | Later ideas (not committed) |
|---|---|---|
| Text PDFs, PDF + EPUB output | OCR for scanned pages (local PaddleOCR) | Right-to-left scripts |
| Code, URL, formula and name protection | Translated diagram labels (numbered legend) | Vertical text |
| Resumable queue, parallel paragraphs | Splitting large tables across pages | Comics and manga: text in speech bubbles |
| Automatic engine and slot selection | Glossary (CSV) for consistent terms | |
| Minimal GUI | Side-by-side preview, mark text not to translate | |
