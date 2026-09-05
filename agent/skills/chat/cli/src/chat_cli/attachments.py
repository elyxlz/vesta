"""The attachment blob store: files the user sends from the app and files the agent sends back, each
under one id directory at <root>/<id>/. Uploads stage into an offset-addressed .part file described by
session.json; finalize verifies the declared size and renames the blob to its sanitized filename beside
meta.json, which from then on is the single truth the serve route and the CLI read. A removed blob
keeps its meta.json (the app renders "no longer available" off the resulting 410), so removal never
breaks chat history. Everything is a pure function over the root path; no daemon state is involved."""

import json
import mimetypes
import os
import pathlib as pl
import re
import shutil
import typing as tp
import uuid

MAX_CHUNK_BYTES = 8 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 512 * 1024 * 1024
MAX_ATTACHMENTS_PER_MESSAGE = 10
STALE_SESSION_MAX_AGE_SECS = 24 * 3600

# Control files are dot-prefixed and sanitize_filename strips leading dots, so a user file can never
# collide with (and clobber) the store's own records, whatever it is named.
_SESSION_FILE = ".session.json"
_META_FILE = ".meta.json"
_PART_FILE = ".part"
_FILENAME_MAX_CHARS = 120
_FALLBACK_MIME = "application/octet-stream"


class AttachmentMeta(tp.TypedDict, total=False):
    id: str
    name: str
    mime: str
    size: int
    width: int
    height: int
    duration_secs: float


class SizeError(Exception):
    """The declared or staged size exceeds what the store accepts."""


class SizeMismatchError(Exception):
    """Finalize found staged bytes that do not add up to the declared size."""


class UnknownAttachmentError(Exception):
    """No session or finalized attachment exists under this id."""


class OffsetMismatchError(Exception):
    """An append arrived at an offset other than the staged size; `received` is the truth to resync to."""

    def __init__(self, received: int) -> None:
        super().__init__(f"offset mismatch, received {received}")
        self.received = received


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


# Ids are server-minted uuid4 hex. Everything client-supplied flows through this gate before it is
# joined to a path, so a hostile id (`../x`) can never escape the store root.
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


def create_session(root: pl.Path, name: str, mime: str, size: int, extra: AttachmentMeta) -> str:
    """Open an upload session: mint the id, record the declared metadata, create the empty stage."""
    if size < 0 or size > MAX_ATTACHMENT_BYTES:
        raise SizeError(f"size {size} exceeds the {MAX_ATTACHMENT_BYTES} byte limit")
    attachment_id = uuid.uuid4().hex
    directory = _dir(root, attachment_id)
    directory.mkdir(parents=True)
    session: AttachmentMeta = {"id": attachment_id, "name": sanitize_filename(name), "mime": mime, "size": size}
    if "width" in extra:
        session["width"] = extra["width"]
    if "height" in extra:
        session["height"] = extra["height"]
    if "duration_secs" in extra:
        session["duration_secs"] = extra["duration_secs"]
    _write_json(directory / _SESSION_FILE, session)
    (directory / _PART_FILE).touch()
    return attachment_id


def _session(root: pl.Path, attachment_id: str) -> AttachmentMeta:
    session = _read_json(_dir(root, attachment_id) / _SESSION_FILE)
    if session is None:
        raise UnknownAttachmentError(attachment_id)
    return session


def _part_size(root: pl.Path, attachment_id: str) -> int:
    part = _dir(root, attachment_id) / _PART_FILE
    return part.stat().st_size if part.exists() else 0


def staged_size(root: pl.Path, attachment_id: str) -> int:
    _session(root, attachment_id)
    return _part_size(root, attachment_id)


def append_at(root: pl.Path, attachment_id: str, offset: int, data: bytes) -> int:
    """Append one chunk at an explicit offset. Only the exact staged size is accepted, so a client that
    lost a response resyncs off OffsetMismatchError.received instead of corrupting the stage; a replay whose
    bytes already landed reads received == offset + len(data) as delivered."""
    session = _session(root, attachment_id)
    current = _part_size(root, attachment_id)
    if offset != current:
        raise OffsetMismatchError(current)
    if offset + len(data) > session["size"]:
        raise SizeError(f"append past the declared size {session['size']}")
    part = _dir(root, attachment_id) / _PART_FILE
    with part.open("ab") as stage:
        stage.write(data)
    return current + len(data)


def finalize(root: pl.Path, attachment_id: str) -> AttachmentMeta:
    """Verify the staged bytes match the declared size, publish the blob under its filename, and write
    the metadata record (the finalized marker). Idempotent: a finalized id returns its meta unchanged,
    so a lost complete response is retried safely."""
    already = read_meta(root, attachment_id)
    if already is not None:
        return already
    session = _session(root, attachment_id)
    directory = _dir(root, attachment_id)
    staged = _part_size(root, attachment_id)
    if staged != session["size"]:
        raise SizeMismatchError(f"staged {staged} of declared {session['size']} bytes")
    (directory / _PART_FILE).replace(directory / session["name"])
    _write_json(directory / _META_FILE, session)
    (directory / _SESSION_FILE).unlink()
    return session


def blob_destination(root: pl.Path, meta: AttachmentMeta) -> pl.Path:
    """Where a blob copied from elsewhere lands, its id directory created. The name is sanitized here
    too, so a file named by another node cannot reach outside the id directory."""
    directory = _dir(root, meta["id"])
    directory.mkdir(parents=True, exist_ok=True)
    return directory / sanitize_filename(meta["name"])


def record_meta(root: pl.Path, meta: AttachmentMeta) -> None:
    """Publish the metadata beside a blob that already landed, which is what makes it finalized: from
    here on `read_meta`, the serve route and `attachments list` all see the attachment."""
    stored: AttachmentMeta = {**meta, "name": sanitize_filename(meta["name"])}
    _write_json(_dir(root, meta["id"]) / _META_FILE, stored)


def read_meta(root: pl.Path, attachment_id: str) -> AttachmentMeta | None:
    """The finalized metadata, or None while the id is malformed, unknown, or still staging."""
    if not is_valid_id(attachment_id):
        return None
    return _read_json(_dir(root, attachment_id) / _META_FILE)


def upload_status(root: pl.Path, attachment_id: str) -> tuple[int, int, bool]:
    """(received, declared size, finalized): the resume probe a reconnecting uploader asks."""
    meta = read_meta(root, attachment_id)
    if meta is not None:
        return meta["size"], meta["size"], True
    session = _session(root, attachment_id)
    return staged_size(root, attachment_id), session["size"], False


def blob_path(root: pl.Path, attachment_id: str) -> pl.Path:
    meta = read_meta(root, attachment_id)
    if meta is None:
        raise UnknownAttachmentError(attachment_id)
    return _dir(root, attachment_id) / meta["name"]


def is_removed(root: pl.Path, attachment_id: str) -> bool:
    """Meta present but blob gone: the state a cleaned-up attachment serves as 410."""
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


def ingest_file(root: pl.Path, source: pl.Path, mime: str | None, *, max_bytes: int = MAX_ATTACHMENT_BYTES) -> AttachmentMeta:
    """Copy a file on disk straight into the store as a finalized attachment (the agent-send path).
    The copy stands alone, so the caller may delete a temp source right after."""
    size = source.stat().st_size
    if size > max_bytes:
        raise SizeError(f"{source} is {size} bytes, over the {max_bytes} byte limit")
    guessed = mime if mime is not None else mimetypes.guess_type(source.name)[0]
    meta: AttachmentMeta = {
        "id": uuid.uuid4().hex,
        "name": sanitize_filename(source.name),
        "mime": guessed if guessed is not None else _FALLBACK_MIME,
        "size": size,
    }
    directory = _dir(root, meta["id"])
    directory.mkdir(parents=True)
    shutil.copyfile(source, directory / meta["name"])
    _write_json(directory / _META_FILE, meta)
    return meta


def _last_activity(directory: pl.Path) -> float:
    """The newest mtime inside the id directory: appending chunks touches .part but never the parent
    dir, so aging off the directory's own mtime would reap a slow upload still making progress."""
    newest = directory.stat().st_mtime
    for child in directory.iterdir():
        newest = max(newest, child.stat().st_mtime)
    return newest


def sweep(root: pl.Path, now: float, referenced: tp.Callable[[str], bool]) -> list[str]:
    """Garbage-collect abandoned disk: staging sessions and finalized-but-unreferenced attachments with
    no activity for the max age. Removed-blob directories are tombstones for chat history and are
    always kept."""
    if not root.exists():
        return []
    swept: list[str] = []
    cutoff = now - STALE_SESSION_MAX_AGE_SECS
    for directory in root.iterdir():
        if not directory.is_dir() or not is_valid_id(directory.name):
            continue
        attachment_id = directory.name
        if _last_activity(directory) > cutoff:
            continue
        staging = (directory / _SESSION_FILE).exists()
        orphaned = not staging and not is_removed(root, attachment_id) and not referenced(attachment_id)
        if staging or orphaned:
            shutil.rmtree(directory)
            swept.append(attachment_id)
    return swept
