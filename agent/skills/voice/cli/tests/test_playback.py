"""Playback state: derived from the `speak` frames and the reports of the client's speaker."""

from voice.engine import playback
from voice.engine.playback import Play, PlaybackState

A = Play(id="a", text="first reply", token="ta")
B = Play(id="b", text="second reply", token="tb")
C = Play(id="c", text="third reply", token="tc")


def _sent(*plays: Play) -> PlaybackState:
    state = PlaybackState()
    for play in plays:
        state, _to_send = playback.speak(state, play, hold=False)
    return state


def test_plays_are_sent_in_speak_order() -> None:
    state, first = playback.speak(PlaybackState(), A, hold=False)
    state, second = playback.speak(state, B, hold=False)

    assert (first, second) == ((A,), (B,))
    assert [play.id for play in state.sent] == ["a", "b"]


def test_plays_are_held_during_the_users_turn_and_sent_after_it_in_order() -> None:
    state, during_a = playback.speak(PlaybackState(), A, hold=True)
    state, during_b = playback.speak(state, B, hold=True)

    state, released = playback.release(state)

    assert (during_a, during_b) == ((), ())
    assert released == (A, B)
    assert state.held == ()
    assert [play.id for play in state.sent] == ["a", "b"]


def test_speaking_begins_on_a_started_report_and_ends_when_every_sent_play_is_over() -> None:
    state = _sent(A, B)
    assert playback.speaking(state) is False

    state, _ended = playback.report(state, "a", "started")
    assert playback.speaking(state) is True

    state, _ended = playback.report(state, "a", "finished")
    assert playback.speaking(state) is True

    state, _ended = playback.report(state, "b", "started")
    state, _ended = playback.report(state, "b", "finished")
    assert playback.speaking(state) is False
    assert state.sent == ()


def test_a_failed_play_counts_as_over() -> None:
    state, _ended = playback.report(_sent(A), "a", "started")

    state, ended = playback.report(state, "a", "failed")

    assert playback.speaking(state) is False
    assert ended is not None
    assert ended.id == "a"


def test_the_play_that_runs_now_is_the_one_that_started_and_is_not_over() -> None:
    state, _ended = playback.report(_sent(A, B), "a", "started")
    assert playback.saying(state) == Play(id="a", text="first reply", token="ta", started=True)

    state, _ended = playback.report(state, "a", "finished")
    assert playback.saying(state) is None


def test_a_stop_names_the_cut_play_and_drops_every_play_that_never_started() -> None:
    state, _ended = playback.report(_sent(A, B, C), "a", "started")

    stopped = playback.stop(state)

    assert stopped.cut is not None
    assert stopped.cut.id == "a"
    assert [play.id for play in stopped.dropped] == ["b", "c"]
    assert stopped.state.sent == ()


def test_a_stop_with_nothing_playing_cuts_nothing() -> None:
    stopped = playback.stop(_sent(A))

    assert stopped.cut is None
    assert [play.id for play in stopped.dropped] == ["a"]


def test_a_finished_play_is_neither_cut_nor_dropped() -> None:
    state, _ended = playback.report(_sent(A, B), "a", "started")
    state, _ended = playback.report(state, "a", "finished")
    state, _ended = playback.report(state, "b", "started")

    stopped = playback.stop(state)

    assert stopped.cut is not None
    assert stopped.cut.id == "b"
    assert stopped.dropped == ()


def test_a_stop_keeps_the_plays_that_wait_for_the_end_of_the_users_turn() -> None:
    state, _ended = playback.report(_sent(A), "a", "started")
    state, _none = playback.speak(state, B, hold=True)

    assert playback.stop(state).state.held == (B,)


def test_a_held_play_whose_synthesis_failed_is_forgotten() -> None:
    state, _none = playback.speak(PlaybackState(), A, hold=True)
    state, _none = playback.speak(state, B, hold=True)

    state, was_held = playback.drop_held(state, "ta")

    assert (state.held, was_held) == ((B,), True)
    assert playback.drop_held(state, "ta") == (state, False)


def test_two_plays_with_one_id_take_their_reports_in_order() -> None:
    again = Play(id="a", text="first reply", token="ta2")
    state = _sent(A, again)

    state, _ended = playback.report(state, "a", "started")
    state, _ended = playback.report(state, "a", "finished")
    state, _ended = playback.report(state, "a", "started")

    running = playback.saying(state)
    assert running is not None
    assert running.token == "ta2"


def test_a_report_names_the_play_it_ended_and_a_started_report_ends_none() -> None:
    state, ended = playback.report(_sent(A), "a", "started")
    assert ended is None

    state, ended = playback.report(state, "a", "finished")
    assert ended == Play(id="a", text="first reply", token="ta", started=True)
    assert playback.report(state, "a", "finished") == (state, None)
