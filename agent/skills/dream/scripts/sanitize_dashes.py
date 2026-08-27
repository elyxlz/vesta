#!/usr/bin/env python3
"""Sanitize banned separators (em/en dash, ' - ', ' + ', ascii arrows) from a text file.
Usage: sanitize_dashes.py <file>   (in-place)  |  --check <file>  (report counts only)
The block_dashes rule only polices chat output; documents, emails and DOCX sources leak.
Run this on any DOCX-source .md, email body, or generated text before sending it to the user."""

import re
import sys
import zipfile
from pathlib import Path


def sanitize(txt: str) -> str:
    # time/date ranges with en/em/hyphen -> hyphen-minus (acceptable inside a range token)
    txt = re.sub(r"(\d[:\.]\d+)\s*[\u2013—]\s*(\d[:\.]\d+)", r"\1-\2", txt)
    txt = re.sub(r"(\d{4}-\d{2}-\d{2})\s*[\u2013—]\s*(\d{4}-\d{2}-\d{2})", r"\1-\2", txt)
    # standalone em/en dash used as a separator -> colon
    txt = txt.replace(" — ", ": ").replace(" —", ":").replace("— ", ": ")
    txt = txt.replace(" \u2013 ", ": ").replace(" \u2013", ":").replace("\u2013 ", ": ")
    txt = txt.replace("—", ":").replace("\u2013", ":")
    # " - " word separator -> ", "  ([^\S\n] = whitespace except newline, so \n- bullet markers survive)
    txt = re.sub(r"[^\S\n]+-[^\S\n]+", ", ", txt)
    # " + " concept/name join -> ", "  (conjunction joins are read case-by-case; comma is the safe default)
    txt = re.sub(r"[^\S\n]+\+[^\S\n]+", ", ", txt)
    # ascii arrows -> " a " / " to "
    return txt.replace("->", " a ").replace("→", " a ")


def count(txt: str) -> dict:
    return {
        "em_dash": len(re.findall(r"—", txt)),
        "en_dash": len(re.findall(r"\u2013", txt)),
        "sep_dash": len(re.findall(r"[^\S\n]+-[^\S\n]+", txt)),
        "plus_join": len(re.findall(r"[^\S\n]+\+[^\S\n]+", txt)),
        "arrow": len(re.findall(r"->|→", txt)),
    }


def docx_text(path: str) -> str:
    """Extract all table-cell and paragraph text from a .docx (zip of XML)."""
    text_parts = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name.startswith("word/") and name.endswith(".xml"):
                data = z.read(name).decode("utf-8", errors="replace")
                # crude but sufficient: text runs are inside <w:t>...</w:t>
                text_parts += re.findall(r"<w:t[^>]*>([^<]*)</w:t>", data)
    return " ".join(text_parts)


if __name__ == "__main__":
    args = sys.argv[1:]
    check = "--check" in args
    if check:
        args.remove("--check")
    if not args:
        print(__doc__)
        sys.exit(1)
    for path in args:
        if path.lower().endswith(".docx"):
            # DOCX: check only (report counts). In-place rewrite of OOXML risks
            # corrupting the document; the fix is manual review of the flagged cells.
            before = count(docx_text(path))
            print(f"{path} (docx, check-only): {before}")
            continue
        t = Path(path).read_text(encoding="utf-8")
        before = count(t)
        if check:
            print(f"{path}: {before}")
            continue
        out = sanitize(t)
        after = count(out)
        Path(path).write_text(out, encoding="utf-8")
        print(f"{path}: {before} -> {after}")
