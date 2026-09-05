# Tabs

The browser runs with no visible tab strip, so tabs are only what the helpers report: pages you
open, switch between, and close by id.

## The tab model

```python
tabs = list_tabs()  # every page, including about: pages
ctx = new_tab("https://example.com")  # create, switch, navigate; returns the tab id
switch_tab(ctx)  # make this tab current
print(current_tab())  # {target_id, url, title} for the current tab
print(page_info())  # url, title, viewport size, scroll offsets, page size
close_tab(ctx)  # close one tab by id
```

`target_id` is the tab's id in every helper. Take it from `list_tabs()` or `current_tab()`, never
from memory of an earlier program: a closed and reopened tab carries a different id.

## What the model is good at

- open, switch to, inspect, and close tabs
- run JS in a named tab: `js(expr, target_id=ctx)`
- drop back to a real page after a tab lands on `about:blank`: `ensure_real_tab()`

## Rules that held up in practice

- A tab reporting `w=0 h=0` in `page_info()` has not laid out yet. Call `wait_for_load()` first.
- `list_tabs()` includes internal `about:` pages. `list_tabs(include_chrome=False)` drops them.
- Re-read element rects after opening a dropdown or a modal, before clicking by coordinate.
- Tabs live in the session, so a tab opened by one program is there for the next one. Close each
  tab you finish with: a session that accumulates tabs slows every later program down.
