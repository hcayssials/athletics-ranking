"""Cache + seed-fallback behavior (stale-while-revalidate on cold start)."""
import time

from wa_ranking import cache


def _blob_age(seconds_old: float) -> float:
    return time.time() - seconds_old


def _redirect(monkeypatch, tmp_path):
    """Point the live cache and seed dirs at temp dirs for the duration of a test."""
    live, seed = tmp_path / "cache", tmp_path / "seed"
    live.mkdir()
    seed.mkdir()
    monkeypatch.setattr(cache, "CACHE_DIR", live)
    monkeypatch.setattr(cache, "SEED_DIR", seed)
    return live, seed


def _write_seed(seed_dir, key, data, fetched_at):
    import json
    blob = {"_fetched_at": fetched_at, "_key": key, "data": data}
    with open(seed_dir / f"{key}.json", "w", encoding="utf-8") as f:
        json.dump(blob, f)


def test_read_none_when_no_live_and_no_seed(monkeypatch, tmp_path):
    _redirect(monkeypatch, tmp_path)
    assert cache.read("road_to_birmingham__1500m_men") is None


def test_read_falls_back_to_seed_when_live_missing(monkeypatch, tmp_path):
    _, seed = _redirect(monkeypatch, tmp_path)
    # Seed is intentionally ancient — it must still be served on a cold start.
    _write_seed(seed, "k", {"hello": "seed"}, fetched_at=_blob_age(365 * 24 * 3600))
    assert cache.read("k") == {"hello": "seed"}


def test_fresh_live_wins_over_seed(monkeypatch, tmp_path):
    _, seed = _redirect(monkeypatch, tmp_path)
    _write_seed(seed, "k", {"src": "seed"}, fetched_at=_blob_age(365 * 24 * 3600))
    cache.write("k", {"src": "live"})  # fresh live write
    assert cache.read("k") == {"src": "live"}


def test_stale_live_falls_back_to_seed(monkeypatch, tmp_path):
    live, seed = _redirect(monkeypatch, tmp_path)
    _write_seed(seed, "k", {"src": "seed"}, fetched_at=_blob_age(2 * 24 * 3600))
    # Write a live blob then backdate it past the TTL.
    import json
    stale = {"_fetched_at": _blob_age(30 * 24 * 3600), "_key": "k", "data": {"src": "live-stale"}}
    with open(live / "k.json", "w", encoding="utf-8") as f:
        json.dump(stale, f)
    assert cache.read("k") == {"src": "seed"}
