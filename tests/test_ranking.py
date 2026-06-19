"""Unit tests for the ranking math (counting-set model; no network)."""
from datetime import date

from wa_ranking.ranking import (
    insert_and_recompute, rank_position, ranking_score, resolve_window, select_counting,
)

EAC = "European Athletics Championships"


def p(score, d="2026-05-01", disc="1500", comp="Some Meet"):
    return {"performance_score": score, "date": d, "discipline_code": disc, "competition": comp}


# --- baseline: trust WA's returned counting set ---------------------------------------

def test_ranking_score_floors_mean_of_returned_set():
    perfs = [p(1400), p(1380), p(1360), p(1340), p(1301)]
    assert ranking_score(perfs, 5) == 1356            # 6781/5 = 1356.2 -> floor 1356


def test_ranking_score_fewer_than_n_averages_over_actual_count():
    assert ranking_score([p(1400), p(1300)], 5) == 1350


def test_ranking_score_none_when_empty():
    assert ranking_score([], 5) is None


# --- selection rules ------------------------------------------------------------------

def test_select_counting_takes_best_n():
    perfs = [p(1400), p(1380), p(1360), p(1340), p(1320), p(1300)]
    assert [x["performance_score"] for x in select_counting(perfs, 5)] == \
        [1400, 1380, 1360, 1340, 1320]


def test_protected_championship_is_window_exempt_but_displaceable():
    # The continental result is window-exempt (kept despite being out of window) but is
    # still displaced when there are enough better in-window results.
    perfs = [p(1400), p(1380), p(1360), p(1340), p(1320),
             p(1000, d="2024-06-12", comp=f"{EAC}, Roma")]
    sel = select_counting(perfs, 5, always_include_competitions=(EAC,))
    scores = [x["performance_score"] for x in sel]
    # Five better results fill the best-5, so the weak continental result drops out.
    assert 1000 not in scores and 1320 in scores and len(sel) == 5


def test_main_event_minimum_enforced():
    perfs = [p(1400, disc="MILE"), p(1390, disc="MILE"), p(1380, disc="MILE"),
             p(1370, disc="MILE"), p(1300), p(1290), p(1280)]
    sel = select_counting(perfs, 5, main_event_codes=("1500",), main_event_min=3)
    assert sum(1 for x in sel if x["discipline_code"] == "1500") == 3
    # Without the rule the best 5 would contain only one main event.
    free = select_counting(perfs, 5)
    assert sum(1 for x in free if x["discipline_code"] == "1500") == 1


def test_fixed_window_drops_out_of_range_but_keeps_protected():
    perfs = [p(1400, d="2026-03-01"),
             p(1390, d="2025-07-01"),                                  # before fixed start
             p(1000, d="2024-06-12", comp=EAC)]                        # protected
    sel = select_counting(perfs, 5, window_start=date(2025, 7, 27),
                          window_end=date(2026, 7, 26), always_include_competitions=(EAC,))
    scores = [x["performance_score"] for x in sel]
    assert 1400 in scores and 1390 not in scores and 1000 in scores


# --- inserting a hypothetical ---------------------------------------------------------

def test_insert_displaces_weakest():
    perfs = [p(1400), p(1380), p(1360), p(1340), p(1320)]
    r = insert_and_recompute(perfs, p(1390, comp="(hypothetical)"), 5)
    assert r["old_score"] == 1360
    assert r["new_score"] == 1374                     # 1400,1390,1380,1360,1340
    assert r["new_perf_counts"] is True
    assert r["delta"] == 14


def test_insert_too_weak_does_not_count():
    perfs = [p(1400), p(1380), p(1360), p(1340), p(1320)]
    r = insert_and_recompute(perfs, p(1000), 5)
    assert r["new_perf_counts"] is False
    assert r["new_score"] == r["old_score"]


def test_better_result_displaces_continental():
    # A stronger new result fills the best-5 and pushes the weak continental result out;
    # the continental result is window-exempt, not immune to a better score.
    perfs = [p(1400), p(1380), p(1360), p(1340), p(1000, d="2024-06-12", comp=EAC)]
    r = insert_and_recompute(perfs, p(1390), 5, always_include_competitions=(EAC,))
    scores = [x["performance_score"] for x in r["new_counting"]]
    assert 1390 in scores and 1000 not in scores      # weak continental result displaced
    assert r["new_perf_counts"] is True


def test_steeple_weak_hypothetical_does_not_count():
    # Regression (Daru): full best-3 set incl. a continental result, all main-event (3KSC).
    # A weaker main-event hypothetical must NOT be force-selected by the main-event minimum
    # — it should not count and the score must be unchanged.
    perfs = [p(1252, disc="3KSC"), p(1236, disc="3KSC"),
             p(1225, d="2024-06-10", disc="3KSC", comp=EAC)]
    r = insert_and_recompute(
        perfs, p(1206, disc="3KSC", comp="(hypothetical)"), 3,
        main_event_codes=("3KSC",), main_event_min=2, always_include_competitions=(EAC,),
    )
    assert r["new_perf_counts"] is False
    assert r["new_score"] == r["old_score"] == 1237


# --- misc -----------------------------------------------------------------------------

def test_rank_position():
    others = [1400, 1380, 1360, 1340, 1320]
    assert rank_position(others, 1370) == 3
    assert rank_position(others, 1500) == 1
    assert rank_position(others, 1000) == 6


def test_resolve_window_rolling_and_fixed():
    assert resolve_window(12, date(2026, 6, 16)) == (date(2025, 6, 16), date(2026, 6, 16))
    assert resolve_window(12, date(2026, 6, 16), window_start=date(2025, 7, 27),
                          window_end=date(2026, 7, 26)) == (date(2025, 7, 27), date(2026, 7, 26))
