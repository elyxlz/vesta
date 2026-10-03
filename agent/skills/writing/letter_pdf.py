#!/usr/bin/env python3
"""Render a plain-text letter to a clean A4 PDF, with a hard page budget.

Input format (plain text, blank line between blocks):
    Subject: <subject line>          (optional first line)
    <salutation / paragraphs ...>
    <sign-off block: the last 1-3 short lines, e.g. "Kind regards," / name / title>

Usage:
    letter_pdf.py letter.md out.pdf [--max-pages 1] [--signoff-lines 2] [--date "2 October 2026"]

Fits the page budget by stepping through progressively tighter layouts. Exits 1 (and keeps
no PDF) when even the tightest layout overflows, so an over-budget PDF is never produced and
sent by accident. Prints the page count and the layout used.
"""

import argparse
import html
import subprocess
import sys
import tempfile
from pathlib import Path

LAYOUTS = [
    ("normal", "25mm 25mm", "11pt", "1.5", "11pt"),
    ("snug", "22mm 23mm", "10.5pt", "1.45", "10pt"),
    ("tight", "18mm 20mm", "10pt", "1.4", "8pt"),
]


def build_html(text: str, signoff_lines: int, date: str | None, layout: tuple) -> str:
    _, margin, size, lh, gap = layout
    lines = text.strip().split("\n")
    subject = None
    if lines and lines[0].lower().startswith("subject:"):
        subject = lines[0].split(":", 1)[1].strip()
        lines = lines[1:]
    blocks = [b.strip() for b in "\n".join(lines).split("\n\n") if b.strip()]
    sig = blocks[-signoff_lines:] if signoff_lines else []
    body = blocks[: len(blocks) - len(sig)]
    parts = []
    if date:
        parts.append(f"<div class='date'>{html.escape(date)}</div>")
    if subject:
        parts.append(f"<div class='subj'>{html.escape(subject)}</div>")
    parts += [f"<p>{html.escape(b).replace(chr(10), '<br>')}</p>" for b in body]
    if sig:
        sig_html = "<br><br>".join(html.escape(b).replace("\n", "<br>") for b in sig)
        parts.append(f"<div class='sig'>{sig_html}</div>")
    css = (
        f"@page{{size:A4;margin:{margin}}}"
        f"body{{font-family:'Helvetica Neue',Arial,sans-serif;font-size:{size};line-height:{lh};color:#111}}"
        f".date{{margin-bottom:14pt}}.subj{{font-weight:600;margin-bottom:14pt}}p{{margin:0 0 {gap}}}.sig{{margin-top:16pt}}"
    )
    return f"<html><head><meta charset='utf-8'><style>{css}</style></head><body>{''.join(parts)}</body></html>"


def pages(pdf: str) -> int:
    out = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True, check=True).stdout
    return int(next(line.split()[-1] for line in out.splitlines() if line.startswith("Pages:")))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--max-pages", type=int, default=1)
    ap.add_argument("--signoff-lines", type=int, default=2)
    ap.add_argument("--date")
    a = ap.parse_args()
    text = Path(a.src).read_text(encoding="utf-8")
    out = Path(a.out)
    n = 0
    with tempfile.TemporaryDirectory() as td:
        page = Path(td) / "letter.html"
        for layout in LAYOUTS:
            page.write_text(build_html(text, a.signoff_lines, a.date, layout), encoding="utf-8")
            subprocess.run(
                ["chromium", "--headless", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={a.out}", str(page)],
                capture_output=True,
                check=False,
            )
            if not out.exists():
                print("render failed: chromium produced no PDF", file=sys.stderr)
                return 1
            n = pages(a.out)
            if n <= a.max_pages:
                print(f"OK {n} page(s), layout={layout[0]}: {a.out}")
                return 0
        out.unlink()
        print(f"OVER BUDGET: {n} pages even at the tightest layout (max {a.max_pages}); cut the text", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
