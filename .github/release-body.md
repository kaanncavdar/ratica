Ratica translates PDF books on your own computer and keeps the original page layout. Free, open source, offline. This is a **beta**: please [report anything that goes wrong](https://github.com/kaanncavdar/ratica/issues).

## What's new in 0.1.1

- **Translate from any supported language, not only English.** Ratica recognises the language of the book
  and preselects it; you can change it in the new *Translate from* box.
- English is now a target language too, so you can translate books into English.
- On the command line, `--source` is detected from the book unless you give it.

![Before and after](https://raw.githubusercontent.com/kaanncavdar/ratica/main/docs/images/before-after.png)

## Which file do I need?

| Your computer | Download | How to install |
|---|---|---|
| **Windows 10/11** (64-bit) | `Ratica-…-Windows-Setup.exe` | Run it. Windows may say *"Windows protected your PC"* because the installer is not code-signed: click **More info → Run anyway**. |
| **Mac with Apple Silicon** (M1, M2, M3, M4) | `Ratica-…-macOS-AppleSilicon.dmg` | Open it and drag **Ratica** to **Applications**. The first time, right-click Ratica → **Open** → **Open**, because the app is not notarized by Apple. |
| **Linux** (x64) | `Ratica-…-Linux-x64.tar.gz` | `tar xzf Ratica-*-Linux-x64.tar.gz && ./Ratica/Ratica` |

## First start

Ratica downloads its translation engine and AI model once (about 5–6 GB) and measures your computer's speed. After that it works offline.

- **NVIDIA GPU (6 GB or more):** recommended, uses CUDA.
- **Apple Silicon Mac:** supported, uses Metal.
- **AMD / Intel GPU:** should work through Vulkan; not tested yet, reports welcome.
- **No GPU:** works, but a book takes many hours.

## How to use

1. Choose a PDF (or drop it on the window) and pick a language.
2. Press **Translate**. You can pause and resume; progress is saved.
3. `book.<language>.pdf` (same layout) and `book.<language>.epub` appear next to the original.

A 30-second intro video is in the [README](https://github.com/kaanncavdar/ratica#readme).

## Known limitations

- Scanned PDFs (pages that are images) are not translated yet.
- Text inside images and pages rotated sideways stay in the original language.
- A phrase in italics or a coloured link inside a paragraph takes the paragraph's main style.
