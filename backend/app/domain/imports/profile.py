"""Profile raw files in code: types, missing, patterns, outliers, keys, duplicates and joins. No model, deterministic.

This is the Data steward's first look (design: IMPORT.md step 2). It reads; it never changes a file. The steward turns what it finds into
findings and questions; the numbers here are what it may cite.

    python -m app.domain.imports.profile [data_dir]
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
from pydantic import BaseModel

DATE_FORMATS = {"YYYY-MM-DD": r"\d{4}-\d{2}-\d{2}", "MM/DD/YYYY": r"\d{2}/\d{2}/\d{4}", "YYYY-MM": r"\d{4}-\d{2}", "YYYY/MM/DD": r"\d{4}/\d{2}/\d{2}"}


class ColumnProfile(BaseModel):
    name: str
    inferred_type: str  # integer | number | number (comma decimal) | date | id | text | empty
    missing: int
    missing_pct: float
    distinct: int
    top_values: list[tuple[str, int]]
    patterns: list[tuple[str, int]]  # value shapes: 9 for a digit, a/A for a letter; shows id shapes and date formats
    date_formats: list[str] = []
    numeric_min: float | None = None
    numeric_max: float | None = None
    numeric_median: float | None = None
    outliers: int = 0  # values more than 3 IQR beyond the quartiles
    is_candidate_key: bool = False


class FileProfile(BaseModel):
    file: str
    kind: str  # csv | email | text | pdf | json | markdown | other
    size_bytes: int
    rows: int | None = None
    columns: list[ColumnProfile] = []
    duplicate_rows: int = 0
    notes: list[str] = []


class JoinCandidate(BaseModel):
    left: str  # "file.column"
    right: str
    overlap_pct: float  # share of the smaller side's distinct values found on the other side, exactly as written
    shared: int
    normalised_overlap_pct: float  # the same after upper-casing and dropping spaces, hyphens and dots: a big jump means a formatting gap, not a missing record


class Profile(BaseModel):
    files: list[FileProfile]
    joins: list[JoinCandidate]


def shape(value: str) -> str:
    """'PN-12345' -> 'AA-99999'; '12/04/2024' -> '99/99/9999'. Runs longer than 4 are kept short with a count."""
    out = re.sub(r"[A-Z]", "A", re.sub(r"[a-z]", "a", re.sub(r"\d", "9", value)))
    return re.sub(r"(.)\1{4,}", lambda m: f"{m.group(1)}{{{len(m.group(0))}}}", out)


def _infer(values: pd.Series) -> tuple[str, list[str]]:
    v = values[values != ""]
    if v.empty:
        return "empty", []
    sample = v.head(2000)
    fmts = [name for name, pat in DATE_FORMATS.items() if sample.str.fullmatch(pat).mean() > 0.02]
    if fmts and sum(sample.str.fullmatch(DATE_FORMATS[f]).sum() for f in fmts) / len(sample) > 0.9:
        return "date", fmts
    if sample.str.fullmatch(r"-?\d+").all():
        return "integer", []
    if sample.str.fullmatch(r"-?\d+([.]\d+)?").all():
        return "number", []
    if sample.str.fullmatch(r"-?[\d.]+,\d+").mean() > 0.5:
        return "number (comma decimal)", []
    if sample.map(shape).nunique() <= 8 and sample.str.contains(r"\d").all() and sample.str.len().between(4, 20).all():
        return "id", []
    return "text", fmts


def _column(name: str, s: pd.Series, n_rows: int) -> ColumnProfile:
    present = s[s.str.strip() != ""]
    kind, fmts = _infer(s.str.strip())
    top = Counter(present).most_common(5)
    pats = Counter(present.map(shape)).most_common(5)
    prof = ColumnProfile(name=name, inferred_type=kind, missing=int(n_rows - len(present)), missing_pct=round(100 * (n_rows - len(present)) / max(n_rows, 1), 1),
                         distinct=int(present.nunique()), top_values=[(str(k), int(c)) for k, c in top], patterns=[(k, int(c)) for k, c in pats], date_formats=fmts,
                         is_candidate_key=bool(len(present) == n_rows and present.nunique() == n_rows and n_rows > 1))
    if kind in ("integer", "number"):
        x = pd.to_numeric(present, errors="coerce").dropna()
        if len(x):
            q1, q3 = x.quantile(0.25), x.quantile(0.75)
            iqr = q3 - q1
            prof.numeric_min, prof.numeric_max, prof.numeric_median = float(x.min()), float(x.max()), float(x.median())
            prof.outliers = int(((x < q1 - 3 * iqr) | (x > q3 + 3 * iqr)).sum()) if iqr > 0 else 0
    return prof


def profile_file(path: Path, root: Path | None = None) -> FileProfile:
    name = path.relative_to(root).as_posix() if root else path.name
    size = path.stat().st_size
    ext = path.suffix.lower()
    if ext == ".csv":
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        return FileProfile(file=name, kind="csv", size_bytes=size, rows=len(df), columns=[_column(c, df[c], len(df)) for c in df.columns],
                           duplicate_rows=int(df.duplicated().sum()))
    if ext == ".eml":
        return FileProfile(file=name, kind="email", size_bytes=size, notes=["an email: headers and a body, to be read as data"])
    if ext == ".txt":
        return FileProfile(file=name, kind="text", size_bytes=size, notes=["pasted text: no headers to rely on"])
    if ext == ".pdf":
        from pypdf import PdfReader

        r = PdfReader(path)
        return FileProfile(file=name, kind="pdf", size_bytes=size, rows=len(r.pages), notes=[f"{len(r.pages)} page{"" if len(r.pages) == 1 else "s"}, {sum(len(p.extract_text() or '') for p in r.pages)} characters of text"])
    if ext == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list) and data and isinstance(data[0], dict):
            df = pd.DataFrame(data).fillna("").astype(str)
            return FileProfile(file=name, kind="json", size_bytes=size, rows=len(df), columns=[_column(c, df[c], len(df)) for c in df.columns],
                               duplicate_rows=int(df.duplicated().sum()), notes=["a list of records"])
        return FileProfile(file=name, kind="json", size_bytes=size, notes=["not a list of records"])
    if ext == ".md":
        return FileProfile(file=name, kind="markdown", size_bytes=size, notes=[f"{len(path.read_text(encoding='utf-8').splitlines())} lines; tables are read by rule"])
    return FileProfile(file=name, kind="other", size_bytes=size)


def _norm(v: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", v.upper().replace("O", "0"))


def find_joins(files: list[FileProfile], root: Path, min_overlap: float = 0.5, min_distinct: int = 20) -> list[JoinCandidate]:
    """Pairs of id-like or text columns in different files whose values overlap exactly as written. A normalised overlap far above the exact one
    (a part number with and without its hyphen) is a formatting gap the recipe has to close; a low one is a real gap, a finding."""
    sets: dict[str, set[str]] = {}
    for f in files:
        if f.kind not in ("csv", "json"):
            continue
        df = pd.read_csv(root / f.file, dtype=str, keep_default_na=False) if f.kind == "csv" else pd.DataFrame(json.loads((root / f.file).read_text(encoding="utf-8"))).fillna("").astype(str)
        for c in f.columns:
            if c.inferred_type in ("id", "text") and c.distinct >= min_distinct and c.name not in ("description", "headline", "summary", "url", "name", "contact_email"):
                sets[f"{f.file}.{c.name}"] = set(df[c.name].str.strip()) - {""}
    out = []
    keys = sorted(sets)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if a.split(".")[0] == b.split(".")[0]:
                continue
            small = min(len(sets[a]), len(sets[b]))
            shared = len(sets[a] & sets[b])
            na, nb = {_norm(x) for x in sets[a]}, {_norm(x) for x in sets[b]}
            nshared = len(na & nb)
            if small and nshared / min(len(na), len(nb)) >= min_overlap:
                out.append(JoinCandidate(left=a, right=b, overlap_pct=round(100 * shared / small, 1), shared=shared,
                                         normalised_overlap_pct=round(100 * nshared / min(len(na), len(nb)), 1)))
    return sorted(out, key=lambda j: (-j.normalised_overlap_pct, -j.overlap_pct))


def profile_all(data_dir: Path) -> Profile:
    data_dir = Path(data_dir)
    files = [profile_file(p, data_dir) for p in sorted(data_dir.rglob("*")) if p.is_file() and not p.name.startswith(".") and p.name != "README.md"]
    return Profile(files=files, joins=find_joins(files, data_dir))


if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[4] / "data")
    prof = profile_all(root)
    for f in prof.files:
        print(f"{f.file}: {f.kind}, {f.size_bytes} bytes" + (f", {f.rows} rows, {f.duplicate_rows} duplicate" if f.rows is not None and f.kind in ("csv", "json") else ""))
        for c in f.columns:
            flag = " KEY" if c.is_candidate_key else ""
            print(f"   {c.name:<24}{c.inferred_type:<24}missing {c.missing:>4} distinct {c.distinct:>5}  {c.patterns[0][0] if c.patterns else ''}{flag}")
    print("\njoin candidates:")
    for j in prof.joins[:15]:
        print(f"   {j.left} ~ {j.right}: {j.overlap_pct}% as written, {j.normalised_overlap_pct}% normalised ({j.shared} shared)")
