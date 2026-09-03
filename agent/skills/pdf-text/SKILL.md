---
name: pdf-text
description: Check a PDF before quoting text extracted from it. Use before quoting a figure, formula, symbol, amount, IBAN, reference code, meter reading, or deadline from any PDF, because an extractor can print letters the page never contained.
---

# PDF text (CLI: pdf-text)

A text extractor never says it could not read a character. A Type0 font with Identity-H encoding stores glyph indices, not characters, and its ToUnicode CMap is the only route from an index to a character. When that CMap is absent or maps nothing, the extractor prints the raw index as a letter: index 0x56 comes out as `V`, so a page reading `sigma = 0.75` extracts as `V 0.75`. The result is a well formed sentence with letters the author never wrote, and nothing downstream can tell. `pdffonts` reports `uni yes` for exactly this font, because its column asks whether a ToUnicode object exists, not whether it maps anything.

Symbol and math fonts are where this bites: a lone capital letter where a symbol belongs is the tell.

## Setup

```bash
uv tool install --editable ~/agent/skills/pdf-text/cli
```

## Usage

```bash
pdf-text paper.pdf
```

Exit 0 with no output: every Type0/Identity-H font in the file maps to Unicode, so quote the extracted text.

Exit 1 with one line per font that cannot map, naming the pages that carry it:

```
UWPNAD+SymbolMT pages 12,41,42
```

The check does not know what the characters really are; only the rendered page does. For every listed page, render it and read the image instead of the extracted text:

```bash
uv run --with PyMuPDF python3 -c 'import pymupdf, sys; pymupdf.open(sys.argv[1])[int(sys.argv[2]) - 1].get_pixmap(dpi=150).save(sys.argv[3])' paper.pdf 41 /tmp/paper-p41.png
```

Then open `/tmp/paper-p41.png` with the Read tool and quote from what you see.

Exit 2 with the reason on stderr: the file is missing or is not a PDF.
