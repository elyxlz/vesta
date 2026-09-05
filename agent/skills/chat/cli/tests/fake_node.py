"""An in-process fake of vestad's chat node: the rooms, the message log with its global id sequence,
the attachment protocol, the peers list, and the live socket, answering the node's exact status codes
and bodies. It runs on a real aiohttp TestServer over plain http, so the client, the replica and the
command suites all drive real HTTP against it.

Test hooks: `emit` pushes one frame to every connected socket, `refuse_speaking` and `refuse_burst`
turn a post into the node's two refusals, `drop_answers_at` lands the chunk at that offset and then
kills the connection (an answer lost on the way back), `rewind_stage_to` refuses one chunk whole and
names a staged size behind it, `stall_chunks` refuses every chunk naming the offset it was handed,
and `requests` records every (method, path with its query, json body)."""

import contextlib
import dataclasses
import datetime as dt
import json
import typing as tp
import uuid

from aiohttp import web
from aiohttp.test_utils import TestServer
from chat_cli.attachments import AttachmentMeta
from chat_cli.node_client import JsonValue, NodeClient, NodeConfig, NodeMessage, new_session

SPEAKING_REFUSAL = "the user is talking right now: drop this reply, wait for their next message, then answer the whole thought"
BURST_REFUSAL = "burst guard: this room holds 40 agent messages since the user last spoke; stop until the user writes again"

DEFAULT_PAGE_SIZE = 50
_TOKEN_HEADER = "X-Agent-Token"
_GROUP_ID_HEX_CHARS = 12


@dataclasses.dataclass
class FakeRoom:
    id: str
    name: str | None
    agents: list[str]
    created_at: int = 0
    last_message_at: int | None = None

    def wire(self) -> dict[str, JsonValue]:
        """The room as the node serializes it: camelCase, like the rest of the tree."""
        return {
            "id": self.id,
            "name": self.name,
            "agents": list(self.agents),
            "createdAt": self.created_at,
            "lastMessageAt": self.last_message_at,
        }


@dataclasses.dataclass
class FakeUpload:
    meta: AttachmentMeta
    data: bytearray
    finalized: bool = False


def _stamp() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _readable_ts(ts: str) -> bool:
    try:
        dt.datetime.fromisoformat(ts)
    except ValueError:
        return False
    return True


def room_id_for(agents: list[str], name: str | None) -> str:
    """The node's id derivation: a named room is a group, one agent is its direct room, two agents are
    a peer room, and three or more without a name have no id."""
    if name is not None:
        return f"grp-{uuid.uuid4().hex[:_GROUP_ID_HEX_CHARS]}"
    if len(agents) == 1:
        return f"dm:{agents[0]}"
    return f"dm:{agents[0]}:{agents[1]}"


class FakeNode:
    """Everything the node holds, plus the app serving it. Tests seed state through `seed_room` and
    `seed_message`, or drive the routes exactly as the client does."""

    def __init__(self, agent: str = "vesta", token: str = "agent-token") -> None:
        self.agent = agent
        self.token = token
        self.rooms: dict[str, FakeRoom] = {}
        self.messages: list[NodeMessage] = []
        self.attachments: dict[str, FakeUpload] = {}
        self.peers: list[str] = []
        self.requests: list[tuple[str, str, JsonValue]] = []
        self.sockets: list[web.WebSocketResponse] = []
        self.refuse_speaking = False
        self.refuse_burst = False
        self.drop_answers_at: int | None = None
        self.rewind_stage_to: int | None = None
        self.stall_chunks = False
        self._next_id = 0
        self.app = web.Application(middlewares=[self._gate()])
        self.app.router.add_get("/rooms", self._list_rooms)
        self.app.router.add_post("/rooms", self._open_room)
        self.app.router.add_get("/rooms/ws", self._socket)
        self.app.router.add_post("/rooms/attachments", self._create_attachment)
        self.app.router.add_put("/rooms/attachments/{id}/data", self._attachment_data)
        self.app.router.add_get("/rooms/attachments/{id}/status", self._attachment_status)
        self.app.router.add_post("/rooms/attachments/{id}/complete", self._complete_attachment)
        self.app.router.add_get("/rooms/attachments/{id}", self._serve_attachment)
        self.app.router.add_get("/rooms/{id}/history", self._history)
        self.app.router.add_post("/rooms/{id}/messages", self._post_message)
        self.app.router.add_post("/rooms/{id}/messages/import", self._import)
        self.app.router.add_get("/agents/{name}/peers", self._peers)

    def _gate(self) -> tp.Callable[..., tp.Awaitable[web.StreamResponse]]:
        """Record every request, then answer 401 unless it carries this agent's token."""

        @web.middleware
        async def gate(request: web.Request, handler: tp.Callable[[web.Request], tp.Awaitable[web.StreamResponse]]) -> web.StreamResponse:
            body: JsonValue = None
            if request.content_type == "application/json":
                body = await request.json()
            self.requests.append((request.method, request.path_qs, body))
            if _TOKEN_HEADER not in request.headers or request.headers[_TOKEN_HEADER] != self.token:
                return web.json_response({"error": "unauthorized"}, status=401)
            return await handler(request)

        return gate

    def seed_room(self, agents: list[str], name: str | None = None) -> FakeRoom:
        room = FakeRoom(id=room_id_for(sorted(agents), name), name=name, agents=sorted(agents))
        self.rooms[room.id] = room
        return room

    def seed_message(self, room: str, kind: str, sender: str, text: str) -> NodeMessage:
        return self._append(room, kind, sender, text, [])

    def _append(
        self,
        room: str,
        kind: str,
        sender: str,
        text: str,
        attachments: list[AttachmentMeta],
        origin_id: int | None = None,
        input_method: str | None = None,
    ) -> NodeMessage:
        self._next_id += 1
        message: NodeMessage = {"id": self._next_id, "ts": _stamp(), "room": room, "type": kind, "sender": sender, "text": text}
        if attachments:
            message["attachments"] = attachments
        if origin_id is not None:
            message["origin_id"] = origin_id
        if input_method is not None:
            message["input_method"] = input_method
        self.messages.append(message)
        return message

    async def emit(self, event: JsonValue) -> None:
        """Push one frame to every connected socket, as the node's live edge does."""
        for socket in list(self.sockets):
            await socket.send_str(json.dumps(event))

    async def close_sockets(self) -> None:
        """Drop every live socket, which is what a node restart looks like to a replica."""
        for socket in list(self.sockets):
            await socket.close()

    async def _list_rooms(self, _request: web.Request) -> web.StreamResponse:
        mine = [room.wire() for room in self.rooms.values() if self.agent in room.agents]
        return web.json_response({"rooms": mine})

    async def _open_room(self, request: web.Request) -> web.StreamResponse:
        body = await request.json()
        agents = sorted(body["agents"])
        name = body["name"] if "name" in body else None
        if name is None and len(agents) > 2:
            return web.json_response({"error": "a room with three or more agents needs a name"}, status=400)
        # Only a derived id can be claimed twice: a named room mints a fresh group id on every open,
        # so two rooms of the same people under the same name are two rooms.
        room_id = room_id_for(agents, name)
        if room_id in self.rooms:
            return web.json_response({"room": self.rooms[room_id].wire()})
        room = FakeRoom(id=room_id, name=name, agents=agents)
        self.rooms[room.id] = room
        return web.json_response({"room": room.wire()}, status=201)

    async def _history(self, request: web.Request) -> web.StreamResponse:
        room = request.match_info["id"]
        if room not in self.rooms:
            return web.json_response({"error": "no such room"}, status=404)
        after = int(request.query["after"]) if "after" in request.query else 0
        limit = int(request.query["limit"]) if "limit" in request.query else DEFAULT_PAGE_SIZE
        matching = [message for message in self.messages if message["room"] == room and message["id"] > after]
        page = matching[:limit]
        cursor = page[-1]["id"] if page and len(matching) > limit else None
        return web.json_response({"events": page, "cursor": cursor})

    async def _post_message(self, request: web.Request) -> web.StreamResponse:
        room = request.match_info["id"]
        if room not in self.rooms:
            return web.json_response({"error": "no such room"}, status=404)
        body = await request.json()
        text = body["text"] if "text" in body else ""
        ids = body["attachments"] if "attachments" in body else []
        for attachment_id in ids:
            if attachment_id not in self.attachments or not self.attachments[attachment_id].finalized:
                return web.json_response({"error": f"unknown attachment: {attachment_id}"}, status=400)
        if self.refuse_speaking:
            return web.json_response({"error": SPEAKING_REFUSAL, "user_speaking": True}, status=409)
        if self.refuse_burst:
            return web.json_response({"error": BURST_REFUSAL}, status=429)
        message = self._append(room, "chat", self.agent, text, [self.attachments[one].meta for one in ids])
        await self.emit(message)
        return web.json_response({"ok": True, "id": message["id"]})

    async def _import(self, request: web.Request) -> web.StreamResponse:
        room = request.match_info["id"]
        if room not in self.rooms:
            return web.json_response({"error": "no such room"}, status=404)
        body = await request.json()
        items = body["messages"]
        for item in items:
            if not _readable_ts(item["ts"]):
                return web.json_response({"error": f"invalid ts on origin_id {item['origin_id']}"}, status=400)
        known = {message["origin_id"] for message in self.messages if "origin_id" in message}
        outcome = {"imported": 0, "skipped": 0}
        for item in items:
            if item["origin_id"] in known:
                outcome["skipped"] += 1
                continue
            known.add(item["origin_id"])
            sender = self.agent if item["type"] == "chat" else "user"
            metas = [self.attachments[one].meta for one in item["attachments"] if one in self.attachments] if "attachments" in item else []
            self._append(room, item["type"], sender, item["text"], metas, origin_id=item["origin_id"])
            outcome["imported"] += 1
        return web.json_response(outcome)

    async def _peers(self, _request: web.Request) -> web.StreamResponse:
        return web.json_response({"peers": list(self.peers)})

    async def _create_attachment(self, request: web.Request) -> web.StreamResponse:
        body = await request.json()
        meta: AttachmentMeta = {"id": uuid.uuid4().hex, "name": body["name"], "mime": body["mime"], "size": body["size"]}
        if "width" in body:
            meta["width"] = body["width"]
        if "height" in body:
            meta["height"] = body["height"]
        if "duration_secs" in body:
            meta["duration_secs"] = body["duration_secs"]
        self.attachments[meta["id"]] = FakeUpload(meta=meta, data=bytearray())
        return web.json_response({"id": meta["id"]})

    def _upload(self, request: web.Request) -> FakeUpload | None:
        attachment_id = request.match_info["id"]
        return self.attachments[attachment_id] if attachment_id in self.attachments else None

    async def _attachment_data(self, request: web.Request) -> web.StreamResponse:
        upload = self._upload(request)
        if upload is None:
            return web.json_response({"error": "unknown attachment"}, status=404)
        offset = int(request.query["offset"])
        # The lost-answer hook: the bytes land and the connection dies before the answer reaches the
        # uploader, which is the one case that leaves the client not knowing where the node stands.
        if offset == self.drop_answers_at:
            if offset == len(upload.data):
                upload.data.extend(await request.read())
            transport = request.transport
            if transport is not None:
                transport.abort()
            return web.Response(status=204)
        # A node that lost part of its stage: the first chunk reaching past that point is refused
        # whole, so the 409 names a staged size behind the offset the uploader asked for.
        if self.rewind_stage_to is not None and offset > self.rewind_stage_to:
            del upload.data[self.rewind_stage_to :]
            self.rewind_stage_to = None
            return web.json_response({"error": "offset mismatch", "received": len(upload.data)}, status=409)
        # A node reporting the offset it was handed: it staged nothing, and the uploader must give up
        # rather than send that chunk forever.
        if self.stall_chunks:
            return web.json_response({"error": "offset mismatch", "received": offset}, status=409)
        if offset != len(upload.data):
            return web.json_response({"error": "offset mismatch", "received": len(upload.data)}, status=409)
        upload.data.extend(await request.read())
        return web.json_response({"ok": True, "received": len(upload.data)})

    async def _attachment_status(self, request: web.Request) -> web.StreamResponse:
        upload = self._upload(request)
        if upload is None:
            return web.json_response({"error": "unknown attachment"}, status=404)
        return web.json_response({"received": len(upload.data), "size": upload.meta["size"], "finalized": upload.finalized})

    async def _complete_attachment(self, request: web.Request) -> web.StreamResponse:
        upload = self._upload(request)
        if upload is None:
            return web.json_response({"error": "unknown attachment"}, status=404)
        if len(upload.data) != upload.meta["size"]:
            return web.json_response({"error": f"staged {len(upload.data)} of declared {upload.meta['size']} bytes"}, status=409)
        upload.finalized = True
        return web.json_response({"attachment": upload.meta})

    async def _serve_attachment(self, request: web.Request) -> web.StreamResponse:
        upload = self._upload(request)
        if upload is None or not upload.finalized:
            return web.json_response({"error": "unknown attachment"}, status=404)
        return web.Response(body=bytes(upload.data), content_type=upload.meta["mime"])

    async def _socket(self, request: web.Request) -> web.StreamResponse:
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        self.sockets.append(socket)
        try:
            async for _ in socket:
                pass
        finally:
            self.sockets.remove(socket)
        return socket


@contextlib.asynccontextmanager
async def running_node(fake: FakeNode) -> tp.AsyncIterator[str]:
    """Serve the fake and yield the base url the client dials, plain http so no certificate is involved."""
    server = TestServer(fake.app)
    await server.start_server()
    try:
        yield str(server.make_url("")).rstrip("/")
    finally:
        await fake.close_sockets()
        await server.close()


@contextlib.asynccontextmanager
async def connected_client(fake: FakeNode) -> tp.AsyncIterator[NodeClient]:
    """A NodeClient wired to a running fake, on the session the client ships."""
    async with running_node(fake) as base_url:
        config: NodeConfig = {"base_url": base_url, "token": fake.token, "agent": fake.agent}
        session = new_session(config)
        try:
            yield NodeClient(config, session)
        finally:
            await session.close()
