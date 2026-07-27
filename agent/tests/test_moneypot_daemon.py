"""The moneypot wrapper derives its port mode from the API key file, so there is one launch
path rather than a private variant and a public one."""

import os
import pathlib as pl
import subprocess

REPO_ROOT = pl.Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "agent/skills/moneypot/scripts/daemon"

STUB_RUNNER = """#!/bin/sh
printf '%s\\n' "$*" > "$RECORDED_ARGV"
printf '%s\\n' "${MONEYPOT_API_KEY:-<unset>}" > "$RECORDED_KEY"
"""


def _invoke(tmp_path: pl.Path, *, key_file: bool) -> tuple[str, str]:
    """Run the wrapper against a stub runner that records the argv and environment it saw."""
    scripts = tmp_path / "agent/skills/vestad/scripts"
    scripts.mkdir(parents=True)
    stub = scripts / "daemon-lifecycle"
    stub.write_text(STUB_RUNNER)
    stub.chmod(0o755)

    data = tmp_path / "agent/data"
    data.mkdir(parents=True)
    if key_file:
        (data / "moneypot-api-key").write_text("s3cret\n")

    recorded_argv = tmp_path / "argv"
    recorded_key = tmp_path / "key"
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    env["RECORDED_ARGV"] = str(recorded_argv)
    env["RECORDED_KEY"] = str(recorded_key)

    result = subprocess.run(["sh", str(WRAPPER), "start"], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    return recorded_argv.read_text(), recorded_key.read_text().strip()


def test_registers_private_when_no_api_key_file_exists(tmp_path):
    argv, key = _invoke(tmp_path, key_file=False)
    assert "--port-mode private" in argv
    assert key == "<unset>"


def test_registers_public_when_an_api_key_file_exists(tmp_path):
    argv, key = _invoke(tmp_path, key_file=True)
    assert "--port-mode public" in argv
    assert key == "s3cret"


def test_declares_its_session_and_service(tmp_path):
    argv, _ = _invoke(tmp_path, key_file=False)
    assert "--session moneypot" in argv
    assert "--service moneypot" in argv
