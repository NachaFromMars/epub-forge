# epub-forge — Markdown + YAML → validated EPUB 3.3 in one command

> Define your book in a single `book.yaml`, point at your Markdown chapters, and get a fully validated EPUB 3.3. Auto EPUBCheck: zero fatal errors, zero errors, zero warnings.

[![OpenClaw Skill](https://img.shields.io/badge/OpenClaw-Skill-blueviolet)](https://github.com/NachaFromMars)

## Overview
epub-forge is a forge engine that converts Markdown content plus a YAML config into a standards-compliant EPUB. Targets EPUB 3.3 + OCF 3.3 + EPUB Accessibility 1.1, with a legacy NCX for EPUB 2 readers (Kindle, Kobo). Everything is driven by `book.yaml`. Unlike epub-builder (raw chapter files), forge is a Markdown-plus-YAML pipeline with automatic validation.

## Features
- **Standards** — EPUB 3.3 + OCF 3.3 + Accessibility 1.1
- **Legacy NCX** — EPUB 2 compatibility (Kindle, Kobo)
- **Auto-validation** — EPUBCheck → 0 fatal / 0 error / 0 warning
- **Single config** — `book.yaml` for metadata, cover, chapters, options
- **One-command** — Markdown in → validated `.epub` out

## Usage / Quick Start
```yaml
# book.yaml
metadata:
  title: "My Book"
  author: "Author Name"
  language: vi
cover: cover.jpg
chapters:
  - file: chapters/ch01.md
    title: "Chapter 1"
```
Then run the forge command to produce a validated `.epub`.

## Trigger Keywords (OpenClaw)
epub forge, build epub, đóng epub, xuất epub, export epub, publish book, epub 3.3

## Related Skills
- [epub-builder](https://github.com/NachaFromMars/epub-builder) — raw chapter files to EPUB
- [epub-reader](https://github.com/NachaFromMars/epub-reader) — read and convert EPUB files

---
Part of the [NachaFromMars](https://github.com/NachaFromMars) OpenClaw skill ecosystem.
