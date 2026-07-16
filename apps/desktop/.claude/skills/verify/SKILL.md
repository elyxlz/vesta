---
name: verify
description: Build, launch, and drive the Vesta Electron desktop app headlessly over CDP to verify changes (renders, preload bridge, store, oauth loopback).
---

# Verify the desktop app

Build the final tree and package an unpacked app (fast, no dmg):

```bash
(cd apps && npm install && npm -w @vesta/web run build)
(cd apps/desktop && npx tsc && npx electron-builder --dir --publish never)
```

Launch with the DevTools protocol enabled (works headless-ish, no window interaction needed):

```bash
apps/desktop/dist/mac-arm64/Vesta.app/Contents/MacOS/Vesta --remote-debugging-port=9223 &
```

Then drive it with a Node script (Node 22 has global `WebSocket`, no deps): fetch `http://127.0.0.1:9223/json/list`, connect to the page's `webSocketDebuggerUrl`, and use `Runtime.evaluate` (with `awaitPromise: true, returnByValue: true`) and `Page.captureScreenshot`.

What to check:

- `PAGE_URL` should be `vesta://bundle/...` (custom protocol serving `resources/web` with SPA fallback).
- `window.vestaNative` exists; `.platform === "darwin"`; root element classes `desktop vibrancy light` + `data-platform=macos`.
- Store round trip through real IPC: `storeWrite` → `storeRead` → `storeClear` (writes `~/Library/Application Support/Vesta/connection.json`).
- Oauth loopback: register `onOauthCallback`, call `oauthStart()` for the port, then hit `http://127.0.0.1:<port>/cb?code=x&state=y` **from the shell with curl** (the renderer itself cannot fetch plain http from the secure `vesta://` origin — mixed content), assert the callback fired with the full URL, then `oauthCancel(port)`.
- `openExternal("file:///...")` must reject (http/https-only guard in main).

Gotchas:

- `timeout` is not on macOS PATH; background the app, `sleep`, `kill $(cat pid)`.
- Ignore CoreText/IMKClient/ViewBridge stderr noise; the dev-mode CSP warning disappears in packaged builds.
- Dev flow instead: `npm -w @vesta/desktop run dev` from `apps/` (vite on http://localhost:1420 + electron).
