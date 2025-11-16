import asyncio
import subprocess
import pathlib as pl
import datetime as dt
import shutil

from vesta.constants import Formats


def read_file(path: pl.Path) -> str | None:
    try:
        return path.read_text()
    except FileNotFoundError:
        return None
    except Exception:
        return None


def delete_file(path: pl.Path) -> bool:
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return True
    except Exception:
        return False


def copy_file(source: pl.Path, dest: pl.Path) -> bool:
    try:
        shutil.copy(source, dest)
        return True
    except Exception:
        return False


def create_directory(path: pl.Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except Exception:
        return False


def file_exists(path: pl.Path) -> bool:
    return path.exists()


def list_json_files(directory: pl.Path) -> list[pl.Path]:
    if not directory.exists():
        return []
    try:
        return list(directory.glob("*.json"))
    except Exception:
        return []


def run_subprocess(command: list[str], *, capture_output: bool = True) -> tuple[int, str, str]:
    try:
        result = subprocess.run(command, capture_output=capture_output, text=True)
        return result.returncode, result.stdout or "", result.stderr or ""
    except Exception as e:
        return -1, "", str(e)


def check_process_running(process_pattern: str) -> bool:
    returncode, stdout, _ = run_subprocess(["pgrep", "-f", process_pattern])
    return returncode == 0 and bool(stdout.strip())


def get_current_time() -> dt.datetime:
    return dt.datetime.now()


def get_timestamp_string(*, format: str = Formats.TIMESTAMP) -> str:
    return dt.datetime.now().strftime(format)


def print_line(text: str, *, flush: bool = False) -> None:
    try:
        print(text, flush=flush)
    except BlockingIOError:
        # Stdout buffer full or not ready (common in signal handlers), skip this message
        pass


def print_inline(text: str) -> None:
    try:
        print(text, end="", flush=True)
    except BlockingIOError:
        pass


def clear_line() -> None:
    print("\r\033[K", end="", flush=True)


def move_cursor_up_and_clear() -> None:
    print("\033[1A\033[K", end="")


def render_messages(lines: list[str]) -> None:
    for line in lines:
        print_line(line)


def delete_files(paths: set[str]) -> dict[str, bool]:
    results = {}
    for path_str in paths:
        path = pl.Path(path_str)
        results[path_str] = delete_file(path)
    return results


def load_notification_files(directory: pl.Path) -> list[tuple[pl.Path, str | None]]:
    files = list_json_files(directory)
    return [(file, read_file(file)) for file in files]


def set_env_var(key: str, value: str) -> None:
    import os

    os.environ[key] = value


def exit_process(code: int = 0) -> None:
    import os

    os._exit(code)


def log_error(message: str, *, colors: dict[str, str]) -> None:
    print_line(f"{colors['yellow']}⚠️ {message}{colors['reset']}")


def log_success(message: str, *, colors: dict[str, str]) -> None:
    print_line(f"{colors['green']}✅ {message}{colors['reset']}")


def log_info(message: str, *, colors: dict[str, str]) -> None:
    print_line(f"{colors['cyan']}📝 {message}{colors['reset']}")


async def sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


async def print_locked(lock: "asyncio.Lock", text: str, *, flush: bool = False) -> None:
    """Print with lock to prevent concurrent writes to terminal."""
    async with lock:
        print(text, flush=flush)


async def print_inline_locked(lock: "asyncio.Lock", *, text: str) -> None:
    """Print inline with lock to prevent concurrent writes to terminal."""
    async with lock:
        print(text, end="", flush=True)


async def clear_line_locked(lock: "asyncio.Lock") -> None:
    """Clear line with lock to prevent concurrent writes to terminal."""
    async with lock:
        print("\r\033[K", end="", flush=True)


async def move_cursor_up_and_clear_locked(lock: "asyncio.Lock") -> None:
    """Move cursor up and clear line with lock to prevent concurrent writes to terminal."""
    async with lock:
        print("\033[1A\033[K", end="")


async def render_messages_locked(lock: "asyncio.Lock", *, lines: list[str]) -> None:
    """Render messages with lock to prevent concurrent writes to terminal."""
    async with lock:
        for line in lines:
            print(line, flush=False)
