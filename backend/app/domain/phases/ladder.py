"""The PR-to-payment ladder of one PR line or PO line, and whose move each wait was. Every rung is read from a record (ME5A, the RFQ/CS tracker,
ME2N, the expediting tracker, MB51, FBL1N, the requirement sheet, a dated mail fact); a rung the data cannot show is unknown, never inferred.

Whose move (one rule per gap, PLAN 6.2): raised -> released: Projects (the project head releases) · released -> RFQ: SCM · RFQ -> quotes: Vendor ·
quotes -> CS approved: SCM, or Projects while a spec query is open (a dated mail fact), or Management when the CS is above the DoA threshold ·
CS -> PO: SCM · PO -> MFC: Projects when the MFC is held for site readiness (the tracker says so), else SCM · MFC -> inspected: Vendor, then QA from
the inspection call · inspected -> dispatched: Finance while a payment before dispatch or an LC is pending, else Vendor · dispatched -> received:
Vendor · received -> invoiced: Vendor · invoiced -> paid: Finance.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import lookups
from app.domain.cache import memo
from app.domain.common import AS_OF
from app.domain.doa import service as doa
from app.domain.inbox.model import MessageEvent
from app.domain.milestones.model import Milestone
from app.domain.orders.service import all_lines as po_lines
from app.domain.payments.model import LcBg
from app.domain.payments.service import invoiced_paid
from app.domain.phases.schema import Ladder, Rung
from app.domain.prs.service import all_lines as pr_lines
from app.domain.quotes.model import ComparativeStatement, Quote
from app.domain.receipts.service import last_receipt
from app.domain.requirements.service import lines_for
from app.domain.values import ref

LABELS = {"needed": "Needed", "pr_raised": "PR raised", "pr_released": "PR released", "rfq_sent": "RFQ sent", "quotes_in": "Quotes in", "cs_approved": "CS approved",
          "po_released": "PO released", "mfc_issued": "MFC issued", "inspected": "Inspected", "dispatched": "Dispatched", "received": "Received (GRN)",
          "invoiced": "Invoiced", "paid": "Paid", "closed": "Closed"}
ORDER = list(LABELS)


@memo
def _milestones(session: Session) -> dict[str, Milestone]:
    return {m.id: m for m in session.scalars(select(Milestone))}


@memo
def _cs_of_pr_line(session: Session) -> dict[str, ComparativeStatement]:
    out = {}
    for s in session.scalars(select(ComparativeStatement)):
        for x in (s.pr_line_ids or "").split(","):
            if x:
                out[x] = s
    return out


@memo
def _first_quote_row(session: Session) -> dict[str, Quote]:
    out: dict[str, Quote] = {}
    for q in session.scalars(select(Quote).where(Quote.cs_no.is_not(None)).order_by(Quote.rfq_sent)):
        out.setdefault(q.cs_no, q)
    return out


@memo
def _spec_queries(session: Session) -> dict[str, MessageEvent]:
    """{PR number: the dated mail fact that a vendor waits for the spec from Projects}."""
    return {e.ref_id: e for e in session.scalars(select(MessageEvent).where(MessageEvent.kind == "spec_awaited", MessageEvent.ref_type == "pr"))}


@memo
def _lcs(session: Session) -> dict[str, LcBg]:
    return {g.po_no: g for g in session.scalars(select(LcBg).where(LcBg.kind == "LC")) if g.po_no}


def _days(a: str | None, b: str | None) -> int | None:
    return (date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days if a and b else None


def ladder(session: Session, *, pr_line_id: str | None = None, po_line_id: str | None = None) -> Ladder | None:
    pos, prs = po_lines(session), pr_lines(session)
    po = pos.get(po_line_id or "")
    pr = prs.get(pr_line_id or "") or (prs.get(po.pr_line_id or "") if po else None)
    if po is None and pr is not None and pr.po_line_id:
        po = pos.get(pr.po_line_id)
    if pr is None and po is None:
        return None
    today = AS_OF.isoformat()
    material = (po.material if po else None) or (pr.material if pr else None)
    project = (po.project_id if po else None) or (pr.project_id if pr else None)
    vertical = lookups.vertical_of_project(session, project)
    rungs: dict[str, Rung] = {}

    def put(key: str, d: str | None, source: str | None = None, r=None, state: str | None = None, unknown: str | None = None):
        rungs[key] = Rung(key=key, label=LABELS[key], state=state or ("done" if d and d <= today else "todo"), date=d, source=source, ref=r, unknown=unknown)

    req = [r for r in lines_for(session, project, material)] if project and material else []
    need = (pr.needed_by if pr else None) or (min(f"{r.month}-01" for r in req) if req else None)
    put("needed", need, f"pr_lines row {pr.src_row}" if pr and pr.needed_by else (f"requirement_lines {req[0].id}" if req else None),
        state="done" if need else "unknown", unknown=None if need else "no requirement month on file: ask the project planner")
    if pr:
        put("pr_raised", pr.created, f"pr_lines row {pr.src_row}", ref("pr_line", pr.id))
        put("pr_released", pr.released, f"pr_lines row {pr.src_row}", ref("pr_line", pr.id))
    else:
        for k in ("pr_raised", "pr_released"):
            put(k, None, state="na", unknown="a PO with no PR (an emergency buy)")
    s = _cs_of_pr_line(session).get(pr.id) if pr else None
    q = _first_quote_row(session).get(s.cs_no) if s else None
    if s:
        put("rfq_sent", s.rfq_sent, f"quotes row {q.src_row}" if q else "comparative_statements", ref("cs", s.cs_no))
        put("quotes_in", s.first_quote, f"comparative_statements {s.cs_no}", ref("cs", s.cs_no))
        put("cs_approved", s.approved_on, f"comparative_statements {s.cs_no}", ref("cs", s.cs_no))
    else:
        bulk = po is not None
        for k in ("rfq_sent", "quotes_in", "cs_approved"):
            put(k, None, state="na" if bulk else "todo", unknown="no CS on file for this line (a rate contract or a repeat order)" if bulk else None)
    m = _milestones(session).get(po.id) if po else None
    if po:
        put("po_released", po.doc_date, f"po_lines row {po.src_row}", ref("po_line", po.id))
    else:
        put("po_released", None)
    if m:
        put("mfc_issued", m.mfc_issued, f"milestones row {m.src_row}", ref("milestone", m.id))
        put("inspected", m.inspection_done, f"milestones row {m.src_row}", ref("milestone", m.id))
        put("dispatched", m.dispatch_clearance, f"milestones row {m.src_row}", ref("milestone", m.id))
    else:
        for k in ("mfc_issued", "inspected", "dispatched"):
            put(k, None, state="na")
    got = last_receipt(session, po.id) if po else None
    first_101 = None
    if po:
        from app.domain.receipts.model import Receipt  # noqa: PLC0415

        first_101 = session.scalar(select(Receipt.posting_date).where(Receipt.po_line_id == po.id, Receipt.movement == "101").order_by(Receipt.posting_date).limit(1))
    put("received", first_101, f"receipts (MB51) for {po.id}" if first_101 else None, ref("po_line", po.id) if po else None)
    ip = invoiced_paid(session, po.po_no) if po else {}
    put("invoiced", ip.get("first_invoice"), f"vendor_ledger row {ip.get('first_invoice_row')}" if ip.get("first_invoice") else None)
    put("paid", ip.get("last_payment"), f"vendor_ledger row {ip.get('last_payment_row')}" if ip.get("last_payment") else None)
    closed = po is not None and po.status == "received" and ip.get("open_invoices") == 0 and ip.get("invoiced", 0) > 0
    put("closed", (ip.get("last_payment") or got) if closed else None)
    if pr and pr.status in ("deleted", "closed") and not po:
        for k in ORDER[3:]:
            if rungs[k].state == "todo":
                rungs[k] = rungs[k].model_copy(update={"state": "na", "unknown": f"PR {pr.status} on {pr.changed_on or '?'}"})

    # whose move each wait was
    spec = _spec_queries(session).get(pr.pr_no) if pr else None
    asked = None
    if spec and s:
        import re  # noqa: PLC0415

        for qq in session.scalars(select(Quote).where(Quote.cs_no == s.cs_no)):
            hit = re.search(r"asked (\d{2})\.(\d{2})\.(\d{4})", qq.remarks or "")
            if hit:
                asked = f"{hit.group(3)}-{hit.group(2)}-{hit.group(1)}"
                break
    held_mfc = bool(m and not m.mfc_issued and m.remarks and "(Projects)" in m.remarks)
    lc = _lcs(session).get(po.po_no) if po else None
    terms = (lookups.answers().get("payment_terms") or {}).get(po.payment_terms or "", {}) if po else {}
    cs_value = (s.l1_rate or 0) * sum((pr_lines(session)[x].qty or 0) for x in (s.pr_line_ids or "").split(",") if x in pr_lines(session)) if s and s.l1_rate else 0
    above = bool(cs_value) and doa.decide(session, doa.CS, cs_value).countersign is not None

    def who(key: str) -> tuple[str, str]:
        if key == "pr_released":
            return "Projects", "the project head releases a PR"
        if key == "rfq_sent":
            return "SCM", "SCM sends the RFQ once the PR is released"
        if key == "quotes_in":
            if spec:
                return "Projects", f"the vendors cannot quote until Projects sends the specification (mail of {spec.message_id[:10]})"
            return "Vendor", "the vendors quote"
        if key == "cs_approved":
            if spec:
                return "Projects", f"a vendor waits for the specification from Projects ({spec.message_id[:10]})"
            if above:
                return "Management", "the CS is above the DoA threshold: the Head of SCM approves"
            return "SCM", "SCM compares the quotes and approves the CS"
        if key == "po_released":
            return "SCM", "SCM releases the PO once the CS is approved"
        if key == "mfc_issued":
            return ("Projects", "the MFC is held for site readiness (the expediting tracker)") if held_mfc else ("SCM", "SCM issues the MFC")
        if key == "inspected":
            return ("QA", "the vendor has called for inspection: QA inspects") if m and m.inspection_call else ("Vendor", "the vendor manufactures")
        if key == "dispatched":
            if lc and not lc.issued_on:
                return "Finance", "an LC must be opened before dispatch"
            if terms.get("before_dispatch"):
                return "Finance", "payment is due before dispatch"
            return "Vendor", "the vendor dispatches"
        if key in ("received", "invoiced"):
            return "Vendor", "the vendor delivers" if key == "received" else "the vendor invoices"
        if key == "paid":
            return "Finance", "Finance pays the invoice"
        return "SCM", ""

    seq = [rungs[k] for k in ORDER]
    prev_date = None
    waiting_on = waiting_since = None
    held: dict[str, int] = {}
    for i, r in enumerate(seq):
        if r.key in ("needed", "closed") or r.state == "na":
            continue
        if r.key == "pr_raised" or (r.key == "po_released" and pr is None):      # the first record: nothing before it is anyone's wait
            prev_date = r.date if r.state == "done" else prev_date
            continue
        if r.key in ("quotes_in", "cs_approved") and spec and asked and r.state != "done":      # the tracker dates the spec query: Projects' wait starts then
            prev_date = max(prev_date or asked, asked)
        if r.key == "mfc_issued" and m and m.mfc_requested:      # the MFC wait starts when the vendor asks for it; before that is the vendor's own schedule
            prev_date = max(prev_date or m.mfc_requested, m.mfc_requested)
        w, why = who(r.key)
        if r.state == "done":
            d = _days(prev_date, r.date) if prev_date else None
            seq[i] = r.model_copy(update={"held_by": w, "days": d if d is None or d >= 0 else 0, "why": why})
            if d and d > 0:
                held[w] = held.get(w, 0) + d
            prev_date = r.date
        elif waiting_on is None and (pr is None or pr.status not in ("deleted", "closed") or po is not None):
            d = _days(prev_date, today) if prev_date else None
            seq[i] = r.model_copy(update={"state": "now", "held_by": w, "days": d, "why": why})
            waiting_on, waiting_since = w, prev_date
            if d and d > 0:
                held[w] = held.get(w, 0) + d
    if closed:
        waiting_on = None
    subject = ref("po_line", po.id, po.short_text) if po and not pr_line_id else ref("pr_line", pr.id, pr.short_text)
    return Ladder(subject=subject, pr_line=ref("pr_line", pr.id) if pr else None, po_line=ref("po_line", po.id) if po else None, rungs=seq,
                  waiting_on=waiting_on, waiting_since=waiting_since, days_waiting=_days(waiting_since, today) if waiting_since else None, held=held)
