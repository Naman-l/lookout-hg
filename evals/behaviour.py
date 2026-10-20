"""Graders for cases that are about what the agent DID over more than one step, read from the ledger and the run log, not from its words.

  sequence   several runs and an approval in a row on one fresh database: how many requests to one contact the ledger holds, and whether any run failed
  followup   a second Ask turn that follows the first: does it carry the first turn, stay on what the first was about, and name what the first was about
  robots     a figure said of robots for a product and month must not exceed that month's forecast (a cumulative backlog is not a month's shortage)

Each returns one dimension ({"name", "passed", "detail"}). They read only the trial's own record: its runs' events, the final ledger and the raw forecast.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from . import graders

ROOT = Path(__file__).resolve().parents[1]
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}
PRODUCTS = {"tern": "Tern T2", "porter": "Porter P5", "heron": "Heron H1"}
HEDGES = ("cumulative", "carried", "carry", "backlog", "since", "through", "by the end", "in total", "altogether", "over the")
PART = re.compile(r"HR-\d{5}")


def grade_sequence(spec: dict, t: dict) -> dict:
    """The ledger across the whole sequence: exactly `count` requests of `type` to `recipient`, and every run finished ok (none did_not_pass because it cited a draft that was already open)."""
    acts = [a for a in t.get("all_actions", []) if a["type"] == spec["type"] and a.get("recipient") == spec["recipient"] and a.get("state") != "rejected"]
    want = spec.get("count", 1)
    bad = []
    if spec.get("per") == "owner":
        # one open request per (contact, owner): two buyers with lines at one contact each sign their own; two for the same owner are a duplicate
        by_owner: dict[str, list[str]] = {}
        for a in acts:
            by_owner.setdefault(str((a.get("change") or {}).get("owner") or a.get("owner") or "no owner recorded"), []).append(a["action_id"])
        dup = {o: ids for o, ids in by_owner.items() if len(ids) > want}
        if not acts:
            bad.append(f"no {spec['type']} to {spec['recipient']} in the ledger")
        if dup:
            bad.append(f"more than {want} {spec['type']} to {spec['recipient']} for the same owner: {dup}")
    elif len(acts) != want:
        bad.append(f"{len(acts)} {spec['type']} to {spec['recipient']} in the ledger, expected {want}: {[a['action_id'] for a in acts]}")
    for i, run in enumerate(t.get("runs", []), 1):
        if "detail" in run and (run["detail"] or {}).get("status") not in ("ok",):
            bad.append(f"step {i} ended {(run['detail'] or {}).get('status')}: {', '.join(((run['detail'] or {}).get('verifier') or {}).get('failures', [])[:2])}")
        if "approve" in run and run["approve"] != 200:
            bad.append(f"step {i}: the approval returned {run['approve']}")
    return graders._dim("sequence", not bad, "; ".join(bad) or f"{len(acts)} {spec['type']} to {spec['recipient']} across {len(t.get('runs', []))} steps ({'one per owner at most' if spec.get('per') == 'owner' else 'exactly ' + str(want)}); every run ended ok")


def _refs(events: list[dict], kind: str) -> set[str]:
    return {r["id"] for e in events for r in (e.get("refs") or []) if r.get("type") == kind}


def _text(run: dict) -> str:
    rec = (run.get("detail") or {}).get("recommendation") or {}
    return " ".join([rec.get("finding", ""), *[f"{p.get('label', '')}. {p.get('text', '')}" for p in rec.get("points", [])], *rec.get("assumptions", []), *rec.get("would_change", []),
                     *[f"{q.get('what', '')} {q.get('question', '')}" for q in rec.get("open_questions", [])]])


def grade_followup(spec: dict, t: dict, owed_parts: set[str]) -> dict:
    """Turn 2 follows turn 1: it is marked as following, it names no part that turn 1 was not about, it names the owed parts turn 1 was about, and the gate denied nothing."""
    runs = [r for r in t.get("runs", []) if "events" in r]
    if len(runs) < 2:
        return graders._dim("followup", False, "fewer than two turns ran", ["two turns"], 0)
    one, two = runs[0], runs[1]
    bad = []
    started = next((e["payload"] for e in two["events"] if e["type"] == "run.started" and not e.get("parent_run_id")), {})
    if not started.get("follows"):
        bad.append("the second turn did not carry the first (run.started says it follows nothing)")
    about = _refs(one["events"], "part") | set(PART.findall(_text(one)))
    db = t.get("db_path")
    if db and Path(db).exists():
        con = sqlite3.connect(db)
        try:
            for line in _refs(one["events"], "po_line"):
                row = con.execute("select part_number from po_lines where id = ?", (line,)).fetchone()
                if row:
                    about.add(row[0])
        finally:
            con.close()
    named = _refs(two["events"], "part") | set(PART.findall(_text(two)))
    stray = sorted(named - about)
    if stray:
        bad.append(f"the second turn names parts the first was not about: {stray}")
    owed_in_scope = sorted(owed_parts & about)
    missed = [p for p in owed_in_scope if p not in named]
    if missed:
        bad.append(f"parts the first turn was about that owe the new duty, not named: {missed}")
    denied = [e["summary"] for e in two["events"] if e["type"] == "tool.called" and (e.get("payload") or {}).get("gate") == "denied"]
    if denied or "have not read the other" in _text(two).lower():
        bad.append(f"the gate denied {len(denied)} call(s) in the second turn" if denied else "the answer says it did not read the other parts")
    return graders._dim("followup", not bad, "; ".join(bad) or f"the second turn follows the first; {len(named)} parts named, all within the first turn's {len(about)}; owed in scope named: {owed_in_scope or 'none in scope'}")


def forecast(path: Path | None = None) -> dict[tuple[str, int], int]:
    import csv
    out = {}
    with open(path or ROOT / "data" / "demand_forecast.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            y, m = r["month"].split("-")
            out[(r["product"], int(m))] = out.get((r["product"], int(m)), 0) + int(float(r["units"]))
    return out


def grade_robots(text: str, fc: dict[tuple[str, int], int] | None = None) -> dict:
    """A number of robots said of one product in one month cannot be more than that month's forecast, unless the sentence says it is a cumulative or carried figure.
    Read sentence by sentence: the product and the month are the ones named in the same sentence."""
    fc = fc if fc is not None else forecast()
    if not text.strip():
        return graders._dim("robots", False, "no answer to read")
    bad, checked = [], 0
    for sent in re.split(r"(?<=[.;!?])\s+|\n", text):
        low = sent.lower()
        prods = [name for key, name in PRODUCTS.items() if key in low]
        months = [n for mname, n in MONTHS.items() if mname in low or mname[:3] + " " in low or re.search(rf"\b{mname[:3]}\b", low)]
        if len(prods) != 1 or len(months) != 1:
            continue
        for m in re.finditer(r"(\d[\d,]*)\s+(?:robots|builds|units|robot)\b", low):
            n = int(m.group(1).replace(",", ""))
            cap = fc.get((prods[0], months[0]))
            if cap is None:
                continue
            checked += 1
            if n > cap and not any(h in low for h in HEDGES):
                bad.append(f"{n} robots said of the {prods[0]} in month {months[0]}, but its forecast is {cap}: '{sent.strip()[:120]}'")
    return graders._dim("robots", not bad, "; ".join(bad) or f"{checked} robot figure(s) for a product-month, none above that month's forecast")
