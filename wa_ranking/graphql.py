"""Minimal World Athletics AppSync GraphQL client, used only by the profile fallback to pull
an athlete's results for a specific year (the public profile HTML only serves the latest one).

World Athletics gates the GraphQL endpoint with an `x-api-key` that rotates. We discover a
working key dynamically: try an env override / cached key / a seed, then, if those fail,
scrape the current keys out of the site's JS chunks and test each. The winner is cached.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

import requests

from . import cache

ENDPOINT = "https://lsloqtmox5h3zf2ydlvbvnvr7e.appsync-api.eu-west-1.amazonaws.com/graphql"
_SEED_KEY = "da2-jkcja3ykujbf3cz64fs7w5gl6m"   # works at time of writing; rotates
_KEY_CACHE = "wa_api_key"
_KEY_RE = re.compile(r"da2-[a-z0-9]{26}")
_CHUNK_RE = re.compile(r"/_next/static/chunks/[A-Za-z0-9/_.-]+\.js")
_HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://worldathletics.org",
    "Referer": "https://worldathletics.org/",
    "User-Agent": "Mozilla/5.0 (wa-ranking-whatif research tool)",
}
_PROBE = ("query P($id:Int,$y:Int){getSingleCompetitorResultsDiscipline"
          "(id:$id,resultsByYear:$y){activeYears}}")


class GraphQLUnavailable(RuntimeError):
    """Raised when no working API key could be obtained."""


def _post(query: str, variables: dict, key: str, timeout: int = 25) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers={**_HEADERS, "x-api-key": key})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def _key_works(key: str) -> bool:
    try:
        r = _post(_PROBE, {"id": 14597392, "y": 2022}, key)
        return "data" in r and not _is_auth_error(r)
    except urllib.error.HTTPError as e:
        return e.code != 401
    except Exception:
        return False


def _is_auth_error(resp: dict) -> bool:
    return any("Unauthorized" in (e.get("errorType", "") + e.get("message", ""))
               for e in resp.get("errors", []) or [])


def _scrape_candidate_keys() -> list[str]:
    """Pull candidate da2- keys out of the WA site's current JS chunks."""
    keys: list[str] = []
    page = requests.get("https://worldathletics.org/stats-zone", headers=_HEADERS, timeout=25).text
    chunks = sorted(set(_CHUNK_RE.findall(page)))
    for path in chunks:
        try:
            js = requests.get("https://worldathletics.org" + path, headers=_HEADERS, timeout=25).text
        except requests.RequestException:
            continue
        for k in _KEY_RE.findall(js):
            if k not in keys:
                keys.append(k)
    return keys


def get_api_key(force: bool = False) -> str:
    """Return a working API key, refreshing (env -> cache -> seed -> scrape) as needed."""
    if not force:
        env = os.environ.get("WA_API_KEY")
        if env:
            return env
        cached = cache.read(_KEY_CACHE, ttl_seconds=7 * 24 * 3600)
        if cached and cached.get("key") and _key_works(cached["key"]):
            return cached["key"]
    for key in [_SEED_KEY, *(_scrape_candidate_keys())]:
        if _key_works(key):
            cache.write(_KEY_CACHE, {"key": key})
            return key
    raise GraphQLUnavailable("No working World Athletics API key found (key may have rotated).")


_RANKINGS_QUERY = """query R($eventGroup:String,$regionType:String,$region:String,$limit:Int){
  getWorldRankings(eventGroup:$eventGroup,regionType:$regionType,region:$region,limit:$limit){
    rankDate parameters{gender}
    rankings{ id place competitorName competitorUrlSlug competitorBirthDate countryCode rankingScore }
  }
}"""


def world_rankings(event_group: str, region_type: str | None = None,
                   region: str | None = None, limit: int | None = None) -> dict:
    """Fetch a world-ranking list via GraphQL (used when the HTML page doesn't server-render,
    e.g. the steeplechase). NOTE: this feed currently returns **women only** regardless of the
    requested gender — callers must guard against using it for men's events."""
    data = query(_RANKINGS_QUERY, {"eventGroup": event_group,
                                   "regionType": region_type or "world",
                                   "region": region, "limit": limit})
    return data["getWorldRankings"]


_SEARCH_QUERY = """query S($q:String){
  searchCompetitors(query:$q){ aaAthleteId familyName givenName disciplines gender country urlSlug }
}"""


def search_competitors(name: str) -> list[dict]:
    """Search World Athletics competitors by name. Returns raw competitor dicts (possibly empty)."""
    data = query(_SEARCH_QUERY, {"q": name})
    return data.get("searchCompetitors") or []


def query(query_str: str, variables: dict) -> dict:
    """Run a GraphQL query, refreshing the key once on auth failure. Returns the `data` dict."""
    key = get_api_key()
    try:
        resp = _post(query_str, variables, key)
        if _is_auth_error(resp):
            raise urllib.error.HTTPError(ENDPOINT, 401, "Unauthorized", None, None)
    except urllib.error.HTTPError as e:
        if e.code != 401:
            raise
        resp = _post(query_str, variables, get_api_key(force=True))
    if resp.get("errors"):
        raise RuntimeError(f"GraphQL errors: {json.dumps(resp['errors'])[:200]}")
    return resp["data"]
