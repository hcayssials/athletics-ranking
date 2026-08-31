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
    assert {"world", "road_to_birmingham", "road_to_ultimate"} <= set(champs)
    assert "rankings_url_template" in champs["world"]


ULTIMATE_EVENTS = ["800m_men", "800m_women", "1500m_men", "1500m_women",
                   "5000m_men", "5000m_women"]


def test_road_to_ultimate_is_invitational_with_wildcards():
    champ = load_championships()["road_to_ultimate"]
    assert champ["data_source"] == "world"          # shares the world ranking list/cache
    assert champ["max_per_country"] is None         # no country cap
    assert champ["contested_events_only"] is True
    assert champ["not_contested_note"]
    assert set(champ["events"]) == set(ULTIMATE_EVENTS)
    # Fallback field sizes: 16 for the 800m, 12 for the 1500m/5000m — except the men's 1500m,
    # where two exceptional invitations push WA's field to 13. The live values come from the
    # qualification feed (see test_feed.py); these are what ship when no snapshot exists.
    for ek in ULTIMATE_EVENTS:
        cfg = championship_event_config("road_to_ultimate", ek)
        assert cfg["quota"] == (13 if ek == "1500m_men" else 16 if ek.startswith("800m") else 12)
        assert len(cfg["auto_invites"]) <= 4      # 0 where the champions aren't in the field
        for inv in cfg["auto_invites"]:
            assert {"name", "country", "reason"} <= set(inv)
    # Every event WA publishes a feed for is one we contest.
    fc = champ["qualification_feed"]
    assert fc["competition_id"] == 7212925
    assert set(fc["events"]) == set(ULTIMATE_EVENTS)
    # 10000m and steeplechase are not on the Ultimate programme
    for absent in ("10000m_men", "10000m_women", "3000mSC_men", "3000mSC_women"):
        assert championship_event_config("road_to_ultimate", absent) == {}
