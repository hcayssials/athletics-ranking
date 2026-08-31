"""Unit tests for championship qualification (caps + champion bye + quota)."""
from wa_ranking.qualify import athlete_status, build_ranked, qualifying_field


def a(name, country, score):
    return {"name": name, "country": country, "ranking_score": score}


# Score-sorted (as build_ranked guarantees). FRA has 4 athletes; cap 3 blocks the 4th.
RANKED = [
    a("Nader", "POR", 1368),
    a("Habz", "FRA", 1358),     # FRA 1
    a("Wightman", "GBR", 1320),
    a("Coscoran", "IRL", 1292),
    a("Mornet", "FRA", 1257),   # FRA 2
    a("Szot", "FRA", 1247),     # FRA 3
    a("Dubois", "FRA", 1200),   # FRA 4 -> should be capped out
]


def test_plain_quota_no_caps_no_champion():
    field = qualifying_field(RANKED[:3], quota=3)
    assert [s["name"] for s in field["slots"]] == ["Nader", "Habz", "Wightman"]
    assert field["cutoff_score"] == 1320
    assert field["blocked"] == []


def test_country_cap_blocks_fourth_from_country():
    field = qualifying_field(RANKED, quota=7, max_per_country=3)
    quals = [s["name"] for s in field["slots"]]
    assert "Dubois" not in quals                      # FRA's 4th is capped
    assert field["counts"]["FRA"] == 3
    blocked_names = [b["name"] for b in field["blocked"]]
    assert "Dubois" in blocked_names
    assert field["cutoff_score"] == 1247              # Szot, last ranking qualifier
    assert qualifying_field(RANKED, quota=7)["counts"]["FRA"] == 3  # default cap == 3


def test_defending_champion_bye():
    champ = {"name": "Jakob Ingebrigtsen", "country": "NOR"}  # not in RANKED
    field = qualifying_field(RANKED, quota=4, max_per_country=3, defending_champion=champ)
    assert field["slots"][0]["reason"] == "defending champion (bye)"
    assert field["slots"][0]["name"] == "Jakob Ingebrigtsen"
    # quota 4 - 1 bye = 3 ranking places.
    ranking_slots = [s for s in field["slots"] if s["reason"] == "ranking"]
    assert len(ranking_slots) == 3
    assert [s["name"] for s in ranking_slots] == ["Nader", "Habz", "Wightman"]


def test_champion_exempt_from_own_country_cap():
    # Champion is NOR; NOR ranking qualifiers can still fill the cap independently.
    ranked = [a("Nordas", "NOR", 1299), a("MoeBerg", "NOR", 1273),
              a("ThirdNor", "NOR", 1250), a("FourthNor", "NOR", 1240)]
    champ = {"name": "Ingebrigtsen", "country": "NOR"}
    field = qualifying_field(ranked, quota=5, max_per_country=3, defending_champion=champ)
    nor_ranking = [s for s in field["slots"] if s["reason"] == "ranking" and s["country"] == "NOR"]
    assert len(nor_ranking) == 3            # cap applies to ranking qualifiers only
    assert field["slots"][0]["name"] == "Ingebrigtsen"  # champ on top of the 3


def test_multiple_wildcards_seed_the_top_slots():
    # Ultimate-Championship style: Olympic + World champions enter by wildcard; one of them
    # (Nader) is also on the ranking list and must not consume a ranking place too.
    invites = [{"name": "Ingebrigtsen", "country": "NOR", "reason": "Olympic champion"},
               {"name": "Nader", "country": "POR", "reason": "World champion"}]
    field = qualifying_field(RANKED, quota=6, max_per_country=None, auto_invites=invites)
    assert [s["name"] for s in field["slots"][:2]] == ["Ingebrigtsen", "Nader"]
    assert field["slots"][0]["reason"] == "Olympic champion"
    ranking = [s["name"] for s in field["slots"] if s["reason"] == "ranking"]
    assert ranking == ["Habz", "Wightman", "Coscoran", "Mornet"]  # 6 - 2 wildcards = 4 places
    assert field["cutoff_score"] == 1257
    assert field["auto_invites"] == invites


def test_no_country_cap_when_max_per_country_is_none():
    field = qualifying_field(RANKED, quota=7, max_per_country=None)
    assert field["blocked"] == []
    assert "Dubois" in [s["name"] for s in field["slots"]]   # FRA's 4th gets in
    assert field["counts"]["FRA"] == 4


def test_athlete_status():
    field = qualifying_field(RANKED, quota=7, max_per_country=3)
    assert athlete_status(field, "Nader")[0] == "qualified"
    assert athlete_status(field, "Dubois")[0] == "blocked_country_cap"
    assert athlete_status(field, "Nobody")[0] == "out"


def test_build_ranked_override_resorts():
    athletes = [a("X", "GBR", 1300), a("Y", "FRA", 1200)]
    ranked = build_ranked(athletes, override_name="Y", override_score=1400)
    assert [r["name"] for r in ranked] == ["Y", "X"]   # Y jumps to the top


def test_not_in_field_athlete_takes_no_place():
    # Wightman is ranked but WA doesn't list him in the field: the place passes down the list.
    absent = [{"name": "Wightman", "country": "GBR", "reason": "not in the field"}]
    field = qualifying_field(RANKED[:4], quota=3, max_per_country=None, not_in_field=absent)
    assert [s["name"] for s in field["slots"]] == ["Nader", "Habz", "Coscoran"]
    assert field["cutoff_score"] == 1292          # Coscoran, not Wightman's 1320
    assert [o["name"] for o in field["omitted"]] == ["Wightman"]
    assert field["omitted"][0]["score"] == 1320   # still carries the ranking score


def test_not_in_field_frees_a_country_cap_slot():
    # FRA's 2nd is out of the field, so FRA's 4th is no longer capped out.
    absent = [{"name": "Mornet", "country": "FRA", "reason": "not in the field"}]
    field = qualifying_field(RANKED, quota=7, max_per_country=3, not_in_field=absent)
    names = [s["name"] for s in field["slots"]]
    assert "Mornet" not in names
    assert "Dubois" in names                      # took the freed FRA slot
    assert field["counts"]["FRA"] == 3
    assert field["blocked"] == []


def test_wildcard_wins_over_not_in_field():
    invites = [{"name": "Nader", "country": "POR", "reason": "World champion"}]
    absent = [{"name": "Nader", "country": "POR", "reason": "not in the field"}]
    field = qualifying_field(RANKED, quota=3, max_per_country=None,
                             auto_invites=invites, not_in_field=absent)
    assert field["slots"][0]["name"] == "Nader"
    assert field["omitted"] == []


def test_athlete_status_not_in_field():
    absent = [{"name": "Habz", "country": "FRA", "reason": "not in the field"}]
    field = qualifying_field(RANKED, quota=7, max_per_country=3, not_in_field=absent)
    assert athlete_status(field, "Habz")[0] == "not_in_field"
    assert athlete_status(field, "Nader")[0] == "qualified"
