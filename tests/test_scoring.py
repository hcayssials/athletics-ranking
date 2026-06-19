"""Unit tests for the scoring engine. Anchors verified against live World Athletics data."""
from datetime import date

import pytest

from wa_ranking.scoring import (
    decay_deduction, month_age, parse_time, placing_score,
    performance_score, result_score, score_performance,
)


def test_parse_time():
    assert parse_time("3:30.11") == 210.11
    assert parse_time("3:30") == 210.0
    assert parse_time("210.11") == 210.11
    assert parse_time(210.11) == 210.11


@pytest.mark.parametrize("time,expected", [
    ("3:30.11", 1243),   # live anchor: Yared Nuguse, Stockholm 2026
    ("3:30.35", 1240),   # live anchor: Nuguse, Rabat 2026
    ("3:28.80", 1262),
])
def test_result_score_anchors(time, expected):
    assert result_score("1500m_men", time) == expected


def test_result_score_monotonic_and_bounds():
    # Faster time -> not fewer points.
    assert result_score("1500m_men", "3:29.00") >= result_score("1500m_men", "3:35.00")
    # Faster than the fastest tabulated mark caps at the max; absurdly slow -> 0.
    assert result_score("1500m_men", "3:00.00") == result_score("1500m_men", "3:19.44")
    assert result_score("1500m_men", "9:99.99") == 0


@pytest.mark.parametrize("cat,place,expected", [
    ("GW", 1, 140),   # live anchor (Diamond League win, 2026 tables)
    ("GW", 2, 120),
    ("OW", 1, 260),
    ("A", 4, 70),
    ("F", 3, 4),
])
def test_placing_score(cat, place, expected):
    assert placing_score(cat, place) == expected


def test_placing_score_beyond_table_is_zero():
    assert placing_score("F", 9) == 0       # F only lists top 3
    assert placing_score("gw", 1) == 140     # case-insensitive


def test_placing_score_unknown_category():
    with pytest.raises(KeyError):
        placing_score("ZZ", 1)


def test_month_age_and_decay():
    assert month_age(date(2025, 9, 16), date(2026, 6, 16)) == 9
    assert month_age(date(2026, 6, 16), date(2026, 6, 16)) == 0
    assert decay_deduction(0) == 0
    assert decay_deduction(9) == -20
    assert decay_deduction(11) == -60


def test_performance_score_and_decay_combination():
    assert performance_score(1262, 140) == 1402
    assert performance_score(1262, 140, decay=-20) == 1382
    # Never negative.
    assert performance_score(0, 0, decay=-50) == 0


def test_score_performance_breakdown():
    b = score_performance("1500m_men", "3:28.80", "GW", 1,
                          perf_date=date(2026, 6, 16), as_of=date(2026, 6, 16))
    assert b["result_score"] == 1262
    assert b["placing_score"] == 140
    assert b["decay"] == 0
    assert b["performance_score"] == 1402
