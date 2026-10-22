"""Turn decisions: one case for each row of the table, with a fixed clock and fixed verdicts.

The clock is a number the test passes in. `HOLD` is the time after a pause at which a segment
that is still open takes the floor.
"""

import pytest
from voice.engine import turns
from voice.engine.turns import TurnState
from voice.providers.base import Verdict

HOLD = turns.HOLD_WAIT_MS / 1000

AGENT: Verdict = {"said_to": "agent", "wants_stop": None}
AGENT_STOP: Verdict = {"said_to": "agent", "wants_stop": True}
AGENT_BACKCHANNEL: Verdict = {"said_to": "agent", "wants_stop": False}
ECHO: Verdict = {"said_to": "echo", "wants_stop": False}
OTHER: Verdict = {"said_to": "other_person", "wants_stop": None}
NOISE: Verdict = {"said_to": "not_speech", "wants_stop": None}

IDLE = TurnState()
IN_TURN = TurnState(phase="user_turn", segment_seen=True)
PAUSED = TurnState(phase="paused", paused_at=10.0, segment_seen=True)

TURN_START = {"type": "turn_start"}
PAUSE = {"type": "pause_playback"}
RESUME = {"type": "resume_playback"}
STOP = {"type": "stop_now"}


def live(text: str = "hello") -> turns.Live:
    return {"kind": "live", "text": text}


def judged(verdict: Verdict | None, text: str = "hello") -> turns.Judged:
    return {"kind": "judged", "text": text, "verdict": verdict}


def committed(verdict: Verdict | None, text: str = "hello") -> turns.Committed:
    return {"kind": "committed", "text": text, "verdict": verdict}


def turn_end(text: str = "hello") -> dict[str, str]:
    return {"type": "turn_end", "text": text}


def ignored(kind: str, text: str = "hello") -> dict[str, str]:
    return {"type": "ignored", "text": text, "kind": kind}


def dropped(kind: str | None, text: str = "hello") -> dict[str, str | None]:
    return {"type": "turn_dropped", "text": text, "kind": kind}


# (name, state, event, speaking, barge_in, now, phase after, actions)
ROWS = [
    ("listening: text said to the agent starts a turn", IDLE, judged(AGENT), False, True, 0.0, "user_turn", [TURN_START]),
    ("listening: with no verdict the first live text starts a turn", IDLE, judged(None), False, True, 0.0, "user_turn", [TURN_START]),
    ("listening: text for another person starts no turn", IDLE, judged(OTHER), False, True, 0.0, "idle", []),
    ("listening: live text alone decides nothing", IDLE, live(), False, True, 0.0, "idle", []),
    ("listening: committed text that started no turn is ignored", IDLE, committed(OTHER), False, True, 0.0, "idle", [ignored("other_person")]),
    ("listening: committed noise is ignored as not speech", IDLE, committed(NOISE), False, True, 0.0, "idle", [ignored("not_speech")]),
    (
        "listening: text that only arrives at the commit is a whole turn",
        IDLE,
        committed(AGENT),
        False,
        True,
        0.0,
        "idle",
        [TURN_START, turn_end()],
    ),
    ("listening: an empty commit sends nothing", IDLE, committed(None, ""), False, True, 0.0, "idle", []),
    ("user turn: committed text said to the agent ends the turn", IN_TURN, committed(AGENT), False, True, 0.0, "idle", [turn_end()]),
    ("user turn: with no verdict the committed text goes to the agent", IN_TURN, committed(None), False, True, 0.0, "idle", [turn_end()]),
    (
        "user turn: committed text for another person drops the turn",
        IN_TURN,
        committed(OTHER),
        False,
        True,
        0.0,
        "idle",
        [dropped("other_person")],
    ),
    ("user turn: an empty commit drops the turn with no kind", IN_TURN, committed(None, ""), False, True, 0.0, "idle", [dropped(None, "")]),
    ("user turn: more live text changes nothing", IN_TURN, live("hello there"), False, True, 0.0, "user_turn", []),
    ("speaking: the first live text pauses the reply", IDLE, live(), True, True, 10.0, "paused", [PAUSE]),
    ("speaking: with barge-in not allowed, live text does not pause", IDLE, live(), True, False, 10.0, "idle", []),
    ("speaking: with barge-in not allowed, a turn still starts", IDLE, judged(None), True, False, 10.0, "user_turn", [TURN_START]),
    ("paused: the user wants a stop", PAUSED, judged(AGENT_STOP), True, True, 10.2, "user_turn", [STOP, TURN_START]),
    ("paused: a backchannel resumes the reply", PAUSED, judged(AGENT_BACKCHANNEL), True, True, 10.2, "idle", [RESUME, ignored("backchannel")]),
    ("paused: an echo resumes the reply", PAUSED, judged(ECHO), True, True, 10.2, "idle", [RESUME, ignored("echo")]),
    ("paused: another person resumes the reply", PAUSED, judged(OTHER), True, True, 10.2, "idle", [RESUME, ignored("other_person")]),
    ("paused: noise resumes the reply", PAUSED, judged(NOISE), True, True, 10.2, "idle", [RESUME, ignored("not_speech")]),
    ("paused: no verdict waits for the time rules", PAUSED, judged(None), True, True, 10.2, "paused", []),
    (
        "paused: with no verdict a commit before the hold time was a backchannel",
        PAUSED,
        committed(None),
        True,
        True,
        10.6,
        "idle",
        [RESUME, ignored("backchannel")],
    ),
    (
        "paused: with no verdict an open segment takes the floor at the hold time",
        PAUSED,
        {"kind": "tick"},
        True,
        True,
        10.0 + HOLD,
        "user_turn",
        [STOP, TURN_START],
    ),
    ("paused: a tick before the hold time changes nothing", PAUSED, {"kind": "tick"}, True, True, 10.0 + HOLD / 2, "paused", []),
    (
        "paused: a commit that wants a stop is a whole turn",
        PAUSED,
        committed(AGENT_STOP),
        True,
        True,
        10.3,
        "idle",
        [STOP, TURN_START, turn_end()],
    ),
    (
        "paused: a commit for another person resumes the reply",
        PAUSED,
        committed(OTHER),
        True,
        True,
        10.3,
        "idle",
        [RESUME, ignored("other_person")],
    ),
    ("paused: an empty commit only resumes the reply", PAUSED, committed(None, ""), True, True, 10.3, "idle", [RESUME]),
    ("any: the user stops the reply on the device", IDLE, {"kind": "stopped_by_user"}, True, True, 0.0, "idle", [STOP]),
    ("paused: the user stops the reply on the device", PAUSED, {"kind": "stopped_by_user"}, True, True, 10.1, "idle", [STOP]),
    ("user turn: the user stops the reply on the device", IN_TURN, {"kind": "stopped_by_user"}, True, True, 0.0, "user_turn", [STOP]),
    ("idle: a tick with nothing paused changes nothing", IDLE, {"kind": "tick"}, True, True, 99.0, "idle", []),
    ("idle: the wake phrase over a reply stops it and opens no turn", IDLE, {"kind": "wake"}, True, True, 0.0, "idle", [STOP]),
    (
        "idle: the wake phrase over a reply with words already heard takes the floor",
        TurnState(segment_seen=True),
        {"kind": "wake"},
        True,
        True,
        0.0,
        "user_turn",
        [STOP, TURN_START],
    ),
    ("paused: the wake phrase takes the floor with no hold", PAUSED, {"kind": "wake"}, True, True, 10.1, "user_turn", [STOP, TURN_START]),
    ("idle: the wake phrase with no reply waits for the words", IDLE, {"kind": "wake"}, False, True, 0.0, "idle", []),
    ("idle: the wake phrase stops no reply when barge-in is off", IDLE, {"kind": "wake"}, True, False, 0.0, "idle", []),
    ("user turn: the wake phrase changes nothing", IN_TURN, {"kind": "wake"}, True, True, 0.0, "user_turn", []),
]


@pytest.mark.parametrize(("name", "state", "event", "speaking", "barge_in", "now", "phase", "actions"), ROWS, ids=[row[0] for row in ROWS])
def test_one_event_gives_the_actions_of_its_row(
    name: str, state: TurnState, event: turns.TurnEvent, speaking: bool, barge_in: bool, now: float, phase: str, actions: list[dict[str, str]]
) -> None:
    after, sent = turns.step(state, event, speaking=speaking, barge_in=barge_in, now=now)

    assert sent == actions
    assert after.phase == phase


def _run(events: list[tuple[turns.TurnEvent, float]], *, speaking: bool, barge_in: bool = True) -> tuple[TurnState, list[dict[str, str]]]:
    state, sent = TurnState(), []
    for event, now in events:
        state, actions = turns.step(state, event, speaking=speaking, barge_in=barge_in, now=now)
        sent += actions
    return state, sent


def test_with_no_judge_a_short_backchannel_lets_the_reply_continue() -> None:
    _state, sent = _run([(live("mhm"), 10.0), (judged(None, "mhm"), 10.0), (committed(None, "mhm"), 10.6)], speaking=True)

    assert sent == [PAUSE, RESUME, ignored("backchannel", "mhm")]


def test_with_no_judge_speech_that_continues_takes_the_floor_and_then_ends_as_a_turn() -> None:
    events: list[tuple[turns.TurnEvent, float]] = [
        (live("wait"), 10.0),
        (judged(None, "wait"), 10.0),
        (live("wait I meant Milan"), 10.7),
        (judged(None, "wait I meant Milan"), 10.7),
        ({"kind": "tick"}, 10.0 + HOLD),
        (committed(None, "wait I meant Milan not Rome"), 12.0),
    ]

    state, sent = _run(events, speaking=True)

    assert sent == [PAUSE, STOP, TURN_START, turn_end("wait I meant Milan not Rome")]
    assert state == TurnState()


def test_only_the_first_live_text_of_a_segment_pauses_the_reply() -> None:
    _state, sent = _run([(live("so"), 10.0), (live("so I"), 10.2), (live("so I was"), 10.4)], speaking=True)

    assert sent == [PAUSE]


def test_a_segment_that_was_answered_with_a_resume_sends_nothing_more_at_its_commit() -> None:
    events: list[tuple[turns.TurnEvent, float]] = [
        (live("yeah"), 10.0),
        (judged(AGENT_BACKCHANNEL, "yeah"), 10.2),
        (live("yeah okay"), 10.4),
        (judged(AGENT_BACKCHANNEL, "yeah okay"), 10.6),
        (committed(AGENT_BACKCHANNEL, "yeah okay"), 11.0),
    ]

    _state, sent = _run(events, speaking=True)

    assert sent == [PAUSE, RESUME, ignored("backchannel", "yeah")]


def test_after_a_resume_a_clear_stop_in_the_same_segment_still_takes_the_floor() -> None:
    events: list[tuple[turns.TurnEvent, float]] = [
        (live("yeah"), 10.0),
        (judged(AGENT_BACKCHANNEL, "yeah"), 10.2),
        (live("yeah but stop"), 10.6),
        (judged(AGENT_STOP, "yeah but stop"), 10.8),
    ]

    state, sent = _run(events, speaking=True)

    assert sent == [PAUSE, RESUME, ignored("backchannel", "yeah"), STOP, TURN_START]
    assert state.phase == "user_turn"


def test_a_new_segment_can_pause_the_reply_again() -> None:
    events: list[tuple[turns.TurnEvent, float]] = [
        (live("mhm"), 10.0),
        (committed(None, "mhm"), 10.5),
        (live("stop"), 12.0),
    ]

    _state, sent = _run(events, speaking=True)

    assert sent == [PAUSE, RESUME, ignored("backchannel", "mhm"), PAUSE]


def test_the_whole_listening_flow_with_no_judge() -> None:
    events: list[tuple[turns.TurnEvent, float]] = [
        (live("what"), 0.0),
        (judged(None, "what"), 0.0),
        (live("what is the weather"), 0.4),
        (judged(None, "what is the weather"), 0.4),
        (committed(None, "What is the weather?"), 1.0),
    ]

    _state, sent = _run(events, speaking=False)

    assert sent == [TURN_START, turn_end("What is the weather?")]


@pytest.mark.parametrize(
    ("state", "speaking", "value"),
    [
        (IDLE, False, "listening"),
        (IDLE, True, "agent_speaking"),
        (IN_TURN, False, "user_turn"),
        (IN_TURN, True, "user_turn"),
        (PAUSED, True, "agent_paused"),
    ],
)
def test_the_state_on_the_wire(state: TurnState, speaking: bool, value: str) -> None:
    assert turns.wire_state(state, speaking) == value
