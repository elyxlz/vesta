import pathlib as pl
import datetime as dt
import logging


def get_logger() -> logging.Logger:
    return logging.getLogger("vesta")


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


def list_json_files(directory: pl.Path) -> list[pl.Path]:
    if not directory.exists():
        return []
    try:
        return list(directory.glob("*.json"))
    except Exception:
        return []


def get_current_time() -> dt.datetime:
    return dt.datetime.now()


def delete_files(paths: set[str]) -> dict[str, bool]:
    results = {}
    for path_str in paths:
        path = pl.Path(path_str)
        results[path_str] = delete_file(path)
    return results


def load_notification_files(directory: pl.Path) -> list[tuple[pl.Path, str | None]]:
    files = list_json_files(directory)
    return [(file, read_file(file)) for file in files]


def exit_process(code: int = 0) -> None:
    import os

    os._exit(code)
