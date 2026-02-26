"""OneDrive skill template."""

from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent / "scripts"

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

The setup script is at `memory/skills/onedrive/scripts/onedrive_setup.py`. Run it with Python:

```bash
uv run memory/skills/onedrive/scripts/onedrive_setup.py setup    # Write rclone.conf
uv run memory/skills/onedrive/scripts/onedrive_setup.py mount    # Mount OneDrive as FUSE filesystem
uv run memory/skills/onedrive/scripts/onedrive_setup.py unmount  # Unmount
uv run memory/skills/onedrive/scripts/onedrive_setup.py status   # Check mount status
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
    "onedrive_setup.py": (_SCRIPTS_DIR / "onedrive_setup.py").read_text(),
}
