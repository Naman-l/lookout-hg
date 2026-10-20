"""What the live runs have cost, from the ledger in evals/spend.yaml.   python -m evals.spend

The README quotes `line()`, so the number cannot drift from the file. A run with no recorded cost is
listed as such, never estimated; a run that has not happened is `pending`. The ledger also carries the
cap Khalid set for the three final live runs, and how much of it is spent.
"""
from __future__ import annotations

from pathlib import Path

import yaml

HERE = Path(__file__).parent


def _doc(path: Path | None = None) -> dict:
    d = yaml.safe_load((path or HERE / "spend.yaml").read_text()) or {}
    return d if isinstance(d, dict) else {"runs": d}


def load(path: Path | None = None) -> list[dict]:
    return _doc(path).get("runs", [])


def cap(path: Path | None = None) -> dict | None:
    return _doc(path).get("cap")


def total(rows: list[dict]) -> float:
    return round(sum(r["usd"] for r in rows if r.get("usd") is not None), 2)


def capped(rows: list[dict]) -> tuple[float, int, int]:
    """(spent, runs done, runs covered) for the runs the cap covers."""
    mine = [r for r in rows if r.get("in_cap")]
    return total(mine), sum(1 for r in mine if not r.get("pending")), len(mine)


def line(rows: list[dict] | None = None, c: dict | None = None) -> str:
    if rows is None:
        d = _doc()
        rows, c = d.get("runs", []), d.get("cap")
    past = [r for r in rows if not r.get("pending")]
    unrecorded = [r["run"] for r in past if r.get("usd") is None]
    recorded = [r for r in past if r.get("usd") is not None]
    text = f"{total(rows):.2f} USD recorded in {len(recorded)} ledger rows (a run, or its judging or re-grading, each a row)"
    text += f", plus {', '.join(unrecorded)} (cost not recorded)" if unrecorded else ""
    text += " (the CLI login's notional figures)"
    if c:
        spent, done, n = capped(rows)
        text += f". Final live runs: {spent:.2f} of a {c['usd']} USD cap spent, {done} of {n} done"
    return text


if __name__ == "__main__" and (len(__import__("sys").argv) < 2 or __import__("sys").argv[1] != "add-round"):
    d = _doc()
    for r in d.get("runs", []):
        cost = "pending" if r.get("pending") else "not recorded" if r.get("usd") is None else f"{r['usd']:6.2f} USD"
        print(f"{r['run']:34} {cost:>13}  {r.get('note', '')}")
    print(line(d.get("runs", []), d.get("cap")))


def add_round(name: str, report_path: Path | None = None, note: str = "") -> list[dict]:
    """Append a round's two ledger rows (the agent runs, the prose judge inside the run) from the report it just wrote, so no cost is typed by hand.
    Older rows stop pointing at report.json: only the newest report is on disk."""
    import json
    import re
    rep = json.loads((report_path or HERE / "report.json").read_text())["results"]
    sp = [v["speed"] for k, v in rep.items() if not k.startswith("_") and v.get("speed")]
    agent = round(sum(s.get("cost_usd") or 0 for s in sp), 2)
    judge = round(sum(s.get("judge_cost_usd") or 0 for s in sp), 2)
    runs = sum(v.get("runs", len(v.get("trials") or [1])) for k, v in rep.items() if not k.startswith("_") and v.get("speed"))
    rows = [{"run": name, "usd": agent, "report": "report.json", "in_cap": True, "note": f"{runs} live agent runs{(' ' + note) if note else ''}; the prose judge inside the run cost {judge} more, next line"},
            {"run": f"{name}, prose judge in the run", "usd": judge, "report": None, "in_cap": True, "note": "judge calls (claude-opus-5-5)"}]
    path = HERE / "spend.yaml"
    text = re.sub(r"report: report\.json,", "report: null,", path.read_text().rstrip("\n"))
    for r in rows:
        text += "\n  - {" + ", ".join(f"{k}: {json.dumps(v)}" for k, v in r.items()) + "}"
    path.write_text(text + "\n")
    return rows


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "add-round":
        add_round(sys.argv[2], note=" ".join(sys.argv[3:]))
        print(line())
    else:
        d = _doc()
        for r in d.get("runs", []):
            cost = "pending" if r.get("pending") else "not recorded" if r.get("usd") is None else f"{r['usd']:6.2f} USD"
            print(f"{r['run']:34} {cost:>13}  {r.get('note', '')}")
        print(line(d.get("runs", []), d.get("cap")))
