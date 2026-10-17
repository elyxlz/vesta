"""Tell vestad that the voice service changed, so every client reads its status again."""

import logging
import os

import aiohttp

logger = logging.getLogger("voice")

NOTIFY_TIMEOUT_SECS = 5


def _env(name: str) -> str:
    return os.environ[name] if name in os.environ else ""


async def notify(scope: str) -> None:
    """Best-effort POST to vestad. Outside a box (no vestad in the environment) it does nothing."""
    port, host, agent, token = _env("VESTAD_PORT"), _env("BOX_HOST"), _env("AGENT_NAME"), _env("AGENT_TOKEN")
    if not port or not host or not agent:
        return
    url = f"https://{host}:{port}/agents/{agent}/services/voice/invalidate"
    try:
        async with (
            aiohttp.ClientSession() as session,
            # vestad's certificate is self-signed, so the call does not verify it.
            session.post(
                url,
                json={"scope": scope},
                headers={"X-Agent-Token": token} if token else {},
                ssl=False,
                timeout=aiohttp.ClientTimeout(total=NOTIFY_TIMEOUT_SECS),
            ),
        ):
            pass
    except (TimeoutError, aiohttp.ClientError) as exc:
        logger.debug("invalidation notify failed: %s", exc)
