"""The company the workspace is for, read from the data's build (the recipe's `company`), never typed into a prompt.

`names(db_path)` returns (full name, short name): 'the company' and 'the company' when the recipe says so. With no database, no build or no company
in it, `LOOKOUT_COMPANY` is used, and failing that the prompts say 'the company'."""

from __future__ import annotations

import os
import sqlite3
from functools import lru_cache

GENERIC = "the company"


@lru_cache(maxsize=16)
def _read(db_path: str) -> str:
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = con.execute("SELECT value FROM build_meta WHERE key = 'company'").fetchone()
        finally:
            con.close()
        return (row[0] or "").strip() if row else ""
    except sqlite3.Error:
        return ""


def names(db_path=None) -> tuple[str, str]:
    """With no database path (None) there is no build to ask: the fallback, the same one a path with no build gives."""
    full = (_read(str(db_path)) if db_path is not None else "") or os.environ.get("LOOKOUT_COMPANY", "").strip() or GENERIC
    short = _meta(str(db_path), "company_short") if db_path is not None else ""
    return full, (GENERIC if full == GENERIC else short or full.split()[0])


def fill(text: str, db_path=None) -> str:
    """Put the company's name into prompt text written with {company} (full) and {company_short}."""
    full, short = names(db_path)
    return text.replace("{company_short}", short).replace("{company}", full)


@lru_cache(maxsize=16)
def _meta(db_path: str, key: str) -> str:
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = con.execute("SELECT value FROM build_meta WHERE key = ?", (key,)).fetchone()
        finally:
            con.close()
        return (row[0] or "").strip() if row else ""
    except sqlite3.Error:
        return ""


def base_currency(db_path=None) -> str:
    """The currency every amount is counted in (the recipe's `base_currency`), else INR's absence says nothing: 'USD' is never assumed silently."""
    return (_meta(str(db_path), "base_currency") if db_path is not None else "") or os.environ.get("LOOKOUT_BASE_CURRENCY", "") or "INR"
