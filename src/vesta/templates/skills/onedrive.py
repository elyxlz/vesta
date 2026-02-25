"""OneDrive skill template."""

SKILL_MD = """\
---
name: onedrive
description: This skill should be used when the user asks about "OneDrive", "cloud files", "sync files", "mount drive", or needs to access, mount, or manage OneDrive cloud storage.
---

# OneDrive

You can mount and access OneDrive files via rclone. Use the setup script to configure and manage the mount.

## Prerequisites

Install rclone and FUSE:
```bash
curl https://rclone.org/install.sh | bash
apt-get install -y fuse3
```

- Environment variable `ONEDRIVE_TOKEN` set (rclone OAuth token JSON)

## Setup Script

The setup script is at `scripts/onedrive_setup.py`. Run it with Python:

```bash
python scripts/onedrive_setup.py setup    # Write rclone.conf
python scripts/onedrive_setup.py mount    # Mount OneDrive as FUSE filesystem
python scripts/onedrive_setup.py unmount  # Unmount
python scripts/onedrive_setup.py status   # Check mount status
```

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ONEDRIVE_TOKEN` | Yes | — | rclone OAuth token JSON |
| `ONEDRIVE_CLIENT_ID` | No | — | Azure app client ID |
| `ONEDRIVE_CLIENT_SECRET` | No | — | Azure app client secret |
| `ONEDRIVE_DRIVE_ID` | No | — | Specific drive ID |
| `ONEDRIVE_REMOTE_NAME` | No | `onedrive` | rclone remote name |
| `ONEDRIVE_REMOTE_PATH` | No | `/` | Remote path to mount |
| `ONEDRIVE_MOUNT_DIR` | No | `~/onedrive` | Local mount point |
| `ONEDRIVE_DATA_DIR` | No | `~/data` | Where rclone.conf is stored |
| `ONEDRIVE_LOGS_DIR` | No | `~/logs` | Where mount logs go |

## Mounted Files

Once mounted, OneDrive files are available at the mount directory (default `~/onedrive`).

## Best Practices

- Run `status` before accessing files to verify the mount is active
- Run `setup` then `mount` on first use or after token refresh
- The mount runs as a background daemon — it survives shell exits
- Use `unmount` before shutting down to clean up

### File Organization
[How the user organizes their OneDrive files]
"""

SCRIPTS = {
    "onedrive_setup.py": """\
#!/usr/bin/env python3
\"\"\"OneDrive setup, mount, unmount, and status via rclone.\"\"\"

import json
import os
import pathlib as pl
import subprocess
import sys


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        print(f"Error: {name} environment variable is required", file=sys.stderr)
        sys.exit(1)
    return val


def _paths() -> tuple[pl.Path, pl.Path, pl.Path]:
    data_dir = pl.Path(_env("ONEDRIVE_DATA_DIR", str(pl.Path.home() / "data")))
    mount_dir = pl.Path(_env("ONEDRIVE_MOUNT_DIR", str(pl.Path.home() / "onedrive")))
    logs_dir = pl.Path(_env("ONEDRIVE_LOGS_DIR", str(pl.Path.home() / "logs")))
    return data_dir, mount_dir, logs_dir


def setup() -> None:
    \"\"\"Write rclone.conf from environment variables.\"\"\"
    token = _require_env("ONEDRIVE_TOKEN")
    try:
        json.loads(token)
    except json.JSONDecodeError as e:
        print(f"Error: ONEDRIVE_TOKEN must be valid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    remote_name = _env("ONEDRIVE_REMOTE_NAME", "onedrive")
    client_id = _env("ONEDRIVE_CLIENT_ID")
    client_secret = _env("ONEDRIVE_CLIENT_SECRET")
    drive_id = _env("ONEDRIVE_DRIVE_ID")

    data_dir, _, _ = _paths()
    config_path = data_dir / "rclone.conf"
    data_dir.mkdir(parents=True, exist_ok=True)

    lines = [f"[{remote_name}]", "type = onedrive"]
    if client_id and client_secret:
        lines += [f"client_id = {client_id}", f"client_secret = {client_secret}"]
    lines += [f"token = {token}"]
    if drive_id:
        lines.append(f"drive_id = {drive_id}")
    lines.append("drive_type = personal")

    config_path.write_text("\\n".join(lines) + "\\n")
    config_path.chmod(0o600)
    print(f"Wrote rclone config to {config_path}")


def mount() -> None:
    \"\"\"Mount OneDrive via rclone as a background daemon.\"\"\"
    data_dir, mount_dir, logs_dir = _paths()
    config_path = data_dir / "rclone.conf"
    remote_name = _env("ONEDRIVE_REMOTE_NAME", "onedrive")
    remote_path = _env("ONEDRIVE_REMOTE_PATH", "/")

    if not config_path.exists():
        print("Error: rclone.conf not found. Run 'setup' first.", file=sys.stderr)
        sys.exit(1)

    # Unmount if already mounted
    _unmount_if_mounted(mount_dir)
    subprocess.run(["rm", "-rf", str(mount_dir)], capture_output=True)
    mount_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    remote = f"{remote_name}:{remote_path}"

    cmd = [
        "rclone", "mount", remote, str(mount_dir),
        "--config", str(config_path),
        "--daemon",
        "--vfs-cache-mode", "full",
        "--vfs-cache-max-age", "24h",
        "--vfs-cache-max-size", "2G",
        "--buffer-size", "128M",
        "--vfs-read-ahead", "1G",
        "--onedrive-chunk-size", "120M",
        "--dir-cache-time", "5m",
        "--poll-interval", "30s",
        "--vfs-write-back", "5s",
        "--transfers", "4",
        "--fast-list",
        "--log-file", str(logs_dir / "onedrive-mount.log"),
        "--log-level", "INFO",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: rclone mount failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    print(f"OneDrive mounted at {mount_dir}")


def _unmount_if_mounted(mount_dir: pl.Path) -> None:
    if not _is_mounted(mount_dir):
        return
    for cmd in [
        ["fusermount", "-uz", str(mount_dir)],
        ["fusermount", "-u", str(mount_dir)],
        ["umount", str(mount_dir)],
    ]:
        try:
            if subprocess.run(cmd, capture_output=True, timeout=10).returncode == 0:
                return
        except (subprocess.SubprocessError, FileNotFoundError):
            continue


def _is_mounted(mount_dir: pl.Path) -> bool:
    try:
        with open("/proc/mounts") as f:
            return str(mount_dir) in f.read()
    except FileNotFoundError:
        return mount_dir.is_mount()


def unmount() -> None:
    \"\"\"Unmount OneDrive.\"\"\"
    _, mount_dir, _ = _paths()
    if not _is_mounted(mount_dir):
        print("OneDrive is not mounted")
        return
    _unmount_if_mounted(mount_dir)
    if mount_dir.exists():
        try:
            mount_dir.rmdir()
        except OSError:
            pass
    print("OneDrive unmounted")


def status() -> None:
    \"\"\"Check mount status.\"\"\"
    _, mount_dir, _ = _paths()
    if _is_mounted(mount_dir):
        try:
            items = list(mount_dir.iterdir())
            print(f"OneDrive is mounted at {mount_dir} ({len(items)} items)")
        except OSError as e:
            print(f"OneDrive mount at {mount_dir} exists but is not accessible: {e}")
    else:
        print(f"OneDrive is not mounted (expected at {mount_dir})")


if __name__ == "__main__":
    commands = {"setup": setup, "mount": mount, "unmount": unmount, "status": status}
    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print(f"Usage: {sys.argv[0]} {{{','.join(commands)}}}")
        sys.exit(1)
    commands[sys.argv[1]]()
""",
}
