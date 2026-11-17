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

    def _fake_graphql(ev, champ, limit=None):
        used_graphql["called"] = True
        used_graphql["limit"] = limit
        return [{"competitor_id": "1", "slug": "s", "rank": 1, "name": "Steeler",
                 "country": "KEN", "ranking_score": 1300.0}]

    monkeypatch.setattr(fetch, "_rankings_via_graphql", _fake_graphql)
    monkeypatch.setattr(fetch, "fetch_athlete_calculation",
                        lambda cid, url, session=None: {"performances": [], "rank_date": "2026-06-16"})

    data = fetch.fetch_championship("road_to_birmingham", "3000mSC_men", force=True)
    assert used_graphql.get("called") is True
    assert used_graphql["limit"] == fetch.LIST_DEPTH      # the fallback reads just as deep
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


def _page_html(start, n):
    """A ranking page of `n` rows whose ranks/ids start at `start`."""
    return "<table><tbody>" + "".join(
        f'<tr data-id="{i}" data-athlete-url="a/{i}"><td data-th="Rank">{i}</td>'
        f'<td data-th="Competitor">ATHLETE {i}</td><td data-th="Nat">KEN</td>'
        f'<td data-th="score">{2000 - i}</td></tr>' for i in range(start, start + n)
    ) + "</tbody></table>"


class _PagedSession:
    """Stands in for requests.Session: serves `pages` (page number -> html), records URLs."""
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def get(self, url, **kwargs):
        self.urls.append(url)
        page = int(url.split("page=")[1]) if "page=" in url else 1
        html = self.pages.get(page, "<html>no table</html>")

        class _Resp:
            text = html
            def raise_for_status(self):
                pass
        return _Resp()


def test_ranking_rows_reads_a_second_page():
    """WA serves 100 rows a page; the list must go past the first (the qualifying cutoff
    sat on row 100 of 100 for the women's 1500m before this)."""
    s = _PagedSession({1: _page_html(1, 100), 2: _page_html(101, 100), 3: _page_html(201, 100)})
    rows = fetch._ranking_rows("https://x/world-rankings/1500m/women", s, 200)
    assert [r["rank"] for r in rows] == list(range(1, 201))
    assert s.urls == ["https://x/world-rankings/1500m/women",
                      "https://x/world-rankings/1500m/women?page=2"]   # page 1 = bare URL


def test_ranking_rows_stops_when_wa_runs_out():
    short = _PagedSession({1: _page_html(1, 100), 2: _page_html(101, 30)})
    assert len(fetch._ranking_rows("https://x/r", short, 400)) == 130
    assert len(short.urls) == 2                                        # short page = last page
    empty = _PagedSession({1: _page_html(1, 100)})
    assert len(fetch._ranking_rows("https://x/r", empty, 200)) == 100
    # A site that ignores ?page and repeats page 1 must not loop or duplicate athletes.
    repeat = _PagedSession({1: _page_html(1, 100), 2: _page_html(1, 100), 3: _page_html(1, 100)})
    assert len(fetch._ranking_rows("https://x/r", repeat, 300)) == 100
    assert len(repeat.urls) == 2


def test_ranking_rows_respects_depth_and_existing_query_string():
    s = _PagedSession({1: _page_html(1, 100), 2: _page_html(101, 100)})
    assert len(fetch._ranking_rows("https://x/r?regionType=world", s, 150)) == 150
    assert s.urls[1] == "https://x/r?regionType=world&page=2"
    one = _PagedSession({1: _page_html(1, 100), 2: _page_html(101, 100)})
    assert len(fetch._ranking_rows("https://x/r", one, 20)) == 20 and len(one.urls) == 1
