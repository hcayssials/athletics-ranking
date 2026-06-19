"""Thin CLI over the what-if engine and the data layer.

Examples:
    python -m wa_ranking.cli whatif --event 1500m_men --athlete "Nuguse" --time 3:28.50 --place 1
    python -m wa_ranking.cli whatif --event 5000m_women --athlete "..." --time 14:20 --qualify
    python -m wa_ranking.cli fetch --event 800m_women --force
    python -m wa_ranking.cli list --event 1500m_men
    python -m wa_ranking.cli events
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from . import fetch
from .config import load_championships, load_events
from .whatif import what_if

DEFAULT_CHAMP = "road_to_birmingham"
DEFAULT_EVENT = "1500m_men"


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--event", default=DEFAULT_EVENT,
                   help=f"Event key, e.g. 800m_women (default: {DEFAULT_EVENT})")
    p.add_argument("--championship", default=DEFAULT_CHAMP,
                   help=f"world | road_to_birmingham (default: {DEFAULT_CHAMP})")


def cmd_whatif(args) -> int:
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    result = what_if(
        args.event, args.athlete, args.time,
        category=args.category, place=args.place, championship=args.championship,
        as_of=as_of, indoor=args.indoor,
        qualification_window=args.qual_window, qualify=args.qualify,
        profile=args.profile,
        force_refresh=args.force, verbose=not args.json,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_fetch(args) -> int:
    data = fetch.fetch_championship(args.championship, args.event, force=args.force, limit=args.limit)
    print(f"Cached {len(data['athletes'])} athletes for '{args.championship}' / '{args.event}' "
          f"(rank date {data['rank_date']}, fetched {data['fetched']}).")
    return 0


def cmd_list(args) -> int:
    data = fetch.fetch_championship(args.championship, args.event, force=args.force, limit=args.limit)
    rows = data["athletes"][: args.limit] if args.limit else data["athletes"]
    for a in rows:
        print(f"  {str(a['rank']):>3}. {a['name']:<28} {a['country']:<4} "
              f"score {a['ranking_score']}  ({len(a['performances'])} perfs)")
    return 0


def cmd_champs(args) -> int:
    for key, c in load_championships().items():
        print(f"  {key}  ->  {c['label']}")
    return 0


def cmd_events(args) -> int:
    for key, e in load_events().items():
        print(f"  {key:<14} {e['label']:<16} N={e['best_n']} "
              f"(min {e['main_event_min']} main), {e['window_months']}mo window")
    return 0


def cmd_refresh(args) -> int:
    """Re-fetch every (championship, event) so the cache holds the latest weekly rankings.
    Intended for a weekly scheduled run (World Athletics updates ~Tuesdays)."""
    champs = [args.championship] if args.championship else list(load_championships())
    for champ in champs:
        for event in load_events():
            try:
                data = fetch.fetch_championship(champ, event, force=True)
                print(f"  {champ}/{event}: {len(data['athletes'])} athletes "
                      f"(rank date {data['rank_date']})")
            except Exception as e:  # e.g. men's steeplechase has no reachable list
                print(f"  {champ}/{event}: skipped ({str(e)[:60]}...)")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="wa_ranking", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("whatif", help="Run a what-if scenario")
    _add_common(p)
    p.add_argument("--athlete", required=True)
    p.add_argument("--time", required=True, help="e.g. 3:29.50")
    p.add_argument("--category", default="GW", help="Meet category code (default GW)")
    p.add_argument("--place", type=int, default=2, help="Projected finishing place (default 2)")
    p.add_argument("--as-of", dest="as_of", default=None, help="YYYY-MM-DD (default today)")
    p.add_argument("--indoor", action="store_true")
    p.add_argument("--qual-window", dest="qual_window", action="store_true",
                   help="Use the championship's fixed qualification window instead of the "
                        "rolling 12-month window")
    p.add_argument("--qualify", action="store_true",
                   help="Resolve championship qualification: quota + 3-per-country cap + "
                        "defending-champion bye (general ranking question if omitted)")
    p.add_argument("--profile", default=None,
                   help="WA profile slug for an UNRANKED athlete not on the list "
                        "(e.g. jake-heyward-14597392, from their worldathletics.org URL)")
    p.add_argument("--force", action="store_true", help="Bypass cache, re-fetch")
    p.add_argument("--json", action="store_true", help="Emit JSON instead of the report")
    p.set_defaults(func=cmd_whatif)

    p = sub.add_parser("fetch", help="Fetch + cache a championship")
    _add_common(p)
    p.add_argument("--force", action="store_true")
    p.add_argument("--limit", type=int, default=None, help="Only first N athletes")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("list", help="List the cached ranking")
    _add_common(p)
    p.add_argument("--force", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("champs", help="List known championships")
    p.set_defaults(func=cmd_champs)

    p = sub.add_parser("events", help="List known events")
    p.set_defaults(func=cmd_events)

    p = sub.add_parser("refresh", help="Re-fetch all events for the weekly ranking update")
    p.add_argument("--championship", default=None,
                   help="Limit to one championship (default: all)")
    p.set_defaults(func=cmd_refresh)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
