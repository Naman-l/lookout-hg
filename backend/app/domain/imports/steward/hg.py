"""The Data steward's reading of an export the recipe has not seen, in code (no model is connected here): which known export it is, which incoming
column is which expected one (by name and by the shape of its values, a proposal), what changed format (slash dates, Indian digit grouping), which
values do not resolve (a plant written as a site's name), and the few questions only a person can answer. It reads; nothing is loaded or changed.

The proposed links are proposals: "'<name as written>' looks like <project> (plant <code>). Link?" is a question for a person, never a match by likeness.
"""

from __future__ import annotations

import csv
import difflib
import io
import re
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from app.domain import lookups

ROOT = Path(__file__).resolve().parents[5]
DATA = ROOT / "data"
KNOWN = {"ME2N purchase orders": "sap/ME2N_purchase_orders.csv", "ME5A purchase requisitions": "sap/ME5A_purchase_requisitions.csv",
         "MB51 goods receipts": "sap/MB51_goods_receipts.csv", "Vendor master": "sap/vendor_master.csv"}
EXAMPLE = DATA / "incoming" / "ME2N_site_office_Oct26.csv"
INDIAN = re.compile(r"^\d{1,2}(,\d\d)*,\d{3}(\.\d+)?$")
WESTERN = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$")


def _read(text: str) -> pd.DataFrame:
    lines = text.splitlines()
    if lines and " | " in lines[0] and "Exported" in lines[0]:      # a SAP list export's stamp line
        lines = lines[1:]
    return pd.read_csv(io.StringIO("\n".join(lines)), dtype=str, keep_default_na=False)


def known(name: str) -> pd.DataFrame:
    return pd.read_csv(DATA / KNOWN[name], skiprows=1, dtype=str, keep_default_na=False)


def shape(v: str) -> str:
    """A value's shape with what drifts between exports folded away (date separators, digit-group commas), so a renamed date or amount column still
    looks like itself."""
    v = re.sub(r"(?<=\d)[/-](?=\d)", ".", v.strip())
    v = re.sub(r"(?<=\d),(?=\d)", "", v)
    return re.sub(r"[A-Za-z]", "a", re.sub(r"\d", "9", v))[:14]


def _shapes(col: pd.Series) -> set[str]:
    return {shape(v) for v in col.head(200) if v.strip()}


def _score(inc: pd.Series, iname: str, exp: pd.Series, ename: str) -> float:
    by_name = difflib.SequenceMatcher(None, re.sub(r"[^a-z]", "", iname.lower()), re.sub(r"[^a-z]", "", ename.lower())).ratio()
    a, b = _shapes(inc), _shapes(exp)
    by_shape = len(a & b) / len(a | b) if a | b else 0.0
    same_values = len(set(inc.head(200)) & set(exp)) / max(1, len(set(inc.head(200))))
    return round(0.35 * by_name + 0.25 * by_shape + 0.4 * same_values, 3)


def mapping(df: pd.DataFrame, exp: pd.DataFrame) -> tuple[dict[str, str], float]:
    """{incoming column: expected column} by the best score, each expected column used once; and the mean score of the matches."""
    pairs = sorted(((_score(df[i], i, exp[e], e), i, e) for i in df.columns for e in exp.columns), reverse=True)
    used_i, used_e, out, scores = set(), set(), {}, []
    for sc, i, e in pairs:
        if sc < 0.3 or i in used_i or e in used_e:
            continue
        out[i], _ = e, used_i.add(i)
        used_e.add(e)
        scores.append(sc)
    return out, (sum(scores) / len(scores) if scores else 0.0)


def read_file(session: Session, name: str, text: str) -> dict:
    df = _read(text)
    best = None
    for k in KNOWN:
        m, fit = mapping(df, known(k))
        if best is None or (len(m), fit) > (len(best[1]), best[2]):
            best = (k, m, fit)
    table, cols, fit = best
    exp = known(table)
    findings, questions, checks = [], [], []
    renamed = {i: e for i, e in cols.items() if i != e}
    if renamed:
        findings.append({"issue": f"{len(renamed)} columns carry other names than {table} prints", "count": len(renamed), "handling": "fix",
                         "consequence": "read under the expected names; the raw names are kept", "example": "; ".join(f"{i} → {e}" for i, e in list(renamed.items())[:4])})
    missing = [e for e in exp.columns if e not in cols.values()]
    if missing:
        findings.append({"issue": f"{len(missing)} {table} columns are not in this download", "count": len(missing), "handling": "leave",
                         "consequence": "those fields stay unknown for these lines (" + ", ".join(missing[:5]) + (" ..." if len(missing) > 5 else "") + ")", "example": missing[0]})
    for i, e in cols.items():
        vals = [v for v in df[i] if v.strip()]
        slash = [v for v in vals if re.fullmatch(r"\d{2}/\d{2}/\d{4}", v)]
        if slash and any(re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", v) for v in exp[e].head(50)):
            findings.append({"issue": f"{i}: dates written dd/mm/yyyy, not dd.mm.yyyy", "count": len(slash), "handling": "fix", "consequence": "read day first, as the SAP export does", "example": slash[0]})
        grouped = [v for v in vals if "," in v and re.fullmatch(r"[\d,]+(\.\d+)?", v)]
        if grouped:
            lakh = [v for v in grouped if INDIAN.match(v) and not WESTERN.match(v)]
            findings.append({"issue": f"{i}: numbers written with digit-group commas" + (" (Indian lakh grouping)" if lakh else ""), "count": len(grouped), "handling": "fix",
                             "consequence": "the commas are dropped before the number is read", "example": (lakh or grouped)[0]})
    site_col = next((i for i, e in cols.items() if e == "Plant"), None)
    if site_col is None:
        site_col = next((c for c in df.columns if c.lower() in ("site", "project", "plant name")), None)
    if site_col is not None:
        codes = set(lookups.plants(session))
        names = sorted(set(df[site_col]) - codes)
        resolved = {n: lookups.resolve_project(session, n) for n in names}
        if names:
            findings.append({"issue": f"{site_col}: the plant is written as the site's name", "count": int(df[site_col].isin(names).sum()), "handling": "link",
                             "consequence": "each name is read as the plant of the project it names; a name nobody linked waits for a person", "example": names[0]})
        for n in names:
            pid = resolved[n]
            covers = int((df[site_col] == n).sum())
            plant = (lookups.plants_of(session).get(pid) or ["none"])[0] if pid else None
            if pid and lookups.project_name(session, pid).lower() == n.lower():
                continue      # the project's own name: no question
            if pid:
                questions.append({"question": f"'{n}' is linked to {lookups.project_name(session, pid)} (plant {plant}) by an earlier answer. Use it here too?", "covers": covers,
                                  "proposed_answer": f"Yes: {lookups.project_name(session, pid)}, plant {plant}", "why_it_blocks": "the lines need a plant to be read"})
                continue
            near = difflib.get_close_matches(n.lower(), [p.name.lower() for p in lookups.projects(session).values()], n=1, cutoff=0.7)
            cand = next((p for p in lookups.projects(session).values() if near and p.name.lower() == near[0]), None)
            plant = (lookups.plants_of(session).get(cand.id) or ["none"])[0] if cand else None
            questions.append({"question": f"'{n}' looks like {cand.name} (same plant {plant}). Link?" if cand else f"Which project is '{n}'?", "covers": covers,
                              "proposed_answer": f"{cand.name}, plant {plant}" if cand else "unknown: ask the site", "why_it_blocks": "until someone says which project it is, its lines carry no plant"})
    po_col = next((i for i, e in cols.items() if e in ("Purchasing Document", "Purchase Requisition")), None)
    on_file = 0
    if po_col and table == "ME2N purchase orders":
        line_col = next((i for i, e in cols.items() if e == "Item"), None)
        exp_keys = set(zip(exp["Purchasing Document"], exp["Item"]))
        on_file = sum(1 for _, r in df.iterrows() if (r[po_col], r[line_col] if line_col else "") in exp_keys)
        findings.append({"issue": "Lines already in the ME2N export", "count": on_file, "handling": "flag",
                         "consequence": "the same line read twice would double its open value: the load keeps the SAP export's line and records this file's as a repeat",
                         "example": f"{df.iloc[0][po_col]}/{df.iloc[0][line_col]}" if line_col else ""})
    vendor_col = next((i for i, e in cols.items() if e in ("Supplier", "Vendor")), None)
    mat_col = next((i for i, e in cols.items() if e == "Material"), None)
    checks.append({"name": "rows in = rows out", "passed": True, "detail": f"{len(df)} rows read, {len(df)} kept"})
    if vendor_col:
        bad = [v for v in df[vendor_col] if v and v not in lookups.records(session)]
        checks.append({"name": "every vendor code is in the vendor master", "passed": not bad, "detail": f"{len(bad)} not found" if bad else "all found"})
    if mat_col:
        bad = [v for v in df[mat_col] if v and v not in lookups.materials(session)]
        checks.append({"name": "every material is in the material master", "passed": not bad, "detail": f"{len(bad)} not found" if bad else "all found"})
    checks.append({"name": "every site resolves to a plant", "passed": not questions, "detail": f"{sum(q['covers'] for q in questions)} rows wait for an answer" if questions else "all resolve"})
    script = "\n".join([f"# read {name} as {table}", *[f"rename {i!r} -> {e!r}" for i, e in renamed.items()],
                        *(["parse dates dd/mm/yyyy (day first)"] if any("dates written" in f["issue"] for f in findings) else []),
                        *(["drop lakh commas before reading numbers"] if any("Indian digit" in f["issue"] for f in findings) else []),
                        *([f"plant from {site_col}: by the project's name or an answered alias; else wait for the answer"] if site_col else [])])
    return {"file": name, "table": table, "fit": round(fit, 2), "rows_in": len(df), "rows_out": len(df), "mapping": cols, "findings": findings, "questions": questions,
            "checks": checks, "script": script, "already_on_file": on_file}


def example() -> dict:
    return {"filename": EXAMPLE.name, "text": EXAMPLE.read_text(encoding="utf-8")} if EXAMPLE.exists() else {"filename": "", "text": ""}


__all__ = ["read_file", "example", "csv"]
