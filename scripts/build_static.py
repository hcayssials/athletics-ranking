#!/usr/bin/env python3
"""Build the static site data bundle (GitHub Pages deploy) + golden parity vectors.

Emits into web/public/data/ (gitignored; Vite copies public/ into dist/):

  meta.json                    — exactly the /api/meta payload (App.jsx reads it unchanged)
  engine.json                  — config the browser engine needs: events, championships,
                                 placing scores, decay table, WA GraphQL endpoint + key.
                                 Per-event qualification is baked in *resolved* (quota,
                                 wildcards and not_in_field from WA's 'road to' feed where
                                 one exists) so the browser engine reads the same numbers
                                 the Python engine used for the parity vectors
  rankings/{champ}__{event}.json — exactly the /api/rankings payload (or {"error": ...}
                                 for lists WA can't serve, e.g. men's steeplechase)
  lists/{champ}__{event}.json  — the full fetch_championship data (athletes incl.
                                 performances) for source championships only; a
                                 data_source championship (road_to_ultimate) reads its
                                 source's file, mirroring fetch.fetch_championship
  tables/{stem}.json           — result-score tables referenced by events.json, as
                                 [[mark_seconds, result_score], ...] ascending

and golden vectors to web/parity-vectors.json (gitignored): Python what_if /
required_targets outputs over a grid of real athletes × times × options. The JS engine
must reproduce them exactly (node web/src/engine/parity.test.mjs) before any deploy.

Reads through the normal cache (live cache → committed seed), so it needs no network
unless the WA GraphQL key must be (re)validated. Run scripts.refresh_seed first to build
from fresh data.

Usage:
    python -m scripts.build_static             # bundle + vectors
    python -m scripts.build_static --no-vectors
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from wa_ranking import feed, fetch, graphql
from wa_ranking.api import meta as api_meta, rankings as api_rankings
from wa_ranking.config import (DATA_DIR, load_championships, load_events,
                               load_placing_scores, load_result_table, _load_json)
from wa_ranking.scoring import format_seconds, parse_time
from wa_ranking.whatif import required_targets, what_if

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "public" / "data"
VECTORS_PATH = ROOT / "web" / "parity-vectors.json"


def _dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def _table_stem(rel_path: str) -> str:
    return Path(rel_path).stem


def _referenced_tables() -> dict[str, str]:
    """{stem: rel_path} for every result table events.json references (main + alts)."""
    tables: dict[str, str] = {}
    for ev in load_events().values():
        for rel in [ev["result_table"]] + [a["result_table"] for a in ev.get("alt_events", ())]:
            tables[_table_stem(rel)] = rel
    return tables


def _graphql_config() -> dict:
    """Endpoint + a working API key for direct browser calls. The key is scraped from WA's
    own public JS (not a secret); a weekly rebuild picks up rotations."""
    try:
        key = graphql.get_api_key()
    except Exception as e:
        print(f"  ! GraphQL key unavailable ({e}); baking the seed key — search may 401.")
        key = graphql._SEED_KEY
    return {"endpoint": graphql.ENDPOINT, "key": key}


def _resolved_championships() -> dict:
    """championships.json with each event's qualification resolved through feed.py.

    The browser engine has no cache to read a feed snapshot from, so the resolution happens
    here, once, and both engines then work from identical numbers.
    """
    champs = json.loads(json.dumps(load_championships()))  # deep copy; JSON in, JSON out
    for champ, cfg in champs.items():
        for event in feed.feed_events(champ):
            if event not in cfg.get("events", {}):
                continue
            try:
                athletes = fetch.fetch_championship(champ, event)["athletes"]
            except Exception as e:
                print(f"  ! {champ}/{event}: keeping the JSON fallback ({str(e)[:50]})")
                continue
            cfg["events"][event] = feed.event_qualification(champ, event, athletes)
    return champs


def build_bundle() -> None:
    events, champs = load_events(), _resolved_championships()

    _dump(OUT / "meta.json", api_meta())
    _dump(OUT / "engine.json", {
        "generated": date.today().isoformat(),
        "events": events,
        "championships": champs,
        "placing_scores": load_placing_scores(),
        "decay": _load_json("decay.json")["deductions_by_month_age"],
        "graphql": _graphql_config(),
    })

    for stem, rel in sorted(_referenced_tables().items()):
        _dump(OUT / "tables" / f"{stem}.json", load_result_table(rel))

    for champ, cfg in champs.items():
        source = cfg.get("data_source")
        for event in events:
            key = f"{champ}__{event}"
            try:
                _dump(OUT / "rankings" / f"{key}.json", api_rankings(champ, event))
            except Exception as e:
                detail = getattr(e, "detail", None) or str(e)
                _dump(OUT / "rankings" / f"{key}.json", {"error": detail})
                print(f"  rankings/{key}: error file ({detail[:60]})")
                continue
            if not source:  # full data only for source championships; others share it
                _dump(OUT / "lists" / f"{key}.json", fetch.fetch_championship(champ, event))
    n = sum(1 for _ in OUT.rglob("*.json"))
    size = sum(p.stat().st_size for p in OUT.rglob("*.json"))
    print(f"Bundle: {n} files, {size/1e6:.1f} MB -> {OUT}")


def _sample_athletes(athletes: list[dict]) -> list[dict]:
    """First, middle, last ranked athletes — plus one from a country already holding 3+
    ranked ahead if present (exercises the country-cap path)."""
    ranked = [a for a in athletes if a.get("ranking_score") is not None]
    if not ranked:
        return []
    picks = {0, len(ranked) // 2, len(ranked) - 1}
    counts: dict[str, int] = {}
    for i, a in enumerate(ranked):
        c = a.get("country")
        counts[c] = counts.get(c, 0) + 1
        if counts[c] == 4:
            picks.add(i)
            break
    return [ranked[i] for i in sorted(picks)]


def _times_for(athlete: dict, event_cfg: dict) -> list[str]:
    """A fast, a typical and a slow hypothetical time for this athlete's event."""
    times = []
    if event_cfg.get("entry_standard"):
        times.append(event_cfg["entry_standard"])
    best = None
    for p in athlete.get("performances", []):
        try:
            s = parse_time(p["mark"])
        except (ValueError, TypeError):
            continue
        best = s if best is None else min(best, s)
    if best:
        times.append(format_seconds(round(best * 0.99, 2)))   # ~1% improvement
        times.append(format_seconds(round(best * 1.06, 2)))   # an off day
    return times or ["4:00.00"]


def build_vectors() -> None:
    as_of = date.today()
    events, champs = load_events(), load_championships()
    vectors = []

    def add(kind: str, inputs: dict) -> None:
        fn = required_targets if kind == "required" else what_if
        try:
            if kind == "required":
                out = fn(inputs["event"], inputs["athlete"], championship=inputs["championship"],
                         place=inputs["place"], category=inputs["category"])
            else:
                out = fn(inputs["event"], inputs["athlete"], inputs["time"],
                         category=inputs.get("category", "GW"), place=inputs.get("place", 2),
                         championship=inputs["championship"],
                         as_of=date.fromisoformat(inputs["as_of"]),
                         qualify=inputs.get("qualify", False),
                         qualification_window=inputs.get("qualification_window", False),
                         sub_event=inputs.get("sub_event"), verbose=False)
            vectors.append({"kind": kind, "inputs": inputs, "expect": out})
        except (ValueError, RuntimeError) as e:
            vectors.append({"kind": kind, "inputs": inputs, "expect_error": str(e)})

    for champ, cfg in champs.items():
        has_quota = bool(cfg.get("events"))
        for event, ev_cfg in events.items():
            try:
                data = fetch.fetch_championship(champ, event)
            except Exception:
                continue
            quota_here = "quota" in cfg.get("events", {}).get(event, {})
            for i, ath in enumerate(_sample_athletes(data["athletes"])):
                for t in _times_for(ath, ev_cfg):
                    add("whatif", {"event": event, "championship": champ,
                                   "athlete": ath["name"], "time": t,
                                   "as_of": as_of.isoformat(),
                                   "qualify": quota_here})
                if i == 0:
                    # Extremes of the placing table + the reverse solver.
                    t = _times_for(ath, ev_cfg)[0]
                    add("whatif", {"event": event, "championship": champ,
                                   "athlete": ath["name"], "time": t, "category": "OW",
                                   "place": 1, "as_of": as_of.isoformat(),
                                   "qualify": quota_here})
                    add("whatif", {"event": event, "championship": champ,
                                   "athlete": ath["name"], "time": t, "category": "F",
                                   "place": 8, "as_of": as_of.isoformat()})
                    if quota_here and cfg.get("qualification_window"):
                        add("whatif", {"event": event, "championship": champ,
                                       "athlete": ath["name"], "time": t,
                                       "as_of": as_of.isoformat(), "qualify": True,
                                       "qualification_window": True})
                    add("required", {"event": event, "championship": champ,
                                     "athlete": ath["name"], "place": 1, "category": "GW"})
                    add("required", {"event": event, "championship": champ,
                                     "athlete": ath["name"], "place": 3, "category": "B"})
                    # A ranked athlete WA doesn't list in the field, so the gate covers the
                    # not_in_field path (their place passes down the list).
                    if quota_here:
                        absent = (feed.event_qualification(champ, event, data["athletes"])
                                  .get("not_in_field") or [])
                        out_of_field = next((x for x in data["athletes"]
                                             if absent and x["name"] == absent[0]["name"]), None)
                        if out_of_field:
                            add("whatif", {"event": event, "championship": champ,
                                           "athlete": out_of_field["name"],
                                           "time": _times_for(out_of_field, ev_cfg)[0],
                                           "as_of": as_of.isoformat(), "qualify": True})
                    # Every similar/indoor input event once.
                    for alt in ev_cfg.get("alt_events", ()):
                        add("whatif", {"event": event, "championship": champ,
                                       "athlete": ath["name"],
                                       "time": _alt_time(alt, ev_cfg),
                                       "sub_event": alt["key"],
                                       "as_of": as_of.isoformat(),
                                       "qualify": quota_here})
        if not has_quota and champ != "world":
            continue

    _dump(VECTORS_PATH, {"as_of": as_of.isoformat(), "count": len(vectors), "vectors": vectors})
    errs = sum(1 for v in vectors if "expect_error" in v)
    print(f"Vectors: {len(vectors)} ({errs} error-cases) -> {VECTORS_PATH}")


def _alt_time(alt: dict, ev_cfg: dict) -> str:
    """A plausible time for a similar event: scale the main entry standard by table range."""
    tab = load_result_table(alt["result_table"])
    mid = tab[len(tab) // 4][0]          # a strong-but-realistic mark from the table itself
    return format_seconds(mid)


def main(argv: list[str]) -> int:
    build_bundle()
    if "--no-vectors" not in argv:
        build_vectors()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
