"""OneDrive integration using rclone FUSE mount."""

import asyncio
import json
import logging
import pathlib as pl
import subprocess
import time

from .models import VestaSettings

logger = logging.getLogger(__name__)

# Store the mount process globally for cleanup
_mount_process: subprocess.Popen | None = None


def check_rclone_installed() -> bool:
    """Check if rclone is installed and available in PATH."""
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


def setup_rclone_config(config: VestaSettings, *, config_path: pl.Path) -> None:
    """Generate rclone configuration file from environment variables.

    Args:
        config: VestaSettings instance with OneDrive configuration
        config_path: Path where rclone.conf should be written

    Raises:
        ValueError: If required OneDrive configuration is missing
    """
    if not config.onedrive_token:
        raise ValueError("ONEDRIVE_TOKEN environment variable is required")

    # Parse the token JSON to validate it
    try:
        json.loads(config.onedrive_token)
    except json.JSONDecodeError as e:
        raise ValueError(f"ONEDRIVE_TOKEN must be valid JSON: {e}")

    # Build rclone config content
    # If client_id and client_secret are provided, use them
    # Otherwise, rclone will use its built-in OAuth credentials
    rclone_config = f"""[{config.onedrive_remote_name}]
type = onedrive
"""

    if config.onedrive_client_id and config.onedrive_client_secret:
        rclone_config += f"""client_id = {config.onedrive_client_id}
client_secret = {config.onedrive_client_secret}
"""

    rclone_config += f"""region = global
token = {config.onedrive_token}
drive_type = personal
"""

    # Write config file
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
    """Mount OneDrive using rclone.

    Args:
        config: VestaSettings instance with OneDrive configuration
        mount_dir: Local directory where OneDrive should be mounted
        config_path: Path to rclone.conf file
        timeout: Maximum seconds to wait for mount to be ready

    Returns:
        The rclone mount subprocess

    Raises:
        RuntimeError: If mount fails or times out
    """
    global _mount_process

    # Create mount directory if it doesn't exist
    mount_dir.mkdir(parents=True, exist_ok=True)

    # Build rclone mount command
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
        # Start rclone mount process
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _mount_process = process

        # Wait for mount to be ready by checking if directory is accessible
        start_time = time.time()
        while time.time() - start_time < timeout:
            # Check if process has exited with error
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise RuntimeError(f"rclone mount process exited with code {process.returncode}\nstdout: {stdout}\nstderr: {stderr}")

            # Try to list the mount directory to verify it's mounted
            try:
                list(mount_dir.iterdir())
                logger.info(f"OneDrive successfully mounted at {mount_dir}")
                return process
            except (OSError, PermissionError):
                # Mount not ready yet, wait a bit
                await asyncio.sleep(0.5)

        # Timeout reached
        raise RuntimeError(f"Timeout waiting for OneDrive mount to be ready after {timeout}s")

    except Exception as e:
        # Cleanup on failure
        if _mount_process:
            _mount_process.terminate()
            _mount_process = None
        raise RuntimeError(f"Failed to mount OneDrive: {e}") from e


def unmount_onedrive(mount_dir: pl.Path, *, timeout: int = 10) -> None:
    """Unmount OneDrive and cleanup.

    Args:
        mount_dir: The mounted directory to unmount
        timeout: Maximum seconds to wait for unmount
    """
    global _mount_process

    logger.info(f"Unmounting OneDrive from {mount_dir}")

    try:
        # Use fusermount to unmount (works on Linux)
        result = subprocess.run(
            ["fusermount", "-u", str(mount_dir)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            logger.warning(f"fusermount returned {result.returncode}: {result.stderr}")
            # Try umount as fallback
            subprocess.run(
                ["umount", str(mount_dir)],
                capture_output=True,
                timeout=timeout,
            )

    except (subprocess.SubprocessError, FileNotFoundError) as e:
        logger.error(f"Failed to unmount OneDrive: {e}")

    # Terminate the mount process if it's still running
    if _mount_process:
        try:
            _mount_process.terminate()
            _mount_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _mount_process.kill()
        finally:
            _mount_process = None

    logger.info("OneDrive unmounted")
