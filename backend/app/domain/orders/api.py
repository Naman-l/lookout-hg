from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain import lookups
from app.domain.milestones.model import Milestone
from app.domain.orders import service
from app.domain.orders.schema import PoLineView
from app.domain.payments.service import guarantees, invoiced_paid, ledger_by_po
from app.domain.phases.ladder import ladder
from app.domain.phases.schema import Ladder

router = APIRouter()


class LedgerItem(BaseModel):
    """One FBL1N line on the PO: an invoice (RE), a payment (KZ) or an advance (KA), oldest first."""

    doc_no: str
    doc_type: str  # RE | KZ | KA
    kind: str  # Invoice | Payment | Advance
    reference: str | None  # the vendor's invoice number
    date: str
    net_due: str | None
    amount: float  # unsigned
    cleared_by: str | None  # the clearing document (a paid invoice)
    cleared_on: str | None
    text: str | None
    row: int  # vendor_ledger row


KINDS = {"RE": "Invoice", "KZ": "Payment", "KA": "Advance"}


class PoDetail(BaseModel):
    po: str
    lines: list[PoLineView]
    ladders: list[Ladder]
    milestones: list[dict]
    guarantees: list[dict]
    ledger: dict
    ledger_items: list[LedgerItem] = []


@router.get("/pos", response_model=list[PoLineView], summary="PO lines (ME2N, netted against MB51), with plain-word flags")
def pos(status: str | None = None, buyer: str | None = None, project: str | None = None, vendor: str | None = None, material: str | None = None,
        session: Session = Depends(get_session)):
    b = lookups.member_of(session, buyer) if buyer else None
    pid = lookups.resolve_project(session, project) if project else None
    return service.list_lines(session, status=status, buyer=b.id if b else None, project=pid, vendor=vendor, material=material)


@router.get("/pos/{po_no}", response_model=PoDetail, summary="One PO: its lines, the ladder of each, milestones, guarantees, invoices and payments")
def po(po_no: str, session: Session = Depends(get_session)):
    lines = service.lines_of_po(session, po_no)
    if not lines:
        raise HTTPException(404, "no such PO")
    ms = [dict(id=m.id, item=m.item_text, mfc_requested=m.mfc_requested, mfc_issued=m.mfc_issued, inspection_call=m.inspection_call, inspection_planned=m.inspection_planned,
               inspection_done=m.inspection_done, dispatch=m.dispatch_clearance, delivered=m.delivered, site_ready=m.site_ready_planned, commissioned=m.commissioned,
               warranty_end=m.warranty_end, remarks=m.remarks) for m in session.scalars(select(Milestone).where(Milestone.po_no == po_no))]
    return PoDetail(po=po_no, lines=[service.view(session, l) for l in lines], ladders=[x for x in (ladder(session, po_line_id=l.id) for l in lines) if x], milestones=ms,
                    guarantees=[g.model_dump() for g in guarantees(session) if g.po == po_no], ledger=invoiced_paid(session, po_no),
                    ledger_items=[LedgerItem(doc_no=i.doc_no, doc_type=i.doc_type, kind=KINDS.get(i.doc_type, i.doc_type), reference=i.reference, date=i.doc_date, net_due=i.net_due,
                                             amount=abs(i.amount), cleared_by=i.clearing_doc, cleared_on=i.clearing_date, text=i.text, row=i.src_row)
                                  for i in ledger_by_po(session).get(po_no, [])])


@router.get("/orders/{po_line:path}", response_model=PoLineView, summary="One PO line")
def order(po_line: str, session: Session = Depends(get_session)):
    l = service.line(session, po_line)
    if l is None:
        raise HTTPException(404, "no such PO line")
    return service.view(session, l)
