"""Unit tests for microsoft_cli.monitor preview / timestamp helpers."""

from microsoft_cli.monitor import clean_preview, strip_fractional


def test_clean_preview_strips_zero_width_and_bidi():
    # Real-world pattern: Booking.com-style invisible padding between words.
    raw = "Go further for less\r\n ‌​‍‎‏﻿ ‌​ hey"
    assert clean_preview(raw) == "Go further for less hey"


def test_clean_preview_collapses_whitespace():
    assert clean_preview("a\n\n  b\t\tc") == "a b c"


def test_clean_preview_handles_empty():
    assert clean_preview("") == ""


def test_strip_fractional_removes_graph_start_time_padding():
    # Graph returns '2026-05-01T07:00:00.0000000' — seven trailing zeros.
    assert strip_fractional("2026-05-01T07:00:00.0000000") == "2026-05-01T07:00:00"


def test_strip_fractional_preserves_timezone_suffix():
    assert strip_fractional("2026-05-01T07:00:00.123Z") == "2026-05-01T07:00:00Z"
    assert strip_fractional("2026-05-01T07:00:00.123+00:00") == "2026-05-01T07:00:00+00:00"


def test_strip_fractional_leaves_non_fractional_intact():
    assert strip_fractional("2026-05-01T07:00:00") == "2026-05-01T07:00:00"
