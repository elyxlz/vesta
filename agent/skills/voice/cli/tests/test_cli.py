"""The `voice` command: one grammar, one line of JSON for each command, failures on stderr."""

import json
import pathlib as pl

import pytest
import voice.config as vc
from voice import cli, providers
from voice.providers import own
from voice.settings import JsonValue

from .fakes import FakeJudge, FakeStt, FakeTts

BEHAVIOR_DEFAULTS: dict[str, JsonValue] = {
    "barge_in": True,
    "wake_word": False,
    "wake_word_phrase": "hey aria",
    "wake_word_threshold": 0.5,
    "wake_word_follow_up_secs": 5,
    "wake_word_keep_phrase": False,
}


@pytest.fixture
def home(tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch) -> pl.Path:
    """A hermetic config dir, and a fake provider for each role: `keyed` needs a key, `local` needs none."""
    monkeypatch.setattr(cli, "_data_dir", lambda: tmp_path)
    for registry, fake in ((providers.STT, FakeStt), (providers.TTS, FakeTts), (providers.JUDGES, FakeJudge)):
        monkeypatch.setitem(registry, "keyed", fake(needs_key=True))
        monkeypatch.setitem(registry, "local", fake(needs_key=False))
    return tmp_path


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, JsonValue], str]:
    """Run one command. Returns its exit code, its one line of stdout as JSON, and its stderr."""
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert len(lines) <= 1, f"more than one line on stdout: {captured.out!r}"
    return code, json.loads(lines[0]) if lines else {}, captured.err


def failure(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    """Run one command that must fail. Returns the `error` of its one JSON line on stderr."""
    code, out, err = run(capsys, *argv)
    assert code != 0
    assert out == {}
    assert len(err.splitlines()) == 1
    return json.loads(err)["error"]


def test_bare_invocation_prints_usage_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 0
    assert "daemon" in capsys.readouterr().out


def test_help_flag_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])

    assert exc.value.code == 0


def test_a_command_that_does_not_exist_fails_with_one_json_line(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["set-key"])

    assert exc.value.code == 2
    assert "invalid choice" in json.loads(capsys.readouterr().err)["error"]


def test_status_shows_each_role_and_each_behavior_and_never_a_key(home: pl.Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(capsys, "stt", "connect", "keyed", "--key", "secret-key-value")

    code, status, _err = run(capsys, "status")

    assert code == 0
    assert status["stt"] == {
        "providers": ["deepgram", "elevenlabs", "keyed", "local"],
        "connected": ["keyed"],
        "selected": "keyed",
        "on": True,
        "settings": {"address": "http://127.0.0.1:9000"},
        "keyterms": [],
    }
    assert status["judge"] == {"providers": ["keyed", "local", "typesafe"], "connected": [], "selected": None, "on": False, "settings": {}}
    assert status["behavior"] == BEHAVIOR_DEFAULTS
    assert "secret-key-value" not in json.dumps(status)


def test_connect_checks_the_provider_stores_it_and_selects_it(home: pl.Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, status, _err = run(capsys, "tts", "connect", "keyed", "--key", "k")

    assert code == 0
    assert status["tts"]["selected"] == "keyed"
    assert status["tts"]["on"] is True
    assert vc.provider_creds(vc.load(home)["tts"], "keyed") == {"api_key": "k"}


def test_connect_turns_every_role_on(home: pl.Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(capsys, "stt", "connect", "local")
    run(capsys, "tts", "connect", "local")
    _code, status, _err = run(capsys, "judge", "connect", "local")

    assert (status["stt"]["on"], status["tts"]["on"], status["judge"]["on"]) == (True, True, True)


def test_connect_refuses_a_provider_that_fails_its_check_and_stores_nothing(
    home: pl.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(providers.STT, "keyed", FakeStt(needs_key=True, valid=False))

    assert failure(capsys, "stt", "connect", "keyed", "--key", "bad") == "keyed failed the stt check: the fake says no"
    assert vc.load(home)["stt"] == {}


def test_check_tests_a_provider_and_stores_nothing(home: pl.Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, answer, _err = run(capsys, "stt", "check", "keyed", "--key", "k")

    assert (code, answer) == (0, {"role": "stt", "provider": "keyed", "ok": True})
    assert vc.load(home)["stt"] == {}


def test_a_provider_with_no_key_connects_with_no_key(home: pl.Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, status, _err = run(capsys, "stt", "connect", "local")

    assert code == 0
    assert status["stt"]["connected"] == ["local"]
    assert vc.provider_creds(vc.load(home)["stt"], "local") == {}


def test_a_key_is_necessary_exactly_when_the_provider_needs_one(home: pl.Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert failure(capsys, "stt", "connect", "keyed") == "keyed needs a key: add --key <key>"
    assert failure(capsys, "stt", "connect", "local", "--key", "k") == "local takes no key: run the command with no --key"
    assert failure(capsys, "stt", "check", "keyed") == "keyed needs a key: add --key <key>"
    assert vc.load(home)["stt"] == {}


def test_a_provider_the_skill_does_not_know_is_refused_with_the_known_names(home: pl.Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert failure(capsys, "judge", "connect", "nobody") == "unknown judge provider: nobody (providers: keyed, local, typesafe)"


def test_use_switches_between_connected_providers_with_no_key(home: pl.Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(capsys, "stt", "connect", "keyed", "--key", "k")
    run(capsys, "stt", "connect", "local")

    _code, status, _err = run(capsys, "stt", "use", "keyed")

    assert status["stt"]["selected"] == "keyed"
    assert failure(capsys, "stt", "use", "deepgram") == "deepgram is not connected to stt; run `voice stt connect deepgram` first"


def test_disconnect_of_the_selected_provider_selects_the_next_one(home: pl.Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(capsys, "stt", "connect", "local")
    run(capsys, "stt", "connect", "keyed", "--key", "k")

    _code, status, _err = run(capsys, "stt", "disconnect", "keyed")

    assert (status["stt"]["selected"], status["stt"]["connected"]) == ("local", ["local"])


def test_on_fails_for_a_role_with_no_selected_provider_and_off_keeps_the_keys(home: pl.Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert failure(capsys, "judge", "on") == "judge has no selected provider; run `voice judge connect <provider>` first"

    run(capsys, "judge", "connect", "keyed", "--key", "k")
    assert run(capsys, "judge", "on")[1]["judge"]["on"] is True
    _code, status, _err = run(capsys, "judge", "off")
    assert (status["judge"]["on"], status["judge"]["connected"]) == (False, ["keyed"])


def test_set_stores_a_provider_setting_of_the_selected_provider(home: pl.Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(capsys, "stt", "connect", "local")

    _code, status, _err = run(capsys, "stt", "set", "address", "http://box:9100")

    assert status["stt"]["settings"] == {"address": "http://box:9100"}


def test_set_refuses_an_unknown_key_a_wrong_type_and_an_empty_text(home: pl.Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(capsys, "stt", "connect", "local")

    assert failure(capsys, "stt", "set", "eot_threshold", "0.7") == "unknown setting: eot_threshold (settings: address)"
    assert failure(capsys, "stt", "set", "address", " ") == "address must be text that is not empty"
    assert failure(capsys, "behavior", "set", "barge_in", "maybe") == "barge_in must be on or off, got 'maybe'"
    assert failure(capsys, "behavior", "set", "idle_ms", "5") == (
        "unknown setting: idle_ms (settings: barge_in, wake_word, wake_word_phrase, wake_word_threshold, "
        "wake_word_follow_up_secs, wake_word_keep_phrase)"
    )
    assert failure(capsys, "tts", "set", "fake_voice", "v-other") == "tts has no selected provider; run `voice tts connect <provider>` first"


def test_a_value_out_of_range_is_refused(tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "_data_dir", lambda: tmp_path)
    vc.connect(tmp_path, "stt", "deepgram", {"api_key": "k"})

    assert failure(capsys, "stt", "set", "eot_threshold", "0.2") == "eot_threshold must be at least 0.5, got '0.2'"
    assert run(capsys, "stt", "set", "eot_threshold", "0.7")[1]["stt"]["settings"]["eot_threshold"] == 0.7


def test_a_behavior_is_set_with_its_own_command(home: pl.Path, capsys: pytest.CaptureFixture[str]) -> None:
    _code, status, _err = run(capsys, "behavior", "set", "barge_in", "off")

    assert status["behavior"] == {**BEHAVIOR_DEFAULTS, "barge_in": False}


def test_a_client_gets_its_own_behavior_and_loses_it_with_unset(home: pl.Path, capsys: pytest.CaptureFixture[str]) -> None:
    _code, status, _err = run(capsys, "behavior", "set", "barge_in", "off", "--client", "whatsapp-call")

    assert status["behavior"] == BEHAVIOR_DEFAULTS
    assert status["client_behavior"] == {"whatsapp-call": {"barge_in": False}}
    assert run(capsys, "behavior", "unset", "barge_in", "--client", "whatsapp-call")[1]["client_behavior"] == {}
    assert failure(capsys, "behavior", "unset", "idle_ms", "--client", "web").startswith("unknown behavior: idle_ms")


def test_status_says_where_the_model_of_the_wake_phrase_is_and_if_it_is_there(home: pl.Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(capsys, "behavior", "set", "wake_word_phrase", "Hey, Vesta")
    model = home / "wake_words" / "hey_vesta.onnx"

    assert run(capsys, "status")[1]["wake_word_model"] == {"path": str(model), "found": False}
    model.parent.mkdir()
    model.write_bytes(b"onnx")
    assert run(capsys, "status")[1]["wake_word_model"] == {"path": str(model), "found": True}


def test_the_wake_word_is_switched_with_the_behavior_command(home: pl.Path, capsys: pytest.CaptureFixture[str]) -> None:
    _code, status, _err = run(capsys, "behavior", "set", "wake_word", "on")

    assert status["behavior"] == {**BEHAVIOR_DEFAULTS, "wake_word": True}
    assert failure(capsys, "behavior", "set", "wake_word_threshold", "1") == "wake_word_threshold must be at most 0.95, got '1'"


def test_voice_sets_the_voice_of_the_selected_provider_only(
    home: pl.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(providers.TTS, "keyed", FakeTts(needs_key=True, voice_setting="keyed_voice"))
    run(capsys, "tts", "connect", "local")
    run(capsys, "tts", "voice", "v-other")
    run(capsys, "tts", "connect", "keyed", "--key", "k")

    _code, status, _err = run(capsys, "tts", "voice", "v-other")
    entry = vc.load(home)["tts"]

    assert status["tts"]["settings"] == {"keyed_voice": "v-other"}
    assert (entry["fake_voice"], entry["keyed_voice"]) == ("v-other", "v-other")
    assert failure(capsys, "tts", "voice", "v-nobody") == "keyed_voice must be one of its options, got 'v-nobody'"


def test_the_voice_of_each_provider_is_the_same_after_two_switches(
    home: pl.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(providers.TTS, "keyed", FakeTts(needs_key=True, voice_setting="keyed_voice"))
    run(capsys, "tts", "connect", "local")
    run(capsys, "tts", "voice", "v-other")
    run(capsys, "tts", "connect", "keyed", "--key", "k")

    run(capsys, "tts", "use", "local")
    assert run(capsys, "status")[1]["tts"]["settings"] == {"fake_voice": "v-other"}
    assert run(capsys, "tts", "use", "keyed")[1]["tts"]["settings"] == {"keyed_voice": "v-default"}


def test_a_voice_the_user_added_can_be_selected(home: pl.Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(capsys, "tts", "connect", "local")
    _code, status, _err = run(capsys, "tts", "voices", "add", "v-mine", "--name", "Mine", "--description", "my own")

    assert status["tts"]["voices"] == [{"provider": "local", "id": "v-mine", "name": "Mine", "description": "my own"}]
    assert run(capsys, "tts", "voice", "v-mine")[1]["tts"]["settings"] == {"fake_voice": "v-mine"}
    assert run(capsys, "tts", "voices", "remove", "v-mine")[1]["tts"]["voices"] == []


def test_key_terms_are_edited_with_their_own_verbs(home: pl.Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(capsys, "stt", "connect", "local")
    run(capsys, "stt", "keyterms", "add", "Roscioli")
    assert run(capsys, "stt", "keyterms", "add", "Vesta")[1]["stt"]["keyterms"] == ["Roscioli", "Vesta"]
    assert run(capsys, "stt", "keyterms", "remove", "Roscioli")[1]["stt"]["keyterms"] == ["Vesta"]


def test_a_provider_of_this_box_is_in_the_registry_of_its_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(providers.STT, "whisper-local", FakeStt())

    assert "whisper-local" in providers.names("stt")
    assert providers.get("stt", "whisper-local") is providers.STT["whisper-local"]


def test_a_provider_name_used_two_times_fails_every_command_and_names_it(
    home: pl.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(own.STT, "deepgram", FakeStt())
    monkeypatch.setitem(own.JUDGES, "typesafe", FakeJudge())

    expected = "a provider name is used two times in providers/own.py (stt: deepgram; judge: typesafe); give it a new name"
    assert failure(capsys, "status") == expected
    assert failure(capsys, "tts", "on") == expected


def test_the_own_file_ships_with_three_empty_maps() -> None:
    assert (own.STT, own.TTS, own.JUDGES) == ({}, {}, {})
    assert providers.duplicate_names() == []


def test_daemon_subcommands_are_registered(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["daemon", "--help"])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    for want in ("start", "stop", "restart", "status"):
        assert want in out
