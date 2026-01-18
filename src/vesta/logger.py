"""Vesta logger - import and use directly: logger.info(), logger.dreamer(), etc."""

import logging
import pathlib as pl
import re
import sys
import typing as tp

from rich.console import Console
from rich.logging import RichHandler

console = Console(force_terminal=True)

# Category styles: (symbol, color, prefix)
CATEGORIES: dict[str, tuple[str, str, str]] = {
    "init": ("*", "yellow", "INIT"),
    "shutdown": ("*", "red", "SHUTDOWN"),
    "client": ("*", "dim", "CLIENT"),
    "dreamer": ("*", "magenta", "DREAMER"),
    "interrupt": ("*", "yellow", "INTERRUPT"),
    "proactive": ("*", "yellow", "PROACTIVE"),
    "mcp": ("*", "dim", "MCP"),
    "user": (">", "white", "USER"),
    "assistant": ("<", "magenta", "ASSISTANT"),
    "tool": ("~", "dim", "TOOL"),
    "output": ("~", "dim", "OUTPUT"),
    "notification": ("!", "yellow", "NOTIFICATION"),
    "subagent": ("*", "magenta", "SUBAGENT"),
    "sdk": ("~", "dim", "SDK"),
}

# Regex to strip Rich markup for file logs
_MARKUP_RE = re.compile(r"\[/?[a-z_]+\]")

# Internal logger instance
_logger = logging.getLogger("vesta")
_logger.setLevel(logging.INFO)
_logger.handlers = []
_logger.propagate = False

# Console handler with Rich
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

# File handler (set up later via setup())
_file_handler: logging.Handler | None = None


def setup(logs_dir: pl.Path, *, log_level: str = "INFO") -> None:
    """Configure logging with file output."""
    global _file_handler

    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "vesta.log"

    level = getattr(logging, log_level.upper(), logging.INFO)
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
    """Remove Rich markup and emojis for file logs."""
    # Remove Rich markup tags
    clean = _MARKUP_RE.sub("", msg)
    # Remove leading emoji (first char if it's outside ASCII)
    if clean and ord(clean[0]) > 127:
        clean = clean.lstrip()
        if clean and ord(clean[0]) > 127:
            clean = clean[1:].lstrip()
    return clean


def _log(msg: str, *, level: int = logging.INFO) -> None:
    """Log with styled console and clean file output."""
    record = _logger.makeRecord(_logger.name, level, "", 0, msg, (), None)
    _console_handler.emit(record)
    sys.stdout.flush()  # Force immediate output

    if _file_handler:
        clean_record = _logger.makeRecord(_logger.name, level, "", 0, _strip_markup(msg), (), None)
        _file_handler.emit(clean_record)
        _file_handler.flush()


def _log_category(category: str, msg: tp.Any, *, level: int = logging.INFO) -> None:
    """Log a categorized message with styling."""
    emoji, color, prefix = CATEGORIES[category]
    styled = f"{emoji} [{color}][{prefix}][/{color}] {msg}"
    _log(styled, level=level)


# Category functions
def init(msg: tp.Any) -> None:
    _log_category("init", msg)


def shutdown(msg: tp.Any) -> None:
    _log_category("shutdown", msg)


def client(msg: tp.Any) -> None:
    _log_category("client", msg)


def dreamer(msg: tp.Any) -> None:
    _log_category("dreamer", msg)


def interrupt(msg: tp.Any) -> None:
    _log_category("interrupt", msg, level=logging.DEBUG)


def proactive(msg: tp.Any) -> None:
    _log_category("proactive", msg)


def mcp(msg: tp.Any) -> None:
    _log_category("mcp", msg)


def user(msg: tp.Any) -> None:
    _log_category("user", msg)


def assistant(msg: tp.Any) -> None:
    _log_category("assistant", msg)


def tool(msg: tp.Any) -> None:
    _log_category("tool", msg)


def output(msg: tp.Any) -> None:
    _log_category("output", msg)


def notification(msg: tp.Any) -> None:
    _log_category("notification", msg)


def subagent(msg: tp.Any) -> None:
    _log_category("subagent", msg)


def sdk(msg: tp.Any) -> None:
    _log_category("sdk", msg, level=logging.DEBUG)


# Standard logging functions
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
