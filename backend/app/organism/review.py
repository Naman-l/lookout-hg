"""The Reviewer: a separate session with no tools and no memory of the run. It grades a Recommendation against the
grade sheet's soft checks and says what to fix. The verifier's hard checks are code and are not repeated here."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import yaml

from .. import db as _db
from . import company
from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
from pydantic import BaseModel, Field

REVIEW_MODEL = os.environ.get("LOOKOUT_REVIEW_MODEL", os.environ.get("LOOKOUT_FAST_MODEL", "claude-haiku-5-5"))
ENABLED = os.environ.get("LOOKOUT_REVIEW", "1") != "0"
_SHEETS = yaml.safe_load((Path(__file__).parent / "grades.yaml").read_text())


class CheckResult(BaseModel):
    """One soft check: pass or fail, with a one-line critique when it fails. No middle score."""

    name: str
    passed: bool
    critique: str = Field(default="", description="Only when it fails: one short line saying what is wrong")
    critical: bool = False  # a failed critical check also sends Lookout back once in inline mode


class Review(BaseModel):
    checks: list[CheckResult]
    summary: str = Field(description="One line a buyer can read: how good the Recommendation is and the main gap, if any")

    @property
    def score(self) -> int:
        """The share of checks passed, 0-100."""
        return round(100 * sum(c.passed for c in self.checks) / len(self.checks)) if self.checks else 0

    @property
    def failed(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]


def sheet_for(kind: str, only_critical: bool = False) -> list[dict]:
    sheet = _SHEETS["common"] + ([] if kind == "common" else _SHEETS.get(kind, []))
    return [c for c in sheet if c.get("critical")] if only_critical else sheet


def _bullets(items) -> str:
    return "\n".join(f"- {x}" for x in items) if items else "- (none)"


def render(rec: dict, drafts: list[dict] | None = None) -> str:
    """The Recommendation as a buyer reads it, in words. The Reviewer is never shown field names: a Reviewer that reads `why_it_blocks` fails 'buyer's words' for ours."""
    out = [f"Finding: {rec.get('finding', '')}", *(["Points:\n" + _bullets(f"{p.get('label', '')}: {p.get('text', '')}" for p in rec["points"])] if rec.get("points") else []), "Assumptions:\n" + _bullets(rec.get("assumptions")), "What would change it:\n" + _bullets(rec.get("would_change")),
           "Open questions:\n" + _bullets(f"{q.get('what', '')}. Why it blocks: {q.get('why_it_blocks', '')}. Owner: {q.get('owner') or 'nobody named'}. Ask: {q.get('question', '')}" for q in rec.get("open_questions", []))]
    nxt = rec.get("next_step") or {}
    if nxt.get("what"):  # a case's finding is its Situation; what to do is here (F74)
        out.insert(1, "Next step: " + " · ".join(x for x in (nxt.get("who"), nxt.get("what"), nxt.get("by")) if x))
    if rec.get("recommended"):
        out.insert(2, f"Recommended way through: {str(rec['recommended'].get('kind') or '').replace('_', ' ')}, because {rec['recommended'].get('reason')}")   # the kind in words: an id is the page's, not the buyer's
    if rec.get("case_findings"):
        out.insert(2, "What it picked out from the records:\n" + _bullets(f.get("meaning") for f in rec["case_findings"]))   # never the key: it is an internal name
    if rec.get("findings"):
        out.append("What was found in the file:\n" + _bullets(f"{f.get('issue', '')}: {f.get('count', '?')} rows. If left alone: {f.get('consequence', '')}. Example: {f.get('example', '')}. Handling: {f.get('handling', '')}" for f in rec["findings"]))
    out.append("Figures it cites:\n" + _bullets(f"{n.get('name') or n.get('id')}: {n.get('value')} {n.get('unit')}" for n in rec.get("numbers", [])))
    if drafts:  # the requests staged for approval: the check on commitments has to read what would be sent
        out.append("Requests drafted for approval:\n" + _bullets(f"To {d.get('to')}, subject \"{d.get('subject')}\":\n{d.get('body')}" for d in drafts))
    return "\n\n".join(out)


def build_prompt(kind: str, title: str, rec: dict, verifier: dict, drafts: list[dict] | None = None, only_critical: bool = False) -> str:
    checks = "\n".join(f"{i}. {c['name']}: {c['asks']}" for i, c in enumerate(sheet_for(kind, only_critical), 1))
    return (
        f"You review a procurement Recommendation written for a buyer at {company.names(_db.DB_PATH)[0]}.\nItem: {title}.\n\n"
        f"The Recommendation, as the buyer reads it:\n\n{render(rec, drafts)}\n\n"
        f"Code has already verified the numbers against the tools and the checks it can make (passed: {verifier.get('passed')}"
        + (f"; failed: {verifier.get('failures')}" if verifier.get("failures") else "") + "). Do not check arithmetic or ids; do not invent facts.\n\n"
        f"Answer each check PASS or FAIL, using only its own wording, strictly:\n{checks}\n\n"
        "Reply with ONLY one JSON object, as short as you can: "
        '{"pass": [true or false for each check, in the order above], "critique": {"<check number>": "<what is wrong, at most 15 words>"} for the failed checks only, '
        '"summary": "<at most 15 words>"}.'
    )


def parse(text: str, kind: str, only_critical: bool = False) -> "Review | None":
    """The Reviewer's one-turn JSON reply -> Review; anything malformed is None (ungraded), never a guess."""
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        raw = json.loads(text[start:end])
        sheet = sheet_for(kind, only_critical)
        flags = raw["pass"]
        if len(flags) != len(sheet) or any(not isinstance(x, bool) for x in flags):
            return None
        notes = {str(k): str(v) for k, v in (raw.get("critique") or {}).items()}
        return Review(checks=[CheckResult(name=c["name"], passed=ok, critique="" if ok else notes.get(str(i), ""), critical=bool(c.get("critical")))
                              for i, (c, ok) in enumerate(zip(sheet, flags), 1)], summary=str(raw.get("summary", "")))
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


async def review(kind: str, title: str, rec: dict, verifier: dict, drafts: list[dict] | None = None, only_critical: bool = False) -> tuple[Review | None, float]:
    """Grade once. Returns (review, cost_usd); (None, 0) if the reviewer could not run, which never fails the run."""
    options = ClaudeAgentOptions(
        model=REVIEW_MODEL, system_prompt="You are a careful, fair procurement reviewer. You grade; you never rewrite.", tools=[], setting_sources=[],
        strict_mcp_config=True, cwd=tempfile.mkdtemp(prefix="lookout-review-"), thinking={"type": "disabled"}, effort="low", max_turns=1,
        max_budget_usd=0.2,
        env={"CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS": "1"},
    )
    out, cost = None, 0.0
    try:
        async for m in query(prompt=build_prompt(kind, title, rec, verifier, drafts, only_critical), options=options):
            if isinstance(m, ResultMessage):
                cost = m.total_cost_usd or 0.0
                out = parse(m.result or "", kind, only_critical)
    except Exception:  # noqa: BLE001  a reviewer that cannot run is reported as ungraded, never as a pass
        return None, cost
    return out, cost


def needs_revision(verifier_passed: bool, review: Review | None, revised: bool) -> bool:
    """One round only. Revise when a code check failed, or (inline mode) a critical soft check failed. A soft fail elsewhere is shown, not acted on."""
    if revised:
        return False
    return (not verifier_passed) or (review is not None and any(c.critical and not c.passed for c in review.checks))


def revision_prompt(verifier: dict, review: Review | None) -> str:
    lines = ["Revise your Recommendation once. Do not delegate again unless a handoff is missing; use get_handoffs."]
    for f in verifier.get("failures", []):
        lines.append(f"- A code check failed: {f}")
    if review:
        lines += [f"- Reviewer: {c.name}: {c.critique}" for c in review.failed]
    lines.append("Keep every figure to the numbers the tools gave (use the say forms). Write the corrected Recommendation.")
    return "\n".join(lines)
