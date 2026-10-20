"""The system on data it never saw.   python -m evals.perturbed [--json evals/perturbed.json]

The same recipe is run on changed data (the supplier whose plant burns is renamed everywhere it is written, the fraud mail asks for another amount),
the app is served on the result, and four things are asked: does the build pass; does the Action list find the fire and the fraud under the new
name with the old name nowhere in anything the app says; does the independent oracle, run on the changed files, agree with the app on the three
tariff amounts per part (the arithmetic and the rule, on numbers neither has seen); and do the trust scenarios still hold. DOMAIN's own test
(backend/tests/domain/test_perturbed.py) checks the build side more widely (a sixth buyer, a moved data date, an unextracted quote); this one
is the end-to-end, over HTTP, graded by the oracle. No model, no key.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

from . import agent_runner, oracle

ROOT = Path(__file__).resolve().parents[1]
OLD, NEW = "Yunzhan", "Marlowe"
SWAPS = [("yunzhan-rnotor", "marlowe-rnotion"), ("yunzhan-motor", "marlowe-motion"), ("Yunzhan", "Marlowe"), ("YUNZHAN", "MARLOWE"), ("yunzhan", "marlowe"), ("Ruilian", "Caldera"), ("RUILIAN", "CALDERA"), ("ruilian", "caldera")]
FRAUD_FROM, FRAUD_TO = "187,420.00", "61,205.50"


def _swap(text: str) -> str:
    for a, b in SWAPS:
        text = text.replace(a, b)
    return text


def make_world(root: Path) -> tuple[Path, Path]:
    """(data dir, database) of the recipe run on the changed files."""
    data = root / "data"
    shutil.copytree(ROOT / "data", data, ignore=shutil.ignore_patterns("__pycache__"))
    for p in [*data.glob("*.csv"), *(data / "external").glob("*"), *(data / "quotes").glob("*")]:
        if p.is_file() and p.suffix in (".csv", ".json", ".md", ".eml", ".txt"):
            p.write_text(_swap(p.read_text(encoding="utf-8")), encoding="utf-8")
        if p.is_file() and OLD in p.name:
            p.rename(p.with_name(_swap(p.name)))
    fraud = next((data / "quotes").glob("*URGENT*"))
    fraud.write_text(fraud.read_text(encoding="utf-8").replace(FRAUD_FROM, FRAUD_TO), encoding="utf-8")
    db = root / "perturbed.db"
    env = {**os.environ, "LOOKOUT_DB": str(db)}
    done = subprocess.run([sys.executable, "-m", "app.domain.imports.build", "--recipe", str(ROOT / "recipes" / "halden"), "--data", str(data), "--db", str(db)],
                          cwd=ROOT / "backend", env=env, capture_output=True, text=True, timeout=300)
    if done.returncode != 0:
        raise RuntimeError("the build failed on the changed data: " + (done.stdout + done.stderr)[-400:])
    return data, db


def _check(name: str, ok: bool, detail: str) -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail}


def run() -> list[dict]:
    out = []
    with tempfile.TemporaryDirectory(prefix="lookout-perturbed-") as w:
        w = Path(w)
        try:
            data, db = make_world(w / "world")
        except RuntimeError as e:
            return [_check("the build passes on changed data", False, str(e))]
        out.append(_check("the build passes on changed data", True, "35 gate checks, the same recipe, the supplier renamed and the fraud amount changed"))
        with agent_runner.app_server(db, w / "app", replay=True) as base:
            http = httpx.Client(base_url=base, timeout=60)
            items = http.get("/api/action-items").json()
            fire = next((i for i in items if i["key"].startswith("disruption:") and "fire" in i["title"].lower()), None)
            fraud = next((i for i in items if i["group"] == "trust" and "URGENT" in i["key"]), None)
            out.append(_check("the fire is found under the new name", bool(fire) and NEW in fire["title"], fire["title"] if fire else "no fire item"))
            out.append(_check("the fraud is held, the imitation named correctly", bool(fraud) and f"look-alike {NEW} domain" in fraud["title"], fraud["title"] if fraud else "no fraud item"))
            incident = next((i for i in items if i["key"].startswith("incident:")), None)
            out.append(_check("the supplier hit by a cyberattack is found under its new name, from the news + its schedule mail + its lines", bool(incident) and "Caldera" in incident["title"] and "cyberattack" in incident["title"],
                              incident["title"] if incident else "no incident item"))
            surfaces = {"action list": json.dumps(items)}
            for path in ("/api/suppliers", "/api/data-issues", "/api/people"):
                r = http.get(path)
                surfaces[path] = r.text if r.status_code == 200 else ""
            for it in (fire, fraud, incident):
                if it:
                    surfaces[it["key"]] = http.get(f"/api/action-items/{it['key']}").text
            leaks = sorted(k for k, v in surfaces.items() if OLD.lower() in v.lower() or "ruilian" in v.lower() or FRAUD_FROM.split(".")[0] in v)
            self_seen = {k: re.findall(r".{40}(?:yunzhan|187,420).{40}", v, re.I)[:2] for k, v in surfaces.items() if k in leaks}
            out.append(_check("nothing of the old month leaks into what the app says", not leaks, f"leaks in: {self_seen}" if leaks else f"{len(surfaces)} surfaces read; the old name and the old amount appear in none"))
            # the tariff, on numbers neither has seen: the oracle reads the changed files; the app reads its own build
            o = oracle.compute(data)
            tariff = http.get("/api/action-items/tariff:all").json()
            body = json.dumps(tariff)
            want = [f"{o['t1_owed']:,}"[:-4] if o["t1_owed"] > 9999 else str(o["t1_owed"])]
            import sqlite3
            from sqlalchemy import create_engine
            from sqlalchemy.orm import Session
            sys.path.insert(0, str(ROOT / "backend"))
            from app.domain.tariffs import service as tariffs
            with Session(create_engine(f"sqlite:///{db}", future=True)) as s:
                exps = tariffs.all_exposures(s)
            bad = []
            for e in exps:
                p = e.part.id
                if e.status == "china_listed":
                    for label, got, exp in (("owed", round(float(e.owed.usd)), o["owed_by_part"].get(p, 0)),
                                            ("conditional", round(float(e.conditional.usd)) if e.conditional else 0, o["conditional_by_part"].get(p, 0)),
                                            ("gross", round(float(e.gross.usd)), o["gross_by_part"].get(p, 0))):
                        if abs(got - exp) > 1:
                            bad.append(f"{p} {label}: app {got}, oracle {exp}")
                elif e.status == "unknown_origin" and abs(round(float(e.if_china.usd)) - o["if_china_by_part"].get(p, 0)) > 1:
                    bad.append(f"{p} if China: app {round(float(e.if_china.usd))}, oracle {o['if_china_by_part'].get(p, 0)}")
            out.append(_check("the app and the oracle agree on the three tariff amounts per part, on the changed data", not bad,
                              "; ".join(bad[:4]) if bad else f"{len(exps)} parts; owed {o['t1_owed'] + o['t2_owed']:,}, conditional {o['t1_conditional'] + o['t2_conditional']:,}, if China {o['if_china']:,}"))
            http.close()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evals.perturbed")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    res = run()
    for c in res:
        print(f"{'ok  ' if c['ok'] else 'FAIL'} {c['name']}: {c['detail']}")
    if a.json:
        a.json.write_text(json.dumps(res, indent=1))
    return 0 if all(c["ok"] for c in res) else 1


if __name__ == "__main__":
    sys.exit(main())
