"""The stored config: connected, selected, on and off, and a switch that loses nothing."""

import pathlib as pl

import pytest
import voice.config as vc
from voice.settings import SettingValue


def test_connect_stores_the_entry_selects_the_provider_and_turns_stt_and_tts_on(tmp_path: pl.Path) -> None:
    vc.connect(tmp_path, "stt", "deepgram", {"api_key": "dg"})
    config = vc.connect(tmp_path, "tts", "elevenlabs", {"api_key": "el"})

    assert vc.provider_name(config["stt"]) == "deepgram"
    assert vc.is_enabled(config["stt"]) is True
    assert vc.provider_creds(config["tts"], "elevenlabs") == {"api_key": "el"}
    assert vc.is_enabled(config["tts"]) is True


def test_connect_turns_the_judge_on(tmp_path: pl.Path) -> None:
    config = vc.connect(tmp_path, "judge", "typesafe", {"api_key": "k"})

    assert vc.provider_name(config["judge"]) == "typesafe"
    assert vc.is_enabled(config["judge"]) is True


def test_a_provider_with_no_key_is_connected_by_an_empty_entry(tmp_path: pl.Path) -> None:
    config = vc.connect(tmp_path, "stt", "local", {})

    assert vc.connected(config["stt"]) == ["local"]
    assert vc.provider_creds(config["stt"], "local") == {}


def test_use_selects_a_connected_provider_and_refuses_one_that_is_not(tmp_path: pl.Path) -> None:
    vc.connect(tmp_path, "stt", "deepgram", {"api_key": "dg"})
    vc.connect(tmp_path, "stt", "elevenlabs", {"api_key": "el"})

    assert vc.provider_name(vc.use(tmp_path, "stt", "deepgram")["stt"]) == "deepgram"
    with pytest.raises(ValueError, match="not connected"):
        vc.use(tmp_path, "stt", "whisper")


def test_the_settings_and_the_key_of_each_provider_are_the_same_after_two_switches(tmp_path: pl.Path) -> None:
    vc.connect(tmp_path, "stt", "deepgram", {"api_key": "dg"})
    vc.set_setting(tmp_path, "stt", "eot_threshold", 0.7)
    vc.add_keyterm(tmp_path, "Roscioli")
    vc.connect(tmp_path, "stt", "elevenlabs", {"api_key": "el"})
    vc.set_setting(tmp_path, "stt", "vad_silence_threshold_secs", 1.2)

    vc.use(tmp_path, "stt", "deepgram")
    entry = vc.use(tmp_path, "stt", "elevenlabs")["stt"]

    assert entry["eot_threshold"] == 0.7
    assert entry["vad_silence_threshold_secs"] == 1.2
    assert vc.keyterms(entry) == ["Roscioli"]
    assert vc.provider_creds(entry, "deepgram") == {"api_key": "dg"}
    assert vc.provider_creds(entry, "elevenlabs") == {"api_key": "el"}


def test_disconnect_of_the_selected_provider_selects_the_next_one_in_name_order(tmp_path: pl.Path) -> None:
    vc.connect(tmp_path, "stt", "whisper", {})
    vc.connect(tmp_path, "stt", "elevenlabs", {"api_key": "el"})
    vc.connect(tmp_path, "stt", "deepgram", {"api_key": "dg"})

    entry = vc.disconnect(tmp_path, "stt", "deepgram")["stt"]

    assert vc.provider_name(entry) == "elevenlabs"
    assert vc.connected(entry) == ["elevenlabs", "whisper"]
    assert vc.is_enabled(entry) is True


def test_disconnect_of_a_provider_that_is_not_selected_keeps_the_selection(tmp_path: pl.Path) -> None:
    vc.connect(tmp_path, "stt", "elevenlabs", {"api_key": "el"})
    vc.connect(tmp_path, "stt", "deepgram", {"api_key": "dg"})

    assert vc.provider_name(vc.disconnect(tmp_path, "stt", "elevenlabs")["stt"]) == "deepgram"


def test_a_role_with_no_provider_left_is_off_and_keeps_its_settings(tmp_path: pl.Path) -> None:
    vc.connect(tmp_path, "stt", "deepgram", {"api_key": "dg"})
    vc.add_keyterm(tmp_path, "Roscioli")

    entry = vc.disconnect(tmp_path, "stt", "deepgram")["stt"]

    assert vc.provider_name(entry) is None
    assert vc.is_enabled(entry) is False
    assert vc.keyterms(entry) == ["Roscioli"]


def test_on_fails_for_a_role_with_no_selected_provider_and_off_keeps_the_keys(tmp_path: pl.Path) -> None:
    with pytest.raises(ValueError, match="no selected provider"):
        vc.set_enabled(tmp_path, "judge", True)

    vc.connect(tmp_path, "judge", "typesafe", {"api_key": "k"})
    assert vc.is_enabled(vc.set_enabled(tmp_path, "judge", True)["judge"]) is True
    entry = vc.set_enabled(tmp_path, "judge", False)["judge"]
    assert vc.is_enabled(entry) is False
    assert vc.provider_creds(entry, "typesafe") == {"api_key": "k"}


def test_a_behavior_is_stored_in_its_own_entry(tmp_path: pl.Path) -> None:
    config = vc.set_setting(tmp_path, "behavior", "barge_in", False)

    assert config["behavior"] == {"barge_in": False}
    assert config["stt"] == {}


def test_a_client_keeps_its_own_behavior_over_the_shared_value(tmp_path: pl.Path) -> None:
    vc.set_setting(tmp_path, "behavior", "barge_in", True)
    vc.set_setting(tmp_path, "behavior", "wake_word", True)
    stored = vc.set_client_behavior(tmp_path, "whatsapp-call", "barge_in", False)["behavior"]

    assert vc.client_behavior(stored, "whatsapp-call") == {"barge_in": False, "wake_word": True}
    assert vc.client_behavior(stored, "web") == {"barge_in": True, "wake_word": True}
    assert vc.client_behavior(stored, None) == {"barge_in": True, "wake_word": True}


def test_a_client_with_no_value_of_its_own_follows_the_shared_value_again(tmp_path: pl.Path) -> None:
    vc.set_client_behavior(tmp_path, "web", "barge_in", False)
    vc.set_client_behavior(tmp_path, "web", "wake_word", True)
    vc.set_client_behavior(tmp_path, "web", "barge_in", None)
    stored = vc.set_client_behavior(tmp_path, "mobile", "wake_word", True)["behavior"]

    assert vc.client_values(stored) == {"web": {"wake_word": True}, "mobile": {"wake_word": True}}
    stored = vc.set_client_behavior(tmp_path, "web", "wake_word", None)["behavior"]
    assert vc.client_values(stored) == {"mobile": {"wake_word": True}}


@pytest.mark.parametrize("clients", [["web"], {"web": "off"}, "web"])
def test_client_values_that_are_not_a_map_read_as_none(clients: SettingValue) -> None:
    assert vc.client_values({"barge_in": True, "clients": clients}) == {}


def test_a_custom_voice_belongs_to_the_selected_tts_provider(tmp_path: pl.Path) -> None:
    vc.connect(tmp_path, "tts", "elevenlabs", {"api_key": "el"})
    vc.add_custom_voice(tmp_path, "v1", "Mine")
    vc.connect(tmp_path, "tts", "deepgram", {"api_key": "dg"})
    entry = vc.add_custom_voice(tmp_path, "aura-2-new-en", "New", "a new voice")["tts"]

    assert [v["id"] for v in vc.provider_voices(entry, "elevenlabs")] == ["v1"]
    assert vc.provider_voices(entry, "deepgram") == [
        {"provider": "deepgram", "id": "aura-2-new-en", "name": "New", "description": "a new voice"}
    ]
    assert vc.provider_voices(vc.remove_custom_voice(tmp_path, "v1")["tts"], "elevenlabs") == []


def test_an_unreadable_file_reads_as_no_config(tmp_path: pl.Path) -> None:
    vc.config_path(tmp_path).write_text("{not json")

    assert vc.load(tmp_path) == {"stt": {}, "tts": {}, "judge": {}, "behavior": {}}


def test_a_provider_sees_its_settings_and_never_a_key() -> None:
    entry: vc.Domain = {
        "provider": "deepgram",
        "credentials": {"deepgram": {"api_key": "dg"}, "elevenlabs": {"api_key": "el"}},
        "enabled": True,
        "eot_threshold": 0.7,
        "keyterms": ["Roscioli"],
    }

    assert vc.provider_settings(entry) == {"eot_threshold": 0.7, "keyterms": ["Roscioli"]}
