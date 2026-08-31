"""FastAPI wrapper exposing the what-if engine + ranking data to a web front-end.

Thin layer: every endpoint maps to an existing function that already returns JSON-ready data.
Run locally with:  uvicorn wa_ranking.api:app --reload
"""
from __future__ import annotations

import os
import threading
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import feed, fetch, graphql
from .config import (load_championship, load_championships,
                     load_event, load_events, load_placing_scores)
from .profile import _main_discipline_name
from .whatif import required_targets, what_if

# On boot, warm the cache for common (championship, event) lists so the first real request
# isn't slow (~40s/event). Cache-aware: fetch_championship is a no-op when data is fresh.
# Override with PREWARM="champ:event,champ:event" or disable with PREWARM="off".
_PREWARM_DEFAULT = "road_to_birmingham"  # all events under this championship


def _prewarm_pairs() -> list[tuple[str, str]]:
    spec = os.environ.get("PREWARM", _PREWARM_DEFAULT)
    if spec.lower() == "off":
        return []
    if ":" in spec:
        return [tuple(p.split(":", 1)) for p in spec.split(",") if ":" in p]
    return [(spec, ev) for ev in load_events()]  # PREWARM names a championship -> all events


def _prewarm() -> None:
    # force=True so we pull fresh live data into the (ephemeral) cache, overriding the baked
    # seed snapshot. Without force, fetch would just read the seed back and never revalidate.
    for champ, event in _prewarm_pairs():
        try:
            fetch.fetch_championship(champ, event, force=True)
        except Exception:
            pass  # e.g. men's steeplechase has no list — skip


@asynccontextmanager
async def lifespan(_app: FastAPI):
    threading.Thread(target=_prewarm, daemon=True).start()  # non-blocking
    yield


app = FastAPI(title="World Athletics ranking what-if API", version="1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_RANKING_FIELDS = ("rank", "name", "country", "ranking_score", "competitor_id", "slug")


@app.exception_handler(HTTPException)
async def _http_exc(request, exc: HTTPException):
    # Surface a consistent {"error": ...} shape for the UI.
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.exception_handler(Exception)
async def _unhandled_exc(request, exc: Exception):
    # Any uncaught error (e.g. an upstream WA fetch failing) still returns JSON the UI can
    # read, instead of FastAPI's plain-text "Internal Server Error" page.
    return JSONResponse(status_code=500, content={"error": f"{type(exc).__name__}: {exc}"})


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/meta")
def meta():
    """Selectors + reference data for the UI (events, championships, placing categories)."""
    events = load_events()
    champs = load_championships()
    cats = load_placing_scores().get("_meta", {}).get("categories", [])
    return {
        "events": [
            {"key": k, **{f: e.get(f) for f in
                          ("label", "gender", "best_n", "main_event_min",
                           "window_months", "entry_standard")},
             # The discipline a hypothetical can be entered in: the main event plus similar /
             # indoor events. The UI builds the input-event picker from this.
             "input_events": [{"key": "main", "label": e.get("discipline"), "is_main": True,
                               "indoor": False, "road": False}]
                            + [{"key": a["key"], "label": a["label"], "is_main": False,
                                "indoor": a.get("indoor", False), "road": a.get("road", False)}
                               for a in e.get("alt_events", ())]}
            for k, e in events.items()
        ],
        # Per-championship presentation + qualification info so the UI stays config-driven:
        # not_contested lists events absent from an invitational's programme (the UI shows
        # not_contested_note for them instead of a ranking list).
        "championships": [
            {"key": k, "label": c.get("label"),
             "short_label": c.get("short_label", c.get("label")),
             "scope_label": c.get("scope_label", c.get("label")),
             "rank_label": c.get("rank_label", "Rank"),
             "max_per_country": c.get("max_per_country"),
             "has_qualification": any("quota" in e for e in (c.get("events") or {}).values()),
             "not_contested": ([ek for ek in events if ek not in (c.get("events") or {})]
                               if c.get("contested_events_only") else []),
             "not_contested_note": c.get("not_contested_note"),
             "qualification_footnote": c.get("qualification_footnote"),
             # Explains the greyed rows: ranked athletes WA doesn't list in the field.
             "not_in_field_note": c.get("not_in_field_note")}
            for k, c in champs.items()
        ],
        "categories": cats,
    }


@app.get("/api/rankings")
def rankings(championship: str, event: str, limit: int | None = None):
    """The ranking list for an event (slim rows for the table/picker)."""
    try:
        data = fetch.fetch_championship(championship, event, limit=limit)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Feed-overlaid where WA publishes a 'road to' feed (quota, wildcards, not_in_field),
    # else straight from championships.json.
    ce = feed.event_qualification(championship, event, data["athletes"])
    return {
        "championship": championship,
        "event": event,
        "rank_date": data["rank_date"],
        "quota": ce.get("quota"),
        "defending_champion": ce.get("defending_champion"),
        "auto_invites": ce.get("auto_invites"),
        "not_in_field": ce.get("not_in_field", []),
        "qualification_source": ce.get("qualification_source", "config"),
        "max_per_country": load_championship(championship).get("max_per_country"),
        "athletes": [{f: a.get(f) for f in _RANKING_FIELDS} for a in data["athletes"]],
    }


@app.get("/api/athlete")
def athlete(championship: str, event: str, name: str):
    """One athlete's counting performances (for a detail view)."""
    try:
        data = fetch.fetch_championship(championship, event)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    a = fetch.find_athlete(data, name)
    if a is None:
        raise HTTPException(status_code=404, detail=f"Athlete '{name}' not found in this list.")
    return a


@app.get("/api/required")
def required(championship: str, event: str, name: str, place: int = 1, category: str = "GW"):
    """Reverse solver: the time (finishing `place` in a `category` meet) a ranked athlete would
    need to reach the qualifying cutoff and #1, computed from current standings."""
    try:
        return required_targets(event, name, championship=championship, place=place, category=category)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/search")
def search(name: str, event: str | None = None):
    """Search World Athletics for athletes by name (for the unranked path). Ranks candidates
    whose discipline/gender match `event` first. Returns slim rows incl. the profile slug."""
    name = (name or "").strip()
    if len(name) < 2:
        return {"name": name, "candidates": []}
    try:
        raw = graphql.search_competitors(name)
    except Exception:
        raise HTTPException(status_code=502, detail="World Athletics search is temporarily unavailable.")

    main_name = gender = None
    if event:
        try:
            ev = load_event(event)
            main_name = ev.get("discipline_name") or _main_discipline_name(ev["discipline"])
            gender = ev.get("gender")
        except Exception:
            pass

    def relevance(c: dict) -> int:
        score = 0
        if main_name and main_name in (c.get("disciplines") or ""):
            score += 4
        if gender and (c.get("gender") or "").lower() == gender:
            score += 2
        return score

    ranked = sorted(raw, key=relevance, reverse=True)
    candidates = [{
        "name": f"{(c.get('givenName') or '').strip()} {(c.get('familyName') or '').strip()}".strip(),
        "country": c.get("country"),
        "slug": (c.get("urlSlug") or "").split("/")[-1],
        "disciplines": c.get("disciplines"),
        "gender": c.get("gender"),
    } for c in ranked[:8] if c.get("urlSlug")]
    return {"name": name, "candidates": candidates}


class WhatIfRequest(BaseModel):
    event: str
    athlete: str
    time: str
    category: str = "GW"
    place: int = 2
    championship: str = "road_to_birmingham"
    as_of: str | None = None
    qualify: bool = False
    qualification_window: bool = False
    profile: str | None = None
    sub_event: str | None = None


@app.post("/api/whatif")
def whatif_endpoint(req: WhatIfRequest):
    """Run a what-if scenario. Returns the full structured result dict."""
    try:
        return what_if(
            req.event, req.athlete, req.time,
            category=req.category, place=req.place, championship=req.championship,
            as_of=date.fromisoformat(req.as_of) if req.as_of else None,
            qualify=req.qualify, qualification_window=req.qualification_window,
            profile=req.profile, sub_event=req.sub_event, verbose=False,
        )
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))


# Serve the built front-end (web/dist) at / when present — single-service deploy.
_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="web")
