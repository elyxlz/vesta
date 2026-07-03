"""Best-effort live extraction of an outgoing chat message from a streaming Bash tool call.

The agent's chat replies are typed as the `-m`/`--message` argument of an `app-chat send`
command inside a Bash tool call. With partial messages enabled the tool input streams as
`input_json_delta` chunks, so the reply text is visible while the model writes it. This module
owns that one decision: given the raw partial JSON accumulated so far, what reply text (if any)
is readable? It is a display-only preview — wrong or absent extraction costs nothing, because
the real ChatEvent that follows is the record.
"""

import re

# `"command"` value opener inside the streamed Bash tool-input JSON.
_COMMAND_KEY_RE = re.compile(r'"command"\s*:\s*"')
# `app-chat send … -m/--message <quote>` inside the decoded command string.
_SEND_MESSAGE_RE = re.compile(r"app-chat\s+send\s+(?:[^;|&]*?\s)??(?:-m|--message)\s+(['\"])")

_JSON_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f"}


def _decode_json_string_prefix(body: str) -> str:
    """Decode a (possibly incomplete) JSON string value prefix, stopping at its closing quote
    or at a partial escape sequence cut by a chunk boundary."""
    out: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == '"':
            break
        if ch == "\\":
            if i + 1 >= len(body):
                break
            esc = body[i + 1]
            if esc == "u":
                if i + 6 > len(body):
                    break
                out.append(chr(int(body[i + 2 : i + 6], 16)))
                i += 6
                continue
            out.append(_JSON_ESCAPES[esc] if esc in _JSON_ESCAPES else esc)
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _shell_quoted_prefix(body: str, quote: str) -> str:
    """The content of a shell-quoted string prefix, up to its closing quote if present.

    Double quotes honor backslash escapes for `"` and `\\`; single quotes take everything
    verbatim until the next single quote."""
    if quote == "'":
        end = body.find("'")
        return body if end == -1 else body[:end]
    out: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == '"':
            break
        if ch == "\\" and i + 1 < len(body) and body[i + 1] in ('"', "\\"):
            out.append(body[i + 1])
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def extract_chat_preview(raw_partial_json: str) -> str | None:
    """The app-chat reply text visible so far in a partially streamed Bash tool input.

    None until an `app-chat send … -m/--message <quote>` opener has streamed. Chained commands
    preview the last send; the caller detects a restart by prefix mismatch."""
    key = _COMMAND_KEY_RE.search(raw_partial_json)
    if not key:
        return None
    command = _decode_json_string_prefix(raw_partial_json[key.end() :])
    opener = None
    for match in _SEND_MESSAGE_RE.finditer(command):
        opener = match
    if not opener:
        return None
    return _shell_quoted_prefix(command[opener.end() :], opener.group(1))
