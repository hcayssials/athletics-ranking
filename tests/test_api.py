"""API tests via FastAPI TestClient. Hermetic: the WA fetch is monkeypatched to a fixture,
so the real scoring/ranking/qualification logic runs without any network."""
import os

os.environ["PREWARM"] = "off"  # don't kick off the boot-time cache warm during tests

import pytest
from fastapi.testclient import TestClient

from wa_ranking import feed, fetch
from wa_ranking.api import app

client = TestClient(app)


def _perf(score, d, disc="1500", comp="Meet"):
    return {"performance_score": score, "date": d, "discipline_code": disc,
            "competition": comp, "category": "GW", "place": 2, "mark": "3:33.00",
            "result_score": score - 120, "placing_score": 120}


def _fixture():
    def athlete(rank, name, country, score, perfs):
        return {"competitor_id": f"id{rank}", "slug": f"/a/{name}", "rank": rank,
                "name": name, "country": country, "ranking_score": score,
                "performances": perfs, "rank_date": "2026-06-16"}
    perfs = [_perf(s, "2026-05-01") for s in (1380, 1360, 1340, 1320, 1300)]
    return {"championship": "road_to_birmingham", "event": "1500m_men",
            "rank_date": "2026-06-16",
            "athletes": [athlete(1, "Alpha RUNNER", "GBR", 1350, perfs),
                         athlete(2, "Beta RUNNER", "FRA", 1330, perfs)]}


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr(fetch, "fetch_championship",
                        lambda *a, **k: _fixture())  # used by both api + whatif
    # No feed snapshot: these tests exercise the championships.json fallback path. The
    # feed overlay has its own tests (test_feed.py) with a stubbed snapshot.
    monkeypatch.setattr(feed, "read_feed", lambda *a, **k: None)


def test_health():
    assert client.get("/api/health").json() == {"ok": True}


def test_meta_lists_events_and_championships():
    m = client.get("/api/meta").json()
    keys = {e["key"] for e in m["events"]}
    assert {"1500m_men", "3000mSC_women"} <= keys
    assert {c["key"] for c in m["championships"]} == {"world", "road_to_birmingham",
                                                      "road_to_ultimate"}
    assert "GW" in m["categories"]
    champs = {c["key"]: c for c in m["championships"]}
    assert champs["road_to_birmingham"]["has_qualification"] is True
    assert champs["road_to_birmingham"]["not_contested"] == []
    assert champs["world"]["has_qualification"] is False
    ult = champs["road_to_ultimate"]
    assert ult["has_qualification"] is True
    assert set(ult["not_contested"]) == {"10000m_men", "10000m_women",
                                         "3000mSC_men", "3000mSC_women"}
    assert ult["not_contested_note"]
    assert ult["max_per_country"] is None
    assert "Diamond League Final" in ult["qualification_footnote"]


def test_rankings_ultimate_includes_wildcards():
    r = client.get("/api/rankings", params={"championship": "road_to_ultimate",
                                            "event": "1500m_men"}).json()
    assert r["quota"] == 13                      # 12 + an extra exceptional invitation
    assert r["max_per_country"] is None
    assert {i["name"] for i in r["auto_invites"]} == {"Cole HOCKER", "Isaac NADER",
                                                      "Josh KERR", "Jakob INGEBRIGTSEN"}
    assert r["not_in_field"] == [] and r["qualification_source"] == "config"


def test_whatif_ultimate_qualification_no_cap():
    body = {"event": "1500m_men", "athlete": "Alpha", "time": "3:28.80",
            "category": "GW", "place": 1, "as_of": "2026-06-16",
            "championship": "road_to_ultimate", "qualify": True}
    w = client.post("/api/whatif", json=body).json()
    q = w["qualification"]
    assert q["quota"] == 13 and q["max_per_country"] is None
    assert len(q["auto_invites"]) == 4
    assert q["ranking_places"] == 9
    assert q["not_in_field"] == [] and q["is_not_in_field"] is False
    # wildcards hold the first slots of the resolved field
    assert [s["reason"] for s in q["field_new"][:2]] == ["World Champion", "Olympic Champion"]


def test_whatif_ultimate_not_contested_event_is_400():
    body = {"event": "3000mSC_men", "athlete": "Alpha", "time": "8:10.00",
            "championship": "road_to_ultimate", "qualify": True}
    resp = client.post("/api/whatif", json=body)
    assert resp.status_code == 400
    assert "not be competed" in resp.json()["error"]


def test_rankings_returns_slim_rows():
    r = client.get("/api/rankings", params={"championship": "road_to_birmingham",
                                            "event": "1500m_men"}).json()
    assert r["rank_date"] == "2026-06-16" and r["quota"] == 30
    assert r["defending_champion"]["name"] == "Jakob INGEBRIGTSEN"
    a = r["athletes"][0]
    assert set(a) == {"rank", "name", "country", "ranking_score", "competitor_id", "slug"}
    assert "performances" not in a   # stripped for the table


def test_whatif_returns_structured_result():
    body = {"event": "1500m_men", "athlete": "Alpha", "time": "3:28.80",
            "category": "GW", "place": 1, "as_of": "2026-06-16", "qualify": True}
    w = client.post("/api/whatif", json=body).json()
    assert w["athlete"] == "Alpha RUNNER"
    assert w["new_score"] > w["recomputed_old_score"]      # a fast win improves the score
    assert "qualification" in w and "above_cutoff" in w["qualification"]
    assert w["hypothetical_performance"]["result_score"] == 1262  # real 1500m table lookup


def test_whatif_unknown_athlete_is_400():
    body = {"event": "1500m_men", "athlete": "Nobody", "time": "3:30"}
    resp = client.post("/api/whatif", json=body)
    assert resp.status_code == 400
    assert "error" in resp.json()
