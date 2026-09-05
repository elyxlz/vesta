# Browser setup

Run these steps once, at activation. During a task, drive the browser with `browser exec` and fix a
broken install through Recovery below; never run an install step in the middle of a user's request.

## 1. Install the CLI

```bash
uv tool install --editable ~/agent/skills/browser/cli
```

Provides the `browser` command. Re-run it whenever `[project.scripts]` in `cli/pyproject.toml`
gains a command: an editable install picks up code changes on its own, but a new console script
exists only after a reinstall.

## 2. Build the two engine environments

Each engine runs in its own locked environment, so build both:

```bash
uv sync --frozen --project ~/agent/skills/browser/engines/chromium
uv sync --frozen --project ~/agent/skills/browser/engines/camoufox
```

## 3. Confirm the browser binaries

```bash
ls /usr/bin/chromium
ls /opt/camoufox/*/camoufox
```

When either is missing, install both:

```bash
~/agent/skills/browser/install-engines.sh
```

The script installs Debian's chromium, the pinned Camoufox bundle under `/opt/camoufox/<tag>/`,
and the display packages (`Xvfb`, `openbox`, `x11vnc`, `websockify`, `novnc`), verifies the
Camoufox download, and is safe to re-run: a binary already present is left alone.

## 4. Start the daemon

```bash
browser daemon start
```

Idempotent (a running daemon is a no-op). Check it with `browser daemon status`, which reads the
pid record at `~/agent/data/daemons/browser.pid` and reports `"port": null`, because this daemon
serves a unix socket and registers a port only for the duration of a handover.

Then add this line to `~/agent/skills/restart/daemons.sh`, as the `restart` skill describes:

```
browser daemon start
```

## 5. Confirm both routes

```bash
browser doctor
```

`data.engines.routes.standard.ready`, `data.engines.routes.stealth.ready`, and
`data.engines.display.ready` in the report must all be `true`. A `false` route names the file it
could not find, which points back at step 2 or step 3; a `false` display names the missing package
under `data.engines.display.missing`, which points back at step 3.

## Runtime paths

| What | Where |
| --- | --- |
| Daemon socket | `~/agent/data/browser/browser.sock` |
| Session profiles | `~/agent/data/browser/profiles/<engine>/<session>/` |
| Session scratch | `~/agent/data/browser/sessions/<session>/` |
| Screenshots | `~/agent/data/browser/artifacts/<session>/`, pruned after 7 days |
| Daemon log | `~/agent/logs/browser.log` |
| Chromium | `/usr/bin/chromium` |
| Camoufox | `/opt/camoufox/<tag>/camoufox` |
| Engine environments | `~/agent/skills/browser/engines/<engine>/.venv/` |

A profile directory is what makes a session durable: it holds the cookies and the sign-in, and it
survives a daemon restart. Deleting one signs that session out.

Six environment variables point the daemon at other binaries, for a host that keeps them elsewhere:
`VESTA_BROWSER_CHROMIUM`, `VESTA_BROWSER_BROWSER_USE`, `VESTA_BROWSER_CAMOUFOX_PYTHON`,
`VESTA_BROWSER_CAMOUFOX_EXE`, `VESTA_BROWSER_NOVNC_DIR`, `VESTA_BROWSER_X11_DIR`. The defaults in
the table are what the image ships, so leave them unset here.

## Handover requirements

Every session opens its own headed display, an Xvfb plus an `openbox` window manager, from its
first `browser exec`; the image installs both. `browser handover start` additionally streams that
display to the user in their own browser, so it needs three more things:

1. `VESTAD_PUBLIC_URL` and `AGENT_NAME` in the daemon's environment. vestad supplies both to
   this container; a handover started while either one is unset answers `handover_failed`.
2. `x11vnc`, `websockify`, and `/usr/share/novnc`, the stream pieces the handover adds on top of
   the display every session already runs, which the image installs alongside the display
   packages. Elsewhere, one line covers both sets: `apt-get install -y xvfb openbox x11vnc novnc`.
3. `data.handover.ready` of `true` in `browser doctor`, which lists any missing piece under
   `data.handover.missing`. `data.engines.display.ready` covers the display packages instead,
   since every session needs them, not only a handover.

## Recovery

```bash
browser doctor                 # binaries, versions, sessions, display and handover readiness, last error
browser daemon restart         # a daemon that answers nothing or answers wrong
browser stop-all               # stop every session's browser; the profiles stay
tail -50 ~/agent/logs/browser.log
```

`browser stop-all` is the answer to a session wedged on a page, to memory pressure from several
live browsers, and to a program that leaves a browser in a state you cannot read. The next
`browser exec` starts that session again from its profile.
