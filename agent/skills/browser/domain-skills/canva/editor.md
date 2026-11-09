# Canva editor: editing a shared design's text and layout

Verified 8 Nov 2026 on a design opened from a "can edit" share link (`canva.link/...` redirects to
`https://www.canva.com/design/<id>/<key>/edit`). An edit link opens the editor with NO sign-in, and
every change autosaves into the owner's design. Download/export (PDF, PNG) and "Make a copy" DO need
a signed-in account: ask the owner to export (Share > Download > PDF Standard) rather than signing in.

## Read the design
Text lives in the DOM as `<p>` / `<li>` / `<span>` inside absolutely positioned boxes, so a
`getBoundingClientRect()` sweep gives every box's screen position. Each text appears twice (a hidden
accessibility copy sits off-canvas, often higher up): filter on `width > 5` and a sane `y`.

## Clicks: what gets selected
- Single click on text = selects its GROUP (CVs/templates group each section: title, date, bullets).
- Keep double-clicking the same point until `document.activeElement.isContentEditable` is true and its
  `innerText` contains the expected text (took 3 clicks in practice). ONLY THEN type.
- Typing while a group (not text) is selected fires single-letter shortcuts (T, L, R, C add elements).
  Never type without the isContentEditable check.

## Replace text precisely
In edit mode, set a DOM Range over the exact substring (TreeWalker over text nodes, `getSelection().addRange`)
and `type_text(new)`. Canva honours DOM selection. For a whole bullet, select from the first to the last
text node of its `<li>`. Do NOT press Delete/Backspace with a collapsed caret to "clean up": it ate a word.
Removing a whole bullet: removing its `<li>` from the contenteditable DOM persisted fine; a trailing empty
`<p><br></p>` is cleared by placing the caret in it and one Backspace. Enter inside a list adds a bullet.
Text boxes reflow internally but do NOT push sibling boxes: free space is yours to move into.

## Move things exactly
Select a group (single click), click the toolbar "Position" button: the panel's Advanced fields are
Width, Height, X, Y in cm (visible `<input>`s whose value ends in " cm"; order W, H, X, Y). Triple-click a
field, Ctrl+A, type the number, Enter. Re-read the fields to confirm. Duplicate a group with Ctrl+D
(lands offset ~+0.4 cm) to clone a section's styling, then edit its texts and set its X/Y.
Check which object is selected before setting Y: a click on a title can select a child box (width differs
from the group's), and moving that breaks the layout. Ctrl+Z undoes one step.

## Verify
Zoom with Ctrl+= (4 presses ~ 35% -> 100%) and screenshot; re-run the position sweep to check gaps.
