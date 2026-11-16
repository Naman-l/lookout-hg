"""What an id looks like in this customer's records, read from the build's recipe (`id_shapes` in answers.yaml, kept in build_meta).

The verifier and the plans recognise a part number, a supplier id, a legacy supplier id and a PO line by these patterns; no code names a shape.
With no build (a unit test, a path with no database) a shape matches nothing: nothing is recognised that nobody said was an id."""

from __future__ import annotations

import json
import re
import sqlite3
from functools import lru_cache

NEVER = re.compile(r"(?!x)x")  # matches nothing


@lru_cache(maxsize=16)
def _read(db_path: str) -> dict:
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = con.execute("SELECT value FROM build_meta WHERE key = 'id_shapes'").fetchone()
        finally:
            con.close()
        return json.loads(row[0]) if row and row[0] else {}
    except (sqlite3.Error, ValueError):
        return {}


def shape(db_path, kind: str) -> str | None:
    """The pattern text for one kind of id ('part', 'supplier', 'legacy_supplier', 'po_line'), or None when the recipe names none."""
    return _read(str(db_path)).get(kind) if db_path is not None else None


def shapes(db_path) -> dict[str, str]:
    """Every kind of id the recipe names, with its pattern."""
    return dict(_read(str(db_path))) if db_path is not None else {}


def pattern(db_path, *kinds: str, whole: bool = False) -> re.Pattern:
    """One compiled pattern for any of these kinds of id, as a whole word (or the whole string); nothing matches when the recipe names none of them."""
    parts = [s for s in (shape(db_path, k) for k in kinds) if s]
    if not parts:
        return NEVER
    body = "(?:" + "|".join(parts) + ")"
    return re.compile(rf"^{body}$" if whole else rf"\b{body}\b")
