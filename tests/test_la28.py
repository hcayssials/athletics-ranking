"""Road to LA28 (Olympic planning mode): config facts, window/eligibility rules, the
'best_performances' standards policy, and proof that the Beijing (Worlds) behaviour is unchanged.

Hermetic: ranking lists are synthetic (monkeypatched `fetch.fetch_championship`), the feed is
patched out (`feed.read_feed`), and every date is passed explicitly (`as_of`, `perf_date`), so
nothing depends on the network or the wall clock.
"""
import os

os.environ["PREWARM"] = "off"

from datetime import date

import pytest

from wa_ranking import api, feed, fetch, whatif
from wa_ranking.config import (championship_event_config, load_championship,
                               load_championships, load_event)
from wa_ranking.qualify import athlete_status, qualifying_field

LA = "road_to_la28"
BJ = "road_to_beijing"
AS_OF = date(2026, 11, 15)

# event -> (men/women standard, quota, window start)  [official LA28 qualification system]
OFFICIAL = {
    "800m_men": ("1:43.00", 48), "800m_women": ("1:57.00", 48),
    "1500m_men": ("3:30.00", 45), "1500m_women": ("3:57.50", 45),
    "5000m_men": ("12:50.00", 42), "5000m_women": ("14:34.00", 42),
    "10000m_men": ("26:48.00", 27), "10000m_women": ("30:30.00", 27),
    "3000mSC_men": ("8:07.50", 30), "3000mSC_women": ("9:06.00", 30),
}
WINDOW_END = "2028-06-18"


# ----------------------------------------------------------------------------- helpers
def _perf(score, code, mark, d="2026-10-01"):
    return {"performance_score": score, "discipline_code": code, "mark": mark,
            "competition": "Meet", "date": d, "result_score": score, "placing_score": 0}


def _data(event, country="GBR", extra=()):
    code = load_event(event)["main_event_codes"][0]
    runner = {"name": "Test Runner", "country": country, "ranking_score": 1300, "rank": 2,
              "performances": [_perf(1300, code, "x")] * 3}
    top = {"name": "Top Dog", "country": "KEN", "ranking_score": 1400, "rank": 1,
           "performances": [_perf(1400, code, "x")] * 3}
    return {"rank_date": "2026-11-10", "athletes": [top, runner, *extra]}


@pytest.fixture
def patch(monkeypatch):
    """Install a synthetic ranking list + no feed snapshot; returns a setter for the list."""
    state = {}

    def install(event, **kw):
        state["data"] = _data(event, **kw)
    monkeypatch.setattr(whatif.fetch, "fetch_championship", lambda *a, **k: state["data"])
    monkeypatch.setattr(fetch, "fetch_championship", lambda *a, **k: state["data"])
    monkeypatch.setattr(feed, "read_feed", lambda *a, **k: None)
    return install


def _wi(event="1500m_men", time="3:29.00", *, perf_date, champ=LA, cat="GW", sub=None,
        achievers=None, as_of=AS_OF, qualify=True):
    return whatif.what_if(event, "Test Runner", time, category=cat, place=1, championship=champ,
                          as_of=as_of, perf_date=perf_date, sub_event=sub, qualify=qualify,
                          standard_achievers=achievers, verbose=False)


def _es(**kw):
    return _wi(**kw)["qualification"]["entry_standard"]


def _achievers(n, start=480.0, step=0.1, prefix="C"):
    """n achievers with distinct countries, marks start, start+step... (seconds -> m:ss.xx)."""
    out = []
    for i in range(n):
        s = round(start + i * step, 2)
        out.append({"name": f"{prefix}{i:02d} ATHLETE", "country": f"{prefix}{i:02d}",
                    "mark": f"{int(s // 60)}:{s % 60:05.2f}"})
    return out


# ------------------------------------------------------------------ 1. config
def test_la28_events_standards_quotas_windows():
    assert set(load_championship(LA)["events"]) == set(OFFICIAL)
    for ev, (std, quota) in OFFICIAL.items():
        cfg = championship_event_config(LA, ev)
        assert cfg["entry_standard"] == std, ev
        assert cfg["quota"] == quota, ev
        w = cfg.get("qualification_window") or load_championship(LA)["qualification_window"]
        start = "2026-12-19" if ev.startswith("10000m") else "2027-06-19"
        assert w == {"start": start, "end": WINDOW_END}, ev


def test_la28_has_no_wildcards_and_no_feed():
    c = load_championship(LA)
    for ev, cfg in c["events"].items():
        assert "auto_invites" not in cfg and "defending_champion" not in cfg, ev
    assert "qualification_feed" not in c
    assert feed.feed_events(LA) == {}


def test_la28_top_level_facts():
    c = load_championship(LA)
    assert c["max_per_country"] == 3
    assert c["planning"] is True
    assert c["data_source"] == "world"
    assert c["source"]["version"] == "9 November 2026"
    assert c["cutoff_target_label"] == "reach the projected ranking cutoff"
    assert c["qualification_policy"]["standards_over_quota"] == "best_performances"
    assert c["qualification_policy"]["road_label_category"] == "E"
    assert c["qualification_policy"]["national_championships_until"] == "2028-06-22"
    # no mile alternative for the 1500m
    assert not championship_event_config(LA, "1500m_men").get("alt_entry_standards")
    for ev in ("5000m_men", "5000m_women"):
        assert [a["event"] for a in championship_event_config(LA, ev)["alt_entry_standards"]] == ["5 km Road"]
    for ev in ("10000m_men", "10000m_women"):
        assert [a["event"] for a in championship_event_config(LA, ev)["alt_entry_standards"]] == ["10km Road"]


def test_beijing_precedes_la28_and_is_not_planning():
    keys = [k for k, c in load_championships().items() if not c.get("archived")]
    assert keys.index("road_to_beijing") < keys.index("road_to_la28")
    assert not load_championship(BJ).get("planning")
    assert "qualification_policy" not in load_championship(BJ)


# ------------------------------------------------------------------ 2. window boundaries
@pytest.mark.parametrize("day,status,meets", [
    ("2027-06-18", "before", False),
    ("2027-06-19", "inside", True),
    ("2028-06-18", "inside", True),
    ("2028-06-19", "national_championships_only", True),
    ("2028-06-22", "national_championships_only", True),
    ("2028-06-23", "after", False),
])
def test_window_boundaries_1500m(patch, day, status, meets):
    patch("1500m_men")
    es = _es(perf_date=date.fromisoformat(day))
    assert es["window_status"] == status
    assert es["meets_mark"] is True          # 3:29.00 beats 3:30.00 on any date
    assert es["meets"] is meets
    assert es["inside_window"] is (status in ("inside", "national_championships_only"))
    if status == "national_championships_only":
        assert es["conditions"] and "National" in es["conditions"][0]
    else:
        assert es["conditions"] == []


def test_before_window_note_explains(patch):
    patch("1500m_men")
    note = _es(perf_date=date(2027, 6, 18))["note"]
    assert "Fast enough" in note and "before the qualification window opens" in note
    assert "2027-06-19" in note


def test_10000m_has_earlier_window_start(patch):
    patch("10000m_men")
    d = date(2027, 1, 10)
    assert _es(event="10000m_men", time="26:40.00", perf_date=d)["window_status"] == "inside"
    assert _es(event="10000m_men", time="26:40.00", perf_date=date(2026, 12, 18))["window_status"] == "before"
    assert _es(event="10000m_men", time="26:40.00", perf_date=date(2026, 12, 19))["meets"] is True
    patch("1500m_men")
    assert _es(perf_date=d)["window_status"] == "before"


def test_future_dated_performance_is_echoed(patch):
    patch("1500m_men")
    r = _wi(perf_date=date(2027, 7, 10), as_of=date(2026, 11, 15))
    assert r["as_of"] == "2026-11-15" and r["performance_date"] == "2027-07-10"
    new = [p for p in r["new_counting"] if p.get("hypothetical")]
    assert new and new[0]["date"] == "2027-07-10"
    assert r["qualification"]["entry_standard"]["meets"] is True


# ------------------------------------------------------------------ 3. category / road / indoor / alt
D_IN = date(2027, 9, 1)


@pytest.mark.parametrize("cat", ["D", "E"])
def test_low_category_main_event_invalid(patch, cat):
    patch("1500m_men")
    es = _es(perf_date=D_IN, cat=cat)
    assert es["valid_category"] is False and es["meets"] is False and es["meets_mark"] is True


def test_category_c_is_valid(patch):
    patch("1500m_men")
    assert _es(perf_date=D_IN, cat="C")["meets"] is True


@pytest.mark.parametrize("event,sub,time", [("10000m_men", "10km", "26:40.00"),
                                            ("5000m_men", "5km", "12:40.00")])
def test_road_label_category_rules(patch, event, sub, time):
    patch(event)
    kw = dict(event=event, sub=sub, time=time, perf_date=D_IN)
    e = _es(cat="E", **kw)
    assert e["event_valid"] is True and e["valid_category"] is True and e["meets"] is True
    assert e["conditions"] and "Label" in " ".join(e["conditions"])
    assert "Conditional" in e["note"]
    d = _es(cat="D", **kw)
    assert d["valid_category"] is False and d["meets"] is False
    b = _es(cat="B", **kw)
    assert b["valid_category"] is True and b["meets"] is True and b["conditions"] == []


def test_label_category_does_not_apply_to_track_alt_or_main(patch):
    patch("5000m_men")
    # a Category E 3000m (non-road alt) never meets; Category E main 5000m is invalid
    assert _es(event="5000m_men", sub="3000m", time="7:20.00", perf_date=D_IN, cat="E")["meets"] is False
    assert _es(event="5000m_men", time="12:40.00", perf_date=D_IN, cat="E")["meets"] is False


def test_indoor_never_meets(patch):
    patch("1500m_men")
    es = _es(sub="1500m_i", perf_date=D_IN)
    assert es["indoor_invalid"] is True and es["meets"] is False
    patch("5000m_men")
    assert _es(event="5000m_men", sub="5000m_i", time="12:40.00", perf_date=D_IN)["meets"] is False


def test_mile_not_an_alternative_for_la28_but_is_for_beijing(patch):
    patch("1500m_men")
    la = _es(sub="mile", time="3:50.00", perf_date=D_IN)
    assert la["event_valid"] is False and la["meets"] is False
    bj = _es(sub="mile", time="3:50.00", perf_date=date(2026, 11, 15), champ=BJ)
    assert bj["event_valid"] is True and bj["meets"] is True
    assert bj["standard"] == "3:50.00" and bj["standard_event"] == "Mile"


# ------------------------------------------------------------------ 4. no feed / projection
def test_no_feed_projection_defaults(patch):
    patch("1500m_men")
    q = _wi(perf_date=D_IN)["qualification"]
    assert q["standard_achievers_known"] is False
    assert q["standard_achievers_assumed"] is False
    assert q["projection_only"] is True
    assert q["standards_oversubscribed"] is False
    assert q["standards_policy"] == "best_performances"
    assert q["route_new"] == "standard"
    assert q["qualification_source"] == "config"


def test_rankings_endpoint_for_la28(patch):
    patch("1500m_men")
    r = api.rankings(LA, "1500m_men")
    assert r["standard_achievers"] is None          # unknown, not []
    assert r["tracking"]["status"] == "not_configured"
    assert r["standards_policy"] == "best_performances"
    assert r["quota"] == 45 and r["entry_standard"] == "3:30.00"
    assert r["qualification_window"] == {"start": "2027-06-19", "end": WINDOW_END}
    assert r["auto_invites"] is None or r["auto_invites"] == []


# ------------------------------------------------------------------ 5. oversubscription (steeple, quota 30)
SC = dict(event="3000mSC_men")


def _sc(time, achievers, country="GBR", extra_ath=()):
    return _wi(time=time, perf_date=D_IN, achievers=achievers, **SC)["qualification"]


def test_oversubscribed_slower_mark_is_outside_quota(patch):
    patch("3000mSC_men")
    ach = _achievers(30)                       # 8:00.00 .. 8:02.90, exactly fills the quota
    q = _sc("8:05.00", ach)
    assert q["entry_standard"]["meets"] is True
    assert q["standards_oversubscribed"] is True
    assert q["route_new"] == "standard_outside_quota" and q["status_new"] == "standard_outside_quota"
    assert q["standard_achievers_assumed"] is True and q["projection_only"] is True
    assert q["standard_places"] == 30 and q["cutoff_score"] is None
    assert q["above_cutoff"] is False


def test_oversubscribed_faster_mark_takes_a_place(patch):
    patch("3000mSC_men")
    q = _sc("7:58.00", _achievers(30))
    assert q["route_new"] == "standard" and q["qual_position_new"] == 1
    assert q["standards_oversubscribed"] is True       # the 30th-best was bumped
    assert q["cutoff_score"] is None                   # no ranking places at all
    assert q["ranking_places"] == 0
    assert all(s["reason"] == "entry standard" for s in q["field_new"])
    assert len(q["field_new"]) == 30


def test_tie_with_last_placed_mark_is_unresolved(patch):
    patch("3000mSC_men")
    ach = _achievers(30)
    last = ach[-1]["mark"]
    q = _sc(last, ach)
    assert q["standards_tied"] and "Test Runner" in q["standards_tied"]
    assert q["route_new"] == "standard_tie_unresolved"


def test_listed_athlete_orders_by_mark_not_ranking_score(patch):
    patch("3000mSC_men")
    # Test Runner is the best-ranked athlete (1300 vs Top Dog 1400: make him the best below)
    slow = {"name": "Test Runner", "country": "GBR", "mark": "8:07.00"}
    ach = _achievers(30) + [slow]
    q = _sc("8:07.00", ach)
    assert q["route_old"] == "standard_outside_quota"      # ranking score does not help him
    q = _sc("8:01.05", ach)
    assert q["route_new"] == "standard"
    # 8:00.00 .. 8:01.00 are 11 faster marks -> he is 12th
    assert q["qual_position_new"] == 12
    assert q["qual_position_old"] is None
    names = [s["name"] for s in q["field_new"]]
    assert names.index("Test Runner") == 11
    assert "C29 ATHLETE" not in names                      # the slowest placed mark was bumped
    # a slower re-run than the listed mark does not replace it
    q = _sc("8:07.50", ach)
    assert q["route_new"] == "standard_outside_quota"


def test_noc_limit_fourth_achiever_blocked_and_takes_no_place(patch):
    patch("3000mSC_men")
    ken = [{"name": f"KEN{i} ATHLETE", "country": "KEN", "mark": f"8:0{i}.00"} for i in range(3)]
    q = _wi(time="7:59.00", perf_date=D_IN, achievers=ken, **SC)["qualification"]
    assert q["route_new"] == "standard"
    # a Kenyan 4th (slower than the three listed, so by performance he is the one capped)
    patch("3000mSC_men", country="KEN")
    q = _wi(time="8:05.00", perf_date=D_IN, achievers=ken, **SC)["qualification"]
    assert q["entry_standard"]["meets"] is True
    assert q["route_new"] == "blocked_country_cap" and q["status_new"] == "blocked_country_cap"
    assert q["standard_places"] == 3                        # the blocked one consumed nothing
    assert q["country_count"] == 3


def test_qualifying_field_blocked_does_not_consume_a_place():
    ach = [{"name": f"K{i}", "country": "KEN", "mark": "m", "mark_seconds": 480.0 + i} for i in range(4)]
    ach.append({"name": "U1", "country": "USA", "mark": "m", "mark_seconds": 485.0})
    f = qualifying_field([], 4, max_per_country=3, standard_achievers=ach,
                         standards_policy="best_performances")
    assert [s["name"] for s in f["slots"]] == ["K0", "K1", "K2", "U1"]
    assert [b["name"] for b in f["blocked"]] == ["K3"]
    assert f["outside_quota"] == [] and f["standards_oversubscribed"] is False


# ------------------------------------------------------------------ 6. qualifying_field policies
def _ranked():
    return [{"name": "R1", "country": "AAA", "ranking_score": 1400},
            {"name": "R2", "country": "BBB", "ranking_score": 1300}]


def _ach5():
    # input order is deliberately NOT mark order
    marks = [("S1", 490.0), ("S2", 485.0), ("S3", 495.0), ("S4", 480.0), ("S5", 488.0)]
    return [{"name": n, "country": f"X{n}", "mark": str(m), "mark_seconds": m} for n, m in marks]


def test_all_qualify_keeps_everyone_in_input_order():
    f = qualifying_field(_ranked(), 3, standard_achievers=_ach5())
    assert f["standards_policy"] == "all_qualify"
    assert [s["name"] for s in f["slots"]] == ["S1", "S2", "S3", "S4", "S5"]
    assert f["standard_places"] == 5 > f["quota"]
    assert f["ranking_places"] == 0 and f["cutoff_score"] is None
    assert f["outside_quota"] == [] and f["standards_oversubscribed"] is False
    assert athlete_status(f, "S3")[0] == "qualified"


def test_best_performances_orders_by_mark_and_closes_ranking():
    f = qualifying_field(_ranked(), 3, standard_achievers=_ach5(),
                         standards_policy="best_performances")
    assert [s["name"] for s in f["slots"]] == ["S4", "S2", "S5"]
    assert [o["name"] for o in f["outside_quota"]] == ["S1", "S3"]
    assert f["standards_oversubscribed"] is True
    assert f["ranking_places"] == 0 and f["cutoff_score"] is None
    assert athlete_status(f, "S3")[0] == "standard_outside_quota"
    assert athlete_status(f, "R1")[0] == "out"


def test_best_performances_undersubscribed_fills_by_ranking():
    f = qualifying_field(_ranked(), 4, standard_achievers=_ach5()[:2],
                         standards_policy="best_performances")
    assert [s["reason"] for s in f["slots"]] == ["entry standard"] * 2 + ["ranking"] * 2
    assert f["cutoff_score"] == 1300 and f["standards_oversubscribed"] is False


def test_best_performances_tie_for_last_place_reported():
    ach = [{"name": n, "country": n, "mark": "m", "mark_seconds": s}
           for n, s in (("A", 480.0), ("B", 481.0), ("C", 481.0))]
    f = qualifying_field([], 2, standard_achievers=ach, standards_policy="best_performances")
    assert set(f["standards_tied"]) == {"B", "C"}
    # all_qualify never has a tie problem
    assert qualifying_field([], 2, standard_achievers=ach)["standards_tied"] == []


def test_best_performances_unknown_marks_last_input_order_kept():
    ach = [{"name": "U1", "country": "A", "mark": None, "mark_seconds": None},
           {"name": "K1", "country": "B", "mark": "m", "mark_seconds": 500.0},
           {"name": "U2", "country": "C", "mark": None, "mark_seconds": None}]
    f = qualifying_field([], 3, standard_achievers=ach, standards_policy="best_performances")
    assert [s["name"] for s in f["slots"]] == ["K1", "U1", "U2"]


# ------------------------------------------------------------------ 7. Beijing unchanged
def test_beijing_policy_and_byes_unchanged(patch):
    patch("1500m_men")
    q = _wi(perf_date=AS_OF, champ=BJ)["qualification"]
    assert q["standards_policy"] == "all_qualify"
    assert q["standards_oversubscribed"] is False and q["standards_tied"] == []
    names = {i["name"] for i in q["auto_invites"]}
    assert "Isaac NADER" in names and "Josh KERR" in names
    assert q["quota"] == 56
    assert q["projection_only"] is True            # no snapshot -> standard achievers unknown


def test_beijing_over_quota_achievers_all_get_in(patch):
    patch("1500m_men")
    ach = _achievers(60, start=200.0, step=0.1)     # 3:20.00 ..; 60 > quota 56
    q = _wi(time="3:29.00", perf_date=AS_OF, champ=BJ, achievers=ach)["qualification"]
    assert q["route_new"] == "standard"
    assert q["standards_oversubscribed"] is False
    assert q["status_new"] == "qualified"
    assert len(q["field_new"]) >= 60
    # slowest of all still in
    slow = _wi(time="3:29.90", perf_date=AS_OF, champ=BJ, achievers=ach)["qualification"]
    assert slow["route_new"] != "standard_outside_quota" and slow["route_new"] == "standard"


# ------------------------------------------------------------------ 8. tracking_status / meta
def test_tracking_status(monkeypatch):
    assert feed.tracking_status(LA, "1500m_men")["status"] == "not_configured"
    monkeypatch.setattr(feed, "read_feed",
                        lambda *a, **k: {"quota": 56, "fetched": "2026-11-10T06:00:00"})
    t = feed.tracking_status(BJ, "1500m_men")
    assert t["status"] == "snapshot" and t["fetched"] == "2026-11-10T06:00:00"
    monkeypatch.setattr(feed, "read_feed", lambda *a, **k: None)
    assert feed.tracking_status(BJ, "1500m_men")["status"] == "missing"
    # LA28 stays "not_configured" whatever read_feed does
    monkeypatch.setattr(feed, "read_feed", lambda *a, **k: {"quota": 1, "fetched": "x"})
    t = feed.tracking_status(LA, "1500m_men")
    assert t["status"] == "not_configured" and t["fetched"] is None
    assert t["expected"] == "autumn 2027"


def test_meta_la28_entry():
    m = api.meta()
    assert [c["key"] for c in m["championships"]] == ["world", "road_to_beijing", "road_to_la28"]
    ch = {c["key"]: c for c in m["championships"]}
    la, bj = ch[LA], ch[BJ]
    assert la["planning"] is True and bj["planning"] is False
    assert la["has_qualification"] is True and la["max_per_country"] == 3
    assert [e["title"] for e in la["explainers"]] and bj["explainers"] == []
    assert la["source"]["version"] == "9 November 2026"
    assert la["data_status"]["official_tracking"] == "not_published"
    assert la["qualification_policy"]["standards_over_quota"] == "best_performances"
    assert not any(k.startswith("_") for k in la["qualification_policy"])
    w = la["qualification_windows"]
    assert set(w) == set(OFFICIAL)
    for ev in OFFICIAL:
        start = "2026-12-19" if ev.startswith("10000m") else "2027-06-19"
        assert w[ev] == {"start": start, "end": WINDOW_END}, ev
    assert la["standards"] == {ev: s for ev, (s, _) in OFFICIAL.items()}
    # 5km road is offered as an input event on the 5000m
    ev5 = next(e for e in m["events"] if e["key"] == "5000m_men")
    assert {"key": "5km", "label": "5km (road)", "is_main": False, "indoor": False,
            "road": True} in ev5["input_events"]


# ------------------------------------------------------------------ 9. reverse solver
def test_required_targets_labels(patch):
    patch("1500m_men")
    la = whatif.required_targets("1500m_men", "Test Runner", championship=LA, place=1, category="GW")
    labels = [t["label"] for t in la["targets"]]
    assert "reach the projected ranking cutoff" in labels
    assert "reach the qualifying cutoff" not in labels
    std = la["targets"][0]
    assert std["kind"] == "standard" and std["time"] == "3:30.00"
    assert std["status"] == "reachable"
    bj = whatif.required_targets("1500m_men", "Test Runner", championship=BJ, place=1, category="GW")
    blabels = [t["label"] for t in bj["targets"]]
    assert "reach the qualifying cutoff" in blabels
    assert "reach the projected ranking cutoff" not in blabels
    assert bj["targets"][0]["kind"] == "standard" and bj["targets"][0]["time"] == "3:30.00"


def test_what_would_it_take_uses_projected_label(patch):
    patch("1500m_men")
    r = _wi(perf_date=D_IN)
    labels = [t["label"] for t in r["what_would_it_take"]["targets"]]
    assert labels[0] == "meet the entry standard"
    assert "reach the projected ranking cutoff" in labels
