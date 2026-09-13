"""The attachment blob store: files the user sends from the app and files the agent sends back, each
under one id directory at <root>/<id>/. A file is copied in whole under the id the node minted for it,
beside a meta.json, which from then on is the single truth the CLI reads. A removed blob keeps its
meta.json, so the app renders "no longer available" and removal never breaks chat history. Everything
is a pure function over the root path; no daemon state is involved."""

import json
import os
import pathlib as pl
import re
import shutil
import typing as tp

MAX_ATTACHMENT_BYTES = 512 * 1024 * 1024
MAX_ATTACHMENTS_PER_MESSAGE = 10
STALE_ATTACHMENT_MAX_AGE_SECS = 24 * 3600

# The record file is dot-prefixed and sanitize_filename strips leading dots, so a user file can never
# collide with (and clobber) the store's own record, whatever it is named.
_META_FILE = ".meta.json"
_FILENAME_MAX_CHARS = 120
FALLBACK_MIME = "application/octet-stream"


class AttachmentMeta(tp.TypedDict, total=False):
    id: str
    name: str
    mime: str
    size: int
    width: int
    height: int
    duration_secs: float


class SizeError(Exception):
    """The file is larger than the store accepts."""


class UnknownAttachmentError(Exception):
    """No attachment exists under this id."""


def sanitize_filename(name: str) -> str:
    """One safe filename from client input: the basename only, control characters stripped, never
    hidden, never empty, capped so a hostile name cannot blow up the directory entry."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(char for char in base if char.isprintable() and char != "\x7f")
    cleaned = cleaned.lstrip(".").strip()
    if not cleaned:
        return "file"
    return cleaned[:_FILENAME_MAX_CHARS]


def human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    value = float(size)
    for unit in ("kB", "MB", "GB"):
        value /= 1024
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
    raise AssertionError("unreachable")


def attachments_root(data_dir: pl.Path) -> pl.Path:
    """The store's directory under a data dir. The store owns its own layout."""
    return data_dir / "attachments"


# Ids are node-minted uuid4 hex. Every id from outside flows through this gate before it is joined to
# a path, so a hostile id (`../x`) can never escape the store root.
_ID_PATTERN = re.compile(r"[0-9a-f]{32}")


def is_valid_id(attachment_id: str) -> bool:
    return _ID_PATTERN.fullmatch(attachment_id) is not None


def _dir(root: pl.Path, attachment_id: str) -> pl.Path:
    if not is_valid_id(attachment_id):
        raise UnknownAttachmentError(attachment_id)
    # The id format already forbids traversal; this normalized containment check is the guard at
    # the path-construction owner itself, so no caller can reach disk outside the store root.
    base = os.path.normpath(str(root))
    normalized = os.path.normpath(str(root / attachment_id))
    if not normalized.startswith(base + os.sep):
        raise UnknownAttachmentError(attachment_id)
    return pl.Path(normalized)


def _read_json(path: pl.Path) -> AttachmentMeta | None:
    if not path.exists():
        return None
    return tp.cast(AttachmentMeta, json.loads(path.read_text()))


def _write_json(path: pl.Path, record: AttachmentMeta) -> None:
    """Atomic publish: a crash mid-write must never leave a truncated record a later read chokes on."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record))
    tmp.replace(path)


def blob_destination(root: pl.Path, meta: AttachmentMeta) -> pl.Path:
    """Where a blob copied from elsewhere lands, its id directory created. The name is sanitized here
    too, so a file named by another node cannot reach outside the id directory."""
    directory = _dir(root, meta["id"])
    directory.mkdir(parents=True, exist_ok=True)
    return directory / sanitize_filename(meta["name"])


def record_meta(root: pl.Path, meta: AttachmentMeta) -> AttachmentMeta:
    """Publish the metadata beside a blob that already landed, which is what makes the attachment
    complete: from here on `read_meta` and `attachments list` both see it. Answers the record as
    stored, so the caller names the file this store really holds."""
    stored: AttachmentMeta = {**meta, "name": sanitize_filename(meta["name"])}
    _write_json(_dir(root, meta["id"]) / _META_FILE, stored)
    return stored


def store_copy(root: pl.Path, source: pl.Path, meta: AttachmentMeta) -> AttachmentMeta:
    """Copy a file that already reached another store into this one, under the id it carries there.
    The sender's own history then renders the same blob the room holds."""
    shutil.copyfile(source, blob_destination(root, meta))
    return record_meta(root, meta)


def read_meta(root: pl.Path, attachment_id: str) -> AttachmentMeta | None:
    """The stored metadata, or None while the id is malformed or unknown to this store."""
    if not is_valid_id(attachment_id):
        return None
    return _read_json(_dir(root, attachment_id) / _META_FILE)


def blob_path(root: pl.Path, attachment_id: str) -> pl.Path:
    meta = read_meta(root, attachment_id)
    if meta is None:
        raise UnknownAttachmentError(attachment_id)
    return _dir(root, attachment_id) / meta["name"]


def is_removed(root: pl.Path, attachment_id: str) -> bool:
    """Meta present but blob gone: what `attachments rm` leaves behind, and what the app renders as
    "no longer available"."""
    meta = read_meta(root, attachment_id)
    return meta is not None and not (_dir(root, attachment_id) / meta["name"]).exists()


def remove_blob(root: pl.Path, attachment_id: str) -> int:
    """Free the bytes, keep meta.json, so history stays renderable as "no longer available"."""
    meta = read_meta(root, attachment_id)
    if meta is None:
        raise UnknownAttachmentError(attachment_id)
    blob = _dir(root, attachment_id) / meta["name"]
    if not blob.exists():
        return 0
    freed = blob.stat().st_size
    blob.unlink()
    return freed


def _last_activity(directory: pl.Path) -> float:
    """The newest mtime inside the id directory: a file rewritten in place leaves the directory's own
    mtime untouched, so aging off the directory alone would reap an attachment just refreshed."""
    newest = directory.stat().st_mtime
    for child in directory.iterdir():
        newest = max(newest, child.stat().st_mtime)
    return newest


def sweep(root: pl.Path, now: float, referenced: tp.Callable[[str], bool]) -> list[str]:
    """Garbage-collect abandoned disk: every id directory no message references, with no activity for
    the max age. A directory with no meta.json is one nothing finished writing, so it goes the same
    way. Removed-blob directories are tombstones for chat history and are always kept."""
    if not root.exists():
        return []
    swept: list[str] = []
    cutoff = now - STALE_ATTACHMENT_MAX_AGE_SECS
    for directory in root.iterdir():
        if not directory.is_dir() or not is_valid_id(directory.name):
            continue
        attachment_id = directory.name
        if _last_activity(directory) > cutoff:
            continue
        if not is_removed(root, attachment_id) and not referenced(attachment_id):
            shutil.rmtree(directory)
            swept.append(attachment_id)
    return swept
