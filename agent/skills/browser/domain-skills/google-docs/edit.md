# Google Docs: writing into a doc shared with "anyone with the link can edit"

Verified 10 Nov 2026 (five full rewrites of one doc in a row, each checked). A doc shared as
"Anyone with the link: Editor" opens in the editor with NO Google sign-in: the page shows
"Sign in" top right and "Editing" in the mode dropdown. "View only" or "Request edit access"
in `innerText` means the link is view-only: ask the owner to change it rather than signing in.

## Read the doc (no browser needed)
`curl -sL "https://docs.google.com/document/d/<ID>/export?format=txt"` returns the plain text
(leading BOM, CRLF line ends, blank line after each paragraph). Use it to read before writing and
to VERIFY after writing. The editor DOM is a canvas renderer, so `innerText` does not hold the body.

## Write: replace the whole body
```python
new_tab("https://docs.google.com/document/d/<ID>/edit")
wait_for_load(); wait(4)
lines = open("/tmp/doc.txt").read().split("\n")
click_at_xy(600, 400); wait(0.5)            # focus the page body
press_key("a", modifiers=2); wait(0.5)      # Ctrl+A
press_key("Delete"); wait(1)
for i, l in enumerate(lines):
    if l: type_text(l)
    if i < len(lines) - 1: press_key("Enter")
wait(3)
```
About 6 to 12 s for ~60 lines. Typed text lands as plain paragraphs (no heading styles); a line
starting with `- ` stays literal text. Edits autosave; the export URL reflects them within ~5 s.

## Traps
- Ctrl+Shift+H (find and replace) did not open from automation; targeted edits are not reliable.
  Keep the doc's full text in a local mirror file, edit the mirror, and rewrite the whole body.
- BEFORE a full rewrite, diff the export against your mirror (strip BOM, CR and blank lines): if
  they differ, the owner edited the doc and a rewrite would erase their changes. Merge first.
- After writing, grep the export for a line from the top, the middle and the end: a full-body
  replace that half-failed leaves old and new text mixed.
- Stop the session afterwards (`browser session stop <name>`).
