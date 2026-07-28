"""`ssh-tunnel setup`: the verb that authorizes a key and owns the sshd the tunnel is pointed at.

Runs the real command in a hermetic HOME whose sshd records are already seeded, which is the
state in which setup never reaches its bring-up path, so no root and no sshd are involved. What
is pinned here is that a second run adds a key without moving the port a live tunnel is using.
"""

import json
import os
import pathlib as pl
import subprocess

import pytest

REPO_ROOT = pl.Path(__file__).resolve().parents[2]
SSH_TUNNEL = REPO_ROOT / "agent/skills/ssh/ssh-tunnel"
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFirst first@laptop"
OTHER_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAISecond second@desktop"
SSHD_PORT = 2201
KEEPER_SECS = "120"


@pytest.fixture
def box(tmp_path):
    """A HOME whose sshd is up: the port the tunnel reads, and a pid that answers a liveness check."""
    home = tmp_path / "home"
    daemons = home / "agent/data/daemons"
    daemons.mkdir(parents=True)
    keeper = subprocess.Popen(["sleep", KEEPER_SECS])
    (daemons / "ssh-tunnel.sshd-pid").write_text(str(keeper.pid))
    (daemons / "ssh-tunnel.sshd-port").write_text(str(SSHD_PORT))
    yield home
    keeper.kill()
    keeper.wait()


def _setup(home: pl.Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "HOME": str(home)}
    return subprocess.run([str(SSH_TUNNEL), "setup", *args], env=env, capture_output=True, text=True, check=False, timeout=30)


def _authorized(home: pl.Path) -> list[str]:
    return (home / ".ssh/authorized_keys").read_text().splitlines()


def _perms(path: pl.Path) -> str:
    return oct(path.stat().st_mode)[-3:]


def test_setup_authorizes_a_key_against_the_running_sshd(box):
    result = _setup(box, KEY)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"status": "ready", "sshd_port": SSHD_PORT}
    assert _authorized(box) == [KEY]


def test_setup_keeps_the_key_file_private(box):
    """sshd refuses a key file the world can read, so the verb owns both modes."""
    assert _setup(box, KEY).returncode == 0
    assert _perms(box / ".ssh") == "700"
    assert _perms(box / ".ssh/authorized_keys") == "600"


def test_setup_run_again_with_the_same_key_changes_nothing(box):
    """The same machine asking twice is the common case: one entry, not two."""
    assert _setup(box, KEY).returncode == 0
    again = _setup(box, KEY)
    assert again.returncode == 0, again.stdout + again.stderr
    assert json.loads(again.stdout) == {"status": "ready", "sshd_port": SSHD_PORT}
    assert _authorized(box) == [KEY]


def test_setup_adds_a_second_machine_without_moving_the_sshd_port(box):
    """The tunnel is pointed at that port, so authorizing another machine must leave it alone."""
    assert _setup(box, KEY).returncode == 0
    result = _setup(box, OTHER_KEY)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"status": "ready", "sshd_port": SSHD_PORT}
    assert _authorized(box) == [KEY, OTHER_KEY]
    assert (box / "agent/data/daemons/ssh-tunnel.sshd-port").read_text() == str(SSHD_PORT)


def test_setup_without_a_key_on_a_box_that_has_none_answers_with_an_envelope(box):
    result = _setup(box)
    assert result.returncode == 1
    assert json.loads(result.stderr)["error"]
    assert not (box / ".ssh").exists()


def test_setup_without_a_key_brings_sshd_back_for_an_authorized_machine(box):
    """A restart takes sshd with it and leaves the keys, so the machine that was already
    authorized gets back in without pasting its key again."""
    assert _setup(box, KEY).returncode == 0
    result = _setup(box)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"status": "ready", "sshd_port": SSHD_PORT}
    assert _authorized(box) == [KEY]
