"""Championship qualification: per-country caps + wildcard byes + quota.

A *general ranking* question ("what's my rank?") needs none of this — see ranking.py.
A *qualifying* question ("do I make championship X?") applies:

  - a fixed number of qualification places (`quota`);
  - **wildcards** taking the first slots as byes (a defending champion in Birmingham; the
    Olympic/World champions in the Ultimate Championship). A wildcard does not count toward
    any country cap and consumes one place, so only `quota - len(wildcards)` remain for the
    ranking;
  - an optional **max-per-country cap** on the ranking qualifiers (3 for Birmingham;
    None = no cap for the Ultimate Championship).

Everything here operates on ranking *positions/scores*, independent of how each athlete's
score was computed.
"""
from __future__ import annotations


def qualifying_field(ranked: list[dict], quota: int, *, max_per_country: int | None = 3,
                     defending_champion: dict | None = None,
                     auto_invites: list[dict] | None = None) -> dict:
    """Resolve who qualifies.

    Args:
        ranked: athletes as {name, country, ranking_score}, sorted by score descending.
        quota: total qualification places (including wildcard byes).
        max_per_country: cap on ranking qualifiers per country (wildcards exempt);
            None means no cap.
        defending_champion: {name, country} seeded at #1, or None — shorthand for a single
            auto_invite with reason "defending champion (bye)".
        auto_invites: wildcards as {name, country, reason} seeded in order at the top
            (e.g. Olympic/World champions). Takes precedence over defending_champion.

    Returns a dict with the ordered `slots`, the `cutoff_score`, per-country `counts`
    (excluding wildcards), and athletes `blocked` by their country cap.
    """
    invites = list(auto_invites) if auto_invites else (
        [{**defending_champion, "reason": "defending champion (bye)"}]
        if defending_champion else [])

    slots: list[dict] = []
    counts: dict[str, int] = {}
    blocked: list[dict] = []
    remaining = quota
    pos = 1
    invite_names = {i["name"].upper() for i in invites}

    for inv in invites:
        slots.append({
            "position": pos,
            "name": inv["name"],
            "country": inv.get("country"),
            "score": None,
            "reason": inv.get("reason", "wildcard"),
        })
        remaining -= 1
        pos += 1

    for a in ranked:
        if a["name"].upper() in invite_names:
            continue  # already in via a wildcard; exempt from the country cap
        if remaining <= 0:
            break
        country = a.get("country")
        if max_per_country is not None and counts.get(country, 0) >= max_per_country:
            blocked.append({
                "name": a["name"], "country": country,
                "score": a.get("ranking_score"),
                "reason": f"country cap ({max_per_country})",
            })
            continue
        slots.append({
            "position": pos, "name": a["name"], "country": country,
            "score": a.get("ranking_score"), "reason": "ranking",
        })
        counts[country] = counts.get(country, 0) + 1
        remaining -= 1
        pos += 1

    ranking_slots = [s for s in slots if s["reason"] == "ranking"]
    return {
        "quota": quota,
        "max_per_country": max_per_country,
        "slots": slots,
        "cutoff_score": ranking_slots[-1]["score"] if ranking_slots else None,
        "places_filled": len(slots),
        "counts": counts,
        "blocked": blocked,
        "defending_champion": defending_champion,
        "auto_invites": invites,
    }


def athlete_status(field: dict, name: str) -> tuple[str, dict | None]:
    """Classify an athlete in a resolved field: qualified / blocked_country_cap / out."""
    nm = name.upper()
    for s in field["slots"]:
        if s["name"].upper() == nm:
            return ("qualified", s)
    for b in field["blocked"]:
        if b["name"].upper() == nm:
            return ("blocked_country_cap", b)
    return ("out", None)


def build_ranked(athletes: list[dict], *, override_name: str | None = None,
                 override_score: float | None = None) -> list[dict]:
    """Build a score-sorted ranking list, optionally substituting one athlete's score."""
    rows = []
    for a in athletes:
        score = a.get("ranking_score")
        if override_name and a["name"].upper() == override_name.upper():
            score = override_score
        rows.append({"name": a["name"], "country": a.get("country"), "ranking_score": score})
    rows.sort(key=lambda r: (r["ranking_score"] is not None, r["ranking_score"] or 0),
              reverse=True)
    return rows
