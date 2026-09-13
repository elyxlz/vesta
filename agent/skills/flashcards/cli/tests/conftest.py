import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from flashcards_cli import db
from flashcards_cli.config import Config

NOON = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def tmp_config(tmp_path: Path) -> Config:
    cfg = Config(data_dir=tmp_path / "flashcards", log_dir=tmp_path / "flashcards" / "logs")
    cfg.log_dir.mkdir(parents=True)
    db.init_db(cfg.data_dir)
    return cfg


@pytest.fixture
def conn(tmp_config: Config) -> sqlite3.Connection:
    connection = db.get_db(tmp_config.data_dir)
    yield connection
    connection.close()
