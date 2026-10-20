"""`python -m app.organism.dev.fire <item_key>`: work one item end to end on the real wiring and print the story.

Prints every step as it streams, then the Recommendation, the verifier's verdict, the staged drafts and the
cost. Exit code 0 only if the verifier passed, nothing was sent, and Lookout itself had no refused calls.
"""

from __future__ import annotations

import asyncio
import sys

from ...domain.actions import ledger
from ..runs import store
from ..runs.events import Recorder
from .smoke import render
from ..workflows.work_item import run_workflow


async def main(item_key: str, question: str | None = None, import_file: str | None = None) -> int:
    db = store.scratch_copy("lookout-fire-")
    rec = Recorder("run-fire", db)
    q = rec.subscribe()

    async def printer():
        while True:
            _, e = await q.get()
            line = render(e)
            if line:
                print(line, flush=True)

    p = asyncio.create_task(printer())
    if import_file:
        from pathlib import Path

        from ..workflows.import_file import run_import

        result = await run_import(Path(import_file).name, db_path=db, incoming_dir=Path(import_file).parent, run_id="run-fire", recorder=rec)
    elif question:
        from ..workflows.ask import run_ask

        result = await run_ask(question, db_path=db, context=None, run_id="run-fire", recorder=rec)
    else:
        result = await run_workflow(item_key, db_path=db, run_id="run-fire", recorder=rec)
    await asyncio.sleep(0.05)
    p.cancel()

    row = store.read_run(db, "run-fire")
    print("\n--- Recommendation ---")
    if row["recommendation_json"]:
        from ..schemas import Recommendation, VerifierResult

        r = Recommendation.model_validate_json(row["recommendation_json"])
        v = VerifierResult.model_validate_json(row["verifier_json"])
        print(r.finding)
        for n in r.numbers:
            print(f"  {n.value:>8} {n.unit:<4} {n.name}  [{n.id}]")
        for a in r.assumptions:
            print(f"  assumes: {a}")
        for w in r.would_change:
            print(f"  would change if: {w}")
        for u in r.open_questions:
            print(f"  open question · ask {u.owner}: {u.question}")
        print(f"\nverifier: {'PASSED' if v.passed else 'DID NOT PASS'} · {v.numbers_from_tools} of {v.numbers_checked} numbers from tools · {v.open_questions_with_owner} open questions with an owner")
        for f in v.failures:
            print(f"  FAILED {f}")
    else:
        from ..schemas import VerifierResult

        v = VerifierResult.model_validate_json(row["verifier_json"]) if row["verifier_json"] else None
        print("(none)")
        for f in (v.failures if v else []):
            print(f"  FAILED {f}")
    drafts = ledger.list_actions(db)
    for a in drafts:
        if a.type == "note":
            print(f"\n--- Logged {a.action_id} [{a.state}] ---\n{a.body}")
            continue
        print(f"\n--- Draft {a.action_id} [{a.state}] to {a.recipient} ---\n{a.subject}\n{a.body}")
    lookout_denied = [e for e in rec.events if e.type == "tool.called" and e.agent == "lookout" and e.payload.get("gate") == "denied"]
    print(f"\nstatus {result.status} · {result.wall_ms / 1000:.1f} s · first step {result.first_step_ms} ms · first model token {rec.first_token_ms} ms · cost {result.cost_usd} USD · "
          f"tool calls {row['tool_calls']} (refused {row['denied_calls']}) · Lookout-level refusals {len(lookout_denied)} · outbox {len(ledger.outbox(db))}")
    from ..workflows.work_item import ROLL_UPS

    nothing_to_draft = item_key.startswith(("trust:", "import", "triage:", "compare:")) or item_key in ROLL_UPS  # a trust item or a portfolio view ends with no draft
    ok = bool(v and v.passed) and not ledger.outbox(db) and not lookout_denied and (not drafts if nothing_to_draft else bool(drafts))
    return 0 if ok else 1


if __name__ == "__main__":
    # python -m app.organism.dev.fire <item_key>   or   python -m app.organism.dev.fire ask "a question"
    if len(sys.argv) < 2:
        sys.exit("usage: python -m app.organism.dev.fire <item key> | ask \"<question>\" | import <file>   (no default: name the item)")
    if len(sys.argv) > 2 and sys.argv[1] == "import":
        sys.exit(asyncio.run(main("import", import_file=sys.argv[2])))
    if len(sys.argv) > 2 and sys.argv[1] == "ask":
        sys.exit(asyncio.run(main("ask", sys.argv[2])))
    sys.exit(asyncio.run(main(sys.argv[1])))
