"""World Athletics 'road to' qualification feed: quota, entry standard, wildcards, and who has
already achieved the standard.

For a championship that qualifies by *entry standard + world rankings* (the World
Championships), the ranking list alone can't say who is in: athletes who have met the entry
standard are in first, and the rankings only fill what is left of the target number. WA
publishes exactly that per event in `getChampionshipQualifications` (the data behind its
"Road to …" pages): `entryNumber` (the target field), `entryStandard`, the qualification
window, `maxCompetitorsByCoutnry`, and rows tagged "Qualified" (+ a label such as
"Defending World Champion"), "Qualified by Entry Standard" (with the mark and date),
"In World Rankings quota*" and "Next best by World Rankings".

A championship opts in with a `qualification_feed` block in championships.json (WA
competition id + the WA event id per event). Snapshots are cached/seeded like ranking lists
(`data/cache_seed/feed__<champ>__<event>.json`, refreshed by scripts.refresh_seed), so the
site builds offline. `event_qualification` overlays a snapshot on the JSON config: the feed
wins on quota / entry standard / window / wildcards / standard achievers; the JSON values are
the fallback when no snapshot exists, and hand-maintained wildcards the feed doesn't carry
yet (e.g. Ultimate Championship winners) are merged in.

Network-only code lives in `fetch_feed`; everything else is pure and covered by
tests/test_feed.py with stubbed payloads.
"""
from __future__ import annotations

import re
from datetime import datetime

from . import cache
from .config import championship_event_config, load_championship
from .wa_parse import parse_wa_date

_QUERY = """query Q($competitionId:Int!,$eventId:Int){
  getChampionshipQualifications(competitionId:$competitionId,eventId:$eventId){
    eventId entryNumber entryStandard maxCompetitorsByCoutnry
    firstQualificationDay lastQualificationDay rankDate
    numberOfCompetitorsQualifiedByEntryStandard numberOfCompetitorsFilledUpByWorldRankings
    disciplineName
    alternativeEntryStandards { entryStandard event }
    qualifications { qualifiedBy qualified qualificationPosition name countryCode score
                     urlSlug label result date venue }
  }
}"""

_BY_WILDCARD = "Qualified by Wild Card"      # Ultimate-style rows
_BY_QUALIFIED = "Qualified"                  # Beijing-style rows (label says why)
_BY_STANDARD = "Qualified by Entry Standard"
# WA sometimes returns `label` as a stringified map, e.g. "{label=Olympic Champion}".
_LABEL_RE = re.compile(r"label=(?P<label>[^}]*)}")
_ATHLETE_ID_RE = re.compile(r"(\d+)$")


def cache_key(championship: str, event: str) -> str:
    return f"feed__{championship}__{event}"


def athlete_key(slug: str | None, name: str) -> str:
    """Stable identity for matching feed rows to ranking rows: the trailing WA athlete id in
    the slug (the two sources spell the slug differently), falling back to the name."""
    m = _ATHLETE_ID_RE.search(slug or "")
    return m.group(1) if m else (name or "").strip().upper()


def _label(raw) -> str | None:
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw.get("label")
    m = _LABEL_RE.search(str(raw))
    return m.group("label").strip() if m else (str(raw).strip() or None)


def _window(payload: dict) -> dict | None:
    start = parse_wa_date(payload.get("firstQualificationDay"))
    end = parse_wa_date(payload.get("lastQualificationDay"))
    return {"start": start, "end": end} if start and end else None


def parse_feed(payload: dict) -> dict:
    """Normalise one event's `getChampionshipQualifications` payload.

    Returns {quota, discipline, entry_standard, alt_entry_standards, max_per_country, window,
    rank_date, counts, auto_invites, standard_achievers}. `quota` is WA's entryNumber (the
    target field, wildcards included); `auto_invites` the byes WA lists with its own label;
    `standard_achievers` everyone WA marks "Qualified by Entry Standard", with the mark.
    """
    rows = payload.get("qualifications") or []
    invites, achievers = [], []
    for r in rows:
        by = r.get("qualifiedBy")
        if by == _BY_WILDCARD or (by == _BY_QUALIFIED and _label(r.get("label"))):
            invites.append({
                "name": r.get("name"),
                "country": r.get("countryCode"),
                "reason": _label(r.get("label")) or "wildcard",
            })
        elif by == _BY_STANDARD:
            achievers.append({
                "name": r.get("name"),
                "country": r.get("countryCode"),
                "mark": (r.get("result") or "").strip() or None,
                "date": parse_wa_date(r.get("date")),
                "venue": r.get("venue"),
                "slug": r.get("urlSlug"),
            })
    return {
        "quota": payload.get("entryNumber"),
        "discipline": payload.get("disciplineName"),
        "entry_standard": (payload.get("entryStandard") or "").strip() or None,
        "alt_entry_standards": [
            {"event": a.get("event"), "entry_standard": a.get("entryStandard")}
            for a in (payload.get("alternativeEntryStandards") or [])
            if a.get("event") and a.get("entryStandard")],
        "max_per_country": payload.get("maxCompetitorsByCoutnry"),
        "window": _window(payload),
        "rank_date": parse_wa_date(payload.get("rankDate")),
        "counts": {
            "entry_standard": payload.get("numberOfCompetitorsQualifiedByEntryStandard"),
            "world_rankings": payload.get("numberOfCompetitorsFilledUpByWorldRankings"),
        },
        "auto_invites": invites,
        "standard_achievers": achievers,
    }


def feed_events(championship: str) -> dict:
    """{event_key: WA event id} for a championship that declares a qualification feed."""
    return (load_championship(championship).get("qualification_feed") or {}).get("events", {})


def read_feed(championship: str, event: str,
              ttl_seconds: int | None = cache.DEFAULT_TTL_SECONDS) -> dict | None:
    """The cached/seeded feed snapshot for one event, or None if there isn't one."""
    if event not in feed_events(championship):
        return None
    return cache.read(cache_key(championship, event), ttl_seconds=ttl_seconds)


def fetch_feed(championship: str, event: str, *, force: bool = False,
               ttl_seconds: int = cache.DEFAULT_TTL_SECONDS) -> dict:
    """Fetch (or load from cache) one event's qualification feed.

    Network-only path: hits WA's GraphQL endpoint (the same CORS-open API the name search
    uses). Raises KeyError if the championship/event has no feed configured.
    """
    from . import graphql

    events = feed_events(championship)
    if event not in events:
        raise KeyError(f"{championship} declares no qualification feed for '{event}'.")
    if not force:
        cached = cache.read(cache_key(championship, event), ttl_seconds=ttl_seconds)
        if cached is not None:
            return cached

    competition_id = load_championship(championship)["qualification_feed"]["competition_id"]
    event_id = events[event]
    data = graphql.query(_QUERY, {"competitionId": int(competition_id), "eventId": int(event_id)})
    payload = (data or {}).get("getChampionshipQualifications")
    if not payload or payload.get("entryNumber") is None:
        raise RuntimeError(
            f"World Athletics returned no qualification feed for {championship}/{event}.")

    result = {
        "championship": championship,
        "event": event,
        "competition_id": int(competition_id),
        "event_id": int(event_id),
        "fetched": datetime.now().isoformat(timespec="seconds"),
        **parse_feed(payload),
    }
    cache.write(cache_key(championship, event), result)
    return result


def _merge_invites(feed_invites: list[dict], config_invites: list[dict]) -> list[dict]:
    """Feed wildcards first (WA's own labels), then hand-maintained ones the feed doesn't
    carry yet (e.g. Ultimate Championship winners) — deduplicated by name."""
    seen, out = set(), []
    for inv in list(feed_invites) + list(config_invites):
        key = (inv.get("name") or "").upper()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(inv)
    return out


def event_qualification(championship: str, event: str) -> dict:
    """Per-event qualification config with the feed snapshot overlaid when there is one.

    The feed is authoritative for what it knows better than a hand-maintained file — field
    size, entry standard (+ road/mile alternatives), window, the byes WA has recorded and the
    athletes who have achieved the standard. championships.json remains the source for
    everything else, and the whole answer when no snapshot exists (`qualification_source`
    is then "config" and `standard_achievers` is absent = unknown).
    """
    cfg = dict(championship_event_config(championship, event))
    if not cfg:
        return cfg
    snap = read_feed(championship, event, ttl_seconds=None)  # a stale snapshot beats none
    if not snap or snap.get("quota") is None:
        return {**cfg, "qualification_source": "config"}
    out = {
        **cfg,
        "quota": snap["quota"],
        "auto_invites": _merge_invites(snap.get("auto_invites") or [], cfg.get("auto_invites") or []),
        "standard_achievers": snap.get("standard_achievers") or [],
        "qualification_source": "feed",
        "feed_fetched": snap.get("fetched"),
        "feed_counts": snap.get("counts"),
    }
    if snap.get("entry_standard"):
        out["entry_standard"] = snap["entry_standard"]
    if snap.get("alt_entry_standards"):
        out["alt_entry_standards"] = snap["alt_entry_standards"]
    if snap.get("window"):
        out["qualification_window"] = snap["window"]
    out.pop("defending_champion", None)  # byes are carried by auto_invites once overlaid
    return out
