"""Small shared parsers for World Athletics field formats (used by fetch.py and profile.py)."""
from __future__ import annotations

import re
from datetime import datetime


def parse_wa_date(raw: str) -> str | None:
    """'07 JUN 2026' -> '2026-06-07' (ISO). Returns None if unparseable."""
    raw = (raw or "").strip()
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_place(raw) -> int | None:
    """'P6' / '6' / 6 -> 6. Returns None if there's no number."""
    m = re.search(r"\d+", str(raw or ""))
    return int(m.group()) if m else None
