"""WA qualification-feed parsing + the config overlay (no network; stubbed payloads).

feed.py is a network-only module like fetch/profile/graphql, so its parsing and overlay are
covered here with a trimmed copy of what WA's `getChampionshipQualifications` returns for the
Road to Beijing 27 — see the landmine note in CLAUDE.md.
"""
import pytest

from wa_ranking import cache, feed, graphql

# One event's payload, trimmed to the shape WA returns for Beijing 27 (Sep 2026).
PAYLOAD = {
    "eventId": 10229502, "entryNumber": 56, "entryStandard": "3:30.00",
    "maxCompetitorsByCoutnry": 3,
    "firstQualificationDay": "23 AUG 2026", "lastQualificationDay": "22 AUG 2027",
    "rankDate": "22 AUG 2027",
    "numberOfCompetitorsQualifiedByEntryStandard": 3,
    "numberOfCompetitorsFilledUpByWorldRankings": 21,
    "disciplineName": "Men's 1500 Metres",
    "alternativeEntryStandards": [{"entryStandard": "3:50.00", "event": "Mile"},
                                  {"entryStandard": "3:50.00", "event": "Mile Road"}],
    "qualifications": [
        {"qualifiedBy": "Qualified", "qualified": True, "qualificationPosition": 1,
         "name": "Isaac NADER", "countryCode": "POR", "score": None,
         "urlSlug": "portugal/isaac-nader-14743337", "label": "Defending World Champion",
         "result": None, "date": None, "venue": None},
        {"qualifiedBy": "Qualified by Entry Standard", "qualified": True, "qualificationPosition": 2,
         "name": "Josh KERR", "countryCode": "GBR", "score": None,
         "urlSlug": "great-britain-ni/josh-kerr-14582777", "label": None,
         "result": "3:29.35", "date": "13 SEP 2026", "venue": "Budapest (HUN)"},
        {"qualifiedBy": "Qualified by Entry Standard", "qualified": True, "qualificationPosition": 3,
         "name": "Cameron MYERS", "countryCode": "AUS", "score": None,
         "urlSlug": "australia/cameron-myers-15012345", "label": None,
         "result": "3:29.68", "date": "13 SEP 2026", "venue": "Budapest (HUN)"},
        {"qualifiedBy": "In World Rankings quota*", "qualified": True, "qualificationPosition": 4,
         "name": "Ethan STRAND", "countryCode": "USA", "score": 1314,
         "urlSlug": "united-states/ethan-strand-14900000", "label": None,
         "result": None, "date": None, "venue": None},
        {"qualifiedBy": "Next best by World Rankings", "qualified": False, "qualificationPosition": None,
         "name": "Hobbs KESSLER", "countryCode": "USA", "score": 1287,
         "urlSlug": "united-states/hobbs-kessler-14709999", "label": None,
         "result": None, "date": None, "venue": None},
    ],
}


def test_parse_feed_reads_quota_standard_window_byes_and_achievers():
    f = feed.parse_feed(PAYLOAD)
    assert f["quota"] == 56                       # WA's entryNumber IS the target field
    assert f["entry_standard"] == "3:30.00"
    assert f["alt_entry_standards"] == [{"event": "Mile", "entry_standard": "3:50.00"},
                                        {"event": "Mile Road", "entry_standard": "3:50.00"}]
    assert f["max_per_country"] == 3
    assert f["window"] == {"start": "2026-08-23", "end": "2027-08-22"}
    assert f["rank_date"] == "2027-08-22"
    assert f["counts"] == {"entry_standard": 3, "world_rankings": 21}
    assert f["auto_invites"] == [{"name": "Isaac NADER", "country": "POR",
                                  "reason": "Defending World Champion"}]
    assert [a["name"] for a in f["standard_achievers"]] == ["Josh KERR", "Cameron MYERS"]
    assert f["standard_achievers"][0] == {"name": "Josh KERR", "country": "GBR", "mark": "3:29.35",
                                          "date": "2026-09-13", "venue": "Budapest (HUN)",
                                          "slug": "great-britain-ni/josh-kerr-14582777"}


def test_parse_feed_ultimate_style_wildcards_and_map_labels():
    f = feed.parse_feed({"entryNumber": 12, "qualifications": [
        {"qualifiedBy": "Qualified by Wild Card", "name": "A", "countryCode": "SWE",
         "urlSlug": "sweden/a-1", "label": "{label=Olympic Champion}"},
        {"qualifiedBy": "Qualified by Wild Card", "name": "B", "countryCode": "NOR",
         "urlSlug": "norway/b-2", "label": None},
        {"qualifiedBy": "Qualified", "name": "C", "countryCode": "USA",   # no label -> not a bye
         "urlSlug": "usa/c-3", "label": None},
    ]})
    assert [(i["name"], i["reason"]) for i in f["auto_invites"]] == [("A", "Olympic Champion"),
                                                                     ("B", "wildcard")]
    assert f["entry_standard"] is None and f["window"] is None and f["standard_achievers"] == []


def test_athlete_key_matches_the_two_slug_spellings():
    assert (feed.athlete_key("/athletes/kenya/faith-kipyegon-14413305", "Faith KIPYEGON")
            == feed.athlete_key("kenya/faith-kipyegon-14413305", "Faith KIPYEGON"))
    assert feed.athlete_key(None, "Faith KIPYEGON") == "FAITH KIPYEGON"   # name fallback


def test_event_qualification_overlays_the_snapshot(monkeypatch):
    snapshot = {**feed.parse_feed(PAYLOAD), "fetched": "2026-09-18T06:00:00"}
    monkeypatch.setattr(feed, "read_feed", lambda *a, **k: snapshot)
    cfg = feed.event_qualification("road_to_beijing", "1500m_men")
    assert cfg["quota"] == 56 and cfg["entry_standard"] == "3:30.00"
    assert cfg["qualification_window"] == {"start": "2026-08-23", "end": "2027-08-22"}
    # Feed byes first (WA's label), then the hand-maintained Ultimate winner the feed lacks —
    # and a name in both lists appears once.
    assert [i["name"] for i in cfg["auto_invites"]] == ["Isaac NADER", "Josh KERR"]
    assert cfg["auto_invites"][0]["reason"] == "Defending World Champion"
    assert cfg["auto_invites"][1]["source"] == "manual"
    assert [a["name"] for a in cfg["standard_achievers"]] == ["Josh KERR", "Cameron MYERS"]
    assert cfg["qualification_source"] == "feed" and cfg["feed_fetched"]
    assert "defending_champion" not in cfg


def test_event_qualification_falls_back_to_json_without_a_snapshot(monkeypatch):
    monkeypatch.setattr(feed, "read_feed", lambda *a, **k: None)
    cfg = feed.event_qualification("road_to_beijing", "1500m_men")
    assert cfg["quota"] == 56 and cfg["entry_standard"] == "3:30.00"
    assert "standard_achievers" not in cfg          # unknown, not empty
    assert cfg["qualification_source"] == "config"
    assert [i["name"] for i in cfg["auto_invites"]] == ["Isaac NADER", "Josh KERR"]
    # A championship without any feed: config, untouched.
    b = feed.event_qualification("road_to_birmingham", "1500m_men")
    assert b["quota"] == 30 and b["defending_champion"]["name"] == "Jakob INGEBRIGTSEN"
    # No config at all for the event -> {} (e.g. the world ranking).
    assert feed.event_qualification("world", "1500m_men") == {}


def test_fetch_feed_normalises_and_caches(monkeypatch):
    calls = {}

    def fake_query(query, variables):
        calls["vars"] = variables
        return {"getChampionshipQualifications": PAYLOAD}

    monkeypatch.setattr(graphql, "query", fake_query)
    written = {}
    monkeypatch.setattr(cache, "write", lambda k, d: written.update({k: d}))
    monkeypatch.setattr(cache, "read", lambda *a, **k: None)

    out = feed.fetch_feed("road_to_beijing", "1500m_men")
    assert calls["vars"] == {"competitionId": 7216591, "eventId": 10229502}
    assert out["quota"] == 56 and out["event"] == "1500m_men" and out["fetched"]
    assert written["feed__road_to_beijing__1500m_men"]["entry_standard"] == "3:30.00"


def test_fetch_feed_rejects_an_event_with_no_feed():
    with pytest.raises(KeyError):
        feed.fetch_feed("road_to_birmingham", "1500m_men")
    with pytest.raises(KeyError):
        feed.fetch_feed("world", "1500m_men")


def test_fetch_feed_raises_when_wa_returns_nothing(monkeypatch):
    monkeypatch.setattr(cache, "read", lambda *a, **k: None)
    monkeypatch.setattr(graphql, "query", lambda q, v: {"getChampionshipQualifications": None})
    with pytest.raises(RuntimeError, match="no qualification feed"):
        feed.fetch_feed("road_to_beijing", "1500m_men")


def test_committed_seed_snapshots_agree_with_the_config():
    """The seeded feed (what the site ships) must not silently drift from championships.json —
    if WA changes a standard or the quota, both should move together."""
    from wa_ranking.config import championship_event_config, load_championship
    champ = load_championship("road_to_beijing")
    for ek in feed.feed_events("road_to_beijing"):
        snap = feed.read_feed("road_to_beijing", ek, ttl_seconds=None)
        assert snap is not None, f"missing seed snapshot for {ek}"
        cfg = championship_event_config("road_to_beijing", ek)
        assert snap["quota"] == cfg["quota"], ek
        assert snap["entry_standard"] == cfg["entry_standard"], ek
        assert snap["max_per_country"] == champ["max_per_country"], ek
        assert snap["window"] == (cfg.get("qualification_window") or champ["qualification_window"]), ek
        # The defending champion WA labels is the one we list first.
        assert snap["auto_invites"][0]["name"] == cfg["auto_invites"][0]["name"], ek
