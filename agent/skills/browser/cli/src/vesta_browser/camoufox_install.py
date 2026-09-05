"""Installs the pinned Camoufox bundle under /opt/camoufox/<tag>/. Standalone: run by path with the system python.

The Dockerfile runs it for fresh images and the browser-daemon migration runs it on the fleet,
because a fleet upgrade never reruns the Dockerfile. Idempotent: an installed tag is left alone.
"""

from __future__ import annotations

import argparse
import json
import pathlib as pl
import platform
import shutil
import sys
import typing as tp
import urllib.request
import zipfile
from hashlib import sha256

CAMOUFOX_RELEASE_TAG = "v150.0.2-beta.25"
# arm64 and x86_64 assets carry different build numbers within one release, so pin
# each arch's exact asset name + digest rather than templating from a version string.
CAMOUFOX_ASSETS = {
    "aarch64": ("camoufox-150.0.2-alpha.25-lin.arm64.zip", "b2870af8cd99721d41bd48f0cce0f949449ab75364b80ee3d389bd35953ea213"),
    "x86_64": ("camoufox-150.0.2-alpha.26-lin.x86_64.zip", "b146b98b0c2c41023716feef36451f319a534309f72c54584a4b0b88670f510b"),
}
RELEASE_DOWNLOAD_URL = "https://github.com/daijro/camoufox/releases/download"

DOWNLOAD_TIMEOUT_S = 600.0
DOWNLOAD_CHUNK = 1 << 20

INSTALL_ROOT = pl.Path("/opt/camoufox")
Downloader = tp.Callable[[str, pl.Path], None]


def _verify_sha256(path: pl.Path, expected: str) -> None:
    digest = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(DOWNLOAD_CHUNK), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected:
        raise RuntimeError(f"Camoufox download sha256 mismatch: expected {expected}, got {actual}")


def _download(url: str, dest: pl.Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "vesta-browser"})
    with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_S) as r, dest.open("wb") as f:
        shutil.copyfileobj(r, f, DOWNLOAD_CHUNK)


def _extract_preserving_mode(zip_path: pl.Path, dest: pl.Path) -> None:
    """Extract, restoring unix exec bits (zipfile.extractall drops them, which would
    leave the camoufox binary and its .so loader non-executable)."""
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            z.extract(info, dest)
            mode = info.external_attr >> 16
            if mode:
                (dest / info.filename).chmod(mode)


_OMNI_SEARCH_SELECTOR = "moz-src/toolkit/components/search/SearchEngineSelector.sys.mjs"
# Camoufox's no-search-engines patch, verbatim from its shipped omni.ja (v150 and v152).
_BROKEN_SEARCH_STUB = """\
      return [
        {
          "appliesTo": [{
            "default": "yes",
            "included": {
              "everywhere": true
            },
            "webExtension": {
              "id": "none@mozilla.org"
            }
          }],
        },
      ];"""
_REPAIRED_SEARCH_STUB = """\
      return [
        {
          "recordType": "engine",
          "identifier": "ddg",
          "base": {
            "classification": "general",
            "name": "DuckDuckGo",
            "urls": {
              "search": {
                "base": "https://duckduckgo.com/",
                "searchTermParamName": "q"
              }
            }
          },
          "variants": [{ "environment": { "allRegionsAndLocales": true } }]
        },
        {
          "recordType": "defaultEngines",
          "globalDefault": "ddg",
          "specificDefaults": []
        },
      ];"""


def repair_search_stub(home: pl.Path) -> None:
    """Fix Camoufox's search-config stub inside omni.ja so SearchService can start.

    Camoufox hardcodes SearchEngineSelector's configuration to one stub record that
    predates search-config-v2; FF150+ hands it to the Rust selector, which requires
    `recordType` and fails search init permanently (fatal in headless boxes: every
    open then hangs, issue #1445). Rewriting the stub to a minimal valid config
    heals fresh extractions and already-installed builds alike; Firefox invalidates
    the profile startupCache on its own when omni.ja changes."""
    omni = home / "omni.ja"
    if not omni.is_file():
        return
    with zipfile.ZipFile(omni) as z:
        if _OMNI_SEARCH_SELECTOR not in z.namelist():
            return
        source = z.read(_OMNI_SEARCH_SELECTOR).decode()
    if _BROKEN_SEARCH_STUB not in source:
        return
    repaired = source.replace(_BROKEN_SEARCH_STUB, _REPAIRED_SEARCH_STUB)
    tmp = omni.with_name("omni.ja.tmp")
    with zipfile.ZipFile(omni) as zin, zipfile.ZipFile(tmp, "w") as zout:
        for info in zin.infolist():
            data = repaired.encode() if info.filename == _OMNI_SEARCH_SELECTOR else zin.read(info)
            zout.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
    tmp.replace(omni)


def _asset_for_arch(arch: str) -> tuple[str, str]:
    if arch not in CAMOUFOX_ASSETS:
        raise RuntimeError(f"unsupported architecture {arch!r}; supported: {sorted(CAMOUFOX_ASSETS)}")
    return CAMOUFOX_ASSETS[arch]


def install(root: pl.Path = INSTALL_ROOT, arch: str = platform.machine(), download: Downloader = _download) -> pl.Path:
    home = root / CAMOUFOX_RELEASE_TAG
    exe = home / "camoufox"
    if exe.is_file():
        # LEGACY(remove-when: CAMOUFOX_RELEASE_TAG moves past v150.0.2-beta.25): heals bundles
        # extracted before the search-stub repair shipped; a new tag always extracts fresh.
        repair_search_stub(home)
        return exe
    asset_name, expected_sha = _asset_for_arch(arch)
    root.mkdir(parents=True, exist_ok=True)
    part = root / f".{asset_name}.part"
    staging = root / f".{CAMOUFOX_RELEASE_TAG}.staging"
    try:
        download(f"{RELEASE_DOWNLOAD_URL}/{CAMOUFOX_RELEASE_TAG}/{asset_name}", part)
        _verify_sha256(part, expected_sha)
        if staging.exists():
            shutil.rmtree(staging)
        _extract_preserving_mode(part, staging)
        repair_search_stub(staging)
        # replace() onto a non-empty directory fails, and a half-extracted tag directory is exactly
        # what an interrupted install leaves behind.
        shutil.rmtree(home, ignore_errors=True)
        staging.replace(home)
    finally:
        part.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)
    return exe


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=pl.Path, default=INSTALL_ROOT)
    args = parser.parse_args()
    print(json.dumps({"installed": str(install(root=args.root))}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
