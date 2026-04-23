"""Post-launch stealth: UA scrub, navigator.webdriver hide, Cloudflare Turnstile solver.

`apply_to_session` is called by the daemon right after attaching to a page.
`solve_cf_turnstile` is an agent-callable helper for stubborn CF challenges.
"""

from __future__ import annotations

import asyncio
import sys

WEBDRIVER_HIDE_JS = "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"

# Also nudge a few fingerprint surfaces that headless Chrome leaves too obvious.
FINGERPRINT_SOFTEN_JS = """
(() => {
  try { Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] }); } catch(_) {}
  try { Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] }); } catch(_) {}
})();
"""


async def _call(cdp, method: str, params: dict | None = None, session_id: str | None = None):
    try:
        await asyncio.wait_for(cdp.send_raw(method, params or {}, session_id=session_id), timeout=3)
    except Exception as e:
        print(f"[vesta-browser] stealth {method} failed: {e}", file=sys.stderr)


async def apply_to_session(cdp, session_id: str, ua: str | None = None) -> None:
    """Apply webdriver hide + fingerprint softening + optional UA override.

    Call after attaching the session and enabling Page/Runtime domains.
    """
    await _call(
        cdp,
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": WEBDRIVER_HIDE_JS + "\n" + FINGERPRINT_SOFTEN_JS},
        session_id=session_id,
    )
    # Apply immediately to the current document too.
    await _call(cdp, "Runtime.evaluate", {"expression": WEBDRIVER_HIDE_JS}, session_id=session_id)
    if ua and "Headless" in ua:
        cleaned = ua.replace("Headless", "")
        await _call(
            cdp,
            "Emulation.setUserAgentOverride",
            {"userAgent": cleaned, "platform": "Linux"},
            session_id=session_id,
        )


def solve_cf_turnstile(timeout: float = 20.0, poll: float = 0.5) -> bool:
    """Best-effort Cloudflare Turnstile challenge click. Returns True if we clicked.

    This is the kind of helper the agent should edit when it discovers a site-specific
    variant. The fallback pattern: find the challenge iframe, click its center.
    """
    import time

    from .helpers import js, click

    deadline = time.time() + timeout
    while time.time() < deadline:
        # Is a CF challenge visible?
        found = js(
            "(() => {"
            "  const ifr = Array.from(document.querySelectorAll('iframe'))"
            "    .find(f => /challenges\\.cloudflare\\.com/i.test(f.src||''));"
            "  if (!ifr) return null;"
            "  const r = ifr.getBoundingClientRect();"
            "  return {x: r.left + r.width/2, y: r.top + r.height/2, w: r.width, h: r.height};"
            "})()"
        )
        if found and "w" in found and found["w"] > 50:
            # Click the center of the challenge iframe; CDP compositor click goes through.
            click(found["x"], found["y"])
            time.sleep(2.0)
            # Confirm the challenge is gone.
            still = js("document.querySelector('iframe[src*=\"challenges.cloudflare.com\"]') !== null")
            if not still:
                return True
        time.sleep(poll)
    return False
