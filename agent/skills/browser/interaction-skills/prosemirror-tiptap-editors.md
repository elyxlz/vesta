# Typing into ProseMirror / TipTap rich-text editors

Modern web apps (Notion-likes, Linear, many CMSs, GPTZero's scan box, chat composers)
use **ProseMirror** (often via the **TipTap** wrapper). The editable node looks like
`<div class="tiptap ProseMirror" contenteditable="true">`. These editors keep their own
internal document model and a `beforeinput`/`input` pipeline; the visible DOM is a
*projection* of that model. That breaks the naive ways of inserting text.

## What does NOT work

- **`execCommand('insertText', ...)`** -- mutates the DOM text but does **not** update
  ProseMirror's document model. The editor's own word/char counter stays at 0, and any
  "submit" reads an empty doc. You'll see text on screen but the app acts as if the box
  is empty.
- **Synthetic `ClipboardEvent('paste', {clipboardData})`** -- ProseMirror's paste handler
  ignores untrusted events (`isTrusted === false`), and Firefox won't let you populate
  `clipboardData` on a constructed event anyway. No-op.
- **`navigator.clipboard.writeText()` + real Ctrl+V** -- blocked headless:
  `Clipboard write was blocked due to lack of user activation`.

## What works: real keystrokes, chunked

Real BiDi key events go through the genuine `beforeinput` pipeline, so ProseMirror
registers them. Two gotchas: you must give the editor **real focus** first (a coordinate
click, not just `.focus()`), and a **single huge `type_text` payload breaks the socket**
(`BrokenPipeError` / channel error). Chunk it.

```python
# stdin mode (helpers pre-imported)
txt = open("/tmp/doc.txt").read().strip()
# focus + clear, and grab the editor rect for a real click
r = js("""(function(){
  var ed=document.querySelector('.tiptap.ProseMirror');
  ed.focus();
  document.execCommand('selectAll'); document.execCommand('delete');
  var b=ed.getBoundingClientRect();
  return {x:Math.round(b.x+b.width/2), y:Math.round(b.y+30)};
})()""")
click(r["x"], r["y"])  # real focus
for i in range(0, len(txt), 120):  # ~120-char chunks; larger risks BrokenPipe
    type_text(txt[i : i + 120])
# verify the editor's OWN counter moved before acting on it:
print(js("(document.body.innerText.match(/([0-9,]+)\\s*words/)||['?'])[0]"))
```

Then click the app's submit/scan button by text and read the result from
`document.body.innerText`. Newlines in `type_text` become paragraph breaks, which is
usually what you want.

## SPA caveats (these apps are heavy-JS)

- `goto()` on these SPAs often hangs (the `load` event never fires cleanly). Run the nav
  in a background thread with a ~15s join, then read `page_info()` / DOM in a **separate**
  short call -- never `wait_for_load()`. Cap every browser call at `timeout 40-60`.
- The editor node may not exist for the first ~1-2s after navigation; re-query
  `document.querySelectorAll('.tiptap.ProseMirror').length` before typing.
- Repeated navigations/scans accumulate contexts → Camoufox
  `Maximum number of active sessions`. Fix: `browser stop` then relaunch on the **same**
  `--user-data-dir` (logged-in sessions persist in the profile). Never pkill.

Verified Jul 2026 driving app.gptzero.me end to end (paste a document → run a scan → read
the verdict) via the browser skill.
