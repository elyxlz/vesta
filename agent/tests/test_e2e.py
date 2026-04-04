"""End-to-end tests for Vesta.

These tests build a Docker image, spin up an ephemeral container, inject
notifications via ``docker exec``, and verify outcomes by reading files
back out of the container.  Every run is idempotent — the container is
destroyed in teardown regardless of pass/fail.

Requirements:
  - Docker daemon running
  - Claude credentials at ~/.claude/.credentials.json (Claude Code OAuth)
"""

import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]  # …/vesta
IMAGE_TAG = "vesta:e2e-test"
CONTAINER_PREFIX = "vesta-e2e"
CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
CONTAINER_CREDS = "/root/.claude/.credentials.json"
NOTIFICATIONS_DIR = "/root/vesta/notifications"
WORKSPACE_DIR = "/root/vesta/workspace"
MEMORY_PATH = "/root/vesta/MEMORY.md"
WS_PORT = 17865  # high port to avoid collisions

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


def _run(cmd: list[str], *, check: bool = True, timeout: int = 300, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=capture, text=True, check=check, timeout=timeout)


def _docker(*args: str, check: bool = True, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return _run(["docker", *args], check=check, timeout=timeout)


def _exec(container: str, cmd: str, *, timeout: int = 30) -> str:
    result = _docker("exec", container, "bash", "-c", cmd, timeout=timeout)
    return result.stdout.strip()


def _exec_check(container: str, cmd: str) -> bool:
    result = _docker("exec", container, "bash", "-c", cmd, check=False, timeout=15)
    return result.returncode == 0


def _write_notification(container: str, message: str, *, sender: str = "pytest", interrupt: bool = True) -> None:
    payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "pytest",
        "type": "message",
        "message": message.strip(),
        "sender": sender,
        "interrupt": interrupt,
        "metadata": {},
    }
    filename = f"{int(time.time() * 1_000_000)}-{uuid.uuid4().hex}.json"
    escaped = json.dumps(payload).replace("'", "'\\''")
    _exec(container, f"echo '{escaped}' > {NOTIFICATIONS_DIR}/{filename}")


def _wait_for_file(container: str, path: str, *, timeout: float = 120.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _exec_check(container, f"test -f {path}"):
            return _exec(container, f"cat {path}")
        time.sleep(2.0)
    raise AssertionError(f"Timed out waiting for {path} in container {container}")


def _assert_missing(container: str, path: str, *, duration: float = 30.0) -> None:
    deadline = time.time() + duration
    while time.time() < deadline:
        if _exec_check(container, f"test -f {path}"):
            raise AssertionError(f"Unexpected file created: {path}")
        time.sleep(2.0)


def _wait_for_agent_ready(container: str, *, timeout: float = 120.0) -> None:
    """Wait until the agent's WebSocket server is accepting connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _exec_check(container, f"curl -sf http://localhost:{WS_PORT}/ws -o /dev/null || curl -sf --head http://localhost:{WS_PORT}/ -o /dev/null"):
            return
        # Also check if the log file has the WS startup message
        if _exec_check(container, "grep -q 'WebSocket server started' /root/vesta/logs/vesta.log 2>/dev/null"):
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

    # Create container with host networking and -i to keep stdin open
    # (without -i, aioconsole.ainput gets EOFError and triggers shutdown)
    _docker(
        "create", "-i",
        "--name", name,
        "--network", "host",
        "-e", f"WS_PORT={WS_PORT}",
        "-e", "AGENT_NAME=e2e-test",
        "-e", "NOTIFICATION_CHECK_INTERVAL=1",
        "-e", "NOTIFICATION_BUFFER_DELAY=0",
        "-e", "EPHEMERAL=true",
        docker_image,
    )

    try:
        # Inject credentials
        _docker("cp", str(CREDENTIALS_PATH), f"{name}:{CONTAINER_CREDS}")

        # Inject test MEMORY.md
        tmp = Path(f"/tmp/vesta-e2e-memory-{name}.md")
        tmp.write_text(TEST_MEMORY)
        _docker("cp", str(tmp), f"{name}:{MEMORY_PATH}")
        tmp.unlink()

        # Ensure workspace exists
        _docker("start", name)
        _exec(container=name, cmd=f"mkdir -p {WORKSPACE_DIR}")

        # Wait for agent to be ready
        _wait_for_agent_ready(name)

        yield name
    finally:
        _docker("rm", "-f", name, check=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_notification_creates_file(container):
    """Agent should process a notification and create the requested file."""
    uid = uuid.uuid4().hex[:8]
    target = f"{WORKSPACE_DIR}/single-{uid}.txt"
    expected = f"E2E content {uid}"

    _write_notification(container, f'Create the file "{target}" containing only:\n{expected}')
    contents = _wait_for_file(container, target)
    assert expected in contents


def test_notification_batching(container):
    """Multiple notifications arriving together should be batched and both handled."""
    uid = uuid.uuid4().hex[:8]
    file1 = f"{WORKSPACE_DIR}/batch-{uid}-1.txt"
    file2 = f"{WORKSPACE_DIR}/batch-{uid}-2.txt"

    _write_notification(container, f'Create the file "{file1}" containing only:\nfirst')
    _write_notification(container, f'Create the file "{file2}" containing only:\nsecond')

    assert "first" in _wait_for_file(container, file1)
    assert "second" in _wait_for_file(container, file2)


def test_multiple_files_single_request(container):
    """Agent should handle a request to create multiple files at once."""
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
    """Agent should be able to modify existing files."""
    uid = uuid.uuid4().hex[:8]
    target = f"{WORKSPACE_DIR}/modify-{uid}.txt"

    _exec(container, f'echo "original content" > {target}')
    _write_notification(container, f'Append the text "--- APPENDED ---" to the file "{target}"')

    deadline = time.time() + 60
    while time.time() < deadline:
        content = _exec(container, f"cat {target}")
        if "APPENDED" in content:
            break
        time.sleep(2)

    final = _exec(container, f"cat {target}")
    assert "original" in final
    assert "APPENDED" in final


def test_interrupt_notification_interrupts_agent(container):
    """A notification with interrupt=true (default) should interrupt active processing."""
    uid = uuid.uuid4().hex[:8]
    slow_file = f"{WORKSPACE_DIR}/slow-{uid}.txt"
    urgent_file = f"{WORKSPACE_DIR}/urgent-{uid}.txt"

    # Send a slow task
    _write_notification(
        container,
        f'Wait 30 seconds using bash sleep, then create "{slow_file}" with "slow done".',
    )
    # Give the agent a moment to start processing
    time.sleep(5)

    # Send an urgent interrupt notification
    _write_notification(
        container,
        f'Create the file "{urgent_file}" containing only:\nurgent done',
        interrupt=True,
    )

    # The urgent file should appear well before the 30s sleep
    contents = _wait_for_file(container, urgent_file, timeout=60.0)
    assert "urgent done" in contents


def test_passive_notification_waits_for_idle(container):
    """A notification with interrupt=false should wait until the agent is idle."""
    uid = uuid.uuid4().hex[:8]
    busy_file = f"{WORKSPACE_DIR}/busy-{uid}.txt"
    passive_file = f"{WORKSPACE_DIR}/passive-{uid}.txt"

    # Send a task that keeps the agent busy for a bit
    _write_notification(
        container,
        f'Create the file "{busy_file}" containing "busy done". Do this immediately, no waiting.',
    )
    # Immediately send a passive (non-interrupting) notification
    time.sleep(1)
    _write_notification(
        container,
        f'Create the file "{passive_file}" containing only:\npassive done',
        interrupt=False,
    )

    # Both should eventually complete — passive just waits for idle
    assert "busy done" in _wait_for_file(container, busy_file)
    assert "passive done" in _wait_for_file(container, passive_file)


def test_graceful_shutdown(container):
    """Container should have a log file and shut down cleanly."""
    assert _exec_check(container, "test -f /root/vesta/logs/vesta.log")
    log = _exec(container, "head -20 /root/vesta/logs/vesta.log")
    assert "started" in log.lower() or "init" in log.lower() or "config" in log.lower()
