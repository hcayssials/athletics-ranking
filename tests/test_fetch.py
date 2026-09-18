"""Data-layer parsing + the steeplechase GraphQL fallback (no network; fixtures/stubs)."""
import json

from wa_ranking import cache, fetch

# A minimal but realistic ranking-list row (the page is server-rendered HTML).
_HTML = """
<table><tbody>
  <tr data-id="14296364" data-athlete-url="jakob-ingebrigtsen/14296364">
    <td data-th="Rank">1</td>
    <td data-th="Competitor">Jakob INGEBRIGTSEN</td>
    <td data-th="DOB">19 SEP 2000</td>
    <td data-th="Nat">NOR</td>
    <td data-th="score">1452</td>
  </tr>
  <tr data-id="99999" data-athlete-url="no-name/99999">
    <td data-th="Rank">2</td>
    <td data-th="Nat">GBR</td>
  </tr>
</tbody></table>
"""


def test_parse_ranking_html_extracts_rows():
    rows = fetch.parse_ranking_html(_HTML)
    # Second row has no "Competitor" cell -> skipped as a non-data row.
    assert len(rows) == 1
    r = rows[0]
    assert r["competitor_id"] == "14296364"
    assert r["slug"] == "jakob-ingebrigtsen/14296364"
    assert r["rank"] == 1
    assert r["name"] == "Jakob INGEBRIGTSEN"
    assert r["country"] == "NOR"
    assert r["ranking_score"] == 1452.0


def test_parse_ranking_html_empty_when_no_rows():
    assert fetch.parse_ranking_html("<html><body>no table here</body></html>") == []


def test_normalize_performance_maps_wa_keys():
    p = fetch.normalize_performance({
        "date": "10 JUN 2024", "competition": "European Athletics Championships",
        "category": "GL", "disciplineCode": "3KSC", "place": "P6", "mark": " 8:09.00 ",
        "resultScore": 1200, "placingScore": 25, "performanceScore": 1225,
        "monthCorrectionApplied": True,
    })
    assert p["date"] == "2024-06-10"
    assert p["discipline_code"] == "3KSC"
    assert p["place"] == 6
    assert p["mark"] == "8:09.00"
    assert p["performance_score"] == 1225
    assert p["month_correction_applied"] is True


def test_decode_calc_handles_double_encoded_json():
    inner = {"athlete": "X", "results": []}
    assert fetch._decode_calc(json.dumps(json.dumps(inner))) == inner  # string-of-string
    assert fetch._decode_calc(json.dumps(inner)) == inner              # plain object


def test_mens_steeplechase_falls_back_to_graphql(monkeypatch, tmp_path):
    """Men's steeplechase list isn't server-rendered, so an empty HTML parse must trigger
    the GraphQL fallback (the event declares graphql_event_group)."""
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)            # force a cache miss
    monkeypatch.setattr(cache, "SEED_DIR", tmp_path / "no_seed")

    class _Resp:
        text = "<html>no table</html>"
        def raise_for_status(self):
            pass

    monkeypatch.setattr(fetch.requests.Session, "get", lambda self, *a, **k: _Resp())
    used_graphql = {}

    def _fake_graphql(ev, champ):
        used_graphql["called"] = True
        return [{"competitor_id": "1", "slug": "s", "rank": 1, "name": "Steeler",
                 "country": "KEN", "ranking_score": 1300.0}]

    monkeypatch.setattr(fetch, "_rankings_via_graphql", _fake_graphql)
    monkeypatch.setattr(fetch, "fetch_athlete_calculation",
                        lambda cid, url, session=None: {"performances": [], "rank_date": "2026-06-16"})

    data = fetch.fetch_championship("road_to_birmingham", "3000mSC_men", force=True)
    assert used_graphql.get("called") is True
    assert data["athletes"][0]["name"] == "Steeler"


def _calc_payload(avg, score, wr=()):
    return {"athlete": "Emmanuel WANYONYI", "athleteUrlSlug": "kenya/emmanuel-wanyonyi-14974928",
            "country": "KEN", "rankDate": "01 SEP 2026", "place": 1,
            "averagePerformanceScore": avg, "rankingScore": score, "wrResults": list(wr),
            "results": [{"date": "10 JUL 2026", "disciplineCode": "1000", "mark": "2:11.83",
                         "place": "1.", "performanceScore": 1393}]}


def test_wr_bonus_is_ranking_score_minus_average():
    # WA's per-record wrBonus reads 0 even when the bonus applies, so it must not be used.
    wr = [{"date": "10 JUL 2026", "competition": "Herculis, Monaco", "category": "GW",
           "disciplineCode": "1000", "indoor": False, "mark": "2:11.83", "wrBonus": 0}]
    assert fetch.wr_bonus(_calc_payload(1424, 1434, wr)) == 10
    assert fetch.wr_bonus(_calc_payload(1382, 1382)) == 0
    assert fetch.wr_bonus({"results": []}) == 0                   # older payload: no fields


def test_fetch_athlete_calculation_keeps_wr_bonus_and_records():
    wr = [{"date": "10 JUL 2026", "competition": "Herculis, Monaco", "category": "GW",
           "disciplineCode": "1000", "indoor": False, "mark": " 2:11.83 ", "wrBonus": 0}]

    class _Resp:
        text = json.dumps(json.dumps(_calc_payload(1424, 1434, wr)))
        def raise_for_status(self):
            pass

    class _Session:
        def get(self, url, **k):
            assert url.endswith("competitorId=139983837")
            return _Resp()

    calc = fetch.fetch_athlete_calculation("139983837", "https://x/?competitorId={competitor_id}",
                                           _Session())
    assert calc["wr_bonus"] == 10
    assert calc["wr_results"] == [{"date": "2026-07-10", "competition": "Herculis, Monaco",
                                   "category": "GW", "discipline_code": "1000",
                                   "indoor": False, "mark": "2:11.83"}]
    assert calc["performances"][0]["performance_score"] == 1393


def test_fetch_championship_carries_wr_bonus_onto_athletes(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cache, "SEED_DIR", tmp_path / "no_seed")

    class _Resp:
        text = _HTML
        def raise_for_status(self):
            pass

    monkeypatch.setattr(fetch.requests.Session, "get", lambda self, *a, **k: _Resp())
    monkeypatch.setattr(fetch, "fetch_athlete_calculation", lambda cid, url, session=None: {
        "performances": [], "rank_date": "2026-09-01", "wr_bonus": 10,
        "wr_results": [{"discipline_code": "MILE"}]})
    a = fetch.fetch_championship("world", "1500m_men", force=True)["athletes"][0]
    assert a["wr_bonus"] == 10 and a["wr_results"] == [{"discipline_code": "MILE"}]
