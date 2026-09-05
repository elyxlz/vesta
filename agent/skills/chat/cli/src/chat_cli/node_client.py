"""Every call the chat daemon makes to vestad's chat node: the rooms this agent is in, the history it
pulls forward by id, the messages it posts, the attachment bytes it moves, and the live socket it
reads. One owner, so no other module spells a node path, a status code, or the token header. vestad's
certificate is self-signed, so an https node is dialed with certificate verification off."""

import asyncio
import json
import pathlib as pl
import typing as tp

import aiohttp

from .attachments import AttachmentMeta
from .store import RoomRecord

# Every HTTP call to the node is bounded by this. The live socket is not: it is dialed on a session
# that carries no deadline of its own, so a quiet room never drops it.
NODE_TIMEOUT_SECS = 30.0
# One upload chunk, and the size a download streams in.
UPLOAD_CHUNK_BYTES = 4 * 1024 * 1024

_TOKEN_HEADER = "X-Agent-Token"
_HTTPS_PREFIX = "https://"
_ENV_KEYS = ("AGENT_NAME", "AGENT_TOKEN", "BOX_HOST", "VESTAD_PORT")
# What a caller says when the environment names no node: the four values, so the reader can fix it.
NODE_UNREACHABLE = f"the chat node is unreachable: {', '.join(_ENV_KEYS)} must be set"
_SPEAKING_FIELD = "user_speaking"
_BURST_STATUS = 429
_CONFLICT_STATUS = 409

type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None


class NodeConfig(tp.TypedDict):
    """Where the node is, and who this agent is to it."""

    base_url: str
    token: str
    agent: str


class NodeMessage(tp.TypedDict):
    """One message as the node's history page and live socket carry it."""

    id: int
    ts: str
    room: str
    type: str
    sender: str
    text: str
    input_method: tp.NotRequired[str]
    intent_id: tp.NotRequired[str]
    origin_id: tp.NotRequired[int]
    attachments: tp.NotRequired[list[AttachmentMeta]]


class ImportItem(tp.TypedDict):
    """One message handed to the node's import. `origin_id` is this store's own row id, which the node
    echoes back on the replicated copy, so the row is stamped instead of duplicated."""

    origin_id: int
    ts: str
    type: str
    text: str
    input_method: tp.NotRequired[str]
    attachments: tp.NotRequired[list[str]]


class ImportOutcome(tp.TypedDict):
    imported: int
    skipped: int


class UploadExtra(tp.TypedDict, total=False):
    """What an upload declares beyond name, mime and size: the media facts a client renders from."""

    width: int
    height: int
    duration_secs: float


class NodeError(Exception):
    """The node could not be reached, or answered something this client cannot read."""


class SpeakingRefusedError(Exception):
    """The user is talking in that room, so the post was refused. Not a failure to retry."""


class BurstRefusedError(Exception):
    """The room holds too many agent messages since the user last spoke."""


def node_config_from_env(env: tp.Mapping[str, str]) -> NodeConfig | None:
    """The node this agent talks to, or None while any of the four identity values is missing or
    empty. A None keeps the replica loop off; every other daemon function still works."""
    for key in _ENV_KEYS:
        if key not in env or not env[key]:
            return None
    return {"base_url": f"{_HTTPS_PREFIX}{env['BOX_HOST']}:{env['VESTAD_PORT']}", "token": env["AGENT_TOKEN"], "agent": env["AGENT_NAME"]}


def new_session(config: NodeConfig) -> aiohttp.ClientSession:
    """The session every NodeClient runs on. An https node is vestad, whose certificate is self-signed
    and so verifies nothing; a test dials plain http. The session bounds the connect alone, so a node
    that never answers the handshake falls into the replica's backoff instead of the OS deadline, while
    reads stay unbounded and the live socket survives a quiet room. Each HTTP call passes
    NODE_TIMEOUT_SECS itself."""
    checks_certificate = not config["base_url"].startswith(_HTTPS_PREFIX)
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=NODE_TIMEOUT_SECS)
    return aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=checks_certificate), timeout=timeout)


def _object(value: JsonValue, what: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise NodeError(f"{what} is not an object")
    return value


def _field(value: JsonValue, key: str, what: str) -> JsonValue:
    holder = _object(value, what)
    if key not in holder:
        raise NodeError(f"{what} carries no {key}")
    return holder[key]


def _items(value: JsonValue, what: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise NodeError(f"{what} is not a list")
    return value


def _text(value: JsonValue, what: str) -> str:
    if not isinstance(value, str):
        raise NodeError(f"{what} is not a string")
    return value


def _whole(value: JsonValue, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise NodeError(f"{what} is not a number")
    return value


def _decimal(value: JsonValue, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NodeError(f"{what} is not a number")
    return float(value)


def _decode(text: str, what: str) -> JsonValue:
    if not text:
        return None
    try:
        decoded: JsonValue = json.loads(text)
    except json.JSONDecodeError as error:
        raise NodeError(f"{what}: unreadable answer") from error
    return decoded


def _reason(payload: JsonValue, status: int) -> str:
    if isinstance(payload, dict) and "error" in payload and isinstance(payload["error"], str):
        return payload["error"]
    return f"http {status}"


def _refused_by_the_user(status: int, payload: JsonValue) -> bool:
    return status == _CONFLICT_STATUS and isinstance(payload, dict) and _SPEAKING_FIELD in payload and payload[_SPEAKING_FIELD] is True


def _answer(status: int, text: str, what: str) -> JsonValue:
    """The body of a call that landed, or the refusal its status carries."""
    payload = _decode(text, what)
    if 200 <= status < 300:
        return payload
    reason = _reason(payload, status)
    if _refused_by_the_user(status, payload):
        raise SpeakingRefusedError(reason)
    if status == _BURST_STATUS:
        raise BurstRefusedError(reason)
    raise NodeError(f"{what}: {reason}")


def _attachment(value: JsonValue) -> AttachmentMeta:
    holder = _object(value, "attachment")
    meta: AttachmentMeta = {
        "id": _text(_field(holder, "id", "attachment"), "attachment id"),
        "name": _text(_field(holder, "name", "attachment"), "attachment name"),
        "mime": _text(_field(holder, "mime", "attachment"), "attachment mime"),
        "size": _whole(_field(holder, "size", "attachment"), "attachment size"),
    }
    if "width" in holder:
        meta["width"] = _whole(holder["width"], "attachment width")
    if "height" in holder:
        meta["height"] = _whole(holder["height"], "attachment height")
    if "duration_secs" in holder:
        meta["duration_secs"] = _decimal(holder["duration_secs"], "attachment duration")
    return meta


def parse_room(value: JsonValue) -> RoomRecord:
    """One room as the node describes it, from a history answer or a live frame."""
    holder = _object(value, "room")
    name = holder["name"] if "name" in holder else None
    return {
        "id": _text(_field(holder, "id", "room"), "room id"),
        "name": None if name is None else _text(name, "room name"),
        "agents": [_text(agent, "room agent") for agent in _items(_field(holder, "agents", "room"), "room agents")],
    }


def parse_message(value: JsonValue) -> NodeMessage:
    """One message as the node describes it, from a history page or a live frame."""
    holder = _object(value, "message")
    message: NodeMessage = {
        "id": _whole(_field(holder, "id", "message"), "message id"),
        "ts": _text(_field(holder, "ts", "message"), "message ts"),
        "room": _text(_field(holder, "room", "message"), "message room"),
        "type": _text(_field(holder, "type", "message"), "message type"),
        "sender": _text(_field(holder, "sender", "message"), "message sender"),
        "text": _text(_field(holder, "text", "message"), "message text"),
    }
    if "input_method" in holder:
        message["input_method"] = _text(holder["input_method"], "message input method")
    if "intent_id" in holder:
        message["intent_id"] = _text(holder["intent_id"], "message intent id")
    if "origin_id" in holder:
        message["origin_id"] = _whole(holder["origin_id"], "message origin id")
    if "attachments" in holder:
        message["attachments"] = [_attachment(item) for item in _items(holder["attachments"], "message attachments")]
    return message


def _read_at(path: pl.Path, offset: int, length: int) -> bytes:
    with path.open("rb") as handle:
        handle.seek(offset)
        return handle.read(length)


class NodeClient:
    """The node's surface as the daemon uses it. Every call raises NodeError on a transport failure or
    an answer this client cannot read; a refused post raises its own refusal instead."""

    def __init__(self, config: NodeConfig, session: aiohttp.ClientSession) -> None:
        self._config = config
        self._session = session
        self._base = config["base_url"].rstrip("/")
        self._headers = {_TOKEN_HEADER: config["token"]}
        self._timeout = aiohttp.ClientTimeout(total=NODE_TIMEOUT_SECS)

    async def _call(self, method: str, path: str, *, params: dict[str, str] | None = None, body: JsonValue = None) -> JsonValue:
        what = f"{method} {path}"
        try:
            async with self._session.request(
                method, self._base + path, headers=self._headers, params=params, json=body, timeout=self._timeout
            ) as response:
                status = response.status
                text = await response.text()
        except (TimeoutError, aiohttp.ClientError) as error:
            raise NodeError(f"{what}: {error}") from error
        return _answer(status, text, what)

    async def rooms(self) -> list[RoomRecord]:
        """Every room the node has this agent in."""
        payload = await self._call("GET", "/rooms")
        return [parse_room(item) for item in _items(_field(payload, "rooms", "rooms answer"), "rooms")]

    async def open_room(self, agents: list[str], name: str | None) -> RoomRecord:
        """The room holding exactly these agents, opened when the node does not hold it yet."""
        body: dict[str, JsonValue] = {"agents": list(agents)}
        if name is not None:
            body["name"] = name
        payload = await self._call("POST", "/rooms", body=body)
        return parse_room(_field(payload, "room", "open room answer"))

    async def history_after(self, room: str, after: int, limit: int) -> tuple[list[NodeMessage], int | None]:
        """One page of everything the room holds past node id `after`, plus the id to continue from
        while the room holds more."""
        payload = await self._call("GET", f"/rooms/{room}/history", params={"after": str(after), "limit": str(limit)})
        events = [parse_message(item) for item in _items(_field(payload, "events", "history page"), "history events")]
        cursor = _field(payload, "cursor", "history page")
        return events, None if cursor is None else _whole(cursor, "history cursor")

    async def post(self, room: str, text: str, attachments: list[str]) -> int:
        """Send one message as this agent, answering the node id it landed under."""
        body: dict[str, JsonValue] = {"text": text}
        if attachments:
            body["attachments"] = list(attachments)
        payload = await self._call("POST", f"/rooms/{room}/messages", body=body)
        return _whole(_field(payload, "id", "post answer"), "message id")

    async def import_messages(self, room: str, items: list[ImportItem]) -> ImportOutcome:
        """Hand the node history this agent already holds. An origin id the node has seen is skipped,
        so a re-run imports only what is missing."""
        payload = await self._call("POST", f"/rooms/{room}/messages/import", body={"messages": list(items)})
        return {
            "imported": _whole(_field(payload, "imported", "import answer"), "imported count"),
            "skipped": _whole(_field(payload, "skipped", "import answer"), "skipped count"),
        }

    async def peers(self) -> list[str]:
        """The other agents on this gateway."""
        payload = await self._call("GET", f"/agents/{self._config['agent']}/peers")
        return [_text(item, "peer") for item in _items(_field(payload, "peers", "peers answer"), "peers")]

    async def _staged(self, attachment_id: str) -> int:
        payload = await self._call("GET", f"/rooms/attachments/{attachment_id}/status")
        return _whole(_field(payload, "received", "upload status"), "received offset")

    async def _send_chunk(self, attachment_id: str, offset: int, chunk: bytes) -> int:
        """One chunk at its offset. The answer is the node's staged size, which is where the next chunk
        goes: a 409 names the size the node really holds, and a response lost on the way back is
        resolved by asking for that size, so neither one ever duplicates bytes."""
        path = f"/rooms/attachments/{attachment_id}/data"
        try:
            async with self._session.put(
                self._base + path, headers=self._headers, params={"offset": str(offset)}, data=chunk, timeout=self._timeout
            ) as response:
                status = response.status
                text = await response.text()
        except (TimeoutError, aiohttp.ClientError):
            return await self._staged(attachment_id)
        payload = _decode(text, path)
        if status == _CONFLICT_STATUS:
            return _whole(_field(payload, "received", "chunk conflict"), "received offset")
        if status < 200 or status >= 300:
            raise NodeError(f"PUT {path}: {_reason(payload, status)}")
        return _whole(_field(payload, "received", "chunk answer"), "received offset")

    async def upload(self, path: pl.Path, mime: str, extra: UploadExtra | None = None) -> AttachmentMeta:
        """Move one local file into the node's attachment store: open the session, send the bytes in
        UPLOAD_CHUNK_BYTES pieces, finalize. The finalized metadata is what a message references."""
        size = (await asyncio.to_thread(path.stat)).st_size
        declared: dict[str, JsonValue] = {"name": path.name, "mime": mime, "size": size}
        if extra is not None:
            declared.update(extra)
        created = await self._call("POST", "/rooms/attachments", body=declared)
        attachment_id = _text(_field(created, "id", "attachment session"), "attachment id")
        offset = 0
        while offset < size:
            chunk = await asyncio.to_thread(_read_at, path, offset, UPLOAD_CHUNK_BYTES)
            received = await self._send_chunk(attachment_id, offset, chunk)
            # A node answering the very offset it was handed staged nothing and never will, so the loop
            # would spin. A lower answer is the node naming where it really stands, which the next read
            # resumes from.
            if received == offset or received < 0:
                raise NodeError(f"PUT /rooms/attachments/{attachment_id}/data: no progress at offset {offset}")
            offset = received
        completed = await self._call("POST", f"/rooms/attachments/{attachment_id}/complete")
        return _attachment(_field(completed, "attachment", "attachment answer"))

    async def download(self, attachment_id: str, dest: pl.Path) -> None:
        """Stream one blob to `dest`, creating the directory it sits in."""
        path = f"/rooms/attachments/{attachment_id}"
        await asyncio.to_thread(dest.parent.mkdir, parents=True, exist_ok=True)
        try:
            async with self._session.get(self._base + path, headers=self._headers, timeout=self._timeout) as response:
                if response.status != 200:
                    raise NodeError(f"GET {path}: {_reason(_decode(await response.text(), path), response.status)}")
                handle = await asyncio.to_thread(dest.open, "wb")
                try:
                    async for chunk in response.content.iter_chunked(UPLOAD_CHUNK_BYTES):
                        await asyncio.to_thread(handle.write, chunk)
                finally:
                    handle.close()
        except (TimeoutError, aiohttp.ClientError) as error:
            raise NodeError(f"GET {path}: {error}") from error

    def ws_connect(self) -> aiohttp.client._WSRequestContextManager:
        """The live edge of every room this agent is in. The caller owns the socket's lifetime."""
        return self._session.ws_connect(f"{self._base}/rooms/ws", headers=self._headers)
