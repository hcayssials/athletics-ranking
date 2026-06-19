"""fetch_profile end-to-end with the network stubbed (regression guard for the unranked path).

Catches breakages in the profile flow that the network-dependent path otherwise hides —
e.g. a missing import used only when building the final result dict.
"""
from datetime import date

from wa_ranking import cache, graphql, profile

_NEXT_DATA = (
    '<script id="__NEXT_DATA__" type="application/json">'
    '{"props":{"pageProps":{"competitor":{'
    '"basicData":{"countryCode":"GBR"},'
    '"worldRankings":{"current":[],"best":[]},'
    '"resultsByYear":{"resultsByEvent":[]}}}}}'
    "</script>"
)


class _Resp:
    text = _NEXT_DATA

    def raise_for_status(self):
        pass


def _stub_network(monkeypatch, tmp_path, *, results_by_year):
    """results_by_year: {year -> resultsByEvent list}. GraphQL is queried once per year."""
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cache, "SEED_DIR", tmp_path / "no_seed")
    monkeypatch.setattr(profile.requests, "get", lambda *a, **k: _Resp())

    def _query(_q, variables, **k):
        rbe = results_by_year.get(variables["resultsByYear"], [])
        return {"getSingleCompetitorResultsDiscipline": {"resultsByEvent": rbe}}

    monkeypatch.setattr(graphql, "query", _query)


def test_fetch_profile_builds_result_no_network(monkeypatch, tmp_path):
    _stub_network(monkeypatch, tmp_path, results_by_year={})
    r = profile.fetch_profile("jake-heyward-14597392", "1500m_men", date(2026, 6, 19), 12, force=True)
    assert r["name"] == "Jake Heyward"
    assert r["country"] == "GBR"
    assert r["ranked"] is False
    assert r["performances"] == []
    assert r["fetched"]          # built without error (regressed when datetime import was dropped)


def test_fetch_profile_keeps_in_window_main_results(monkeypatch, tmp_path):
    event_2026 = [{
        "discipline": "1500 Metres",
        "results": [
            {"date": "10 MAY 2026", "competition": "Meet", "category": "B",
             "place": "1", "mark": "3:33.00", "resultScore": 1180},
        ],
    }]
    event_2025 = [{
        "discipline": "1500 Metres",
        "results": [
            {"date": "10 MAY 2020", "competition": "Old", "category": "B",   # outside the window
             "place": "1", "mark": "3:40.00", "resultScore": 1000},
        ],
    }]
    _stub_network(monkeypatch, tmp_path, results_by_year={2026: event_2026, 2025: event_2025})
    r = profile.fetch_profile("jake-heyward-14597392", "1500m_men", date(2026, 6, 19), 12, force=True)
    assert len(r["performances"]) == 1
    assert r["performances"][0]["date"] == "2026-05-10"
