"""The system under test, seen from the evals.

Detector and code cases need the built app. The seam is one function the domain lane exposes,
`backend/dev/probe.py` `measure(db_path) -> dict` (a developer tool outside the app package), returning the flat keys the answer sheets name (counts,
facts keyed `name` or `name:part`, news matches, ledger probes). Until it exists a case is BLOCKED,
which is reported as such and is never a pass. Agent cases use `app.organism.run_workflow`.
"""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

PROBE = Path(__file__).resolve().parents[1] / "backend" / "dev" / "probe.py"


class Blocked(Exception):
    """The system under test does not exist yet (reason in the message)."""


def measure(db_path: Path) -> dict:
    if not PROBE.exists():
        raise Blocked(f"{PROBE} not on this branch")
    spec = importlib.util.spec_from_file_location("lookout_probe", PROBE)
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    return probe.measure(db_path)


def run_agent_case(case: dict, db_path: Path) -> dict:
    try:
        wf = importlib.import_module("app.organism").run_workflow
    except (ModuleNotFoundError, AttributeError) as e:
        raise Blocked("app.organism.run_workflow not on this branch yet (organism build)") from e
    return {"run_id": wf(case["item_key"], db_path=db_path)}
