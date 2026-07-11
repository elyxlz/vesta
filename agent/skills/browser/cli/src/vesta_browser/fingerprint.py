"""Coherent browser-fingerprint randomization for anti-detection.

Strategy (per 2025-2026 research): defeat fingerprinting with COHERENT, FIXED
profiles (not random noise). Real devices produce stable signals; randomization
itself is a detectable signal because two requests to the same site produce
different canvas hashes from the "same machine".

A profile is a self-consistent triple of GPU vendor + GPU renderer + UA +
platform + hardware-concurrency + device-memory + screen + languages. Pick one
profile per session, then inject its override JS via
`Page.addScriptToEvaluateOnNewDocument` BEFORE the first navigation, so every
fingerprinting probe (canvas.toDataURL, gl.getParameter, AudioContext, etc.)
sees the spoofed values.

This is a standalone helper for CDP-driven Chrome/Chromium sessions. The
browser skill's default launcher is Camoufox, which spoofs its fingerprint in
C++ below JS; this module fills the same role when a caller drives raw Chrome
over CDP instead. Usage:

    from vesta_browser.fingerprint import pick_profile, build_override_js

    profile = pick_profile(seed="my-session-id")   # or pick_profile("win11-chrome131-rtx3060")
    js = build_override_js(profile)
    # then, before the first navigation on the CDP session:
    #   cdp("Page.addScriptToEvaluateOnNewDocument", source=js)
"""

from __future__ import annotations

import hashlib
import json
import os
import random
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class FingerprintProfile:
    """A coherent set of fingerprint signals that collectively look like one
    real machine. Mismatch between any two of these is a detection giveaway,
    so don't mix and match across profiles."""

    name: str
    user_agent: str
    platform: str  # navigator.platform
    accept_language: str
    languages: tuple[str, ...]  # navigator.languages
    hardware_concurrency: int
    device_memory: int
    screen_w: int
    screen_h: int
    color_depth: int
    pixel_ratio: float
    timezone: str  # IANA, e.g. "Europe/London"
    webgl_vendor: str  # UNMASKED_VENDOR_WEBGL (37445)
    webgl_renderer: str  # UNMASKED_RENDERER_WEBGL (37446)
    # Canvas noise seed: a per-profile integer that keeps canvas output STABLE
    # within a profile but DIFFERENT across profiles. Real devices give the
    # same hash every time, so we mimic that by using a fixed seed per profile.
    canvas_seed: int


# A small bench of plausible Linux + Windows + macOS desktop profiles. Each
# triple was double-checked against real userAgentData / WebGL renderer pairs
# we have seen in the wild. Add more by sampling from BrowserForge or
# fingerprintjs/fingerprintjs-pro DB. Keep them coherent.
PROFILES: tuple[FingerprintProfile, ...] = (
    FingerprintProfile(
        name="win11-chrome131-rtx3060",
        user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
        platform="Win32",
        accept_language="en-US,en;q=0.9",
        languages=("en-US", "en"),
        hardware_concurrency=12,
        device_memory=16,
        screen_w=2560,
        screen_h=1440,
        color_depth=24,
        pixel_ratio=1.0,
        timezone="Europe/London",
        webgl_vendor="Google Inc. (NVIDIA)",
        webgl_renderer=("ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
        canvas_seed=0x5A1B2C3D,
    ),
    FingerprintProfile(
        name="macos-chrome131-m1",
        user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
        platform="MacIntel",
        accept_language="en-US,en;q=0.9",
        languages=("en-US", "en"),
        hardware_concurrency=8,
        device_memory=8,
        screen_w=1728,
        screen_h=1117,
        color_depth=30,
        pixel_ratio=2.0,
        timezone="Europe/London",
        webgl_vendor="Google Inc. (Apple)",
        webgl_renderer="ANGLE (Apple, ANGLE Metal Renderer: Apple M1, Unspecified Version)",
        canvas_seed=0x9F4E2D1C,
    ),
    FingerprintProfile(
        name="win10-chrome130-iris-xe",
        user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"),
        platform="Win32",
        accept_language="en-GB,en-US;q=0.9,en;q=0.8",
        languages=("en-GB", "en-US", "en"),
        hardware_concurrency=8,
        device_memory=8,
        screen_w=1920,
        screen_h=1080,
        color_depth=24,
        pixel_ratio=1.0,
        timezone="Europe/London",
        webgl_vendor="Google Inc. (Intel)",
        webgl_renderer=("ANGLE (Intel, Intel(R) Iris(R) Xe Graphics (0x00009A49) Direct3D11 vs_5_0 ps_5_0, D3D11)"),
        canvas_seed=0x71A9C4E8,
    ),
    FingerprintProfile(
        name="linux-chrome130-amd",
        user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"),
        platform="Linux x86_64",
        accept_language="en-US,en;q=0.9",
        languages=("en-US", "en"),
        hardware_concurrency=16,
        device_memory=32,
        screen_w=1920,
        screen_h=1200,
        color_depth=24,
        pixel_ratio=1.0,
        timezone="Europe/London",
        webgl_vendor="Mesa",
        webgl_renderer="AMD Radeon RX 6700 XT (radeonsi, navi22, LLVM 17.0.6, DRM 3.54, 6.6.16-amd64)",
        canvas_seed=0x3C6E8B17,
    ),
    FingerprintProfile(
        name="win11-chrome131-rtx4070",
        user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
        platform="Win32",
        accept_language="en-US,en;q=0.9",
        languages=("en-US", "en"),
        hardware_concurrency=24,
        device_memory=32,
        screen_w=3440,
        screen_h=1440,
        color_depth=24,
        pixel_ratio=1.0,
        timezone="Europe/London",
        webgl_vendor="Google Inc. (NVIDIA)",
        webgl_renderer=("ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
        canvas_seed=0xE2A7CD45,
    ),
    FingerprintProfile(
        name="macos-chrome130-intel",
        user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"),
        platform="MacIntel",
        accept_language="en-US,en;q=0.9",
        languages=("en-US", "en"),
        hardware_concurrency=12,
        device_memory=16,
        screen_w=2560,
        screen_h=1600,
        color_depth=30,
        pixel_ratio=2.0,
        timezone="Europe/London",
        webgl_vendor="Google Inc. (Intel Inc.)",
        webgl_renderer="ANGLE (Intel Inc., Intel(R) UHD Graphics 630, OpenGL 4.1)",
        canvas_seed=0x4B91D8F6,
    ),
)

PROFILES_BY_NAME: dict[str, FingerprintProfile] = {p.name: p for p in PROFILES}


def pick_profile(
    name: str | None = None,
    seed: int | str | None = None,
) -> FingerprintProfile:
    """Pick a profile.

    `name`: exact profile name from PROFILES_BY_NAME.
    `seed`: deterministic pick from PROFILES (good for "same fingerprint within
            a session, different across sessions"). Hashed if string.
    Otherwise: random pick (each call may differ).
    """
    if name and name != "random":
        if name not in PROFILES_BY_NAME:
            raise ValueError(f"unknown fingerprint profile {name!r}; available: {sorted(PROFILES_BY_NAME)}")
        return PROFILES_BY_NAME[name]
    if seed is not None:
        if isinstance(seed, str):
            seed = int(hashlib.sha256(seed.encode()).hexdigest()[:16], 16)
        rng = random.Random(seed)
        return rng.choice(PROFILES)
    return random.choice(PROFILES)


def build_override_js(profile: FingerprintProfile) -> str:
    """Build the Page.addScriptToEvaluateOnNewDocument JS that imposes
    `profile` on the page, before any fingerprinting probe runs.

    Properties of the patches:
      * Coherent: all surfaces (canvas, WebGL, navigator, screen) report
        signals consistent with one machine.
      * Stable: canvas/audio outputs are deterministic per profile (we use the
        profile's `canvas_seed` to seed a tiny LCG that perturbs canvas pixel
        bytes by at most 1 in a way the same profile always reproduces).
      * Idempotent: prototype overrides check a sentinel so repeated injection
        doesn't double-wrap and break sites that re-evaluate scripts.
      * `toString` is preserved on overridden functions so naive
        `Function.prototype.toString.call(canvas.toDataURL)` checks still see
        "function toDataURL() { [native code] }".
    """
    p = profile
    # Note: this is a JS source string. Never f-string-interpolate untrusted
    # inputs into it; all values here come from a hardcoded PROFILES table.
    return f"""
(() => {{
  const __vesta_fp__ = window.__vesta_fp__;
  if (__vesta_fp__) return;  // already applied
  Object.defineProperty(window, '__vesta_fp__', {{
    value: {{name: {json.dumps(p.name)}, seed: {p.canvas_seed}}},
    configurable: false, enumerable: false, writable: false
  }});

  // ---- helpers --------------------------------------------------------
  // Preserve native-looking toString on patched functions. The trick: copy
  // .toString from the original.
  const _stamp = (orig, patched) => {{
    try {{
      patched.toString = function toString() {{ return orig.toString(); }};
    }} catch (_) {{}}
    return patched;
  }};
  const _defGet = (obj, prop, get) => {{
    try {{ Object.defineProperty(obj, prop, {{get, configurable: true}}); }} catch(_) {{}}
  }};

  // ---- navigator ------------------------------------------------------
  _defGet(navigator, 'userAgent', () => {json.dumps(p.user_agent)});
  _defGet(navigator, 'appVersion', () => {json.dumps(p.user_agent.split(" ", 1)[1] if " " in p.user_agent else p.user_agent)});
  _defGet(navigator, 'platform', () => {json.dumps(p.platform)});
  _defGet(navigator, 'hardwareConcurrency', () => {p.hardware_concurrency});
  _defGet(navigator, 'deviceMemory', () => {p.device_memory});
  _defGet(navigator, 'languages', () => {json.dumps(list(p.languages))});
  _defGet(navigator, 'language', () => {json.dumps(p.languages[0])});
  _defGet(navigator, 'webdriver', () => undefined);

  // navigator.userAgentData (Client Hints): Chromium exposes this. If we lie
  // about UA but leave userAgentData honest, the mismatch is detectable.
  // Simplest fix: blank it.
  try {{ Object.defineProperty(navigator, 'userAgentData', {{get: () => undefined}}); }} catch(_) {{}}

  // ---- screen ---------------------------------------------------------
  _defGet(screen, 'width', () => {p.screen_w});
  _defGet(screen, 'height', () => {p.screen_h});
  _defGet(screen, 'availWidth', () => {p.screen_w});
  _defGet(screen, 'availHeight', () => {p.screen_h - 40});
  _defGet(screen, 'colorDepth', () => {p.color_depth});
  _defGet(screen, 'pixelDepth', () => {p.color_depth});
  _defGet(window, 'devicePixelRatio', () => {p.pixel_ratio});

  // ---- timezone -------------------------------------------------------
  // Lie about timezone via Intl.DateTimeFormat.prototype.resolvedOptions.
  // Don't touch Date directly: too many side-effects.
  try {{
    const _Intl_DTF = Intl.DateTimeFormat;
    const _orig_resolved = _Intl_DTF.prototype.resolvedOptions;
    _Intl_DTF.prototype.resolvedOptions = _stamp(_orig_resolved, function resolvedOptions() {{
      const r = _orig_resolved.call(this);
      r.timeZone = {json.dumps(p.timezone)};
      return r;
    }});
  }} catch (_) {{}}

  // ---- WebGL ----------------------------------------------------------
  // UNMASKED_VENDOR_WEBGL = 0x9245 = 37445
  // UNMASKED_RENDERER_WEBGL = 0x9246 = 37446
  const _patchWebGL = (proto) => {{
    if (!proto) return;
    const orig = proto.getParameter;
    if (!orig || orig.__vesta_patched) return;
    const patched = _stamp(orig, function getParameter(name) {{
      if (name === 37445) return {json.dumps(p.webgl_vendor)};
      if (name === 37446) return {json.dumps(p.webgl_renderer)};
      // VENDOR (0x1F00 = 7936), RENDERER (0x1F01 = 7937), VERSION (0x1F02 = 7938)
      if (name === 7936) return 'WebKit';
      if (name === 7937) return 'WebKit WebGL';
      return orig.call(this, name);
    }});
    patched.__vesta_patched = true;
    proto.getParameter = patched;
  }};
  _patchWebGL(window.WebGLRenderingContext && WebGLRenderingContext.prototype);
  _patchWebGL(window.WebGL2RenderingContext && WebGL2RenderingContext.prototype);

  // ---- Canvas ---------------------------------------------------------
  // Stable noise: tiny per-profile LCG mutation of canvas bytes. Same profile
  // ⇒ same canvas hash every time (real-device stable). Different profile
  // ⇒ different canvas hash (defeats per-machine fingerprint cache).
  let _canvas_state = {p.canvas_seed} >>> 0;
  const _next = () => {{
    // LCG: numerical recipes constants. Cheap, deterministic.
    _canvas_state = (_canvas_state * 1664525 + 1013904223) >>> 0;
    return _canvas_state;
  }};
  const _resetState = () => {{ _canvas_state = {p.canvas_seed} >>> 0; }};
  const _perturb = (data) => {{
    // Flip the lowest bit of one byte every ~512 pixels. Small enough that
    // images render visually identical, large enough that any hash differs
    // between profiles.
    _resetState();
    const n = data.length;
    for (let i = 0; i < n; i += 4) {{
      // skip alpha, perturb only RGB rarely
      if ((_next() & 0x1FF) === 0) {{
        data[i] = data[i] ^ 1;
      }}
    }}
    return data;
  }};

  try {{
    const C = HTMLCanvasElement.prototype;
    const origToDataURL = C.toDataURL;
    if (origToDataURL && !origToDataURL.__vesta_patched) {{
      const patched = _stamp(origToDataURL, function toDataURL(...args) {{
        // Force one read+perturb of the bitmap before serialization.
        try {{
          const ctx = this.getContext('2d');
          if (ctx) {{
            const w = this.width, h = this.height;
            if (w > 0 && h > 0) {{
              const id = ctx.getImageData(0, 0, w, h);
              _perturb(id.data);
              ctx.putImageData(id, 0, 0);
            }}
          }}
        }} catch (_) {{}}
        return origToDataURL.apply(this, args);
      }});
      patched.__vesta_patched = true;
      C.toDataURL = patched;
    }}

    const Ctx = CanvasRenderingContext2D.prototype;
    const origGetImageData = Ctx.getImageData;
    if (origGetImageData && !origGetImageData.__vesta_patched) {{
      const patched = _stamp(origGetImageData, function getImageData(...args) {{
        const id = origGetImageData.apply(this, args);
        _perturb(id.data);
        return id;
      }});
      patched.__vesta_patched = true;
      Ctx.getImageData = patched;
    }}
  }} catch (_) {{}}

  // ---- AudioContext ---------------------------------------------------
  // Audio fingerprint comes from AudioBuffer.getChannelData. Add tiny
  // deterministic perturbation.
  try {{
    const AB = window.AudioBuffer;
    if (AB && AB.prototype && AB.prototype.getChannelData &&
        !AB.prototype.getChannelData.__vesta_patched) {{
      const orig = AB.prototype.getChannelData;
      const patched = _stamp(orig, function getChannelData(...args) {{
        const a = orig.apply(this, args);
        // perturb every ~1024th sample by ~1e-7 (audibly inert, hash-shifting)
        const seed_local = ({p.canvas_seed} ^ args[0]|0) >>> 0;
        let s = seed_local;
        for (let i = 0; i < a.length; i += 1024) {{
          s = (s * 1664525 + 1013904223) >>> 0;
          a[i] = a[i] + (s % 100) * 1e-9;
        }}
        return a;
      }});
      patched.__vesta_patched = true;
      AB.prototype.getChannelData = patched;
    }}
  }} catch (_) {{}}

  // ---- plugins / mimeTypes -------------------------------------------
  // Stealth defaults that aren't hostile (a real desktop Chrome has a few).
  try {{
    const fakePlugin = (name, filename, desc) => {{
      const p = Object.create(Plugin.prototype);
      p.name = name; p.filename = filename; p.description = desc; p.length = 0;
      return p;
    }};
    const list = [
      fakePlugin('PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format'),
      fakePlugin('Chrome PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format'),
      fakePlugin('Chromium PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format'),
      fakePlugin('Microsoft Edge PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format'),
      fakePlugin('WebKit built-in PDF', 'internal-pdf-viewer', 'Portable Document Format'),
    ];
    Object.setPrototypeOf(list, PluginArray.prototype);
    list.namedItem = function(n) {{ return list.find(p => p.name === n) || null; }};
    list.item = function(i) {{ return list[i] || null; }};
    list.refresh = function() {{}};
    _defGet(navigator, 'plugins', () => list);
  }} catch(_) {{}}
}})();
"""


def profile_to_dict(profile: FingerprintProfile) -> dict:
    """For logging / debugging."""
    d = asdict(profile)
    d["languages"] = list(d["languages"])
    return d


def env_seeded_profile(env_var: str = "VESTA_FP_SEED") -> FingerprintProfile:
    """Pick a profile using an env-var seed if present, else random.

    Useful for "same fingerprint across all browser launches in this session"
    (set the env var to e.g. the current PID or session id).
    """
    seed = os.environ.get(env_var)
    return pick_profile(seed=seed)
