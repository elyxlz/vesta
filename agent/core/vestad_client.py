"""Agent -> vestad lifecycle calls. The agent reaches its own vestad over the loopback with its
X-Agent-Token (the same channel the vesta-cloud-account skill uses), and vestad performs the docker action.
Because that action tears this process down shortly after, the calls are effectively
fire-and-forget: a connection cut mid-request is the expected success signal (vestad is stopping or
restarting the container under us). The action did NOT happen if vestad is unreachable, times out,
or answers an error status (on success it would have killed the container before replying) — all
returned as False so the caller can surface it."""

import os

import aiohttp

from . import lifecycle, logger

_TIMEOUT = aiohttp.ClientTimeout(total=15)
AGENT_RESTART_REASON = lifecycle.AGENT_RESTART


async def _request_lifecycle(
    action: str,
    *,
    reason: lifecycle.RestartReason | None = None,
) -> bool:
    """POST /agents/{me}/{action} to vestad (action = "restart" | "stop"). Returns True when vestad
    accepted it — including the connection being cut mid-request, the expected path once vestad
    starts tearing the container down — and False only when vestad could not be reached at all."""
    port = os.environ["VESTAD_PORT"] if "VESTAD_PORT" in os.environ else ""
    name = os.environ["AGENT_NAME"] if "AGENT_NAME" in os.environ else ""
    token = os.environ["AGENT_TOKEN"] if "AGENT_TOKEN" in os.environ else ""
    if not (port and name and token):
        logger.error("cannot reach vestad: missing VESTAD_PORT/AGENT_NAME/AGENT_TOKEN")
        return False
    url = f"https://localhost:{port}/agents/{name}/{action}"
    connector = aiohttp.TCPConnector(ssl=False)
    try:
        async with aiohttp.ClientSession(connector=connector, timeout=_TIMEOUT) as session:
            resp = await session.post(
                url,
                headers={"X-Agent-Token": token},
                json={
                    "reason": reason.log_reason,
                    "agent_message": reason.agent_message,
                }
                if reason is not None
                else None,
            )
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
    port = os.environ["VESTAD_PORT"] if "VESTAD_PORT" in os.environ else ""
    name = os.environ["AGENT_NAME"] if "AGENT_NAME" in os.environ else ""
    token = os.environ["AGENT_TOKEN"] if "AGENT_TOKEN" in os.environ else ""
    if not (port and name and token):
        logger.error("cannot send user notification to vestad: missing VESTAD_PORT/AGENT_NAME/AGENT_TOKEN")
        return
    url = f"https://localhost:{port}/agents/{name}/user-notification"
    payload = {"kind": kind, "title": title, "body": body}
    connector = aiohttp.TCPConnector(ssl=False)
    try:
        async with aiohttp.ClientSession(connector=connector, timeout=_TIMEOUT) as session:
            resp = await session.post(url, headers={"X-Agent-Token": token}, json=payload)
            resp.raise_for_status()
    except aiohttp.ClientError as exc:
        logger.warning(f"user notification to vestad failed ({kind}): {exc}")
    except TimeoutError:
        logger.warning(f"user notification to vestad timed out ({kind})")


async def request_restart(
    reason: lifecycle.RestartReason = AGENT_RESTART_REASON,
) -> bool:
    """Ask vestad to restart this agent's container (graceful docker restart)."""
    return await _request_lifecycle("restart", reason=reason)


async def request_stop() -> bool:
    """Ask vestad to stop this agent's container and keep it stopped (records user-desired stopped)."""
    return await _request_lifecycle("stop")
