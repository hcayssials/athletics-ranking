"""Fallback data source: a single athlete's World Athletics profile.

Used when an athlete is NOT in the scraped ranking list (e.g. unranked / returning from
injury). Basic info (name, nationality, best-ever rank) comes from the profile page's
`__NEXT_DATA__`. Results come from the GraphQL `getSingleCompetitorResultsDiscipline` query,
fetched **per year across the whole window** so a counting set that spans two calendar years
is captured (the profile HTML alone only serves the latest season). We compute each result's
placing score from our own tables, since the feed gives the result score but not the placing.

If no GraphQL key can be obtained, we fall back to the profile HTML (latest season only) and
flag the window as possibly incomplete.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime

import requests
from dateutil.relativedelta import relativedelta

from . import cache, graphql
from .config import load_event
from .scoring import placing_score

_PROFILE_URL = "https://worldathletics.org/athletes/x/{slug}"
_HEADERS = {"User-Agent": "Mozilla/5.0 (wa-ranking-whatif research tool)"}
_TIMEOUT = 30
_RESULTS_QUERY = """query D($id:Int,$resultsByYear:Int,$resultsByYearOrderBy:String){
  getSingleCompetitorResultsDiscipline(id:$id,resultsByYear:$resultsByYear,resultsByYearOrderBy:$resultsByYearOrderBy){
    resultsByEvent{ discipline disciplineCode results{ date competition venue category race place mark resultScore } }
  }
}"""

# The profile feed leaves disciplineCode null, so main/similar events are matched by name.
_SIMILAR_NAMES = {
    "800m": {"600 Metres", "1000 Metres", "800 Metres Short Track",
             "600 Metres Short Track", "1000 Metres Short Track"},
    "1500m": {"Mile", "2000 Metres", "1500 Metres Short Track", "Mile Short Track",
              "2000 Metres Short Track", "Mile Road"},
    "5000m": {"3000 Metres", "2 Miles", "5000 Metres Short Track",
              "3000 Metres Short Track", "2 Miles Short Track", "5 Kilometres"},
    "10000m": {"10 Kilometres"},
    "3000msc": {"2000 Metres Steeplechase"},
}


def _main_discipline_name(discipline: str) -> str:
    """'1500m' -> '1500 Metres', '10000m' -> '10,000 Metres' (WA commas only >= 10000)."""
    num = int(discipline.rstrip("m"))
    return (f"{num:,}" if num >= 10000 else str(num)) + " Metres"


def normalize_ref(ref: str) -> str:
    """Accept a full URL, 'country/name-id', or 'name-id'; return the final 'name-id' slug."""
    ref = ref.strip().rstrip("/")
    if "worldathletics.org" in ref or "/athletes/" in ref:
        ref = ref.split("/athletes/", 1)[-1]
    return ref.split("/")[-1]


def _athlete_id(slug: str) -> int | None:
    m = re.search(r"(\d+)$", slug)
    return int(m.group(1)) if m else None


def _name_from_slug(slug: str) -> str:
    return " ".join(p.capitalize() for p in re.sub(r"-\d+$", "", slug).split("-"))


def _parse_next_data(doc: str) -> dict:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', doc, re.S)
    if not m:
        raise ValueError("Could not find __NEXT_DATA__ on the profile page.")
    return json.loads(m.group(1))


def _parse_wa_date(raw: str) -> str | None:
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime((raw or "").strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _place_int(raw) -> int | None:
    m = re.search(r"\d+", str(raw or ""))
    return int(m.group()) if m else None


def _result_to_perf(r: dict, is_main: bool, main_code: str, group: str) -> dict:
    rscore = r.get("resultScore") or 0
    place = _place_int(r.get("place"))
    cat = r.get("category")
    pscore = placing_score(cat, place, group) if (cat and place) else 0
    return {
        "date": _parse_wa_date(r.get("date")),
        "competition": r.get("competition") or r.get("venue"),
        "category": cat,
        "discipline_code": main_code if is_main else "SIMILAR",
        "place": place,
        "mark": (r.get("mark") or "").strip(),
        "result_score": rscore,
        "placing_score": pscore,
        "performance_score": max(0, rscore + pscore),
        "is_main": is_main,
    }


def fetch_profile(ref: str, event: str, as_of: date, window_months: int, *,
                  force: bool = False, ttl_seconds: int = cache.DEFAULT_TTL_SECONDS) -> dict:
    """Return an athlete's window results for `event` (with computed performance scores),
    plus name, nationality and ranked/best-rank status."""
    slug = normalize_ref(ref)
    key = f"profile_{slug}__{event}__{as_of.isoformat()}"
    if not force:
        cached = cache.read(key, ttl_seconds=ttl_seconds)
        if cached is not None:
            return cached

    ev = load_event(event)
    group = ev.get("placing_event_group", "standard")
    main_code0 = ev["main_event_codes"][0]
    main_name = ev.get("discipline_name") or _main_discipline_name(ev["discipline"])
    similar_names = _SIMILAR_NAMES.get(ev["discipline"], set())
    window_start = as_of - relativedelta(months=window_months)

    # 1. Basic athlete info from the profile HTML (no key needed).
    resp = requests.get(_PROFILE_URL.format(slug=slug), headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    comp = _parse_next_data(resp.text)["props"]["pageProps"]["competitor"]
    country = (comp.get("basicData") or {}).get("countryCode")
    current = comp.get("worldRankings", {}).get("current") or []
    best = comp.get("worldRankings", {}).get("best") or []
    best_for_event = next((b for b in best if b.get("urlSlug") == ev["discipline"]), None)

    # 2. Results for every calendar year the window touches (GraphQL); fall back to HTML.
    perfs, incomplete = [], False
    years = range(window_start.year, as_of.year + 1)
    aid = _athlete_id(slug)
    try:
        for year in years:
            data = graphql.query(_RESULTS_QUERY,
                                 {"id": aid, "resultsByYear": year, "resultsByYearOrderBy": "discipline"})
            for blk in (data["getSingleCompetitorResultsDiscipline"] or {}).get("resultsByEvent") or []:
                disc = (blk.get("discipline") or "").strip()
                is_main = disc == main_name
                if not (is_main or disc in similar_names):
                    continue
                for r in blk.get("results") or []:
                    perfs.append(_result_to_perf(r, is_main, main_code0, group))
    except (graphql.GraphQLUnavailable, Exception):
        # Fall back to the profile HTML (latest active season only).
        incomplete = True
        perfs = []
        for blk in comp.get("resultsByYear", {}).get("resultsByEvent", []) or []:
            disc = (blk.get("discipline") or "").strip()
            is_main = disc == main_name
            if not (is_main or disc in similar_names):
                continue
            for r in blk.get("results") or []:
                if r.get("resultScore") is not None:
                    perfs.append(_result_to_perf(r, is_main, main_code0, group))

    # Keep only performances inside the window.
    perfs = [p for p in perfs if p["date"] and window_start.isoformat() < p["date"] <= as_of.isoformat()]

    result = {
        "slug": slug, "name": _name_from_slug(slug), "country": country, "event": event,
        "ranked": bool(current),
        "best_rank": (best_for_event or {}).get("place"),
        "best_rank_weeks": (best_for_event or {}).get("weeks"),
        "performances": perfs,
        "incomplete_window": incomplete,
        "years_fetched": list(years),
        "fetched": datetime.now().isoformat(timespec="seconds"),
    }
    cache.write(key, result)
    return result
