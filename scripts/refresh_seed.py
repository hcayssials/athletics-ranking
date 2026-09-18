#!/usr/bin/env python3
"""Refresh the committed cache seed (run weekly, then commit + push to redeploy).

Force-fetches the prewarmed championship/event ranking lists from World Athletics into the
live cache, then copies those snapshots into data/cache_seed/ (the site's data source).
Profile_* and api-key caches are intentionally excluded.

Championships that declare a `qualification_feed` (Road to Beijing) also get their WA
'road to' feed refreshed — that snapshot carries the target field, entry standard, window,
the byes WA has recorded and the athletes who have achieved the standard. Their ranking
*list* comes from the source championship (data_source), so only the feed is fetched here.
Archived championships are skipped entirely.

Usage:
    python -m scripts.refresh_seed            # all championships x all events
    python -m scripts.refresh_seed world      # one championship (Beijing shares its list)
"""
from __future__ import annotations

import shutil
import sys

from wa_ranking import feed, fetch
from wa_ranking.config import CACHE_DIR, SEED_DIR, load_championships, load_events


def _refresh_feeds(champs: list[str]) -> int:
    """Refresh the WA qualification feed for every championship/event that declares one."""
    copied = 0
    for champ in champs:
        for event in feed.feed_events(champ):
            key = feed.cache_key(champ, event)
            try:
                snap = feed.fetch_feed(champ, event, force=True)
            except Exception as e:
                print(f"  {key}: skipped ({str(e)[:60]})")
                continue
            src = CACHE_DIR / f"{key}.json"
            if src.exists():
                shutil.copy(src, SEED_DIR / f"{key}.json")
                copied += 1
                print(f"  {key}: field {snap['quota']}, standard {snap['entry_standard']}, "
                      f"{len(snap['auto_invites'])} bye(s), "
                      f"{len(snap['standard_achievers'])} standard achiever(s) -> seed")
    return copied


def main(argv: list[str]) -> int:
    all_champs = [argv[0]] if argv else list(load_championships())
    all_champs = [c for c in all_champs if not load_championships()[c].get("archived")]
    # A data_source championship (e.g. road_to_beijing) shares another championship's
    # list/cache — refreshing the source covers it, so skip to avoid duplicate fetches.
    champs = [c for c in all_champs if not load_championships()[c].get("data_source")]
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    copied = _refresh_feeds(all_champs)
    for champ in champs:
        for event in load_events():
            key = f"{champ}__{event}"
            try:
                data = fetch.fetch_championship(champ, event, force=True)
            except Exception as e:  # e.g. men's steeplechase has no reachable list
                print(f"  {key}: skipped ({str(e)[:60]})")
                continue
            src = CACHE_DIR / f"{key}.json"
            if src.exists():
                shutil.copy(src, SEED_DIR / f"{key}.json")
                copied += 1
                print(f"  {key}: {len(data['athletes'])} athletes -> seed")
    print(f"Done. {copied} snapshot(s) written to {SEED_DIR}.")
    print("Next: git add data/cache_seed && git commit && git push  (triggers redeploy).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
