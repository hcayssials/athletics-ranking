"""Shared World Athletics field parsers."""
from wa_ranking.wa_parse import parse_place, parse_wa_date


def test_parse_wa_date():
    assert parse_wa_date("07 JUN 2026") == "2026-06-07"
    assert parse_wa_date("10 June 2024") == "2024-06-10"
    assert parse_wa_date("  28 AUG 2025 ") == "2025-08-28"
    assert parse_wa_date("") is None
    assert parse_wa_date(None) is None
    assert parse_wa_date("not a date") is None


def test_parse_place():
    assert parse_place("P6") == 6
    assert parse_place("2") == 2
    assert parse_place(3) == 3
    assert parse_place("") is None
    assert parse_place(None) is None
    assert parse_place("DNF") is None
