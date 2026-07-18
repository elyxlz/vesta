# Cloudflare 403 that curl can never win (JS challenge)

When a site returns **HTTP 403 to curl but works in a browser**, do NOT waste time cycling
User-Agents and headers. Diagnose the block type first, in one request:

```bash
curl -sI --max-time 15 -A "Mozilla/5.0 ... Chrome/120 Safari/537.36" "$URL" \
  | grep -iE "server|cf-mitigated|cf-ray|set-cookie"
```

**If you see `cf-mitigated: challenge`** (and the body says "Just a moment" /
"Enable JavaScript" / `challenge-platform`), it is a **Cloudflare JavaScript challenge**,
not UA sniffing. Proof it's not headers: a full browser UA + Accept/Accept-Language headers
still returns 403 (verified on whatson.bfi.org.uk, Jul 2026). Cloudflare serves an
interstitial whose JS computes a token, sets a `cf_clearance` cookie, then reloads. curl
cannot execute JS, so it is stuck on the challenge forever regardless of headers.

**Fix: use a real browser** (`browser launch --stealth`, DISPLAY=:77). It runs the challenge
JS, gets `cf_clearance`, and every subsequent request in that session works. This is *why*
"just use the browser" works here; it is the only thing that can pass the challenge.

**Distinguish from a plain 403** (no `cf-mitigated` header, no JS-challenge body): that IS
usually UA / header / IP based, and a spoofed UA or a different egress may fix it without a
browser. Check the header before reaching for the heavy tool.

Sites confirmed on the JS-challenge path: whatson.bfi.org.uk (BFI IMAX booking + search
endpoints). Any unattended poller against such a site must drive a stealth browser, not curl.
