from gmaps_cli.proto import find_proto, open_intervals, open_now, phone, review_count

FTID = "0x12dcf1f90bb8a3c3:0x7b07736c1223655d"


def _proto(*, state: object = 2, entries: object = None) -> list[object]:
    proto: list[object] = [None] * 204
    proto[10] = FTID
    proto[11] = "Alghero Gelateria Oops"
    proto[37] = [None, 416]
    proto[178] = [["+39 079 966 3707"]]
    proto[203] = [None, [["Thursday", 4, [2026, 8, 20], entries, 0, 1], 0, state]]
    return proto


def test_find_proto_locates_the_ftid_array():
    proto = _proto()
    record: list[object] = [["preamble"], proto]
    assert find_proto(record) is proto
    assert find_proto([["no", "ftid", "here"]]) is None


def test_review_count_and_phone_read_pinned_positions():
    proto = _proto()
    assert review_count(proto) == 416
    assert phone(proto) == "+39 079 966 3707"
    assert review_count(None) is None
    assert phone(None) is None


def test_open_now_maps_state_codes():
    assert open_now(_proto(state=1)) is True
    assert open_now(_proto(state=2)) is True
    assert open_now(_proto(state=4)) is False
    assert open_now(_proto(state=5)) is False
    assert open_now(_proto(state=0)) is None
    assert open_now(_proto(state=None)) is None
    assert open_now(None) is None


def test_open_intervals_decodes_clock_pairs():
    # "2-11:30 pm" -> 14:00-23:30
    assert open_intervals(_proto(entries=[["2–11:30 pm", [[14], [23, 30]]]])) == [(840, 1410)]
    # "11 am-12 am": an empty close means midnight, wrapping to end of day
    assert open_intervals(_proto(entries=[["11 am–12 am", [[11], []]]])) == [(660, 1440)]
    # "7 am-12:30 am": a null close hour means zero, so the interval wraps past midnight
    assert open_intervals(_proto(entries=[["7 am–12:30 am", [[7], [None, 30]]]])) == [(420, 1470)]
    assert open_intervals(_proto(entries=None)) == []
    assert open_intervals(None) == []
