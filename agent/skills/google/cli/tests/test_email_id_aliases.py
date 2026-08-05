"""`email attachment` accepts both --id and --email-id, matching the other id-taking subcommands.

Either spelling parses, so a wrong guess cannot exit 2 with a usage error. That matters because
these commands run with stderr suppressed, where a usage error looks exactly like a command that
ran and found nothing, turning a flag mismatch into a silent false negative.
"""

import pytest
from google_cli import cli


@pytest.mark.parametrize("flag", ["--id", "--email-id"])
def test_attachment_accepts_both_id_spellings(flag):
    argv = ["email", "attachment", flag, "MSG-ID", "--attachment-id", "ATT-ID", "--save-path", "/tmp/f.pdf"]
    args = cli._build_parser().parse_args(argv)
    assert args.email_id == "MSG-ID"
