#!/usr/bin/env python3
"""Extract epub text to JSON files for the dashboard reader.

Parses epub ZIP directly for best chapter title extraction:
1. container.xml -> OPF path
2. OPF -> spine order, manifest, NCX/nav references
3. toc.ncx or nav.xhtml -> actual chapter labels
4. HTML h1/h2 fallback for unlabeled chapters
5. Front matter detection and marking
6. Merging of tiny unlabeled sections
"""

import json
import os
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import unquote, urljoin
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup
import warnings
warnings.filterwarnings("ignore")

BOOKS_DIR = Path.home() / "agent" / "data" / "skills" / "library" / "books"
OUTPUT_DIR = Path.home() / "agent" / "data" / "skills" / "library" / "text"

# Namespaces
NS_CONTAINER = "urn:oasis:names:tc:opendocument:xmlns:container"
NS_OPF = "http://www.idpf.org/2007/opf"
NS_DC = "http://purl.org/dc/elements/1.1/"
NS_NCX = "http://www.daisy.org/z3986/2005/ncx/"
NS_XHTML = "http://www.w3.org/1999/xhtml"
NS_EPUB = "http://www.idpf.org/2007/ops"

FRONT_MATTER_KEYWORDS = [
    "cover", "copyright", "title page", "titlepage", "dedication",
    "also by", "about the author", "about the publisher", "epigraph",
    "frontmatter", "front matter", "halftitle", "half title",
    "other books", "books by", "praise for", "advance praise",
    "table of contents", "contents", "toc",
]

FRONT_MATTER_HTML_KEYWORDS = [
    "copyright", "isbn", "published by", "all rights reserved",
    "dedication", "also by", "other books by", "praise for",
    "advance praise", "library of congress", "cataloging-in-publication",
]


def sanitize_filename(name: str) -> str:
    """Convert epub filename to a safe JSON filename."""
    name = Path(name).stem
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'\s+', '_', name.strip())
    return name[:100]


def is_front_matter_label(label: str) -> bool:
    """Check if a TOC label indicates front matter."""
    lower = label.lower().strip()
    for kw in FRONT_MATTER_KEYWORDS:
        if kw in lower:
            return True
    return False


def is_front_matter_html(text: str) -> bool:
    """Check if short HTML content looks like front matter."""
    if len(text) > 500:
        return False
    lower = text.lower()
    matches = sum(1 for kw in FRONT_MATTER_HTML_KEYWORDS if kw in lower)
    return matches >= 1


def is_generic_chapter_label(label: str) -> bool:
    """Check if a label is just 'Chapter N' or similar generic."""
    return bool(re.match(r'^(chapter\s*\d*|part\s*\d*|section\s*\d*)$', label.strip(), re.IGNORECASE))


def clean_html(html_content: str) -> str:
    """Clean HTML to keep only readable content."""
    soup = BeautifulSoup(html_content, 'lxml')

    for tag in soup.find_all(['script', 'style', 'img', 'svg', 'link', 'meta']):
        tag.decompose()

    body = soup.find('body')
    if body:
        soup = body

    allowed = {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'br', 'em', 'strong',
               'i', 'b', 'blockquote', 'ul', 'ol', 'li', 'div', 'span', 'a', 'sup', 'sub'}

    for tag in soup.find_all(True):
        if tag.name not in allowed:
            tag.unwrap()
        else:
            attrs = {}
            if tag.name == 'a' and tag.get('href'):
                attrs['href'] = tag['href']
            tag.attrs = attrs

    result = str(soup)
    result = re.sub(r'\n\s*\n\s*\n', '\n\n', result)
    return result.strip()


def extract_headings(html_content: str) -> list[str]:
    """Extract h1/h2/h3 text from HTML content."""
    soup = BeautifulSoup(html_content, 'lxml')
    headings = []
    for tag in ['h1', 'h2', 'h3']:
        for el in soup.find_all(tag):
            text = el.get_text(strip=True)
            if text and len(text) < 300:
                headings.append(text)
    return headings


def get_text_length(html_content: str) -> int:
    """Get plain text length of HTML."""
    soup = BeautifulSoup(html_content, 'lxml')
    return len(soup.get_text(strip=True))


def normalize_href(href: str) -> str:
    """Normalize a TOC href to just the filename (no fragment, no path prefix)."""
    # Remove fragment
    href = href.split('#')[0]
    # Decode percent-encoding
    href = unquote(href)
    # Get just the filename
    href = href.rsplit('/', 1)[-1] if '/' in href else href
    return href


def parse_container(zf: zipfile.ZipFile) -> str | None:
    """Parse META-INF/container.xml to find OPF path."""
    try:
        xml = zf.read("META-INF/container.xml").decode("utf-8")
    except KeyError:
        return None
    root = ET.fromstring(xml)
    for rf in root.iter(f"{{{NS_CONTAINER}}}rootfile"):
        path = rf.get("full-path")
        if path and path.endswith(".opf"):
            return path
    # Fallback: search for .opf file
    for name in zf.namelist():
        if name.endswith(".opf"):
            return name
    return None


def parse_opf(zf: zipfile.ZipFile, opf_path: str):
    """Parse the OPF file. Returns (metadata, manifest, spine, ncx_id, nav_id, opf_dir)."""
    xml = zf.read(opf_path).decode("utf-8")
    root = ET.fromstring(xml)
    opf_dir = opf_path.rsplit('/', 1)[0] + '/' if '/' in opf_path else ''

    # Metadata
    title = ""
    author = ""
    meta_el = root.find(f"{{{NS_OPF}}}metadata")
    if meta_el is not None:
        t = meta_el.find(f"{{{NS_DC}}}title")
        if t is not None and t.text:
            title = t.text.strip()
        a = meta_el.find(f"{{{NS_DC}}}creator")
        if a is not None and a.text:
            author = a.text.strip()

    # Manifest: id -> {href, media_type, properties}
    manifest = {}
    manifest_el = root.find(f"{{{NS_OPF}}}manifest")
    ncx_id = None
    nav_id = None
    if manifest_el is not None:
        for item in manifest_el.findall(f"{{{NS_OPF}}}item"):
            item_id = item.get("id", "")
            href = item.get("href", "")
            media_type = item.get("media-type", "")
            properties = item.get("properties", "")
            manifest[item_id] = {
                "href": href,
                "media_type": media_type,
                "properties": properties,
                "full_path": opf_dir + href,
            }
            if media_type == "application/x-dtbncx+xml":
                ncx_id = item_id
            if "nav" in properties.split():
                nav_id = item_id

    # Spine: ordered list of manifest IDs
    spine = []
    spine_el = root.find(f"{{{NS_OPF}}}spine")
    if spine_el is not None:
        # Also check for toc attribute pointing to NCX
        if ncx_id is None:
            toc_attr = spine_el.get("toc")
            if toc_attr and toc_attr in manifest:
                ncx_id = toc_attr
        for itemref in spine_el.findall(f"{{{NS_OPF}}}itemref"):
            idref = itemref.get("idref", "")
            if idref in manifest:
                spine.append(idref)

    return {
        "title": title,
        "author": author,
        "manifest": manifest,
        "spine": spine,
        "ncx_id": ncx_id,
        "nav_id": nav_id,
        "opf_dir": opf_dir,
    }


def parse_ncx(zf: zipfile.ZipFile, ncx_path: str) -> list[dict]:
    """Parse toc.ncx and return list of {label, href_file, href_full}."""
    try:
        xml = zf.read(ncx_path).decode("utf-8")
    except KeyError:
        return []
    root = ET.fromstring(xml)
    entries = []
    for np in root.iter(f"{{{NS_NCX}}}navPoint"):
        label_el = np.find(f"{{{NS_NCX}}}navLabel/{{{NS_NCX}}}text")
        content_el = np.find(f"{{{NS_NCX}}}content")
        if label_el is not None and content_el is not None:
            label = (label_el.text or "").strip()
            src = content_el.get("src", "")
            entries.append({
                "label": label,
                "href_file": normalize_href(src),
                "href_full": src,
            })
    return entries


def parse_nav(zf: zipfile.ZipFile, nav_path: str) -> list[dict]:
    """Parse EPUB3 nav document and return list of {label, href_file}."""
    try:
        html = zf.read(nav_path).decode("utf-8")
    except KeyError:
        return []
    soup = BeautifulSoup(html, 'lxml')
    # Find the TOC nav element
    toc_nav = soup.find('nav', attrs={'epub:type': 'toc'}) or soup.find('nav')
    if not toc_nav:
        return []
    entries = []
    for a in toc_nav.find_all('a'):
        href = a.get('href', '')
        label = a.get_text(strip=True)
        if href and label:
            entries.append({
                "label": label,
                "href_file": normalize_href(href),
                "href_full": href,
            })
    return entries


def extract_epub(epub_path: Path) -> dict | None:
    """Extract book content from epub with proper chapter titles."""
    try:
        zf = zipfile.ZipFile(str(epub_path))
    except Exception as e:
        print(f"  ERROR opening {epub_path.name}: {e}")
        return None

    # 1. Find OPF
    opf_path = parse_container(zf)
    if not opf_path:
        print(f"  ERROR: No OPF found in {epub_path.name}")
        return None

    # 2. Parse OPF
    try:
        opf = parse_opf(zf, opf_path)
    except Exception as e:
        print(f"  ERROR parsing OPF in {epub_path.name}: {e}")
        return None

    title = opf["title"] or epub_path.stem
    author = opf["author"]
    manifest = opf["manifest"]
    spine = opf["spine"]

    # 3. Parse TOC (NCX first, then nav)
    toc_entries = []
    if opf["ncx_id"] and opf["ncx_id"] in manifest:
        ncx_path = manifest[opf["ncx_id"]]["full_path"]
        toc_entries = parse_ncx(zf, ncx_path)

    # If NCX entries are all generic ("Chapter N"), try nav too
    ncx_all_generic = all(is_generic_chapter_label(e["label"]) for e in toc_entries) if toc_entries else True

    nav_entries = []
    if opf["nav_id"] and opf["nav_id"] in manifest:
        nav_path = manifest[opf["nav_id"]]["full_path"]
        nav_entries = parse_nav(zf, nav_path)

    nav_all_generic = all(is_generic_chapter_label(e["label"]) for e in nav_entries) if nav_entries else True

    # Use whichever has better labels; prefer NCX if both are good
    if ncx_all_generic and not nav_all_generic:
        toc_entries = nav_entries
    elif not toc_entries and nav_entries:
        toc_entries = nav_entries

    # 4. Build a mapping: filename -> TOC label
    # A file can have multiple TOC entries (fragments); take the first one
    file_to_toc = {}
    for entry in toc_entries:
        fname = entry["href_file"]
        if fname not in file_to_toc:
            file_to_toc[fname] = entry["label"]

    # 5. Process spine items
    raw_chapters = []
    for item_id in spine:
        item = manifest[item_id]
        if item["media_type"] not in ("application/xhtml+xml", "text/html"):
            continue

        full_path = item["full_path"]
        try:
            content = zf.read(full_path).decode("utf-8", errors="replace")
        except KeyError:
            continue

        text_len = get_text_length(content)
        html = clean_html(content)
        if not html.strip():
            continue

        # Determine filename for TOC lookup
        fname = item["href"].rsplit('/', 1)[-1] if '/' in item["href"] else item["href"]

        # Get title from TOC
        toc_label = file_to_toc.get(fname, "")

        # Get headings from HTML
        headings = extract_headings(content)

        # Determine best chapter title
        chapter_title = ""

        if toc_label and not is_generic_chapter_label(toc_label):
            # Good TOC label
            chapter_title = toc_label
        elif headings:
            # Use first heading, possibly combining with TOC label
            if toc_label and is_generic_chapter_label(toc_label):
                # e.g. "Chapter 4" from TOC + "General paths to AI" from h2
                # Combine: "Chapter 4: General paths to AI"
                first_heading = headings[0]
                if first_heading.lower() != toc_label.lower():
                    chapter_title = f"{toc_label}: {first_heading}"
                else:
                    chapter_title = toc_label
            else:
                chapter_title = headings[0]
        elif toc_label:
            chapter_title = toc_label
        # else: will be assigned later

        # Detect front matter
        is_fm = False
        if toc_label and is_front_matter_label(toc_label):
            is_fm = True
        elif text_len < 500 and is_front_matter_html(BeautifulSoup(content, 'lxml').get_text()):
            is_fm = True

        raw_chapters.append({
            "title": chapter_title,
            "html": html,
            "text_len": text_len,
            "is_front_matter": is_fm,
            "has_toc_entry": bool(toc_label),
        })

    # 6. Merge tiny sections and assign fallback titles
    chapters = []
    chapter_num = 0

    for i, ch in enumerate(raw_chapters):
        # Merge tiny sections without TOC entries into previous chapter
        if (not ch["has_toc_entry"]
                and ch["text_len"] < 200
                and not ch["title"]
                and chapters
                and not ch["is_front_matter"]):
            # Merge into previous
            chapters[-1]["html"] += "\n" + ch["html"]
            continue

        # Assign fallback title if needed
        if not ch["title"]:
            if ch["is_front_matter"]:
                ch["title"] = "Front Matter"
            elif ch["text_len"] < 200 and is_front_matter_html(
                    BeautifulSoup(ch["html"], 'lxml').get_text()):
                ch["is_front_matter"] = True
                ch["title"] = "Front Matter"
            else:
                chapter_num += 1
                ch["title"] = f"Chapter {chapter_num}"
        else:
            # Count non-front-matter chapters for numbering
            if not ch["is_front_matter"] and not ch["title"].startswith("—"):
                chapter_num += 1

        # Mark front matter with dash prefix
        if ch["is_front_matter"] and not ch["title"].startswith("—"):
            ch["title"] = f"— {ch['title']}"

        chapters.append({
            "title": ch["title"],
            "html": ch["html"],
        })

    if not chapters:
        print(f"  WARNING: No chapters extracted from {epub_path.name}")
        return None

    zf.close()
    return {
        "title": title,
        "author": author,
        "chapters": chapters,
    }


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    epub_files = sorted(BOOKS_DIR.glob("*.epub"))
    print(f"Found {len(epub_files)} epub files")

    # Force re-extraction of all books
    force = "--force" in sys.argv

    mapping = {}

    for i, epub_path in enumerate(epub_files):
        json_name = sanitize_filename(epub_path.name) + ".json"
        out_path = OUTPUT_DIR / json_name

        if out_path.exists() and not force:
            mapping[epub_path.name] = json_name
            print(f"[{i+1}/{len(epub_files)}] SKIP (exists): {epub_path.name}")
            continue

        print(f"[{i+1}/{len(epub_files)}] Extracting: {epub_path.name}")
        result = extract_epub(epub_path)

        if result:
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False)
            size_kb = out_path.stat().st_size / 1024
            print(f"  -> {json_name} ({size_kb:.0f} KB, {len(result['chapters'])} chapters)")
            mapping[epub_path.name] = json_name
        else:
            print(f"  -> FAILED")

    # Save mapping
    mapping_path = OUTPUT_DIR / "_mapping.json"
    with open(mapping_path, 'w') as f:
        json.dump(mapping, f, indent=2)

    print(f"\nDone! Extracted {len(mapping)} books to {OUTPUT_DIR}")
    print(f"Mapping saved to {mapping_path}")


if __name__ == "__main__":
    main()
