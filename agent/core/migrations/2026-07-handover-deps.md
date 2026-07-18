Your browser skill's handover flow (handing your live browser to your user so they
sign in by hand, the fallback for sites that gate on account trust rather than
fingerprint) shells out to Xvfb, x11vnc, openbox and websockify, and serves noVNC's
client assets. The agent image now installs all four at build time, but a container
created before that never picks them up: a new image only reaches newly created
containers, never a running one. Without them `browser handover start` refuses to
run, so that fallback is simply unavailable to you.

This migration installs them. It is a no-op if they are already present, and safe
to run more than once.

### 1. Install the handover packages if any are missing

```bash
if ! command -v Xvfb >/dev/null 2>&1 || ! command -v x11vnc >/dev/null 2>&1 \
   || ! command -v openbox >/dev/null 2>&1 || ! command -v websockify >/dev/null 2>&1 \
   || [ ! -f /usr/share/novnc/core/rfb.js ]; then
  apt-get update && apt-get install -y --no-install-recommends xvfb novnc x11vnc openbox
  rm -rf /var/lib/apt/lists/*
fi
```

### 2. Check it took

Only if you have the browser skill installed:

```bash
browser doctor
```

The `handover` block should read `"ready": true` with nothing under `missing`. If
something is still listed, mention it in your next message so your user knows
handover is not available yet. Nothing is lost either way: `browser handover start`
names the exact apt line to run whenever you next reach for it.
