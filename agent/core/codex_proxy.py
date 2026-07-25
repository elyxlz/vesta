"""Lifecycle for the local ChatGPT-subscription bridge used by the Claude Code harness."""

import asyncio
import os
import socket

import aiohttp

from . import logger
from .config import VestaConfig
from .models import State

_START_ATTEMPTS = 5
_START_TIMEOUT_S = 10.0


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _wait_ready(url: str, process: asyncio.subprocess.Process) -> bool:
    deadline = asyncio.get_running_loop().time() + _START_TIMEOUT_S
    async with aiohttp.ClientSession() as session:
        while asyncio.get_running_loop().time() < deadline:
            if process.returncode is not None:
                return False
            try:
                async with session.get(f"{url}/healthz", timeout=aiohttp.ClientTimeout(total=0.5)) as response:
                    if response.status == 200:
                        return True
            except (TimeoutError, aiohttp.ClientError):
                pass
            await asyncio.sleep(0.1)
    return False


async def start_codex_proxy(config: VestaConfig, state: State) -> None:
    """Start the pinned bridge on a free loopback port, retrying the tiny bind race."""
    if state.codex_proxy_url is not None:
        return
    env = os.environ.copy()
    env["CCP_CONFIG_DIR"] = str(config.data_dir / "claude-code-proxy")
    for _ in range(_START_ATTEMPTS):
        port = _available_port()
        url = f"http://127.0.0.1:{port}"
        env["PORT"] = str(port)
        process = await asyncio.create_subprocess_exec(
            "claude-code-proxy",
            "serve",
            "--no-monitor",
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        if await _wait_ready(url, process):
            state.codex_proxy_process = process
            state.codex_proxy_url = url
            logger.startup(f"OpenAI subscription bridge listening on {url}")
            return
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except TimeoutError:
                process.kill()
                await process.wait()
    raise RuntimeError("OpenAI subscription bridge failed to start")
