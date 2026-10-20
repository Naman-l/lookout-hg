"""Hindsight replay: would the Action list have seen it coming?   python -m evals.hindsight [--cut 2026-09-17 ...] [--json evals/hindsight.json]

For each cut in evals/hindsight.yaml the records are built as the data stood that day (LOOKOUT_AS_OF), the app is served on them with that day as
"today", and the Action list is read. A thing must be on the list the day its source arrives (show) and must not be there before (hide): a hidden
item that shows means the app read the future. The records themselves are checked for leaks: no message and no order dated after the cut.
No model and no key. A build takes about ten seconds, so this is run by `make hindsight` and, for two cuts, by the tests.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx
import yaml

from . import agent_runner

ROOT = Path(__file__).resolve().parents[1]
SHEET = ROOT / "evals" / "hindsight.yaml"


def build_db(as_of: str, out: Path) -> None:
    env = {**os.environ, "LOOKOUT_AS_OF": as_of, "LOOKOUT_DB": str(out)}
    r = subprocess.run([sys.executable, "-m", "app.domain.imports.build", "--recipe", str(ROOT / "recipes" / "halden"), "--db", str(out)],
                       cwd=ROOT / "backend", env=env, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"build as of {as_of} failed: {(r.stdout + r.stderr)[-300:]}")


def leaks(db: Path, as_of: str) -> list[str]:
    con = sqlite3.connect(db)
    try:
        out = []
        late = con.execute("select count(*) from messages where substr(date,1,10) > ?", (as_of,)).fetchone()[0]
        if late:
            out.append(f"{late} message(s) dated after {as_of}")
        late = con.execute("select count(*) from po_lines where order_date > ?", (as_of,)).fetchone()[0]
        if late:
            out.append(f"{late} order line(s) dated after {as_of}")
        meta = dict(con.execute("select key, value from build_meta").fetchall())
        if meta.get("as_of") != as_of:
            out.append(f"the records say as_of {meta.get('as_of')}, not {as_of}")
        return out
    finally:
        con.close()


def run_cut(cut: dict, work: Path) -> dict:
    as_of = str(cut["as_of"])
    db = work / f"{as_of}.db"
    build_db(as_of, db)
    problems = leaks(db, as_of)
    os.environ["LOOKOUT_AS_OF"] = as_of
    try:
        with agent_runner.app_server(db, work / f"app-{as_of}", replay=True, extra_env={"LOOKOUT_AS_OF": as_of}) as base:
            health = httpx.get(f"{base}/api/health", timeout=10).json()
            items = httpx.get(f"{base}/api/action-items", timeout=30).json()
    finally:
        os.environ.pop("LOOKOUT_AS_OF", None)
    keys = {i["key"] for i in items}
    groups = {i["group"] for i in items}
    for k in cut.get("show", []):
        if k not in keys:
            problems.append(f"missing on {as_of}: {k}")
    for k in cut.get("hide", []):
        if k in keys:
            problems.append(f"shows before its source arrived: {k}")
    for g in cut.get("hide_groups", []):
        if g in groups:
            problems.append(f"a {g} item shows before any {g} source arrived: {sorted(i['key'] for i in items if i['group'] == g)}")
    snap = health.get("snapshot_date") or health.get("as_of")
    if snap and str(snap) != as_of:
        problems.append(f"the app says today is {snap}, not {as_of}")
    return {"as_of": as_of, "why": cut["why"], "items": len(items), "ok": not problems, "problems": problems,
            "on_the_list": sorted(keys)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evals.hindsight")
    ap.add_argument("--cut", action="append", help="only these dates")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    sheet = yaml.safe_load(SHEET.read_text())
    cuts = [c for c in sheet["cuts"] if not a.cut or str(c["as_of"]) in a.cut]
    results = []
    with tempfile.TemporaryDirectory(prefix="lookout-hindsight-") as w:
        for c in cuts:
            r = run_cut(c, Path(w))
            results.append(r)
            print(f"{'ok  ' if r['ok'] else 'FAIL'} as of {r['as_of']}: {r['items']} items on the list" + ("" if r["ok"] else "\n     " + "\n     ".join(r["problems"])))
    if a.json:
        a.json.write_text(json.dumps(results, indent=1))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
