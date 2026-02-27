"""Vesta logger - import and use directly: logger.info(), logger.dreamer(), etc."""

import logging
import pathlib as pl
import re
import sys
import typing as tp

from rich.console import Console
from rich.logging import RichHandler

console = Console(force_terminal=True)

_MARKUP_RE = re.compile(r"\[/?[a-z_]+\]")

_logger = logging.getLogger("vesta")
_logger.setLevel(logging.INFO)
_logger.handlers = []
_logger.propagate = False

_console_handler = RichHandler(
    console=console,
    show_time=True,
    show_path=False,
    rich_tracebacks=True,
    markup=True,
    omit_repeated_times=False,
)
_console_handler.setFormatter(logging.Formatter("%(message)s"))
_console_handler.setLevel(logging.INFO)
_logger.addHandler(_console_handler)

_file_handler: logging.Handler | None = None


def setup(logs_dir: pl.Path, *, log_level: str = "INFO") -> None:
    global _file_handler

    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "vesta.log"

    levels = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARNING": logging.WARNING, "ERROR": logging.ERROR, "CRITICAL": logging.CRITICAL}
    level = levels[log_level.upper()] if log_level.upper() in levels else logging.INFO
    _logger.setLevel(level)
    _console_handler.setLevel(level)

    if _file_handler:
        _logger.removeHandler(_file_handler)
        _file_handler.close()

    from logging.handlers import RotatingFileHandler

    _file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    _file_handler.setLevel(logging.DEBUG)
    _file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    _logger.addHandler(_file_handler)


def _strip_markup(msg: str) -> str:
    clean = _MARKUP_RE.sub("", msg)
    if clean and ord(clean[0]) > 127:
        clean = clean.lstrip()
        if clean and ord(clean[0]) > 127:
            clean = clean[1:].lstrip()
    return clean


def _log(msg: str, *, level: int = logging.INFO) -> None:
    record = _logger.makeRecord(_logger.name, level, "", 0, msg, (), None)
    _console_handler.emit(record)
    sys.stdout.flush()

    if _file_handler:
        clean_record = _logger.makeRecord(_logger.name, level, "", 0, _strip_markup(msg), (), None)
        _file_handler.emit(clean_record)
        _file_handler.flush()


def _cat(symbol: str, color: str, prefix: str, msg: tp.Any, *, level: int = logging.INFO) -> None:
    _log(f"{symbol} [{color}][{prefix}][/{color}] {msg}", level=level)


# Category loggers
def init(msg: tp.Any) -> None:
    _cat("*", "yellow", "INIT", msg)


def shutdown(msg: tp.Any) -> None:
    _cat("*", "red", "SHUTDOWN", msg)


def client(msg: tp.Any) -> None:
    _cat("*", "dim", "CLIENT", msg)


def dreamer(msg: tp.Any) -> None:
    _cat("*", "magenta", "DREAMER", msg)


def interrupt(msg: tp.Any) -> None:
    _cat("*", "yellow", "INTERRUPT", msg, level=logging.DEBUG)


def proactive(msg: tp.Any) -> None:
    _cat("*", "yellow", "PROACTIVE", msg)


def startup(msg: tp.Any) -> None:
    _cat("*", "dim", "STARTUP", msg)


def user(msg: tp.Any) -> None:
    _cat(">", "white", "USER", msg)


def assistant(msg: tp.Any) -> None:
    _cat("<", "magenta", "ASSISTANT", msg)


def tool(msg: tp.Any) -> None:
    _cat("~", "dim", "TOOL", msg)


def output(msg: tp.Any) -> None:
    _cat("~", "dim", "OUTPUT", msg)


def notification(msg: tp.Any) -> None:
    _cat("!", "yellow", "NOTIFICATION", msg)


def system(msg: tp.Any) -> None:
    _cat(">", "cyan", "SYSTEM", msg)


def subagent(msg: tp.Any) -> None:
    _cat("*", "magenta", "SUBAGENT", msg)


def sdk(msg: tp.Any) -> None:
    _cat("~", "dim", "SDK", msg, level=logging.DEBUG)


# Standard loggers
def debug(msg: tp.Any) -> None:
    _log(f"[dim]{msg}[/dim]", level=logging.DEBUG)


def info(msg: tp.Any) -> None:
    _log(str(msg))


def warning(msg: tp.Any) -> None:
    _log(f"[yellow]! {msg}[/yellow]", level=logging.WARNING)


def error(msg: tp.Any) -> None:
    _log(f"[red]x {msg}[/red]", level=logging.ERROR)


def critical(msg: tp.Any) -> None:
    _log(f"[bold red]X {msg}[/bold red]", level=logging.CRITICAL)


def exception(msg: tp.Any) -> None:
    _logger.exception(_strip_markup(str(msg)))
