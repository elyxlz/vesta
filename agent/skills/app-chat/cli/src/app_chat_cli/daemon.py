"""App Chat daemon.

Connects to the agent's /ws endpoint. Writes notification files for inbound
user messages and accepts CLI commands via Unix socket to send replies.
"""

import asyncio
import datetime as dt
import json
import os
import pathlib as pl
import signal
import sys
import uuid

import aiohttp


RECONNECT_DELAY = 2.0


def cmd_serve(args: object) -> None:
    notifications_dir = pl.Path(args.notifications_dir)
    ws_url = args.ws_url
    data_dir = pl.Path(args.data_dir or pl.Path.home() / ".app-chat")

    notifications_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    sock_path = data_dir / "app-chat.sock"

    daemon = AppChatDaemon(
        notifications_dir=notifications_dir,
        ws_url=ws_url,
        sock_path=sock_path,
    )
    asyncio.run(daemon.run())


class AppChatDaemon:
    def __init__(
        self,
        *,
        notifications_dir: pl.Path,
        ws_url: str,
        sock_path: pl.Path,
    ) -> None:
        self.notifications_dir = notifications_dir
        self.ws_url = ws_url
        self.sock_path = sock_path
        self._shutdown = asyncio.Event()
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None

    async def run(self) -> None:
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._shutdown.set)

        self._session = aiohttp.ClientSession()
        try:
            tasks = [
                asyncio.create_task(self._ws_loop()),
                asyncio.create_task(self._socket_server()),
            ]
            await self._shutdown.wait()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await self._session.close()
            self.sock_path.unlink(missing_ok=True)

    async def _ws_loop(self) -> None:
        """Connect to /ws, watch for user messages, write notifications."""
        while not self._shutdown.is_set():
            try:
                assert self._session is not None
                async with self._session.ws_connect(self.ws_url) as ws:
                    self._ws = ws
                    _log(f"connected to {self.ws_url}")
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._handle_event(msg.data)
                        elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                            break
            except (aiohttp.ClientError, OSError) as exc:
                _log(f"ws error: {exc}")
            finally:
                self._ws = None
            if not self._shutdown.is_set():
                await asyncio.sleep(RECONNECT_DELAY)

    async def _handle_event(self, raw: str) -> None:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return
        if event.get("type") == "user":
            self._write_notification(event.get("text", ""), timestamp=event.get("ts"))

    def _write_notification(self, message: str, *, timestamp: str | None = None) -> None:
        if not message.strip():
            return
        ts = timestamp or dt.datetime.now(dt.UTC).isoformat()
        notification = {
            "timestamp": ts,
            "source": "app-chat",
            "type": "message",
            "message": message,
            "interrupt": True,
        }
        filename = f"{uuid.uuid4()}-app-chat-message.json"
        path = self.notifications_dir / filename
        path.write_text(json.dumps(notification), encoding="utf-8")
        _log(f"notification: {filename}")

    async def _socket_server(self) -> None:
        """Unix socket server for CLI commands (e.g. app-chat send)."""
        self.sock_path.unlink(missing_ok=True)

        server = await asyncio.start_unix_server(self._handle_socket_conn, path=str(self.sock_path))
        os.chmod(str(self.sock_path), 0o600)
        _log(f"socket server: {self.sock_path}")

        try:
            await self._shutdown.wait()
        finally:
            server.close()
            await server.wait_closed()

    async def _handle_socket_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            data = await asyncio.wait_for(reader.read(65536), timeout=30.0)
            request = json.loads(data.decode())
            command = request.get("command")

            if command == "send":
                message = request.get("message", "").strip()
                if not message:
                    response = {"error": "empty message"}
                elif self._ws and not self._ws.closed:
                    await self._ws.send_json({"type": "chat", "text": message})
                    response = {"ok": True, "message": message}
                else:
                    response = {"error": "not connected to agent"}
            else:
                response = {"error": f"unknown command: {command}"}

            writer.write(json.dumps(response).encode())
            await writer.drain()
        except (json.JSONDecodeError, TimeoutError, OSError):
            pass
        finally:
            writer.close()


def _log(message: str) -> None:
    print(f"[app-chat] {message}", file=sys.stderr, flush=True)
