"""Agent -> vestad lifecycle calls. The agent reaches its own vestad over the loopback with its
X-Agent-Token (the same channel the account skill uses), and vestad performs the docker action.
Because that action tears this process down shortly after, the calls are effectively
fire-and-forget: a connection cut mid-request is the expected success signal (vestad is stopping or
restarting the container under us). The action did NOT happen if vestad is unreachable, times out,
or answers an error status (on success it would have killed the container before replying) — all
returned as False so the caller can surface it."""

import os

import aiohttp

from . import logger

_TIMEOUT = aiohttp.ClientTimeout(total=15)


async def _request_lifecycle(action: str) -> bool:
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
            resp = await session.post(url, headers={"X-Agent-Token": token})
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


async def request_restart() -> bool:
    """Ask vestad to restart this agent's container (graceful docker restart)."""
    return await _request_lifecycle("restart")


async def request_stop() -> bool:
    """Ask vestad to stop this agent's container and keep it stopped (records user-desired stopped)."""
    return await _request_lifecycle("stop")
