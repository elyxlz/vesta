"""`MICROSOFT_READ_ONLY` refuses every command that writes to the account.

An agent handed someone else's mailbox to read must not be able to send mail, post to Teams,
delete messages, or rename folders; `EMAIL_DRAFT_ONLY` covers only the three transmitting email
verbs. The guard sits at the single dispatch choke point in `main()`, keyed by `(group, command)`,
so a route added later cannot quietly escape it by being dispatched somewhere else.

Deliberately still allowed: `email send-delay` and `email pending` configure and inspect the
local outbox and are invisible to the account's owner, and `email undo` cancels a queued send,
so it only ever removes a write.
"""

from __future__ import annotations

import argparse

import pytest
from microsoft_cli import cli

# Independent pins of the classification: a command moving between these lists, entering the
# parser unclassified, or leaving `_MUTATING_COMMANDS` must fail a test here.
_WRITES = [
    ("email", "send"),
    ("email", "reply"),
    ("email", "forward"),
    ("email", "draft"),
    ("email", "reply-draft"),
    ("email", "delete"),
    ("email", "move"),
    ("email", "archive"),
    ("email", "update"),
    ("email", "block"),
    ("email", "unblock"),
    ("calendar", "create"),
    ("calendar", "update"),
    ("calendar", "delete"),
    ("calendar", "respond"),
    ("folder", "create"),
    ("folder", "rename"),
    ("folder", "delete"),
    ("teams", "send"),
    ("teams", "start"),
    ("teams", "post"),
    ("teams", "reply"),
    ("teams", "set-presence"),
    ("teams", "clear-presence"),
    ("notify", "add"),
    ("notify", "remove"),
]
_READS = [
    ("email", "list"),
    ("email", "get"),
    ("email", "search"),
    ("email", "attachment"),
    ("email", "pending"),
    ("email", "send-delay"),
    ("email", "undo"),
    ("calendar", "list"),
    ("calendar", "calendars"),
    ("calendar", "get"),
    ("folder", "list"),
    ("folder", "status"),
    ("teams", "chats"),
    ("teams", "messages"),
    ("teams", "teams"),
    ("teams", "channels"),
    ("teams", "channel-messages"),
    ("teams", "presence"),
    ("notify", "list"),
]


@pytest.mark.parametrize(("group", "command"), _WRITES)
def test_read_only_refuses_every_writing_command(monkeypatch: pytest.MonkeyPatch, group: str, command: str) -> None:
    monkeypatch.setenv("MICROSOFT_READ_ONLY", "1")
    with pytest.raises(RuntimeError, match="read-only mode"):
        cli._guard_read_only(group, command)


@pytest.mark.parametrize(("group", "command"), _READS)
def test_read_only_still_allows_reads(monkeypatch: pytest.MonkeyPatch, group: str, command: str) -> None:
    monkeypatch.setenv("MICROSOFT_READ_ONLY", "1")
    cli._guard_read_only(group, command)


def test_every_guarded_group_command_is_classified() -> None:
    """A subcommand added to a guarded group must be classified read or write the day it is added:
    an unclassified writer would sail through the read-only guard silently."""
    parser = cli.build_parser()
    top = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    guarded = ("email", "calendar", "folder", "notify", "teams")
    parser_commands = {
        (group, command)
        for group in guarded
        for action in top.choices[group]._actions
        if isinstance(action, argparse._SubParsersAction)
        for command in action.choices
    }
    assert parser_commands == set(_WRITES) | set(_READS)
    assert frozenset(_WRITES) == cli._MUTATING_COMMANDS


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "Yes"])
def test_read_only_accepts_the_documented_truthy_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("MICROSOFT_READ_ONLY", value)
    assert cli._read_only_enabled() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "  "])
def test_read_only_is_off_by_default_and_for_falsy_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("MICROSOFT_READ_ONLY", value)
    assert cli._read_only_enabled() is False
    cli._guard_read_only("email", "send")


def test_read_only_unset_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MICROSOFT_READ_ONLY", raising=False)
    assert cli._read_only_enabled() is False
    cli._guard_read_only("teams", "send")


def test_draft_only_is_untouched_by_this_change() -> None:
    assert sorted(cli._TRANSMIT_COMMANDS) == ["forward", "reply", "send"]
