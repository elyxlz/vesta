#!/usr/bin/env python3
"""Build ~/agent/data/skills/library/catalog.json from epubs in ~/agent/data/skills/library/books/.

Extracts metadata (title, author, language, publisher, subjects, description,
date, word_count) from each epub's OPF, saves the cover image to
~/agent/data/skills/library/covers/<sanitized>.jpg, and matches audio files in ~/agent/data/skills/library/audio/
by normalized filename similarity.

Idempotent: re-running updates existing entries and adds new ones. Never
writes base64-embedded covers (covers are served via GET /cover/<filename>).
"""

import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

DATA_DIR = Path.home() / "agent" / "data" / "skills" / "library"
BOOKS_DIR = DATA_DIR / "books"
AUDIO_DIR = DATA_DIR / "audio"
COVERS_DIR = DATA_DIR / "covers"
CATALOG_PATH = DATA_DIR / "catalog.json"
TEXT_DIR = DATA_DIR / "text"

NS_CONTAINER = "urn:oasis:names:tc:opendocument:xmlns:container"
NS_OPF = "http://www.idpf.org/2007/opf"
NS_DC = "http://purl.org/dc/elements/1.1/"

COVER_MEDIA_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def sanitize_filename(name: str) -> str:
    """Convert an epub filename to a safe cover/text base name."""
    name = Path(name).stem
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"\s+", "_", name.strip())
    return name[:100]


def normalize_for_match(name: str) -> str:
    """Normalize a filename for fuzzy audio/ebook matching."""
    stem = Path(name).stem.lower()
    stem = re.sub(r"_nodrm$", "", stem)
    stem = re.sub(r"[^a-z0-9]+", "", stem)
    return stem


def find_opf_path(zf: zipfile.ZipFile) -> str | None:
    try:
        xml = zf.read("META-INF/container.xml").decode("utf-8")
    except KeyError:
        return None
    root = ET.fromstring(xml)
    for rf in root.iter(f"{{{NS_CONTAINER}}}rootfile"):
        path = rf.get("full-path")
        if path and path.endswith(".opf"):
            return path
    for name in zf.namelist():
        if name.endswith(".opf"):
            return name
    return None


def parse_opf_metadata(zf: zipfile.ZipFile, opf_path: str) -> tuple[dict, dict, str]:
    """Return (metadata_dict, manifest_dict, opf_dir)."""
    xml = zf.read(opf_path).decode("utf-8")
    root = ET.fromstring(xml)
    opf_dir = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""

    meta = {
        "title": "",
        "author": "",
        "language": "",
        "publisher": "",
        "subjects": [],
        "description": "",
        "date": "",
    }

    meta_el = root.find(f"{{{NS_OPF}}}metadata")
    if meta_el is not None:

        def _text(tag):
            el = meta_el.find(f"{{{NS_DC}}}{tag}")
            return (el.text or "").strip() if el is not None and el.text else ""

        meta["title"] = _text("title")
        meta["author"] = _text("creator")
        meta["language"] = _text("language")
        meta["publisher"] = _text("publisher")
        meta["description"] = _text("description")
        meta["date"] = _text("date")
        for subj_el in meta_el.findall(f"{{{NS_DC}}}subject"):
            if subj_el.text and subj_el.text.strip():
                meta["subjects"].append(subj_el.text.strip())

    # Strip HTML from description
    if meta["description"]:
        try:
            meta["description"] = BeautifulSoup(meta["description"], "lxml").get_text(" ", strip=True)
        except Exception:
            pass

    # Cover id lookup (via <meta name="cover" content="..."/>)
    cover_id = None
    if meta_el is not None:
        for m in meta_el.findall(f"{{{NS_OPF}}}meta"):
            if m.get("name") == "cover":
                cover_id = m.get("content")
                break

    # Manifest
    manifest = {}
    manifest_el = root.find(f"{{{NS_OPF}}}manifest")
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

    # Resolve cover item
    cover_item = None
    if cover_id and cover_id in manifest:
        cover_item = manifest[cover_id]
    else:
        # Look for properties="cover-image" (EPUB3)
        for item in manifest.values():
            if "cover-image" in item["properties"].split():
                cover_item = item
                break
    if cover_item is None:
        # Heuristic: first image item with "cover" in href
        for item in manifest.values():
            if item["media_type"].startswith("image/") and "cover" in item["href"].lower():
                cover_item = item
                break

    meta["_cover_item"] = cover_item
    return meta, manifest, opf_dir


def extract_cover(zf: zipfile.ZipFile, cover_item: dict | None, out_base: str) -> str | None:
    """Save cover image to COVERS_DIR. Returns relative path string or None."""
    if not cover_item:
        return None
    media_type = cover_item.get("media_type", "")
    ext = COVER_MEDIA_TYPES.get(media_type, "")
    if not ext:
        # Fall back to href extension
        href_ext = Path(cover_item.get("href", "")).suffix.lower()
        if href_ext in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            ext = ".jpg" if href_ext == ".jpeg" else href_ext
        else:
            return None
    try:
        data = zf.read(cover_item["full_path"])
    except KeyError:
        return None
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = COVERS_DIR / f"{out_base}{ext}"
    out_path.write_bytes(data)
    return f"covers/{out_path.name}"


def count_words(zf: zipfile.ZipFile, manifest: dict) -> int:
    """Rough word count across HTML/XHTML manifest items."""
    total = 0
    for item in manifest.values():
        if item["media_type"] in ("application/xhtml+xml", "text/html"):
            try:
                content = zf.read(item["full_path"]).decode("utf-8", errors="replace")
            except KeyError:
                continue
            try:
                text = BeautifulSoup(content, "lxml").get_text(" ", strip=True)
            except Exception:
                continue
            total += len(text.split())
    return total


def audio_metadata(audio_path: Path) -> dict:
    """Extract narrator/duration from an audio file via ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                str(audio_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        data = json.loads(result.stdout or "{}")
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return {}
    fmt = data.get("format", {})
    tags = fmt.get("tags", {}) or {}
    info = {}
    # Narrator is often in composer/artist/performer
    narrator = tags.get("composer") or tags.get("performer") or tags.get("narrator") or tags.get("artist")
    if narrator:
        info["narrator"] = narrator
    try:
        seconds = float(fmt.get("duration", 0))
        if seconds > 0:
            info["duration_seconds"] = round(seconds, 3)
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            info["duration"] = f"{h}h {m:02d}m"
    except (TypeError, ValueError):
        pass
    return info


def build_audio_index() -> dict[str, Path]:
    """Index audio files by a normalized filename prefix (first 20 chars)."""
    idx: dict[str, Path] = {}
    if not AUDIO_DIR.exists():
        return idx
    for audio in AUDIO_DIR.iterdir():
        if audio.suffix.lower() not in (".m4b", ".mp3"):
            continue
        key = normalize_for_match(audio.name)[:20]
        if key and key not in idx:
            idx[key] = audio
    return idx


def build_entry(epub_path: Path, audio_index: dict[str, Path]) -> dict | None:
    try:
        zf = zipfile.ZipFile(str(epub_path))
    except (zipfile.BadZipFile, OSError) as e:
        print(f"  ERROR opening {epub_path.name}: {e}")
        return None

    with zf:
        opf_path = find_opf_path(zf)
        if not opf_path:
            print(f"  ERROR: no OPF in {epub_path.name}")
            return None
        try:
            meta, manifest, _ = parse_opf_metadata(zf, opf_path)
        except ET.ParseError as e:
            print(f"  ERROR parsing OPF in {epub_path.name}: {e}")
            return None

        out_base = sanitize_filename(epub_path.name)
        cover_rel = extract_cover(zf, meta.pop("_cover_item", None), out_base)
        word_count = count_words(zf, manifest)

    entry = {
        "filename": epub_path.name,
        "title": meta["title"] or epub_path.stem,
        "author": meta["author"],
        "language": meta["language"],
        "publisher": meta["publisher"],
        "subjects": meta["subjects"],
        "description": meta["description"],
        "word_count": word_count,
        "date": meta["date"],
        "cover": cover_rel or "",
        "has_trial_limitation": False,
    }

    # Audio matching
    key = normalize_for_match(epub_path.name)[:20]
    audio = audio_index.get(key) if key else None
    if audio:
        entry["audio_file"] = audio.name
        info = audio_metadata(audio)
        entry.update(info)

    return entry


def build_audio_only_entries(audio_index: dict[str, Path], ebook_keys: set[str]) -> list[dict]:
    """Create entries for audiobooks with no matching epub."""
    entries = []
    for key, audio in audio_index.items():
        if key in ebook_keys:
            continue
        info = audio_metadata(audio)
        entry = {
            "filename": "",
            "title": audio.stem,
            "author": "",
            "language": "",
            "publisher": "",
            "subjects": [],
            "description": "",
            "word_count": 0,
            "date": "",
            "cover": "",
            "has_trial_limitation": False,
            "audio_file": audio.name,
            "audio_only": True,
        }
        entry.update(info)
        entries.append(entry)
    return entries


def load_existing() -> dict[str, dict]:
    """Load the existing catalog keyed by a stable ID (filename or audio_file)."""
    if not CATALOG_PATH.exists():
        return {}
    try:
        data = json.loads(CATALOG_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    existing = {}
    for item in data:
        key = item.get("filename") or item.get("audio_file") or item.get("title")
        if key:
            existing[key] = item
    return existing


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    COVERS_DIR.mkdir(parents=True, exist_ok=True)

    if not BOOKS_DIR.exists():
        print(f"ERROR: {BOOKS_DIR} does not exist. Create it and drop .epub files in.")
        sys.exit(1)

    existing = load_existing()
    audio_index = build_audio_index()

    epub_files = sorted(BOOKS_DIR.glob("*.epub"))
    print(f"Found {len(epub_files)} epub files")
    print(f"Found {len(audio_index)} audio files")

    new_catalog: list[dict] = []
    ebook_keys: set[str] = set()

    for i, epub_path in enumerate(epub_files, 1):
        print(f"[{i}/{len(epub_files)}] {epub_path.name}")
        entry = build_entry(epub_path, audio_index)
        if not entry:
            continue

        # Merge with existing (preserve manually-set fields that we don't recompute,
        # but always overwrite freshly-extracted fields).
        prev = existing.get(entry["filename"])
        if prev:
            # Preserve cover_b64 only if still present upstream (deprecated, but don't
            # silently drop it if a user kept it around; we do not re-add it ourselves).
            if "pdf_file" in prev:
                entry["pdf_file"] = prev["pdf_file"]

        new_catalog.append(entry)
        key = normalize_for_match(epub_path.name)[:20]
        if key:
            ebook_keys.add(key)

    # Add audio-only entries, preserving any existing hand-edited metadata.
    for entry in build_audio_only_entries(audio_index, ebook_keys):
        prev_key = entry["audio_file"]
        prev = existing.get(prev_key)
        if prev:
            # Merge: keep previously-extracted metadata (title/author/cover/etc.)
            merged = {**prev}
            # Drop deprecated base64 covers
            merged.pop("cover_b64", None)
            # Overwrite with re-extracted audio info
            for k in ("duration", "duration_seconds", "narrator"):
                if k in entry:
                    merged[k] = entry[k]
            merged["audio_only"] = True
            merged["audio_file"] = entry["audio_file"]
            new_catalog.append(merged)
        else:
            new_catalog.append(entry)

    # Sort by title
    new_catalog.sort(key=lambda b: (b.get("title") or "").lower())

    CATALOG_PATH.write_text(json.dumps(new_catalog, indent=2, ensure_ascii=False))
    size_kb = CATALOG_PATH.stat().st_size / 1024
    print(f"\nWrote {len(new_catalog)} entries to {CATALOG_PATH} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
