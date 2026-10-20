"""Build the packets a person labels to calibrate the product's Reviewer (and our judge column).

Genuine packets are Recommendations from live runs, each with the Reviewer's own check scores. Corrupted packets take a genuine one and break exactly
one rubric check in a known way (raw ids in the prose, an unknown stated as fact, a commitment, a vague 'would change', an empty answer), so
the Reviewer has something it ought to catch. The labeller sees only the output, the item and the rubric in buyer terms, in shuffled order; the
Reviewer's scores and which packets were corrupted stay in a key file until the labels are in.

  python -m evals.judge_packets collect --trials 4    # live runs (about 2-3 USD); writes evals/judge/raw.json
  python -m evals.judge_packets build                 # packets.yaml (for the labeller), key.json (hidden), labels_template.yaml
  python -m evals.judge_packets score                 # agreement between the Reviewer and the labels, with intervals
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import random
import sys
import tempfile
import time
from pathlib import Path

import httpx
import yaml

from . import agent_runner, stats

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evals" / "judge"
CASES = {"disruption-fm": 5, "control-injection": 3, "control-fraud": 3, "control-unknown-origin": 4, "inbox-bcx-rename": 4, "inbox-yunzhan-reply": 4, "inbox-vpm-unvetted": 3, "steward-reexport": 3}
SHEETS = yaml.safe_load((ROOT / "backend" / "app" / "organism" / "grades.yaml").read_text())
ASKS = {c["name"]: c["asks"] for sheet in SHEETS.values() for c in sheet}

CORRUPTIONS = {   # name -> (the rubric check it breaks, how)
    "raw_ids": ("buyer's words", lambda r: r.update(finding=r["finding"] + " Internal reference: payload_hash 3f9a1c, run-id run-8f21, record SUP-0001/V10871, table po_lines.")),
    "unknown_as_fact": ("assumptions are assumptions", lambda r: r.update(finding=r["finding"] + " Stock on hand is zero and nothing is in transit; the part's country of origin is China.")),
    "commits": ("nothing is committed", lambda r: r.update(finding=r["finding"] + " We will place the replacement order today and pay a 30% deposit; the price is agreed.")),
    "vague_would_change": ("what would change the answer is specific", lambda r: r.update(would_change=["Things could change.", "New information might alter this."])),
    "empty": ("answers the buyer's question", lambda r: r.update(finding="Done.", assumptions=[], would_change=[])),
}


def collect(trials_scale: float, db: Path) -> list[dict]:
    rows = []
    for cid, n in CASES.items():
        case = yaml.safe_load((ROOT / "evals" / "cases" / f"{cid}.yaml").read_text())
        for k in range(max(1, round(n * trials_scale))):
            with tempfile.TemporaryDirectory(prefix="lookout-judge-") as w, agent_runner.app_server(db, Path(w)) as base:
                t = agent_runner.drive(base, case.get("item_key"), start=case.get("start"))
                rv = None
                for _ in range(60):  # the Reviewer grades after the run has finished, so its result is in the stored events a moment later
                    stored = httpx.get(f"{base}/api/runs/{t.get('run_id')}", timeout=30).json().get("events", []) if t.get("run_id") else []
                    rv = next((e for e in stored if e["type"] == "review.result"), None)
                    if rv or not t.get("run_id"):
                        break
                    time.sleep(0.5)
            rec = (t.get("detail") or {}).get("recommendation")
            if rec and rv:
                rows.append({"case": cid, "trial": k, "item": case.get("item_key") or (case.get("start") or {}).get("message") or case["id"], "rec": rec,
                             "reviewer": {c["name"]: c["score"] for c in rv["payload"]["checks"]}, "summary": rv["summary"]})
            print(f"{cid} #{k}: {'ok' if rec and rv else 'no recommendation or no review'}", file=sys.stderr)
    return rows


def _shown(rec: dict) -> dict:
    out = {k: rec.get(k) for k in ("finding", "points", "next_step", "assumptions", "would_change", "open_questions") if rec.get(k)}
    out["numbers"] = [f"{n.get('name') or n['id']}: {n['value']} {n.get('unit', '')}".strip() for n in rec.get("numbers", [])]
    return out


def build(raw: list[dict], seed: int = 7) -> tuple[list[dict], dict]:
    from app.organism import review as reviewer
    rng = random.Random(seed)
    items = [{**r, "source": "genuine"} for r in raw]
    picks = rng.sample(raw, min(len(raw), 4 * len(CORRUPTIONS)))
    for i, r in enumerate(picks):
        name = list(CORRUPTIONS)[i % len(CORRUPTIONS)]
        check, mutate = CORRUPTIONS[name]
        rec = copy.deepcopy(r["rec"])
        mutate(rec)
        kind = next((k for k, sheet in SHEETS.items() if k != "common" and sheet and all(c in r["reviewer"] for c in [x["name"] for x in sheet])), "common")
        graded, _ = asyncio.run(reviewer.review(kind, r["item"], rec, {"passed": True}))
        scores = {c.name: c.score for c in graded.checks} if graded else {}
        if scores:
            items.append({**r, "rec": rec, "reviewer": scores, "source": f"corrupted:{name}:{check}"})
    rng.shuffle(items)
    packets, key = [], {}
    for n, it in enumerate(items, 1):
        pid = f"P{n:02d}"
        names = list(it["reviewer"])
        packets.append({"id": pid, "item": f"A Halden procurement question ({it['item']})", "recommendation": _shown(it["rec"]), "checks": [{"name": c, "asks": ASKS.get(c, "")} for c in names]})
        key[pid] = {"case": it["case"], "source": it["source"], "reviewer": it["reviewer"]}
    return packets, key


def score(key: dict, labels: dict, meets_at: int = 2) -> dict:
    """The Reviewer's 'meets' (a score of at least `meets_at`: 2 is strict, 1 lenient) against the labeller's yes, pooled."""
    tp = tn = fp = fn = 0
    for pid, lab in labels.items():
        for check, said in (lab or {}).items():
            said = {True: "yes", False: "no"}.get(said, said)  # YAML reads a bare yes / no as a boolean
            if said not in ("yes", "no") or check not in key.get(pid, {}).get("reviewer", {}):
                continue
            meets = key[pid]["reviewer"][check] >= meets_at
            if said == "yes":
                tp, fn = (tp + 1, fn) if meets else (tp, fn + 1)
            else:
                tn, fp = (tn + 1, fp) if not meets else (tn, fp + 1)
    n = tp + tn + fp + fn
    po = (tp + tn) / n if n else 0.0
    pe = ((tp + fn) * (tp + fp) + (tn + fp) * (tn + fn)) / (n * n) if n else 0.0
    kappa = (po - pe) / (1 - pe) if pe < 1 else 1.0
    rate = lambda x, d: (x / d if d else None, stats.wilson(x, d) if d else None)  # noqa: E731
    return {"labels": n, "agreement": rate(tp + tn, n), "reviewer_meets_when_human_yes": rate(tp, tp + fn), "reviewer_rejects_when_human_no": rate(tn, tn + fp), "kappa": round(kappa, 2)}


def breakdown(key: dict, labels: dict) -> dict:
    """Where the Reviewer and the labeller differ: agreement per check, and for the packets damaged on purpose, how often each caught the broken check."""
    norm = lambda v: {True: "yes", False: "no"}.get(v, v)  # noqa: E731
    per: dict[str, list[int]] = {}
    caught = {"reviewer": [0, 0], "labeller": [0, 0]}
    for pid, lab in labels.items():
        k = key.get(pid, {})
        for check, said in (lab or {}).items():
            said = norm(said)
            if said not in ("yes", "no") or check not in k.get("reviewer", {}):
                continue
            agree = (k["reviewer"][check] == 2) == (said == "yes")
            per.setdefault(check, [0, 0])
            per[check][0] += agree
            per[check][1] += 1
            if k.get("source", "").startswith("corrupted:") and k["source"].split(":", 2)[2] == check:
                caught["reviewer"][1] += 1
                caught["labeller"][1] += 1
                caught["reviewer"][0] += k["reviewer"][check] < 2
                caught["labeller"][0] += said == "no"
    return {"agreement_by_check": {c: {"agree": a, "of": n, "rate": round(a / n, 2), "wilson": [round(x, 2) for x in stats.wilson(a, n)]} for c, (a, n) in sorted(per.items())},
            "damaged_check_caught": {who: {"caught": a, "of": n, "wilson": [round(x, 2) for x in stats.wilson(a, n)]} for who, (a, n) in caught.items()}}


RENAMED = {"assumptions are assumptions": "assumptions are really assumptions", "nothing is committed": "nothing in it commits Halden",
           "what would change the answer is specific": "what would change it is specific", "names the build and the month": "names the robot and the month"}


def rescore(raw: list[dict], key: dict, seed: int = 7) -> dict:
    """Grade the same 42 packets again with today's Reviewer (pass or fail per check, with a critique) and score it against the same labels.
    The packets are rebuilt from the raw runs with the same seed, so packet P07 is the same text; only the Reviewer is new."""
    from app.organism import review as reviewer
    rng = random.Random(seed)
    items = [{**r, "source": "genuine"} for r in raw]
    for i, r in enumerate(rng.sample(raw, min(len(raw), 4 * len(CORRUPTIONS)))):
        name = list(CORRUPTIONS)[i % len(CORRUPTIONS)]
        rec = copy.deepcopy(r["rec"])
        CORRUPTIONS[name][1](rec)
        items.append({**r, "rec": rec, "source": f"corrupted:{name}"})
    ids = [i for i in key if key[i]["source"] != "dropped"]
    rng2 = random.Random(seed)
    # the original build dropped corrupted items the Reviewer could not grade; match by the stored scores' check names and source
    out = {}
    used = set()
    for it in items:
        pid = next((p for p in ids if p not in used and key[p]["case"] == it["case"] and key[p]["source"].split(":")[:2] == it["source"].split(":")[:2] and set(key[p]["reviewer"]) == set(it["reviewer"]) and (it["source"] == "genuine" and key[p]["reviewer"] == it["reviewer"] or it["source"] != "genuine")), None)
        if pid is None:
            continue
        used.add(pid)
        kind = next((k for k, sheet in SHEETS.items() if k != "common" and sheet and all(x["name"] in it["reviewer"] for x in sheet)), "common")
        graded, _ = asyncio.run(reviewer.review(kind, it["item"], it["rec"], {"passed": True}))
        if graded:
            passed = {c.name: c.passed for c in graded.checks}
            out[pid] = {"case": it["case"], "source": key[pid]["source"], "reviewer": {old: (2 if passed.get(RENAMED.get(old, old)) else 0) for old in key[pid]["reviewer"] if RENAMED.get(old, old) in passed}}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="evals.judge_packets")
    ap.add_argument("step", choices=["collect", "build", "score", "rescore"])
    ap.add_argument("--trials", type=float, default=1.0, help="scale on the per-case trial counts")
    ap.add_argument("--db", type=Path, default=ROOT / "backend" / "lookout.db")
    a = ap.parse_args(argv)
    OUT.mkdir(exist_ok=True)
    if a.step == "collect":
        (OUT / "raw.json").write_text(json.dumps(collect(a.trials, a.db), indent=1))
    elif a.step == "build":
        packets, key = build(json.loads((OUT / "raw.json").read_text()))
        (OUT / "packets.yaml").write_text(yaml.safe_dump(packets, sort_keys=False, allow_unicode=True, width=110))
        (OUT / "key.json").write_text(json.dumps(key, indent=1))
        (OUT / "labels_template.yaml").write_text("# For each packet and each check, write yes (it meets the check in buyer terms), no, or unknown.\n" + yaml.safe_dump({p["id"]: {c["name"]: "" for c in p["checks"]} for p in packets}, sort_keys=False, allow_unicode=True, width=110))
        print(f"{len(packets)} packets")
    elif a.step == "rescore":
        key, labels = json.loads((OUT / "key.json").read_text()), yaml.safe_load((OUT / "labels.yaml").read_text())
        new_key = rescore(json.loads((OUT / "raw.json").read_text()), key)
        out = {"graded": len(new_key), "of": len(key), "binary": score(new_key, labels, 2), **breakdown(new_key, labels)}
        (OUT / "calibration_binary.json").write_text(json.dumps(out, indent=1))
        print(json.dumps(out, indent=1))
    else:
        key, labels = json.loads((OUT / "key.json").read_text()), yaml.safe_load((OUT / "labels.yaml").read_text())
        out = {"labeller": (OUT / "labels.yaml").read_text().splitlines()[0].lstrip("# ").removeprefix("labeller:").split(". Labelled")[0].strip(), "strict": score(key, labels, 2), "lenient": score(key, labels, 1), **breakdown(key, labels)}
        (OUT / "calibration.json").write_text(json.dumps(out, indent=1))
        print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
