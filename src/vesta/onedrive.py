import asyncio
import json
import logging
import os
import pathlib as pl
import subprocess
import time

from .config import VestaSettings

logger = logging.getLogger(__name__)
_mount_process: subprocess.Popen | None = None


def check_rclone_installed() -> bool:
    try:
        return subprocess.run(["rclone", "version"], capture_output=True, text=True, timeout=5).returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def check_fusermount_installed() -> bool:
    try:
        return subprocess.run(["fusermount3", "--version"], capture_output=True, text=True, timeout=5).returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def setup_rclone_config(config: VestaSettings, *, config_path: pl.Path) -> None:
    token = config.onedrive_token.get_secret_value() if config.onedrive_token else None
    if not token:
        raise ValueError("ONEDRIVE_TOKEN is required for OneDrive sync")

    try:
        json.loads(token)
    except json.JSONDecodeError as e:
        raise ValueError(f"ONEDRIVE_TOKEN must be valid JSON: {e}")

    rclone_config = f"""[{config.onedrive_remote_name}]
type = onedrive
"""

    client_id = config.onedrive_client_id.get_secret_value() if config.onedrive_client_id else None
    client_secret = config.onedrive_client_secret.get_secret_value() if config.onedrive_client_secret else None
    if client_id and client_secret:
        rclone_config += f"""client_id = {client_id}
client_secret = {client_secret}
"""

    rclone_config += f"""token = {token}
"""

    if config.onedrive_drive_id:
        rclone_config += f"""drive_id = {config.onedrive_drive_id}
"""

    rclone_config += """drive_type = personal
"""

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(rclone_config)
    os.chmod(config_path, 0o600)
    logger.info(f"Created rclone config at {config_path} with secure permissions (0600)")
    logger.warning(f"OneDrive credentials stored in {config_path} - keep this file secure")


async def mount_onedrive(config: VestaSettings, *, mount_dir: pl.Path, config_path: pl.Path, timeout: int = 30) -> subprocess.Popen:
    global _mount_process

    if not check_fusermount_installed():
        raise RuntimeError("fusermount3 is required for OneDrive mounts")

    unmount_onedrive(mount_dir)
    subprocess.run(["rm", "-rf", str(mount_dir)], capture_output=True)
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
        "full",
        "--vfs-cache-max-age",
        "24h",
        "--vfs-cache-max-size",
        "2G",
        "--buffer-size",
        "128M",
        "--vfs-read-ahead",
        "1G",
        "--onedrive-chunk-size",
        "120M",
        "--dir-cache-time",
        "5m",
        "--poll-interval",
        "30s",
        "--vfs-write-back",
        "5s",
        "--transfers",
        "4",
        "--fast-list",
        "--log-file",
        str(config.logs_dir / "onedrive-mount.log"),
        "--log-level",
        "INFO",
    ]

    # Test if we can list files before mounting
    test_result = subprocess.run(
        ["rclone", "lsf", remote_path, "--config", str(config_path), "--max-depth", "1"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if test_result.returncode != 0:
        raise RuntimeError(f"Cannot list OneDrive files: {test_result.stderr[:200]}")

    file_count = len([line for line in test_result.stdout.strip().split("\n") if line])
    if file_count == 0:
        raise RuntimeError(f"OneDrive at {remote_path} is empty - check drive_id/remote_path configuration")

    logger.info(f"Verified {file_count} items in OneDrive, mounting at {mount_dir}")

    process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _mount_process = process

    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            contents = list(mount_dir.iterdir())
            with open("/proc/mounts") as f:
                if str(mount_dir) in f.read() and contents:
                    logger.info(f"OneDrive mounted at {mount_dir} with {len(contents)} items")
                    return process
        except (OSError, PermissionError, FileNotFoundError):
            pass
        await asyncio.sleep(0.5)

    if process.poll() is not None:
        logger.error(f"rclone mount exited with code {process.returncode} - check {config.logs_dir / 'onedrive-mount.log'}")
        _mount_process = None
        raise RuntimeError(f"OneDrive mount failed with code {process.returncode}")

    try:
        contents = list(mount_dir.iterdir())
        if not contents:
            process.terminate()
            _mount_process = None
            raise RuntimeError(f"OneDrive mounted but directory is empty at {mount_dir} - check token/drive_id/remote_path")
    except (OSError, PermissionError):
        pass

    logger.info(f"OneDrive mounted at {mount_dir}")
    return process


def _kill_mount_users(mount_dir: pl.Path) -> None:
    subprocess.run(["fuser", "-km", str(mount_dir)], capture_output=True, text=True, timeout=5)


def is_mounted(mount_dir: pl.Path) -> bool:
    try:
        with open("/proc/mounts") as mounts:
            return str(mount_dir) in mounts.read()
    except FileNotFoundError:
        return mount_dir.is_mount()


def unmount_onedrive(mount_dir: pl.Path, *, timeout: int = 10) -> None:
    global _mount_process

    if not is_mounted(mount_dir):
        return

    logger.info(f"Unmounting OneDrive from {mount_dir}")

    commands = [
        ["fusermount", "-uz", str(mount_dir)],
        ["fusermount", "-u", str(mount_dir)],
        ["umount", str(mount_dir)],
    ]

    for cmd in commands:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if result.returncode == 0:
                break
            logger.warning(f"Command {' '.join(cmd)} failed: {result.stderr.strip()}")
        except (subprocess.SubprocessError, FileNotFoundError):
            continue
    else:
        logger.warning("Normal unmount failed; killing processes")
        _kill_mount_users(mount_dir)
        subprocess.run(["fusermount", "-u", str(mount_dir)], capture_output=True, text=True, timeout=timeout)

    if _mount_process:
        try:
            _mount_process.terminate()
            _mount_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _mount_process.kill()
        finally:
            _mount_process = None

    logger.info("OneDrive unmounted")
    if mount_dir.exists():
        for child in mount_dir.iterdir():
            if child.is_file():
                child.unlink(missing_ok=True)
            elif child.is_dir():
                child.rmdir()
        mount_dir.rmdir()
        logger.info(f"Removed mount directory {mount_dir}")
