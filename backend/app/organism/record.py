"""`python -m app.organism.record <item_key>`: run the item live and save the run as a fixture under
recordings/, whatever status it ended with. Run it after the data or the prompts change, and commit the result."""

from __future__ import annotations

import asyncio
import sys

from . import recordings
from .runs import store
from .workflows.work_item import run_workflow


async def main(item_key: str, import_file: str | None = None, question: str | None = None) -> int:
    db = store.scratch_copy("lookout-record-")
    if import_file:  # the Data steward on a file: recorded under import:<file name>
        from pathlib import Path

        from .workflows.import_file import run_import

        result = await run_import(Path(import_file).name, db_path=db, incoming_dir=Path(import_file).parent, run_id="run-recorded")
    elif question:
        from .workflows.ask import run_ask

        result = await run_ask(question, db_path=db, run_id="run-recorded")
    else:
        result = await run_workflow(item_key, db_path=db, run_id="run-recorded")
    # Every run is recorded as it ended, pass or fail: a set that keeps only the passes would make the replays a selection.
    print(f"recorded {recordings.save(db, result.run_id)}  ({result.status}, {result.wall_ms / 1000:.1f} s, {(result.cost_usd or 0):.3f} USD)")
    return 0 if result.status in ("ok", "did_not_pass") else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python -m app.organism.record <item key> | ask \"<question>\" | import <file>   (no default: name the item)")
    if len(sys.argv) > 2 and sys.argv[1] == "ask":
        sys.exit(asyncio.run(main("ask", question=sys.argv[2])))
    if len(sys.argv) > 2 and sys.argv[1] == "import":
        sys.exit(asyncio.run(main("import", sys.argv[2])))
    sys.exit(asyncio.run(main(sys.argv[1])))
