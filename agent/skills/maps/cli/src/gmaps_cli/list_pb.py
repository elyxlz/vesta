"""Builders for the Google `entitylist` RPC `pb` strings, captured from the web app.

Pure string assembly, kept apart from the search/place `pb.py` so the two RPC families never
share a template. The `!7e81!28e2` block after a token marks a signed-in session request.
"""

from __future__ import annotations


def list_index_pb() -> str:
    return "!1e3"


def getlist_pb(list_id: str, limit: int = 500) -> str:
    """Reads are cookie-authed, so the session-token slot (`!1s` before `!7e81`) stays empty."""
    return f"!1m4!1s{list_id}!2e2!3m1!1e1!2e2!3e2!4i{limit}!6m3!1s!7e81!28e2!8i3!16b1"


def ftid_halves(ftid: str) -> tuple[int, int]:
    """`0x<hi>:0x<lo>` -> `(int(hi, 16), int(lo, 16))`; `lo` is the decimal cid."""
    parts = ftid.split(":")
    if len(parts) != 2:
        raise ValueError(f"malformed ftid: {ftid!r}")
    return (int(parts[0], 16), int(parts[1], 16))
