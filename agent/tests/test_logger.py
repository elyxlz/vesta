"""Tests for vesta.log's line structure and semantic ANSI colors."""

import pathlib as pl
import re

import pytest

from core import logger

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
EMITTER_LINE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ")


@pytest.fixture
def log_file(tmp_path: pl.Path) -> pl.Path:
    logger.setup(tmp_path)
    return tmp_path / "vesta.log"


def raw_lines(log_file: pl.Path) -> list[str]:
    return log_file.read_text().splitlines()


def read_lines(log_file: pl.Path) -> list[str]:
    return [ANSI_RE.sub("", line) for line in raw_lines(log_file)]


def test_every_line_of_a_multiline_message_carries_a_timestamp_and_source_tag(log_file: pl.Path) -> None:
    logger.assistant("I counted the rate limits\nand found three\nacross today")

    lines = read_lines(log_file)
    assert len(lines) == 3
    for line in lines:
        assert EMITTER_LINE.match(line), line
        assert "[AGENT] [ASSISTANT] " in line
    assert lines[2].endswith("across today")


def test_a_multiline_warning_tags_every_line(log_file: pl.Path) -> None:
    logger.warning("config store is corrupt\nkeeping the rest")

    lines = read_lines(log_file)
    assert len(lines) == 2
    assert all(EMITTER_LINE.match(line) and "[WARNING] [SYSTEM] [RUNTIME] " in line for line in lines)


def test_embedded_ansi_is_replaced_by_the_semantic_line_color(log_file: pl.Path) -> None:
    logger.system("tool said \x1b[31mred\x1b[0m today")

    assert "\x1b[31mred" not in log_file.read_text()
    assert read_lines(log_file)[0].endswith("[SYSTEM] [MESSAGE] tool said red today")


def test_bracketed_content_survives_into_the_file(log_file: pl.Path) -> None:
    logger.system("[result] the tool exited 0")

    assert read_lines(log_file)[0].endswith("[SYSTEM] [MESSAGE] [result] the tool exited 0")


def test_an_empty_message_still_emits_its_tag(log_file: pl.Path) -> None:
    logger.system("")

    assert read_lines(log_file)[0].endswith("[SYSTEM] [MESSAGE] ")


def test_counting_system_lines_finds_every_daemon_record_and_no_agent_narration(log_file: pl.Path) -> None:
    logger.system("Rate limit rejected\nRate limit rejected on retry")
    logger.assistant("Let me grep for Rate limit rejected\nto see how many Rate limit rejected lines exist")
    logger.tool("Bash: grep -c 'Rate limit rejected' vesta.log")

    system_lines = [line for line in read_lines(log_file) if "[SYSTEM]" in line]
    assert len(system_lines) == 2
    assert sum("Rate limit rejected" in line for line in system_lines) == 2


@pytest.mark.parametrize(
    ("emit", "pattern"),
    [
        (logger.thinking, r"\x1b\[2;35m.*\[AGENT\] \[THINKING\] hello\x1b\[0m"),
        (logger.assistant, r"\x1b\[95m.*\[AGENT\] \[ASSISTANT\] hello\x1b\[0m"),
        (logger.notification, r"\x1b\[36m.*\[NOTIFICATION\] \[MESSAGE\] hello\x1b\[0m"),
        (logger.warning, r"\x1b\[33m.*\[WARNING\] \[SYSTEM\] \[RUNTIME\] hello\x1b\[0m"),
    ],
)
def test_file_log_colors_the_complete_line(log_file: pl.Path, emit, pattern: str) -> None:
    emit("hello")

    assert re.fullmatch(pattern, raw_lines(log_file)[0])
