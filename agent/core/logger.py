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
    return _MARKUP_RE.sub("", msg)


def _log(msg: str, *, level: int = logging.INFO) -> None:
    record = _logger.makeRecord(_logger.name, level, "", 0, msg, (), None)
    _console_handler.emit(record)
    try:
        sys.stdout.flush()
    except BlockingIOError:
        pass

    if _file_handler:
        clean_record = _logger.makeRecord(_logger.name, level, "", 0, _strip_markup(msg), (), None)
        _file_handler.emit(clean_record)


def _cat(symbol: str, color: str, prefix: str, msg: tp.Any, *, level: int = logging.INFO) -> None:
    _log(f"{symbol} [{color}][{prefix}][/{color}] {msg}", level=level)


def _system_phase(phase: str, msg: tp.Any, *, level: int = logging.INFO) -> None:
    _log(f"* [cyan][SYSTEM][/cyan] - [dim][{phase}][/dim] {msg}", level=level)


def _agent_phase(phase: str, msg: tp.Any, *, level: int = logging.INFO) -> None:
    _log(f"< [magenta][AGENT][/magenta] - [blue][{phase}][/blue] {msg}", level=level)


def _user_phase(phase: str, msg: tp.Any, *, level: int = logging.INFO) -> None:
    _log(f"> [white][USER][/white] - [dim][{phase}][/dim] {msg}", level=level)


def _event_phase(phase: str, msg: tp.Any, *, level: int = logging.INFO) -> None:
    _log(f"! [yellow][EVENT][/yellow] - [dim][{phase}][/dim] {msg}", level=level)


# Category loggers
def init(msg: tp.Any) -> None:
    _system_phase("INIT", msg)


def shutdown(msg: tp.Any) -> None:
    _system_phase("SHUTDOWN", msg)


def client(msg: tp.Any) -> None:
    _system_phase("CLIENT", msg)


def dreamer(msg: tp.Any) -> None:
    _system_phase("DREAMER", msg)


def interrupt(msg: tp.Any) -> None:
    _system_phase("INTERRUPT", msg, level=logging.DEBUG)


def proactive(msg: tp.Any) -> None:
    _system_phase("PROACTIVE", msg)


def startup(msg: tp.Any) -> None:
    _system_phase("STARTUP", msg)


def user(msg: tp.Any) -> None:
    _user_phase("MESSAGE", msg)


def assistant(msg: tp.Any) -> None:
    _agent_phase("ASSISTANT", msg)


def thinking(msg: tp.Any) -> None:
    text = str(msg)
    lines = text.splitlines() or [text]
    for line in lines:
        _agent_phase("THINKING", line)


def tool(msg: tp.Any) -> None:
    _agent_phase("TOOL CALL", msg)


def notification(msg: tp.Any) -> None:
    _event_phase("NOTIFICATION", msg)


def system(msg: tp.Any) -> None:
    _system_phase("MESSAGE", msg)


def subagent(msg: tp.Any) -> None:
    _agent_phase("SUBAGENT", msg)


def sdk(msg: tp.Any) -> None:
    _system_phase("SDK", msg, level=logging.DEBUG)


def usage(msg: tp.Any) -> None:
    _system_phase("USAGE", msg)


def debug(msg: tp.Any) -> None:
    _log(f"[dim]{msg}[/dim]", level=logging.DEBUG)


def warning(msg: tp.Any) -> None:
    _log(f"[yellow]! {msg}[/yellow]", level=logging.WARNING)


def error(msg: tp.Any) -> None:
    _log(f"[red]x {msg}[/red]", level=logging.ERROR)


def exception(msg: tp.Any) -> None:
    _logger.exception(_strip_markup(str(msg)))
