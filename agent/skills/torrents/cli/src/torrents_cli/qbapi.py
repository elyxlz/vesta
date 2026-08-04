"""Transport and endpoint compatibility for the qBittorrent WebUI API.

Two transports, chosen by environment: with MEDIA_SERVER_HOST set, every call is curl run on the
media server over SSH (qBittorrent there is bound to localhost); otherwise direct HTTP to
QB_HOST (default BOX_HOST) : QB_PORT. File uploads work on both: over SSH the .torrent bytes are
streamed through ssh stdin into curl, so the file never needs to exist on the server first.

qBittorrent 5.x renamed the pause endpoints (torrents/pause -> torrents/stop and
torrents/resume -> torrents/start, WebAPI 2.11) and removed the old names, so stop_torrents and
start_torrents try the current name and fall back to the legacy one on 404.
"""

import dataclasses
import json
import os
import pathlib as pl
import shlex
import subprocess
import typing as tp
import urllib.error
import urllib.parse
import urllib.request

Json = None | bool | int | float | str | list["Json"] | dict[str, "Json"]

HTTP_TIMEOUT_SECS = 60
SSH_TIMEOUT_SECS = 90


def env(name: str, default: str) -> str:
    return os.environ[name] if name in os.environ else default


@dataclasses.dataclass(frozen=True)
class Server:
    ssh_host: str | None
    ssh_user: str
    ssh_port: str
    qb_host: str
    qb_port: str

    @property
    def base(self) -> str:
        host = "localhost" if self.ssh_host else self.qb_host
        return f"http://{host}:{self.qb_port}/api/v2"


def server_from_env() -> Server:
    return Server(
        ssh_host=os.environ["MEDIA_SERVER_HOST"] if "MEDIA_SERVER_HOST" in os.environ else None,
        ssh_user=env("MEDIA_SERVER_USER", "media"),
        ssh_port=env("MEDIA_SERVER_SSH_PORT", "22"),
        qb_host=env("QB_HOST", env("BOX_HOST", "host.docker.internal")),
        qb_port=env("QB_PORT", "8888"),
    )


class ApiError(Exception):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _ssh_run(server: Server, command: str, *, stdin: bytes | None = None) -> bytes:
    if not server.ssh_host:
        raise ApiError("this command needs a media server: set MEDIA_SERVER_HOST")
    proc = subprocess.run(
        ["ssh", "-p", server.ssh_port, f"{server.ssh_user}@{server.ssh_host}", command],
        input=stdin,
        capture_output=True,
        timeout=SSH_TIMEOUT_SECS,
        check=False,
    )
    if proc.returncode != 0:
        raise ApiError(f"ssh to {server.ssh_host} failed: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout


def ssh_text(server: Server, command: str) -> str:
    """Run a shell command on the media server and return its stdout."""
    return _ssh_run(server, command).decode(errors="replace")


def api(server: Server, path: str, data: dict[str, str] | None = None, file: pl.Path | None = None) -> Json:
    """One qBittorrent API call over whichever transport the server uses.

    `data` fields go as a form POST; `file` additionally uploads a .torrent as multipart under
    the `torrents` field. GET when both are None.
    """
    raw = _call_ssh(server, path, data, file) if server.ssh_host else _call_http(server, path, data, file)
    try:
        return tp.cast(Json, json.loads(raw))
    except json.JSONDecodeError:
        return raw.strip()


def stop_torrents(server: Server, hashes: str) -> Json:
    return _first_supported(server, ("torrents/stop", "torrents/pause"), {"hashes": hashes})


def start_torrents(server: Server, hashes: str) -> Json:
    return _first_supported(server, ("torrents/start", "torrents/resume"), {"hashes": hashes})


def _first_supported(server: Server, paths: tuple[str, ...], data: dict[str, str]) -> Json:
    for index, path in enumerate(paths):
        try:
            return api(server, path, data)
        except ApiError as error:
            if error.status != 404 or index + 1 == len(paths):
                raise
    raise ApiError(f"no supported endpoint among {paths}")


def _call_ssh(server: Server, path: str, data: dict[str, str] | None, file: pl.Path | None) -> str:
    url = f"{server.base}/{path}"
    parts = ["curl", "-sS", "-w", shlex.quote("\\n%{http_code}")]
    stdin: bytes | None = None
    if file is not None:
        for key, value in (data or {}).items():
            parts += ["-F", shlex.quote(f"{key}={value}")]
        parts += ["-F", shlex.quote(f"torrents=@-;filename={file.name};type=application/x-bittorrent")]
        stdin = file.read_bytes()
    else:
        for key, value in (data or {}).items():
            parts += ["--data-urlencode", shlex.quote(f"{key}={value}")]
    parts.append(shlex.quote(url))
    body, _, status = _ssh_run(server, " ".join(parts), stdin=stdin).decode(errors="replace").rpartition("\n")
    if not status.isdigit() or int(status) >= 400:
        raise ApiError(f"qBittorrent returned {status} for {path}", status=int(status) if status.isdigit() else None)
    return body


def _call_http(server: Server, path: str, data: dict[str, str] | None, file: pl.Path | None) -> str:
    url = f"{server.base}/{path}"
    if file is not None:
        boundary = "----qb7f3a9"
        body = b""
        for key, value in (data or {}).items():
            body += f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
        body += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="torrents"; filename="{file.name}"\r\n'
            f"Content-Type: application/x-bittorrent\r\n\r\n"
        ).encode()
        body += file.read_bytes() + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        request = urllib.request.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    else:
        payload = urllib.parse.urlencode(data).encode() if data is not None else None
        request = urllib.request.Request(url, data=payload)
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECS) as response:
            return response.read().decode(errors="replace")
    except urllib.error.HTTPError as error:
        raise ApiError(f"qBittorrent returned {error.code} for {path}", status=error.code) from error
    except urllib.error.URLError as error:
        raise ApiError(f"cannot reach qBittorrent at {server.base}: {error.reason}") from error
