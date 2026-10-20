"""The load gate's checks, applied to a steward's normalised table. Code only: the steward never grades its own work.

  columns        exactly the expected columns of the known export, in order
  rows           one output row per input row (nothing dropped or invented without a recorded reason)
  values         per column, as many non-blank values out as were mapped in (no raw value lost, none invented)
  shapes         every value shape in the output is a shape the known export shows (dates, ids, numbers read the same way)
"""

from __future__ import annotations

import re
from collections import Counter

import pandas as pd

from .drift import shapes


def gate(source: pd.DataFrame, out: pd.DataFrame, expected: pd.DataFrame, mapping: dict[str, str] | None = None) -> list[dict]:
    """Checks as [{name, passed, detail}]. `mapping` is {output column: source column} when known; otherwise values are checked by count only."""
    checks = []
    want = list(expected.columns)
    ok = list(out.columns) == want
    checks.append({"name": "columns", "passed": ok, "detail": "the expected columns, in order" if ok else f"expected {want}, got {list(out.columns)}"})
    ok = len(out) == len(source)
    checks.append({"name": "rows", "passed": ok, "detail": f"{len(source)} rows in, {len(out)} out"})
    lost = []
    available = Counter(int((source[c].astype(str) != "").sum()) for c in source.columns)  # each source column can feed one output column
    for c in want:
        if c not in out.columns:
            continue
        got = int((out[c].astype(str) != "").sum())
        src_col = (mapping or {}).get(c)
        if src_col and src_col in source.columns:
            had = int((source[src_col].astype(str) != "").sum())
            if got != had:
                lost.append(f"{c}: {had} values in, {got} out")
        elif available[got] > 0:  # without a stated mapping: some still-unused source column must have exactly this many values
            available[got] -= 1
        else:
            lost.append(f"{c}: {got} values, which no unused source column has")
    checks.append({"name": "values", "passed": not lost, "detail": "no value lost or invented" if not lost else "; ".join(lost)})
    odd = []
    for c in want:
        if c in out.columns:
            new = shapes(out[c].astype(str)) - shapes(expected[c])
            if new:
                odd.append(f"{c}: {sorted(new)[:3]}")
    checks.append({"name": "shapes", "passed": not odd, "detail": "every value reads like the known export" if not odd else "new shapes: " + "; ".join(odd)})
    odd_dates = []
    for c in want:
        order = slash_date_order(expected[c]) if c in expected.columns else None
        if order and c in out.columns:
            bad = [v for v in out[c].astype(str) if _SLASH.fullmatch(v) and not _fits(v, order)]
            if bad:
                odd_dates.append(f"{c}: {len(bad)} slash dates break the known export's {order} order (e.g. {bad[0]})")
    checks.append({"name": "dates", "passed": not odd_dates, "detail": "slash dates keep the known export's day and month order" if not odd_dates else "; ".join(odd_dates)})
    return checks


_SLASH = re.compile(r"\d{2}/\d{2}/\d{4}")


def slash_date_order(expected_col: pd.Series) -> str | None:
    """'MM/DD/YYYY' or 'DD/MM/YYYY' when the known export's slash dates settle it: a value like 01/22/2025 can only be month first, 22/01/2025
    only day first, and 01/02/2025 is silent. The order is returned when one reading is contradicted by (almost) none of the telling values."""
    month_first = day_first = 0
    for v in expected_col.astype(str):
        if _SLASH.fullmatch(v):
            first, second = int(v[:2]), int(v[3:5])
            month_first += second > 12
            day_first += first > 12
    if month_first and day_first <= 0.05 * month_first:
        return "MM/DD/YYYY"
    if day_first and month_first <= 0.05 * day_first:
        return "DD/MM/YYYY"
    return None


def _fits(value: str, order: str) -> bool:
    first, second = int(value[:2]), int(value[3:5])
    return second <= 31 and first <= 12 if order == "MM/DD/YYYY" else first <= 31 and second <= 12
