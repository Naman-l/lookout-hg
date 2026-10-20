"""Grade the Data steward's proposal against the original rows, not against its own checks.

The steward's last passing normaliser script is taken from the run's events and run again in the app's sandbox on the re-exported file. Its output
must equal the original rows cell for cell (so a month/day swap, a comma left in a price or a space left in a quantity shows up), and the
columns must be the known export's, in order. Any value it dropped or invented is a differing cell."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd

from . import graders

ROOT = Path(__file__).resolve().parents[1]


def final_script(events: list[dict]) -> str | None:
    """The code of the last try_step that passed every check."""
    best = None
    for ev in events:
        p = ev.get("payload") or {}
        if ev.get("type") == "tool.result" and str(p.get("name", "")).endswith("try_step") and p.get("ok") and p.get("script"):
            best = p["script"]
    return best


def replay(script: str, filename: str, text: str) -> pd.DataFrame | str:
    """Run the script in the app's sandbox on the file; the normalised table, or the reason it could not run."""
    from app.domain.imports import sandbox
    from app.domain.imports.context import Ctx
    with tempfile.TemporaryDirectory(prefix="lookout-steward-eval-") as d:
        incoming = Path(d) / "incoming"
        incoming.mkdir()
        (incoming / filename).write_text(text, encoding="utf-8")
        step = Path(d) / "01_normalise.py"
        step.write_text(script, encoding="utf-8")
        ctx = Ctx(data=incoming, answers={}, t={})
        out = sandbox.run_step(ctx, step)
        if not out.ok:
            return f"the script did not run again: {(out.error or '')[:160]}"
        got = ctx.t.get("normalised")
        return got.astype(str) if got is not None else "the script stored no normalised table"


def differences(got: pd.DataFrame, want: pd.DataFrame) -> list[str]:
    bad = []
    if list(got.columns) != list(want.columns):
        bad.append(f"columns {list(got.columns)} are not {list(want.columns)}")
        return bad
    if len(got) != len(want):
        bad.append(f"{len(got)} rows out, {len(want)} expected")
        return bad
    got = got.reset_index(drop=True)
    for c in want.columns:
        wrong = got[c].ne(want[c].reset_index(drop=True))
        if wrong.any():
            i = int(wrong.idxmax())
            bad.append(f"{c}: {int(wrong.sum())} cells differ, first at row {i + 1}: got {got[c][i]!r}, original {want[c].iloc[i]!r}")
    return bad


def grade(events: list[dict], filename: str, text: str, want: pd.DataFrame) -> dict:
    script = final_script(events)
    if script is None:
        return graders._dim("steward_output", False, "no normaliser step passed its checks, so there is nothing to compare")
    got = replay(script, filename, text)
    if isinstance(got, str):
        return graders._dim("steward_output", False, got)
    bad = differences(got, want)
    return graders._dim("steward_output", not bad, "; ".join(bad[:3]) if bad else f"{len(got)} rows equal the original rows, cell for cell")
