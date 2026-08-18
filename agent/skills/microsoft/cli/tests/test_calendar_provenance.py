"""Events the agent created must be distinguishable from events the user committed to.

Without this, an entry the agent added from a passing tip reads back, days later, exactly like a
plan the user made, and any date arithmetic built on it inherits the invention. That is not
hypothetical: it is the failure this exists to prevent, and it recurred on two separate events
within two days on a live box, the second time producing a question put to the user twice with a
premise the agent had authored itself.

A body convention ("added by <agent>") cannot do this job: the default event list does not select
bodies, and nobody re-reads a body they wrote. `categories` is selected in both list modes and
renders in the user's own client, so the mark is visible to both sides.
"""

from microsoft_cli import format as fmt
from microsoft_cli.payloads import AGENT_EVENT_CATEGORY


def _event(subject: str, categories: list[str] | None = None) -> dict:
    return {
        "start": {"dateTime": "2026-08-29T00:00:00"},
        "end": {"dateTime": "2026-08-31T00:00:00"},
        "subject": subject,
        "location": {"displayName": "London"},
        "id": "AAA",
        **({"categories": categories} if categories is not None else {}),
    }


def test_an_agent_created_event_is_marked():
    out = fmt.format_calendar_event_list([_event("Habibi Funk", [AGENT_EVENT_CATEGORY])])
    assert f"[{AGENT_EVENT_CATEGORY}] Habibi Funk" in out


def test_a_user_event_is_left_alone():
    """The mark has to mean something, so it must not appear on everything."""
    out = fmt.format_calendar_event_list([_event("FIRST DAY at ElevenLabs", [])])
    assert "[vesta]" not in out
    assert "FIRST DAY at ElevenLabs" in out


def test_an_event_with_no_categories_key_is_not_marked_and_does_not_raise():
    """Older events, and any list mode that omits the field, must degrade to unmarked."""
    out = fmt.format_calendar_event_list([_event("Dentist")])
    assert "[vesta]" not in out
    assert "Dentist" in out


def test_other_categories_do_not_trigger_the_mark():
    out = fmt.format_calendar_event_list([_event("Team offsite", ["Work", "Travel"])])
    assert "[vesta]" not in out


def test_the_mark_survives_alongside_the_users_own_categories():
    out = fmt.format_calendar_event_list([_event("Padel", ["Sport", AGENT_EVENT_CATEGORY])])
    assert f"[{AGENT_EVENT_CATEGORY}] Padel" in out


def test_row_shape_is_unchanged_so_downstream_parsing_still_works():
    """Five tab-separated columns, marked or not."""
    marked = fmt.format_calendar_event_list([_event("A", [AGENT_EVENT_CATEGORY])])
    plain = fmt.format_calendar_event_list([_event("B", [])])
    assert len(marked.split("\t")) == len(plain.split("\t")) == 5


def test_agent_authored_recognises_events_that_predate_the_category() -> None:
    """The category only exists on events created after it shipped.

    Every older event is unstamped, and those are the ones that have had time to be forgotten and
    re-read as the user's own. Both cases below are real: a six-week-old block whose end date was
    taken for the user's travel plan, and a festival saved off an Instagram tip that was nearly
    cited as evidence of where he would be that weekend.
    """
    from microsoft_cli.format import agent_authored

    assert agent_authored({"body": {"content": "Sardinia leg. Added by vesta 30 Jul, dates known."}})
    assert agent_authored({"body": {"content": "Open-air funk weekender. Via Leila (IG). Tickets likely needed."}})


def test_agent_authored_does_not_claim_the_users_own_events() -> None:
    """A bare mention of the agent is not a tell, or an event ABOUT it would be read as BY it."""
    from microsoft_cli.format import agent_authored

    assert not agent_authored({"body": {"content": "Royal Festival Hall, doors 17:15"}})
    assert not agent_authored({"body": {"content": "call re vesta roadmap and vesta pricing"}})
    assert not agent_authored({"body": {"content": "tickets purchased, seats 4F/4G"}})
    assert not agent_authored({})
