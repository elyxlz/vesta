"""A fake provider for each role, connected in the test's own data directory."""

import pathlib as pl
import typing as tp

import pytest
import voice.config as vc
from voice import providers
from voice.providers import limit

from .fakes import FakeJudge, FakeStt, FakeTts


@pytest.fixture(autouse=True)
def fresh_limiters() -> tp.Iterator[None]:
    """Each test starts with the default TTS caps: a lowered cap must not leak into the next test."""
    limit.reset()
    yield
    limit.reset()


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
