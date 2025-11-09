"""Context for what-day MCP - minimal since this is stateless."""

import argparse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from mcp.server.fastmcp import FastMCP


def _validate_directory(path_str: str | None, param_name: str) -> Path:
    """Validate and prepare a directory parameter"""
    if not path_str:
        raise ValueError(f"Error: --{param_name} is required")

    path = Path(path_str).resolve()
    path.mkdir(parents=True, exist_ok=True)

    # Test writability
    test_file = path / ".write_test"
    try:
        test_file.touch()
        test_file.unlink()
    except Exception as e:
        raise RuntimeError(f"Error: --{param_name} directory is not writable: {path} ({e})")

    return path


@dataclass
class WhatDayContext:
    """Context for what-day MCP. Stateless but requires directories for consistency."""

    data_dir: Path
    log_dir: Path


@asynccontextmanager
async def what_day_lifespan(server: FastMCP) -> AsyncIterator[WhatDayContext]:
    """Lifespan manager for what-day MCP.

    Requires data_dir and log_dir for consistency across all MCPs.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=str, required=True)
    parser.add_argument("--log-dir", type=str, required=True)
    args, _ = parser.parse_known_args()

    data_dir = _validate_directory(args.data_dir, "data-dir")
    log_dir = _validate_directory(args.log_dir, "log-dir")

    ctx = WhatDayContext(data_dir, log_dir)

    try:
        yield ctx
    finally:
        pass
