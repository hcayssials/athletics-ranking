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


def test_standard_achievers_take_places_before_the_ranking_fill():
    # Beijing style: Dubois (FRA, ranked last) has the entry standard -> in before Coscoran.
    achievers = [{"name": "Dubois", "country": "FRA", "mark": "3:29.90"}]
    field = qualifying_field(RANKED, quota=4, max_per_country=None, standard_achievers=achievers)
    assert [(s["name"], s["reason"]) for s in field["slots"]] == [
        ("Dubois", "entry standard"), ("Nader", "ranking"), ("Habz", "ranking"), ("Wightman", "ranking")]
    assert field["slots"][0]["score"] == 1200 and field["slots"][0]["mark"] == "3:29.90"
    assert field["standard_places"] == 1 and field["ranking_places"] == 3
    assert field["cutoff_score"] == 1320                   # last *ranking* qualifier
    assert athlete_status(field, "Dubois")[1]["reason"] == "entry standard"


def test_standard_achiever_off_the_list_still_consumes_a_place():
    achievers = [{"name": "Unranked FAST", "country": "USA", "mark": "3:28.00"}]
    field = qualifying_field(RANKED[:3], quota=3, max_per_country=None, standard_achievers=achievers)
    assert [s["name"] for s in field["slots"]] == ["Unranked FAST", "Nader", "Habz"]
    assert field["slots"][0]["score"] is None


def test_standard_achievers_count_toward_the_country_cap():
    # Three FRA standard achievers fill FRA's 3; the 4th (Habz, ranked 2nd!) is capped out.
    achievers = [{"name": "Mornet", "country": "FRA"}, {"name": "Szot", "country": "FRA"},
                 {"name": "Dubois", "country": "FRA"}]
    field = qualifying_field(RANKED, quota=7, max_per_country=3, standard_achievers=achievers)
    names = [s["name"] for s in field["slots"]]
    assert names[:3] == ["Mornet", "Szot", "Dubois"] and "Habz" not in names
    assert athlete_status(field, "Habz")[0] == "blocked_country_cap"
    assert athlete_status(field, "Habz")[1]["route"] == "ranking"
    assert field["counts"]["FRA"] == 3
    # A 4th standard achiever from FRA is blocked too (route says by which path).
    field = qualifying_field(RANKED, quota=7, max_per_country=3,
                             standard_achievers=achievers + [{"name": "Habz", "country": "FRA"}])
    assert athlete_status(field, "Habz")[0] == "blocked_country_cap"
    assert athlete_status(field, "Habz")[1]["route"] == "entry standard"


def test_wildcard_wins_over_standard_and_duplicates_are_ignored():
    invites = [{"name": "Nader", "country": "POR", "reason": "Defending World Champion"}]
    achievers = [{"name": "Nader", "country": "POR"}, {"name": "Habz", "country": "FRA"},
                 {"name": "Habz", "country": "FRA"}]
    field = qualifying_field(RANKED, quota=3, auto_invites=invites, standard_achievers=achievers)
    assert [(s["name"], s["reason"]) for s in field["slots"]] == [
        ("Nader", "Defending World Champion"), ("Habz", "entry standard"), ("Wightman", "ranking")]
    assert field["slots"][0]["score"] == 1368              # wildcard's ranking score rides along


def test_standard_achievers_are_not_capped_by_the_quota():
    # WA: ties for the last standard place all qualify — they squeeze the ranking fill to 0.
    achievers = [{"name": f"S{i}", "country": "XX{}".format(i)} for i in range(4)]
    field = qualifying_field(RANKED, quota=3, max_per_country=None, standard_achievers=achievers)
    assert field["standard_places"] == 4 and field["ranking_places"] == 0
    assert field["cutoff_score"] is None
