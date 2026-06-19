"""Unit tests for the profile-fallback helpers (pure functions, no network)."""
from wa_ranking.profile import _name_from_slug, normalize_ref
from wa_ranking.scoring import format_seconds, time_for_result_score


def test_normalize_ref_forms():
    assert normalize_ref("jake-heyward-14597392") == "jake-heyward-14597392"
    assert normalize_ref("great-britain-ni/jake-heyward-14597392") == "jake-heyward-14597392"
    assert normalize_ref(
        "https://worldathletics.org/athletes/great-britain-ni/jake-heyward-14597392"
    ) == "jake-heyward-14597392"
    assert normalize_ref(" .../athletes/x/jake-heyward-14597392/ ") == "jake-heyward-14597392"


def test_name_from_slug():
    assert _name_from_slug("jake-heyward-14597392") == "Jake Heyward"
    assert _name_from_slug("nadia-battocletti-14653296") == "Nadia Battocletti"


def test_format_seconds():
    assert format_seconds(215.0) == "3:35.00"
    assert format_seconds(214.18) == "3:34.18"
    assert format_seconds(54.3) == "54.30"


def test_time_for_result_score_inverts_table():
    # round-trip: the time for a known score should itself score >= that value.
    from wa_ranking.scoring import result_score
    t = time_for_result_score("1500m_men", 1175)
    assert t is not None
    assert result_score("1500m_men", t) >= 1175
