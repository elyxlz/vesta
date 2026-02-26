"""Vesta management CLI — runs on the host to manage the Docker container."""

import os
import subprocess
import sys

CONTAINER = "vesta"
IMAGE = "vesta"
INSTALL_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CREATE_ARGS = ["docker", "create", "--name", CONTAINER, "-it", "--restart", "unless-stopped", "--device", "/dev/fuse", "-p", "7865:7865", IMAGE]


def _ps(flags: str = "") -> str:
    result = subprocess.run(["docker", "ps", flags, "-q", "-f", f"name={CONTAINER}"], capture_output=True, text=True)
    return result.stdout.strip()


def cmd_setup() -> None:
    """First-time setup: build image, create container, authenticate, start."""
    if _ps("-a"):
        confirm = input("Existing container will be removed (all state lost). Continue? [y/N] ").strip().lower()
        if confirm != "y":
            print("Aborted. Use 'vesta backup' first to snapshot state.")
            return
    subprocess.run(["docker", "build", "-t", IMAGE, INSTALL_ROOT], check=True)
    subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True)
    subprocess.run(CREATE_ARGS, check=True)
    subprocess.run(["docker", "start", CONTAINER], check=True)
    print("Authenticating Claude (copy the URL and open in your browser)...")
    subprocess.run(["docker", "exec", "-it", CONTAINER, "claude"], check=True)
    subprocess.run(["docker", "restart", CONTAINER], check=True)
    print("Attaching to Vesta (detach: ctrl-q)...")
    os.execvp("docker", ["docker", "attach", "--detach-keys=ctrl-q", CONTAINER])


def cmd_rebuild() -> None:
    """Rebuild image and recreate container, preserving auth credentials."""
    if not _ps("-a"):
        print("No container found. Run: vesta setup")
        sys.exit(1)
    if _ps():
        subprocess.run(["docker", "stop", "-t", "300", CONTAINER], check=True)
    r = subprocess.run(["docker", "cp", f"{CONTAINER}:/root/.claude", "/tmp/.claude-vesta"], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"Warning: failed to copy auth credentials: {r.stderr.strip()}", file=sys.stderr)
    subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True)
    subprocess.run(["docker", "build", "-t", IMAGE, INSTALL_ROOT], check=True)
    subprocess.run(CREATE_ARGS, check=True)
    subprocess.run(["rm", "-rf", "/tmp/.claude-vesta/backups", "/tmp/.claude-vesta/.claude.json"], capture_output=True)
    r = subprocess.run(["docker", "cp", "/tmp/.claude-vesta", f"{CONTAINER}:/root/.claude"], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"Warning: failed to restore auth credentials: {r.stderr.strip()}", file=sys.stderr)
    subprocess.run(["rm", "-rf", "/tmp/.claude-vesta"], capture_output=True)
    subprocess.run(["docker", "start", CONTAINER], check=True)
    print("Rebuilt. Auth preserved. Attaching (detach: ctrl-q)...")
    os.execvp("docker", ["docker", "attach", "--detach-keys=ctrl-q", CONTAINER])


def cmd_start() -> None:
    """Start a stopped container."""
    if _ps():
        print("Vesta is already running")
    elif _ps("-a"):
        subprocess.run(["docker", "start", CONTAINER], check=True)
    else:
        print("Container not found. Run: vesta setup")
        sys.exit(1)


def cmd_stop() -> None:
    """Stop the running container."""
    subprocess.run(["docker", "stop", "-t", "300", CONTAINER], check=True)


def cmd_attach() -> None:
    """Show recent logs then attach to Vesta's console (detach: ctrl-q)."""
    subprocess.run(["docker", "logs", "--tail", "50", CONTAINER])
    os.execvp("docker", ["docker", "attach", "--detach-keys=ctrl-q", CONTAINER])


def cmd_logs() -> None:
    """Tail container logs."""
    os.execvp("docker", ["docker", "logs", "-f", CONTAINER])


def cmd_backup() -> None:
    """Snapshot the container as a Docker image."""
    from datetime import datetime

    tag = f"vesta-backup:{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    subprocess.run(["docker", "commit", CONTAINER, tag], check=True)
    print(f"Backup created: {tag}")


def cmd_shell() -> None:
    """Open a bash shell inside the container."""
    os.execvp("docker", ["docker", "exec", "-it", CONTAINER, "bash"])


def cmd_status() -> None:
    """Show container status."""
    subprocess.run(["docker", "ps", "-a", "-f", f"name={CONTAINER}", "--format", "table {{.Names}}\t{{.Status}}\t{{.Image}}"], check=True)


def cmd_destroy() -> None:
    """Remove the container permanently."""
    confirm = input("Destroy container (all state lost)? [y/N] ").strip().lower()
    if confirm == "y":
        subprocess.run(["docker", "rm", "-f", CONTAINER], check=True)


COMMANDS = {
    "setup": cmd_setup,
    "rebuild": cmd_rebuild,
    "start": cmd_start,
    "stop": cmd_stop,
    "attach": cmd_attach,
    "logs": cmd_logs,
    "backup": cmd_backup,
    "shell": cmd_shell,
    "status": cmd_status,
    "destroy": cmd_destroy,
}


def main() -> None:
    if os.path.exists("/.dockerenv"):
        print("Error: 'vesta' CLI manages Docker from the host. Use 'python -m vesta.main' to run the agent directly.", file=sys.stderr)
        sys.exit(1)

    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: vesta {{{'|'.join(COMMANDS)}}}")
        sys.exit(1)

    COMMANDS[sys.argv[1]]()
