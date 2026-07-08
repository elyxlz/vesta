# Tabs

Camoufox runs headless, so there is no visible tab strip to keep in sync; tabs are just
top-level BiDi browsing contexts you open, attach to, and close.

## The BiDi tab model

```python
tabs = list_tabs()                     # top-level contexts; includes about: pages
real_tabs = list_tabs(include_internal=False)  # drop about:/moz-extension:/etc
ctx = new_tab("https://example.com")   # create + switch + navigate; returns the context id
switch_tab(ctx)                        # make this context current (also activates it)
print(current_tab())                   # {target_id, url, title} for the current context
print(page_info())
close_tab(ctx)                         # close a context by id
```

`target_id` in every helper is the BiDi **context id** (a stable UUID for the tab), the analog
of the old CDP target id.

## What the model is good at

- open, attach to, inspect, and close tabs
- run JS / take a snapshot in any context by id (`js(expr, target_id=ctx)`)
- reach an iframe's context: `iframe_target("substring-of-its-url")`

## Rules that held up in practice

- Navigating away invalidates the snapshot's refs; take a fresh `browser snapshot` after.
- `list_tabs()` includes internal `about:` pages by default; pass `include_internal=False` when
  you want only real pages.
- If a page reports `w=0 h=0` in `page_info()`, you're likely attached to a context that hasn't
  laid out yet; `wait_for_load()` first.
- For dynamic UIs, re-read element rects (fresh snapshot) after opening dropdowns / modals before
  coordinate-clicking.
