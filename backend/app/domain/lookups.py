"""The small tables every service joins on, read once per build: the team, purchasing groups, projects and their plants, people outside SCM on
file, vendors and materials, and the recipe's answers. Nothing here names a customer fact; it is all read from the build and the recipe."""

from __future__ import annotations

from functools import lru_cache

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.cache import memo
from app.domain.common.recipe import recipe_dir
from app.domain.materials.model import Material
from app.domain.people.model import Buyer, Contact, PurchasingGroup
from app.domain.projects.model import Project, ProjectAlias, ProjectPlant, WorkFront
from app.domain.suppliers.model import SupplierIdentity, SupplierRecord

VERTICALS = ("roads", "railway", "bess", "solar", "td")
VERTICAL_NAMES = {"roads": "Roads", "railway": "Railway", "bess": "BESS", "solar": "Solar", "td": "T&D"}
VERTICAL_SHORT = {"roads": "Roads", "railway": "Rly", "bess": "BESS", "solar": "Solar", "td": "T&D"}


@lru_cache(maxsize=4)
def _answers(path: str, mtime: float) -> dict:
    return yaml.safe_load(open(path).read())


def answers() -> dict:
    """The recipe's answers.yaml (company, thresholds, targets, the people outside SCM): configuration, never code."""
    p = recipe_dir() / "answers.yaml"
    return _answers(str(p), p.stat().st_mtime)


@memo
def team(session: Session) -> dict[str, Buyer]:
    """{member id: the member}, in the order the team table lists them."""
    return {b.id: b for b in session.scalars(select(Buyer))}


def member_name(session: Session, member_id: str | None) -> str:
    b = team(session).get(member_id or "")
    return b.name if b else (member_id or "")


def member_of(session: Session, name_or_id: str | None) -> Buyer | None:
    """The member a screen or a request names, by id or full name, any case."""
    want = (name_or_id or "").strip().lower()
    return next((b for b in team(session).values() if want in (b.id.lower(), b.name.lower())), None) if want else None


@memo
def group_owner(session: Session) -> dict[str, str]:
    """{SAP purchasing group: the member whose group it is}."""
    out = {pg.code: pg.person_id for pg in session.scalars(select(PurchasingGroup)) if pg.person_id}
    for b in team(session).values():
        for g in (b.purchasing_groups or "").split(","):
            out.setdefault(g.strip(), b.id)
    return out


def leads(session: Session) -> list[Buyer]:
    """The members someone reports to, the Head excepted: the GMs, the AGM and the Manager SCM as the organogram draws them."""
    t = team(session)
    over = {b.reports_to for b in t.values() if b.reports_to}
    return [b for b in t.values() if b.id in over and not b.countersigns]


def lead_of(session: Session, member: Buyer | None) -> Buyer | None:
    """The member a member reports to (None for the Head)."""
    return team(session).get(member.reports_to or "") if member else None


@memo
def under(session: Session, member_id: str) -> list[str]:
    """Every member who reports to `member_id`, directly or through someone else, in the team table's order."""
    t = team(session)
    out: list[str] = []
    todo = [member_id]
    while todo:
        m = todo.pop(0)
        for b in t.values():
            if b.reports_to == m and b.id not in out and b.id != member_id:
                out.append(b.id)
                todo.append(b.id)
    return [b for b in t if b in out]


def duty(session: Session, name: str) -> Buyer | None:
    """The member who holds a department-wide question (answers.yaml team duties): a vertical's decisions (roads, railway, bess, solar, td), the
    vendor library, a rate spread seen across projects, the MIS sheets."""
    return next((b for b in team(session).values() if name in (b.duties or "").split(",")), None)


def vertical_lead(session: Session, vertical: str) -> Buyer | None:
    return duty(session, vertical)


def head(session: Session) -> Buyer | None:
    """The member who countersigns above the DoA threshold."""
    return next((b for b in team(session).values() if b.countersigns), None)


def mis(session: Session) -> Buyer | None:
    """The member who builds the fund and projection sheets."""
    return duty(session, "mis")


@memo
def projects(session: Session) -> dict[str, Project]:
    return {p.id: p for p in session.scalars(select(Project))}


def project_name(session: Session, pid: str | None) -> str:
    p = projects(session).get(pid or "")
    return p.name if p else (pid or "")


@memo
def plants(session: Session) -> dict[str, ProjectPlant]:
    return {p.plant: p for p in session.scalars(select(ProjectPlant))}


@memo
def plants_of(session: Session) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for p in plants(session).values():
        if p.project_id:
            out.setdefault(p.project_id, []).append(p.plant)
    return out


@memo
def aliases(session: Session) -> dict[str, list[ProjectAlias]]:
    """{project id: the other names sheets write for it}."""
    out: dict[str, list[ProjectAlias]] = {}
    for a in session.scalars(select(ProjectAlias)):
        for pid in (a.project_ids or "").split(","):
            if pid:
                out.setdefault(pid, []).append(a)
    return out


@memo
def work_fronts(session: Session) -> dict[str, list[WorkFront]]:
    out: dict[str, list[WorkFront]] = {}
    for w in session.scalars(select(WorkFront)):
        out.setdefault(w.project_id, []).append(w)
    return out


def resolve_project(session: Session, text: str | None) -> str | None:
    """A project id from its name, an alias a person answered for, its id or one of its plant codes: exact (any case), never by likeness."""
    t = (text or "").strip().lower()
    if not t:
        return None
    for p in projects(session).values():
        if t in (p.id.lower(), p.name.lower()):
            return p.id
    pl = plants(session).get(t)
    if pl and pl.project_id:
        return pl.project_id
    for pid, al in aliases(session).items():
        if any(a.alias.lower() == t and len((a.project_ids or "").split(",")) == 1 for a in al):
            return pid
    return None


@memo
def contacts(session: Session) -> dict[str, Contact]:
    return {c.id: c for c in session.scalars(select(Contact))}


def contact_for(session: Session, function: str, project_id: str | None = None) -> Contact | None:
    """The person on file who owns a function (for a project, where the function is per project: its head, its planner)."""
    c = contacts(session)
    return c.get(f"{function}:{project_id}") if project_id and f"{function}:{project_id}" in c else c.get(function)


@memo
def materials(session: Session) -> dict[str, Material]:
    return {m.code: m for m in session.scalars(select(Material))}


@memo
def identities(session: Session) -> dict[str, SupplierIdentity]:
    return {i.id: i for i in session.scalars(select(SupplierIdentity))}


@memo
def records(session: Session) -> dict[str, SupplierRecord]:
    return {r.record_id: r for r in session.scalars(select(SupplierRecord))}


@memo
def records_of(session: Session) -> dict[str, list[SupplierRecord]]:
    out: dict[str, list[SupplierRecord]] = {}
    for r in records(session).values():
        out.setdefault(r.identity_id, []).append(r)
    for v in out.values():
        v.sort(key=lambda r: (r.created_on or "", r.record_id))
    return out


def vendor_name(session: Session, identity_or_record: str | None) -> str:
    """The name a buyer says: the newest record's name (a renamed vendor goes by its new name)."""
    if not identity_or_record:
        return ""
    r = records(session).get(identity_or_record)
    ident = r.identity_id if r else identity_or_record
    i = identities(session).get(ident)
    return i.name if i else (r.name if r else identity_or_record)


def identity_of(session: Session, record_id: str | None) -> str | None:
    r = records(session).get(record_id or "")
    return r.identity_id if r else None


def contact_on_file(session: Session, identity_or_record: str | None) -> tuple[str | None, str | None]:
    """(name, email) of the vendor's contact on file: the newest record's that has one. Never an address read from a message."""
    if not identity_or_record:
        return None, None
    r = records(session).get(identity_or_record)
    ident = r.identity_id if r else identity_or_record
    for rec in reversed(records_of(session).get(ident, [])):
        if rec.contact_email:
            return rec.contact_name, rec.contact_email
    return None, None


def vertical_of_project(session: Session, pid: str | None) -> str | None:
    p = projects(session).get(pid or "")
    return p.vertical if p else None
