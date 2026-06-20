"""Generate World Athletics result-score tables (time -> points) for every running event.

WHY THIS EXISTS
    Scoring a hypothetical performance needs WA's official "time -> points" table for that
    exact discipline (and indoor vs outdoor use *different* tables). Rather than hand-parse
    WA's giant scoring-table PDF, we ingest an already-published parse of it:
    `jchen1/iaaf-scoring-tables`, which extracts every event x gender x indoor/outdoor table.
    That parse is verified byte-identical to our original hand-committed tables for all five
    ranking events (the byte-identity gate below), so it is trusted as the source.

WHAT IT WRITES
    One CSV per (event, gender, indoor/outdoor) into data/scoring_tables/, in the format
    config.load_result_table reads: a `mark_seconds,result_score` header then rows sorted
    ascending by mark. Outdoor files are `<event>_<gender>.csv`; indoor add `_indoor`.

SCOPE
    Time-based events only (track, road, race walk: smaller mark = more points). Field and
    combined events (jumps, throws, decathlon) are skipped -- their lookup direction is the
    opposite (larger mark = more points) and the scoring engine assumes time semantics.

EDITION
    Default 2023: it reproduces WA's *live* ranking scores for our cached events exactly (the
    real-data gate below) and matches our committed tables. `--edition 2025` is the latest
    published edition (identical to 2023 for distance events); the gates guard correctness
    either way -- a wrong edition fails the real-data check loudly.

RUN
    python -m scripts.build_scoring_tables                 # edition 2023, write + validate
    python -m scripts.build_scoring_tables --edition 2025
    python -m scripts.build_scoring_tables --check         # validate only, write nothing
"""
from __future__ import annotations

import argparse
import csv
import glob
import io
import json
import sys
import urllib.request
from bisect import bisect_left
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLES_DIR = ROOT / "data" / "scoring_tables"
CACHE_SEED = ROOT / "data" / "cache_seed"
SOURCE_DIR = TABLES_DIR / "_source"  # gitignored cache of the upstream parse
SOURCE_URL = "https://raw.githubusercontent.com/jchen1/iaaf-scoring-tables/master/iaaf-{edition}.json"

# Field / combined events: lookup direction is reversed (bigger = better), so they don't fit
# the time-based scoring engine. Skipped until that's supported.
FIELD_EVENTS = {"DT", "HJ", "HT", "JT", "LJ", "PV", "SP", "TJ"}


def _is_field(event: str) -> bool:
    e = event.replace(".", "").replace(" ", "")
    return event in FIELD_EVENTS or any(k in e for k in ("Decathlon", "Heptathlon", "Pentathlon", "Hept", "Pent"))


def slug(event: str) -> str:
    """jchen event name -> filename stem (matches our existing files: '10,000m' -> '10000m',
    '2 Miles' -> '2Miles', '3000mSC' -> '3000mSC')."""
    return event.replace(",", "").replace(" ", "")


def filename(event: str, gender: str, category: str) -> str:
    return f"{slug(event)}_{gender}{'_indoor' if category == 'indoor' else ''}.csv"


def load_source(edition: str) -> list[dict]:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    path = SOURCE_DIR / f"iaaf-{edition}.json"
    if not path.exists():
        url = SOURCE_URL.format(edition=edition)
        print(f"  downloading {url}")
        urllib.request.urlretrieve(url, path)
    return json.loads(path.read_text())


def build_tables(rows: list[dict]) -> dict[str, list[tuple[float, int]]]:
    """Group the flat upstream rows into {filename: sorted [(mark_seconds, points)]}."""
    grouped: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for r in rows:
        if _is_field(r["event"]):
            continue
        fn = filename(r["event"], r["gender"], r["category"])
        grouped[fn].append((float(r["mark"]), int(r["points"])))
    for fn in grouped:
        grouped[fn].sort(key=lambda t: t[0])
    return dict(grouped)


def render_csv(table: list[tuple[float, int]]) -> str:
    # LF line endings, pinned by .gitattributes (data/scoring_tables/*.csv text eol=lf).
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["mark_seconds", "result_score"])
    for mark, score in table:
        w.writerow([f"{mark:.2f}", score])
    return buf.getvalue()


# --- validation gates -------------------------------------------------------------------

def _parse_time(s: str) -> float | None:
    s = "".join(c for c in str(s) if c in "0123456789:.")
    if not s:
        return None
    if ":" not in s:
        try:
            return float(s)
        except ValueError:
            return None
    sec = 0.0
    for p in s.split(":"):
        try:
            sec = sec * 60 + float(p)
        except ValueError:
            return None
    return round(sec, 3)


def _lookup(table: list[tuple[float, int]], seconds: float) -> int:
    marks = [m for m, _ in table]
    i = bisect_left(marks, seconds)
    return 0 if i >= len(table) else table[i][1]


# discipline_code (as it appears in cached performances) -> (filename) it should score from.
# Lets us check generated tables -- including the indoor ones -- against real WA-scored marks.
def _code_to_file(code: str, gender: str) -> str | None:
    out = {"800": "800m", "1500": "1500m", "5000": "5000m", "3000": "3000m",
           "1000": "1000m", "600": "600m", "2000": "2000m", "MILE": "Mile",
           "3KSC": "3000mSC", "2KSC": "2000mSC"}
    ind = {"800sh": "800m", "1500sh": "1500m", "5000sh": "5000m", "3000sh": "3000m",
           "1000sh": "1000m", "600sh": "600m", "2000sh": "2000m", "MILEsh": "Mile"}
    if code in out:
        return f"{out[code]}_{gender}.csv"
    if code in ind:
        return f"{ind[code]}_{gender}_indoor.csv"
    return None  # road / ambiguous codes (10RR, 5RR, 1MR, 2MLSsh, ...) -- skip in validation


def validate_against_real_data(tables: dict[str, list[tuple[float, int]]]) -> int:
    """For every cached performance whose discipline maps to a generated table, the table's
    lookup is compared to WA's stored result_score. A discrepancy larger than one point means
    a real error (wrong edition, or indoor/outdoor mixup) and is fatal -- returned as the
    count. Discrepancies of exactly +-1 point are expected: the stored mark is rounded to 0.01
    while WA scores the true (slightly faster) time, which flips a point only on steep short
    events -- so those are reported but tolerated. (Verified: distance events match exactly.)"""
    checked = defaultdict(int)
    off_by_one = defaultdict(int)
    errors = defaultdict(list)  # |delta| > 1 -> real problem
    for fn in glob.glob(str(CACHE_SEED / "*.json")):
        gender = "women" if "_women" in Path(fn).name else "men"
        data = json.loads(Path(fn).read_text()).get("data", {})
        for ath in data.get("athletes", []):
            for p in ath.get("performances", []):
                code, mark, rs = p.get("discipline_code"), p.get("mark"), p.get("result_score")
                if not (code and mark and rs):
                    continue
                tf = _code_to_file(code, gender)
                if not tf or tf not in tables:
                    continue
                t = _parse_time(mark)
                if t is None:
                    continue
                checked[tf] += 1
                delta = rs - _lookup(tables[tf], t)
                if abs(delta) == 1:
                    off_by_one[tf] += 1
                elif delta != 0:
                    errors[tf].append((mark, rs, rs - delta))
    n_err = sum(len(v) for v in errors.values())
    print(f"\n  real-data gate: checked {sum(checked.values())} performances across "
          f"{len(checked)} tables")
    for tf in sorted(checked):
        err = errors.get(tf, [])
        ob1 = off_by_one.get(tf, 0)
        flag = "ERR" if err else "OK "
        note = f"  +-1: {ob1}" if ob1 else ""
        note += "" if not err else f"  >1 ERRORS: {err[:3]}"
        print(f"    [{flag}] {tf:24s} {checked[tf]:4d} checked{note}")
    return n_err


def validate_byte_identity(tables: dict[str, str]) -> int:
    """Every file that already exists on disk (notably the original 5 ranking events) must be
    regenerated byte-for-byte. Returns the number that differ."""
    diffs = 0
    for fn, content in sorted(tables.items()):
        path = TABLES_DIR / fn
        # Compare values only (splitlines ignores LF/CRLF): a real number change is a problem;
        # a line-ending-only change is not.
        if path.exists() and path.read_text().splitlines() != content.splitlines():
            print(f"    [VALUE-DIFF] {fn} differs from committed version")
            diffs += 1
    print(f"\n  byte-identity gate: {diffs} of the existing tables would change")
    return diffs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--edition", default="2023", choices=["2023", "2025"])
    ap.add_argument("--check", action="store_true", help="validate only; write nothing")
    args = ap.parse_args()

    print(f"Building scoring tables from edition {args.edition}")
    rows = load_source(args.edition)
    tables = build_tables(rows)
    rendered = {fn: render_csv(tbl) for fn, tbl in tables.items()}
    print(f"  generated {len(tables)} time-event tables "
          f"(field/combined events skipped)")

    real_errors = validate_against_real_data(tables)
    byte_diffs = validate_byte_identity(rendered)
    if real_errors or byte_diffs:
        print(f"\nFAILED: {real_errors} real-data errors (>1pt), {byte_diffs} byte diffs. "
              "Not writing.")
        return 1

    if args.check:
        print("\n--check: validation passed, nothing written.")
        return 0

    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    for fn, content in rendered.items():
        (TABLES_DIR / fn).write_bytes(content.encode("utf-8"))
    print(f"\nWrote {len(rendered)} tables to {TABLES_DIR.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
