"""WA qualification-feed parsing + the not-in-the-field derivation (no network; stubs).

feed.py is a network-only module like fetch/profile/graphql, so it's covered here with
stubbed payloads — see the landmine note in CLAUDE.md.
"""
import pytest

from wa_ranking import feed

# One event's getChampionshipQualifications payload, trimmed to the shape WA returns.
# `label` really does arrive as a stringified map, and the tail rows are the "next best".
PAYLOAD = {
    "entryNumber": 13,
    "disciplineName": "Men's 1500 Metres",
    "qualifications": [
        {"qualifiedBy": "Qualified by Wild Card", "name": "Isaac NADER", "countryCode": "POR",
         "score": None, "urlSlug": "portugal/isaac-nader-14743337",
         "label": "{label=World Champion}", "qualificationPosition": 1, "qualified": True},
        {"qualifiedBy": "Qualified by Wild Card", "name": "Josh KERR", "countryCode": "GBR",
         "score": None, "urlSlug": "great-britain-ni/josh-kerr-14582777",
         "label": "{label=Exceptional Invitation}", "qualificationPosition": 2, "qualified": True},
        {"qualifiedBy": "Qualified by World Rankings", "name": "Cameron MYERS", "countryCode": "AUS",
         "score": 1372, "urlSlug": "australia/cameron-myers-15012345",
         "label": None, "qualificationPosition": 3, "qualified": True},
        {"qualifiedBy": "Next best by World Rankings", "name": "Hobbs KESSLER", "countryCode": "USA",
         "score": 1287, "urlSlug": "united-states/hobbs-kessler-14709999",
         "label": None, "qualificationPosition": None, "qualified": False},
    ],
}


def athlete(name, score, slug):
    return {"name": name, "country": "XXX", "ranking_score": score, "slug": slug}


def test_parse_feed_reads_field_size_wildcards_and_tail():
    f = feed.parse_feed(PAYLOAD)
    assert f["quota"] == 13                      # WA's entryNumber IS the field size
    assert f["auto_invites"] == [
        {"name": "Isaac NADER", "country": "POR", "reason": "World Champion"},
        {"name": "Josh KERR", "country": "GBR", "reason": "Exceptional Invitation"},
    ]
    assert f["tail_score"] == 1287               # lowest listed score = the floor
    assert len(f["in_field"]) == 4               # wildcards + qualifiers + next-best


def test_parse_feed_handles_missing_label_and_scores():
    f = feed.parse_feed({"entryNumber": 8, "qualifications": [
        {"qualifiedBy": "Qualified by Wild Card", "name": "A", "countryCode": "SWE",
         "score": None, "urlSlug": "sweden/a-1", "label": None}]})
    assert f["auto_invites"][0]["reason"] == "wildcard"
    assert f["tail_score"] is None


def test_athlete_key_matches_the_two_slug_spellings():
    # Ranking rows carry '/athletes/...', the feed doesn't; the trailing WA id is the join.
    assert (feed.athlete_key("/athletes/kenya/faith-kipyegon-14413305", "Faith KIPYEGON")
            == feed.athlete_key("kenya/faith-kipyegon-14413305", "Faith KIPYEGON"))
    assert feed.athlete_key(None, "Faith KIPYEGON") == "FAITH KIPYEGON"   # name fallback


def test_derive_not_in_field_flags_only_above_the_tail():
    f = feed.parse_feed(PAYLOAD)
    athletes = [
        athlete("Cameron MYERS", 1372, "/athletes/australia/cameron-myers-15012345"),  # listed
        athlete("Faith ABSENT", 1320, "/athletes/kenya/faith-absent-14413305"),        # missing
        athlete("Hobbs KESSLER", 1287, "/athletes/united-states/hobbs-kessler-14709999"),
        athlete("Deep DOWNLIST", 1100, "/athletes/spain/deep-downlist-14000001"),      # below tail
        athlete("No SCORE", None, "/athletes/spain/no-score-14000002"),
    ]
    absent = feed.derive_not_in_field(athletes, f)
    assert [a["name"] for a in absent] == ["Faith ABSENT"]
    assert absent[0]["score"] == 1320 and absent[0]["reason"] == "not in the field"


def test_derive_not_in_field_says_nothing_without_a_tail():
    assert feed.derive_not_in_field([athlete("X", 1300, "/a/x-1")], {"in_field": [], "tail_score": None}) == []


def test_event_qualification_overlays_the_snapshot(monkeypatch):
    snapshot = {**feed.parse_feed(PAYLOAD), "fetched": "2026-08-31T06:00:00"}
    monkeypatch.setattr(feed, "read_feed", lambda *a, **k: snapshot)
    athletes = [athlete("Faith ABSENT", 1320, "/athletes/kenya/faith-absent-14413305")]
    cfg = feed.event_qualification("road_to_ultimate", "1500m_men", athletes)
    assert cfg["quota"] == 13                                  # feed wins over the JSON quota
    assert [i["name"] for i in cfg["auto_invites"]] == ["Isaac NADER", "Josh KERR"]
    assert [a["name"] for a in cfg["not_in_field"]] == ["Faith ABSENT"]
    assert cfg["qualification_source"] == "feed"


def test_event_qualification_falls_back_to_json_without_a_snapshot(monkeypatch):
    monkeypatch.setattr(feed, "read_feed", lambda *a, **k: None)
    cfg = feed.event_qualification("road_to_ultimate", "1500m_men", [])
    assert cfg["quota"] == 13                                  # championships.json fallback
    assert "not_in_field" not in cfg
    assert cfg.get("qualification_source") is None
    # Birmingham declares no feed at all: config, untouched.
    assert feed.event_qualification("road_to_birmingham", "1500m_men", [])["quota"] == 30


def test_fetch_feed_normalises_and_caches(monkeypatch):
    from wa_ranking import cache, graphql
    calls = {}

    def fake_query(query, variables):
        calls["vars"] = variables
        return {"getChampionshipQualifications": PAYLOAD}

    monkeypatch.setattr(graphql, "query", fake_query)
    written = {}
    monkeypatch.setattr(cache, "write", lambda k, d: written.update({k: d}))
    monkeypatch.setattr(cache, "read", lambda *a, **k: None)

    out = feed.fetch_feed("road_to_ultimate", "1500m_men")
    assert calls["vars"] == {"competitionId": 7212925, "eventId": 10229502}
    assert out["quota"] == 13 and out["event"] == "1500m_men"
    assert written["feed__road_to_ultimate__1500m_men"]["quota"] == 13


def test_fetch_feed_rejects_an_event_with_no_feed():
    with pytest.raises(KeyError):
        feed.fetch_feed("road_to_ultimate", "10000m_men")
    with pytest.raises(KeyError):
        feed.fetch_feed("road_to_birmingham", "1500m_men")


def test_fetch_feed_raises_when_wa_returns_nothing(monkeypatch):
    from wa_ranking import cache, graphql
    monkeypatch.setattr(cache, "read", lambda *a, **k: None)
    monkeypatch.setattr(graphql, "query", lambda q, v: {"getChampionshipQualifications": None})
    with pytest.raises(RuntimeError, match="no qualification feed"):
        feed.fetch_feed("road_to_ultimate", "1500m_men")
