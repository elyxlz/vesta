import pathlib
import sys
import typing as tp

import pytest
from recall_cli import cli

Add = tp.Callable[..., None]


@pytest.mark.parametrize(
    "query,expected",
    [
        ("print-to-pdf", '"print-to-pdf"'),
        ("wifi password", '"wifi" "password"'),
        ("sched* v0.3.15", '"sched"* "v0.3.15"'),
        ("cats OR dog-food", '"cats" OR "dog-food"'),
    ],
)
def test_literal_query_quotes_non_operator_tokens(query: str, expected: str) -> None:
    assert cli.literal_query(query) == expected


def test_main_hyphenated_query_falls_back_to_literal_match(
    events_db: tuple[pathlib.Path, Add], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path, add = events_db
    add("assistant", "render it with chromium print-to-pdf headless")
    add("assistant", "unrelated message")
    monkeypatch.setattr(cli, "DB_PATH", path)
    monkeypatch.setattr(sys, "argv", ["recall", "print-to-pdf"])
    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "chromium print-to-pdf" in out
    assert "unrelated" not in out
