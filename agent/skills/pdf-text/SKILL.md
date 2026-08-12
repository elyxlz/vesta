---
name: pdf-text
description: Verify that text extracted from a PDF is what the page actually says. Use before quoting a figure, a formula, a symbol or a code from any PDF (papers, invoices, bills, statements, contracts).
---

# PDF text

`pdftotext` never says "I could not read this character". When a font gives it no
route to Unicode it prints a plausible letter instead, and the extracted text
stays a well formed sentence. Quoting from it then puts characters in your mouth
that the document never contained.

## The failure this catches

One economics working paper renders `sigma = 0.75; alpha = 0.1` and extracts as
`V 0.75; D 0.1`. No error, no replacement character, no encoding complaint.

The mechanism, in three parts, all of which have to line up:

1. The font is **Identity-H CID TrueType**, so the codes in the content stream
   are glyph indices, not characters.
2. Its **`/ToUnicode` CMap exists and defines nothing**: a codespace range, then
   `endcmap`, with zero `bfchar` and zero `bfrange` entries.
3. The embedded subset has **no `cmap` table** (legal for Identity-H, which
   renders straight from glyph indices).

With every route to a character gone, poppler falls back to reading the raw CID
as a Unicode scalar. CID 0x56 prints as `V`, CID 0x44 as `D`.

**`pdffonts` will not warn you.** Its `uni` column reports whether a `/ToUnicode`
object EXISTS, not whether the map inside it maps anything, so an empty CMap
answers `uni yes`. The instrument reports on the container while being read as a
report on the content.

## Usage

```bash
agent/skills/pdf-text/scripts/check-glyphs paper.pdf
agent/skills/pdf-text/scripts/check-glyphs paper.pdf --pages 40-42
agent/skills/pdf-text/scripts/check-glyphs --selftest
```

Exit codes: **1** unmappable glyphs are actually drawn on the pages checked,
**0** clean, **2** the parse failed. A parse failure is never reported as clean.

Output names the font, the code, how often it appears, and what `pdftotext` will
emit for it, so the fake character is recognisable on sight next time.

## What to do when it reports something

The script deliberately does NOT guess what the character really was. Only the
rendered page can tell you that:

```bash
pdftoppm -f 41 -l 41 -r 150 -png paper.pdf /tmp/pg   # then read the image
```

Then quote from the render, not from the extraction.

## When to run it

Before quoting anything from a PDF where a wrong character changes the meaning:
a Greek letter in a formula, a currency amount, an IBAN, a booking reference, a
meter reading, a deadline. Symbol and math fonts are where this bites; body text
in a normal Type1 or TrueType font is usually fine.

Cheap habit that costs nothing: if extracted text contains lone capital letters
where a symbol belongs, that is the tell, and this is the check.

## Notes

`--selftest` builds a synthetic two-font PDF in a temp dir, one clean font and
one Identity-H font with an empty CMap, and asserts the broken one is reported
and the clean one is not. It exercises the failure branch, which is the point: a
check nobody has watched fail is not a check. The first version of this script
returned empty for streams it could not decompress, so uncompressed PDFs read as
having no glyphs at all and it printed a confident `clean`. The selftest caught
that on its first execution.
