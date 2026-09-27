# Ratica

**Translate long technical PDF books on your own computer.** Ratica reads a PDF, translates it paragraph by paragraph with a local AI model, and gives you the translation as both PDF and EPUB. No cloud, no account, no API key. Your book never leaves your machine.

> **Status: beta.** Ratica works end to end, but it is young: expect rough edges and please [report them](https://github.com/kaanncavdar/ratica/issues).

![How Ratica translates a book](docs/images/pipeline.svg)

## Install

Download the file for your system from **[Releases](https://github.com/kaanncavdar/ratica/releases)**:

| System | File | Notes |
|---|---|---|
| Windows 10/11 | `Ratica-…-Windows-Setup.exe` | Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway**. |
| macOS (Apple Silicon) | `Ratica-…-macOS-AppleSilicon.dmg` | Drag Ratica to Applications. The first time, right-click Ratica → **Open**, because the app is not notarized by Apple. |
| Linux (x64) | `Ratica-…-Linux-x64.tar.gz` | Unpack and run `Ratica/Ratica`. |

On first start Ratica downloads its translation engine and AI model (about 5–6 GB, once) and measures your computer's speed. After that it works offline.

### Run from source

Download or clone this repository, then double-click **`start.bat`** (Windows) or **`start.command`** (macOS), or run `./start.sh` (Linux). The script installs [uv](https://docs.astral.sh/uv/) if needed, then Ratica's packages, then opens the app.

## Use

1. Choose a PDF or drop it on the window.
2. Pick the language to translate to.
3. Press **Translate**. You can pause and resume at any time; progress is saved.
4. The translated `book.<language>.pdf` and `book.<language>.epub` are saved next to the original.

There is also a command line:

```
ratica translate book.pdf --to de        # translate (sets itself up on first use)
ratica translate book.pdf --to ja --keep "Kubernetes,Linus Torvalds"
ratica setup                             # download and measure speed now
ratica info                              # hardware and settings, for bug reports
```

## Features

- Translates text-based PDF books between many languages written left to right: Latin, Cyrillic, Greek, Chinese, Japanese, Korean, Devanagari and more.
- Keeps code, URLs, formulas and names exactly as they are.
- Keeps images, headings, lists and code blocks.
- Shows every language's letters correctly by falling back to [Noto](https://fonts.google.com/noto) fonts.
- Writes both a **PDF** and an **EPUB** (EPUB reflows nicely on phones and e-readers).
- Resumes where it stopped if the computer sleeps or the app closes.
- Shows a time estimate before starting.
- Sets itself up: it detects your hardware, downloads the right engine and model once, and measures your computer's speed.
- Leaves room for your other work: it never fills the GPU memory and runs at low priority.

## How fast is it?

On an entry-level gaming GPU with 6 GB of memory, a 200-page book takes about **half an hour**. Faster GPUs finish sooner because they translate more paragraphs at once. Without a GPU, translation works but takes many hours.

## Requirements

| Hardware | Support |
|---|---|
| NVIDIA GPU with 6 GB or more | ✅ Recommended (CUDA) |
| Apple Silicon Mac (M1 or newer) | ✅ Supported (Metal) |
| AMD or Intel GPU | 🧪 Should work (Vulkan), not yet tested — reports welcome |
| No GPU | ⚠️ Works, but slow |

Windows 10/11, macOS 12 or newer, and Linux. About 6 GB of free disk space for the engine and the model.

![How Ratica picks an engine](docs/images/backends.svg)

## The AI model

Ratica uses **[Gemma-4-E4B-it](https://huggingface.co/google/gemma-4-E4B-it)** (Apache 2.0) through [llama.cpp](https://github.com/ggml-org/llama.cpp). It was chosen after comparing several current open models on translation quality, protection of code and URLs, speed and memory use. The benchmark scripts are in [`bench/`](bench/), so anyone can run the comparison on their own hardware.

## Privacy

Everything runs locally. Ratica only goes online to download the engine and the model on first launch and to check for updates on GitHub. It never uploads your files or text.

## Known limitations

- Scanned PDFs (pages that are images) are not translated yet; OCR is planned.
- Text inside images and diagrams stays in the original language.
- The output is reflowed, so page numbers differ from the original. Formulas typeset as text may lose their layout.
- The app window is in English for now.

## Roadmap

| v1 (now) | v2 |
|---|---|
| Text PDFs → PDF + EPUB | OCR for scanned pages |
| Code, URL, formula and name protection | Translated diagram labels |
| Resumable, parallel translation | Splitting large tables |
| Automatic hardware setup | Glossary for consistent terms |
| Simple desktop app | Side-by-side preview, translated app window |

Right-to-left scripts and comics (text inside speech bubbles) are ideas for later, not promises.

Read the design in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

## Contributing

Ratica is built in the open and help is welcome, especially:

- **Hardware reports** from AMD, Intel and Apple GPUs: speed, memory use, anything that breaks.
- **Translation quality feedback** in any language.
- Bug reports and pull requests.

## Acknowledgements

[llama.cpp](https://github.com/ggml-org/llama.cpp) · [Gemma](https://ai.google.dev/gemma) · [PyMuPDF](https://github.com/pymupdf/PyMuPDF) · [Noto fonts](https://fonts.google.com/noto) · [FLORES-200](https://github.com/facebookresearch/flores) · [PySide6](https://doc.qt.io/qtforpython-6/)

## License

[AGPL-3.0](LICENSE). Ratica is free and open source. Anyone may use, study and change it; modified versions must stay open source too.
