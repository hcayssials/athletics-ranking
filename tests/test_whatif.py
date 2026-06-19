"""Reverse solver ('what would it take') helper."""
from wa_ranking.whatif import _targets_required


def _counting(scores):
    return [{"performance_score": s} for s in scores]


def test_targets_required_statuses():
    counting = _counting([1300, 1280, 1260, 1240, 1220])  # full best-5 set, current avg 1260
    rows = _targets_required("1500m_men", counting, 5, placing=100, current_score=1260, targets=[
        ("already there", 1200),     # at/below current score -> met
        ("reach the cutoff", 1280),  # above current -> needs a real (reachable) time
        ("reach #1", 1400),          # absurdly high -> faster than the table tops out
    ])
    by_label = {r["label"]: r for r in rows}

    assert by_label["already there"]["status"] == "met"
    assert by_label["already there"]["time"] is None

    reach = by_label["reach the cutoff"]
    assert reach["status"] == "reachable"
    assert reach["time"] is not None
    assert reach["result_score"] > 0

    assert by_label["reach #1"]["status"] == "unreachable"
    assert by_label["reach #1"]["time"] is None


def test_targets_required_skips_none_score():
    rows = _targets_required("1500m_men", _counting([1300, 1280]), 5, 100, current_score=1290,
                             targets=[("no target", None), ("real", 1310)])
    assert [r["label"] for r in rows] == ["real"]
