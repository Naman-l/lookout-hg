"""Drift: how an incoming CSV differs from the export the standard recipe was built on. All code, no model.

A known export has an expected set of columns and, per column, the value shapes it shows (dates as 99/99/9999, part numbers
as AA99999). The report lists what is missing, what is new, which new column probably is which missing one (by value shape
and name, as a hint only), and which columns show a new format. The steward decides; this only measures."""

from __future__ import annotations

import difflib
import re
from pathlib import Path

import pandas as pd

from ..profile import shape

ROOT = Path(__file__).resolve().parents[5]
DATA_DIR = ROOT / "data"
KNOWN = {"purchase_orders": "purchase_orders.csv", "parts": "parts.csv", "bom": "bom.csv", "suppliers": "suppliers.csv", "demand_forecast": "demand_forecast.csv"}


def _tokens(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def known_export(table: str, data_dir: Path = DATA_DIR) -> pd.DataFrame:
    return pd.read_csv(data_dir / KNOWN[table], dtype=str, keep_default_na=False)


def shapes(values: pd.Series, limit: int = 400) -> set[str]:
    return {shape(v) for v in values.head(limit) if v != ""}


def _similarity(found: pd.Series, expected: pd.Series, found_name: str, expected_name: str) -> float:
    a, b = shapes(found), shapes(expected)
    by_shape = len(a & b) / len(a | b) if a | b else 0.0
    by_name = difflib.SequenceMatcher(None, _tokens(found_name), _tokens(expected_name)).ratio()
    return round(0.6 * by_shape + 0.4 * by_name, 3)


def fit(df: pd.DataFrame, exp: pd.DataFrame) -> float:
    """How well a file maps onto one known export: each found column may stand for at most ONE expected column (the best pairs first), and the score is the pairs' similarity over
    the larger of the two column counts, so a file is not credited for stretching one of its columns over several expected ones, nor for having many extra columns."""
    pairs = sorted(((_similarity(df[f], exp[c], f, c), f, c) for f in df.columns for c in exp.columns), reverse=True)
    used_f, used_c, total = set(), set(), 0.0
    for s, f, c in pairs:
        if f in used_f or c in used_c:
            continue
        used_f.add(f)
        used_c.add(c)
        total += s
    return round(total / max(len(df.columns), len(exp.columns), 1), 3)


def detect_table(df: pd.DataFrame, data_dir: Path = DATA_DIR) -> tuple[str | None, float]:
    """Which known export this file most resembles (by column names and value shapes, one found column to one expected column), and how well."""
    best, best_score = None, 0.0
    for table in KNOWN:
        score = fit(df, known_export(table, data_dir))
        if score > best_score:
            best, best_score = table, score
    return best, best_score


def drift_report(path: Path, data_dir: Path = DATA_DIR, table: str | None = None) -> dict:
    """`table` names the known export to compare with (the steward's own reading of the file); without it the closest one by `fit` is used."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    if table is not None:
        if table not in KNOWN:
            raise ValueError(f"no known export {table!r}; the known exports are {sorted(KNOWN)}")
        score = fit(df, known_export(table, data_dir))
    else:
        table, score = detect_table(df, data_dir)
    exp = known_export(table, data_dir) if table else pd.DataFrame()
    found, expected = list(df.columns), list(exp.columns)
    same = [c for c in found if c in expected]
    missing = [c for c in expected if c not in found]
    new = [c for c in found if c not in expected]
    guesses = []
    for m in missing:
        ranked = sorted(((_similarity(df[f], exp[m], f, m), f) for f in new), reverse=True)
        if ranked and ranked[0][0] >= 0.3:
            guesses.append({"expected": m, "probably": ranked[0][1], "score": ranked[0][0], "runner_up": ranked[1][1] if len(ranked) > 1 and ranked[1][0] >= 0.3 else None})
    reformatted = [{"column": c, "found": sorted(shapes(df[c]))[:4], "expected": sorted(shapes(exp[c]))[:4]} for c in same if shapes(df[c]) and not shapes(df[c]) <= shapes(exp[c])]
    return {
        "file": path.name, "rows": len(df), "looks_like": table, "match": score, "known_export": KNOWN.get(table), "expected_columns": expected, "found_columns": found,
        "missing": missing, "new": new, "likely_renames": guesses, "same_name_new_format": reformatted, "drifted": bool(missing or new or reformatted),
    }
