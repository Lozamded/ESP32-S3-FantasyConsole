"""Minimal CSV-backed UI string table.

`strings.csv` (columns: key, es, en) is the single source of truth for every
label/button/message the GUI shows. The app just reads the `en` column at
startup (LOCALE below); the `es` column is kept for reference/future use, not
wired to a runtime switcher.
"""

from __future__ import annotations

import csv
from pathlib import Path

LOCALE = "en"

_STRINGS_CSV = Path(__file__).resolve().parent / "strings.csv"


def _load_strings() -> dict[str, dict[str, str]]:
    if not _STRINGS_CSV.is_file():
        return {}
    with _STRINGS_CSV.open(encoding="utf-8", newline="") as f:
        return {row["key"]: row for row in csv.DictReader(f) if row.get("key")}


_STRINGS = _load_strings()


def tr(key: str, **kwargs: object) -> str:
    """Look up `key` in the active locale; falls back to the raw key if missing."""
    row = _STRINGS.get(key)
    text = row.get(LOCALE) if row else None
    if not text:
        text = key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text
