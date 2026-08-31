"""World Athletics 'road to' qualification feed: who is actually in a championship's field.

The ranking list alone doesn't answer "who's going". For an invitational like the Ultimate
Championship, WA publishes a separate qualification feed (`getChampionshipQualifications`)
listing, per event, the wildcards, the ranking qualifiers and a tail of next-best athletes.
Two things only that feed knows:

  - **the wildcards actually taken** (Olympic champion / World champion / the Diamond League
    Final winner once Brussels is run / an exceptional or host-federation invitation), and the
    resulting field size — the men's 1500m sits at 13 because two exceptional invitations were
    added to the base 12;
  - **who is ranked but not in the field.** An athlete who has declined, is injured or is
    contesting another event is dropped from the feed entirely while staying on the world
    ranking list. They hold their ranking position but take no qualifying place, so the real
    cutoff sits lower than the list implies.

Absence is only meaningful above the feed's tail: WA lists ~40 next-best athletes, so someone
below the last listed score is simply out of frame, not withdrawn. `derive_not_in_field`
applies exactly that rule and says nothing about anyone further down.

A championship opts in with a `qualification_feed` block in championships.json (competition id
+ the WA event id per event). Snapshots are cached/seeded like ranking lists, so the site
builds offline; `event_qualification` overlays the snapshot on the JSON config, which stays as
the fallback when no snapshot exists.
"""
from __future__ import annotations

import re
from datetime import datetime

from . import cache
from .config import championship_event_config, load_championship

_QUERY = """query Q($competitionId:Int!,$eventId:Int){
  getChampionshipQualifications(competitionId:$competitionId,eventId:$eventId){
    entryNumber
    disciplineName
    qualifications{ qualifiedBy qualified qualificationPosition name countryCode score urlSlug label }
  }
}"""

_WILDCARD = "Qualified by Wild Card"
# WA returns `label` as a stringified map, e.g. "{label=Olympic Champion}".
_LABEL_RE = re.compile(r"label=(?P<label>[^}]*)}")
_ATHLETE_ID_RE = re.compile(r"(\d+)$")


def cache_key(championship: str, event: str) -> str:
    return f"feed__{championship}__{event}"


def athlete_key(slug: str | None, name: str) -> str:
    """Stable identity for matching feed rows to ranking rows.

    The two sources spell the slug differently ('/athletes/kenya/x-14413305' vs
    'kenya/x-14413305') but share the trailing WA athlete id; fall back to the name.
    """
    m = _ATHLETE_ID_RE.search(slug or "")
    return m.group(1) if m else (name or "").strip().upper()


def _label(raw) -> str | None:
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw.get("label")
    m = _LABEL_RE.search(str(raw))
    return m.group("label").strip() if m else str(raw).strip() or None


def parse_feed(payload: dict) -> dict:
    """Normalise one event's `getChampionshipQualifications` payload.

    Returns {quota, auto_invites, in_field, tail_score, discipline}: `quota` is WA's
    entryNumber (the real field size, wildcards included), `in_field` the athlete keys of
    everyone the feed lists at all, and `tail_score` the lowest ranking score it shows —
    the floor below which absence tells us nothing.
    """
    rows = payload.get("qualifications") or []
    invites, in_field, scores = [], [], []
    for r in rows:
        key = athlete_key(r.get("urlSlug"), r.get("name"))
        in_field.append(key)
        if r.get("score") is not None:
            scores.append(float(r["score"]))
        if r.get("qualifiedBy") == _WILDCARD:
            invites.append({
                "name": r.get("name"),
                "country": r.get("countryCode"),
                "reason": _label(r.get("label")) or "wildcard",
            })
    return {
        "quota": payload.get("entryNumber"),
        "discipline": payload.get("disciplineName"),
        "auto_invites": invites,
        "in_field": in_field,
        "tail_score": min(scores) if scores else None,
    }


def derive_not_in_field(athletes: list[dict], feed: dict) -> list[dict]:
    """Ranked athletes WA doesn't list in the field, in ranking order.

    Only athletes scoring at or above the feed's tail count: below it we can't distinguish
    "withdrawn" from "outside the listed tail", so they're left alone.
    """
    tail = feed.get("tail_score")
    if tail is None:
        return []
    listed = set(feed.get("in_field") or [])
    absent = []
    for a in athletes:
        score = a.get("ranking_score")
        if score is None or score < tail:
            continue
        if athlete_key(a.get("slug"), a.get("name")) in listed:
            continue
        absent.append({"name": a["name"], "country": a.get("country"),
                       "score": score, "reason": "not in the field"})
    return absent


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

    Network-only path: hits WA's GraphQL endpoint, the same CORS-open API the name search
    uses. Raises KeyError if the championship/event has no feed configured.
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
    if not payload:
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


def event_qualification(championship: str, event: str, athletes: list[dict]) -> dict:
    """Per-event qualification config, with the feed snapshot overlaid when there is one.

    The feed is authoritative for the three things it knows better than a hand-maintained
    JSON file — field size, wildcards, and who isn't in the field — so a weekly refresh keeps
    the tool in step with WA without an edit. championships.json remains the source for
    everything else (and the whole answer when no snapshot exists, e.g. Birmingham).
    """
    cfg = dict(championship_event_config(championship, event))
    feed = read_feed(championship, event, ttl_seconds=None)  # a stale snapshot beats none
    if not feed or feed.get("quota") is None:
        return cfg
    return {
        **cfg,
        "quota": feed["quota"],
        "auto_invites": feed["auto_invites"],
        "not_in_field": derive_not_in_field(athletes, feed),
        "qualification_source": "feed",
        "feed_fetched": feed.get("fetched"),
    }
