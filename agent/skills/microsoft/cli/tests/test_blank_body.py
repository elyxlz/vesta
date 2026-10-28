"""A blank --body is refused at argument parsing, before any draft is created or send queued."""

import pytest
from microsoft_cli import cli

_COMPOSE = {
    "send": ["--to", "bob@x.com", "--subject", "Hi"],
    "draft": ["--to", "bob@x.com"],
    "reply": ["--id", "MSG1"],
    "reply-draft": ["--id", "MSG1"],
    "forward": ["--id", "MSG1", "--to", "bob@x.com"],
}


@pytest.mark.parametrize("command", sorted(_COMPOSE))
@pytest.mark.parametrize("body", ["", "   ", "\n\t \n"])
def test_blank_body_is_refused(command, body, capsys):
    argv = ["email", command, "--account", "me@example.com", *_COMPOSE[command], "--body", body]
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(argv)
    assert exc.value.code != 0
    assert "--body is empty or whitespace only" in capsys.readouterr().err


@pytest.mark.parametrize("command", sorted(_COMPOSE))
def test_nonblank_body_is_kept_verbatim(command):
    argv = ["email", command, "--account", "me@example.com", *_COMPOSE[command], "--body", "  hello\n"]
    assert cli.build_parser().parse_args(argv).body == "  hello\n"


def test_forward_without_body_is_allowed():
    args = cli.build_parser().parse_args(["email", "forward", "--account", "me@example.com", "--id", "MSG1", "--to", "bob@x.com"])
    assert args.body is None
    _, _, kw_of = cli._email_routes()["forward"]
    assert kw_of(args)["mail"].body == ""
