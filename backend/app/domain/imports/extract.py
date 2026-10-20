"""`python -m app.domain.imports.extract <message id>`: ask a model to read one message into an extraction record file (not reviewed, not loaded)."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from app.domain.common.recipe import recipe_dir
from app.domain.imports.extraction import extract

ROOT = Path(__file__).resolve().parents[4]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("message_id")
    ap.add_argument("--db", type=Path, default=None, help="the built database to read the message from (default: the app's)")
    ap.add_argument("--recipe", type=Path, default=recipe_dir())
    ap.add_argument("--data", type=Path, default=ROOT / "data")
    ap.add_argument("--pdf", help="read this attached PDF (its file name under data/quotes/pdf/) instead of the message body")
    args = ap.parse_args(argv)
    from app.db import DB_PATH

    con = sqlite3.connect(args.db or DB_PATH)
    row = con.execute("select subject, body from messages where id = ?", (args.message_id,)).fetchone()
    if row is None:
        raise SystemExit(f"no message {args.message_id!r} in the database")
    path = extract(args.message_id, row[0], row[1], args.data, args.recipe / "extractions", source=f"pdf:{args.pdf}" if args.pdf else "email")
    print(f"wrote {path} (by: model, reviewed: false). Read it against the document, then set reviewed: true to load it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
