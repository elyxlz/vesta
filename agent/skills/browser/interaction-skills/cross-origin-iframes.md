# Cross-Origin Iframes

The symptom: `document.body.innerText` on the parent returns almost nothing while the screenshot
plainly shows a form, and the widget's mount point (`#onfido-mount`, `#widget-root`) reads as
empty. Identity, payment, and document-upload widgets are nearly always third-party iframes, and
the top document cannot see into them.

Enumerate every browsing context and query inside each, do not trust the top document.
`browser bidi "browsingContext.getTree"` lists every context including iframe children. In Python
stdin mode, `iframe_target("substring-of-iframe-url")` returns the first child context whose URL
matches; pass it as `target_id` to `js(...)` to run JS inside that frame.

When cross-target DOM work gets awkward, coordinate clicks are lower friction: `click(x, y)` and
`browser click --at X Y` dispatch a real pointer event at that viewport point regardless of DOM
structure, so they land inside a cross-origin iframe.
