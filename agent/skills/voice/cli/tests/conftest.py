"""A fake provider for each role, connected in the test's own data directory."""

import pathlib as pl

import pytest
import voice.config as vc
from voice import providers
from voice.engine import detector, wake

from .fakes import FakeDetector, FakeJudge, FakeStt, FakeTts


@pytest.fixture
def stt(monkeypatch: pytest.MonkeyPatch, tmp_path: pl.Path) -> FakeStt:
    fake = FakeStt()
    monkeypatch.setitem(providers.STT, "fake", fake)
    vc.connect(tmp_path, "stt", "fake", {})
    return fake


@pytest.fixture
def tts(monkeypatch: pytest.MonkeyPatch, tmp_path: pl.Path) -> FakeTts:
    fake = FakeTts()
    monkeypatch.setitem(providers.TTS, "fake", fake)
    vc.connect(tmp_path, "tts", "fake", {})
    return fake


@pytest.fixture
def judge(monkeypatch: pytest.MonkeyPatch, tmp_path: pl.Path) -> FakeJudge:
    fake = FakeJudge()
    monkeypatch.setitem(providers.JUDGES, "fake", fake)
    vc.connect(tmp_path, "judge", "fake", {})
    vc.set_enabled(tmp_path, "judge", True)
    return fake


@pytest.fixture
def wake_model(monkeypatch: pytest.MonkeyPatch, tmp_path: pl.Path) -> FakeDetector:
    """A model file for the default phrase, which loads as the fake detector. A phrase with no
    file fails to load as a real one does."""
    fake = FakeDetector()

    def load(path: pl.Path) -> FakeDetector:
        if not path.is_file():
            raise detector.DetectorError(f"no wake word model at {path}")
        return fake

    monkeypatch.setattr(detector, "load", load)
    model = wake.model_path(tmp_path, "hey aria")
    model.parent.mkdir(parents=True)
    model.write_bytes(b"onnx")
    return fake
