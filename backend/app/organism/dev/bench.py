"""`python -m app.organism.dev.bench [--n 3] [--record] [--only fire,tariff]`: run each workflow on the real data and print the speed and cost table.

Each run uses a scratch copy of the built database and the live model. Wall time is the run's own clock to `run.finished`; the Reviewer's grade
follows delivery, so its time and cost are shown apart. With --record the last good run of each workflow is saved as the no-key fixture."""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
from pathlib import Path

from .. import recordings
from ..runs import store
from ..workflows.ask import run_ask
from ..workflows.import_file import run_import
from ..workflows.work_item import run_workflow

FIXTURES = Path(__file__).resolve().parents[1] / "domain/imports/steward/fixtures"
BCX = "2026-09-02_Baycrest_Connectors_is_now_BCX_Interconnect_-_2027_quotation_BCX-Q-2609"
VPM = "2026-09-24_Quotation_VPM-Q-260924_-_BLDC_motor_equivalent_to_YZ-BL86-48-400"
FM = "2026-09-22_NOTICE_OF_FORCE_MAJEURE_-_Shenzhen_Yunzhan_Precision_Motor_Co_Ltd"
Q_FIRE = "What does the Yunzhan fire cost us, and who else could make the motor?"
Q_TARIFF = "Which tariff exposure should Marcus look at first?"
Q_STOCK = "How many HR-40110 do we have on the shelf right now?"
Q_WHERE = "Where is HR-40110?"
Q_BUILD = "Is the Tern October build clear?"

# label, kind, how to run: ("item", key) | ("ask", question) | ("import", file)
WORKFLOWS = [
    ("Fire (Yunzhan)", "item", "disruption:SUP-0001"), ("Tariff, one part", "item", "tariff:HR-40110"), ("Tariff, portfolio", "item", "tariff:all"),
    ("Unknown origin", "item", "unknown:HR-40220"), ("Deadline (price lock)", "item", "deadline:SUP-0001:2026-10-13"), ("Compare quotes", "item", "compare:HR-40110"),
    ("Trust item (by code)", "item", "trust:2026-09-12_Spot_offer_-_NG6603-QFN48_in_stock_ships_today"), ("Triage a message", "item", f"triage:{BCX}"),
    ("Triage a new sender", "item", f"triage:{VPM}"), ("Reply to a notice", "item", f"reply:{FM}"), ("Ask: cost and alternatives", "ask", Q_FIRE),
    ("Ask: who first", "ask", Q_TARIFF), ("Ask: not in the data", "ask", Q_STOCK), ("Ask: where is it", "ask", Q_WHERE), ("Ask: is the build clear", "ask", Q_BUILD), ("Data steward (drifted export)", "import", str(FIXTURES / "purchase_orders_export_2026-10.csv")),
]


def message_workflows():
    """A triage for every message a reviewer can open, and a reply for those from a supplier on file. Blocked senders are answered by code and need no recording."""
    from .. import services as _services  # noqa: PLC0415
    from ... import db as _db  # noqa: PLC0415

    svc = _services.get(str(_db.DB_PATH))
    try:
        out = []
        for m in sorted(svc.inbox.list_messages(), key=lambda x: x.date):
            if not svc.inbox.trust(m.ref.id).may_act:
                continue
            label = f"{m.date} {m.ref.id[11:50]}"
            out.append((f"Triage {label}", "item", f"triage:{m.ref.id}"))
            if m.supplier:
                out.append((f"Reply {label}", "item", f"reply:{m.ref.id}"))
        return out
    finally:
        svc.close()


async def once(kind: str, spec: str):
    db = store.scratch_copy("lookout-bench-")
    if kind == "ask":
        r = await run_ask(spec, db_path=db)
    elif kind == "import":
        r = await run_import(Path(spec).name, db_path=db, incoming_dir=Path(spec).parent)
    else:
        r = await run_workflow(spec, db_path=db)
    row = store.read_run(db, r.run_id)
    review = sum(e.payload.get("cost_usd") or 0 for e in r.ctx.recorder.events if e.type == "review.result")
    return db, r, row, review


async def main(n: int, record: bool, only: set[str], messages: bool = False) -> int:
    lines = []
    for label, kind, spec in (message_workflows() if messages else WORKFLOWS):
        if only and not any(o in label.lower() for o in only):
            continue
        walls, firsts, tokens, costs, reviews, calls, oks, last_good = [], [], [], [], [], [], 0, None
        count = 1 if kind == "item" and spec.startswith("trust:") else n
        for _ in range(count):
            db, r, row, review = await once(kind, spec)
            walls.append(r.wall_ms / 1000)
            firsts.append((r.first_step_ms or 0) / 1000)
            if r.ctx.recorder.first_token_ms is not None:
                tokens.append(r.ctx.recorder.first_token_ms / 1000)
            costs.append((row["cost_usd"] or 0) - review)
            reviews.append(review)
            calls.append(row["tool_calls"] or 0)
            if r.status == "ok":
                oks += 1
                last_good = (db, r.run_id)
            else:  # say why: a run that does not pass is the most useful thing a bench can show
                import json as _json  # noqa: PLC0415

                why = _json.loads(row["verifier_json"])["failures"] if row["verifier_json"] else [r.error or r.status]
                print(f"  ! {label}: {r.status}: " + " | ".join(why)[:400], flush=True)
                dump = Path("/tmp") / f"lookout-bench-failed-{abs(hash(label)) % 10000}.txt"
                dump.write_text("\n".join(f"{e.t_ms / 1000:6.1f}s {e.agent_label:<15} {e.type:<16} {e.summary[:140]} {e.payload.get('gate', '')} {e.payload.get('gate_reason', '')}" for e in r.ctx.recorder.events)
                                + "\nchildren: " + str({k: v.run_id for k, v in r.ctx.children.items()}) + f"\nhandoffs: {list(r.ctx.handoffs)} seen: {sorted(r.ctx.handoffs_seen)} delegated: {r.ctx.delegated}\n")
                print(f"    timeline: {dump}", flush=True)
        if record and last_good:
            recordings.save(*last_good)
        med = lambda xs: statistics.median(xs) if xs else float("nan")  # noqa: E731
        lines.append(f"| {label} | {count} | {oks}/{count} | {med(firsts):.1f} | {med(tokens):.1f} | {med(walls):.0f} ({max(walls):.0f}) | {med(costs):.3f} | {med(reviews):.3f} | {med(calls):.0f} |")
        print(lines[-1], flush=True)
    print("\n| Workflow | Runs | Passed | First step (s) | First model token (s) | Wall, median (max) s | Cost USD | Review USD (after delivery) | Tool calls |")
    print("|---|---|---|---|---|---|---|---|---|")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--messages", action="store_true", help="triage every message and reply to each supplier message (use --n 1 --record)")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.n, a.record, {x.strip().lower() for x in a.only.split(",") if x.strip()}, a.messages)))
