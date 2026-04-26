"""
GPTZero scorer (reverse-engineered) with proxy rotation + top-N AI sentences.

Calls the same endpoint as the free web demo at https://gptzero.me/.

Auth model
----------
GPTZero gates the API behind an anonymous Supabase JWT. To get one, you must visit
the site once in a real browser and pass Cloudflare Turnstile (the captcha). After
that, the access_token (1h) and refresh_token (rotating) are cached locally and
the refresh_token is enough to mint new access_tokens without any captcha for as
long as the project keeps issuing them. So the bootstrap is once-per-session,
everything after that is plain `requests`.

Endpoints
---------
1. (bootstrap, browser only) https://gptzero.me/  -> Cloudflare/Turnstile
2. POST https://lydqhgdzhvsqlcobdfxi.supabase.co/auth/v1/token?grant_type=refresh_token
3. POST https://api.gptzero.me/v3/scan
4. POST https://api.gptzero.me/v3/ai/text

Cache layout
------------
~/.gptzero/session.json     anonymous JWT (access + refresh)
~/.gptzero/proxy.json       optional proxy config (see PROXY CONFIG below)
~/.gptzero/proxy_state.json runtime cache of which proxies recently worked

Proxy rotation (per-IP rate limit mitigation)
---------------------------------------------
On 429, the scorer cycles through proxies in this priority order:
  1. proxies recently observed to work (cached)
  2. user-supplied proxies from ~/.gptzero/proxy.json or HTTP(S)_PROXY env var
  3. Tor SOCKS5 (127.0.0.1:9050) if reachable, with NEWNYM rotation per 429
  4. free-proxy aggregator lists (fetched on demand, validated)
  5. raw direct connection (no proxy) as a last resort

PROXY CONFIG (~/.gptzero/proxy.json), all fields optional:
{
  "proxies": ["http://user:pass@host:port", "socks5://host:port", ...],
  "use_tor": true,
  "use_free_lists": true,
  "use_direct": true
}

Top-N AI passages
-----------------
Pass `--top N` to get the most AI-like sentences (or paragraphs with `--by paragraph`):
    python gptzero.py file.md --top 10
    python gptzero.py file.md --top 5 --by paragraph

Returns a JSON like:
    {"summary": {...}, "top_offenders": [{"rank":1, "text":"...", "generated_prob":0.94, ...}]}

Usage
-----
As a library:
    from gptzero import score, top_offenders
    result = score("Some text...")
    print(result["documents"][0]["class_probabilities"])
    print(top_offenders(result, n=10))

As a CLI:
    python gptzero.py file.md                       # full JSON
    python gptzero.py file.md --score               # just AI prob (0..1)
    python gptzero.py file.md --top 10              # top-10 AI sentences as JSON
    python gptzero.py file.md --top 5 --by paragraph
    python gptzero.py --refresh                     # force-refresh JWT
    python gptzero.py --set-tokens ACCESS REFRESH   # seed JWT manually

Bootstrapping
-------------
First run will try to load a cached JWT. If none exists, it will try to bootstrap
by driving Chromium via CDP at https://gptzero.me/. This requires:
  - Chromium installed (apt: chromium)
  - DISPLAY set to an X server (Xvfb works); the script will start `Xvfb :99` if
    nothing is reachable
  - websocket-client (`pip install websocket-client`)
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

import requests

CACHE_DIR = Path.home() / ".gptzero"
CACHE_FILE = CACHE_DIR / "session.json"
PROXY_FILE = CACHE_DIR / "proxy.json"
PROXY_STATE_FILE = CACHE_DIR / "proxy_state.json"

SUPABASE_URL = "https://lydqhgdzhvsqlcobdfxi.supabase.co"
SUPABASE_PUBLISHABLE_KEY = "sb_publishable_-TRlvcmoZ3y9LvkQys7Vcg_TImPL6et"
API_BASE = "https://api.gptzero.me"

DEFAULT_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"),
    "Origin": "https://app.gptzero.me",
    "Referer": "https://app.gptzero.me/",
    "x-gptzero-platform": "webapp",
    "x-page": "/",
    "Accept": "*/*",
    "Content-Type": "application/json",
}


# ---------------------------------------------------------------------------
# token cache
# ---------------------------------------------------------------------------


def _load_cache() -> dict | None:
    try:
        return json.loads(CACHE_FILE.read_text())
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _save_cache(d: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(d, indent=2))
    os.chmod(CACHE_FILE, 0o600)


def _decode_jwt_exp(token: str) -> int | None:
    try:
        payload = token.split(".")[1]
        payload += "=" * ((4 - len(payload) % 4) % 4)
        return int(json.loads(base64.urlsafe_b64decode(payload))["exp"])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# proxy management
# ---------------------------------------------------------------------------


def _proxy_dict(url: str | None) -> dict | None:
    if not url:
        return None
    return {"http": url, "https": url}


def _load_proxy_config() -> dict:
    cfg: dict = {
        "proxies": [],
        "use_tor": True,
        "use_free_lists": True,
        "use_direct": True,
    }
    try:
        cfg.update(json.loads(PROXY_FILE.read_text()))
    except FileNotFoundError:
        pass
    except Exception as e:
        sys.stderr.write(f"[gptzero] could not read {PROXY_FILE}: {e}\n")
    # env var support
    for env_key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        v = os.environ.get(env_key)
        if v and v not in cfg["proxies"]:
            cfg["proxies"].insert(0, v)
    return cfg


def _load_proxy_state() -> dict:
    try:
        return json.loads(PROXY_STATE_FILE.read_text())
    except Exception:
        return {"good": [], "bad": {}}


def _save_proxy_state(state: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        PROXY_STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception:
        pass


def _tor_reachable(host: str = "127.0.0.1", port: int = 9050) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except Exception:
        return False


def _tor_newnym(host: str = "127.0.0.1", port: int = 9051) -> bool:
    """Ask Tor for a fresh circuit. Best-effort, ignore errors."""
    try:
        with socket.create_connection((host, port), timeout=2) as s:
            s.sendall(b'AUTHENTICATE ""\r\n')
            resp = s.recv(256)
            if not resp.startswith(b"250"):
                return False
            s.sendall(b"SIGNAL NEWNYM\r\n")
            resp = s.recv(256)
            return resp.startswith(b"250")
    except Exception:
        return False


def _fetch_free_proxies(timeout: float = 8) -> list[str]:
    """Pull a candidate list from a few free aggregators. Best-effort."""
    out: list[str] = []
    sources = [
        "https://www.proxy-list.download/api/v1/get?type=https",
        "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    ]
    for url in sources:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
                body = r.read().decode("utf-8", "replace")
            for line in body.splitlines():
                line = line.strip()
                if not line or ":" not in line:
                    continue
                # accept "host:port" and full URLs
                if line.startswith("http://") or line.startswith("https://") or line.startswith("socks"):
                    out.append(line)
                else:
                    out.append(f"http://{line}")
        except Exception:
            continue
        if len(out) > 200:
            break
    # dedupe, keep order
    seen = set()
    uniq = []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq[:200]


def _proxy_chain(use_free: bool = True) -> list[str | None]:
    """Build the ordered list of proxies to try.

    Each entry is either a proxy URL or None (meaning "direct, no proxy").
    """
    cfg = _load_proxy_config()
    state = _load_proxy_state()
    chain: list[str | None] = []

    def add(p):
        if p in chain:
            return
        chain.append(p)

    # 1. recently-good proxies first
    for p in state.get("good", []):
        add(p)
    # 2. user-supplied proxies (config + env)
    for p in cfg.get("proxies", []):
        add(p)
    # 3. Tor
    if cfg.get("use_tor", True) and _tor_reachable():
        add("socks5h://127.0.0.1:9050")
    # 4. direct (only if user opted in; tried before free lists since direct is
    #    fastest when the IP isn't rate-limited)
    if cfg.get("use_direct", True):
        add(None)
    # 5. free proxy aggregators (slow, unreliable; only on demand)
    if use_free and cfg.get("use_free_lists", True):
        for p in _fetch_free_proxies():
            add(p)
    return chain


def _mark_proxy_good(p: str | None) -> None:
    state = _load_proxy_state()
    label = p or "DIRECT"
    good = state.get("good", [])
    if label in good:
        good.remove(label)
    good.insert(0, label)
    state["good"] = good[:8]
    _save_proxy_state(state)


def _mark_proxy_bad(p: str | None, reason: str) -> None:
    state = _load_proxy_state()
    label = p or "DIRECT"
    state.setdefault("bad", {})[label] = {"reason": reason, "ts": int(time.time())}
    # also drop from good
    state["good"] = [g for g in state.get("good", []) if g != label]
    _save_proxy_state(state)


def _good_to_url(label: str) -> str | None:
    return None if label == "DIRECT" else label


# ---------------------------------------------------------------------------
# Xvfb / display helpers
# ---------------------------------------------------------------------------


def _x_display_reachable(disp: str) -> bool:
    return subprocess.run(["xdpyinfo", "-display", disp], capture_output=True).returncode == 0


def _ensure_display() -> str:
    """Return an X DISPLAY string, starting Xvfb :99 if nothing else works."""
    cur = os.environ.get("DISPLAY", "").strip()
    if cur and _x_display_reachable(cur):
        return cur
    for disp in (":88", ":99", ":0"):
        if _x_display_reachable(disp):
            os.environ["DISPLAY"] = disp
            return disp
    # start Xvfb :99 in a screen session so it survives this process
    sys.stderr.write("[gptzero] starting Xvfb :99\n")
    subprocess.run(
        [
            "screen",
            "-dmS",
            "xvfb",
            "Xvfb",
            ":99",
            "-screen",
            "0",
            "1920x1080x24",
            "-ac",
        ],
        check=False,
    )
    for _ in range(20):
        time.sleep(0.5)
        if _x_display_reachable(":99"):
            os.environ["DISPLAY"] = ":99"
            return ":99"
    raise RuntimeError("Could not obtain an X display (tried :88, :99, :0; failed to start Xvfb).")


# ---------------------------------------------------------------------------
# refresh + bootstrap
# ---------------------------------------------------------------------------


def _refresh_session(refresh_token: str, proxy: str | None = None) -> dict:
    r = requests.post(
        f"{SUPABASE_URL}/auth/v1/token",
        params={"grant_type": "refresh_token"},
        headers={
            "apikey": SUPABASE_PUBLISHABLE_KEY,
            "Authorization": f"Bearer {SUPABASE_PUBLISHABLE_KEY}",
            "Content-Type": "application/json",
        },
        json={"refresh_token": refresh_token},
        proxies=_proxy_dict(proxy),
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_at": data["expires_at"],
    }


def _bootstrap_from_existing_cdp(port: int = 9222, timeout: int = 60) -> dict | None:
    """If a Chromium with --remote-debugging-port is already running (e.g. the
    user's general browser on 9222), reuse it: open a new tab on
    app.gptzero.me, wait for the Supabase JWT to land in localStorage, also
    grab all api.gptzero.me cookies (csrf, anonymousUserId, etc), and return.
    Returns None on failure so the caller can fall through to launching its
    own Chromium.

    NOTE: gptzero.me itself does NOT mint a JWT on load (no localStorage entry
    until the user types a check). app.gptzero.me does, immediately. Use the
    app subdomain.
    """
    try:
        import websocket  # type: ignore
    except ImportError:
        return None
    try:
        urllib.request.urlopen(  # noqa: S310
            f"http://127.0.0.1:{port}/json/version", timeout=2
        )
    except Exception:
        return None
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/json/new?https://app.gptzero.me/",
            method="PUT",
        )
        data = json.loads(urllib.request.urlopen(req, timeout=5).read())  # noqa: S310
    except Exception as e:
        sys.stderr.write(f"[gptzero] could not open tab on port {port}: {e}\n")
        return None
    ws_url = data.get("webSocketDebuggerUrl")
    if not ws_url:
        return None
    try:
        ws = websocket.create_connection(ws_url, timeout=15, suppress_origin=True)
    except Exception as e:
        sys.stderr.write(f"[gptzero] could not attach to existing browser: {e}\n")
        return None
    mid = 0

    def call(method, **params):
        nonlocal mid
        mid += 1
        ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            d = json.loads(ws.recv())
            if d.get("id") == mid:
                return d.get("result", {})

    try:
        call("Network.enable")
        call("Page.enable")
        call("Runtime.enable")
        token = None
        for _ in range(timeout):
            time.sleep(1.0)
            r = call(
                "Runtime.evaluate",
                expression="localStorage.getItem('sb-lydqhgdzhvsqlcobdfxi-auth-token')",
                returnByValue=True,
            )
            res = r.get("result", {})
            if res.get("subtype") == "error":
                continue
            v = res.get("value")
            if v:
                try:
                    parsed = json.loads(v)
                    if parsed.get("access_token"):
                        token = parsed
                        break
                except Exception:
                    pass
        if not token:
            return None
        # Pull all api.gptzero.me cookies too
        cookies_resp = call(
            "Network.getCookies",
            urls=[
                "https://api.gptzero.me/",
                "https://app.gptzero.me/",
                "https://gptzero.me/",
            ],
        )
        cookies = {}
        for c in cookies_resp.get("cookies", []):
            cookies[c["name"]] = c["value"]
        return {
            "access_token": token["access_token"],
            "refresh_token": token["refresh_token"],
            "expires_at": token.get("expires_at", int(time.time()) + 3600),
            "cookies": cookies,
        }
    finally:
        with contextlib.suppress(Exception):
            ws.close()
        with contextlib.suppress(Exception):
            urllib.request.urlopen(  # noqa: S310
                f"http://127.0.0.1:{port}/json/close/{data['id']}", timeout=3
            )


def _bootstrap_via_browser(proxy: str | None = None) -> dict:
    """Drive Chromium via CDP to load app.gptzero.me, scrape JWT from
    localStorage. Tries an existing browser first (port 9222), then launches
    its own."""
    # 1. fast path: reuse an existing browser with CDP exposed
    if proxy is None:  # only reuse direct-IP browser if no proxy requested
        for port in (9222, 9221, 9223):
            cached = _bootstrap_from_existing_cdp(port=port, timeout=30)
            if cached:
                sys.stderr.write(f"[gptzero] bootstrapped via existing browser at :{port}\n")
                return cached

    try:
        import websocket  # type: ignore
    except ImportError as e:
        raise RuntimeError("Bootstrap requires `websocket-client`. Install with `pip install websocket-client`.") from e

    chromium = None
    for c in ("chromium", "chromium-browser", "google-chrome"):
        if subprocess.run(["which", c], capture_output=True).returncode == 0:
            chromium = c
            break
    if chromium is None:
        raise RuntimeError("No Chromium binary found. Install with `apt install chromium`.")

    display = _ensure_display()

    # clean stale sentinel files that block fresh user-data-dirs sometimes
    port = 9237
    profile = f"/tmp/gptzero-cdp-{os.getpid()}-{int(time.time())}"
    args = [
        chromium,
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile}",
        "--disable-blink-features=AutomationControlled",
    ]
    if proxy:
        args.append(f"--proxy-server={proxy}")
    args.append("about:blank")

    env = os.environ.copy()
    env["DISPLAY"] = display

    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    try:
        # wait for CDP (longer window: chromium is slow on first launch)
        ok = False
        last_err = None
        for _ in range(60):
            try:
                urllib.request.urlopen(  # noqa: S310
                    f"http://127.0.0.1:{port}/json/version", timeout=1
                )
                ok = True
                break
            except Exception as e:
                last_err = e
                # if process died early, abort
                if proc.poll() is not None:
                    raise RuntimeError(f"Chromium exited early (rc={proc.returncode}). DISPLAY={display}, proxy={proxy}") from e
                time.sleep(0.5)
        if not ok:
            raise RuntimeError(f"Chromium did not become CDP-reachable at 127.0.0.1:{port} (DISPLAY={display}, last error: {last_err})")

        targets = json.loads(
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json").read()  # noqa: S310
        )
        page = next(t for t in targets if t.get("type") == "page")
        # Connect directly to the page's debugger WS. No Target.attachToTarget
        # needed -- on this WS we're already on the page session, no sessionId.
        ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=120)
        mid = 0

        def call(method, **params):
            nonlocal mid
            mid += 1
            msg = {"id": mid, "method": method, "params": params}
            ws.send(json.dumps(msg))
            while True:
                d = json.loads(ws.recv())
                if d.get("id") == mid:
                    if "error" in d:
                        raise RuntimeError(f"{method}: {d['error']}")
                    return d.get("result", {})

        call("Page.enable")
        call("Runtime.enable")
        call("Page.navigate", url="https://app.gptzero.me/")

        token = None
        for _ in range(90):
            time.sleep(1.0)
            r = call(
                "Runtime.evaluate",
                expression="localStorage.getItem('sb-lydqhgdzhvsqlcobdfxi-auth-token')",
                returnByValue=True,
            )
            v = r.get("result", {}).get("value")
            if v:
                try:
                    parsed = json.loads(v)
                    if parsed.get("access_token"):
                        token = parsed
                        break
                except Exception:
                    pass
        if not token:
            raise RuntimeError("Browser bootstrap timed out without finding a JWT.")
        # also grab cookies (for api.gptzero.me csrf etc)
        try:
            call("Network.enable")
            cookies_resp = call(
                "Network.getCookies",
                urls=[
                    "https://api.gptzero.me/",
                    "https://app.gptzero.me/",
                    "https://gptzero.me/",
                ],
            )
            cookies = {c["name"]: c["value"] for c in cookies_resp.get("cookies", [])}
        except Exception:
            cookies = {}
        return {
            "access_token": token["access_token"],
            "refresh_token": token["refresh_token"],
            "expires_at": token.get("expires_at", int(time.time()) + 3600),
            "cookies": cookies,
        }
    finally:
        with contextlib.suppress(Exception):
            proc.terminate()
            proc.wait(5)
        with contextlib.suppress(Exception):
            proc.kill()


def _get_access_token(force_refresh: bool = False, proxy: str | None = None) -> str:
    cache = _load_cache()
    now = int(time.time())

    if cache and not force_refresh and cache.get("expires_at", 0) - now > 60:
        return cache["access_token"]

    if cache and cache.get("refresh_token"):
        try:
            new = _refresh_session(cache["refresh_token"], proxy=proxy)
            _save_cache(new)
            return new["access_token"]
        except requests.HTTPError as e:
            sys.stderr.write(f"[gptzero] refresh failed ({e}), falling through to bootstrap\n")
        except Exception as e:
            sys.stderr.write(f"[gptzero] refresh error ({e}), falling through to bootstrap\n")

    new = _bootstrap_via_browser(proxy=proxy)
    _save_cache(new)
    return new["access_token"]


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------


class GPTZeroError(RuntimeError):
    pass


class GPTZeroRateLimited(GPTZeroError):
    pass


def _request_with_proxies(
    fn,
    proxies: list[str | None],
    *,
    label: str,
) -> tuple[Any, str | None]:
    """Try `fn(proxy)` against each proxy until one succeeds.

    `fn` should raise GPTZeroRateLimited on 429, requests.HTTPError or any
    other exception on transient failure. Returns (result, proxy_used).
    """
    last_err: Exception | None = None
    for idx, p in enumerate(proxies):
        try:
            sys.stderr.write(f"[gptzero] {label}: trying proxy {idx + 1}/{len(proxies)} ({p or 'DIRECT'})\n")
            res = fn(p)
            _mark_proxy_good(p)
            return res, p
        except GPTZeroRateLimited as e:
            last_err = e
            _mark_proxy_bad(p, "429")
            # if Tor, ask for a new circuit before bailing out of this proxy
            if p and p.startswith("socks5") and "9050" in p:
                _tor_newnym()
                # one more attempt on Tor with the new circuit
                try:
                    res = fn(p)
                    _mark_proxy_good(p)
                    return res, p
                except Exception as e2:
                    last_err = e2
            continue
        except Exception as e:
            last_err = e
            _mark_proxy_bad(p, str(e)[:120])
            continue
    raise GPTZeroError(
        f"{label}: exhausted all {len(proxies)} proxies. "
        f"Last error: {last_err}. "
        f"Try: (1) wait for the per-IP limit to reset, "
        f"(2) populate ~/.gptzero/proxy.json with a paid proxy, "
        f"(3) start Tor (`tor &`) for SOCKS5 rotation."
    )


def _full_cookies(access_token: str, extra: dict | None = None) -> dict:
    """Build the full cookie jar to send to api.gptzero.me. The accessToken4
    cookie is the JWT; the api.gptzero.me side also needs csrf + anonymousUserId
    (set by the server on first contact) for /v3/ai/text to authenticate."""
    out = {"accessToken4": access_token}
    if extra:
        out.update(extra)
    return out


def _new_scan_one(access_token: str, proxy: str | None, cookies: dict | None = None) -> str:
    r = requests.post(
        f"{API_BASE}/v3/scan",
        headers=DEFAULT_HEADERS,
        cookies=_full_cookies(access_token, cookies),
        json={"source": "webapp", "title": "Untitled"},
        proxies=_proxy_dict(proxy),
        timeout=30,
    )
    if r.status_code == 401:
        raise GPTZeroError("auth")
    if r.status_code == 429:
        raise GPTZeroRateLimited(f"429 on /v3/scan: {r.text[:200]}")
    r.raise_for_status()
    # capture any new cookies the server sets (e.g. anonymousUserId, csrf)
    new_cookies = {k: v for k, v in r.cookies.items()}
    if cookies is not None:
        cookies.update(new_cookies)
    return r.json()["data"]["id"]


def _predict_one(
    access_token: str,
    scan_id: str,
    text: str,
    multilingual: bool,
    proxy: str | None,
    cookies: dict | None = None,
) -> dict:
    r = requests.post(
        f"{API_BASE}/v3/ai/text",
        headers=DEFAULT_HEADERS,
        cookies=_full_cookies(access_token, cookies),
        json={
            "scanId": scan_id,
            "multilingual": multilingual,
            "document": text,
            "interpretability_required": False,
        },
        proxies=_proxy_dict(proxy),
        timeout=180,
    )
    if r.status_code == 401:
        raise GPTZeroError(f"auth (401): {r.text[:200]}")
    if r.status_code == 429:
        # GPTZero returns 429 with a very specific body for the daily-quota case.
        body = r.text[:300]
        if "guest_user_quota_exceeded" in body or "AI scans per day" in body:
            reset = r.headers.get("ratelimit-reset", "?")
            raise GPTZeroRateLimited(f"guest quota exhausted (7 AI scans / 24h). Resets in ~{reset}s. Need a different IP+session pair.")
        raise GPTZeroRateLimited(f"429 on /v3/ai/text: {body}")
    r.raise_for_status()
    return r.json()


def score(
    text: str,
    multilingual: bool = True,
    use_free_proxies: bool = True,
) -> dict:
    """Run an AI-detection scan on `text` and return the full JSON response.

    Tries the cached/configured proxies in order, advancing on 429. Returns the
    raw GPTZero JSON; see schema reference at the bottom of this file.
    """
    if not text or not text.strip():
        raise ValueError("text is empty")

    proxies = _proxy_chain(use_free=use_free_proxies)
    if not proxies:
        proxies = [None]

    for auth_attempt in range(2):
        force_refresh = auth_attempt == 1
        try:
            token = _get_access_token(force_refresh=force_refresh)
        except Exception as e:
            sys.stderr.write(f"[gptzero] direct token fetch failed: {e}\n")
            token = None
            for p in proxies:
                try:
                    token = _get_access_token(force_refresh=force_refresh, proxy=p)
                    break
                except Exception:
                    continue
            if token is None:
                raise

        # Load cookies from cache (csrf, anonymousUserId, etc) - critical for
        # /v3/ai/text auth. Mutated in place by _new_scan_one as the server
        # sets new ones.
        cache = _load_cache() or {}
        cookies = dict(cache.get("cookies") or {})

        try:
            scan_id, used_proxy = _request_with_proxies(
                lambda p: _new_scan_one(token, p, cookies),
                proxies,
                label="scan-create",
            )
            ordered = [used_proxy] + [p for p in proxies if p != used_proxy]
            result, _ = _request_with_proxies(
                lambda p: _predict_one(token, scan_id, text, multilingual, p, cookies),
                ordered,
                label="ai/text",
            )
            # persist any updated cookies back to cache
            if cookies:
                cache["cookies"] = cookies
                _save_cache(cache)
            return result
        except GPTZeroError as e:
            msg = str(e)
            if msg.startswith("auth") and auth_attempt == 0:
                continue
            raise


# ---------------------------------------------------------------------------
# top-N AI passages
# ---------------------------------------------------------------------------


def _find_offsets(haystack: str, needle: str, start: int = 0) -> tuple[int, int] | None:
    """Locate `needle` inside `haystack` starting at `start`. Falls back to a
    fuzzy search by stripping whitespace differences. Returns (begin, end) or
    None."""
    if not needle:
        return None
    idx = haystack.find(needle, start)
    if idx >= 0:
        return idx, idx + len(needle)
    # fallback: ignore extra whitespace
    import re

    pattern = re.escape(needle.strip())
    pattern = pattern.replace(r"\ ", r"\s+").replace(r"\n", r"\s+")
    m = re.search(pattern, haystack[start:], flags=re.DOTALL)
    if m:
        return start + m.start(), start + m.end()
    # last resort: search from the very beginning
    idx = haystack.find(needle)
    if idx >= 0:
        return idx, idx + len(needle)
    return None


def top_offenders(
    result: dict,
    n: int = 10,
    by: str = "sentence",
    source_text: str | None = None,
) -> dict:
    """Pick the top-N most AI-like sentences (or paragraphs) from a `score()` result.

    Parameters
    ----------
    result : the full GPTZero JSON
    n      : how many entries to return
    by     : "sentence" (default) or "paragraph"
    source_text : the original document; used to compute character offsets. If
                  omitted, offsets are best-effort.
    """
    if by not in ("sentence", "paragraph"):
        raise ValueError("by must be 'sentence' or 'paragraph'")
    doc = result.get("documents", [{}])[0]
    cp = doc.get("class_probabilities", {}) or {}
    summary = {
        "ai_likelihood_overall": cp.get("ai"),
        "human": cp.get("human"),
        "mixed": cp.get("mixed"),
        "predicted_class": doc.get("predicted_class"),
        "confidence_category": doc.get("confidence_category"),
        "completely_generated_prob": doc.get("completely_generated_prob"),
        "average_generated_prob": doc.get("average_generated_prob"),
    }

    sentences = doc.get("sentences") or []
    paragraphs = doc.get("paragraphs") or []

    # Build sentence -> paragraph_index map by walking through paragraphs and
    # checking sentence ranges. GPTZero's paragraph items vary in shape; we look
    # for a sentence-index range or fall back to text containment.
    para_for_sent: list[int] = [-1] * len(sentences)
    if paragraphs and sentences:
        used_explicit = False
        for pi, p in enumerate(paragraphs):
            # GPTZero paragraph shape: {start_sentence_index, num_sentences, ...}
            si = p.get("start_sentence_index")
            num = p.get("num_sentences")
            ei = p.get("end_sentence_index")
            if si is not None and num is not None:
                for i in range(si, si + num):
                    if 0 <= i < len(para_for_sent):
                        para_for_sent[i] = pi
                used_explicit = True
            elif si is not None and ei is not None:
                for i in range(si, ei + 1):
                    if 0 <= i < len(para_for_sent):
                        para_for_sent[i] = pi
                used_explicit = True
            elif "sentence_indexes" in p:
                for i in p.get("sentence_indexes") or []:
                    if 0 <= i < len(para_for_sent):
                        para_for_sent[i] = pi
                used_explicit = True
        if not used_explicit:
            # Fallback: text containment
            for pi, p in enumerate(paragraphs):
                ptext = (p.get("text") or p.get("paragraph") or "").strip()
                if not ptext:
                    continue
                for i, s in enumerate(sentences):
                    if para_for_sent[i] != -1:
                        continue
                    stext = (s.get("sentence") or "").strip()
                    if stext and stext in ptext:
                        para_for_sent[i] = pi

    cursor = 0
    enriched: list[dict] = []
    for i, s in enumerate(sentences):
        text = s.get("sentence") or ""
        gp = s.get("generated_prob")
        if gp is None:
            continue
        offsets = None
        if source_text and text:
            offsets = _find_offsets(source_text, text, start=cursor)
            if offsets:
                cursor = offsets[1]
        enriched.append(
            {
                "sentence_index": i,
                "text": text,
                "generated_prob": gp,
                "class_probabilities": s.get("class_probabilities"),
                "highlight_for_ai": s.get("highlight_sentence_for_ai"),
                "position_chars": list(offsets) if offsets else None,
                "paragraph_index": para_for_sent[i] if i < len(para_for_sent) else -1,
            }
        )

    if by == "sentence":
        ranked = sorted(enriched, key=lambda x: x["generated_prob"], reverse=True)[:n]
        for rank, item in enumerate(ranked, start=1):
            item["rank"] = rank
        return {"summary": summary, "by": "sentence", "top_offenders": ranked}

    # paragraph mode: aggregate generated_prob per paragraph
    buckets: dict[int, list[dict]] = {}
    for item in enriched:
        pi = item["paragraph_index"]
        if pi < 0:
            continue
        buckets.setdefault(pi, []).append(item)

    paragraph_rows: list[dict] = []
    for pi, items in buckets.items():
        probs = [it["generated_prob"] for it in items]
        avg = sum(probs) / len(probs)
        peak = max(probs)
        ptext = ""
        if pi < len(paragraphs):
            ptext = paragraphs[pi].get("text") or paragraphs[pi].get("paragraph") or " ".join(it["text"] for it in items)
        offsets = None
        if source_text and ptext:
            offsets = _find_offsets(source_text, ptext.strip())
        paragraph_rows.append(
            {
                "paragraph_index": pi,
                "text": ptext.strip(),
                "avg_generated_prob": avg,
                "peak_generated_prob": peak,
                "n_sentences": len(items),
                "position_chars": list(offsets) if offsets else None,
                "sentences": items,  # keep child sentences for context
            }
        )
    paragraph_rows.sort(key=lambda x: x["avg_generated_prob"], reverse=True)
    paragraph_rows = paragraph_rows[:n]
    for rank, item in enumerate(paragraph_rows, start=1):
        item["rank"] = rank
    return {"summary": summary, "by": "paragraph", "top_offenders": paragraph_rows}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _smoke_test():
    sample = (
        "Climate change is one of the most pressing issues facing humanity today. "
        "Greenhouse gases like carbon dioxide trap heat in the atmosphere and lead "
        "to rising global temperatures. Scientists have observed warming trends for "
        "decades. We must reduce emissions urgently to mitigate the worst impacts. "
        "Renewable energy sources are essential for a sustainable future."
    )
    print("--- smoke test (this paragraph is mildly AI-like) ---")
    res = score(sample)
    doc = res["documents"][0]
    print(json.dumps(doc.get("class_probabilities"), indent=2))
    print("predicted_class:", doc.get("predicted_class"))
    print("confidence_category:", doc.get("confidence_category"))
    print("completely_generated_prob:", doc.get("completely_generated_prob"))


def main(argv=None):
    p = argparse.ArgumentParser(description="GPTZero AI-text detection (free-tier reverse engineer).")
    p.add_argument("file", nargs="?", help="Text/markdown file to scan. If '-', read stdin.")
    p.add_argument("--score", action="store_true", help="Print only the AI probability (0..1).")
    p.add_argument("--refresh", action="store_true", help="Force-refresh the cached JWT.")
    p.add_argument("--no-multilingual", action="store_true", help="Disable multilingual mode.")
    p.add_argument("--smoke", action="store_true", help="Run the built-in smoke test.")
    p.add_argument(
        "--set-tokens",
        nargs=2,
        metavar=("ACCESS", "REFRESH"),
        help="Manually seed the token cache from a browser session.",
    )
    p.add_argument(
        "--top",
        type=int,
        default=None,
        metavar="N",
        help="Print the top-N most AI-like passages as JSON.",
    )
    p.add_argument(
        "--by",
        choices=("sentence", "paragraph"),
        default="sentence",
        help="Granularity for --top (default: sentence).",
    )
    p.add_argument(
        "--no-free-proxies",
        action="store_true",
        help="Skip the free-proxy aggregator step (faster, less resilient).",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Write the JSON result to this path instead of stdout.",
    )
    args = p.parse_args(argv)

    if args.set_tokens:
        access, refresh = args.set_tokens
        exp = _decode_jwt_exp(access) or int(time.time()) + 3600
        _save_cache({"access_token": access, "refresh_token": refresh, "expires_at": exp})
        print("seeded cache at", CACHE_FILE)
        return

    if args.refresh:
        _get_access_token(force_refresh=True)
        print("refreshed; cache at", CACHE_FILE)
        return

    if args.smoke:
        _smoke_test()
        return

    if not args.file:
        p.error("provide a file (or '-' for stdin), --smoke, or --refresh")

    if args.file == "-":
        text = sys.stdin.read()
    else:
        text = Path(args.file).read_text()

    res = score(
        text,
        multilingual=not args.no_multilingual,
        use_free_proxies=not args.no_free_proxies,
    )

    if args.top is not None:
        out = top_offenders(res, n=args.top, by=args.by, source_text=text)
        payload = json.dumps(out, indent=2, ensure_ascii=False)
    elif args.score:
        doc = res["documents"][0]
        payload = str(doc["class_probabilities"]["ai"])
    else:
        payload = json.dumps(res, indent=2, ensure_ascii=False)

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(payload)
        sys.stderr.write(f"[gptzero] wrote {args.out}\n")
    else:
        print(payload)


if __name__ == "__main__":
    main()


# Response schema reference
# -------------------------
#
# Top-level keys returned by /v3/ai/text:
#
#   meta              {pagesCount: int}
#   version           model release date string e.g. "2026-03-30-base"
#   neatVersion       short model version e.g. "4.4b"
#   scanId            UUID of this scan
#   documents[]       one entry per document (we only send one)
#     class_probabilities                {human: 0..1, ai: 0..1, mixed: 0..1}  HEADLINE
#     completely_generated_prob          0..1, "is the WHOLE doc AI?"
#     average_generated_prob             mean per-sentence AI prob
#     predicted_class                    "human" | "ai" | "mixed"
#     confidence_score                   0..1 confidence in predicted_class
#     confidence_category                "low" | "medium" | "high"
#     overall_burstiness                 burstiness metric
#     paragraphs[]                       paragraph-level breakdown
#     sentences[]                        per-sentence detail:
#       sentence                         the text
#       generated_prob                   0..1 AI prob for THIS sentence
#       class_probabilities              {human, ai, paraphrased}
#       perplexity                       (often 0; legacy field)
#       highlight_sentence_for_ai        bool, frontend rendering hint
#     subclass                           which AI sub-class (chatgpt, claude, ...)
#     writing_stats                      empty unless requested
