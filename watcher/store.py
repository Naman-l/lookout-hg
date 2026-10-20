"""Read side of the Watcher: the NDJSON files `app.watcher.emit` writes, one per UTC day."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]


def events_dir() -> Path:
    return Path(os.environ.get("LOOKOUT_EVENTS_DIR", ROOT / "watcher" / "events"))


def read_all(directory: Path | None = None) -> Iterator[dict]:
    """Every event, oldest first. A malformed line is reported as an event, never silently dropped."""
    d = directory or events_dir()
    for f in sorted(d.glob("*.ndjson")):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                yield {"ts": "", "source": "watcher", "kind": "bad_line", "severity": "error",
                       "summary": f"unreadable line {n} in {f.name}", "run_id": None, "body": {"line": line[:200]}}


def field(ev: dict, name: str, default=None):
    """A run-event field lives in `body` (mirrored by emit) or at the top level."""
    return ev.get(name) if ev.get(name) is not None else (ev.get("body") or {}).get(name, default)
