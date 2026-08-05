"""Every email subcommand that takes a message id accepts both --id and --email-id.

Either spelling parses on all nine, so a wrong guess cannot exit 2 with a usage error. That
matters because these commands run with stderr suppressed, where a usage error looks exactly
like a command that ran and found nothing, turning a flag mismatch into a silent false negative.
"""

import pytest
from microsoft_cli.cli import build_parser

# (subcommand, extra required args beyond --account/--id)
ID_SUBCOMMANDS = [
    ("get", []),
    ("attachment", []),
    ("move", ["--to-folder", "Screened"]),
    ("archive", []),
    ("update", []),
    ("delete", []),
    ("reply", ["--body", "x"]),
    ("reply-draft", ["--body", "x"]),
    ("forward", ["--body", "x", "--to", "someone@example.com"]),
]


@pytest.mark.parametrize("command,extra", ID_SUBCOMMANDS)
@pytest.mark.parametrize("flag", ["--id", "--email-id"])
def test_both_id_spellings_parse(command, extra, flag):
    args = build_parser().parse_args(["email", command, "--account", "me@example.com", flag, "MSG-ID", *extra])
    assert args.email_id == "MSG-ID"
