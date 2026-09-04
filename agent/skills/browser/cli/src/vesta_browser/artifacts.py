"""Screenshot collection: what the child wrote, checked, contained, and moved under the session's artifact dir.

Two sources, as Hermes does it: image paths printed on stdout, plus anything new in the artifact
dir itself (the Camoufox worker writes there directly). A candidate is reported only when it sits
under the session's own directories, carries a known image signature, and fits the size cap.
"""

from __future__ import annotations

import datetime as dt
import pathlib as pl
import re
import time
import typing as tp

from .protocol import ARTIFACT_MAX_BYTES, ARTIFACT_RETENTION_DAYS, Artifact
from .runtime_paths import Paths
from .sessions import Session

IMAGE_PATH_RE = re.compile(r"(/[^\s'\"`<>|]+?\.(?:png|jpe?g|webp))\b", re.IGNORECASE)
OWN_NAME_RE = re.compile(r"^\d{8}T\d{6}Z-\d+\.(?:png|jpg|webp)$")
SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"RIFF", "image/webp"),
)
EXTENSION_FOR_MIME = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def _mime(path: pl.Path) -> str | None:
    with path.open("rb") as handle:
        head = handle.read(16)
    for signature, mime in SIGNATURES:
        if head.startswith(signature):
            return mime
    return None


def _contained(path: pl.Path, session: Session) -> bool:
    resolved = path.resolve()
    return any(resolved.is_relative_to(root.resolve()) for root in (session.scratch_dir, session.artifact_dir))


def _candidates(session: Session, stdout: str, started_at: float) -> list[pl.Path]:
    printed = [pl.Path(match) for match in IMAGE_PATH_RE.findall(stdout)]
    present = [
        path for path in session.artifact_dir.iterdir() if path.is_file() and not path.name.startswith(".") and not OWN_NAME_RE.match(path.name)
    ]
    seen: dict[pl.Path, None] = {}
    for path in [*printed, *present]:
        if path.is_file() and path.stat().st_mtime >= started_at:
            seen.setdefault(path.resolve(), None)
    return list(seen)


def _free_target(artifact_dir: pl.Path, stamp: str, ext: str) -> pl.Path:
    index = 1
    while (target := artifact_dir / f"{stamp}-{index}.{ext}").exists():
        index += 1
    return target


def collect(session: Session, stdout: str, started_at: float, now: tp.Callable[[], str]) -> tuple[list[Artifact], list[str]]:
    found: list[Artifact] = []
    warnings: list[str] = []
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    for path in _candidates(session, stdout, started_at):
        if not _contained(path, session):
            warnings.append(f"artifact_skipped: {path} is outside the session directories")
            continue
        mime = _mime(path)
        if mime is None:
            warnings.append(f"artifact_skipped: {path} is not a supported image")
            continue
        size = path.stat().st_size
        if size > ARTIFACT_MAX_BYTES:
            warnings.append(f"artifact_skipped: {path} exceeds {ARTIFACT_MAX_BYTES} bytes")
            continue
        target = _free_target(session.artifact_dir, stamp, EXTENSION_FOR_MIME[mime])
        if path != target:
            path.replace(target)
        found.append({"kind": "screenshot", "path": str(target), "mime_type": mime, "bytes": size, "captured_at": now()})
    return found, warnings


def prune(paths: Paths, now: float | None = None) -> int:
    cutoff = (time.time() if now is None else now) - ARTIFACT_RETENTION_DAYS * 86400
    removed = 0
    if not paths.artifacts.is_dir():
        return 0
    for path in paths.artifacts.rglob("*"):
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink()
            removed += 1
    return removed
