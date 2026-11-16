"""Projects as a buyer picks them: name, vertical, stage, plants, the people on file, and what is open on each."""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.domain import lookups
from app.domain.cache import memo
from app.domain.common import EntityRef
from app.domain.orders.service import all_lines as po_lines
from app.domain.prs.service import all_lines as pr_lines
from app.domain.values import ref


class ProjectRow(BaseModel):
    ref: EntityRef
    name: str
    vertical: str
    stage: str
    state: str | None
    plants: list[str]
    aliases: list[str]
    head: str | None
    planner: str | None
    open_prs: int
    open_po_lines: int
    open_value: float
    work_fronts: list[str]


@memo
def list_projects(session: Session) -> list[ProjectRow]:
    out = []
    for p in lookups.projects(session).values():
        po = [l for l in po_lines(session).values() if l.project_id == p.id and l.status == "open"]
        out.append(ProjectRow(ref=ref("project", p.id, p.name), name=p.name, vertical=p.vertical, stage=p.stage, state=p.state, plants=lookups.plants_of(session).get(p.id, []),
                              aliases=sorted({a.alias for a in lookups.aliases(session).get(p.id, []) if a.alias != p.name}), head=p.head_name, planner=p.planner_name,
                              open_prs=sum(1 for l in pr_lines(session).values() if l.project_id == p.id and l.status == "open"), open_po_lines=len(po),
                              open_value=sum(l.open_value for l in po), work_fronts=[w.name for w in lookups.work_fronts(session).get(p.id, [])]))
    order = {v: i for i, v in enumerate(lookups.VERTICALS)}
    return sorted(out, key=lambda r: (order.get(r.vertical, 9), r.name))
