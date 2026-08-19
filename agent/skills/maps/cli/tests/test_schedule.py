from gmaps_cli.models import Links, Place
from gmaps_cli.schedule import optimize_order, schedule


def _place(name: str) -> Place:
    return Place(
        name=name,
        lat=0.0,
        lng=0.0,
        ftid="0x0:0x0",
        cid=0,
        place_id=None,
        address=None,
        links=Links(place_url="", directions_url=""),
    )


def test_schedule_lays_out_slots():
    stops = [_place("A"), _place("B"), _place("C")]
    legs = [360, 120]  # 6 min, 2 min
    plan = schedule(stops, legs, start="21:00", dwell_min=20)
    assert plan[0].arrive == "21:00"
    assert plan[0].leave == "21:20"
    assert plan[1].arrive == "21:26"  # 21:20 + 6 min
    assert plan[1].leave == "21:46"
    assert plan[2].arrive == "21:48"  # 21:46 + 2 min


def test_schedule_flags_closed_stop():
    stops = [_place("A"), _place("B")]
    legs = [60]
    hours = [("09:00", "23:00"), ("09:00", "21:00")]
    plan = schedule(stops, legs, start="21:30", dwell_min=10, hours=hours)
    assert plan[0].open_at_slot is True
    assert plan[1].open_at_slot is False  # arrives 21:41, closed at 21:00


def test_schedule_handles_after_midnight_close():
    stops = [_place("A")]
    hours = [("11:00", "00:00")]  # open till midnight
    plan = schedule(stops, [], start="23:30", dwell_min=10, hours=hours)
    assert plan[0].open_at_slot is True


def test_optimize_order_nearest_neighbour():
    # 0 near 2, 2 near 1; naive order 0,1,2 is worse than 0,2,1.
    matrix = [
        [0, 100, 10],
        [100, 0, 20],
        [10, 20, 0],
    ]
    assert optimize_order(matrix) == [0, 2, 1]
