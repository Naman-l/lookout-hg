"""Search across the records a buyer names: cases, messages, vendors (name, code, GSTIN), projects (name, any alias a person answered for, plant
code), materials (code, name), PRs, POs and people. Deterministic, no model. A misspelt site name
or a city name finds the project a person answered it for."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import lookups
from app.domain.attention import service as attention
from app.domain.inbox.model import Message
from app.domain.orders.service import all_lines as po_lines
from app.domain.prs.service import all_lines as pr_lines
from app.domain.search.schema import Highlight, Hit


def _u16(s: str) -> int:
    return sum(2 if ord(c) > 0xFFFF else 1 for c in s)


def _hit(q: str, text: str, **kw) -> Hit | None:
    i = text.lower().find(q)
    if i < 0:
        return None
    lo = max(0, i - 40)
    snip = text[lo: i + len(q) + 60]
    score = 100 if text.lower() == q else 80 if text.lower().startswith(q) else 50
    return Hit(matched_text=snip, highlight=Highlight(start=_u16(snip[: i - lo]), end=_u16(snip[: i - lo + len(q)])), score=score + kw.pop("bonus", 0), **kw)


def search(session: Session, q: str, types: list[str] | None = None, limit: int = 30) -> list[Hit]:
    q = q.strip().lower()
    if not q:
        return []
    want = lambda t: not types or t in types  # noqa: E731
    out: list[Hit] = []
    if want("project"):
        for p in lookups.projects(session).values():
            names = [(p.name, "name"), (p.id, "id")] + [(a.alias, f"also written {a.alias}") for a in lookups.aliases(session).get(p.id, []) if a.method != "unresolved"] \
                + [(code, f"plant {code}") for code in lookups.plants_of(session).get(p.id, [])] + ([(p.sap_plant_name, "SAP plant name")] if p.sap_plant_name else [])
            for text, how in names:
                h = _hit(q, text, type="project", ref=p.id, label=p.name, sublabel=f"{lookups.VERTICAL_NAMES.get(p.vertical, p.vertical)} · {how}", url=f"/insights/projects/{p.id}", bonus=10)
                if h:
                    out.append(h)
                    break
    if want("supplier"):
        for ident in lookups.identities(session):
            for r in lookups.records_of(session).get(ident, []):
                h = next((h for h in (_hit(q, t, type="supplier", ref=ident, label=lookups.vendor_name(session, ident), sublabel=f"vendor {', '.join(x.record_id for x in lookups.records_of(session)[ident])}"
                                           + (f" · was {r.name}" if r.name != lookups.vendor_name(session, ident) else ""), url=f"/vendors/{ident}") for t in (r.name, r.record_id, r.gstin or "")) if h), None)
                if h:
                    out.append(h)
                    break
    if want("material"):
        for code, m in lookups.materials(session).items():
            h = _hit(q, code, type="material", ref=code, label=m.description, sublabel=f"material {code} · {m.category}", url=f"/materials/{code}") or \
                _hit(q, m.description, type="material", ref=code, label=m.description, sublabel=f"material {code} · {m.category}", url=f"/materials/{code}")
            if h:
                out.append(h)
    if want("pr") and q[:2] == "10" and q.replace("/", "").isdigit():
        for pr in sorted({l.pr_no for l in pr_lines(session).values() if l.pr_no.startswith(q.split("/")[0])})[:10]:
            l = next(x for x in pr_lines(session).values() if x.pr_no == pr)
            out.append(_hit(q.split("/")[0], pr, type="pr", ref=pr, label=f"PR {pr}", sublabel=f"{lookups.project_name(session, l.project_id) or 'no project'} · {l.short_text}", url=f"/prs/{pr}", bonus=20))
    if want("po") and q[:2] == "45" and q.replace("/", "").isdigit():
        for po in sorted({l.po_no for l in po_lines(session).values() if l.po_no.startswith(q.split("/")[0])})[:10]:
            l = next(x for x in po_lines(session).values() if x.po_no == po)
            out.append(_hit(q.split("/")[0], po, type="po", ref=po, label=f"PO {po}", sublabel=f"{lookups.vendor_name(session, l.identity_id)} · {lookups.project_name(session, l.project_id)}", url=f"/pos/{po}", bonus=20))
    if want("person"):
        for b in lookups.team(session).values():
            h = _hit(q, b.name, type="person", ref=b.id, label=b.name, sublabel=b.role, url=f"/insights/team/{b.id}")
            if h:
                out.append(h)
        for c in lookups.contacts(session).values():
            h = _hit(q, c.name, type="person", ref=c.id, label=c.name, sublabel=(c.title or c.function.replace("_", " ")) + (f", {lookups.project_name(session, c.project_id)}" if c.project_id else ""), url="")
            if h:
                out.append(h)
    if want("item"):
        for i in attention.what_needs_attention(session):
            h = _hit(q, f"{i.title} · {i.summary}", type="item", ref=i.key, label=i.title, sublabel=i.summary, url=f"/items/{i.key}")
            if h:
                out.append(h)
    if want("message"):
        for m in session.scalars(select(Message)):
            h = _hit(q, m.subject, type="message", ref=m.id, label=m.subject, sublabel=f"{m.from_name} · {m.date[:10]}", url=f"/inbox/{m.id}") or \
                _hit(q, m.body or "", type="message", ref=m.id, label=m.subject, sublabel=f"{m.from_name} · {m.date[:10]}", url=f"/inbox/{m.id}")
            if h:
                out.append(h)
    return sorted([h for h in out if h], key=lambda h: -h.score)[:limit]
