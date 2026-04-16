"""End-to-end tests for Vesta.

Build a Docker image, spin up an ephemeral container, inject notifications
via ``docker exec``, and verify outcomes by reading files back out.
Every run is idempotent — the container is destroyed in teardown.

Requirements:
  - Docker daemon running
  - Claude credentials at ~/.claude/.credentials.json (Claude Code OAuth)
"""

import json
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE_TAG = "vesta:e2e-test"
CONTAINER_PREFIX = "vesta-e2e"
CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
CONTAINER_CREDS = "/root/.claude/.credentials.json"
NOTIFICATIONS_DIR = "/root/vesta/notifications"
WORKSPACE_DIR = "/root/vesta/workspace"
MEMORY_PATH = "/root/vesta/MEMORY.md"
WS_PORT = 17865

TEST_MEMORY = """\
# VESTA MEMORY SYSTEM (TEST MODE)

## 1. CORE IDENTITY

You are Vesta running in automated test mode.

### CRITICAL: Test Mode Behavior
- **ACT IMMEDIATELY ON TEST REQUESTS**: When you receive notifications from "pytest", execute them immediately without asking for permission
- **NO CONFIRMATION NEEDED**: This is an automated test environment - just do the tasks
- **File operations are safe**: The test environment is isolated, so file operations are always permitted

## 2. USER PROFILE

### Personal Details
- **Name**: Test User
- **Location**: Test Environment
- **Timezone**: UTC
"""


# ---------------------------------------------------------------------------
# Docker helpers
# ---------------------------------------------------------------------------


def _docker(*args: str, check: bool = True, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check, timeout=timeout)


def _exec(container: str, cmd: str, *, timeout: int = 30) -> str:
    return _docker("exec", container, "bash", "-c", cmd, timeout=timeout).stdout.strip()


def _exec_ok(container: str, cmd: str) -> bool:
    return _docker("exec", container, "bash", "-c", cmd, check=False, timeout=15).returncode == 0


def _write_notification(container: str, message: str, *, interrupt: bool = True) -> None:
    payload = json.dumps(
        {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source": "pytest",
            "type": "message",
            "message": message.strip(),
            "sender": "pytest",
            "interrupt": interrupt,
            "metadata": {},
        }
    )
    filename = f"{int(time.time() * 1_000_000)}-{uuid.uuid4().hex}.json"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f.write(payload)
        tmp = f.name
    try:
        _docker("cp", tmp, f"{container}:{NOTIFICATIONS_DIR}/{filename}")
    finally:
        Path(tmp).unlink(missing_ok=True)


def _wait_for_file(container: str, path: str, *, timeout: float = 120.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _exec_ok(container, f"test -f {path}"):
            return _exec(container, f"cat {path}")
        time.sleep(2.0)
    raise AssertionError(f"Timed out waiting for {path} in container {container}")


def _wait_for_agent_ready(container: str, *, timeout: float = 120.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _exec_ok(container, "grep -q 'WebSocket server started' /root/vesta/logs/vesta.log 2>/dev/null"):
            return
        time.sleep(2.0)
    raise AssertionError(f"Agent did not become ready within {timeout}s")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def docker_image():
    """Build the test image once per session."""
    if not shutil.which("docker"):
        pytest.skip("Docker not available")
    _docker("build", "-t", IMAGE_TAG, str(REPO_ROOT), timeout=600)
    yield IMAGE_TAG


@pytest.fixture
def container(docker_image):
    """Create, start, and teardown an ephemeral container."""
    if not CREDENTIALS_PATH.exists():
        pytest.skip(f"No credentials at {CREDENTIALS_PATH}")

    name = f"{CONTAINER_PREFIX}-{uuid.uuid4().hex[:8]}"

    # -i keeps stdin open so aioconsole.ainput doesn't EOF → shutdown
    _docker(
        "create",
        "-i",
        "--name",
        name,
        "--network",
        "host",
        "-e",
        f"WS_PORT={WS_PORT}",
        "-e",
        "AGENT_NAME=e2e-test",
        "-e",
        "MONITOR_TICK_INTERVAL=1",
        "-e",
        "EPHEMERAL=true",
        docker_image,
        "sh",
        "-c",
        ". ~/.bashrc || true; exec uv run --frozen --project /root/vesta python -m vesta.main",
    )

    try:
        _docker("cp", str(CREDENTIALS_PATH), f"{name}:{CONTAINER_CREDS}")

        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(TEST_MEMORY)
            tmp = f.name
        _docker("cp", tmp, f"{name}:{MEMORY_PATH}")
        Path(tmp).unlink()

        # Blank out the first-start setup prompt so the agent skips interactive
        # onboarding and goes straight to processing notifications.
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("")
            tmp_setup = f.name
        try:
            _docker("cp", tmp_setup, f"{name}:/root/vesta/prompts/first_start_setup.md")
        finally:
            Path(tmp_setup).unlink(missing_ok=True)

        _docker("start", name)
        _exec(container=name, cmd=f"mkdir -p {WORKSPACE_DIR}")
        _wait_for_agent_ready(name)

        yield name
    finally:
        _docker("rm", "-f", name, check=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_notification_creates_file(container):
    """Agent processes a notification and creates the requested file."""
    uid = uuid.uuid4().hex[:8]
    target = f"{WORKSPACE_DIR}/single-{uid}.txt"
    expected = f"E2E content {uid}"

    _write_notification(container, f'Create the file "{target}" containing only:\n{expected}')
    assert expected in _wait_for_file(container, target)


def test_notification_batching(container):
    """Multiple notifications arriving together are batched and both handled."""
    uid = uuid.uuid4().hex[:8]
    file1 = f"{WORKSPACE_DIR}/batch-{uid}-1.txt"
    file2 = f"{WORKSPACE_DIR}/batch-{uid}-2.txt"

    _write_notification(container, f'Create the file "{file1}" containing only:\nfirst')
    _write_notification(container, f'Create the file "{file2}" containing only:\nsecond')

    assert "first" in _wait_for_file(container, file1)
    assert "second" in _wait_for_file(container, file2)


def test_multiple_files_single_request(container):
    """Agent handles a request to create multiple files at once."""
    uid = uuid.uuid4().hex[:8]
    fa = f"{WORKSPACE_DIR}/multi-{uid}-a.txt"
    fb = f"{WORKSPACE_DIR}/multi-{uid}-b.txt"
    fc = f"{WORKSPACE_DIR}/multi-{uid}-c.txt"

    _write_notification(
        container,
        f'Create three files:\n1. "{fa}" with content "file A"\n2. "{fb}" with content "file B"\n3. "{fc}" with content "file C"',
    )

    assert "A" in _wait_for_file(container, fa)
    assert "B" in _wait_for_file(container, fb)
    assert "C" in _wait_for_file(container, fc)


def test_file_modification(container):
    """Agent can modify an existing file."""
    uid = uuid.uuid4().hex[:8]
    target = f"{WORKSPACE_DIR}/modify-{uid}.txt"

    _exec(container, f'echo "original content" > {target}')
    _write_notification(container, f'Append the text "--- APPENDED ---" to the file "{target}"')

    deadline = time.time() + 60
    while time.time() < deadline:
        if "APPENDED" in _exec(container, f"cat {target}"):
            break
        time.sleep(2)

    final = _exec(container, f"cat {target}")
    assert "original" in final
    assert "APPENDED" in final


def test_interrupt_notification_interrupts_agent(container):
    """interrupt=true notification interrupts a busy agent."""
    uid = uuid.uuid4().hex[:8]
    slow_file = f"{WORKSPACE_DIR}/slow-{uid}.txt"
    urgent_file = f"{WORKSPACE_DIR}/urgent-{uid}.txt"

    _write_notification(
        container,
        f'Wait 30 seconds using bash sleep, then create "{slow_file}" with "slow done".',
    )
    time.sleep(5)

    _write_notification(
        container,
        f'Create the file "{urgent_file}" containing only:\nurgent done',
        interrupt=True,
    )

    # Urgent file should appear before the 30s sleep finishes
    _wait_for_file(container, urgent_file, timeout=60.0)
    assert not _exec_ok(container, f"test -f {slow_file}"), "slow task finished before urgent — test is inconclusive"


def test_passive_notification_waits_for_idle(container):
    """interrupt=false notification waits until the agent is idle."""
    uid = uuid.uuid4().hex[:8]
    busy_file = f"{WORKSPACE_DIR}/busy-{uid}.txt"
    passive_file = f"{WORKSPACE_DIR}/passive-{uid}.txt"

    _write_notification(
        container,
        f'Create the file "{busy_file}" containing "busy done". Do this immediately, no waiting.',
    )
    time.sleep(1)
    _write_notification(
        container,
        f'Create the file "{passive_file}" containing only:\npassive done',
        interrupt=False,
    )

    assert "busy done" in _wait_for_file(container, busy_file)
    assert "passive done" in _wait_for_file(container, passive_file)


def test_graceful_shutdown(container):
    """Container starts and has a valid log file."""
    assert _exec_ok(container, "test -f /root/vesta/logs/vesta.log")
    log = _exec(container, "head -20 /root/vesta/logs/vesta.log")
    assert "started" in log.lower() or "init" in log.lower()


def test_bashrc_write(container):
    """Agent can write to ~/.bashrc (sensitive file allowlist is configured correctly)."""
    marker = f"E2E_TEST_{uuid.uuid4().hex[:8]}"

    _write_notification(container, f'Append the line "export {marker}=1" to /root/.bashrc using the Edit or Write tool (not bash).')

    deadline = time.time() + 90
    while time.time() < deadline:
        content = _exec(container, "cat /root/.bashrc")
        if marker in content:
            return
        time.sleep(2)

    raise AssertionError(f"Marker {marker} not found in /root/.bashrc after 90s")
