"""Data layer: scrape the World Athletics ranking list + per-athlete scoring breakdown.

Two sources, both public (no API key required):

1. The ranking list page (e.g. /world-rankings/1500m/men) is server-rendered HTML.
   Each row carries data-id (the ranking-entry / competitorId used below), the athlete
   slug, rank, name, DOB, nation and ranking score.

2. /WorldRanking/RankingScoreCalculation?competitorId=<data-id> returns a (string-encoded)
   JSON object with the athlete's counting performances, each including resultScore,
   placingScore and performanceScore.

Everything is normalised and cached to data/cache/*.json with a TTL.
"""
from __future__ import annotations

import html
import json
import re
import time
from datetime import datetime

import requests

from . import cache
from .config import load_championship
from .wa_parse import parse_place, parse_wa_date

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (wa-ranking-whatif research tool)",
    "X-Requested-With": "XMLHttpRequest",
}
_TIMEOUT = 30

# A ranking table row: capture the opening <tr ...> attrs plus the row body up to </tr>.
_ROW_RE = re.compile(
    r'data-id="(?P<id>\d+)"\s+data-athlete-url="(?P<slug>[^"]+)"(?P<body>.*?)</tr>',
    re.S,
)
_CELL_RE = re.compile(r'<td[^>]*data-th="(?P<th>[^"]+)"[^>]*>(?P<val>.*?)</td>', re.S)


def _clean(fragment: str) -> str:
    """Strip tags/whitespace from an HTML cell fragment."""
    text = re.sub(r"<[^>]+>", " ", fragment)
    return html.unescape(" ".join(text.split()))


def parse_ranking_html(doc: str) -> list[dict]:
    """Parse the ranking list page into a list of athlete rows (ranking order)."""
    athletes: list[dict] = []
    for m in _ROW_RE.finditer(doc):
        cells = {c.group("th"): _clean(c.group("val")) for c in _CELL_RE.finditer(m.group("body"))}
        if "Competitor" not in cells:
            continue  # not a data row
        rank_txt = cells.get("Rank", "")
        score_txt = cells.get("score", "")
        athletes.append(
            {
                "competitor_id": m.group("id"),
                "slug": m.group("slug"),
                "rank": int(rank_txt) if rank_txt.isdigit() else None,
                "name": cells.get("Competitor", ""),
                "dob": cells.get("DOB", ""),
                "country": cells.get("Nat", ""),
                "ranking_score": float(score_txt) if score_txt.replace(".", "", 1).isdigit() else None,
            }
        )
    return athletes


def normalize_performance(r: dict) -> dict:
    """Normalise one entry from the RankingScoreCalculation 'results' list."""
    return {
        "date": parse_wa_date(r.get("date")),
        "date_raw": r.get("date"),
        "competition": r.get("competition"),
        "category": r.get("category"),
        "discipline_code": r.get("disciplineCode"),
        "discipline": r.get("discipline"),
        "indoor": bool(r.get("indoor")),
        "place": parse_place(r.get("place")),
        "mark": (r.get("mark") or "").strip(),
        "result_score": r.get("resultScore"),
        "placing_score": r.get("placingScore"),
        "performance_score": r.get("performanceScore"),
        "month_correction_applied": bool(r.get("monthCorrectionApplied")),
    }


def _decode_calc(text: str) -> dict:
    """RankingScoreCalculation returns a JSON-encoded string; decode (possibly twice)."""
    payload = json.loads(text)
    if isinstance(payload, str):
        payload = json.loads(payload)
    return payload


def fetch_athlete_calculation(competitor_id: str, calc_url_template: str,
                              session: requests.Session | None = None) -> dict:
    """Fetch + normalise one athlete's ranking-score breakdown."""
    s = session or requests
    url = calc_url_template.format(competitor_id=competitor_id)
    resp = s.get(url, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    payload = _decode_calc(resp.text)
    return {
        "competitor_id": competitor_id,
        "athlete": payload.get("athlete"),
        "slug": payload.get("athleteUrlSlug"),
        "country": payload.get("country"),
        "birth_date": parse_wa_date(payload.get("birthDate")),
        "rank_date": parse_wa_date(payload.get("rankDate")),
        "rank_date_raw": payload.get("rankDate"),
        "event_group": payload.get("eventGroup"),
        "rank": payload.get("place"),
        "performances": [normalize_performance(r) for r in payload.get("results", [])],
    }


def fetch_championship(championship: str, event: str, *, force: bool = False,
                       ttl_seconds: int = cache.DEFAULT_TTL_SECONDS,
                       limit: int | None = None) -> dict:
    """Fetch (or load from cache) one event's ranking list + every athlete's breakdown.

    The rankings URL is built from the championship's `rankings_url_template` using the
    event's discipline + gender. Returns {championship, event, fetched, rank_date,
    athletes:[...]}. Cached under a per-(championship, event) key.

    A championship with `data_source` (e.g. road_to_ultimate → world) shares another
    championship's ranking list: same athletes/scores, different qualification overlay —
    so the fetch (and cache key) is delegated rather than duplicated.
    """
    from .config import load_event

    source = load_championship(championship).get("data_source")
    if source and source != championship:
        data = fetch_championship(source, event, force=force,
                                  ttl_seconds=ttl_seconds, limit=limit)
        return {**data, "championship": championship}

    key = f"{championship}__{event}"
    if not force:
        cached = cache.read(key, ttl_seconds=ttl_seconds)
        if cached is not None:
            return cached

    champ = load_championship(championship)
    ev = load_event(event)
    rankings_url = champ["rankings_url_template"].format(
        event_path=ev["discipline"], gender=ev["gender"])
    session = requests.Session()

    resp = session.get(rankings_url, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    rows = parse_ranking_html(resp.text)
    if not rows and ev.get("graphql_event_group"):
        rows = _rankings_via_graphql(ev, champ)  # e.g. steeplechase doesn't server-render
    if limit is not None:
        rows = rows[:limit]

    athletes = []
    rank_date = None
    for i, row in enumerate(rows):
        if i:
            time.sleep(0.2)  # be polite: small gap between per-athlete calls
        calc = fetch_athlete_calculation(row["competitor_id"], champ["calculation_url"], session)
        rank_date = rank_date or calc.get("rank_date")
        athletes.append({**row, "performances": calc["performances"], "rank_date": calc.get("rank_date")})

    result = {
        "championship": championship,
        "event": event,
        "rankings_url": rankings_url,
        "fetched": datetime.now().isoformat(timespec="seconds"),
        "rank_date": rank_date,
        "athletes": athletes,
    }
    cache.write(key, result)
    return result


def _rankings_via_graphql(ev: dict, champ: dict) -> list[dict]:
    """Build ranking rows via GraphQL for events the HTML page doesn't render (steeplechase).

    The accessible rankings feed is women-only, so this raises for men's events rather than
    return the wrong gender.
    """
    from . import graphql

    region = champ.get("region")
    data = graphql.world_rankings(ev["graphql_event_group"],
                                  region_type="area" if region else None, region=region)
    if data is None:
        return []
    returned_gender = (data.get("parameters") or {}).get("gender")
    if ev["gender"] == "men" or returned_gender == "women" and ev["gender"] != "women":
        raise RuntimeError(
            f"{ev['label']} rankings aren't available yet — World Athletics doesn't publish "
            "this event's ranking list in a form this tool can read (the women's list works). "
            "Every other event is available normally.")
    return [{
        "competitor_id": str(r["id"]),
        "slug": r.get("competitorUrlSlug"),
        "rank": r.get("place"),
        "name": r.get("competitorName", ""),
        "dob": parse_wa_date(r.get("competitorBirthDate")),
        "country": r.get("countryCode"),
        "ranking_score": r.get("rankingScore"),
    } for r in (data.get("rankings") or [])]


def find_athlete(data: dict, name: str) -> dict | None:
    """Case-insensitive match on athlete name (full or partial)."""
    needle = name.strip().lower()
    exact = [a for a in data["athletes"] if a["name"].lower() == needle]
    if exact:
        return exact[0]
    partial = [a for a in data["athletes"] if needle in a["name"].lower()]
    return partial[0] if len(partial) == 1 else (partial[0] if partial else None)
