# Forms: a field you cannot find, and a submit that will not advance

Two failures look like a wall and are almost never one. Work through them before you consider a
block, a different engine, or a handover.

## A submit button that does nothing is a validation error

On a multi-step wizard or a checkout, "Continue" or "Submit" that appears to do nothing is the
form refusing you, not the site fighting automation. Read the actual state first:

```python
state = js("""(() => {
  const bad = [...document.querySelectorAll('[required]')].filter(e => !e.value).map(e => e.name || e.id);
  const errs = [...document.querySelectorAll('.text-danger,[class*=error],[role=alert]')]
    .map(e => (e.innerText || '').trim()).filter(Boolean);
  const unticked = [...document.querySelectorAll('input[type=checkbox]')].filter(e => !e.checked).length;
  return {bad, errs, unticked, forms: document.forms.length};
})()""")
print(state)
```

Four causes, in the order they occur: one required field left empty, an error message rendered
somewhere you did not read, an unticked terms checkbox, and a second hidden copy of the form where
you filled the wrong instance (`forms` above greater than 1). The overwhelmingly common one is the
first. A false wall abandoned costs more than a real wall pushed through.

## A page that appears to have no field at all

"There is nowhere to type it, so this needs the user's own device" is the most expensive wrong
conclusion available, because it looks like diligence. Rule out five things, in this order:

1. **A cross-origin iframe.** Identity, payment and document-upload widgets are nearly always
   third-party iframes, so the parent document reads as empty while the screenshot plainly shows a
   form. See [cross-origin-iframes.md](cross-origin-iframes.md).
2. **A field behind a conditional render.** The input exists only after some control is clicked (a
   `v-if` or `x-show` toggled by a "Get a code" or "Enter it manually" link). When the visible
   call-to-action opens a new tab, click it with a capture-phase `preventDefault` so the
   framework's handler still runs and reveals the field without navigating away.
3. **A selector that is too specific.** Framework-rendered inputs often carry no `type` attribute,
   so `input[type=text]` matches nothing even though `el.type === 'text'`. Query bare `input` and
   filter in JS, and include `[contenteditable]` and `[role=textbox]` for masked and custom
   widgets. A `contenteditable` rich-text editor needs
   [prosemirror-tiptap-editors.md](prosemirror-tiptap-editors.md).
4. **A shadow root.** `querySelectorAll` never pierces one, so a web-component field is invisible
   to it. Walk recursively: collect matches, then recurse into every `el.shadowRoot`.
5. **Hydration timing.** A code-split step component mounts late, so an immediate query
   legitimately returns 0 a moment before the field exists. `wait_for_element("<selector>")` or a
   short `wait()` and a re-query settle it.

The sweep that covers 3 and 4 in one call:

```python
fields = js("""(() => {
  const out = [];
  const walk = (root) => {
    for (const el of root.querySelectorAll('input,textarea,[contenteditable],[role=textbox]')) {
      const r = el.getBoundingClientRect();
      out.push({tag: el.tagName, type: el.type || '', name: el.name || el.id || '', x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2)});
    }
    for (const el of root.querySelectorAll('*')) if (el.shadowRoot) walk(el.shadowRoot);
  };
  walk(document);
  return out;
})()""")
print(fields)
```

Then type into what it found: `click_at_xy(x, y)` on the reported centre for real focus, then
`type_text(...)`. There is no click by selector, so a rect read with `js` is how a selector becomes
a click.

A genuine wall states a capability the machine lacks, such as a camera, a physical document, a
biometric, or an on-device 2FA. It is never merely a field you could not find.
