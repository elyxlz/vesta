# Typing into ProseMirror / TipTap rich-text editors

Modern web apps (Notion-likes, Linear, many CMSs, chat composers) use **ProseMirror** (often via
the **TipTap** wrapper). The editable node looks like
`<div class="tiptap ProseMirror" contenteditable="true">`. These editors keep their own internal
document model and a `beforeinput`/`input` pipeline; the visible DOM is a *projection* of that
model. That breaks the naive ways of inserting text.

## What does NOT work

- **`execCommand('insertText', ...)`**: mutates the DOM text but does **not** update
  ProseMirror's document model. The editor's own word/char counter stays at 0, and any
  "submit" reads an empty doc. You'll see text on screen but the app acts as if the box
  is empty. The same applies to `execCommand('selectAll')`/`execCommand('delete')` for
  clearing: the model keeps its old content.
- **Synthetic `ClipboardEvent('paste', {clipboardData})`**: ProseMirror's paste handler
  ignores untrusted events (`isTrusted === false`), and Firefox won't let you populate
  `clipboardData` on a constructed event anyway. No-op.
- **`navigator.clipboard.writeText()` + real Ctrl+V**: blocked headless:
  `Clipboard write was blocked due to lack of user activation`.

## What works: real keystrokes, chunked

Real BiDi key events go through the genuine `beforeinput` pipeline, so ProseMirror registers
them. Clearing works the same way: a real Ctrl+A then Backspace through that pipeline, never
`execCommand`. Three gotchas: the editor node may not be attached for the first second or two
after navigation on these SPAs, so wait for the selector before touching it; the editor needs
**real focus** (a coordinate click, not `.focus()`); and a **single huge `type_text` payload
breaks the socket** (`BrokenPipeError` / channel error), so chunk it.

```python
# stdin mode (helpers pre-imported)
txt = open("/tmp/doc.txt").read().strip()
for _ in range(20):  # the editor mounts late; wait for the node
    if js("document.querySelectorAll('.tiptap.ProseMirror').length"):
        break
    wait(0.5)
r = js("""(function(){
  var b=document.querySelector('.tiptap.ProseMirror').getBoundingClientRect();
  return {x:Math.round(b.x+b.width/2), y:Math.round(b.y+30)};
})()""")
click(r["x"], r["y"])  # real focus
press_key("a", ["Control"])  # clear through the same input pipeline as the typing
press_key("Backspace")
for i in range(0, len(txt), 120):  # ~120-char chunks; larger risks BrokenPipe
    type_text(txt[i : i + 120])
# verify the editor's OWN counter moved before acting on it:
print(js("(document.body.innerText.match(/([0-9,]+)\\s*words/)||['?'])[0]"))
```

Then click the app's submit button by text and read the result from
`document.body.innerText`. Newlines in `type_text` become paragraph breaks, which is
usually what you want.

These apps are heavy-JS SPAs, so the navigation and timeout rules in
[SKILL.md](../SKILL.md)'s "Auth-gated / heavy-JS pages" section apply. One extra: repeated
navigations accumulate contexts until Camoufox reports `Maximum number of active sessions`.
Fix: `browser stop` then relaunch on the **same** `--user-data-dir` (logged-in sessions
persist in the profile). Never pkill.
