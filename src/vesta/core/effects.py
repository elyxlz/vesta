"""Side-effect wrappers for testability.

These thin wrappers around stdlib functions enable dependency injection in tests.
In production they simply delegate to the underlying calls.
"""

import datetime as dt
import pathlib as pl


def read_file(path: pl.Path) -> str:
    """Read file contents. Wraps Path.read_text for test mocking."""
    return path.read_text(encoding="utf-8")


def delete_file(path: pl.Path) -> None:
    """Delete file if exists. Wraps Path.unlink for test mocking."""
    path.unlink(missing_ok=True)


def list_json_files(directory: pl.Path) -> list[pl.Path]:
    if not directory.exists():
        return []
    return list(directory.glob("*.json"))


def get_current_time() -> dt.datetime:
    """Get current time. Wraps datetime.now for test mocking."""
    return dt.datetime.now()


def delete_files(paths: set[str]) -> None:
    for path_str in paths:
        delete_file(pl.Path(path_str))


def load_notification_files(directory: pl.Path) -> list[tuple[pl.Path, str]]:
    files = list_json_files(directory)
    return [(file, read_file(file)) for file in files]


def exit_process(code: int = 0) -> None:
    """Force immediate process termination. Only use from signal handlers."""
    import os

    os._exit(code)
