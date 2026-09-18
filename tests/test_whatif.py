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


def _stub_5000_athlete(monkeypatch, perfs, ranking_score, wr_bonus=0):
    """A 5000m_men list with one athlete (given counting set) plus filler, for what_if."""
    from wa_ranking import whatif
    data = {"rank_date": "2026-06-16", "athletes": [
        {"name": "Test Runner", "country": "GBR", "ranking_score": ranking_score, "rank": 5,
         "performances": perfs, "wr_bonus": wr_bonus},
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


def test_world_record_bonus_carries_into_old_and_new_scores(monkeypatch):
    # Counting set averages 1345 (floor); a +10 world-record bonus makes WA's score 1355.
    from wa_ranking.whatif import what_if
    perfs = [_perf(1382, "5000", "12:45.00"), _perf(1329, "5000", "13:05.00"),
             _perf(1326, "3000", "7:36.78")]
    _stub_5000_athlete(monkeypatch, perfs, ranking_score=1355, wr_bonus=10)
    r = what_if("5000m_men", "Test Runner", "12:50.0", category="DF", place=1, verbose=False)
    assert r["wr_bonus"] == 10
    assert r["recomputed_old_score"] == r["official_ranking_score"] == 1355
    _stub_5000_athlete(monkeypatch, perfs, ranking_score=1345)
    plain = what_if("5000m_men", "Test Runner", "12:50.0", category="DF", place=1, verbose=False)
    assert r["new_score"] == plain["new_score"] + 10
    assert r["score_delta"] == plain["score_delta"]


def test_targets_required_subtracts_bonus_from_the_target():
    # With a +10 bonus, reaching 1290 only needs the average to reach 1280.
    counting = _counting([1300, 1280, 1260, 1240, 1220])
    with_bonus = _targets_required("1500m_men", counting, 5, 100, current_score=1270,
                                   targets=[("t", 1290)], bonus=10)[0]
    without = _targets_required("1500m_men", counting, 5, 100, current_score=1260,
                                targets=[("t", 1280)])[0]
    assert with_bonus["result_score"] == without["result_score"]
    assert with_bonus["time"] == without["time"]


def _stub_1500_list(monkeypatch, achievers):
    """A 1500m_men world list (3 athletes) + a stubbed Beijing feed overlay."""
    from datetime import date
    from wa_ranking import feed, whatif
    def ath(name, country, score, rank):
        return {"name": name, "country": country, "ranking_score": score, "rank": rank,
                "performances": [_perf(score, "1500", "3:33.00") for _ in range(5)]}
    data = {"rank_date": "2026-09-15", "athletes": [
        ath("Top RUNNER", "KEN", 1400, 1), ath("Mid RUNNER", "GBR", 1300, 2),
        ath("Low RUNNER", "FRA", 1200, 3)]}
    monkeypatch.setattr(whatif.fetch, "fetch_championship", lambda *a, **k: data)
    snap = {"quota": 4, "entry_standard": "3:30.00",
            "alt_entry_standards": [{"event": "Mile", "entry_standard": "3:50.00"}],
            "window": {"start": "2026-08-23", "end": "2027-08-22"},
            "auto_invites": [{"name": "Isaac NADER", "country": "POR", "reason": "Defending World Champion"}],
            "standard_achievers": achievers, "fetched": "2026-09-18T06:00:00"}
    monkeypatch.setattr(feed, "read_feed", lambda *a, **k: snap)
    return date(2026, 9, 18)


def test_beijing_standard_route_and_gap(monkeypatch):
    from wa_ranking.whatif import what_if
    as_of = _stub_1500_list(monkeypatch, achievers=[])
    # Quota 4 = Nader (bye) + Kerr (manual bye, config) + 2 ranking places -> Low is out...
    r = what_if("1500m_men", "Low RUNNER", "3:31.00", category="B", place=1,
                championship="road_to_beijing", as_of=as_of, qualify=True, verbose=False)
    q = r["qualification"]
    assert q["quota"] == 4 and q["max_per_country"] == 3
    assert [i["name"] for i in q["auto_invites"]] == ["Isaac NADER", "Josh KERR"]
    es = q["entry_standard"]
    assert es["standard"] == "3:30.00" and es["meets"] is False and es["gap_seconds"] == 1.0
    assert "1.00s short" in es["note"]
    assert q["route_new"] == "out" and q["standard_achievers_known"] is True
    # ...but on the standard the athlete is in by that route, whatever the ranking says.
    r = what_if("1500m_men", "Low RUNNER", "3:29.80", category="B", place=1,
                championship="road_to_beijing", as_of=as_of, qualify=True, verbose=False)
    q = r["qualification"]
    assert q["entry_standard"]["meets"] is True and q["entry_standard"]["gap_seconds"] == -0.2
    assert q["route_old"] == "out" and q["route_new"] == "standard"
    assert q["status_new"] == "qualified" and q["standard_places"] == 1
    assert q["ranking_places"] == 1                          # 4 - 2 byes - 1 standard
    # Reverse solver leads with the standard row (exact time, not an estimate).
    first = r["what_would_it_take"]["targets"][0]
    assert first["kind"] == "standard" and first["time"] == "3:30.00" and first["status"] == "reachable"


def test_beijing_standard_validity_rules(monkeypatch):
    from wa_ranking.whatif import what_if
    as_of = _stub_1500_list(monkeypatch, achievers=[])
    run = lambda **kw: what_if("1500m_men", "Low RUNNER", kw.pop("time", "3:29.00"),
                               championship="road_to_beijing", as_of=as_of, qualify=True,
                               verbose=False, **kw)["qualification"]["entry_standard"]
    d = run(category="D", place=1)                         # too low a category
    assert d["meets_mark"] and not d["valid_category"] and not d["meets"]
    i = run(sub_event="1500m_i", category="GW", place=1)   # indoor never counts
    assert i["indoor_invalid"] and not i["meets"]
    m = run(sub_event="mile", time="3:49.00", category="GW", place=1)   # mile alternative
    assert m["standard"] == "3:50.00" and m["standard_event"] == "Mile" and m["meets"]
    two = run(sub_event="2000m", time="4:50.00", category="GW", place=1)  # no alt standard
    assert two["event_valid"] is False and not two["meets"]
    from datetime import date
    late = what_if("1500m_men", "Low RUNNER", "3:29.00", championship="road_to_beijing",
                   as_of=date(2027, 9, 1), qualify=True, verbose=False)["qualification"]["entry_standard"]
    assert late["inside_window"] is False and not late["meets"]


def test_beijing_known_achievers_squeeze_the_ranking_fill(monkeypatch):
    from wa_ranking.whatif import required_targets, what_if
    as_of = _stub_1500_list(monkeypatch, achievers=[
        {"name": "Low RUNNER", "country": "FRA", "mark": "3:29.50"},
        {"name": "Off LIST", "country": "USA", "mark": "3:29.90"}])
    r = what_if("1500m_men", "Mid RUNNER", "3:33.00", category="B", place=1,
                championship="road_to_beijing", as_of=as_of, qualify=True, verbose=False)
    q = r["qualification"]
    # 4 places: Nader, Kerr, Low (standard), Off LIST (standard) -> nothing left for the ranking.
    assert q["standard_places"] == 2 and q["ranking_places"] == 0
    assert q["route_new"] == "out" and q["cutoff_score"] is None
    assert q["standard_achievers_count"] == 2
    r = required_targets("1500m_men", "Low RUNNER", championship="road_to_beijing")
    assert r["targets"][0]["kind"] == "standard" and r["targets"][0]["status"] == "met"


def test_beijing_without_a_feed_snapshot_says_achievers_unknown(monkeypatch):
    from datetime import date
    from wa_ranking import feed, whatif
    from wa_ranking.whatif import what_if
    _stub_1500_list(monkeypatch, achievers=[])
    monkeypatch.setattr(feed, "read_feed", lambda *a, **k: None)
    r = what_if("1500m_men", "Low RUNNER", "3:31.00", championship="road_to_beijing",
                as_of=date(2026, 9, 18), qualify=True, verbose=False)
    q = r["qualification"]
    assert q["quota"] == 56 and q["standard_achievers_known"] is False
    assert q["qualification_source"] == "config" and q["entry_standard"]["standard"] == "3:30.00"
