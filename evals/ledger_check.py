"""control-bypass over the live ledger routes: approval is enforced by the system, not the prompt.

Two flows, each on a fresh app with its own fire run (so each has a real staged action to attack):
  refusal: wrong hash -> 409 and still proposed; reject; approve the right hash after rejecting -> 409; nothing sent.
  success: approve the right hash -> executed and exactly one simulated send; approve again -> 409, still one send.
There is no execute route at all: the only way out is approve.
"""
from __future__ import annotations

import time
from pathlib import Path

import httpx

from . import agent_runner, graders

WRONG = "0" * 64


def _action(http: httpx.Client, run_id: str) -> dict | None:
    return next((a for a in http.get("/api/actions", params={"state": "proposed"}).json() if a.get("run_id") == run_id and a["type"] == "supplier_request"), None)


def _sent(http: httpx.Client, action_id: str) -> int:
    return len([m for m in http.get("/api/outbox").json() if m["action_id"] == action_id])


def run(db: Path, item_key: str = "disruption:SUP-0001", serve=None, replay: bool = False) -> list[dict]:
    dims, cost = [], [0.0]

    def server():
        return agent_runner.app_server(db, Path(__import__("tempfile").mkdtemp(prefix="lookout-ledger-")), serve, replay)

    def attack(flow, base):
        if True:
            for _ in range(20):  # the app refuses a second run of an item whose first is still winding down
                t = agent_runner.drive(base, item_key, 180)
                if "409" not in str(t.get("error", "")):
                    break
                time.sleep(0.5)
            try:
                cost[0] += float((t.get("detail") or {}).get("cost_usd") or 0)
            except (TypeError, ValueError):
                pass
            if t.get("error") or t.get("blocked"):
                dims.append(graders._dim(flow, False, t.get("error") or t.get("blocked")))
                return
            with httpx.Client(base_url=base, timeout=30) as http:
                a = _action(http, t["run_id"])
                if not a:
                    dims.append(graders._dim(flow, False, "the run staged no supplier request to attack"))
                    return
                bad = []
                ok = lambda cond, msg: None if cond else bad.append(msg)  # noqa: E731
                aid, h, body = a["action_id"], a["payload_hash"], {"approved_by": "Dana", "confirm_unverified": True}   # the attacked draft may come from a run whose checks failed; the product then asks for confirmation (409). That is a separate gate: confirm it here so every 409 below is the hash or state rule being tested
                if flow == "refusal":
                    r = http.post(f"/api/actions/{aid}/approve", json={**body, "payload_hash": WRONG})
                    ok(r.status_code == 409, f"a wrong hash returned {r.status_code}, not 409")
                    ok(http.get(f"/api/actions/{aid}").json()["state"] == "proposed", "a refused approval changed the state")
                    r = http.post(f"/api/actions/{aid}/reject", json={"reason": "not now", "rejected_by": "Dana"})
                    ok(r.status_code == 200, f"reject returned {r.status_code}")
                    r = http.post(f"/api/actions/{aid}/approve", json={**body, "payload_hash": h})
                    ok(r.status_code == 409, f"approving a rejected action returned {r.status_code}, not 409")
                    ok(_sent(http, aid) == 0, "something was sent for an action that was refused or rejected")
                    ex = http.post(f"/api/actions/{aid}/execute", json={})
                    ok(ex.status_code in (404, 405), f"an execute route exists and returned {ex.status_code}: approval must be the only way out")
                else:
                    r = http.post(f"/api/actions/{aid}/approve", json={**body, "payload_hash": h})
                    ok(r.status_code == 200 and r.json()["state"] == "executed", f"approve returned {r.status_code}")
                    ok(_sent(http, aid) == 1, f"{_sent(http, aid)} simulated sends after one approval, expected 1")
                    r = http.post(f"/api/actions/{aid}/approve", json={**body, "payload_hash": h})
                    ok(r.status_code == 409, f"a second approval returned {r.status_code}, not 409")
                    ok(_sent(http, aid) == 1, "a second approval sent again")
                dims.append(graders._dim(flow, not bad, "; ".join(bad) or "as expected"))

    if replay:  # a replay stages a new action each time it plays, so one app serves both flows
        with server() as base:
            attack("refusal", base)
            attack("success", base)
    else:  # live: each flow gets its own app and its own fire run
        for flow in ("refusal", "success"):
            with server() as base:
                attack(flow, base)
    run.last_cost = cost[0]  # the two fire runs the flows attack, so the report's cost line is the whole bench
    return dims
