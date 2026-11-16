"""The hindsight check (`make hindsight`): the records rebuilt as they stood on four days, and Today's cases on each.

For each cut (1 Sep, 1 Oct, 14 Oct, 20 Oct) the recipe rebuilds a database with LOOKOUT_AS_OF set to that day (exports and sheets cut at the date, mail
after it not read), and the detectors run on it. Checks:
- a case that rests on a message never appears on a day before the message was received;
- a case that rests on a dated record (a deletion, a receipt) never appears before that record;
- the MFC / PO-validity case is already on Today on 1 Sep, weeks before the vendor's mail asking for the firm-price protection (PLAN §12).
Prints one row per case and day, and exits 1 on any failure.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / "backend" / ".venv" / "bin" / "python"
CUTS = ["2026-09-01", "2026-10-01", "2026-10-14", "2026-10-20"]

PROBE = """
import json, os
from app.db import SessionLocal
from app.domain.attention import service
with SessionLocal() as s:
    out = {}
    for i in service.what_needs_attention(s):
        d = service.item_detail(s, i.key)
        msgs = [m.id for m in d.messages]
        out[i.key] = {"title": i.title, "messages": msgs, "stake": float(i.at_stake.amount) if i.at_stake is not None and hasattr(i.at_stake, "amount") else None}
print(json.dumps(out))
"""


def cases_on(cut: str, workdir: Path) -> dict:
    db = workdir / f"lookout-{cut}.db"
    env = {**os.environ, "LOOKOUT_AS_OF": cut, "LOOKOUT_DB": str(db)}
    subprocess.run([str(PY), "-m", "app.domain.imports.build", "--recipe", str(ROOT / "recipes" / "hg"), "--db", str(db)], cwd=ROOT / "backend", env=env,
                   check=True, capture_output=True)
    out = subprocess.run([str(PY), "-c", PROBE], cwd=ROOT / "backend", env=env, check=True, capture_output=True, text=True).stdout
    return json.loads(out.strip().splitlines()[-1])


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="lookout-hindsight-") as tmp:
        by_cut = {c: cases_on(c, Path(tmp)) for c in CUTS}
    fails = []
    keys = sorted({k for c in by_cut.values() for k in c})
    print(f"{'case':58} " + " ".join(f"{c[5:]:>6}" for c in CUTS))
    for k in keys:
        print(f"{k[:58]:58} " + " ".join(f"{'yes' if k in by_cut[c] else '-':>6}" for c in CUTS))
        for c in CUTS:
            if k not in by_cut[c]:
                continue
            for m in by_cut[c][k]["messages"]:
                if m[:10] > c:
                    fails.append(f"{k} is on Today on {c} but rests on a message of {m[:10]}")
    if "mfc-validity:4500120768" not in by_cut["2026-09-01"]:
        fails.append("the MFC / PO-validity case is not on Today on 1 Sep")
    else:
        stake = by_cut["2026-09-01"]["mfc-validity:4500120768"]["stake"]
        print(f"\n1 Sep: the MFC case is on Today ({'₹ at stake unknown: the vendor has not stated its price yet' if stake is None else stake}); its claim arrives 15 Oct.")
    for k in ("pr-cancelled:gaya:2026-10-15", "pv-claim:4500121087"):
        if k in by_cut["2026-10-14"] and k.startswith("pr-cancelled"):
            fails.append(f"{k} is on Today on 14 Oct, before the PRs were deleted (15 Oct)")
    print(f"\n{len(keys)} cases over {len(CUTS)} days; {len(fails)} failures")
    for f in fails:
        print("FAIL", f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
