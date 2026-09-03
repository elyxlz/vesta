import sys
from pathlib import Path

import pymupdf

USAGE = "usage: pdf-text <file.pdf>"


def maps_to_unicode(doc: pymupdf.Document, font_xref: int) -> bool:
    kind, value = doc.xref_get_key(font_xref, "ToUnicode")
    if kind != "xref":
        return False
    cmap = doc.xref_stream(int(value.split()[0]))
    return b"beginbfchar" in cmap or b"beginbfrange" in cmap


def unmappable_fonts(doc: pymupdf.Document) -> dict[str, set[int]]:
    """Base font name to the 1-based pages carrying a Type0/Identity-H font whose ToUnicode maps nothing."""
    flagged: dict[str, set[int]] = {}
    for page in doc:
        for xref, _ext, kind, basefont, _name, encoding, _referencer in page.get_fonts(full=True):
            if kind != "Type0" or encoding != "Identity-H" or maps_to_unicode(doc, xref):
                continue
            if basefont not in flagged:
                flagged[basefont] = set()
            flagged[basefont].add(page.number + 1)
    return flagged


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(USAGE, file=sys.stderr)
        return 2
    try:
        doc = pymupdf.open(Path(args[0]))
    except (pymupdf.FileNotFoundError, pymupdf.FileDataError) as exc:
        print(f"pdf-text: {exc}", file=sys.stderr)
        return 2
    flagged = unmappable_fonts(doc)
    for basefont, pages in flagged.items():
        print(f"{basefont} pages {','.join(str(page) for page in sorted(pages))}")
    return 1 if flagged else 0
