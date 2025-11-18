import asyncio
import json
import logging
import pathlib as pl
import subprocess
import time

from .models import VestaSettings

logger = logging.getLogger(__name__)

_mount_process: subprocess.Popen | None = None


def check_rclone_installed() -> bool:
    try:
        result = subprocess.run(
            ["rclone", "version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def check_fusermount_installed() -> bool:
    try:
        result = subprocess.run(
            ["fusermount3", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def setup_rclone_config(config: VestaSettings, *, config_path: pl.Path) -> None:
    if not config.onedrive_token:
        raise ValueError("ONEDRIVE_TOKEN environment variable is required")

    try:
        json.loads(config.onedrive_token)
    except json.JSONDecodeError as e:
        raise ValueError(f"ONEDRIVE_TOKEN must be valid JSON: {e}")

    rclone_config = f"""[{config.onedrive_remote_name}]
type = onedrive
"""

    if config.onedrive_client_id and config.onedrive_client_secret:
        rclone_config += f"""client_id = {config.onedrive_client_id}
client_secret = {config.onedrive_client_secret}
"""

    rclone_config += f"""token = {config.onedrive_token}
"""

    if config.onedrive_drive_id:
        rclone_config += f"""drive_id = {config.onedrive_drive_id}
"""

    rclone_config += """drive_type = personal
"""

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(rclone_config)
    logger.info(f"Created rclone config at {config_path}")


async def mount_onedrive(
    config: VestaSettings,
    mount_dir: pl.Path,
    config_path: pl.Path,
    *,
    timeout: int = 30,
) -> subprocess.Popen:
    global _mount_process

    if not check_fusermount_installed():
        raise RuntimeError(
            "fusermount3 is not installed. OneDrive mounting requires FUSE support.\n"
            "Install it with: sudo pacman -S fuse3  (Arch/Endeavour)\n"
            "               or: sudo apt install fuse3  (Debian/Ubuntu)\n"
            "               or: sudo dnf install fuse3  (Fedora/RHEL)"
        )

    mount_dir.mkdir(parents=True, exist_ok=True)

    remote_path = f"{config.onedrive_remote_name}:{config.onedrive_remote_path}"
    cmd = [
        "rclone",
        "mount",
        remote_path,
        str(mount_dir),
        "--config",
        str(config_path),
        "--vfs-cache-mode",
        "writes",
        "--daemon",
    ]

    logger.info(f"Mounting OneDrive at {mount_dir}")

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _mount_process = process

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                list(mount_dir.iterdir())
                with open("/proc/mounts") as f:
                    if str(mount_dir) in f.read():
                        logger.info(f"OneDrive successfully mounted at {mount_dir}")
                        return process
            except (OSError, PermissionError, FileNotFoundError):
                await asyncio.sleep(0.5)

        raise RuntimeError(
            f"OneDrive mount failed after {timeout}s. Check: ps aux | grep rclone\n"
            f"If you see '<defunct>' processes, fusermount3 may be missing or crashed."
        )

    except Exception as e:
        if _mount_process:
            _mount_process.terminate()
            _mount_process = None
        raise RuntimeError(f"Failed to mount OneDrive: {e}") from e


def unmount_onedrive(mount_dir: pl.Path, *, timeout: int = 10) -> None:
    global _mount_process

    logger.info(f"Unmounting OneDrive from {mount_dir}")

    try:
        result = subprocess.run(
            ["fusermount", "-u", str(mount_dir)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            logger.warning(f"fusermount returned {result.returncode}: {result.stderr}")
            subprocess.run(
                ["umount", str(mount_dir)],
                capture_output=True,
                timeout=timeout,
            )

    except (subprocess.SubprocessError, FileNotFoundError) as e:
        logger.error(f"Failed to unmount OneDrive: {e}")

    if _mount_process:
        try:
            _mount_process.terminate()
            _mount_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _mount_process.kill()
        finally:
            _mount_process = None

    logger.info("OneDrive unmounted")
