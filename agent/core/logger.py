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
from rich.markup import escape

console = Console(force_terminal=True)
_file_console = Console(
    force_terminal=True,
    color_system="standard",
    no_color=False,
    highlight=False,
)

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


_FILE_LOG_FORMAT = "%(asctime)s %(vesta_level)s%(message)s"
_FILE_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_SYSTEM_PHASE_STYLES = {
    "INIT": "bright_green",
    "STARTUP": "bright_green",
    "SHUTDOWN": "dim green",
    "SDK": "dim green",
    "USAGE": "dim green",
}
_AGENT_PHASE_STYLES = {
    "ASSISTANT": "bright_magenta",
    "THINKING": "dim magenta",
}


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
    file_handler.setFormatter(_RichFileFormatter(_FILE_LOG_FORMAT, datefmt=_FILE_LOG_DATE_FORMAT))
    _logger.addHandler(file_handler)


def _plain(msg: str) -> str:
    """Console styling out, so the file stays greppable: rich's own tags, plus any ANSI a captured payload carried in."""
    return _ANSI_RE.sub("", _MARKUP_RE.sub("", msg))


def _render_markup(msg: str) -> str:
    """Render the logger's Rich markup to portable ANSI without wrapping."""
    with _file_console.capture() as capture:
        _file_console.print(msg, markup=True, highlight=False, soft_wrap=True, end="")
    return capture.get()


class _RichFileFormatter(logging.Formatter):
    """Render a semantic color across the complete persisted log line."""

    _MESSAGE_PLACEHOLDER = "\0VESTA_LOG_MESSAGE\0"

    def format(self, record: logging.LogRecord) -> str:
        had_level = hasattr(record, "vesta_level")
        original_level = getattr(record, "vesta_level", None)
        record.vesta_level = "" if record.levelno == logging.INFO else f"[{record.levelname}] "

        try:
            return self._format(record)
        finally:
            if had_level:
                record.vesta_level = original_level
            else:
                del record.vesta_level

    def _format(self, record: logging.LogRecord) -> str:
        line_style = getattr(record, "vesta_line_style", None)
        if not line_style:
            return super().format(record)

        message = record.getMessage()
        original_msg = record.msg
        original_args = record.args
        had_message = hasattr(record, "message")
        original_message = getattr(record, "message", None)

        try:
            record.msg = self._MESSAGE_PLACEHOLDER
            record.args = ()
            formatted = super().format(record)
        finally:
            record.msg = original_msg
            record.args = original_args
            if had_message:
                record.message = original_message
            else:
                del record.message

        prefix, suffix = formatted.split(self._MESSAGE_PLACEHOLDER, maxsplit=1)
        markup = f"[{line_style}]{escape(prefix)}{escape(message)}{escape(suffix)}[/{line_style}]"
        return _render_markup(markup)


def _emit(msg: str, *, level: int, line_style: str) -> None:
    console_record = _logger.makeRecord(
        _logger.name,
        level,
        "",
        0,
        f"[{line_style}]{escape(msg)}[/{line_style}]",
        (),
        None,
    )
    _console_handler.emit(console_record)
    with contextlib.suppress(BlockingIOError):
        sys.stdout.flush()

    for file_handler in _file_handlers():
        file_record = _logger.makeRecord(
            _logger.name,
            level,
            "",
            0,
            msg,
            (),
            None,
            extra={"vesta_line_style": line_style},
        )
        file_handler.emit(file_record)


def _log(msg: tp.Any, *, prefix: str, level: int = logging.INFO, line_style: str) -> None:
    """Emit one fully tagged, timestamped record per input line."""
    text = str(msg)
    for line in text.splitlines() or [text]:
        _emit(f"{prefix}{_plain(line)}", level=level, line_style=line_style)


def _system_phase(phase: str, msg: tp.Any, *, level: int = logging.INFO) -> None:
    _log(msg, prefix=f"[SYSTEM] [{phase}] ", level=level, line_style=_SYSTEM_PHASE_STYLES.get(phase, "green"))


def _agent_phase(phase: str, msg: tp.Any, *, level: int = logging.INFO) -> None:
    _log(msg, prefix=f"[AGENT] [{phase}] ", level=level, line_style=_AGENT_PHASE_STYLES.get(phase, "magenta"))


def _user_phase(phase: str, msg: tp.Any, *, level: int = logging.INFO) -> None:
    _log(msg, prefix=f"[USER] [{phase}] ", level=level, line_style="white")


def _notification_phase(phase: str, msg: tp.Any, *, level: int = logging.INFO) -> None:
    _log(msg, prefix=f"[NOTIFICATION] [{phase}] ", level=level, line_style="cyan")


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


def notification(msg: tp.Any) -> None:
    _notification_phase("MESSAGE", msg)


def subagent(msg: tp.Any) -> None:
    _agent_phase("SUBAGENT", msg)


def sdk(msg: tp.Any) -> None:
    _system_phase("SDK", msg, level=logging.DEBUG)


def usage(msg: tp.Any) -> None:
    _system_phase("USAGE", msg)


def debug(msg: tp.Any) -> None:
    _log(msg, prefix="[SYSTEM] [RUNTIME] ", level=logging.DEBUG, line_style="dim green")


def warning(msg: tp.Any) -> None:
    _log(msg, prefix="[SYSTEM] [RUNTIME] ", level=logging.WARNING, line_style="yellow")


def error(msg: tp.Any) -> None:
    _log(msg, prefix="[SYSTEM] [RUNTIME] ", level=logging.ERROR, line_style="red")


def exception(msg: tp.Any) -> None:
    _logger.exception(
        "[SYSTEM] [RUNTIME] %s",
        _plain(str(msg)),
        extra={"vesta_line_style": "red"},
    )
