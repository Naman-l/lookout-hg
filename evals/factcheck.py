"""The commercial facts a sheet expects, checked against an answer: right, wrong, or not measured.

Two ways to measure a fact, and the page says which:
  by id        the fact names the number id a tool returns; the answer's number with that id is compared with the sheet's value within its tolerance.
               Equal is right; different is wrong. This is the strong check.
  in the text  the sheet has no id for it because no tool returns it as a number. The value is looked for in the answer's own words and numbers (a figure within
               the sheet's tolerance, or the date, or the text). Found is right (a weaker check: the figure is there, not proved to be said of the right thing).
               Not found is NOT wrong: the answer may leave it out or say it another way, so it is "not measured", never a failure and never a pass.
A fact the sheet expects and the answer never states stays not measured: missing information stays missing.
"""
from __future__ import annotations

import re

from . import graders

NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*([KkMm])?(?![\w])")
SUFFIX = {"k": 1_000, "m": 1_000_000}


def numbers_in(text: str) -> list[float]:
    """Every figure in the text, with $1.35M and 183K read as numbers; the thousands commas removed."""
    out = []
    for m in NUMBER.finditer(text or ""):
        v = float(m.group(1).replace(",", "") + (m.group(2) or ""))
        out.append(v * SUFFIX.get((m.group(3) or "").lower(), 1))
    return out


def _tolerance(fact: dict) -> float:
    return max(float(fact.get("tolerance") or 0), 0.0005)


def found_in_text(fact: dict, text: str) -> bool:
    v = fact["value"]
    if isinstance(v, (int, float)):
        tol = _tolerance(fact)
        return any(abs(n - v) <= abs(v) * tol for n in numbers_in(text)) if v else False
    low = (text or "").lower()
    return any(form.lower() in low for form in graders.date_forms(str(v)))


def answer_text(rec: dict) -> str:
    parts = [rec.get("finding", ""), *[f"{p.get('label', '')}. {p.get('text', '')}" for p in rec.get("points", [])], *rec.get("assumptions", []), *rec.get("would_change", []), (rec.get("next_step") or {}).get("what", "")]
    parts += [f"{q.get('what', '')} {q.get('why_it_blocks', q.get('why', ''))} {q.get('question', '')}" for q in rec.get("open_questions", [])]
    return "\n".join(str(p) for p in parts)


def label(fact: dict) -> str:
    return " ".join(str(x) for x in (fact["name"], fact.get("part"), fact.get("option"), (f"qty {fact['qty']}" if fact.get("qty") is not None else None)) if x)


def check_facts(facts: list[dict], rec: dict) -> list[dict]:
    """One row per expected fact: {fact, expected, via, got, status}. status is right, wrong or not measured."""
    nums = {n.get("id"): n for n in rec.get("numbers", [])}
    text = answer_text(rec)
    rows = []
    for f in facts:
        row = {"fact": label(f), "expected": f["value"], "source": f.get("source_table") or "", "via": None, "got": None, "status": "not measured"}
        if f.get("id"):
            n = nums.get(f["id"])
            row["via"] = "id"
            if n is None:
                row["status"] = "wrong"          # the tool gave this number and the answer does not state it: the grader fails it too
                row["got"] = "not in the answer"
            else:
                row["got"] = n.get("value")
                try:
                    ok = graders.within(float(n["value"]), float(f["value"]), f.get("tolerance", 0.0))
                except (TypeError, ValueError):
                    ok = False
                row["status"] = "right" if ok else "wrong"
        elif found_in_text(f, text):
            row.update(via="found in the answer", got=f["value"], status="right")
        rows.append(row)
    return rows


def tally(rows: list[dict]) -> dict[str, int]:
    out = {"right": 0, "wrong": 0, "not measured": 0}
    for r in rows:
        out[r["status"]] += 1
    return out
