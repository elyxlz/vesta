"""Tests for the two publish-identity guards: the PreToolUse hook and the upstream scrub script.

Both resolve the identifiers they refuse to publish from the instance they run on, so every test
here builds a throwaway identity in tmp_path and points HOME and AGENT_DIR at it. Nothing in this
file may depend on the identity of the machine running the suite."""

import json
import pathlib as pl
import subprocess
import sys

import pytest

ROOT = pl.Path(__file__).resolve().parents[1]
HOOK = ROOT / "skills" / "upstream" / "scripts" / "guard-publish.py"
SCRUB = ROOT / "skills" / "upstream" / "scripts" / "scrub-check.sh"

OWNER = "Zephrine"
CONTACT_SLUG = "quilliam-vandersloot"
PUBLISH = "curl -X POST https://api.github.com/repos/o/r/issues/1/comments -d @{body}"

# Joined at run time rather than spelled out: a contact-shaped string sitting in the file is a
# finding when these guards are run over their own source, which is a thing worth being able to do.
PHONE = "+" + "447700900123"
EMAIL = "someone@" + "example.invalid"


@pytest.fixture
def box(tmp_path, monkeypatch):
    """A box with an owner and one contact, and no connection to the real machine."""
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent" / "MEMORY.md").write_text(f"## 4. The user\n- **Name**: {OWNER}\n")
    contacts = tmp_path / ".contacts"
    contacts.mkdir()
    (contacts / f"{CONTACT_SLUG}.md").write_text("# Quilliam Vandersloot\nRelationship: colleague\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("AGENT_DIR", str(tmp_path / "agent"))
    monkeypatch.delenv("VESTA_OWNER", raising=False)
    return tmp_path


def run_hook(payload, env_home):
    env = {"HOME": str(env_home), "AGENT_DIR": str(env_home / "agent"), "PATH": "/usr/bin:/bin"}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), env=env, capture_output=True, text=True, check=False)


def bash(command):
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def scrub(target, env_home, stdin=None):
    env = {"HOME": str(env_home), "AGENT_DIR": str(env_home / "agent"), "PATH": "/usr/bin:/bin"}
    args = ["sh", str(SCRUB)] + ([] if stdin is not None else [str(target)])
    return subprocess.run(args, input=stdin, env=env, capture_output=True, text=True, check=False)


# The hook.


def test_publishing_call_carrying_the_owner_name_is_denied(box):
    result = run_hook(bash(PUBLISH.replace("@{body}", f"'thanks {OWNER}'")), box)

    assert result.returncode == 2
    assert "DENIED" in result.stderr


def test_denial_names_the_kind_and_never_the_value(box):
    """The refusal is fed back to the model, so printing the match would republish it into context."""
    result = run_hook(bash(PUBLISH.replace("@{body}", f"'thanks {OWNER}'")), box)

    assert "a name" in result.stderr
    assert OWNER.lower() not in result.stderr.lower()


def test_a_contact_name_counts_as_the_owners_identity(box):
    result = run_hook(bash(PUBLISH.replace("@{body}", "'reviewed with Vandersloot'")), box)

    assert result.returncode == 2


def test_identifier_in_a_referenced_file_is_denied(box):
    body = box / "body.md"
    body.write_text(f"Reported by {OWNER}, who hit this on a fresh box.\n")

    result = run_hook(bash(PUBLISH.format(body=body)), box)

    assert result.returncode == 2
    assert str(body) in result.stderr


def test_a_clean_publishing_call_is_allowed(box):
    result = run_hook(bash(PUBLISH.replace("@{body}", "'the retry loop never resets its backoff'")), box)

    assert result.returncode == 0
    assert result.stderr == ""


def test_reading_a_public_host_is_not_publishing(box):
    result = run_hook(bash(f"curl https://api.github.com/repos/o/r/issues?creator={OWNER}"), box)

    assert result.returncode == 0


def test_a_private_destination_is_out_of_scope(box):
    result = run_hook(bash(f"curl -X POST https://internal.example/notes -d 'from {OWNER}'"), box)

    assert result.returncode == 0


def test_non_bash_tools_are_out_of_scope(box):
    result = run_hook({"tool_name": "Write", "tool_input": {"content": OWNER}}, box)

    assert result.returncode == 0


def test_a_binary_on_the_command_line_is_not_a_message_body(box):
    """An interpreter path is a path like any other; decoded as text it matches the address
    pattern, and denying over that would make the guard fire on ordinary publishing calls."""
    binary = box / "helper"
    binary.write_bytes(b"\x7fELF\x00\x00 " + EMAIL.encode() + b" \x00 " + PHONE.encode() + b"\x00")

    result = run_hook(bash(f"{binary} && " + PUBLISH.replace("@{body}", "'clean text'")), box)

    assert result.returncode == 0


def test_malformed_payload_fails_open(box):
    env = {"HOME": str(box), "AGENT_DIR": str(box / "agent"), "PATH": "/usr/bin:/bin"}
    result = subprocess.run([sys.executable, str(HOOK)], input="not json", env=env, capture_output=True, text=True, check=False)

    assert result.returncode == 0


def test_an_unidentified_box_still_catches_contact_shaped_strings(tmp_path, monkeypatch):
    """Before a box knows whose it is, no name resolves; the pattern half must still hold."""
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent" / "MEMORY.md").write_text("- **Name**: [Unknown]\n")

    result = run_hook(bash(PUBLISH.replace("@{body}", f"'reach me on {PHONE}'")), tmp_path)

    assert result.returncode == 2
    assert "a phone number" in result.stderr


def test_heartbeat_records_a_harness_invocation(box):
    run_hook({"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {}}, box)

    assert (box / "agent" / "data" / "guard-publish.fired").is_file()


def test_a_hand_run_does_not_stamp_the_heartbeat(box):
    """A stamp written by a manual test would launder itself into evidence of live firing."""
    run_hook(bash("echo hello"), box)

    assert not (box / "agent" / "data" / "guard-publish.fired").exists()


# The scrub script.


def test_scrub_reports_the_owner_name(box):
    draft = box / "draft.md"
    draft.write_text(f"Suggested by {OWNER} after the third retry.\n")

    result = scrub(draft, box)

    assert result.returncode == 1
    assert "HIT" in result.stdout and "name" in result.stdout


def test_scrub_splits_a_hyphenated_contact_slug(box):
    """Half a two-part slug identifies the user as well as the whole of it."""
    draft = box / "draft.md"
    draft.write_text("Vandersloot confirmed the repro.\n")

    result = scrub(draft, box)

    assert result.returncode == 1


def test_scrub_reports_contact_shaped_strings(box):
    draft = box / "draft.md"
    draft.write_text(f"ping me on {PHONE} or {EMAIL}\n")

    result = scrub(draft, box)

    assert result.returncode == 1
    assert "phone" in result.stdout and "email" in result.stdout


def test_scrub_passes_clean_text_and_says_how_many_names_it_checked(box):
    draft = box / "draft.md"
    draft.write_text("The retry loop never resets its backoff, so the second failure waits forever.\n")

    result = scrub(draft, box)

    assert result.returncode == 0
    assert "name(s) checked" in result.stdout


def test_scrub_reads_stdin(box):
    result = scrub(None, box, stdin=f"a note from {OWNER}\n")

    assert result.returncode == 1


def test_scrub_refuses_to_pass_when_no_name_resolves(tmp_path):
    """A scrubber that knows no identifiers clears every text handed to it, which reads as
    protection forever. Say the name check was vacuous instead of passing."""
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent" / "MEMORY.md").write_text("- **Name**: [Unknown]\n")
    draft = tmp_path / "draft.md"
    draft.write_text("nothing identifying here\n")

    result = scrub(draft, tmp_path)

    assert result.returncode == 2
    assert "not a clean result" in result.stderr.lower()


def test_scrub_reports_a_missing_file_as_unchecked(box):
    result = scrub(box / "nope.md", box)

    assert result.returncode == 2
    assert "not a clean result" in result.stderr.lower()


def test_scrub_never_edits_the_file_it_checks(box):
    draft = box / "draft.md"
    original = f"Suggested by {OWNER}.\n"
    draft.write_text(original)

    scrub(draft, box)

    assert draft.read_text() == original
