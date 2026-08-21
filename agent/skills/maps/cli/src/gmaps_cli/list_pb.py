"""Builders for the Google `entitylist` RPC `pb` strings, captured from the web app.

Pure string assembly, kept apart from the search/place `pb.py` so the two RPC families never
share a template. The `!7e81!28e2` block after a token marks a signed-in session request.
"""

from __future__ import annotations

import urllib.parse


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


# Writes carry the page session token (`!1s...!7e81!28e2`) plus one server-issued consistency
# token, which already arrives with its `:<ts>` suffix from the page pool.
def create_pb(name: str, token: str, consistency: str) -> str:
    return f"!3s{urllib.parse.quote(name)}!5m3!1s{token}!7e81!28e2!9s{consistency}"


def rename_pb(list_id: str, name: str, token: str, consistency: str) -> str:
    return f"!1m4!1s{list_id}!2e1!3m1!1e1!2s{urllib.parse.quote(name)}!4m3!1s{token}!7e81!28e2!6s{consistency}"


def delete_pb(list_id: str, token: str, consistency: str) -> str:
    return f"!1m4!1s{list_id}!2e1!3m1!1e1!2m3!1s{token}!7e81!28e2!3s{consistency}"
