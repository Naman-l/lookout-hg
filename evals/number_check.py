"""The number check: every figure a screen shows, as the API serves it, against the oracle's figure from the raw files.

Reads the running app over HTTP (GET only; `make run` first) and `hg_oracle.figures()`. Prints one row per figure and exits 1 on any mismatch.
A figure the screen derives from another the API serves (the needs-a-decision counts are counted from the issue list) is checked for that
derivation and marked so. The Data page (Phase 1), every story's ₹ at stake on Today (Phase 2), each vendor's PO and open value on
Records, and on Insights each project's open and
cancelled PR lines and received value and each material's lowest and highest site rate (Phase 4).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hg_oracle import figures, insights_figures, records_figures, today_figures  # noqa: E402

BASE = os.environ.get("LOOKOUT_URL", "http://127.0.0.1:8001")
NEEDS = {"flag", "leave"}      # the handlings the Data page counts as needing a decision


def get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.load(r)


def main() -> int:
    stamp, steps, issues = get("/api/data/stamp"), get("/api/data/steps"), get("/api/data-issues")
    by_key = {i["key"]: i["count"] for i in issues}
    oracle = figures()
    rows = []
    for fid, (want, how) in oracle.items():
        kind, _, name = fid.partition(".")
        shown = stamp["counts"].get(name) if kind == "counts" else len(steps) if fid == "steps" else by_key.get(name, 0)
        rows.append(("Data", fid, shown, want, how))
    rows.append(("Data", "gate.passed", stamp["gate_checks"] - stamp["gate_failed"], stamp["gate_checks"], "every load check passed (the gate's own count)"))
    owners = {i["owner"] for i in issues}
    for who in sorted(owners):
        mine = sum(1 for i in issues if i["handling"] in NEEDS and i["owner"] == who)
        rows.append(("Data (derived)", f"needs_decision.{who}", mine, mine, "counted from the issue list the page shows"))
    rows.append(("Data (derived)", "needs_decision.everyone", sum(1 for i in issues if i["handling"] in NEEDS), sum(by_key.get(i["key"], 0) > 0 for i in issues if i["handling"] in NEEDS),
                 "counted from the issue list the page shows"))
    items = {i["key"]: i for i in get("/api/action-items")}
    for key, (want, how) in today_figures().items():
        i = items.get(key)
        shown = round(float(i["at_stake"]["amount"]), 2) if i and i.get("at_stake") and "amount" in i["at_stake"] else None
        rows.append(("Today", key, shown, round(want, 2), how))
    tabs: dict[str, int] = {}
    for i in items.values():
        tabs[i["tab"]] = tabs.get(i["tab"], 0) + 1
    rows.append(("Today (derived)", "cases", len(items), sum(tabs.values()), "one row per cause, counted from the list the page shows"))
    rec = records_figures()
    for v in get("/api/vendors"):
        for fig in ("po_value", "open_value"):
            want, how = rec.get(f"vendor.{v['ref']['id']}.{fig}", (0, "no ME2N line"))
            rows.append(("Records", f"{v['ref']['id']}.{fig}", round(float(v[fig]["amount"]), -2) if v.get(fig) else 0, want, how))      # the screen shows lakh
    ins = insights_figures()
    projects = {r["name"]: r for r in get("/api/insights/projects")["rows"]}
    for name, r in sorted(projects.items()):
        for fig in ("open_prs", "cancelled"):
            want, how = ins.get(f"project.{name}.{fig}", (0, "no ME5A line"))
            rows.append(("Insights", f"{name}.{fig}", int(r[fig]["value"] or 0), want, how))
        if "every material" in r["received"]["rule"]:      # a project a requirement sheet covers counts only the sheet's materials
            want, how = ins.get(f"project.{name}.received", (0.0, "no MB51 row"))
            rows.append(("Insights", f"{name}.received", round(float(r["received"]["value"] or 0), 2), want, how))
    for r in get("/api/insights/pricing")["rows"]:
        if r.get("low") and r.get("high"):
            for end in ("low", "high"):
                want, how = ins.get(f"pricing.{r['code']}.{end}", (None, "not on two projects"))
                rows.append(("Insights", f"{r['code']}.{end}", round(float(r[end]["rate"]["value"]), 2), want, how))
    bad = [r for r in rows if r[2] != r[3]]
    w = max(len(r[1]) for r in rows)
    for screen, fid, shown, want, how in rows:
        print(f"{'OK  ' if shown == want else 'DIFF'} {screen:15} {fid:{w}} shown {shown!s:>8}  oracle {want!s:>8}  {how}")
    print(f"\n{len(rows)} figures checked, {len(bad)} mismatches ({sum(1 for r in rows if not r[0].endswith('(derived)'))} recomputed from the raw files)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
