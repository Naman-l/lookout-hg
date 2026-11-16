from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain import lookups
from app.domain.attention import service as attention
from app.domain.common import EntityRef
from app.domain.quotes import service as quotes
from app.domain.quotes.model import ComparativeStatement, Quote
from app.domain.quotes.schema import QuoteView
from app.domain.suppliers import service
from app.domain.suppliers.schema import VendorDetail, VendorRow
from app.domain.values import ref

router = APIRouter()


class VendorQuote(QuoteView):
    """A vendor's quote as its page lists it: what it was for (CS, material, project) and how the CS came out."""

    cs: str | None
    cs_status: str | None  # the CS's status (Approved, Pending...), else the tracker row's
    cs_approved_on: str | None
    material: EntityRef | None
    project: EntityRef | None


def _cases(session: Session) -> dict[str, list]:
    out: dict[str, list] = {}
    for i in attention.what_needs_attention(session):
        for r in i.refs:
            if r.type == "supplier":
                out.setdefault(r.id, []).append(ref("item", i.key, i.title))
    return out


@router.get("/vendors", response_model=list[VendorRow], summary="Vendors: one row per company (codes linked, never merged), library verticals, on-time share, open POs")
def vendors(in_library: bool | None = None, session: Session = Depends(get_session)):
    cases = _cases(session)
    return [v.model_copy(update={"cases": cases.get(v.ref.id, [])}) for v in service.list_vendors(session) if in_library is None or v.in_library == in_library]


@router.get("/vendors/{vendor_id}", response_model=VendorDetail, summary="One vendor: its codes, library rows, delivery record, MSME dues, guarantees, POs, quotes and messages")
def vendor(vendor_id: str, session: Session = Depends(get_session)):
    v = service.profile(session, vendor_id)
    if v is None:
        raise HTTPException(404, "no such vendor")
    return v.model_copy(update={"cases": _cases(session).get(v.ref.id, [])})


@router.get("/vendors/{vendor_id}/quotes", response_model=list[VendorQuote], summary="Every quote on file from one vendor (tracker and mail), newest first, with its CS, material, project and the CS outcome")
def vendor_quotes(vendor_id: str, session: Session = Depends(get_session)):
    ident = lookups.identity_of(session, vendor_id) or (vendor_id if vendor_id in lookups.identities(session) else None)
    if ident is None:
        raise HTTPException(404, "no such vendor")
    out = []
    for q in session.scalars(select(Quote).where(Quote.identity_id == ident).order_by(Quote.quote_date.desc(), Quote.id)):
        s = session.get(ComparativeStatement, q.cs_no) if q.cs_no else None
        m = lookups.materials(session).get(q.material or "")
        out.append(VendorQuote(**quotes.view(session, q).model_dump(), cs=q.cs_no, cs_status=(s.status if s else None) or q.cs_status,
                               cs_approved_on=(s.approved_on if s else None) or q.approved_on,
                               material=ref("material", q.material, m.description if m else None) if q.material else None,
                               project=ref("project", q.project_id, lookups.project_name(session, q.project_id)) if q.project_id else None))
    return out
