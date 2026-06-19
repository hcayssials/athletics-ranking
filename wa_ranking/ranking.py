"""Ranking math: best-N selection, insertion of a hypothetical, and rank position.

Key fact about the data source: the World Athletics RankingScoreCalculation endpoint returns
*exactly the counting performances* — WA has already applied every selection rule (12-month
window, similar events, the >=3-of-5 main-event minimum, and the always-include-previous-
continental-championship rule). Verified: `floor(mean(returned performances)) == official`
for every athlete on the list.

So the **baseline** ranking score is simply the floored mean of the returned set; we do *not*
re-window it (doing so wrongly drops kept championship results). Selection logic is needed
only to (a) decide what a *hypothetical* new performance displaces, and (b) optionally apply
a *fixed* qualification window that differs from WA's rolling one.
"""
from __future__ import annotations

import math
from datetime import date
from dateutil.relativedelta import relativedelta


def _to_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _score(p: dict) -> int:
    return p.get("performance_score") or 0


def _is_protected(perf: dict, patterns: list[str]) -> bool:
    """A performance that always counts (e.g. the previous continental championship)."""
    comp = (perf.get("competition") or "").lower()
    return any(pat in comp for pat in patterns)


def resolve_window(window_months: int, as_of: date, *,
                   window_start: date | None = None,
                   window_end: date | None = None) -> tuple[date, date]:
    """Return the (start, end) date bounds for a window. Rolling by default; explicit
    start/end give a fixed window (e.g. the Road-to qualification period)."""
    end = window_end or as_of
    start = window_start or (end - relativedelta(months=window_months))
    return start, end


def select_counting(candidates: list[dict], best_n: int, *,
                    main_event_codes: tuple[str, ...] = (),
                    main_event_min: int = 0,
                    always_include_competitions: tuple[str, ...] = (),
                    window_start: date | None = None,
                    window_end: date | None = None) -> list[dict]:
    """Select the counting performances (<= best_n) that maximise the mean, subject to:

    - **protected** performances (matching `always_include_competitions`) always count;
    - at least `main_event_min` of the selection are in `main_event_codes`;
    - if a fixed window (`window_start`/`window_end`) is given, non-protected performances
      outside it are dropped first. With no window bounds, all candidates are kept (the
      returned set is already WA's rolling selection).
    """
    patterns = [s.lower() for s in always_include_competitions]
    main_codes = set(main_event_codes)

    # 1. Optional fixed-window filter (protected performances survive regardless of date).
    pool = []
    for p in candidates:
        if _is_protected(p, patterns):
            pool.append(p)
        elif window_start is None and window_end is None:
            pool.append(p)
        else:
            d = _to_date(p.get("date"))
            start = window_start or date.min
            end = window_end or date.max
            if d is not None and start < d <= end:
                pool.append(p)
    pool.sort(key=_score, reverse=True)

    # 2. Force-keep protected performances.
    selected = [p for p in pool if _is_protected(p, patterns)]
    others = [p for p in pool if not _is_protected(p, patterns)]

    # 3. Satisfy the main-event minimum with the best available main-event performances.
    if main_codes and main_event_min > 0:
        mains_in = sum(1 for p in selected if p.get("discipline_code") in main_codes)
        need = min(main_event_min - mains_in, best_n - len(selected))
        if need > 0:
            other_mains = [p for p in others if p.get("discipline_code") in main_codes]
            selected += other_mains[:need]

    # 4. Fill remaining slots by score.
    sel_ids = {id(p) for p in selected}
    selected += [p for p in others if id(p) not in sel_ids][: best_n - len(selected)]

    selected.sort(key=_score, reverse=True)
    return selected[:best_n]


def ranking_score(perfs: list[dict], best_n: int, **sel) -> int | None:
    """Floored mean of the counting performances (None if there are none).

    With no selection kwargs this is the baseline: floor(mean(perfs)) — matching WA exactly,
    since `perfs` is already WA's counting set. `sel` accepts the `select_counting` keywords.
    """
    counting = select_counting(perfs, best_n, **sel)
    if not counting:
        return None
    return math.floor(sum(_score(p) for p in counting) / len(counting))


def insert_and_recompute(perfs: list[dict], new_perf: dict, best_n: int, **sel) -> dict:
    """Insert a hypothetical performance and recompute. Returns old/new score, delta, the
    old and new counting sets, and whether the new performance actually counts."""
    old_counting = select_counting(perfs, best_n, **sel)
    new_counting = select_counting(perfs + [new_perf], best_n, **sel)

    def floored(rows):
        return math.floor(sum(_score(p) for p in rows) / len(rows)) if rows else None

    old_score, new_score = floored(old_counting), floored(new_counting)
    return {
        "old_score": old_score,
        "new_score": new_score,
        "delta": (None if old_score is None or new_score is None else new_score - old_score),
        "old_counting": old_counting,
        "new_counting": new_counting,
        "new_perf_counts": any(p is new_perf for p in new_counting),
    }


def rank_position(all_scores: list[float], new_score: float) -> int:
    """1-based position of `new_score` among `all_scores` (ties: highest position)."""
    return 1 + sum(1 for s in all_scores if s is not None and s > new_score)
