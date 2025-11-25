import logging
import pathlib as pl
import sys
from logging.handlers import RotatingFileHandler


def _configure_handler(handler: logging.Handler, *, level: int, formatter: logging.Formatter) -> logging.Handler:
    handler.setLevel(level)
    handler.setFormatter(formatter)
    return handler


def setup_logging(logs_dir: pl.Path, *, debug: bool = False, console: bool = True) -> logging.Logger:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "vesta.log"

    logger = logging.getLogger("vesta")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)

    for handler in logger.handlers:
        handler.close()
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    logger.addHandler(_configure_handler(file_handler, level=logging.DEBUG, formatter=formatter))

    if console:
        stream_handler = logging.StreamHandler(stream=sys.stdout)
        logger.addHandler(_configure_handler(stream_handler, level=logging.DEBUG if debug else logging.INFO, formatter=formatter))

    logger.propagate = False

    return logger
