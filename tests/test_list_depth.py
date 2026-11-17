"""The build's guard against a ranking list too short for its qualifying field."""
from scripts.build_static import MIN_ROWS_BELOW_CUTOFF, list_depth_problem
from wa_ranking import qualify


def _athletes(n, country=None):
    # Distinct countries unless told otherwise, so the per-country cap doesn't bite.
    return [{"name": f"ATHLETE {i}", "country": country or f"C{i}", "ranking_score": 2000 - i}
            for i in range(1, n + 1)]


def _field(athletes, quota):
    return qualify.qualifying_field(qualify.build_ranked(athletes), quota, max_per_country=3)


def test_deep_list_is_fine():
    a = _athletes(200)
    assert list_depth_problem(a, _field(a, 56)) is None


def test_cutoff_near_the_end_of_the_list_is_a_problem():
    a = _athletes(56 + MIN_ROWS_BELOW_CUTOFF - 1)
    assert "last ranking qualifier is row 56" in list_depth_problem(a, _field(a, 56))
    b = _athletes(56 + MIN_ROWS_BELOW_CUTOFF)
    assert list_depth_problem(b, _field(b, 56)) is None


def test_country_cap_exhausting_the_list_is_a_problem():
    # One country, cap 3: only 3 of 56 places can be filled however long the list is.
    a = _athletes(100, country="KEN")
    assert "only 3 of 56 places filled" in list_depth_problem(a, _field(a, 56))


def test_field_filled_without_the_ranking_needs_no_list():
    a = _athletes(5)
    std = [{"name": x["name"], "country": x["country"], "mark": "3:29.00"} for x in a]
    f = qualify.qualifying_field(qualify.build_ranked(a), 5, max_per_country=3,
                                 standard_achievers=std)
    assert list_depth_problem(a, f) is None
