"""Bundled real-Firefox fingerprint presets, seed-selected per profile dir.

Camoufox reads its fingerprint from the CAMOU_CONFIG env var (chunked into
CAMOU_CONFIG_1..N past the 32767-byte Linux cap) at launch; the C++ patches apply
it below JS. We bypass Camoufox's Python launcher, so we own config selection:
one coherent preset per profile, stable across restarts (a real machine has one
identity), different across profiles. Coherence across surfaces is the actual
anti-detect win, so presets are authored/scraped as whole consistent identities,
never mixed field-by-field.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

CHUNK = 32767  # Linux env-var cap read by Camoufox MaskConfig::GetJson
_DIR = Path(__file__).parent / "presets"


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
    """Deterministic per profile dir, uniform across the bundled set."""
    presets = _load()
    digest = hashlib.sha256(str(profile_dir).encode()).digest()
    idx = int.from_bytes(digest[:8], "big") % len(presets)
    return presets[idx]


def camou_config_env(preset: dict) -> dict[str, str]:
    """Serialize a preset to CAMOU_CONFIG_1..N chunks Camoufox concatenates back."""
    payload = {key: value for key, value in preset.items() if not key.startswith("_")}
    blob = json.dumps(payload, separators=(",", ":"))
    env = {}
    for offset in range(0, len(blob), CHUNK):
        env[f"CAMOU_CONFIG_{offset // CHUNK + 1}"] = blob[offset : offset + CHUNK]
    return env
