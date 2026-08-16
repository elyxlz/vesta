"""Agent -> vestad lifecycle calls. The agent reaches its own vestad over the loopback with its
X-Agent-Token (the same channel the vesta-cloud skill uses), and vestad performs the docker action.
Because that action tears this process down shortly after, the calls are effectively
fire-and-forget: a connection cut mid-request is the expected success signal (vestad is stopping or
restarting the container under us). The action did NOT happen if vestad is unreachable, times out,
or answers an error status (on success it would have killed the container before replying) — all
returned as False so the caller can surface it."""

import os
import typing as tp

import aiohttp
import pydantic as pyd

from . import lifecycle, logger

_TIMEOUT = aiohttp.ClientTimeout(total=15)


class AgentEndpoint(tp.NamedTuple):
    url: str
    token: str


def _agent_endpoint(path: str) -> AgentEndpoint | None:
    """The self-scoped vestad URL `/agents/{me}/{path}` plus this agent's token, or None (logged) when
    the identity env is incomplete."""
    host = os.environ["BOX_HOST"] if "BOX_HOST" in os.environ else ""
    port = os.environ["VESTAD_PORT"] if "VESTAD_PORT" in os.environ else ""
    name = os.environ["AGENT_NAME"] if "AGENT_NAME" in os.environ else ""
    token = os.environ["AGENT_TOKEN"] if "AGENT_TOKEN" in os.environ else ""
    if not (host and port and name and token):
        logger.error(f"cannot reach vestad for {path}: missing BOX_HOST/VESTAD_PORT/AGENT_NAME/AGENT_TOKEN")
        return None
    return AgentEndpoint(url=f"https://{host}:{port}/agents/{name}/{path}", token=token)


def _agent_session(token: str) -> aiohttp.ClientSession:
    """One session per call to vestad: its self-signed TLS, the shared timeout, and the agent token
    header on every request."""
    return aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False), timeout=_TIMEOUT, headers={"X-Agent-Token": token})


async def _request_lifecycle(action: str, *, reason: lifecycle.RestartReason | None = None) -> bool:
    """POST /agents/{me}/{action} to vestad (action = "restart" | "stop"). Returns True when vestad
    accepted it — including the connection being cut mid-request, the expected path once vestad
    starts tearing the container down — and False only when vestad could not be reached at all."""
    endpoint = _agent_endpoint(action)
    if endpoint is None:
        return False
    url, token = endpoint
    body = None if reason is None else {"reason": reason.log_reason, "agent_message": reason.agent_message}
    try:
        async with _agent_session(token) as session:
            resp = await session.post(url, json=body)
            resp.raise_for_status()
        # vestad answered 2xx without tearing us down yet (rare — a real restart/stop usually cuts
        # the connection first, below). The action was accepted.
        return True
    except aiohttp.ClientResponseError as exc:
        # vestad answered, but rejected the action (auth/path scope, route skew, or a docker error).
        # On success it would have killed the container before responding, so a response means failure.
        logger.error(f"vestad rejected {action}: HTTP {exc.status}")
        return False
    except aiohttp.ClientConnectorError as exc:
        # Never connected — vestad is down; the action did not happen.
        logger.error(f"vestad unreachable for {action}: {exc}")
        return False
    except aiohttp.ClientError:
        # Connected, then the request was cut mid-flight — the expected success path: vestad is
        # tearing this container down.
        return True
    except TimeoutError:
        logger.error(f"vestad timed out on {action}")
        return False


async def send_user_notification(kind: str, title: str, body: str) -> None:
    """POST /agents/{me}/user-notification to vestad, which fans a `user_notification` delta to
    connected clients and an Expo push to backgrounded mobile. Best-effort: any missing identity,
    transport failure, non-2xx, or timeout is logged and swallowed, so surfacing a user notification
    never disrupts the turn that emitted it (the durable work it describes already happened). `kind` is
    one of "message"/"rate_limited"."""
    endpoint = _agent_endpoint("user-notification")
    if endpoint is None:
        return
    url, token = endpoint
    payload = {"kind": kind, "title": title, "body": body}
    try:
        async with _agent_session(token) as session:
            resp = await session.post(url, json=payload)
            resp.raise_for_status()
    except aiohttp.ClientError as exc:
        logger.warning(f"user notification to vestad failed ({kind}): {exc}")
    except TimeoutError:
        logger.warning(f"user notification to vestad timed out ({kind})")


async def fetch_user_devices() -> pyd.JsonValue | None:
    """GET /agents/{me}/devices: every device the user has, with what each reported about itself (its
    IANA timezone; on a phone that shares it, its position plus the macro place). None (logged) when
    vestad cannot answer, so the caller reports that instead of guessing."""
    endpoint = _agent_endpoint("devices")
    if endpoint is None:
        return None
    url, token = endpoint
    try:
        async with _agent_session(token) as session:
            resp = await session.get(url)
            resp.raise_for_status()
            body: pyd.JsonValue = await resp.json()
            return body
    except aiohttp.ClientError as exc:
        logger.warning(f"user devices fetch from vestad failed: {exc}")
    except TimeoutError:
        logger.warning("user devices fetch from vestad timed out")
    return None


async def request_restart(reason: lifecycle.RestartReason = lifecycle.AGENT_RESTART) -> bool:
    """Ask vestad to restart this agent's container (graceful docker restart)."""
    return await _request_lifecycle("restart", reason=reason)


async def request_stop() -> bool:
    """Ask vestad to stop this agent's container and keep it stopped (records user-desired stopped)."""
    return await _request_lifecycle("stop")
