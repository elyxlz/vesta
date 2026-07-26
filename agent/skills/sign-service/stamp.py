#!/usr/bin/env python3
"""Stamp a hand-drawn signature PNG onto a labeled field in one or more PDFs.

Finds a text label on the target page and drops the signature image into a box
just below it, keeping proportions so the ink never distorts. Placement is
best-effort: always render a preview and get the user to approve before sending.

Run: uv run --with PyMuPDF python3 stamp.py --signature sig.png --outdir out \\
       --label "FIRMA del CONTRIBUENTE" --page 2 form.pdf
"""

import argparse
import sys
from pathlib import Path
from typing import NamedTuple


class Placement(NamedTuple):
    """How to place the signature relative to the located label, in PDF points."""

    width: float = 175.0
    height: float = 26.0
    gap: float = 1.0
    x_min: float = 0.0
    x_max: float = 1e9


def signature_box(label, width, height, gap):
    """Given a label rectangle (x0, y0, x1, y1), return the placement box
    (x0, y0, x1, y1) for the signature: a `width` by `height` box that starts
    `gap` points below the label's bottom edge, left-aligned to the label."""
    x0, _y0, _x1, y1 = label
    top = y1 + gap
    return (x0, top, x0 + width, top + height)


def find_label(page, labels, x_min, x_max):
    """Locate the signature label on a PyMuPDF page. Prefer an exact phrase
    match; fall back to the first word of the first label within an x band
    (useful when the phrase is split across text spans in a column)."""
    import fitz

    for phrase in labels:
        hits = page.search_for(phrase)
        if hits:
            return tuple(hits[0])
    first = labels[0].split()[0].upper() if labels else ""
    for word in page.get_text("words"):
        if word[4].upper() == first and x_min < word[0] < x_max:
            return tuple(fitz.Rect(word[:4]))
    return None


def stamp(pdf, signature, out, page_index, labels, place):
    """Stamp `signature` onto `pdf` and save to `out`. Returns the label
    rectangle used, or None if no label was found (nothing is written)."""
    import fitz

    doc = fitz.open(pdf)
    page = doc[page_index]
    label = find_label(page, labels, place.x_min, place.x_max)
    if label is None:
        return None
    box = fitz.Rect(*signature_box(label, place.width, place.height, place.gap))
    page.insert_image(box, filename=signature, keep_proportion=True, overlay=True)
    doc.save(out, garbage=3, deflate=True)
    return label


def build_parser():
    p = argparse.ArgumentParser(description="Stamp a signature PNG onto a labeled field in one or more PDFs.")
    p.add_argument("pdfs", nargs="+", help="Input PDF file(s) to sign.")
    p.add_argument("-s", "--signature", required=True, help="Signature PNG (transparent background, ink only).")
    p.add_argument("-o", "--outdir", required=True, help="Directory for the signed PDFs and any previews.")
    p.add_argument(
        "-l",
        "--label",
        action="append",
        dest="labels",
        required=True,
        metavar="TEXT",
        help="Text that marks the signature line. Repeatable to try several variants in order.",
    )
    p.add_argument("-p", "--page", type=int, default=0, help="Zero-based page index of the field (default 0).")
    p.add_argument("--width", type=float, default=175.0, help="Signature box width in points (default 175).")
    p.add_argument("--height", type=float, default=26.0, help="Signature box height in points (default 26).")
    p.add_argument(
        "--gap",
        type=float,
        default=1.0,
        help="Gap between the label and the box, in points (default 1).",
    )
    p.add_argument(
        "--x-min",
        type=float,
        default=0.0,
        help="Lower x bound for the label-word fallback search (default 0).",
    )
    p.add_argument(
        "--x-max",
        type=float,
        default=1e9,
        help="Upper x bound for the label-word fallback search (default unbounded).",
    )
    p.add_argument(
        "--suffix",
        default=" (signed)",
        help="Filename suffix for the signed output (default ' (signed)').",
    )
    p.add_argument("--preview", action="store_true", help="Also render a 2x PNG preview of the stamped page.")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    place = Placement(args.width, args.height, args.gap, args.x_min, args.x_max)
    rc = 0
    for pdf in args.pdfs:
        stem = Path(pdf).stem
        out = outdir / f"{stem}{args.suffix}.pdf"
        label = stamp(pdf, args.signature, str(out), args.page, args.labels, place)
        if label is None:
            print(f"NO LABEL found in {pdf}", file=sys.stderr)
            rc = 1
            continue
        print(f"stamped {out} | label at ({round(label[0])}, {round(label[1])})")
        if args.preview:
            import fitz

            prev = outdir / f"{stem}_p{args.page + 1}_preview.png"
            fitz.open(str(out))[args.page].get_pixmap(matrix=fitz.Matrix(2, 2)).save(str(prev))
            print(f"preview {prev}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
