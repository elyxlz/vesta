"""Resolve a pinned `claude` binary that cc_sdk owns, independent of the host.

The agent drives the interactive `claude` CLI, whose behavior (MCP tool deferral,
transcript shape, hook semantics) is version sensitive. Relying on whatever `claude`
happens to be on PATH lets that contract drift between machines and image builds. So
cc_sdk pins the version here and fetches the matching native binary on demand (verified
by SHA-256), caching it under ~/.cache/cc-sdk. This is the same "vendor a known-good
binary" approach vestad uses for restic/cloudflared.

Pre-fetch at image build time with `python -m cc_sdk._claude_bin`; otherwise the binary
is fetched lazily on first use. stdlib only (runs in the agent venv, no extra deps).
"""

import hashlib
import json
import os
import pathlib as pl
import platform
import tempfile
import urllib.request

# Bump deliberately, with the live e2e tests as the gate.
CLAUDE_VERSION = "2.1.161"

_BASE_URL = "https://downloads.claude.ai/claude-code-releases"
_HTTP_TIMEOUT_S = 120


def _detect_platform() -> str:
    """Mirror claude.ai/install.sh's platform string (linux-x64, linux-arm64-musl, darwin-arm64, ...)."""
    system = platform.system()
    if system == "Darwin":
        os_name = "darwin"
    elif system == "Linux":
        os_name = "linux"
    else:
        raise RuntimeError(f"unsupported OS for claude binary: {system}")

    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        arch = "x64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        raise RuntimeError(f"unsupported architecture for claude binary: {machine}")

    # musl libc (alpine) ships a differently-named loader; the agent image is glibc (debian),
    # so this only matters if cc_sdk is ever run on alpine.
    if os_name == "linux" and (pl.Path("/lib/libc.musl-x86_64.so.1").exists() or pl.Path("/lib/libc.musl-aarch64.so.1").exists()):
        return f"linux-{arch}-musl"
    return f"{os_name}-{arch}"


def _cache_dir() -> pl.Path:
    override = os.environ.get("CC_SDK_CACHE_DIR")
    return pl.Path(override) if override else pl.Path("~/.cache/cc-sdk").expanduser()


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=_HTTP_TIMEOUT_S) as response:
        return response.read()


def _expected_checksum(version: str, plat: str) -> str:
    manifest = json.loads(_fetch(f"{_BASE_URL}/{version}/manifest.json").decode())
    platforms = manifest["platforms"] if "platforms" in manifest else {}
    if plat not in platforms or "checksum" not in platforms[plat]:
        raise RuntimeError(f"claude {version} has no build for platform {plat}")
    return platforms[plat]["checksum"]


def ensure_claude(version: str = CLAUDE_VERSION) -> str:
    """Return the path to the pinned `claude` binary, downloading+verifying it if absent.

    CC_SDK_CLAUDE_BIN overrides the resolved path entirely (no download): an escape hatch
    for pointing at a specific binary, and how the test suite injects its fake claude.
    """
    override = os.environ.get("CC_SDK_CLAUDE_BIN")
    if override:
        return override

    plat = _detect_platform()
    cache_dir = _cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"claude-{version}-{plat}"
    if target.exists() and os.access(target, os.X_OK):
        return str(target)

    expected = _expected_checksum(version, plat)
    blob = _fetch(f"{_BASE_URL}/{version}/{plat}/claude")
    actual = hashlib.sha256(blob).hexdigest()
    if actual != expected:
        raise RuntimeError(f"claude {version} {plat} checksum mismatch: expected {expected}, got {actual}")

    # Write to a temp file in the same dir and atomically rename, so concurrent starts never
    # observe a half-written binary.
    fd, tmp_name = tempfile.mkstemp(dir=str(cache_dir), prefix=".claude-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(blob)
        pl.Path(tmp_name).chmod(0o755)
        pl.Path(tmp_name).replace(target)
    except BaseException:
        pl.Path(tmp_name).unlink(missing_ok=True)
        raise
    return str(target)


if __name__ == "__main__":
    print(ensure_claude())
