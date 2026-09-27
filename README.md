# Ratica

**Translate long technical PDF books on your own computer.** Ratica reads a PDF, translates it paragraph by paragraph with a local AI model, and gives you the translation as both PDF and EPUB. No cloud, no account, no API key. Your book never leaves your machine.

> **Status: early development.** There is no release yet. Watch the repository to follow along.

![How Ratica translates a book](docs/images/pipeline.svg)

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

Windows, macOS and Linux. About 6 GB of free disk space for the engine and the model.

![How Ratica picks an engine](docs/images/backends.svg)

## The AI model

Ratica uses **[Gemma-4-E4B-it](https://huggingface.co/google/gemma-4-E4B-it)** (Apache 2.0) through [llama.cpp](https://github.com/ggml-org/llama.cpp). It was chosen after comparing several current open models on translation quality, protection of code and URLs, speed and memory use. The benchmark scripts are in [`bench/`](bench/), so anyone can run the comparison on their own hardware.

## Privacy

Everything runs locally. Ratica only goes online to download the engine and the model on first launch and to check for updates on GitHub. It never uploads your files or text.

## Roadmap

| v1 | v2 |
|---|---|
| Text PDFs → PDF + EPUB | OCR for scanned pages |
| Code, URL, formula and name protection | Translated diagram labels |
| Resumable, parallel translation | Splitting large tables |
| Automatic hardware setup | Glossary for consistent terms |
| Simple desktop app | Side-by-side preview |

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
