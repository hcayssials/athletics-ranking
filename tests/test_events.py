"""Tests covering the multi-event expansion (800/1500/5000/10000, men & women)."""
import pytest

from wa_ranking.config import (DATA_DIR, championship_event_config, load_championships,
                               load_event, load_events)
from wa_ranking.scoring import placing_score, result_score

ALL_EVENTS = ["800m_men", "800m_women", "1500m_men", "1500m_women",
              "5000m_men", "5000m_women", "10000m_men", "10000m_women",
              "3000mSC_men", "3000mSC_women"]


def test_all_events_present_and_well_formed():
    events = load_events()
    assert set(ALL_EVENTS) <= set(events)
    for ek in ALL_EVENTS:
        ev = load_event(ek)
        assert (DATA_DIR / ev["result_table"]).exists()
        assert ev["best_n"] >= 1 and ev["main_event_min"] >= 1
        assert ev["main_event_codes"]
        assert ev["placing_event_group"] in load_placing_groups()


def load_placing_groups():
    from wa_ranking.config import load_placing_scores
    return {k for k in load_placing_scores() if not k.startswith("_")}


def test_event_specific_n_and_window():
    assert load_event("800m_men")["best_n"] == 5
    assert load_event("5000m_men")["best_n"] == 3
    assert load_event("10000m_men")["best_n"] == 2
    assert load_event("10000m_women")["window_months"] == 18
    assert load_event("1500m_men")["window_months"] == 12
    # steeplechase: like the 5000m group (N=3, min 2), 12-month window, 5000m placing table
    assert load_event("3000mSC_men")["best_n"] == 3
    assert load_event("3000mSC_men")["main_event_min"] == 2
    assert load_event("3000mSC_women")["placing_event_group"] == "5000m"


@pytest.mark.parametrize("event,time,expected", [
    ("1500m_men", "3:30.11", 1243),     # live result-score anchors
    ("10000m_men", "26:50.21", 1242),
    ("10000m_men", "26:47.72", 1246),
])
def test_result_score_live_anchors(event, time, expected):
    assert result_score(event, time) == expected


@pytest.mark.parametrize("group,cat,place,expected", [
    ("standard", "GW", 1, 140),
    ("5000m", "GW", 1, 115),    # distance final placing differs from standard
    ("5000m", "OW", 1, 215),
    ("10000m", "OW", 1, 200),
    ("10000m", "GW", 1, 100),
])
def test_placing_groups(group, cat, place, expected):
    assert placing_score(cat, place, group) == expected


def test_road_to_birmingham_has_quota_and_champion_per_event():
    for ek in ALL_EVENTS:
        cfg = championship_event_config("road_to_birmingham", ek)
        assert isinstance(cfg["quota"], int)
        assert "name" in cfg["defending_champion"]
    # world championship defines no quota -> qualify is unavailable there
    assert championship_event_config("world", "1500m_men") == {}


def test_championships_are_region_level():
    champs = load_championships()
    assert {"world", "road_to_beijing", "road_to_birmingham", "road_to_ultimate"} <= set(champs)
    assert "rankings_url_template" in champs["world"]
    # The two finished championships are archived (hidden from the site, config kept).
    assert champs["road_to_birmingham"]["archived"] is True
    assert champs["road_to_ultimate"]["archived"] is True
    assert "qualification_footnote" not in champs["road_to_ultimate"]   # stale DL-Final note gone
    assert not champs["road_to_beijing"].get("archived")


BEIJING_STANDARDS = {
    "800m_men": "1:43.00", "800m_women": "1:57.50", "1500m_men": "3:30.00", "1500m_women": "3:58.00",
    "5000m_men": "12:50.00", "5000m_women": "14:36.00", "10000m_men": "26:48.00",
    "10000m_women": "30:40.00", "3000mSC_men": "8:08.00", "3000mSC_women": "9:06.50",
}
BEIJING_QUOTA = {"800m": 56, "1500m": 56, "5000m": 42, "10000m": 27, "3000mSC": 36}


def test_road_to_beijing_config_matches_the_published_system():
    """WA 'Qualification System and Entry Standards - Beijing 2027' (May 2026)."""
    champ = load_championships()["road_to_beijing"]
    assert champ["data_source"] == "world"            # shares the world ranking list/cache
    assert champ["max_per_country"] == 3
    assert champ["qualification_window"] == {"start": "2026-08-23", "end": "2027-08-22"}
    assert champ["qualification_feed"]["competition_id"] == 7216591
    assert set(champ["qualification_feed"]["events"]) == set(ALL_EVENTS)
    assert set(champ["events"]) == set(ALL_EVENTS)    # every event is contested
    for ek in ALL_EVENTS:
        cfg = championship_event_config("road_to_beijing", ek)
        assert cfg["quota"] == BEIJING_QUOTA[ek.split("_")[0]]
        assert cfg["entry_standard"] == BEIJING_STANDARDS[ek]
        assert cfg["auto_invites"][0]["reason"] == "Defending World Champion"
        for inv in cfg["auto_invites"]:
            assert {"name", "country", "reason"} <= set(inv)
        # One wildcard per country per event (WA rule) — never two byes from one nation.
        countries = [inv["country"] for inv in cfg["auto_invites"]]
        assert len(countries) == len(set(countries)), ek
        if ek.startswith("10000m"):
            assert cfg["qualification_window"] == {"start": "2026-02-23", "end": "2027-08-22"}
        else:
            assert "qualification_window" not in cfg
    # Ultimate winners are wildcards (hand-maintained) only in the six contested events.
    manual = {ek for ek in ALL_EVENTS
              if any(i.get("source") == "manual" for i in championship_event_config("road_to_beijing", ek)["auto_invites"])}
    assert manual == set(ULTIMATE_EVENTS)
    # The events.json default time is the Beijing standard (console default).
    for ek in ALL_EVENTS:
        assert load_event(ek)["entry_standard"] == BEIJING_STANDARDS[ek]


ULTIMATE_EVENTS = ["800m_men", "800m_women", "1500m_men", "1500m_women",
                   "5000m_men", "5000m_women"]


def test_road_to_ultimate_is_invitational_with_wildcards():
    champ = load_championships()["road_to_ultimate"]
    assert champ["data_source"] == "world"          # shares the world ranking list/cache
    assert champ["max_per_country"] is None         # no country cap
    assert champ["contested_events_only"] is True
    assert champ["not_contested_note"]
    assert set(champ["events"]) == set(ULTIMATE_EVENTS)
    for ek in ULTIMATE_EVENTS:
        cfg = championship_event_config("road_to_ultimate", ek)
        # WA field sizes: 16 for the 800m, 12 for the 1500m/5000m
        assert cfg["quota"] == (16 if ek.startswith("800m") else 12)
        assert 1 <= len(cfg["auto_invites"]) <= 3
        for inv in cfg["auto_invites"]:
            assert {"name", "country", "reason"} <= set(inv)
    # 10000m and steeplechase are not on the Ultimate programme
    for absent in ("10000m_men", "10000m_women", "3000mSC_men", "3000mSC_women"):
        assert championship_event_config("road_to_ultimate", absent) == {}
