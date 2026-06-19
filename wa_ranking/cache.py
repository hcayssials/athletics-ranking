"""Tiny timestamped JSON cache so we don't hammer the World Athletics backend."""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import CACHE_DIR, SEED_DIR

DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days — World Athletics updates rankings ~weekly


def _path(key: str) -> Path:
    safe = key.replace("/", "_")
    return CACHE_DIR / f"{safe}.json"


def _seed_path(key: str) -> Path:
    return SEED_DIR / f"{key.replace('/', '_')}.json"


def _read_blob(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def read(key: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> dict | None:
    """Return cached payload if present and fresh, else None.

    On a cold start the live cache is empty (it's ephemeral and gitignored), so we fall back
    to a committed seed snapshot baked into the image — served regardless of its age, since
    the background prewarm refreshes the live cache shortly after boot (stale-while-revalidate).
    """
    blob = _read_blob(_path(key))
    if blob is not None and not (
        ttl_seconds is not None and time.time() - blob.get("_fetched_at", 0) > ttl_seconds
    ):
        return blob["data"]
    # Live cache missing or stale — fall back to the committed seed if we have one.
    seed = _read_blob(_seed_path(key))
    return seed["data"] if seed is not None else None


def write(key: str, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    blob = {"_fetched_at": time.time(), "_key": key, "data": data}
    with open(_path(key), "w", encoding="utf-8") as f:
        json.dump(blob, f, indent=1, ensure_ascii=False)


def age_seconds(key: str) -> float | None:
    path = _path(key)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        blob = json.load(f)
    return time.time() - blob.get("_fetched_at", 0)
