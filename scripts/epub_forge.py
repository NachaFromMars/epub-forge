#!/usr/bin/env python3
"""
epub-forge — EPUB 3.3 W3C Forge Engine
Build EPUB 3.3 compliant ebooks from Markdown + YAML config.
Zero external dependency core (stdlib only for packaging).

Author: Tiểu Tâm / OpenClaw
Version: 1.0.0
Standard: EPUB 3.3 (W3C Recommendation 2023-05-25)
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

# Optional deps — graceful fallback
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

try:
    import markdown as md_lib
    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────

VERSION = "1.0.0"
EPUB_MIMETYPE = "application/epub+zip"

# XHTML only allows these 5 entities — everything else must be Unicode
ALLOWED_ENTITIES = {"&amp;", "&lt;", "&gt;", "&quot;", "&apos;"}

# HTML named entities → Unicode replacement (50+ mappings)
ENTITY_MAP = {
    "&mdash;": "\u2014", "&ndash;": "\u2013", "&hellip;": "\u2026",
    "&lsquo;": "\u2018", "&rsquo;": "\u2019",
    "&ldquo;": "\u201C", "&rdquo;": "\u201D",
    "&nbsp;": "\u00A0", "&bull;": "\u2022", "&copy;": "\u00A9",
    "&reg;": "\u00AE", "&trade;": "\u2122", "&diams;": "\u2666",
    "&hearts;": "\u2665", "&spades;": "\u2660", "&clubs;": "\u2663",
    "&deg;": "\u00B0", "&times;": "\u00D7", "&divide;": "\u00F7",
    "&plusmn;": "\u00B1", "&frac12;": "\u00BD", "&frac14;": "\u00BC",
    "&frac34;": "\u00BE", "&para;": "\u00B6", "&sect;": "\u00A7",
    "&dagger;": "\u2020", "&Dagger;": "\u2021", "&laquo;": "\u00AB",
    "&raquo;": "\u00BB", "&iexcl;": "\u00A1", "&iquest;": "\u00BF",
    "&cent;": "\u00A2", "&pound;": "\u00A3", "&yen;": "\u00A5",
    "&euro;": "\u20AC", "&micro;": "\u00B5", "&macr;": "\u00AF",
    "&acute;": "\u00B4", "&cedil;": "\u00B8", "&ordf;": "\u00AA",
    "&ordm;": "\u00BA", "&sup1;": "\u00B9", "&sup2;": "\u00B2",
    "&sup3;": "\u00B3", "&not;": "\u00AC", "&brvbar;": "\u00A6",
    "&shy;": "\u00AD", "&middot;": "\u00B7", "&thinsp;": "\u2009",
    "&ensp;": "\u2002", "&emsp;": "\u2003", "&zwj;": "\u200D",
    "&zwnj;": "\u200C", "&lrm;": "\u200E", "&rlm;": "\u200F",
    "&OElig;": "\u0152", "&oelig;": "\u0153", "&Scaron;": "\u0160",
    "&scaron;": "\u0161", "&Yuml;": "\u0178", "&circ;": "\u02C6",
    "&tilde;": "\u02DC", "&fnof;": "\u0192",
}

# Numeric entity pattern
NUMERIC_ENTITY_RE = re.compile(r"&#(\d+);")
HEX_ENTITY_RE = re.compile(r"&#x([0-9a-fA-F]+);")
NAMED_ENTITY_RE = re.compile(r"&([a-zA-Z][a-zA-Z0-9]*);")

# Cover image accepted types
COVER_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

# Image media types
IMAGE_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}

# Font media types
FONT_MEDIA_TYPES = {
    ".otf": "font/otf",
    ".ttf": "font/ttf",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}


# ─────────────────────────────────────────────
# Entity Sanitizer
# ─────────────────────────────────────────────

def sanitize_entities(html: str) -> str:
    """Replace ALL HTML named entities with Unicode equivalents.
    Only &amp; &lt; &gt; &quot; &apos; pass through (XHTML legal).
    Numeric entities (&#123; &#xAB;) are converted to characters.
    """
    # Step 1: Numeric decimal entities → Unicode
    def _dec_replace(m):
        try:
            return chr(int(m.group(1)))
        except (ValueError, OverflowError):
            return m.group(0)
    html = NUMERIC_ENTITY_RE.sub(_dec_replace, html)

    # Step 2: Hex entities → Unicode
    def _hex_replace(m):
        try:
            return chr(int(m.group(1), 16))
        except (ValueError, OverflowError):
            return m.group(0)
    html = HEX_ENTITY_RE.sub(_hex_replace, html)

    # Step 3: Named entities from map
    for entity, char in ENTITY_MAP.items():
        html = html.replace(entity, char)

    # Step 4: Catch remaining unknown named entities (warn + remove)
    def _named_replace(m):
        full = m.group(0)
        if full in ALLOWED_ENTITIES:
            return full
        # Unknown entity — convert to nothing or keep literal
        print(f"  ⚠️  Unknown entity removed: {full}", file=sys.stderr)
        return ""
    html = NAMED_ENTITY_RE.sub(_named_replace, html)

    return html


def verify_no_illegal_entities(xhtml: str) -> list:
    """Scan XHTML for illegal entities. Returns list of violations."""
    violations = []
    for m in NAMED_ENTITY_RE.finditer(xhtml):
        full = m.group(0)
        if full not in ALLOWED_ENTITIES:
            violations.append(f"Illegal entity at pos {m.start()}: {full}")
    return violations


# ─────────────────────────────────────────────
# Markdown → XHTML Converter
# ─────────────────────────────────────────────

def md_to_xhtml(md_text: str) -> str:
    """Convert Markdown text to XHTML body content.
    Uses python-markdown if available, fallback to basic regex.
    """
    if HAS_MARKDOWN:
        extensions = ["extra", "smarty", "sane_lists", "meta"]
        try:
            html = md_lib.markdown(md_text, extensions=extensions)
        except Exception:
            html = md_lib.markdown(md_text)
    else:
        html = _basic_md_to_html(md_text)

    # Post-process: sanitize entities
    html = sanitize_entities(html)

    # Post-process: ensure self-closing tags for XHTML
    html = re.sub(r"<br\s*/?>", "<br/>", html)
    html = re.sub(r"<hr\s*/?>", "<hr/>", html)
    html = re.sub(r'<img([^>]*?)(?<!/)>', r'<img\1/>', html)

    return html


def _basic_md_to_html(md_text: str) -> str:
    """Minimal MD→HTML converter (no external deps)."""
    lines = md_text.split("\n")
    result = []
    in_para = False

    for line in lines:
        stripped = line.strip()

        # Headers
        hm = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if hm:
            if in_para:
                result.append("</p>")
                in_para = False
            level = len(hm.group(1))
            text = xml_escape(hm.group(2))
            result.append(f"<h{level}>{text}</h{level}>")
            continue

        # Horizontal rule
        if re.match(r"^[-*_]{3,}\s*$", stripped):
            if in_para:
                result.append("</p>")
                in_para = False
            result.append("<hr/>")
            continue

        # Empty line = paragraph break
        if not stripped:
            if in_para:
                result.append("</p>")
                in_para = False
            continue

        # Bold + italic
        processed = stripped
        processed = re.sub(r"\*\*\*(.+?)\*\*\*", r"<em><strong>\1</strong></em>", processed)
        processed = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", processed)
        processed = re.sub(r"\*(.+?)\*", r"<em>\1</em>", processed)

        if not in_para:
            result.append("<p>")
            in_para = True
        else:
            result.append("<br/>")
        result.append(processed)

    if in_para:
        result.append("</p>")

    return "\n".join(result)


# ─────────────────────────────────────────────
# XHTML Document Builder
# ─────────────────────────────────────────────

def build_xhtml_doc(title: str, body: str, lang: str = "vi",
                    css_path: str = "../Styles/style.css",
                    epub_type: str = "") -> str:
    """Build a complete XHTML document from body content."""
    epub_attr = f' epub:type="{epub_type}"' if epub_type else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops"
      lang="{lang}" xml:lang="{lang}">
<head>
  <meta charset="UTF-8"/>
  <title>{xml_escape(title)}</title>
  <link rel="stylesheet" type="text/css" href="{css_path}"/>
</head>
<body>
  <section{epub_attr}>
{body}
  </section>
</body>
</html>"""


# ─────────────────────────────────────────────
# Cover Page
# ─────────────────────────────────────────────

def build_cover_xhtml(cover_image_href: str, title: str, lang: str = "vi") -> str:
    """Build cover page XHTML."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops"
      lang="{lang}" xml:lang="{lang}">
<head>
  <meta charset="UTF-8"/>
  <title>Cover</title>
  <style>
    body {{ margin: 0; padding: 0; text-align: center; }}
    img {{ max-width: 100%; max-height: 100%; }}
  </style>
</head>
<body epub:type="cover">
  <img src="{cover_image_href}" alt="{xml_escape(title)} — Cover"/>
</body>
</html>"""


# ─────────────────────────────────────────────
# Title Page
# ─────────────────────────────────────────────

def build_titlepage_xhtml(metadata: dict, lang: str = "vi") -> str:
    """Build title page XHTML."""
    title = xml_escape(metadata.get("title", "Untitled"))
    author = xml_escape(metadata.get("author", "Unknown"))
    publisher = metadata.get("publisher", "")
    pub_html = f'\n    <p class="publisher">{xml_escape(publisher)}</p>' if publisher else ""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops"
      lang="{lang}" xml:lang="{lang}">
<head>
  <meta charset="UTF-8"/>
  <title>{title}</title>
  <link rel="stylesheet" type="text/css" href="../Styles/style.css"/>
</head>
<body epub:type="titlepage">
  <section class="titlepage">
    <h1 class="book-title">{title}</h1>
    <p class="author">{author}</p>{pub_html}
  </section>
</body>
</html>"""


# ─────────────────────────────────────────────
# Copyright Page
# ─────────────────────────────────────────────

def build_copyright_xhtml(metadata: dict, lang: str = "vi") -> str:
    """Build copyright page XHTML."""
    title = xml_escape(metadata.get("title", "Untitled"))
    author = xml_escape(metadata.get("author", "Unknown"))
    year = metadata.get("date", str(datetime.date.today().year))[:4]
    publisher = metadata.get("publisher", "")
    rights = metadata.get("rights", f"© {year} {metadata.get('author', 'Author')}. All rights reserved.")

    pub_line = f"<p>Publisher: {xml_escape(publisher)}</p>" if publisher else ""
    isbn_line = ""
    if metadata.get("isbn"):
        isbn_line = f"<p>ISBN: {xml_escape(metadata['isbn'])}</p>"

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops"
      lang="{lang}" xml:lang="{lang}">
<head>
  <meta charset="UTF-8"/>
  <title>Copyright</title>
  <link rel="stylesheet" type="text/css" href="../Styles/style.css"/>
</head>
<body epub:type="copyright-page">
  <section class="copyright">
    <h2>{title}</h2>
    <p>{xml_escape(rights)}</p>
    <p>Author: {author}</p>
    {pub_line}
    {isbn_line}
  </section>
</body>
</html>"""


# ─────────────────────────────────────────────
# Navigation Document (toc.xhtml)
# ─────────────────────────────────────────────

def build_nav_xhtml(chapters: list, title: str = "Mục Lục",
                    lang: str = "vi") -> str:
    """Build EPUB Navigation Document (toc.xhtml).
    chapters: list of dicts with 'id', 'title', 'href'
    """
    toc_items = []
    for ch in chapters:
        t = xml_escape(ch["title"])
        h = ch["href"]
        toc_items.append(f'      <li><a href="{h}">{t}</a></li>')
    toc_list = "\n".join(toc_items)

    # First chapter href for bodymatter landmark
    first_ch = chapters[0]["href"] if chapters else "Text/chapter-01.xhtml"

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops"
      lang="{lang}" xml:lang="{lang}">
<head>
  <meta charset="UTF-8"/>
  <title>{xml_escape(title)}</title>
  <link rel="stylesheet" type="text/css" href="Styles/style.css"/>
</head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>{xml_escape(title)}</h1>
    <ol>
{toc_list}
    </ol>
  </nav>
  <nav epub:type="landmarks" hidden="">
    <h2>Landmarks</h2>
    <ol>
      <li><a epub:type="bodymatter" href="{first_ch}">Bắt đầu đọc</a></li>
    </ol>
  </nav>
</body>
</html>"""


# ─────────────────────────────────────────────
# NCX (Legacy — backward compat)
# ─────────────────────────────────────────────

def build_ncx(chapters: list, metadata: dict) -> str:
    """Build toc.ncx for EPUB 2 backward compatibility.
    chapters: list of dicts with 'id', 'title', 'href'
    """
    uid = metadata.get("identifier", str(uuid.uuid4()))
    title = xml_escape(metadata.get("title", "Untitled"))

    nav_points = []
    for i, ch in enumerate(chapters, 1):
        t = xml_escape(ch["title"])
        h = ch["href"]
        nav_points.append(f"""    <navPoint id="np-{i}" playOrder="{i}">
      <navLabel><text>{t}</text></navLabel>
      <content src="{h}"/>
    </navPoint>""")

    nav_map = "\n".join(nav_points)
    depth = "1"  # flat chapter list

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="{xml_escape(uid)}"/>
    <meta name="dtb:depth" content="{depth}"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>{title}</text></docTitle>
  <navMap>
{nav_map}
  </navMap>
</ncx>"""


# ─────────────────────────────────────────────
# Package Document (content.opf)
# ─────────────────────────────────────────────

def build_opf(metadata: dict, manifest_items: list, spine_items: list,
              has_ncx: bool = True, accessibility: bool = True) -> str:
    """Build EPUB Package Document (content.opf).
    
    manifest_items: list of dicts with 'id', 'href', 'media_type', 'properties' (optional)
    spine_items: list of item ids in reading order
    """
    uid = metadata.get("identifier", str(uuid.uuid4()))
    title = xml_escape(metadata.get("title", "Untitled"))
    author = xml_escape(metadata.get("author", "Unknown"))
    lang = metadata.get("language", "vi")
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    modified = metadata.get("modified", now)

    # Dublin Core metadata
    meta_lines = [
        f'    <dc:identifier id="uid">{xml_escape(uid)}</dc:identifier>',
        f'    <dc:title>{title}</dc:title>',
        f'    <dc:language>{xml_escape(lang)}</dc:language>',
        f'    <dc:creator>{author}</dc:creator>',
        f'    <meta property="dcterms:modified">{modified}</meta>',
    ]

    # Optional metadata
    if metadata.get("publisher"):
        meta_lines.append(f'    <dc:publisher>{xml_escape(metadata["publisher"])}</dc:publisher>')
    if metadata.get("description"):
        meta_lines.append(f'    <dc:description>{xml_escape(metadata["description"])}</dc:description>')
    if metadata.get("date"):
        meta_lines.append(f'    <dc:date>{xml_escape(metadata["date"])}</dc:date>')
    if metadata.get("rights"):
        meta_lines.append(f'    <dc:rights>{xml_escape(metadata["rights"])}</dc:rights>')
    if metadata.get("isbn"):
        meta_lines.append(f'    <dc:identifier id="isbn">{xml_escape(metadata["isbn"])}</dc:identifier>')

    # Accessibility metadata (EPUB Accessibility 1.1)
    if accessibility:
        a11y = [
            '<meta property="schema:accessMode">textual</meta>',
            '<meta property="schema:accessModeSufficient">textual</meta>',
            '<meta property="schema:accessibilityFeature">structuredNavigation</meta>',
            '<meta property="schema:accessibilityFeature">readingOrder</meta>',
            '<meta property="schema:accessibilityFeature">alternativeText</meta>',
            '<meta property="schema:accessibilityHazard">none</meta>',
            '<meta property="schema:accessibilitySummary">This publication conforms to EPUB Accessibility 1.1.</meta>',
        ]
        for a in a11y:
            meta_lines.append(f"    {a}")

    meta_xml = "\n".join(meta_lines)

    # Manifest
    manifest_lines = []
    for item in manifest_items:
        props = f' properties="{item["properties"]}"' if item.get("properties") else ""
        manifest_lines.append(
            f'    <item id="{item["id"]}" href="{item["href"]}" '
            f'media-type="{item["media_type"]}"{props}/>'
        )
    manifest_xml = "\n".join(manifest_lines)

    # Spine
    toc_attr = ' toc="ncx"' if has_ncx else ""
    spine_lines = []
    for sid in spine_items:
        spine_lines.append(f'    <itemref idref="{sid}"/>')
    spine_xml = "\n".join(spine_lines)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf"
         unique-identifier="uid"
         version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
{meta_xml}
  </metadata>
  <manifest>
{manifest_xml}
  </manifest>
  <spine{toc_attr}>
{spine_xml}
  </spine>
</package>"""


# ─────────────────────────────────────────────
# EPUB Packager (ZIP)
# ─────────────────────────────────────────────

class EpubForge:
    """Main EPUB 3.3 builder."""

    def __init__(self, config_path: str = None, config: dict = None):
        self.config = config or {}
        self.config_dir = Path(".")
        self.errors = []
        self.warnings = []
        self.files = {}  # path_in_zip → content (bytes or str)
        self.manifest_items = []
        self.spine_items = []
        self.chapters_meta = []  # for nav/ncx

        if config_path:
            self.load_config(config_path)

    def load_config(self, config_path: str):
        """Load book config from YAML or JSON file."""
        path = Path(config_path)
        self.config_dir = path.parent

        if not path.exists():
            self.errors.append(f"Config file not found: {config_path}")
            return

        content = path.read_text(encoding="utf-8")

        if path.suffix in (".yaml", ".yml"):
            if not HAS_YAML:
                self.errors.append("PyYAML not installed. Use JSON config or: pip install pyyaml")
                return
            self.config = yaml.safe_load(content)
        elif path.suffix == ".json":
            self.config = json.loads(content)
        else:
            # Try YAML first, then JSON
            try:
                if HAS_YAML:
                    self.config = yaml.safe_load(content)
                else:
                    self.config = json.loads(content)
            except Exception:
                self.errors.append(f"Cannot parse config: {config_path}")
                return

    def _resolve_path(self, rel_path: str) -> Path:
        """Resolve a path relative to config directory."""
        p = Path(rel_path)
        if p.is_absolute():
            return p
        return self.config_dir / p

    def build(self, output_path: str = None) -> str:
        """Build EPUB from loaded config. Returns output path."""
        if self.errors:
            return None

        meta = self.config.get("metadata", {})
        if not meta.get("title"):
            self.errors.append("metadata.title is required")
            return None

        # Generate identifier if not provided
        if not meta.get("identifier"):
            meta["identifier"] = f"urn:uuid:{uuid.uuid4()}"

        lang = meta.get("language", "vi")
        options = self.config.get("options", {})
        gen_ncx = options.get("ncx", True)
        gen_a11y = options.get("accessibility", True)

        # ── Step 1: Cover ──
        cover_path = self.config.get("cover")
        cover_in_zip = None
        if cover_path:
            cover_file = self._resolve_path(cover_path)
            if not cover_file.exists():
                self.errors.append(f"Cover image not found: {cover_path}")
                return None
            ext = cover_file.suffix.lower()
            if ext not in COVER_MEDIA_TYPES:
                self.errors.append(f"Cover must be PNG or JPG, got: {ext}")
                return None
            cover_in_zip = f"OEBPS/Images/cover{ext}"
            self.files[cover_in_zip] = cover_file.read_bytes()
            self.manifest_items.append({
                "id": "cover-image",
                "href": f"Images/cover{ext}",
                "media_type": COVER_MEDIA_TYPES[ext],
                "properties": "cover-image",
            })
            # Cover XHTML
            cover_xhtml = build_cover_xhtml(f"../Images/cover{ext}", meta["title"], lang)
            self.files["OEBPS/Text/cover.xhtml"] = cover_xhtml
            self.manifest_items.append({
                "id": "cover",
                "href": "Text/cover.xhtml",
                "media_type": "application/xhtml+xml",
            })
            self.spine_items.append("cover")

        # ── Step 2: Title Page ──
        tp_xhtml = build_titlepage_xhtml(meta, lang)
        self.files["OEBPS/Text/titlepage.xhtml"] = tp_xhtml
        self.manifest_items.append({
            "id": "titlepage",
            "href": "Text/titlepage.xhtml",
            "media_type": "application/xhtml+xml",
        })
        self.spine_items.append("titlepage")

        # ── Step 3: Copyright Page ──
        if options.get("copyright", True):
            cp_xhtml = build_copyright_xhtml(meta, lang)
            self.files["OEBPS/Text/copyright.xhtml"] = cp_xhtml
            self.manifest_items.append({
                "id": "copyright",
                "href": "Text/copyright.xhtml",
                "media_type": "application/xhtml+xml",
            })
            self.spine_items.append("copyright")

        # ── Step 4: Frontmatter ──
        for i, fm in enumerate(self.config.get("frontmatter", []), 1):
            fm_id = f"frontmatter-{i}"
            fm_title = fm.get("title", fm.get("type", f"Frontmatter {i}"))
            if fm.get("file"):
                fm_file = self._resolve_path(fm["file"])
                if fm_file.exists():
                    fm_body = md_to_xhtml(fm_file.read_text(encoding="utf-8"))
                else:
                    self.warnings.append(f"Frontmatter file not found: {fm['file']}")
                    continue
            elif fm.get("content"):
                fm_body = f"<p>{sanitize_entities(xml_escape(fm['content']))}</p>"
            else:
                continue

            fm_xhtml = build_xhtml_doc(fm_title, fm_body, lang,
                                        epub_type=fm.get("type", ""))
            self.files[f"OEBPS/Text/{fm_id}.xhtml"] = fm_xhtml
            self.manifest_items.append({
                "id": fm_id,
                "href": f"Text/{fm_id}.xhtml",
                "media_type": "application/xhtml+xml",
            })
            self.spine_items.append(fm_id)

        # ── Step 5: Chapters ──
        chapters_cfg = self.config.get("chapters", [])
        if not chapters_cfg:
            self.errors.append("No chapters defined in config")
            return None

        for i, ch_cfg in enumerate(chapters_cfg, 1):
            ch_id = f"chapter-{i:03d}"
            ch_title = ch_cfg.get("title", f"Chapter {i}")
            ch_file = self._resolve_path(ch_cfg.get("file", ""))

            if not ch_file.exists():
                self.errors.append(f"Chapter file not found: {ch_cfg.get('file', '?')}")
                return None

            md_text = ch_file.read_text(encoding="utf-8")
            ch_body = md_to_xhtml(md_text)

            # Check if MD has its own heading, if not add one
            if not re.search(r"<h[1-6]", ch_body):
                ch_body = f"    <h1>{xml_escape(ch_title)}</h1>\n{ch_body}"

            ch_xhtml = build_xhtml_doc(ch_title, ch_body, lang,
                                        epub_type="chapter")
            ch_filename = f"{ch_id}.xhtml"
            self.files[f"OEBPS/Text/{ch_filename}"] = ch_xhtml
            self.manifest_items.append({
                "id": ch_id,
                "href": f"Text/{ch_filename}",
                "media_type": "application/xhtml+xml",
            })
            self.spine_items.append(ch_id)
            self.chapters_meta.append({
                "id": ch_id,
                "title": ch_title,
                "href": f"Text/{ch_filename}",
            })

        # ── Step 6: Backmatter ──
        for i, bm in enumerate(self.config.get("backmatter", []), 1):
            bm_id = f"backmatter-{i}"
            bm_title = bm.get("title", bm.get("type", f"Backmatter {i}"))
            if bm.get("file"):
                bm_file = self._resolve_path(bm["file"])
                if bm_file.exists():
                    bm_body = md_to_xhtml(bm_file.read_text(encoding="utf-8"))
                else:
                    self.warnings.append(f"Backmatter file not found: {bm['file']}")
                    continue
            elif bm.get("content"):
                bm_body = f"<p>{sanitize_entities(xml_escape(bm['content']))}</p>"
            else:
                continue

            bm_xhtml = build_xhtml_doc(bm_title, bm_body, lang,
                                        epub_type=bm.get("type", ""))
            self.files[f"OEBPS/Text/{bm_id}.xhtml"] = bm_xhtml
            self.manifest_items.append({
                "id": bm_id,
                "href": f"Text/{bm_id}.xhtml",
                "media_type": "application/xhtml+xml",
            })
            self.spine_items.append(bm_id)

        # ── Step 7: CSS ──
        css_path = self.config.get("css")
        if css_path:
            css_file = self._resolve_path(css_path)
            if css_file.exists():
                self.files["OEBPS/Styles/style.css"] = css_file.read_text(encoding="utf-8")
            else:
                self.warnings.append(f"Custom CSS not found: {css_path}, using default")
                self.files["OEBPS/Styles/style.css"] = _default_css()
        else:
            self.files["OEBPS/Styles/style.css"] = _default_css()

        self.manifest_items.append({
            "id": "css",
            "href": "Styles/style.css",
            "media_type": "text/css",
        })

        # ── Step 8: Additional images ──
        images_dir = self.config.get("images_dir")
        if images_dir:
            img_path = self._resolve_path(images_dir)
            if img_path.is_dir():
                for img_file in sorted(img_path.iterdir()):
                    ext = img_file.suffix.lower()
                    if ext in IMAGE_MEDIA_TYPES:
                        img_id = f"img-{img_file.stem}"
                        self.files[f"OEBPS/Images/{img_file.name}"] = img_file.read_bytes()
                        self.manifest_items.append({
                            "id": img_id,
                            "href": f"Images/{img_file.name}",
                            "media_type": IMAGE_MEDIA_TYPES[ext],
                        })

        # ── Step 9: Fonts ──
        fonts_dir = self.config.get("fonts_dir")
        if fonts_dir:
            fnt_path = self._resolve_path(fonts_dir)
            if fnt_path.is_dir():
                for fnt_file in sorted(fnt_path.iterdir()):
                    ext = fnt_file.suffix.lower()
                    if ext in FONT_MEDIA_TYPES:
                        fnt_id = f"font-{fnt_file.stem}"
                        self.files[f"OEBPS/Fonts/{fnt_file.name}"] = fnt_file.read_bytes()
                        self.manifest_items.append({
                            "id": fnt_id,
                            "href": f"Fonts/{fnt_file.name}",
                            "media_type": FONT_MEDIA_TYPES[ext],
                        })

        # ── Step 10: Navigation Document ──
        nav_xhtml = build_nav_xhtml(self.chapters_meta, "Mục Lục", lang)
        self.files["OEBPS/toc.xhtml"] = nav_xhtml
        self.manifest_items.append({
            "id": "nav",
            "href": "toc.xhtml",
            "media_type": "application/xhtml+xml",
            "properties": "nav",
        })

        # ── Step 11: NCX ──
        if gen_ncx:
            ncx_xml = build_ncx(self.chapters_meta, meta)
            self.files["OEBPS/toc.ncx"] = ncx_xml
            self.manifest_items.append({
                "id": "ncx",
                "href": "toc.ncx",
                "media_type": "application/x-dtbncx+xml",
            })

        # ── Step 12: Package Document ──
        opf_xml = build_opf(meta, self.manifest_items, self.spine_items,
                            has_ncx=gen_ncx, accessibility=gen_a11y)
        self.files["OEBPS/content.opf"] = opf_xml

        # ── Step 13: Container ──
        container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""
        self.files["META-INF/container.xml"] = container_xml

        # ── Step 14: Package ZIP ──
        if not output_path:
            safe_title = re.sub(r"[^\w\-]", "_", meta.get("title", "book"))
            output_path = str(self.config_dir / f"{safe_title}.epub")

        self._write_epub(output_path)

        if self.errors:
            return None

        # ── Step 15: Validate ──
        if options.get("validate", True):
            self.validate(output_path)

        return output_path

    def _write_epub(self, output_path: str):
        """Write ZIP archive with correct mimetype positioning."""
        try:
            with zipfile.ZipFile(output_path, "w") as zf:
                # 1. mimetype MUST be first, STORED, no extra field
                mi = zipfile.ZipInfo("mimetype")
                mi.compress_type = zipfile.ZIP_STORED
                mi.extra = b""
                zf.writestr(mi, EPUB_MIMETYPE)

                # 2. All other files — DEFLATED
                for path_in_zip, content in sorted(self.files.items()):
                    info = zipfile.ZipInfo(path_in_zip)
                    info.compress_type = zipfile.ZIP_DEFLATED

                    if isinstance(content, bytes):
                        zf.writestr(info, content)
                    else:
                        zf.writestr(info, content.encode("utf-8"))

        except Exception as e:
            self.errors.append(f"ZIP write error: {e}")

    def validate(self, epub_path: str) -> dict:
        """Run EPUBCheck on the built EPUB. Returns result dict."""
        result = {"fatals": 0, "errors": 0, "warnings": 0, "messages": []}

        # Try epubcheck
        epubcheck_cmd = None
        for cmd in ["epubcheck", "/usr/local/bin/epubcheck"]:
            try:
                subprocess.run([cmd, "--version"], capture_output=True, timeout=10)
                epubcheck_cmd = cmd
                break
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue

        if not epubcheck_cmd:
            # Try java -jar
            jar_paths = [
                "/usr/local/lib/epubcheck/epubcheck.jar",
                "/opt/epubcheck/epubcheck.jar",
                os.path.expanduser("~/epubcheck/epubcheck.jar"),
            ]
            for jar in jar_paths:
                if os.path.exists(jar):
                    epubcheck_cmd = f"java -jar {jar}"
                    break

        if not epubcheck_cmd:
            self.warnings.append("EPUBCheck not found — skipping validation")
            return result

        try:
            cmd_parts = epubcheck_cmd.split() + [epub_path]
            proc = subprocess.run(
                cmd_parts,
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = proc.stdout + proc.stderr

            # Parse EPUBCheck output
            for line in output.splitlines():
                if "FATAL" in line.upper():
                    result["fatals"] += 1
                    result["messages"].append(line.strip())
                elif "ERROR" in line.upper() and "error" not in line.lower().split(":")[-1]:
                    result["errors"] += 1
                    result["messages"].append(line.strip())
                elif "WARNING" in line.upper():
                    result["warnings"] += 1
                    result["messages"].append(line.strip())

            # Better parsing from summary line
            summary_match = re.search(
                r"(\d+)\s*fatal.*?(\d+)\s*error.*?(\d+)\s*warn",
                output, re.IGNORECASE
            )
            if summary_match:
                result["fatals"] = int(summary_match.group(1))
                result["errors"] = int(summary_match.group(2))
                result["warnings"] = int(summary_match.group(3))

            result["raw_output"] = output

        except subprocess.TimeoutExpired:
            self.warnings.append("EPUBCheck timed out (120s)")
        except Exception as e:
            self.warnings.append(f"EPUBCheck error: {e}")

        return result

    def info(self):
        """Print EPUB structure info without building."""
        meta = self.config.get("metadata", {})
        chapters = self.config.get("chapters", [])

        print(f"📖 {meta.get('title', 'Untitled')}")
        print(f"✍️  {meta.get('author', 'Unknown')}")
        print(f"🌐 {meta.get('language', 'vi')}")
        print(f"📄 {len(chapters)} chapters")
        print(f"🖼️  Cover: {self.config.get('cover', 'None')}")
        print(f"📐 Frontmatter: {len(self.config.get('frontmatter', []))}")
        print(f"📐 Backmatter: {len(self.config.get('backmatter', []))}")


# ─────────────────────────────────────────────
# Default CSS
# ─────────────────────────────────────────────

def _default_css() -> str:
    """Default CSS optimized for Vietnamese text."""
    return """/* epub-forge default stylesheet — Vietnamese optimized */
@charset "UTF-8";

/* ── Base ── */
body {
  font-family: "Noto Serif", "Times New Roman", Georgia, serif;
  font-size: 1em;
  line-height: 1.75;
  margin: 1em;
  padding: 0;
  color: #1a1a1a;
  background-color: #ffffff;
  text-align: justify;
  -webkit-hyphens: auto;
  hyphens: auto;
}

/* ── Headings ── */
h1, h2, h3, h4, h5, h6 {
  font-family: "Noto Sans", "Helvetica Neue", Arial, sans-serif;
  text-align: left;
  margin-top: 1.5em;
  margin-bottom: 0.5em;
  line-height: 1.3;
  color: #2c2c2c;
}
h1 { font-size: 1.8em; margin-top: 2em; }
h2 { font-size: 1.4em; }
h3 { font-size: 1.2em; }

/* ── Paragraphs ── */
p {
  margin: 0;
  text-indent: 1.5em;
}
p + p {
  margin-top: 0.3em;
}
p:first-child,
h1 + p, h2 + p, h3 + p {
  text-indent: 0;
}

/* ── Links ── */
a {
  color: #2563eb;
  text-decoration: none;
}
a:hover {
  text-decoration: underline;
}

/* ── Block elements ── */
blockquote {
  margin: 1em 2em;
  padding: 0.5em 1em;
  border-left: 3px solid #c9a96e;
  font-style: italic;
  color: #555;
}

pre, code {
  font-family: "Courier New", monospace;
  font-size: 0.9em;
}
pre {
  background: #f5f5f5;
  padding: 1em;
  overflow-x: auto;
  border-radius: 4px;
}

/* ── Images ── */
img {
  max-width: 100%;
  height: auto;
  display: block;
  margin: 1em auto;
}

/* ── Tables ── */
table {
  border-collapse: collapse;
  margin: 1em auto;
  width: 100%;
}
th, td {
  border: 1px solid #ddd;
  padding: 0.5em;
  text-align: left;
}
th {
  background: #f0f0f0;
  font-weight: bold;
}

/* ── Lists ── */
ul, ol {
  margin: 0.5em 0;
  padding-left: 2em;
}
li {
  margin-bottom: 0.3em;
}

/* ── Separator ── */
hr {
  border: none;
  text-align: center;
  margin: 2em 0;
}
hr::after {
  content: "♦ ♦ ♦";
  color: #c9a96e;
  font-size: 0.8em;
  letter-spacing: 0.5em;
}

/* ── Special pages ── */
.titlepage {
  text-align: center;
  margin-top: 30%;
}
.titlepage .book-title {
  font-size: 2.2em;
  margin-bottom: 0.5em;
}
.titlepage .author {
  font-size: 1.4em;
  color: #555;
}
.titlepage .publisher {
  font-size: 1em;
  color: #888;
  margin-top: 2em;
}

.copyright {
  font-size: 0.85em;
  color: #666;
  margin-top: 30%;
}

/* ── Cover ── */
[epub|type="cover"] {
  text-align: center;
  padding: 0;
  margin: 0;
}
[epub|type="cover"] img {
  max-width: 100%;
  max-height: 100%;
}

/* ── Navigation ── */
nav[epub|type="toc"] ol {
  list-style-type: none;
  padding-left: 0;
}
nav[epub|type="toc"] li {
  margin: 0.5em 0;
}
nav[epub|type="toc"] a {
  color: #333;
  text-decoration: none;
}
"""


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="epub-forge",
        description="EPUB 3.3 W3C Forge — Build standard-compliant EPUB from Markdown",
    )
    sub = parser.add_subparsers(dest="command", help="Command")

    # build
    p_build = sub.add_parser("build", help="Build EPUB from config")
    p_build.add_argument("--config", "-c", required=True, help="Book config (YAML/JSON)")
    p_build.add_argument("--output", "-o", help="Output .epub path")

    # validate
    p_val = sub.add_parser("validate", help="Validate an existing EPUB")
    p_val.add_argument("--epub", "-e", required=True, help="EPUB file to validate")

    # info
    p_info = sub.add_parser("info", help="Show book structure from config")
    p_info.add_argument("--config", "-c", required=True, help="Book config (YAML/JSON)")

    # version
    sub.add_parser("version", help="Show version")

    args = parser.parse_args()

    if args.command == "version":
        print(f"epub-forge v{VERSION} — EPUB 3.3 W3C Forge Engine")
        return 0

    if args.command == "info":
        forge = EpubForge(config_path=args.config)
        if forge.errors:
            for e in forge.errors:
                print(f"❌ {e}", file=sys.stderr)
            return 3
        forge.info()
        return 0

    if args.command == "validate":
        forge = EpubForge()
        result = forge.validate(args.epub)
        print(f"EPUBCheck: {result['fatals']} fatal / {result['errors']} error / {result['warnings']} warning")
        if result.get("raw_output"):
            print(result["raw_output"])
        return 1 if (result["fatals"] + result["errors"]) > 0 else 0

    if args.command == "build":
        print(f"📦 epub-forge v{VERSION} — Building EPUB 3.3 W3C")
        print(f"   Config: {args.config}")

        forge = EpubForge(config_path=args.config)

        if forge.errors:
            for e in forge.errors:
                print(f"❌ {e}", file=sys.stderr)
            return 3

        output = forge.build(output_path=args.output)

        if forge.warnings:
            for w in forge.warnings:
                print(f"⚠️  {w}")

        if forge.errors:
            for e in forge.errors:
                print(f"❌ {e}", file=sys.stderr)
            return 2

        if output:
            size = os.path.getsize(output)
            print(f"✅ EPUB built: {output} ({size:,} bytes)")
            return 0
        else:
            print("❌ Build failed", file=sys.stderr)
            return 2

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
