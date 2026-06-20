"""Scoring engine: time -> result score, category/place -> placing score, age decay.

All numbers come from editable data files (see config.py); nothing is hardcoded here.

Result-score lookup rule (validated against live World Athletics data, Jun 2026):
    A time T scores the points of the *fastest tabulated threshold it still meets* —
    i.e. the smallest tabulated mark that is >= T. Example: 3:30.11 -> 1243,
    3:30.35 -> 1240, matching the live RankingScoreCalculation breakdown.
"""
from __future__ import annotations

import re
from bisect import bisect_left
from datetime import date

from .config import load_decay, load_event, load_placing_scores, load_result_table


def parse_time(value: str | float) -> float:
    """Parse a race time to seconds. Accepts '3:30.11', '3:30', '210.11', or seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if ":" not in s:
        return float(s)
    parts = s.split(":")
    parts = [float(p) for p in parts]
    seconds = 0.0
    for p in parts:
        seconds = seconds * 60 + p
    return round(seconds, 3)


def result_score(event: str, time: str | float, result_table: str | None = None) -> int:
    """Convert a performance time to a World Athletics result score.

    By default uses `event`'s result table; pass `result_table` to score on a different
    discipline's table (e.g. a hypothetical 3000m for a 5000m ranking)."""
    seconds = parse_time(time)
    table = load_result_table(result_table or load_event(event)["result_table"])  # asc by seconds
    marks = [row[0] for row in table]
    idx = bisect_left(marks, seconds)
    if idx >= len(table):
        return 0  # slower than the slowest tabulated mark -> no points
    return table[idx][1]


def format_seconds(seconds: float) -> str:
    """Format seconds as a race time, e.g. 214.5 -> '3:34.50' (or '54.30' under a minute)."""
    if seconds < 60:
        return f"{seconds:.2f}"
    m, s = divmod(round(seconds, 2), 60)
    return f"{int(m)}:{s:05.2f}"


def time_for_result_score(event: str, target_score: int, result_table: str | None = None) -> str | None:
    """The (slowest) time that scores at least `target_score` result points, formatted.

    Useful for "what time would they need?": invert the result-score table. Pass `result_table`
    to invert a different discipline's table.
    """
    table = load_result_table(result_table or load_event(event)["result_table"])  # asc by seconds
    best = None
    for seconds, score in table:
        if score >= target_score:
            best = seconds            # keep the slowest qualifying mark
    return format_seconds(best) if best is not None else None


def placing_score(category: str, place: int, event_group: str = "standard") -> int:
    """Placing points for finishing `place` in a `category` competition.

    Returns 0 if no points are awarded at that position for that category.
    """
    tables = load_placing_scores()
    if event_group not in tables:
        raise KeyError(f"Unknown placing event_group '{event_group}'.")
    cat = category.upper()
    if cat not in tables[event_group]:
        known = sorted(k for k in tables[event_group] if not k.startswith("_"))
        raise KeyError(f"Unknown category '{category}'. Known: {known}")
    return int(tables[event_group][cat].get(str(place), 0))


def month_age(perf_date: date, as_of: date) -> int:
    """Whole calendar months a performance is old, measured from `as_of`."""
    months = (as_of.year - perf_date.year) * 12 + (as_of.month - perf_date.month)
    if as_of.day < perf_date.day:
        months -= 1
    return max(0, months)


def decay_deduction(months_old: int) -> int:
    """Age-decay deduction (<=0) for a performance `months_old` months old."""
    return load_decay().get(months_old, 0)


def performance_score(result: int, placing: int, decay: int = 0) -> int:
    """Combine result + placing scores, applying an (already-negative) decay deduction."""
    return max(0, result + placing + decay)


def score_performance(event: str, time: str | float, category: str, place: int,
                      perf_date: date | None = None, as_of: date | None = None,
                      event_group: str = "standard", result_table: str | None = None) -> dict:
    """Fully score a (hypothetical) performance, returning a breakdown dict. `result_table`
    overrides the scoring table (for a similar-event hypothetical, e.g. a 3000m)."""
    rscore = result_score(event, time, result_table=result_table)
    pscore = placing_score(category, place, event_group)
    months = month_age(perf_date, as_of) if (perf_date and as_of) else 0
    decay = decay_deduction(months)
    total = performance_score(rscore, pscore, decay)
    return {
        "time": str(time),
        "seconds": parse_time(time),
        "category": category.upper(),
        "place": place,
        "result_score": rscore,
        "placing_score": pscore,
        "months_old": months,
        "decay": decay,
        "performance_score": total,
    }
