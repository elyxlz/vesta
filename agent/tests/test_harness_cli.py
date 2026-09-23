"""The harness spawns the `claude` on PATH, the binary core's pin governs, never the CLI the SDK
bundles inside its own package (which the SDK prefers whenever no path is given)."""

import stat

import core.config as cfg
from core.client import build_client_options
from core.config import ClaudeConfig


def _config(tmp_path):
    config = cfg.VestaConfig(agent_dir=tmp_path / "agent", provider=ClaudeConfig())
    config.agent_dir.mkdir(parents=True, exist_ok=True)
    (config.agent_dir / "MEMORY.md").write_text("memory")
    return config


def test_harness_runs_the_claude_on_path_not_the_sdk_bundled_one(tmp_path, state, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude = bin_dir / "claude"
    claude.write_text("#!/bin/sh\n")
    claude.chmod(claude.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", str(bin_dir))

    options = build_client_options(_config(tmp_path), state)

    assert options.cli_path == str(claude)
