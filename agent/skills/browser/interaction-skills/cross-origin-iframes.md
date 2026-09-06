# Cross-origin iframes

The symptom: `document.body.innerText` on the parent returns almost nothing while the screenshot
plainly shows a form, and the widget's mount point (`#onfido-mount`, `#widget-root`) reads as
empty. Identity, payment, and document-upload widgets are nearly always third-party iframes, and
the top document cannot see into them.

Do not trust the top document. Two ways in, in order of preference:

1. **Click by coordinate.** `click_at_xy(x, y)` and `type_text(...)` dispatch real input at a
   viewport point regardless of document structure, so they land inside a cross-origin iframe.
   Read the target's position from the screenshot or from the parent's iframe rect.
2. **Query inside the frame.** On the Chromium engine, `iframe_target("substring-of-iframe-url")`
   returns the frame's id, which `js(expr, target_id=...)` then runs inside:

   ```python
   frame = iframe_target("onfido")
   print(js("document.body.innerText.slice(0, 500)", target_id=frame))
   ```

The parent's own DOM still tells you where the frame is, which is enough for the coordinate path:

```python
print(js("[...document.querySelectorAll('iframe')].map(f => ({src: f.src, r: f.getBoundingClientRect()}))"))
```
