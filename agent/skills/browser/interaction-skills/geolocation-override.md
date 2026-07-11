# Geolocation override (beat region-locked location pickers)

Some sites scope their "find a store / service near you" search to the **account or site region**, not
to a typed address. Symptom: you type a foreign city/postcode into the location field and it either
rejects it ("please enter the entire address") or the autocomplete only returns places in the *wrong*
country. Real example (2026): Apple's `getsupport.apple.com` Genius Bar store picker on a UK-region
account refused every Rome address and only autocompleted UK results, so booking an Italian store was
impossible through the text field.

The fix is to stop fighting the text field and instead spoof the browser's **geolocation**, then click
the site's own **"Use my current location"** button. The site geocodes the coordinates and returns the
right country's results directly.

```python
browser <<'PY'
# 1. grant the origin geolocation permission (else the browser blocks the API)
cdp("Browser.grantPermissions", origin="https://getsupport.apple.com", permissions=["geolocation"])
# 2. override the position to your target (lat, lon). Rome city centre here.
cdp("Emulation.setGeolocationOverride", latitude=41.9028, longitude=12.4810, accuracy=50)
# 3. now click the site's own "Use my current location" control
click(472, 349)   # or click a ref
wait(5)
PY
```

Notes:
- `accuracy` in metres; a small value (~50) reads as a confident fix.
- Grant the permission to the exact origin the page runs on, or the `navigator.geolocation` call still prompts/blocks.
- Coordinates beat addresses: pick the city centre or the specific store's lat/lon. A few common ones:
  Rome 41.9028, 12.4964 · London 51.5074, -0.1278 · NYC 40.7128, -74.0060 · Milan 45.4642, 9.1900.
- This only helps when the site exposes a "use my location" path. If it's address-only, you still need
  the text field (try clicking the field's far-right edge first so the cursor lands at the end, then
  backspace to clear, many shadow-DOM inputs ignore Ctrl+A / JS value-set but honour real keystrokes).
- To undo: `cdp("Emulation.clearGeolocationOverride")`.
