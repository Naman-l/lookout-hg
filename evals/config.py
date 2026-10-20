"""The configuration recorded with every run, so a result can be reproduced."""
from __future__ import annotations

import hashlib
import importlib.metadata
import os
import subprocess
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUDGET_USD = 12.0   # used only when the ledger carries no cap


def load_env(path: Path | None = None) -> None:
    """Read the repository's .env (where the README tells a reviewer to put the key) into this process, never over a variable already set.
    The app reads .env itself; the eval commands call this so `make eval` finds the same key."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(path or ROOT / ".env", override=False)


def default_budget() -> float:
    """A live run stops itself here: LOOKOUT_EVAL_BUDGET_USD, else what is left of the cap in evals/spend.yaml (Khalid's, for the three final live
    runs), else 12 USD. `--budget` overrides."""
    try:
        if "LOOKOUT_EVAL_BUDGET_USD" in os.environ:
            return float(os.environ["LOOKOUT_EVAL_BUDGET_USD"])
        from . import spend
        d = spend._doc()
        if d.get("cap"):
            return max(float(d["cap"]["usd"]) - spend.capped(d.get("runs", []))[0], 0.0)
    except (ValueError, OSError, KeyError):
        pass
    return DEFAULT_BUDGET_USD


def _tree_hash(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.relative_to(ROOT).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:8]


def data_hash() -> str:
    return _tree_hash([p for p in (ROOT / "data").rglob("*") if p.is_file()])


def prompt_hash() -> str:
    d = ROOT / "backend" / "app" / "organism"
    files = [p for p in d.rglob("*") if p.suffix in {".md", ".txt", ".yaml"} and p.is_file()] if d.exists() else []
    return _tree_hash(files) if files else "none"


def sheets_hash() -> str:
    """The answer sheets as they stood for this run. They change only between rounds, with a dated line in rounds.yaml."""
    return _tree_hash(list((ROOT / "evals" / "cases").glob("*.yaml")))


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def sdk_version() -> str:
    try:
        return importlib.metadata.version("claude-agent-sdk")
    except importlib.metadata.PackageNotFoundError:
        return "not installed"


def snapshot(model: str | None, trials: int) -> dict:
    # the date is the Pacific one: the day the run was made, where it was made
    return {"date": datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d"), "model": model or "none (no-model)",
            "prompt_hash": prompt_hash(), "data_hash": data_hash(), "sheets_hash": sheets_hash(), "sdk": sdk_version(),
            "git_sha": git_sha(), "trials": trials}
