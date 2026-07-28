"""Round-trip tests for the shared on-disk referral store."""

from __future__ import annotations

from vc_account_cli import referral_store


def test_get_returns_none_when_unset(tmp_path, monkeypatch):
    monkeypatch.setattr(referral_store, "PATH", tmp_path / "referral_code")
    assert referral_store.get_referral_code() is None


def test_set_then_get_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(referral_store, "PATH", tmp_path / "nested" / "referral_code")
    referral_store.set_referral_code(" ADA123 ")
    assert referral_store.get_referral_code() == "ADA123"


def test_clear_removes_the_file(tmp_path, monkeypatch):
    monkeypatch.setattr(referral_store, "PATH", tmp_path / "referral_code")
    referral_store.set_referral_code("ADA123")
    referral_store.clear_referral_code()
    assert referral_store.get_referral_code() is None
    assert not referral_store.PATH.exists()


def test_clear_is_a_noop_when_no_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(referral_store, "PATH", tmp_path / "referral_code")
    referral_store.clear_referral_code()  # must not raise
    assert referral_store.get_referral_code() is None


def test_empty_file_is_treated_as_no_code(tmp_path, monkeypatch):
    path = tmp_path / "referral_code"
    path.write_text("   \n")
    monkeypatch.setattr(referral_store, "PATH", path)
    assert referral_store.get_referral_code() is None
