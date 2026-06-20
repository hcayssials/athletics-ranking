"""Reverse solver ('what would it take') helper."""
from wa_ranking.whatif import _targets_required


def _counting(scores):
    return [{"performance_score": s} for s in scores]


def test_targets_required_statuses():
    counting = _counting([1300, 1280, 1260, 1240, 1220])  # full best-5 set, current avg 1260
    rows = _targets_required("1500m_men", counting, 5, placing=100, current_score=1260, targets=[
        ("already there", 1200),     # at/below current score -> met
        ("reach the cutoff", 1280),  # above current -> needs a real (reachable) time
        ("reach #1", 1400),          # absurdly high -> faster than the table tops out
    ])
    by_label = {r["label"]: r for r in rows}

    assert by_label["already there"]["status"] == "met"
    assert by_label["already there"]["time"] is None

    reach = by_label["reach the cutoff"]
    assert reach["status"] == "reachable"
    assert reach["time"] is not None
    assert reach["result_score"] > 0

    assert by_label["reach #1"]["status"] == "unreachable"
    assert by_label["reach #1"]["time"] is None


def test_required_targets_structure(monkeypatch):
    from wa_ranking import whatif
    data = {"rank_date": "2026-06-16", "athletes": [
        {"name": "Top A", "country": "ESP", "ranking_score": 1320,
         "performances": [{"performance_score": 1320, "discipline_code": "1500", "competition": "x", "date": "2026-05-01"}]},
        {"name": "Low B", "country": "GBR", "ranking_score": 1150,
         "performances": [{"performance_score": 1150, "discipline_code": "1500", "competition": "y", "date": "2026-05-01"}]},
    ]}
    monkeypatch.setattr(whatif.fetch, "fetch_championship", lambda *a, **k: data)
    r = whatif.required_targets("1500m_men", "Low B", place=1, category="GW")
    assert r["athlete"] == "Low B" and r["place"] == 1 and r["category"] == "GW"
    assert any("#1" in t["label"] for t in r["targets"])
    for t in r["targets"]:
        assert t["status"] in ("met", "reachable", "unreachable")


def test_targets_required_skips_none_score():
    rows = _targets_required("1500m_men", _counting([1300, 1280]), 5, 100, current_score=1290,
                             targets=[("no target", None), ("real", 1310)])
    assert [r["label"] for r in rows] == ["real"]


def _perf(score, code, mark):
    return {"performance_score": score, "discipline_code": code, "mark": mark,
            "competition": "Meet", "date": "2026-05-01", "result_score": score,
            "placing_score": 0}


def _stub_5000_athlete(monkeypatch, perfs, ranking_score):
    """A 5000m_men list with one athlete (given counting set) plus filler, for what_if."""
    from wa_ranking import whatif
    data = {"rank_date": "2026-06-16", "athletes": [
        {"name": "Test Runner", "country": "GBR", "ranking_score": ranking_score, "rank": 5,
         "performances": perfs},
        {"name": "Filler", "country": "KEN", "ranking_score": 1400, "rank": 1,
         "performances": [_perf(1400, "5000", "12:40.00")]},
    ]}
    monkeypatch.setattr(whatif.fetch, "fetch_championship", lambda *a, **k: data)


def test_similar_event_blocked_by_main_minimum(monkeypatch):
    # Two 5000m (1310/1312) and a strong counting 3000m (1381). The single non-5000m slot is held
    # by that 3000m, so a new 3000m that is faster than the counting 5000m results still can't
    # count -- the main-event minimum (2 of 3 must be the 5000m) protects them.
    from wa_ranking.whatif import what_if
    _stub_5000_athlete(monkeypatch, [
        _perf(1312, "5000", "12:57.90"), _perf(1310, "5000", "12:53.63"),
        _perf(1381, "3000", "7:25.77"),
    ], ranking_score=1334)
    r = what_if("5000m_men", "Test Runner", "7:30.0", category="DF", place=5,
                sub_event="3000m", verbose=False)
    assert r["hypothetical_event"]["discipline_code"] == "3000"
    assert r["hypothetical_event"]["is_main"] is False
    # scores above the counting 5000m marks but below the counting 3000m -> blocked, no change
    assert 1310 < r["hypothetical_performance"]["performance_score"] < 1381
    assert r["new_perf_counts"] is False
    assert r["score_delta"] == 0
    assert r["main_event_rule"]["blocked_by_main_rule"] is True
    assert "5000m" in r["similar_event_note"] and "similar event" in r["similar_event_note"]


def test_similar_event_counts_replacing_similar(monkeypatch):
    # A faster 3000m than the existing counting 3000m displaces it (the non-main slot), raising
    # the score -- and is not "blocked".
    from wa_ranking.whatif import what_if
    _stub_5000_athlete(monkeypatch, [
        _perf(1382, "5000", "12:45.00"), _perf(1329, "5000", "13:05.00"),
        _perf(1326, "3000", "7:36.78"),
    ], ranking_score=1345)
    r = what_if("5000m_men", "Test Runner", "7:25.0", category="DF", place=1,
                sub_event="3000m", verbose=False)
    assert r["new_perf_counts"] is True
    assert r["score_delta"] > 0
    assert r["main_event_rule"]["blocked_by_main_rule"] is False


def test_main_event_entry_has_no_similar_note(monkeypatch):
    from wa_ranking.whatif import what_if
    _stub_5000_athlete(monkeypatch, [
        _perf(1382, "5000", "12:45.00"), _perf(1329, "5000", "13:05.00"),
        _perf(1326, "3000", "7:36.78"),
    ], ranking_score=1345)
    r = what_if("5000m_men", "Test Runner", "12:50.0", category="DF", place=1, verbose=False)
    assert r["hypothetical_event"]["is_main"] is True
    assert r["similar_event_note"] is None
