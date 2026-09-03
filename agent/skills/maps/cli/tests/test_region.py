import sys

from gmaps_cli import cli, region

TAB = "# tzdb zone descriptions\nIT\t+4154+01229\tEurope/Rome\nNO\t+5955+01045\tEurope/Oslo\nGB\t+513030-0000731\tEurope/London\n"


def test_country_for_zone_maps_a_zone_to_its_one_country(tmp_path):
    tab = tmp_path / "zone.tab"
    tab.write_text(TAB, encoding="utf-8")
    assert region.country_for_zone("Europe/Rome", tab=tab) == "it"
    assert region.country_for_zone("Europe/London", tab=tab) == "gb"


def test_country_for_zone_keeps_per_country_zone_names_distinct(tmp_path):
    # Europe/Oslo shares Berlin's clocks in tzdb, but the reported name still means Norway.
    tab = tmp_path / "zone.tab"
    tab.write_text(TAB, encoding="utf-8")
    assert region.country_for_zone("Europe/Oslo", tab=tab) == "no"


def test_country_for_zone_falls_back_on_unknown_zone_or_missing_tab(tmp_path):
    tab = tmp_path / "zone.tab"
    tab.write_text(TAB, encoding="utf-8")
    assert region.country_for_zone("Mars/Olympus", tab=tab) == "us"
    assert region.country_for_zone("Europe/Rome", tab=tmp_path / "absent.tab") == "us"
    assert region.country_for_zone(None, tab=tab) == "us"


def test_local_zone_prefers_tz_env(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Rome")
    assert region.local_zone() == "Europe/Rome"


def test_local_zone_reads_the_localtime_symlink(monkeypatch, tmp_path):
    monkeypatch.delenv("TZ", raising=False)
    zone_file = tmp_path / "zoneinfo" / "Europe" / "Rome"
    zone_file.parent.mkdir(parents=True)
    zone_file.touch()
    localtime = tmp_path / "localtime"
    localtime.symlink_to(zone_file)
    monkeypatch.setattr(region, "LOCALTIME", localtime)
    assert region.local_zone() == "Europe/Rome"


def test_cli_country_defaults_from_the_box_timezone(monkeypatch, tmp_path):
    tab = tmp_path / "zone1970.tab"
    tab.write_text(TAB, encoding="utf-8")
    monkeypatch.setattr(region, "ZONE_TAB", tab)
    monkeypatch.setenv("TZ", "Europe/Rome")
    captured = {}

    def fake_search(query, *, near, filters, locale, country):
        captured["country"] = country
        return []

    monkeypatch.setattr(cli, "search", fake_search)
    monkeypatch.setattr(sys, "argv", ["maps", "search", "coffee"])
    cli.main()
    assert captured["country"] == "it"


def test_cli_country_flag_wins_over_the_timezone(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Rome")
    captured = {}

    def fake_search(query, *, near, filters, locale, country):
        captured["country"] = country
        return []

    monkeypatch.setattr(cli, "search", fake_search)
    monkeypatch.setattr(sys, "argv", ["maps", "search", "coffee", "--country", "fr"])
    cli.main()
    assert captured["country"] == "fr"
