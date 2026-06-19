"""The what-if scenario: score a hypothetical performance and report new score + rank.

Always returns a structured dict (frontend-ready) and, by default, prints the assumptions
used plus the result.
"""
from __future__ import annotations

import math
from datetime import date

from . import fetch
from .config import (championship_event_config, load_championship, load_event,
                     load_placing_scores)
from .profile import fetch_profile
from .qualify import athlete_status, build_ranked, qualifying_field
from .ranking import insert_and_recompute, ranking_score, rank_position, resolve_window, select_counting
from .scoring import format_seconds, placing_score, score_performance, time_for_result_score


def what_if(event: str, athlete: str, new_time: str | float,
            category: str = "GW", place: int = 2, *,
            championship: str = "road_to_birmingham",
            as_of: date | None = None, indoor: bool = False,
            qualification_window: bool = False, qualify: bool = False,
            profile: str | None = None,
            force_refresh: bool = False, verbose: bool = True) -> dict:
    """Model the effect of a new performance on an athlete's ranking score and rank.

    Args:
        event: key in events.json (e.g. '1500m_men', '5000m_women').
        athlete: athlete name (full or unambiguous partial).
        new_time: e.g. '3:29.50'.
        category: meet category code (default 'GW' = Diamond League / World Indoors).
        place: projected finishing place (default 2).
        championship: key in championships.json ('world' or 'road_to_birmingham').
        as_of: ranking date to evaluate against (default: today).
        qualify: also resolve championship qualification (quota + 3-per-country cap +
            defending-champion bye). Requires the championship to declare a quota for the event.
        indoor / qualification_window / force_refresh / verbose: see README.
    """
    as_of = as_of or date.today()
    champ = load_championship(championship)
    ev = load_event(event)
    champ_event = championship_event_config(championship, event)
    best_n, window = ev["best_n"], ev["window_months"]
    placing_group = ev.get("placing_event_group", "standard")

    # Window: rolling (default, matches WA's published scores) or the championship's fixed
    # qualification window if requested (per-event override falls back to championship default).
    qw = champ_event.get("qualification_window") or champ.get("qualification_window")
    if qualification_window and qw:
        window_start = date.fromisoformat(qw["start"])
        window_end = date.fromisoformat(qw["end"])
        window_kind = "fixed"
    else:
        window_start = window_end = None
        window_kind = "rolling"
    always_include = tuple(champ.get("always_include_competitions", ()))
    main_codes = tuple(ev.get("main_event_codes", ()))
    main_min = ev.get("main_event_min", 0)
    # Selection kwargs. With window_start/end None (rolling), WA's returned set is the
    # counting set and is kept as-is; a fixed qualification window filters it.
    sel = {"window_start": window_start, "window_end": window_end,
           "always_include_competitions": always_include,
           "main_event_codes": main_codes, "main_event_min": main_min}

    data = fetch.fetch_championship(championship, event, force=force_refresh)
    ath = fetch.find_athlete(data, athlete)
    profile_info = None
    if ath is None:
        if not profile:
            n = len(data["athletes"])
            raise ValueError(
                f"'{athlete}' is either not in the {championship} {event} ranking list "
                f"(top ~{n}), or doesn't yet have enough performances in the window to be "
                "ranked. If they're unranked, pass profile='<wa-slug>' (e.g. "
                "'jake-heyward-14597392', the last part of their "
                "worldathletics.org/athletes/... URL).")
        profile_info = fetch_profile(profile, event, as_of, window, force=force_refresh)
        ath = {"name": profile_info["name"], "country": profile_info["country"],
               "ranking_score": None, "rank": None,
               "performances": profile_info["performances"]}

    perfs = ath["performances"]

    # Score the hypothetical performance (a fresh result -> no age decay).
    breakdown = score_performance(
        event, new_time, category, place,
        perf_date=as_of, as_of=as_of, event_group=placing_group,
    )
    new_perf = {
        "date": as_of.isoformat(),
        "competition": "(hypothetical)",
        "category": category.upper(),
        "discipline_code": ev["main_event_codes"][0],
        "indoor": indoor,
        "place": place,
        "mark": str(new_time),
        "result_score": breakdown["result_score"],
        "placing_score": breakdown["placing_score"],
        "performance_score": breakdown["performance_score"],
        "month_correction_applied": breakdown["decay"] != 0,
        "hypothetical": True,
    }

    recompute = insert_and_recompute(perfs, new_perf, best_n, **sel)
    official_score = ath.get("ranking_score")
    recomputed_old = ranking_score(perfs, best_n, **sel)
    new_score = recompute["new_score"]

    # New rank: hold all other athletes at their current (official) ranking scores.
    others = [a["ranking_score"] for a in data["athletes"] if a is not ath]
    new_rank = rank_position(others, new_score)
    old_rank = ath.get("rank")

    # Optional championship qualification (quota + per-country cap + defending-champion bye).
    qualification = None
    if qualify:
        if "quota" not in champ_event:
            raise ValueError(
                f"Championship '{championship}' has no quota for event '{event}'; --qualify is "
                "only meaningful for a qualification championship (e.g. road_to_birmingham)."
            )
        quota = champ_event["quota"]
        max_pc = champ.get("max_per_country", 3)
        champion = champ_event.get("defending_champion")
        athletes = data["athletes"]
        if profile_info:  # unranked athlete isn't in the list — add him so he can slot in
            athletes = athletes + [{"name": ath["name"], "country": ath["country"],
                                    "ranking_score": None}]
        is_champion = bool(champion) and ath["name"].upper() == champion["name"].upper()

        ranked_old = build_ranked(athletes)
        ranked_new = build_ranked(athletes, override_name=ath["name"], override_score=new_score)
        field_old = qualifying_field(ranked_old, quota, max_per_country=max_pc, defending_champion=champion)
        field_new = qualifying_field(ranked_new, quota, max_per_country=max_pc, defending_champion=champion)
        status_old, slot_old = athlete_status(field_old, ath["name"])
        status_new, slot_new = athlete_status(field_new, ath["name"])

        cutoff = field_new["cutoff_score"]
        country_ahead = sum(1 for a in data["athletes"]
                            if a is not ath and a.get("country") == ath.get("country")
                            and (a.get("ranking_score") or 0) > new_score)
        qualification = {
            "quota": quota,
            "quota_is_total_field": champ.get("quota_is_total_field", False),
            "max_per_country": max_pc,
            "defending_champion": champion,
            "is_defending_champion": is_champion,
            "ranking_places": quota - (1 if champion else 0),
            "cutoff_score": cutoff,
            "above_cutoff": (new_score is not None and cutoff is not None and new_score >= cutoff),
            "status_old": status_old,
            "status_new": status_new,
            "qual_position_old": (slot_old or {}).get("position"),
            "qual_position_new": (slot_new or {}).get("position"),
            "country_count": field_new["counts"].get(ath.get("country"), 0),
            "country_ahead": country_ahead,
            "field_new": field_new["slots"],
            "blocked_new": field_new["blocked"],
        }

    # Reverse "what would it take": for a ranked athlete, the time a single new race (at the
    # modelled place/category) would need to reach key targets — the qualifying cutoff and #1.
    what_would_it_take = None
    if not profile_info:
        top = max((s for s in others if s is not None), default=None)
        targets = []
        if qualification and qualification.get("cutoff_score") is not None:
            targets.append(("reach the qualifying cutoff", qualification["cutoff_score"]))
        if top is not None:
            targets.append(("reach #1", top + 1))
        rows = _targets_required(event, recompute["old_counting"], best_n,
                                 breakdown["placing_score"], recomputed_old, targets)
        if rows:
            what_would_it_take = {"place": place, "category": category.upper(), "targets": rows}

    # Unranked-athlete summary (when sourced from a profile): counting-set completeness and
    # the time the new race would need to reach a meaningful target.
    profile_summary = None
    if profile_info:
        old_counting = recompute["old_counting"]
        new_counting = recompute["new_counting"]
        list_scores = [a["ranking_score"] for a in data["athletes"] if a.get("ranking_score")]
        target = (qualification["cutoff_score"] if qualification else
                  (min(list_scores) if list_scores else None))
        req = _required_time(event, old_counting, best_n, breakdown["placing_score"], target) \
            if target is not None else (None, None)
        profile_summary = {
            "source": "profile",
            "ranked": profile_info["ranked"],
            "best_rank": profile_info["best_rank"],
            "best_rank_weeks": profile_info["best_rank_weeks"],
            "counting_now": len(old_counting),
            "counting_with_new": len(new_counting),
            "short_of_full_set": max(0, best_n - len(new_counting)),
            "target_score": target,
            "target_label": ("qualifying cutoff" if qualification else "lowest ranked on list"),
            "required_time": req[0],
            "required_result_score": req[1],
            "incomplete_window": profile_info.get("incomplete_window", False),
        }

    result = {
        "championship": championship,
        "event": event,
        "athlete": ath["name"],
        "country": ath.get("country"),
        "as_of": as_of.isoformat(),
        "rank_date": data.get("rank_date"),
        "assumptions": {
            "best_n": best_n,
            "window_months": window,
            "window_kind": window_kind,
            "window_start": (window_start or resolve_window(window, as_of)[0]).isoformat(),
            "window_end": (window_end or as_of).isoformat(),
            "category": category.upper(),
            "place": place,
            "indoor": indoor,
            "result_table": ev["result_table"],
            "placing_edition": load_placing_scores()["_meta"]["edition"],
            "decay_applied": new_perf["month_correction_applied"],
            "notes": [
                ("Window is the fixed qualification period; recomputed scores may differ "
                 "from WA's published (rolling-window) scores."
                 if window_kind == "fixed" else
                 "Rolling window matches WA's published ranking scores."),
                "Hypothetical result dated as_of, so no age-decay (month correction) is applied to it.",
                "Other athletes are held at their current ranking scores (static field).",
                (f"Similar events count; at least {main_min} of {best_n} counting performances "
                 "must be the main event." if main_min else
                 "Similar events count; no main-event minimum configured."),
                "Old/new rank uses the live ranking list; new rank assumes only this athlete changes.",
            ],
        },
        "hypothetical_performance": breakdown,
        "official_ranking_score": official_score,
        "recomputed_old_score": recomputed_old,
        "new_score": new_score,
        "score_delta": recompute["delta"],
        "new_perf_counts": recompute["new_perf_counts"],
        "old_rank": old_rank,
        "new_rank": new_rank,
        "rank_delta": (None if old_rank is None else old_rank - new_rank),
        "old_counting": recompute["old_counting"],
        "new_counting": recompute["new_counting"],
        "qualification": qualification,
        "profile_summary": profile_summary,
        "what_would_it_take": what_would_it_take,
    }
    if verbose:
        print(format_report(result))
    return result


def _required_time(event: str, counting_old: list[dict], best_n: int,
                   placing: int, target: float) -> tuple[str | None, int | None]:
    """Time (before placing points) a single new race needs so the athlete's average reaches
    `target`, given their existing counting performances and the projected placing score."""
    scores = sorted((p["performance_score"] for p in counting_old), reverse=True)
    n = len(scores)
    if n + 1 <= best_n:                       # new result just adds to the set
        need_perf = target * (n + 1) - sum(scores)
    else:                                     # new result displaces the weakest
        need_perf = target * best_n - sum(scores[: best_n - 1])
    need_result = math.ceil(need_perf - placing)
    return time_for_result_score(event, need_result), need_result


def _targets_required(event: str, counting_old: list[dict], best_n: int, placing: int,
                      current_score: float | None, targets: list[tuple[str, float]]) -> list[dict]:
    """Reverse solver: for each (label, target_score), the time a single new race at `placing`
    placing points would need to lift the athlete's average to that target. Reuses
    _required_time. status: 'met' (current score already at/above the target), 'reachable'
    (time shown), or 'unreachable' (needs a faster result than the table tops out at — try a
    higher place/category)."""
    rows = []
    for label, score in targets:
        if score is None:
            continue
        if current_score is not None and current_score >= score:
            rows.append({"label": label, "target_score": round(score),
                         "result_score": None, "time": None, "status": "met"})
            continue
        time, need_result = _required_time(event, counting_old, best_n, placing, score)
        rows.append({"label": label, "target_score": round(score), "result_score": need_result,
                     "time": time, "status": "reachable" if time else "unreachable"})
    return rows


def required_targets(event: str, athlete: str, *, championship: str = "road_to_birmingham",
                     place: int = 1, category: str = "GW", force_refresh: bool = False) -> dict:
    """Reverse solver, standalone (no hypothetical time needed): for a ranked athlete, the time
    a single new race finishing `place` in a `category` meet would need to reach key targets —
    the qualifying cutoff and #1 — computed from current standings."""
    champ = load_championship(championship)
    ev = load_event(event)
    champ_event = championship_event_config(championship, event)
    best_n = ev["best_n"]
    placing_group = ev.get("placing_event_group", "standard")
    sel = {"always_include_competitions": tuple(champ.get("always_include_competitions", ())),
           "main_event_codes": tuple(ev.get("main_event_codes", ())),
           "main_event_min": ev.get("main_event_min", 0)}

    data = fetch.fetch_championship(championship, event, force=force_refresh)
    ath = fetch.find_athlete(data, athlete)
    if ath is None:
        raise ValueError(f"'{athlete}' is not in the {championship} {event} ranking list.")
    old_counting = select_counting(ath["performances"], best_n, **sel)
    placing = placing_score(category, place, placing_group)
    others = [a["ranking_score"] for a in data["athletes"] if a is not ath]
    top = max((s for s in others if s is not None), default=None)

    cutoff = None
    if "quota" in champ_event:
        field = qualifying_field(build_ranked(data["athletes"]), champ_event["quota"],
                                 max_per_country=champ.get("max_per_country", 3),
                                 defending_champion=champ_event.get("defending_champion"))
        cutoff = field["cutoff_score"]

    targets = []
    if cutoff is not None:
        targets.append(("reach the qualifying cutoff", cutoff))
    if top is not None:
        targets.append(("reach #1", top + 1))
    rows = _targets_required(event, old_counting, best_n, placing, ath.get("ranking_score"), targets)
    return {"event": event, "championship": championship, "athlete": ath["name"],
            "place": place, "category": category.upper(), "targets": rows}


def _fmt_perf(p: dict) -> str:
    tag = " *NEW*" if p.get("hypothetical") else ""
    return (f"    {p.get('performance_score'):>5}  "
            f"{p.get('mark',''):<9} {p.get('category',''):<3} "
            f"P{p.get('place','?'):<3} {p.get('date','')}  "
            f"{(p.get('competition') or '')[:42]}{tag}")


def format_report(r: dict) -> str:
    a = r["assumptions"]
    b = r["hypothetical_performance"]
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append(f"WHAT-IF  ·  {r['athlete']} ({r['country']})  ·  {r['event']}")
    lines.append(f"Championship: {r['championship']}")
    lines.append("=" * 72)
    lines.append("")
    lines.append("ASSUMPTIONS")
    lines.append(f"  Ranking score   : mean of best {a['best_n']} performances")
    lines.append(f"  Window          : {a['window_kind']} "
                 f"({a['window_start']} -> {a['window_end']})")
    lines.append(f"  Evaluated as of : {r['as_of']}   (live rank date: {r['rank_date']})")
    lines.append(f"  Result table    : {a['result_table']}")
    lines.append(f"  Placing table   : {a['placing_edition']} edition, "
                 f"category {a['category']}, place {a['place']}"
                 f"{', indoor' if a['indoor'] else ''}")
    for n in a["notes"]:
        lines.append(f"  - {n}")
    lines.append("")
    lines.append("HYPOTHETICAL PERFORMANCE")
    lines.append(f"  Time {b['time']}  ->  result score {b['result_score']}")
    lines.append(f"  Place {b['place']} in category {b['category']}  ->  "
                 f"placing score {b['placing_score']}")
    if b["decay"]:
        lines.append(f"  Age decay ({b['months_old']} mo): {b['decay']}")
    lines.append(f"  Performance score = {b['performance_score']}")
    lines.append("")
    ps = r.get("profile_summary")
    if ps:
        lines.extend(_format_profile_result(r, ps))
    else:
        lines.append("RESULT")
        lines.append(f"  Official ranking score (now) : {r['official_ranking_score']}")
        if r["recomputed_old_score"] != r["official_ranking_score"]:
            lines.append(f"  Recomputed from breakdown    : {r['recomputed_old_score']} "
                         f"(should match official; small diffs = WA rounding/rules)")
        counts = "counts (made best-N)" if r["new_perf_counts"] else "does NOT beat current best-N"
        lines.append(f"  New ranking score            : {r['new_score']}  "
                     f"({_signed(r['score_delta'])}, new perf {counts})")
        lines.append(f"  Rank                         : "
                     f"{r['old_rank']}  ->  {r['new_rank']}  ({_signed(r['rank_delta'])} places)")
    lines.append("")
    lines.append("NEW COUNTING PERFORMANCES (best N)")
    for p in r["new_counting"]:
        lines.append(_fmt_perf(p))

    if r.get("qualification"):
        lines.extend(_format_qualification(r["qualification"]))

    lines.append("=" * 72)
    return "\n".join(lines)


def _format_profile_result(r: dict, ps: dict) -> list[str]:
    best = f"best ever #{ps['best_rank']}" if ps["best_rank"] else "no prior ranking"
    lines = ["RESULT  (athlete sourced from profile — not on the live ranking list)"]
    lines.append(f"  Currently       : UNRANKED in {r['event']}  ({best}, "
                 f"{ps['best_rank_weeks']} wks at it) — no current WA ranking")
    lines.append(f"  Counting results: {ps['counting_now']} now -> {ps['counting_with_new']} "
                 f"with this race  (a full ranking averages {r['assumptions']['best_n']})")
    if ps["short_of_full_set"]:
        lines.append(f"                    still {ps['short_of_full_set']} short of a full "
                     f"{r['assumptions']['best_n']}-performance set")
    lines.append(f"  Would average   : {r['new_score']} points "
                 f"(over {ps['counting_with_new']} results, with this race)")
    lines.append(f"  Would rank      : ~#{r['new_rank']} by score (raw position, before the "
                 "3-per-country cap; see QUALIFICATION for the cap-adjusted picture)")
    if ps["required_time"]:
        lines.append(f"  To reach the {ps['target_label']} ({ps['target_score']}), the race "
                     f"would need ~{ps['required_time']} (before placing points)")
    if ps.get("incomplete_window"):
        lines.append("  ! Only the latest season's results were retrieved (no API key); a "
                     "counting result in an earlier year inside the window may be missing.")
    return lines


_STATUS_LABEL = {
    "qualified": "QUALIFIES",
    "blocked_country_cap": "BLOCKED (country cap)",
    "out": "does not qualify",
}


def _format_qualification(q: dict) -> list[str]:
    lines = ["", "QUALIFICATION"]
    champ = q["defending_champion"]
    quota_tag = "  (TOTAL field; ranking fills what's left after entry standards - see note)" if q["quota_is_total_field"] else ""
    lines.append(f"  Quota           : {q['quota']} places{quota_tag}")
    if champ:
        lines.append(f"  Defending champ : {champ['name']} ({champ.get('country')}) "
                     f"- bye at #1, exempt from country cap; {q['ranking_places']} ranking places remain")
    lines.append(f"  Country cap     : max {q['max_per_country']} per country "
                 f"(this athlete's country currently fills {q['country_count']})")
    cut = q["cutoff_score"]
    cc = q.get("country_count", 0)
    lines.append(f"  Ranking cutoff  : {cut if cut is not None else 'n/a'} "
                 "(score of the last ranking qualifier)")
    if q["is_defending_champion"]:
        lines.append("  Status          : QUALIFIES as defending champion (bye) regardless of ranking")
    elif q.get("above_cutoff") and q["status_new"] == "qualified":
        pos = q["qual_position_new"]
        lines.append(f"  Status          : ABOVE THE CUTOFF — auto-confirmed at qual position {pos}")
    elif q.get("above_cutoff"):
        # Eligible on merit, but the country's 3 places are held by higher-ranked athletes.
        lines.append("  Status          : ABOVE THE CUTOFF — eligible on score, NOT auto-confirmed")
        lines.append(f"                    {q['country_ahead']} higher-ranked compatriots for "
                     f"{q['max_per_country']} places. A country sends UP TO {q['max_per_country']} "
                     "(not necessarily its top-ranked), so selection is the federation's call.")
    else:
        lines.append("  Status          : BELOW THE CUTOFF — would not qualify on ranking")
    return lines


def _signed(v) -> str:
    if v is None:
        return "n/a"
    return f"+{v}" if v > 0 else str(v)
