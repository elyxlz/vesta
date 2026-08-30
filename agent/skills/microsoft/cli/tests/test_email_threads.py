"""`email threads`: which conversations are quiet, and on whose side.

The failure this guards against is subtle. A mailbox check that only asks "has anything new
arrived?" confirms an absence and says nothing about the content already sitting in a thread, so a
conversation reads as quiet while its last message is a question waiting on an answer.
"""

from __future__ import annotations

import pytest
from microsoft_cli import email

ME = "user@example.com"


def _msg(convo: str, sender: str, when: str, subject: str = "s") -> dict:
    return {
        "conversationId": convo,
        "subject": subject,
        "receivedDateTime": when,
        "from": {"emailAddress": {"address": sender}},
    }


@pytest.fixture
def run(monkeypatch, tmp_path):
    """Drive stalled_threads with a scripted mailbox instead of Graph."""

    def _run(inbox, sent, *, days=4, scan=500, accepted=None):
        def fake_list(config, client, *, account_email, folder, limit, since):
            return list(inbox if folder == "inbox" else sent)

        monkeypatch.setattr(email, "list_emails", fake_list)

        class Cfg:
            data_dir = tmp_path

        if accepted is not None:
            (tmp_path / "threads-accepted.txt").write_text(accepted)
        return email.stalled_threads(Cfg(), None, account_email=ME, days=days, scan=scan)

    return _run


def test_reports_which_side_is_quiet(run):
    convo = "c1"
    out = run(
        inbox=[_msg(convo, "them@corp.com", "2020-01-01T09:00:00+00:00")],
        sent=[_msg(convo, ME, "2020-01-01T10:00:00+00:00")],
    )
    assert len(out["stalled"]) == 1
    assert out["stalled"][0]["waiting_on"] == "them"
    assert out["stalled"][0]["counterparts"] == ["them@corp.com"]


def test_last_word_theirs_waits_on_the_user(run):
    convo = "c2"
    out = run(
        inbox=[_msg(convo, "them@corp.com", "2020-01-02T10:00:00+00:00")],
        sent=[_msg(convo, ME, "2020-01-01T10:00:00+00:00")],
    )
    assert out["stalled"][0]["waiting_on"] == "the user"


def test_broadcast_threads_are_excluded(run):
    """Correspondence is DERIVED: a thread the account never sent into is not correspondence.
    Deriving it is the point, because a list of important senders cannot see who is missing."""
    out = run(inbox=[_msg("news", "newsletter@corp.com", "2020-01-01T10:00:00+00:00")], sent=[])
    assert out["stalled"] == []
    assert out["threads_examined"] == 1


def test_recent_threads_are_not_stalled(run):
    """The healthy case. An empty result must still report that work was done, or 'nothing
    stalled' is indistinguishable from 'nothing checked'."""
    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat()
    out = run(inbox=[_msg("c3", "them@corp.com", now)], sent=[_msg("c3", ME, now)])
    assert out["stalled"] == []
    assert out["threads_examined"] == 1


def test_accepted_threads_are_demoted_not_hidden(run):
    """A decision already taken must stop shouting, or the report trains you to skim it. It must
    NOT vanish, or a wrong decision becomes invisible and can never be revisited."""
    convo = "c4"
    out = run(
        inbox=[_msg(convo, "them@corp.com", "2020-01-01T09:00:00+00:00")],
        sent=[_msg(convo, ME, "2020-01-01T10:00:00+00:00")],
        accepted=f"# comment\n\n{convo} closed out of band\n",
    )
    assert out["stalled"] == []
    assert len(out["accepted"]) == 1
    assert out["accepted"][0]["accepted_because"] == "closed out of band"
    assert out["accepted"][0]["conversationId"] == convo


def test_accepted_file_cannot_limit_scope(run):
    """The file holds decisions, never scope. An unlisted thread must still be examined and
    reported: if the file decided WHICH threads get looked at, a thread nobody listed would be
    silently out of scope and its absence would look exactly like a clean result."""
    out = run(
        inbox=[_msg("listed", "a@corp.com", "2020-01-01T09:00:00+00:00"), _msg("unlisted", "b@corp.com", "2020-01-01T09:00:00+00:00")],
        sent=[_msg("listed", ME, "2020-01-01T10:00:00+00:00"), _msg("unlisted", ME, "2020-01-01T10:00:00+00:00")],
        accepted="listed decided already\n",
    )
    assert [r["conversationId"] for r in out["stalled"]] == ["unlisted"]
    assert [r["conversationId"] for r in out["accepted"]] == ["listed"]
    assert out["threads_examined"] == 2


def test_total_folder_failure_raises_rather_than_reporting_calm(monkeypatch, tmp_path):
    """An empty list at exit 0 would be indistinguishable from a quiet mailbox, which is the one
    answer this must never give by accident."""

    def boom(*a, **k):
        raise RuntimeError("unreachable")

    monkeypatch.setattr(email, "list_emails", boom)

    class Cfg:
        data_dir = tmp_path

    with pytest.raises(RuntimeError, match="could not read any mail folder"):
        email.stalled_threads(Cfg(), None, account_email=ME)
