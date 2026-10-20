"""The Ask answer's tables (F100, Rev 4.2), built by code when a run is read, from the figures the run's own tools returned.

An answer that compares or lists shows them as the Analysis card's compact tables, not prose. The agent never writes a table: every cell is a
number a tool returned in this run, with its evidence id, so a cell is cited and is the same figure the verifier checks the answer against.
Derived, never stored, so every stored run and recording gets it with no re-record."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from ..schemas import AskTable, RunEvent, TableCell, TableRow
from ..specialists.registry import SPECIALISTS
from ..toolkit import money_words

MAX_ROWS = 6  # then "+N in Analysis ›"
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# kind -> (id pattern: groups row id, column key), the columns in order (key, heading), title, the row's ref type
_KINDS = (
    ("shortfall", re.compile(r"^shortage:(?P<row>[^:]+):(?P<col>\d{4}-\d{2}):short$"), None, "Short by month", "part"),
    ("po_lines", re.compile(r"^supply:(?P<part>[^:]+):(?P<row>[^:]+/\d+):(?P<col>qty)$"), (("qty", "Open qty"),), "Open PO lines", "po_line"),
    ("exposure", re.compile(r"^tariff:(?P<row>[^:]+):(?P<col>net|conditional)$"), (("net", "Duty owed"), ("conditional", "Only if late")), "New duty by part", "part"),
    ("late_lines", re.compile(r"^item:deadline:chase:chase:(?P<row>[^:]+/\d+)$"), None, "Late lines (no word from the supplier)", "po_line"),
    ("quotes", re.compile(r"^quote:(?P<part>[^:]+):(?P<row>[^:]+):(?P<col>price|duty|total|total_if_china)$"),
     (("price", "Price each"), ("duty", "Duty"), ("total", "Landed"), ("total_if_china", "If ruled China")), "Quotes compared", "quote"),
)


def _say(n: dict) -> str:
    if n.get("say"):
        return n["say"]
    try:
        v = Decimal(str(n.get("value")))
    except (InvalidOperation, TypeError):
        return str(n.get("value"))
    unit = n.get("unit") or ""
    if unit == "USD":
        return money_words(v)
    whole = f"{v:,.0f}" if v == v.to_integral_value() else f"{v:,}"
    return f"{whole}%" if unit == "%" else whole


def _month(col: str) -> str:
    return _MONTHS[int(col[5:7]) - 1]


def _late_note(name: str) -> str:
    """Code's label for a late line without what the row and the table already say: the line and part before the colon, and 'no message mentions it'."""
    rest = name.split(": ", 1)[1] if ": " in name else name
    return re.sub(r",?\s*no message mentions it\s*$", "", rest).strip()


def _named_lines(text: str, lines: list[str]) -> set[str]:
    """The PO lines an answer names, written in full (<prefix>-<year>-<number>/<line>) or short (<number>/<line>)."""
    t = text or ""
    return {ln for ln in lines if ln in t or re.search(rf"(?<![\w/-]){re.escape(ln.split('-')[-1])}(?![\w/])", t)}


def build(events: list[RunEvent], asked_by: str | None = None, answer_text: str = "") -> list[AskTable]:
    """The tables a run's tool results support, in the order the run first read each kind. Only results that returned (ok) count."""
    found: dict[str, dict] = {}  # kind -> {"by": label, "rows": {row: {"part":, "cells": {col: number}}}, "cols": [...]}
    for e in sorted(events, key=lambda e: (e.t_ms, e.seq)):
        p = e.payload or {}
        if e.type != "tool.result" or p.get("ok") is False:
            continue
        for n in p.get("numbers") or []:
            for kind, rx, _, _, _ in _KINDS:
                m = rx.match(str(n.get("id", "")))
                if not m:
                    continue
                t = found.setdefault(kind, {"by": SPECIALISTS[e.agent].label if e.agent in SPECIALISTS else "Lookout", "rows": {}, "cols": []})
                if kind == "late_lines":  # one row per line: its open value, and code's own words for it
                    t = found.setdefault(kind, {"by": "Lookout", "rows": {}, "cols": ["value"]})
                    pm = re.search(r"\(([^()]+)\):", n.get("name") or "")  # the line's part, as code's label names it
                    t["rows"][m["row"]] = {"part": pm.group(1) if pm else None, "label": m["row"], "cells": {"value": n}, "note": _late_note(n.get("name") or "")}
                    break
                part = m.groupdict().get("part")
                row = t["rows"].setdefault((part, m["row"]) if kind == "quotes" else m["row"], {"part": part, "label": m["row"], "cells": {}})
                row["cells"][m["col"]] = n
                if m["col"] not in t["cols"]:
                    t["cols"].append(m["col"])
                break
    out = []
    for kind, _, cols, title, ref in _KINDS:
        if kind not in found:
            continue
        t = found[kind]
        if kind == "late_lines":  # each line's robots on order, bound to its own part and robot (Q8: a count was said of the wrong robot)
            covers: dict[str, list] = {}
            for e in events:
                for n in ((e.payload or {}).get("numbers") or []) if e.type == "tool.result" else []:
                    cm = re.match(r"^cover:([^:]+):([^:]+):robots_on_order$", str(n.get("id", "")))
                    if cm:
                        covers.setdefault(cm.group(1), []).append(n)
            for v in t["rows"].values():
                for c in covers.get(v.get("part") or "", []):
                    robot = (c.get("name") or "").split(" robots ")[0]
                    if robot and f"feeds {robot}" in (v.get("note") or ""):  # the count of the robot the line's own label feeds: a part on two robots has two figures (AGENT-EXPERT)
                        v["cells"]["cover"] = {**c, "say": f"{_say(c)} {robot}".strip()}
                        break
            if any("cover" in v["cells"] for v in t["rows"].values()):
                t["cols"].append("cover")
        keys = ([("value", "Open value")] + ([("cover", "Robots on order")] if "cover" in t["cols"] else [])) if kind == "late_lines" else cols and [(k, h) for k, h in cols if k in t["cols"]] or [(c, _month(c)) for c in sorted(t["cols"])]
        rows = [TableRow(label="Current price" if v["label"] == "current" else v["label"], ref={"type": ref, "id": v["label"]}, note=v.get("note"), part=v["part"] if v["part"] and v["part"].startswith("HR-") else None,
                         cells=[TableCell(say=_say(v["cells"][k]), id=v["cells"][k]["id"]) if k in v["cells"] else None for k, _ in keys])
                for v in t["rows"].values()]
        if kind in ("po_lines", "late_lines") and answer_text:  # the answer is about some of the lines read: those first; the rest are counted, never hidden (the table is code's evidence; AGENT-EXPERT)
            named = _named_lines(answer_text, [r.label for r in rows])
            if named and len(named) < len(rows):
                others = [r for r in rows if r.label not in named]
                rows = [r for r in rows if r.label in named]
                out.append(AskTable(kind=kind, title=title, by=t["by"], columns=[h for _, h in keys], rows=rows[:MAX_ROWS],
                                    more=max(0, len(rows) - MAX_ROWS) + len(others), more_what="other lines read"))
                continue
        if kind == "late_lines" and asked_by:  # 'my late lines': the asker's own, when code's label names them as the buyer
            first = asked_by.split()[0]
            mine = [r for r in rows if f", {first}," in f"{r.note or ''},"]
            rows = mine or rows
        if kind == "exposure":  # the largest duty first
            rows.sort(key=lambda r: -Decimal(str(t["rows"][r.ref["id"]]["cells"].get("net", {}).get("value") or 0)))
        out.append(AskTable(kind=kind, title=title, by=t["by"], columns=[h for _, h in keys], rows=rows[:MAX_ROWS], more=max(0, len(rows) - MAX_ROWS)))
    order = {k: min(i for i, e in enumerate(events) if e.type == "tool.result" and any(rx.match(str(n.get("id", ""))) for n in (e.payload or {}).get("numbers") or []))
             for k, rx, *_ in _KINDS if k in found}
    return sorted(out, key=lambda t: order[t.kind])
