"""Loading of data files: events, championships, placing scores, decay, scoring tables."""
from __future__ import annotations

import csv
import json
from functools import lru_cache
from pathlib import Path

# data/ lives next to the package directory (project root/data).
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CACHE_DIR = DATA_DIR / "cache"


def _load_json(name: str) -> dict:
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def _strip_meta(d: dict) -> dict:
    """Drop documentation keys (those starting with '_', e.g. '_meta')."""
    return {k: v for k, v in d.items() if not k.startswith("_")}


@lru_cache(maxsize=None)
def load_events() -> dict:
    return _strip_meta(_load_json("events.json"))


@lru_cache(maxsize=None)
def load_championships() -> dict:
    return _strip_meta(_load_json("championships.json"))


def championship_event_config(championship: str, event: str) -> dict:
    """Per-event qualification config (quota, defending champion, window override) for a
    championship, or {} if the championship doesn't define qualification for that event."""
    champ = load_championship(championship)
    return champ.get("events", {}).get(event, {})


@lru_cache(maxsize=None)
def load_placing_scores() -> dict:
    return _load_json("placing_scores.json")


@lru_cache(maxsize=None)
def load_decay() -> dict:
    """Return {month_age:int -> deduction:int}."""
    raw = _load_json("decay.json")["deductions_by_month_age"]
    return {int(k): int(v) for k, v in raw.items()}


def load_event(event: str) -> dict:
    events = load_events()
    if event not in events:
        raise KeyError(f"Unknown event '{event}'. Known: {sorted(events)}")
    return events[event]


def load_championship(championship: str) -> dict:
    champs = load_championships()
    if championship not in champs:
        raise KeyError(
            f"Unknown championship '{championship}'. Known: {sorted(champs)}"
        )
    return champs[championship]


@lru_cache(maxsize=None)
def load_result_table(rel_path: str) -> list[tuple[float, int]]:
    """Load a result-score table as a sorted list of (mark_seconds, result_score).

    Sorted ascending by mark_seconds (fastest first).
    """
    table: list[tuple[float, int]] = []
    with open(DATA_DIR / rel_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            table.append((float(row["mark_seconds"]), int(row["result_score"])))
    table.sort(key=lambda r: r[0])
    return table
