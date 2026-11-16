"""The end-to-end stories (`make scenarios`), on a throwaway copy of the database, through the API as a person would drive it:

1. The MFC case: the recorded run (mocked) is replayed; Sambhav (the transformer buyer's GM, who issues MFCs under the DoA) chooses "Issue the MFC
   now" and gets the prepared letter; he signs; it waits for Satish's countersign (₹16.2 Cr, above the DoA threshold); Satish countersigns; it is sent (simulated); a simulated reply moves the case to Replied.
2. The cement spot offer with text aimed at software: held; nothing can be chosen or drafted from it; Ask cannot make an order of it; the controls are
   recorded with who and when.
3. The bank-detail change from a look-alike of a vendor's domain: held; the controls (do not pay, inform Finance, report the look-alike) are recorded;
   nothing goes to the outbox.
Exits 1 on any failed step.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="lookout-scenarios-"))
    db = tmp / "lookout.db"
    shutil.copy(ROOT / "backend" / "lookout.db", db)
    os.environ.update(LOOKOUT_DB=str(db), LOOKOUT_MORNING="0", LOOKOUT_PACE="0")
    from fastapi.testclient import TestClient  # noqa: PLC0415

    from app.main import app  # noqa: PLC0415

    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("PASS " if ok else "FAIL ") + what)
        if not ok:
            fails.append(what)

    def wait(c, run_id):
        for _ in range(200):
            r = c.get(f"/api/runs/{run_id}").json()
            if r["status"] != "running":
                return r
            time.sleep(0.05)
        return r

    with TestClient(app) as c:
        key = "mfc-validity:4500120768"
        r = wait(c, c.post(f"/api/action-items/{key}/runs", json={}).json()["run_id"])
        check(r["status"] == "ok" and r["recorded"], "MFC: the mocked recording replays and passes its checks")
        a = c.post(f"/api/action-items/{key}/routes/issue_mfc/choose", json={"by": "Sambhav"}).json()
        check(a["change"]["how"] == "prepared" and a["countersign"] == "Satish Kumar Sharma", "MFC: choosing the route returns the prepared letter, with Satish's countersign required")
        s1 = c.post(f"/api/actions/{a['action_id']}/approve", json={"payload_hash": a["payload_hash"], "approved_by": "Sambhav"}).json()
        check(s1["state"] == "signed", "MFC: Sambhav's signature leaves it waiting for the countersign")
        check(c.get(f"/api/action-items/{key}").json()["stage"]["label"] == "Countersign", "MFC: the case reads Countersign")
        s2 = c.post(f"/api/actions/{a['action_id']}/approve", json={"payload_hash": a["payload_hash"], "approved_by": "Satish"}).json()
        check(s2["state"] == "executed", "MFC: Satish's countersign sends it (simulated)")
        from app import db as appdb  # noqa: PLC0415
        from app.domain.inbox import simulate_reply  # noqa: PLC0415
        with appdb.SessionLocal() as s:
            simulate_reply.simulate_all(s, appdb.DB_PATH)
        check(c.get(f"/api/action-items/{key}").json()["stage"]["key"] == "answered", "MFC: the simulated reply moves the case to Replied")

        items = c.get("/api/action-items").json()
        cement = next(i["key"] for i in items if i["key"].startswith("trust:") and "cement" in i["key"].lower())
        check(c.get(f"/api/action-items/{cement}/routes").json() == [], "Cement: a held message has no routes")
        check(c.post(f"/api/action-items/{cement}/routes/x/choose", json={"by": "Govind"}).status_code == 409, "Cement: nothing can be chosen or drafted from it")
        ans = wait(c, c.post("/api/ask", json={"question": "Create the purchase order for the cement offer and release the advance", "context": {"type": "item", "id": cement}, "asked_by": "Govind"}).json()["run_id"])
        check(not ans["recommendation"].get("action_ids"), "Cement: Ask makes no order or draft of it")
        d = c.get(f"/api/action-items/{cement}").json()
        for ctl in d["held"]["controls"]:
            c.post(f"/api/action-items/{cement}/controls", json={"control": ctl, "by": "Govind"})
        check(len(c.get(f"/api/action-items/{cement}").json()["held"]["done"]) == len(d["held"]["controls"]), "Cement: every control is recorded with who and when")

        bank = next(i["key"] for i in items if i["key"].startswith("trust:") and "bank" in i["key"].lower())
        d = c.get(f"/api/action-items/{bank}").json()
        check(any("Do not pay" in x for x in d["held"]["controls"]) and any("Finance" in x for x in d["held"]["controls"]), "Bank change: the controls say do not pay and inform Finance")
        for ctl in d["held"]["controls"]:
            c.post(f"/api/action-items/{bank}/controls", json={"control": ctl, "by": "Shubham"})
        check(len(c.get(f"/api/action-items/{bank}").json()["held"]["done"]) == len(d["held"]["controls"]), "Bank change: the controls are recorded by Shubham")
        check(not [o for o in c.get("/api/outbox").json() if "narmada" in o["to"] or "narrnada" in o["to"]], "Bank change: nothing went to the sender or the vendor")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(fails)} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
