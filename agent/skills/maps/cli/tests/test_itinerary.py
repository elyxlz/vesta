from gmaps_cli.itinerary import lay_out, nearest_neighbour, open_at_slot, parse_duration_min


def test_parse_duration_min():
    assert parse_duration_min("15 min") == 15
    assert parse_duration_min("1 h 5 min") == 65
    assert parse_duration_min("2 hr") == 120
    assert parse_duration_min(None) == 0


def test_lay_out_timeline():
    slots = lay_out([6, 2], start="21:00", dwell_min=20, count=3)
    assert slots[0] == ("21:00", "21:20")
    assert slots[1] == ("21:26", "21:46")  # 21:20 + 6 min travel, then 20 min dwell
    assert slots[2] == ("21:48", "22:08")  # 21:46 + 2 min travel


def test_lay_out_rejects_wrong_leg_count():
    try:
        lay_out([6], start="10:00", dwell_min=10, count=3)
    except ValueError:
        return
    raise AssertionError("expected ValueError for mismatched leg count")


def test_open_at_slot_within_todays_hours():
    day = [(660, 1440)]  # 11:00-24:00
    assert open_at_slot(day, "21:00", "21:20") is True
    assert open_at_slot(day, "10:00", "10:20") is False
    assert open_at_slot([], "21:00", "21:20") is None  # no published hours


def test_open_at_slot_handles_past_midnight():
    late = [(1080, 1500)]  # 18:00-01:00
    assert open_at_slot(late, "23:50", "00:30") is True  # slot itself crosses midnight
    assert open_at_slot(late, "00:10", "00:30") is True  # slot entirely after midnight
    assert open_at_slot(late, "01:10", "01:30") is False  # after closing


def test_nearest_neighbour_orders_by_proximity():
    # 0 near 2, 2 near 1; naive 0,1,2 is worse than 0,2,1.
    coords = [(40.0, 8.0), (40.0, 9.0), (40.0, 8.1)]
    assert nearest_neighbour(coords) == [0, 2, 1]
