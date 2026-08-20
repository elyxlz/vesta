import gmaps_cli.client as client_mod
import httpx
from gmaps_cli.client import DOCTOR_ANCHOR_CID, DOCTOR_ANCHOR_NAME, DriftError, doctor
from gmaps_cli.models import DirectionsLeg, Place, PlaceDetail

ALL_OK = {"search": "ok", "place": "ok", "directions": "ok", "transit": "ok", "reverse": "ok"}


def _anchor_place() -> Place:
    return Place(
        name=DOCTOR_ANCHOR_NAME,
        lat=51.5014,
        lng=-0.1419,
        ftid="0x48760520cd5b5eb5:0xa26abf514d902a7",
        cid=DOCTOR_ANCHOR_CID,
        place_id="ChIJtV5bzSAFdkgRpwLZFPWrJgo",
        address="London SW1A 1AA, United Kingdom",
    )


def _anchor_detail() -> PlaceDetail:
    return PlaceDetail(
        name=DOCTOR_ANCHOR_NAME,
        cid=DOCTOR_ANCHOR_CID,
        place_id=None,
        ftid=None,
        address=None,
        lat=51.5014,
        lng=-0.1419,
        rating=None,
        category=None,
        phone=None,
        website=None,
        hours_today=None,
    )


def _patch_all_ok(monkeypatch):
    leg = DirectionsLeg(mode="walking", duration_text="15 min", distance_text="1.2 km")
    monkeypatch.setattr(client_mod, "search", lambda *args, **kwargs: [_anchor_place()])
    monkeypatch.setattr(client_mod, "show", lambda *args, **kwargs: _anchor_detail())
    monkeypatch.setattr(client_mod, "directions", lambda *args, **kwargs: leg)
    monkeypatch.setattr(client_mod, "reverse", lambda *args, **kwargs: "London SW1A 1AA, United Kingdom")


def test_doctor_all_checks_ok(monkeypatch):
    _patch_all_ok(monkeypatch)
    assert doctor(locale="en-US", country="us") == ALL_OK


def test_doctor_records_a_failure_and_keeps_checking(monkeypatch):
    _patch_all_ok(monkeypatch)

    def drifted(*args: object, **kwargs: object) -> object:
        raise DriftError("canary empty")

    monkeypatch.setattr(client_mod, "search", drifted)
    checks = doctor(locale="en-US", country="us")
    assert "canary empty" in checks["search"]
    assert {name: value for name, value in checks.items() if name != "search"} == {
        "place": "ok",
        "directions": "ok",
        "transit": "ok",
        "reverse": "ok",
    }


def test_doctor_flags_a_wrong_anchor(monkeypatch):
    _patch_all_ok(monkeypatch)
    impostor = _anchor_place()
    impostor.cid = 42
    monkeypatch.setattr(client_mod, "search", lambda *args, **kwargs: [impostor])
    checks = doctor(locale="en-US", country="us")
    assert checks["search"] != "ok"
    assert "anchor cid missing" in checks["search"]


def test_doctor_records_network_errors_per_check(monkeypatch):
    _patch_all_ok(monkeypatch)

    def unreachable(*args: object, **kwargs: object) -> object:
        raise httpx.ConnectError("dns down")

    monkeypatch.setattr(client_mod, "reverse", unreachable)
    checks = doctor(locale="en-US", country="us")
    assert "dns down" in checks["reverse"]
    assert checks["search"] == "ok"
