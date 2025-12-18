"""Vesta logger - import and use directly: logger.info(), logger.debug(), etc."""

import datetime as dt
import functools
import logging
import pathlib as pl
import sys
import typing as tp

import rich.console


class ColoredFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[94m",
        "INFO": "\033[96m",
        "WARNING": "\033[93m",
        "ERROR": "\033[91m",
        "CRITICAL": "\033[95m",
    }
    RESET = "\033[0m"
    BOLD = "\033[1m"

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return dt.datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        bold = self.BOLD if record.levelname in ["ERROR", "CRITICAL"] else ""
        formatted = super().format(record)
        return f"\r{color}{bold}{formatted}{self.RESET}\n"


class CleanStreamHandler(logging.StreamHandler):
    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        stream = self.stream or sys.stdout
        try:
            stream.write(msg)
            self.flush()
        except Exception:
            self.handleError(record)


# Internal logger instance
_logger = logging.getLogger("vesta")
_logger.setLevel(logging.INFO)
_logger.handlers = []
_logger.propagate = False

# Console handler with colors
_handler = CleanStreamHandler(sys.stdout)
_handler.setFormatter(ColoredFormatter("%(asctime)s | %(levelname)s | %(message)s"))
_logger.addHandler(_handler)

# File handler (set up later via setup())
_file_handler: logging.Handler | None = None


def setup(logs_dir: pl.Path, *, debug: bool = False) -> None:
    """Configure logging with file output."""
    global _file_handler

    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "vesta.log"

    level = logging.DEBUG if debug else logging.INFO
    _logger.setLevel(level)
    _handler.setLevel(level)

    # Remove old file handler if exists
    if _file_handler:
        _logger.removeHandler(_file_handler)
        _file_handler.close()

    # Add rotating file handler
    from logging.handlers import RotatingFileHandler

    _file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    _file_handler.setLevel(logging.DEBUG)
    _file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    _logger.addHandler(_file_handler)


def _log(level: int, msg: tp.Any) -> None:
    if level >= _logger.level:
        if isinstance(msg, dict | list):
            console = rich.console.Console()
            console.print_json(data=msg, indent=2)
        else:
            _logger.log(level, str(msg))


debug = functools.partial(_log, logging.DEBUG)
info = functools.partial(_log, logging.INFO)
warning = functools.partial(_log, logging.WARNING)
error = functools.partial(_log, logging.ERROR)
critical = functools.partial(_log, logging.CRITICAL)


def exception(msg: tp.Any) -> None:
    _logger.exception(msg)
