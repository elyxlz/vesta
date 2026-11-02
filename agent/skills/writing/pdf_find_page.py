#!/usr/bin/env python3
"""Find which PAGE of a PDF a phrase is on (grep -n on pdftotext output gives LINE numbers, not pages).

usage: pdf_find_page.py <file.pdf> <regex> [--context 80]
Prints: pdf_page (1-based index in the file), printed_page (best guess from a bare number line on that page, or ?), snippet.
Cite printed_page when it exists; it is what the reader sees.
"""

import re
import subprocess
import sys


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    pdf, pat = sys.argv[1], re.compile(sys.argv[2], re.IGNORECASE)
    ctx = int(sys.argv[sys.argv.index("--context") + 1]) if "--context" in sys.argv else 80
    text = subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True, text=True, check=True).stdout
    hits = 0
    for i, page in enumerate(text.split("\f"), 1):
        flat = re.sub(r"\s+", " ", page)
        m = pat.search(flat)
        if not m:
            continue
        nums = [ln.strip() for ln in page.splitlines() if re.fullmatch(r"\s*\d{1,4}\s*", ln)]
        printed = nums[0] if nums else "?"
        s = flat[max(0, m.start() - ctx) : m.end() + ctx]
        print(f"pdf_page={i}\tprinted_page={printed}\t...{s}...")
        hits += 1
    if not hits:
        print("no match (check the regex; ligatures like 'fi' may be split in the text layer)")
        sys.exit(1)


if __name__ == "__main__":
    main()
