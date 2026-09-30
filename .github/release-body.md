Ratica translates PDF books on your own computer and keeps the original page layout. Free, open source, offline. This is a **beta**: please [report anything that goes wrong](https://github.com/kaanncavdar/ratica/issues).

## What's new in 0.1.3

- **macOS: signed and notarized by Apple.** Ratica opens with a double click, without the "Apple could not
  verify" warning.
- **Free up space:** the window shows how much the downloaded engine and model take and can delete them.
  The Windows uninstaller asks whether to delete them too.

Earlier: translate from any supported language, recognised from the book (0.1.1); Applications shortcut in the
macOS disk image (0.1.2).

![Before and after](https://raw.githubusercontent.com/kaanncavdar/ratica/main/docs/images/before-after.png)

## Which file do I need?

| Your computer | Download | How to install |
|---|---|---|
| **Windows 10/11** (64-bit) | `Ratica-…-Windows-Setup.exe` | Run it. The installer is not code-signed yet, so Windows may show *"Windows protected your PC"*: click **More info → Run anyway**. |
| **Mac with Apple Silicon** (M1, M2, M3, M4) | `Ratica-…-macOS-AppleSilicon.dmg` | Open it and drag **Ratica** onto **Applications**, then open it from there. The app is signed and notarized by Apple. |
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
