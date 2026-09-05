"""The vestad helpers as async calls: register and deregister the browser service, mint, find, and revoke its keys.

Each helper is the script the agent already has on PATH (`register-service`, `deregister-service`,
`service-key`); nothing here talks HTTP to vestad directly, so the gateway contract stays with
those scripts.
"""

from __future__ import annotations

import asyncio
import json

GATEWAY_TIMEOUT_SECS = 35


class GatewayError(Exception):
    """A vestad helper script failed or is missing; the message is its stderr or the missing name."""


async def _run(*argv: str, timeout: float = GATEWAY_TIMEOUT_SECS) -> str:
    try:
        process = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except FileNotFoundError as exc:
        raise GatewayError(f"{argv[0]} is not on PATH") from exc
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise GatewayError(f"{argv[0]} did not answer within {timeout}s") from exc
    if process.returncode != 0:
        raise GatewayError(err.decode(errors="replace").strip() or f"{argv[0]} exited with {process.returncode}")
    return out.decode(errors="replace").strip()


async def register_service(name: str, timeout: float = GATEWAY_TIMEOUT_SECS) -> int:
    port = await _run("register-service", name, timeout=timeout)
    if not port.isdigit():
        raise GatewayError(f"register-service answered without a port: {port!r}")
    return int(port)


async def deregister_service(name: str, timeout: float = GATEWAY_TIMEOUT_SECS) -> None:
    await _run("deregister-service", name, timeout=timeout)


async def mint_key(service: str, label: str, ttl_secs: int, timeout: float = GATEWAY_TIMEOUT_SECS) -> str:
    secret = await _run("service-key", "mint", service, "--label", label, "--ttl", str(ttl_secs), timeout=timeout)
    if not secret:
        raise GatewayError("service-key mint answered without a key")
    return secret


async def find_key_id(service: str, label: str, timeout: float = GATEWAY_TIMEOUT_SECS) -> str | None:
    listing = json.loads(await _run("service-key", "list", service, timeout=timeout))
    if not isinstance(listing, dict) or not isinstance(listing["keys"], list):
        raise GatewayError("service-key list answered with an unexpected shape")
    for key in listing["keys"]:
        if isinstance(key, dict) and key["label"] == label:
            return str(key["id"])
    return None


async def revoke_key(service: str, key_id: str, timeout: float = GATEWAY_TIMEOUT_SECS) -> None:
    await _run("service-key", "revoke", service, key_id, timeout=timeout)
