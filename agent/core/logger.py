"""Vesta logger - import and use directly: logger.info(), logger.dreamer(), etc."""

import contextlib
import logging
import pathlib as pl
import re
import sys
import typing as tp
from logging.handlers import RotatingFileHandler

from rich.console import Console
from rich.logging import RichHandler

console = Console(force_terminal=True)

# Exactly the tags this module emits, so bracketed content (`[result]`, `[error]`) survives into the file.
_MARKUP_RE = re.compile(r"\[/?(?:blue|cyan|dim|magenta|red|white|yellow)\]")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

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


def _file_handlers() -> list[RotatingFileHandler]:
    # The file handler's one owner is _logger.handlers (where setup registers it); deriving it
    # avoids a second, module-level copy of the same state.
    return [handler for handler in _logger.handlers if isinstance(handler, RotatingFileHandler)]


def setup(logs_dir: pl.Path, *, log_level: str = "INFO") -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "vesta.log"

    levels = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARNING": logging.WARNING, "ERROR": logging.ERROR, "CRITICAL": logging.CRITICAL}
    level = levels[log_level.upper()] if log_level.upper() in levels else logging.INFO
    _logger.setLevel(level)
    _console_handler.setLevel(level)

    for stale in _file_handlers():
        _logger.removeHandler(stale)
        stale.close()

    file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    _logger.addHandler(file_handler)


def _plain(msg: str) -> str:
    """Console styling out, so the file stays greppable: rich's own tags, plus any ANSI a captured payload carried in."""
    return _ANSI_RE.sub("", _MARKUP_RE.sub("", msg))


def _emit(msg: str, *, level: int) -> None:
    record = _logger.makeRecord(_logger.name, level, "", 0, msg, (), None)
    _console_handler.emit(record)
    with contextlib.suppress(BlockingIOError):
        sys.stdout.flush()

    for file_handler in _file_handlers():
        clean_record = _logger.makeRecord(_logger.name, level, "", 0, _plain(msg), (), None)
        file_handler.emit(clean_record)


def _log(msg: tp.Any, *, prefix: str = "", suffix: str = "", level: int = logging.INFO) -> None:
    """One record per line of msg. vesta.log is line-oriented, so a multi-line message emitted whole would
    write continuation lines carrying no timestamp and no source tag, invisible to any line-wise grep."""
    for line in str(msg).splitlines() or [""]:
        _emit(f"{prefix}{line}{suffix}", level=level)


def _system_phase(phase: str, msg: tp.Any, *, level: int = logging.INFO) -> None:
    _log(msg, prefix=f"* [cyan][SYSTEM][/cyan] - [dim][{phase}][/dim] ", level=level)


def _agent_phase(phase: str, msg: tp.Any, *, level: int = logging.INFO) -> None:
    _log(msg, prefix=f"< [magenta][AGENT][/magenta] - [blue][{phase}][/blue] ", level=level)


def _user_phase(phase: str, msg: tp.Any, *, level: int = logging.INFO) -> None:
    _log(msg, prefix=f"> [white][USER][/white] - [dim][{phase}][/dim] ", level=level)


# Category loggers
def init(msg: tp.Any) -> None:
    _system_phase("INIT", msg)


def shutdown(msg: tp.Any) -> None:
    _system_phase("SHUTDOWN", msg)


def client(msg: tp.Any) -> None:
    _system_phase("CLIENT", msg)


def dreamer(msg: tp.Any) -> None:
    _system_phase("DREAMER", msg)


def proactive(msg: tp.Any) -> None:
    _system_phase("PROACTIVE", msg)


def startup(msg: tp.Any) -> None:
    _system_phase("STARTUP", msg)


def user(msg: tp.Any) -> None:
    _user_phase("MESSAGE", msg)


def assistant(msg: tp.Any) -> None:
    _agent_phase("ASSISTANT", msg)


def thinking(msg: tp.Any) -> None:
    _agent_phase("THINKING", msg)


def tool(msg: tp.Any) -> None:
    _agent_phase("TOOL CALL", msg)


def system(msg: tp.Any) -> None:
    _system_phase("MESSAGE", msg)


def subagent(msg: tp.Any) -> None:
    _agent_phase("SUBAGENT", msg)


def sdk(msg: tp.Any) -> None:
    _system_phase("SDK", msg, level=logging.DEBUG)


def usage(msg: tp.Any) -> None:
    _system_phase("USAGE", msg)


def debug(msg: tp.Any) -> None:
    _log(msg, prefix="[dim]", suffix="[/dim]", level=logging.DEBUG)


def warning(msg: tp.Any) -> None:
    _log(msg, prefix="[yellow]! ", suffix="[/yellow]", level=logging.WARNING)


def error(msg: tp.Any) -> None:
    _log(msg, prefix="[red]x ", suffix="[/red]", level=logging.ERROR)


def exception(msg: tp.Any) -> None:
    _logger.exception(_plain(str(msg)))
