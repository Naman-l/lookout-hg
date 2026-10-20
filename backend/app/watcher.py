"""The Watcher's write side: one NDJSON event stream for everything the app does.

Every request, tool call, action state change, eval case, scenario step and data-build stage calls
``emit``. The recorder under ``watcher/`` reads the same files. Flat schema on purpose, so a reviewer can
``grep`` and ``jq`` it:

    {"ts": ..., "source": "api|agent|actions|data|evals|scenario", "kind": ..., "severity": ...,
     "summary": "<one plain sentence>", "run_id": ..., "request_id": ..., "item_id": ..., "body": {...}}
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
EVENTS_DIR = Path(os.environ.get("LOOKOUT_EVENTS_DIR", _ROOT / "watcher" / "events"))
_lock = threading.Lock()

VALID_SEVERITIES = {"info", "warn", "error", "critical"}


def _path() -> Path:
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    return EVENTS_DIR / f"{datetime.now(timezone.utc):%Y-%m-%d}.ndjson"


def emit(
    source: str,
    kind: str,
    summary: str,
    *,
    severity: str = "info",
    run_id: str | None = None,
    request_id: str | None = None,
    item_id: int | None = None,
    **body,
) -> str:
    """Append one event and return its id. Never raises: a logging failure must not break the app."""
    if severity not in VALID_SEVERITIES:
        severity = "info"
    event = {
        "event_id": f"evt-{uuid.uuid4().hex[:12]}",
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "kind": kind,
        "severity": severity,
        "summary": summary,
        "run_id": run_id,
        "request_id": request_id,
        "item_id": item_id,
        "body": body or None,
    }
    try:
        line = json.dumps(event, default=str)
        with _lock:
            with _path().open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass
    return event["event_id"]
