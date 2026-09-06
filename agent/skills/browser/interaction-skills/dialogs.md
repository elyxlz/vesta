# Dialogs

Browser dialogs (`alert`, `confirm`, `prompt`, `beforeunload`) freeze the JS thread. Two approaches depending on timing.

## Detection

On Chromium, `page_info()` surfaces an open dialog: it returns `{"dialog": {"type", "message", ...}}` instead of the usual viewport dict, because the page's JS is frozen anyway. So when `page_info()` after an action carries a `dialog` key, answer it before doing anything else. On Camoufox, a dialog is announced to a handler you register on `page` and never to `page_info()`, so register it first (below).

## Reactive: answer the dialog through the engine

Each engine has its own call, and both work while the page's JS is frozen.

On Chromium, `page_info()` reports `{"dialog": {"type", "message", ...}}` while one is open, and
`cdp` answers it:

```python
info = page_info()
if "dialog" in info:
    print(info["dialog"]["message"])
    cdp("Page.handleJavaScriptDialog", accept=True)  # OK
    # cdp("Page.handleJavaScriptDialog", accept=False)  # Cancel
    # cdp("Page.handleJavaScriptDialog", accept=True, promptText="hi")  # answer a prompt()
```

On Camoufox, register a handler on `page` before the action that raises the dialog. An unhandled
dialog is dismissed automatically, so the page never freezes but the answer is always "cancel":

```python
page.on("dialog", lambda d: d.accept())
click_at_xy(320, 180)
```

Neither call injects anything into the page, so neither is visible to the site.

## Proactive: stub via JS

Prevents dialogs from ever appearing. Good when you expect multiple `alert()`/`confirm()` calls in sequence.

```python
js("""
window.__dialogs__=[];
window.alert=m=>window.__dialogs__.push(String(m));
window.confirm=m=>{window.__dialogs__.push(String(m));return true;};
window.prompt=(m,d)=>{window.__dialogs__.push(String(m));return d||'';};
""")
# ... do actions that trigger dialogs ...
msgs = js("window.__dialogs__||[]")
```

Tradeoffs:
- Stubs are lost on page navigation -- must re-run the snippet
- `confirm()` always returns `true` (auto-approves)
- Detectable by antibot (`window.alert.toString()` reveals non-native code)
- Does NOT handle `beforeunload`

## beforeunload specifically

Fires when navigating away from a page with unsaved changes (forms, editors, upload pages). The page freezes until the user clicks Leave/Stay.

```python
# Option A: answer it after navigating (engine-level, invisible to the site)
goto_url("https://new-url.com")
if "dialog" in page_info():
    cdp("Page.handleJavaScriptDialog", accept=True)  # Chromium: click "Leave"

# Option B: prevent it before navigating (JS injection, detectable)
js("window.onbeforeunload=null")
goto_url("https://new-url.com")
```

On Camoufox, `page.on("dialog", lambda d: d.accept())` before the navigation does the same job as
option A.
