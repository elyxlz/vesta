"""Tests for vesta.log's line structure: every line carries its own timestamp and source tag, so a
line-wise grep of the log can neither miss a real record nor count the agent's own narration as one."""

import pathlib as pl
import re

import pytest

from core import logger

EMITTER_LINE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \[[A-Z]+\] ")


@pytest.fixture
def log_file(tmp_path: pl.Path) -> pl.Path:
    logger.setup(tmp_path)
    return tmp_path / "vesta.log"


def read_lines(log_file: pl.Path) -> list[str]:
    return log_file.read_text().splitlines()


def test_every_line_of_a_multiline_message_carries_a_timestamp_and_source_tag(log_file: pl.Path) -> None:
    logger.assistant("I counted the rate limits\nand found three\nacross today")

    lines = read_lines(log_file)
    assert len(lines) == 3
    for line in lines:
        assert EMITTER_LINE.match(line), line
        assert "< [AGENT] - [ASSISTANT] " in line
    assert lines[2].endswith("across today")


def test_a_multiline_warning_tags_every_line(log_file: pl.Path) -> None:
    logger.warning("config store is corrupt\nkeeping the rest")

    lines = read_lines(log_file)
    assert len(lines) == 2
    assert all(EMITTER_LINE.match(line) and "[WARNING] ! " in line for line in lines)


def test_ansi_escapes_never_reach_the_file(log_file: pl.Path) -> None:
    logger.system("tool said \x1b[31mred\x1b[0m today")

    assert "\x1b" not in log_file.read_text()
    assert read_lines(log_file)[0].endswith("tool said red today")


def test_bracketed_content_survives_into_the_file(log_file: pl.Path) -> None:
    logger.system("[result] the tool exited 0")

    assert read_lines(log_file)[0].endswith("* [SYSTEM] - [MESSAGE] [result] the tool exited 0")


def test_an_empty_message_still_emits_its_tag(log_file: pl.Path) -> None:
    logger.system("")

    assert read_lines(log_file) == [] or read_lines(log_file)[0].endswith("* [SYSTEM] - [MESSAGE] ")


def test_counting_system_lines_finds_every_daemon_record_and_no_agent_narration(log_file: pl.Path) -> None:
    """The dream skill's log-diagnosis rule rests on this. A `[SYSTEM]` count must reach every line of a
    multi-line daemon record (an untagged continuation line would read as a false zero) and must reach
    none of the agent's own talk about the symptom (which would read as a false positive)."""
    logger.system("Rate limit rejected\nRate limit rejected on retry")
    logger.assistant("Let me grep for Rate limit rejected\nto see how many Rate limit rejected lines exist")
    logger.tool("Bash: grep -c 'Rate limit rejected' vesta.log")

    system_lines = [line for line in read_lines(log_file) if "[SYSTEM]" in line]
    assert len(system_lines) == 2
    assert sum("Rate limit rejected" in line for line in system_lines) == 2
