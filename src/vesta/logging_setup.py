import logging
import pathlib as pl
from logging.handlers import RotatingFileHandler


def setup_logging(logs_dir: pl.Path, *, debug: bool = False) -> logging.Logger:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "vesta.log"

    logger = logging.getLogger("vesta")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)

    logger.handlers.clear()

    file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    logger.propagate = False

    return logger
