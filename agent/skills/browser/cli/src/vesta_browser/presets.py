"""Bundled real-Firefox fingerprint presets, seed-selected per profile dir.

Camoufox applies one fingerprint config below JS through its C++ patches, and the worker hands it
that config at launch. Selection is owned here: one coherent preset per profile, stable across
restarts (a real machine has one identity) and different across profiles. Coherence across surfaces
is the actual anti-detect win, so presets are authored as whole consistent identities, never mixed
field-by-field.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

_DIR = Path(__file__).parent / "presets"

# Config defaults merged under every selected preset. showcursor defaults on in Camoufox (a red
# highlight trailing the pointer, meant for watching humanized movement in dev); on a real session
# it is an instant automation tell, so force it off.
_DEFAULTS = {"showcursor": False}


def _load() -> list[dict]:
    presets = []
    for path in sorted(_DIR.glob("*.json")):
        data = json.loads(path.read_text())
        data["_name"] = path.stem
        presets.append(data)
    if not presets:
        raise RuntimeError("no fingerprint presets bundled")
    return presets


def select_preset(profile_dir: Path) -> dict:
    """Deterministic per profile dir, uniform across the bundled set, with config defaults merged."""
    presets = _load()
    digest = hashlib.sha256(str(profile_dir).encode()).digest()
    idx = int.from_bytes(digest[:8], "big") % len(presets)
    return {**_DEFAULTS, **presets[idx]}


def fit_to_screen(preset: dict, width: int, height: int) -> dict:
    """Rewrite a preset's geometry so the spoofed identity matches a real width x height screen.

    Camoufox sizes the actual window to window.outer*, so a preset authored for a bigger
    monitor overflows (and gets cropped on) a smaller framebuffer like the handover's Xvfb.
    The window chrome size carries over from the preset; the screen is bare (no taskbar),
    so avail equals the full screen.
    """
    chrome_w = preset["window.outerWidth"] - preset["window.innerWidth"]
    chrome_h = preset["window.outerHeight"] - preset["window.innerHeight"]
    return {
        **preset,
        "screen.width": width,
        "screen.height": height,
        "screen.availWidth": width,
        "screen.availHeight": height,
        "window.outerWidth": width,
        "window.outerHeight": height,
        "window.innerWidth": width - chrome_w,
        "window.innerHeight": height - chrome_h,
    }
