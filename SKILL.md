---
name: epub-forge
description: "Build EPUB 3.3 W3C standard-compliant ebooks from Markdown + YAML config. Automation pipeline: MD files + metadata + cover → validated .epub (EPUBCheck 0 fatal/0 error). Use when: building ebooks, converting markdown to EPUB, publishing novels/books, creating standard EPUB files. Triggers: epub, ebook, build epub, epub forge, đóng epub, xuất epub, export epub, publish book, sách điện tử, epub 3.3, W3C epub."
version: 1.0.0
---

> ⚠️ This skill is for NOVEL/general EPUB. For RemNote analysis EPUB, use `remnote-epub` skill instead.

# epub-forge — EPUB 3.3 W3C Forge Engine

Build EPUB 3.3 compliant ebooks from Markdown chapters + YAML config.
One command → validated `.epub` file ready for publishing.

## Standard Compliance

- **EPUB 3.3** — W3C Recommendation (2023-05-25)
- **OCF 3.3** — Open Container Format (ZIP packaging)
- **EPUB Accessibility 1.1** — a11y metadata included
- **Backward Compatible** — Legacy NCX for EPUB 2 readers (Kindle, Kobo)
- **Validation** — Auto EPUBCheck → 0 fatal / 0 error / 0 warning

## Quick Start

### 1. Create config file (`book.yaml`)

```yaml
metadata:
  title: "Tên Sách"
  author: "Tác Giả"
  language: "vi"
  publisher: "NXB"
  description: "Mô tả sách"
  date: "2026-01-01"

cover: "images/cover.jpg"

chapters:
  - title: "Chương 1: Khởi Đầu"
    file: "chapters/ch01.md"
  - title: "Chương 2: Hành Trình"
    file: "chapters/ch02.md"

options:
  ncx: true           # Legacy NCX for EPUB 2 compat
  accessibility: true  # EPUB Accessibility 1.1 metadata
  validate: true       # Auto EPUBCheck after build
  copyright: true      # Generate copyright page
```

### 2. Build EPUB

```bash
python3 scripts/epub_forge.py build --config book.yaml
```

### 3. Validate existing EPUB

```bash
python3 scripts/epub_forge.py validate --epub book.epub
```

### 4. Preview structure

```bash
python3 scripts/epub_forge.py info --config book.yaml
```

## Config Reference

### `metadata` (required)

| Field | Required | Description |
|-------|----------|-------------|
| `title` | ✅ | Book title |
| `author` | ✅ | Author name |
| `language` | ✅ | Language code (vi, en, zh...) |
| `identifier` | Auto | UUID (auto-generated if empty) |
| `publisher` | | Publisher name |
| `description` | | Book description |
| `date` | | Publication date (YYYY-MM-DD) |
| `isbn` | | ISBN number |
| `rights` | | Copyright notice |

### `chapters` (required)

List of chapters in reading order:

```yaml
chapters:
  - title: "Chapter Title"
    file: "path/to/chapter.md"
```

- **title** — Chapter title (shown in TOC)
- **file** — Path to Markdown file (relative to config dir)

### `frontmatter` (optional)

Content before chapters:

```yaml
frontmatter:
  - type: "dedication"
    content: "Dành tặng..."
  - type: "foreword"
    title: "Lời Nói Đầu"
    file: "frontmatter/foreword.md"
```

### `backmatter` (optional)

Content after chapters:

```yaml
backmatter:
  - type: "about-author"
    title: "Về Tác Giả"
    file: "backmatter/about.md"
```

### `cover`

Path to cover image. **MUST be PNG or JPG** (SVG not allowed — many readers don't render SVG covers).

### `css`

Path to custom CSS file. If not provided, uses built-in default (Vietnamese-optimized serif typography).

### `images_dir`

Directory containing additional images referenced in chapters.

### `fonts_dir`

Directory containing custom fonts (OTF/TTF/WOFF/WOFF2).

### `options`

| Option | Default | Description |
|--------|---------|-------------|
| `ncx` | `true` | Generate legacy NCX for EPUB 2 readers |
| `accessibility` | `true` | Include EPUB Accessibility 1.1 metadata |
| `validate` | `true` | Run EPUBCheck after build |
| `copyright` | `true` | Generate copyright page |

## Output EPUB Structure

```
book.epub (ZIP)
├── mimetype                        ← STORED, first entry
├── META-INF/container.xml          ← OCF container
└── OEBPS/
    ├── content.opf                 ← Package Document
    ├── toc.xhtml                   ← Navigation Document
    ├── toc.ncx                     ← Legacy NCX
    ├── Text/
    │   ├── cover.xhtml             ← Cover page
    │   ├── titlepage.xhtml         ← Title page
    │   ├── copyright.xhtml         ← Copyright
    │   └── chapter-NNN.xhtml       ← Chapters
    ├── Styles/style.css            ← CSS
    ├── Images/cover.{jpg|png}      ← Cover image
    └── Fonts/                      ← Embedded fonts
```

## XHTML Sanitization

epub-forge automatically:
- Replaces 50+ HTML entities → Unicode (XHTML only allows 5: `&amp; &lt; &gt; &quot; &apos;`)
- Self-closes void elements (`<br/>`, `<hr/>`, `<img ... />`)
- Adds proper XML declarations and namespaces
- Validates XML well-formedness

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success — EPUB built and valid |
| 1 | Validation failed (EPUBCheck errors) |
| 2 | Build error (file write, ZIP) |
| 3 | Config error (missing file, bad YAML) |

## Dependencies

**Core (stdlib — zero install):** zipfile, xml.etree, json, re, uuid, datetime, argparse

**Optional:**
- `pyyaml` — YAML config parsing (use JSON if not installed)
- `markdown` — Better MD→HTML conversion (fallback: basic regex)
- `Pillow` — Cover image validation
- `epubcheck` — EPUB validation (Java)

## Agent Usage

When using epub-forge from OpenClaw:

```python
# Build EPUB
exec("cd /path/to/book && python3 /path/to/epub_forge.py build --config book.yaml --output output.epub")

# Validate
exec("python3 /path/to/epub_forge.py validate --epub output.epub")
```

## Error Handling

| Error | Cause | Fix |
|-------|-------|-----|
| `Cover must be PNG or JPG` | SVG cover provided | Convert to PNG: `rsvg-convert cover.svg > cover.png` |
| `Chapter file not found` | Wrong path in config | Check file path relative to config directory |
| `Illegal entity` | HTML entities in content | Auto-fixed; check source MD files |
| `EPUBCheck not found` | epubcheck not installed | Install: `apt install epubcheck` or skip validation |

## Changelog

### v1.0.0 (2026-03-19)
- Initial release
- EPUB 3.3 W3C compliant
- 50+ entity sanitization
- Auto NCX generation
- Accessibility metadata
- EPUBCheck integration
- Vietnamese-optimized CSS
