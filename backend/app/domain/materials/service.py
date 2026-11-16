"""Materials: the master facts, the rate paid by site and by vendor over time, where each is used (which projects require or buy it), what is open,
and every quote beside the last PO rate and the budget rate."""

from __future__ import annotations

import statistics

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import lookups
from app.domain.cache import memo
from app.domain.common import EntityRef
from app.domain.orders.service import all_lines as po_lines
from app.domain.prs.service import all_lines as pr_lines
from app.domain.quotes.model import Quote
from app.domain.quotes.service import budget_rates, quotes_for_material
from app.domain.quotes.schema import QuoteView
from app.domain.requirements.service import all_lines as req_lines
from app.domain.values import ref


class MaterialRow(BaseModel):
    ref: EntityRef
    code: str
    description: str
    group: str
    category: str
    base_uom: str
    alt_uom: str | None
    alt_per_base: float | None
    lead_days: int | None
    pv_index: str | None
    open_prs: int
    open_po_lines: int
    open_value: float
    last_rate: float | None
    projects: int  # projects that bought it in the last year
    spread: float | None  # highest over lowest of each project's last rate


class RatePoint(BaseModel):
    date: str
    rate: float
    project: str | None
    vendor: str
    po_line: str


class SiteRate(BaseModel):
    project: EntityRef
    last_rate: float
    last_date: str
    vendor: str
    budget: float | None
    po_lines: int
    vs_median_pct: float | None


class QuoteBeside(BaseModel):
    """One quote beside what the material last cost on a PO at the quote's project (else at any site) and the project's budget rate."""

    quote: str  # the quote's id (QuoteView.ref.id)
    cs: str | None
    project: EntityRef | None
    last_po_rate: float | None
    last_po_date: str | None
    last_po_line: str | None
    last_scope: str | None  # project: the newest PO line at the quote's project | any: the newest anywhere (the quote names no project, or it bought none)
    budget: float | None  # the project's BOQ / tender rate
    vs_last_pct: float | None
    vs_budget_pct: float | None


class MaterialDetail(MaterialRow):
    history: list[RatePoint]  # every PO line's rate, oldest first
    by_site: list[SiteRate]
    by_vendor: list[dict]  # vendor, lines, min, max, last
    where_used: list[dict]  # project, requirement in the 3-month sheet, open PO qty, PR qty
    open_pr_refs: list[EntityRef]
    open_po_refs: list[EntityRef]
    quotes: list[QuoteView]
    median: float | None
    beside: list[QuoteBeside] = []  # per quote: the last PO rate and the budget rate it is read against


@memo
def list_materials(session: Session) -> list[MaterialRow]:
    out = []
    pos, prs = po_lines(session).values(), pr_lines(session).values()
    for code, m in lookups.materials(session).items():
        mine = [l for l in pos if l.material == code]
        last = max(mine, key=lambda l: (l.doc_date, l.id), default=None)
        sites: dict[str, float] = {}
        for l in sorted(mine, key=lambda l: l.doc_date):
            if l.project_id:
                sites[l.project_id] = l.rate_base
        out.append(MaterialRow(ref=ref("material", code, m.description), code=code, description=m.description, group=m.group, category=m.category, base_uom=m.base_uom,
                               alt_uom=m.alt_uom, alt_per_base=m.alt_per_base, lead_days=m.lead_days, pv_index=m.pv_index,
                               open_prs=sum(1 for l in prs if l.material == code and l.status == "open"), open_po_lines=sum(1 for l in mine if l.status == "open"),
                               open_value=sum(l.open_value for l in mine if l.status == "open"), last_rate=last.rate_base if last else None, projects=len(sites),
                               spread=round(max(sites.values()) / min(sites.values()), 2) if len(sites) > 1 and min(sites.values()) else None))
    return out


def detail(session: Session, code: str) -> MaterialDetail | None:
    row = next((r for r in list_materials(session) if r.code == code), None)
    if row is None:
        return None
    mine = sorted((l for l in po_lines(session).values() if l.material == code), key=lambda l: (l.doc_date, l.id))
    sites: dict[str, list] = {}
    for l in mine:
        if l.project_id:
            sites.setdefault(l.project_id, []).append(l)
    lasts = {p: ls[-1] for p, ls in sites.items()}
    med = statistics.median([l.rate_base for l in lasts.values()]) if lasts else None
    br = budget_rates(session)
    by_site = sorted((SiteRate(project=ref("project", p, lookups.project_name(session, p)), last_rate=l.rate_base, last_date=l.doc_date, vendor=lookups.vendor_name(session, l.identity_id),
                               budget=br[(p, code)].rate if (p, code) in br else None, po_lines=len(sites[p]),
                               vs_median_pct=round(100 * (l.rate_base - med) / med, 1) if med else None) for p, l in lasts.items()), key=lambda s: s.last_rate)
    vend: dict[str, list] = {}
    for l in mine:
        vend.setdefault(l.identity_id, []).append(l)
    by_vendor = [dict(vendor=lookups.vendor_name(session, v), id=v, lines=len(ls), min=min(x.rate_base for x in ls), max=max(x.rate_base for x in ls), last=ls[-1].rate_base,
                      last_date=ls[-1].doc_date) for v, ls in vend.items()]
    used = []
    for p in sorted({r.project_id for r in req_lines(session) if r.project_id and code in (r.material_codes or "").split(",")} | set(sites)):
        used.append(dict(project=p, name=lookups.project_name(session, p),
                         required=sum(r.qty for r in req_lines(session) if r.project_id == p and code in (r.material_codes or "").split(",")),
                         on_order=sum(l.open_base for l in sites.get(p, []) if l.status == "open"),
                         pr_open=sum((l.qty_base or l.qty) for l in pr_lines(session).values() if l.project_id == p and l.material == code and l.status == "open")))
    newest = mine[-1] if mine else None
    pct = lambda a, b: round(100 * (a - b) / b, 1) if a is not None and b else None  # noqa: E731
    beside = []
    for q in session.scalars(select(Quote).where(Quote.material == code)):
        at = lasts.get(q.project_id or "")
        last = at or newest
        b = br.get((q.project_id or "", code))
        beside.append(QuoteBeside(quote=q.id, cs=q.cs_no, project=ref("project", q.project_id, lookups.project_name(session, q.project_id)) if q.project_id else None,
                                  last_po_rate=last.rate_base if last else None, last_po_date=last.doc_date if last else None, last_po_line=last.id if last else None,
                                  last_scope=("project" if at else "any") if last else None, budget=b.rate if b else None,
                                  vs_last_pct=pct(q.rate, last.rate_base if last else None), vs_budget_pct=pct(q.rate, b.rate if b else None)))
    return MaterialDetail(**row.model_dump(), beside=beside, history=[RatePoint(date=l.doc_date, rate=l.rate_base, project=l.project_id, vendor=lookups.vendor_name(session, l.identity_id), po_line=l.id) for l in mine],
                          by_site=by_site, by_vendor=sorted(by_vendor, key=lambda v: v["last"]), where_used=used,
                          open_pr_refs=[ref("pr_line", l.id, l.short_text) for l in pr_lines(session).values() if l.material == code and l.status == "open"],
                          open_po_refs=[ref("po_line", l.id, l.short_text) for l in mine if l.status == "open"], quotes=quotes_for_material(session, code), median=med)
