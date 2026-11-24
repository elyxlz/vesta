# Google Docs: editing a doc shared as "anyone with the link can edit"

A doc shared as "Anyone with the link: Editor" opens in the editor with no Google sign-in: the page
shows "Sign in" top right and "Editing" in the mode dropdown. "View only" or "Request edit access" in
`innerText` means the link is view-only: ask the owner to change it rather than signing in.

## Read the doc (no browser needed)
`curl -sL "https://docs.google.com/document/d/<ID>/export?format=txt"` returns the plain text of every
tab (leading BOM, CRLF line ends). Use it to read before writing and to VERIFY after writing: diff the
export taken before an edit against the export taken after, so you see exactly what changed. The editor
DOM is a canvas renderer, so `innerText` does not hold the body. Edits autosave and reach the export
within about 5 s.

## Targeted edits: the Find and replace dialog (keeps images, tables and other tabs intact)
- Opens with REAL clicks only (a JS `click()` on the menu does nothing): close any tooltip first, then
  `click_at_xy` on the centre of `#docs-edit-menu`, then on the visible `.goog-menuitem` whose text
  starts with "Find and replace". Ctrl+Shift+H did not open it from automation.
- Fields: `input[aria-label="Find"]` and `input[aria-label="Replace with"]` (click, Ctrl+A, Delete,
  type). Checkboxes labelled "Match case" and "Use regular expressions". The search scope defaults to
  "All tabs" in multi-tab docs.
- The dialog text shows the match count as "N of M": check M against what you expect BEFORE replacing.
- Buttons "Replace" (replaces the current match, then advances in document order) and "Replace all".
- TRAP: regex replacement does NOT support backreferences. `$1` is written out literally, so a regex
  rename like `I2\.(\d)` -> `I3.$1` destroys the digits. Do literal replaces, one value at a time, each
  guarded by its expected count. To renumber a sequence, rename from the top down (I2 -> I3 before
  I1 -> I2) so no rename collides with the next.

## Small insertions: Ctrl+F then type
`press_key("f", modifiers=2)` opens Docs' own find bar; type the query, Enter, read the count with
`re.findall(r'\d+ of \d+', js("document.body.innerText"))`. `Escape` closes it and leaves a CARET, not
a selection, so typing inserts rather than replaces. The caret position is not reliable (it was at
the match start on a fresh tab and at the match end on a later find in the same tab): type a marker,
read the export to see where it landed, then Backspace it and move with ArrowLeft/ArrowRight. `End`
goes to the end of the visual line, which is the end of a table cell's text. Find searches the current
tab only, so open `/edit?tab=<tab id>` first.

## Whole-body rewrite (only for a plain-text doc)
Click the body, Ctrl+A, Delete, then `type_text` each line with Enter between them. This drops images,
tables and heading styles, so never use it on a formatted doc. Before rewriting, diff the export
against your local copy: if they differ, the owner edited the doc and a rewrite would erase it.

Stop the session afterwards (`browser session stop <name>`).
