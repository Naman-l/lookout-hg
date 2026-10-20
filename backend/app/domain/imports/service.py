"""What the data build found and did, for the Data screen: issues, steps, gate, stamp."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.cache import memo
from app.domain.imports.model import BuildMeta, BuildStep as StepRow, DataIssue as IssueRow, LoadGateCheck
from app.domain.imports.schema import BuildStamp, BuildStep, DataIssue


@memo
def list_issues(session: Session) -> list[DataIssue]:
    """Every defect, most rows affected first inside each file."""
    rows = session.scalars(select(IssueRow).order_by(IssueRow.file, IssueRow.count.desc(), IssueRow.key))
    return [DataIssue(key=r.key, issue=r.issue, file=r.file, count=r.count, handling=r.handling, rule=r.rule, consequence=r.consequence,
                      example=r.example, owner=r.owner, step=r.step) for r in rows]


def list_steps(session: Session) -> list[BuildStep]:
    return [BuildStep(seq=r.seq, step=r.step, title=r.title, rows_in=r.rows_in, rows_out=r.rows_out, issues=r.issues, seconds=r.seconds)
            for r in session.scalars(select(StepRow).order_by(StepRow.seq))]


def build_stamp(session: Session) -> BuildStamp:
    meta = {m.key: m.value for m in session.scalars(select(BuildMeta))}
    gate = list(session.scalars(select(LoadGateCheck)))
    return BuildStamp(as_of=meta["as_of"], recipe=meta["recipe"], recipe_hash=meta["recipe_hash"], built_at=meta["built_at"],
                      counts=json.loads(meta["counts"]), gate_checks=len(gate), gate_failed=sum(1 for g in gate if not g.passed))
