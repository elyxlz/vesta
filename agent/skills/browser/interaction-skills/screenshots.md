# Screenshots

`capture_screenshot(path=None, full=False, max_dim=None)` writes a PNG and returns its path. With
no `path`, the file lands in the session's artifact directory, and the result's `artifacts` list
names it with its size. The path is a file: read it with the Read tool to see the image.

```python
new_tab("https://example.com")
wait_for_load()
print(capture_screenshot(max_dim=1200))
```

Images are costly in context, so take fewer and smaller ones:

- Pass `max_dim` to cap the longest side, on a standard session: the Chromium route resizes to it,
  and a stealth session accepts the argument without resizing. A full-resolution capture of a wide
  page rarely earns its size.
- `full=True` captures the whole scrollable page rather than the viewport. Use it to read a long
  page in one shot, not to look at one control.
- Read the DOM instead when text is what you want: `js("document.body.innerText")` costs a fraction
  of an image and is exact.
- One screenshot per decision. When a click failed, one capture tells you why; a capture after each
  step tells you the same thing five times.
