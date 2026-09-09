"""One finalized attachment on disk, the way the store holds a file that landed elsewhere first: a
minted id, the declared metadata, and the blob copied in. The suites that need a file already in the
store share this instead of each staging one chunk at a time."""

import mimetypes
import pathlib as pl
import uuid

from chat_cli import attachments


def stored_attachment(root: pl.Path, source: pl.Path, mime: str | None = None) -> attachments.AttachmentMeta:
    guessed = mime if mime is not None else mimetypes.guess_type(source.name)[0]
    meta: attachments.AttachmentMeta = {
        "id": uuid.uuid4().hex,
        "name": attachments.sanitize_filename(source.name),
        "mime": guessed if guessed is not None else attachments.FALLBACK_MIME,
        "size": source.stat().st_size,
    }
    return attachments.store_copy(root, source, meta)
