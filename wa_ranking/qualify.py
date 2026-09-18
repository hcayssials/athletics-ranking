"""Championship qualification: wildcards + entry-standard achievers + per-country cap + quota.

A *general ranking* question ("what's my rank?") needs none of this — see ranking.py.
A *qualifying* question ("do I make championship X?") applies:

  - a fixed number of qualification places (`quota` — the target field);
  - **wildcards** taking the first slots as byes (a defending champion, the Olympic/World
    champions at the Ultimate, the Ultimate/Diamond League winners at the Worlds). A wildcard
    does not count toward any country cap and consumes one place;
  - **entry-standard achievers** (World Championships): athletes who have run the entry
    standard are in next, whatever their ranking, and consume places before the ranking
    fill. They *do* count toward the country cap — a fourth standard achiever from one
    country is blocked (federation's call) and takes no place;
  - the **world-ranking fill** of whatever remains, in score order, subject to
  - an optional **max-per-country cap** across all non-wildcard routes (3 for the Worlds and
    Birmingham; None = no cap for the Ultimate Championship).

Everything here operates on ranking *positions/scores*, independent of how each athlete's
score was computed.
"""
from __future__ import annotations


def qualifying_field(ranked: list[dict], quota: int, *, max_per_country: int | None = 3,
                     defending_champion: dict | None = None,
                     auto_invites: list[dict] | None = None,
                     standard_achievers: list[dict] | None = None) -> dict:
    """Resolve who qualifies.

    Args:
        ranked: athletes as {name, country, ranking_score}, sorted by score descending.
        quota: total qualification places (including wildcard byes and standard achievers).
        max_per_country: cap on non-wildcard qualifiers per country (wildcards exempt);
            None means no cap.
        defending_champion: {name, country} seeded at #1, or None — shorthand for a single
            auto_invite with reason "defending champion (bye)".
        auto_invites: wildcards as {name, country, reason} seeded in order at the top
            (e.g. Olympic/World champions). Takes precedence over defending_champion.
        standard_achievers: athletes who have achieved the entry standard, as {name, country,
            mark}, seeded after the wildcards in the given order (WA lists them fastest
            first). A wildcard holder in this list is treated as a wildcard. Not capped by
            the quota (WA: ties for the last standard place all qualify) — they can only
            squeeze the ranking fill.

    Returns a dict with the ordered `slots` (reason: wildcard label / "entry standard" /
    "ranking"), the `cutoff_score` (last *ranking* qualifier), per-country `counts`
    (excluding wildcards), athletes `blocked` by their country cap, and how the places
    split (`standard_places`, `ranking_places`).
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
    score_of = {a["name"].upper(): a.get("ranking_score") for a in ranked}

    for inv in invites:
        slots.append({
            "position": pos,
            "name": inv["name"],
            "country": inv.get("country"),
            "score": score_of.get(inv["name"].upper()),
            "reason": inv.get("reason", "wildcard"),
        })
        remaining -= 1
        pos += 1

    standard_names: set[str] = set()
    for s in standard_achievers or []:
        key = s["name"].upper()
        if key in invite_names or key in standard_names:
            continue
        standard_names.add(key)
        country = s.get("country")
        if max_per_country is not None and counts.get(country, 0) >= max_per_country:
            blocked.append({
                "name": s["name"], "country": country,
                "score": score_of.get(key),
                "reason": f"country cap ({max_per_country})",
                "route": "entry standard",
            })
            continue
        slots.append({
            "position": pos, "name": s["name"], "country": country,
            "score": score_of.get(key), "reason": "entry standard",
            "mark": s.get("mark"),
        })
        counts[country] = counts.get(country, 0) + 1
        remaining -= 1
        pos += 1

    for a in ranked:
        key = a["name"].upper()
        if key in invite_names or key in standard_names:
            continue  # already in (or capped out) via a wildcard / the entry standard
        if remaining <= 0:
            break
        country = a.get("country")
        if max_per_country is not None and counts.get(country, 0) >= max_per_country:
            blocked.append({
                "name": a["name"], "country": country,
                "score": a.get("ranking_score"),
                "reason": f"country cap ({max_per_country})",
                "route": "ranking",
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
    standard_slots = [s for s in slots if s["reason"] == "entry standard"]
    return {
        "quota": quota,
        "max_per_country": max_per_country,
        "slots": slots,
        "cutoff_score": ranking_slots[-1]["score"] if ranking_slots else None,
        "places_filled": len(slots),
        "standard_places": len(standard_slots),
        "ranking_places": len(ranking_slots),
        "counts": counts,
        "blocked": blocked,
        "defending_champion": defending_champion,
        "auto_invites": invites,
    }


def athlete_status(field: dict, name: str) -> tuple[str, dict | None]:
    """Classify an athlete in a resolved field: qualified / blocked_country_cap / out.
    For a qualified athlete the slot's `reason` says the route (wildcard label,
    "entry standard" or "ranking")."""
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
