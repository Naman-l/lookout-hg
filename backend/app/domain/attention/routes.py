"""The routes of each kind of case, as a code table (PLAN §8): the label a buyer reads, where it leads (a letter to a vendor's contact on file, a note
to a person inside the company on file, an entry to make in SAP, a decision on record), who it goes to, and its figures from the records: what it
changes, the earliest help, the cost, and the money it commits (ⓢ: a route that commits money takes the DoA's signatures). Nothing is preselected;
Lookout may mark one Recommended (advice, checked against this table).
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.domain import lookups
from app.domain.attention import service
from app.domain.common import AS_OF, EntityRef, Money
from app.domain.doa import service as doa
from app.domain.fmt import en_in, inr, md
from app.domain.values import money, prov, ref

LeadsTo = Literal["request", "internal_note", "note", "record"]


class Recipient(BaseModel):
    name: str | None
    email: str | None
    role: str  # "<vendor> (contact on file)", "Project head, <project>", "Treasury, Finance"
    vendor: EntityRef | None = None
    function: str | None = None  # the function on file an internal note goes to (project_head:<project id>, finance_treasury, ...)


class Route(BaseModel):
    kind: str
    label: str
    leads_to: LeadsTo
    to: list[Recipient] = []
    changes: str = ""
    earliest: str | None = None
    earliest_basis: str = ""
    cost: Money | None = None
    cost_basis: str = ""
    commits: Money | None = None  # ⓢ
    document: str = doa.REQUEST
    countersign: str | None = None  # the second signature the DoA requires for this route, by name
    doa_line: str | None = None
    also_start: bool = False
    also_why: str = ""
    by: str | None = None


def _rs(amount: float, rule: str) -> Money:
    return money(amount, prov("computed", "routes", rule=rule, by="attention.routes"))


def vendor_to(session: Session, ident: str | None) -> list[Recipient]:
    if not ident:
        return []
    name, email = lookups.contact_on_file(session, ident)
    return [Recipient(name=name, email=email, role=f"{lookups.vendor_name(session, ident)} (contact on file)", vendor=ref("supplier", ident, lookups.vendor_name(session, ident)))]


def person_to(session: Session, function: str, project: str | None = None) -> list[Recipient]:
    c = lookups.contact_for(session, function, project)
    if c is None:
        return []
    role = (c.title or function.replace("_", " ").title()) + (f", {lookups.project_name(session, project)}" if project and c.project_id else "")
    if function in ("project_head", "planner"):
        role = {"project_head": "Project head", "planner": "Planning engineer"}[function] + (f", {lookups.project_name(session, project)}" if project else "")
    return [Recipient(name=c.name, email=c.email, role=role, function=c.id)]


def member_to(session: Session, member) -> list[Recipient]:
    return [Recipient(name=member.name, email=member.email, role=member.role, function=f"member:{member.id}")] if member else []


def countersign_for(session: Session, document: str, value: float, owner_id: str | None) -> tuple[str | None, str]:
    """Who signs second on a route that commits `value`: the Head of SCM above the DoA threshold; the member the owner reports to (the organogram's
    line: their GM, or the Head for a GM) when the value is above the owner's own limit; else nobody."""
    d = doa.decide(session, document, value)
    if d.countersigner:
        return d.countersigner, d.line
    owner = lookups.team(session).get(owner_id or "")
    if owner and owner.signs_upto is not None and value > owner.signs_upto:
        who = lookups.lead_of(session, owner) or lookups.head(session)
        return (who.name if who else None), f"{inr(value)}: above {owner.name.split()[0]}'s limit of {inr(owner.signs_upto)}, also needs {who.name if who else '—'}"
    return None, d.line


def commit(route: Route, session: Session, value: float, document: str, owner_id: str | None, rule: str) -> Route:
    who, line = countersign_for(session, document, value, owner_id)
    return route.model_copy(update=dict(commits=_rs(value, rule), document=document, countersign=who, doa_line=line))


def _l1_vendor(cs) -> str | None:
    return cs.l1.vendor.id if cs and cs.l1 and cs.l1.vendor else None


def _quoted_vendors(session: Session, d) -> list[str]:
    from app.domain.quotes.model import Quote  # noqa: PLC0415

    ids = []
    for pl in d.pr_lines:
        for q in session.query(Quote).filter(Quote.pr_line_id == pl.ref.id, Quote.rate.is_not(None)):
            if q.identity_id and q.identity_id not in ids:
                ids.append(q.identity_id)
    return ids


def _reply_window(act_by: str | None) -> str:
    if not act_by:
        return (AS_OF + timedelta(days=5)).isoformat()
    due = date.fromisoformat(act_by)
    if due <= AS_OF:
        return (AS_OF + timedelta(days=3)).isoformat()
    return min(due, max(AS_OF + timedelta(days=5), due - timedelta(days=14))).isoformat()


def routes(session: Session, key: str, owner: str | None = None) -> list[Route]:
    """The routes of the case, with their figures. Empty for a held message (it has controls instead) and for an unknown key."""
    d = service.item_detail(session, key)
    if d is None or d.tab == "trust":
        return []
    k = d.kind
    owner_id = (lookups.member_of(session, owner).id if lookups.member_of(session, owner) else None) or (d.owner_ids[0] if d.owner_ids else None)
    pid = d.projects[0].id if d.projects else None
    vend = d.vendor.ref.id if d.vendor else None
    amount = float(d.at_stake.amount) if d.at_stake is not None and hasattr(d.at_stake, "amount") else 0.0
    R: list[Route] = []
    if k == "pr-late":
        cs = d.cs
        l1 = _l1_vendor(cs)
        stockist = next((q for q in (cs.quotes if cs else []) if q.remarks and re.search(r"ex-stock", q.remarks, re.I)), None)
        lead = next((n for n in (f.fact for f in d.findings) if "lead time" in n), "")
        R.append(Route(kind="expedite_l1", label=f"Expedite with the L1 vendor · {cs.l1.vendor_name if cs and cs.l1 else 'L1'}", leads_to="request", to=vendor_to(session, l1),
                       changes="Asks the L1 vendor for its fastest dispatch and any part-quantity before the need date", earliest=None,
                       earliest_basis="the vendor's answer: its quote says " + (cs.l1.remarks if cs and cs.l1 and cs.l1.remarks else "no date")))
        if stockist:
            m = re.search(r"(\d+)\s*KM ex-stock in (\d+) weeks", stockist.remarks or "", re.I)
            part = float(m.group(1)) if m else None
            when = (AS_OF + timedelta(weeks=int(m.group(2)))).isoformat() if m else None
            prem = (float(stockist.rate.amount) - float(cs.l1.rate.amount)) * part if part and cs.l1 and cs.l1.rate else None
            r = Route(kind="stockist_partial", label=f"Partial from the stockist · {stockist.vendor_name}", leads_to="request", to=vendor_to(session, stockist.vendor.id if stockist.vendor else None),
                      changes=f"{en_in(part)} KM early from stock; the balance from L1" if part else "Part early from stock", earliest=when,
                      earliest_basis=f"the stockist's quote: {stockist.remarks}", cost=_rs(prem, f"({inr(float(stockist.rate.amount))} - L1 {inr(float(cs.l1.rate.amount))}) x {en_in(part)} KM") if prem else None,
                      cost_basis="the stockist's premium over L1 on the part it supplies")
            if part:
                r = commit(r, session, float(stockist.rate.amount) * part, doa.COMMITMENT, owner_id, "stockist rate x quantity from stock")
            R.append(r)
        R.append(Route(kind="resequence", label="Re-sequence the work front", leads_to="internal_note", to=person_to(session, "planner", pid),
                       changes="Asks the planner to move the front's start to when the cable can arrive", cost=None, cost_basis="not in the records (site cost of the delay)"))
        R.append(Route(kind="accept_later", label="Accept the later date", leads_to="record", changes="Records that the front starts when the cable arrives",
                       cost=None, cost_basis="the front's delay, not in the records"))
    elif k == "pr-stuck":
        R.append(Route(kind="ask_projects", label="Ask Projects for the spec or a firm date", leads_to="internal_note", to=person_to(session, "planner", pid),
                       changes="Puts the wait on record with Projects and asks for the specification by a date", earliest=_reply_window(d.act_by), earliest_basis="the reply asked for"))
        lead = lookups.vertical_lead(session, d.verticals[0]) if d.verticals else None
        R.append(Route(kind="escalate_cs", label="Escalate the CS approval", leads_to="internal_note", to=member_to(session, lead), changes="Asks the approver to clear the CS"))
        R.append(Route(kind="reissue_rfq", label="Re-issue the RFQ to more library vendors", leads_to="request", to=[r for v in _quoted_vendors(session, d)[:3] for r in vendor_to(session, v)],
                       changes="Asks again with the specification attached"))
        R.append(Route(kind="close_not_required", label="Close as not required", leads_to="internal_note", to=person_to(session, "project_head", pid),
                       changes="Asks the project head to approve closing the PR"))
    elif k == "pr-cancelled":
        vids = _quoted_vendors(session, d)
        validity = d.act_by
        R.append(Route(kind="cancel_approval", label="Request cancellation approval, with reason", leads_to="internal_note", to=person_to(session, "project_head", pid),
                       changes="Asks the project head to approve the short-close in writing, with the reason and who is accountable for the spent enquiry"))
        R.append(Route(kind="hold_quotes", label="Ask vendors to hold their quotes", leads_to="request", to=[r for v in vids for r in vendor_to(session, v)],
                       changes=f"Asks {len(vids)} vendors to hold their quoted prices for 60 days", earliest=validity, earliest_basis="the earliest quote lapses then",
                       also_start=bool(validity and d.act_by and validity <= d.act_by), by=validity, also_why=f"the quotes lapse from {md(validity)}, on or before the act-by" if validity else ""))
        R.append(Route(kind="regret", label="Close and send regret letters", leads_to="request", to=[r for v in vids for r in vendor_to(session, v)],
                       changes="Tells each vendor the enquiry is closed"))
        R.append(Route(kind="record_effort", label="Record the effort spent", leads_to="record", changes="Records the RFQs and quotes spent on lines Projects cancelled"))
    elif k == "mfc-validity":
        l = d.po_lines[0] if d.po_lines else None
        claim = amount
        r = Route(kind="issue_mfc", label="Issue the MFC now", leads_to="request", to=vendor_to(session, vend), changes="Holds the firm price and the slot; manufacturing starts",
                  earliest=AS_OF.isoformat(), earliest_basis="today", cost=_rs(0, "the firm price holds"), cost_basis=f"avoids {inr(claim)} after the validity")
        if l:
            r = commit(r, session, float(l.value.amount), doa.MFC, owner_id, "the PO value released for manufacture")
        R.append(r)
        R.append(Route(kind="extend_validity", label="Extend the PO validity at the firm price", leads_to="request", to=vendor_to(session, vend),
                       changes="Asks the vendor to hold the firm price past the validity", earliest=_reply_window(d.act_by), earliest_basis="the reply asked for",
                       cost=None, cost_basis="the vendor's answer"))
        R.append(Route(kind="defer_accept_pv", label="Defer, and accept the price rise", leads_to="record", changes="Records the deferral and its cost",
                       cost=_rs(claim, "the vendor's stated rise after the validity") if claim else None, cost_basis="the vendor's stated rise"))
    elif k == "inspection-ready":
        stake = amount
        R.append(Route(kind="inspect_hold", label="Inspect now, hold dispatch", leads_to="request", to=vendor_to(session, vend),
                       changes="Confirms the inspection date and asks the vendor to hold dispatch until the plinth is ready", cost=_rs(stake, "storage after the free period") if stake else None,
                       cost_basis="storage until the site is ready, at the vendor's rate"))
        R.append(Route(kind="ask_plinth", label="Ask the site for the plinth-ready date", leads_to="internal_note", to=person_to(session, "planner", pid),
                       changes="Asks the planner to confirm when the plinth can take the transformer"))
        r = Route(kind="store_at_works", label="Store at the vendor's works", leads_to="request", to=vendor_to(session, vend), changes="Accepts storage at the vendor's works at its rate",
                  cost=_rs(stake, "storage after the free period") if stake else None, cost_basis="computed from the vendor's rate")
        if stake:
            r = commit(r, session, stake, doa.COMMITMENT, owner_id, "storage charges")
        R.append(r)
    elif k == "commissioning":
        R.append(Route(kind="ask_commissioning", label="Ask Projects for a commissioning date", leads_to="internal_note", to=person_to(session, "planner", pid),
                       changes="Asks the site to commission before the warranty ends"))
        r = Route(kind="accept_extension", label="Accept the warranty extension at the quoted price", leads_to="request", to=vendor_to(session, vend),
                  changes="12 months of warranty from commissioning", cost=_rs(amount, "the vendor's extension price") if amount else None, cost_basis="the vendor's quote")
        if amount:
            r = commit(r, session, amount, doa.COMMITMENT, owner_id, "the extension price")
        R.append(r)
        R.append(Route(kind="record_loss", label="Record the warranty loss", leads_to="record", changes="Records that the warranty lapses unused"))
    elif k == "schedule-slip":
        R.append(Route(kind="hold_original", label="Hold the original date, or a partial dispatch", leads_to="request", to=vendor_to(session, vend),
                       changes="Asks the vendor to keep the PO date, or dispatch part of the quantity by the need date", earliest=_reply_window(d.act_by), earliest_basis="the reply asked for"))
        R.append(Route(kind="resequence", label="Re-sequence the work front", leads_to="internal_note", to=person_to(session, "planner", pid), changes="Asks the planner to move the front"))
        R.append(Route(kind="accept_new_date", label="Accept the new date (to enter in SAP)", leads_to="note", changes="The PO lines' delivery dates, to change in SAP"))
    elif k == "pv-longlead":
        head = lookups.head(session)
        value = sum(float(n.value.amount) for n in d.numbers if False) or sum(x.value for x in __import__("app.domain.lookahead.service", fromlist=["items"]).items(session) if x.project == pid and x.price_basis == "PV" and not x.ordered)
        r = Route(kind="order_now", label="Order now", leads_to="internal_note", to=member_to(session, head), changes="Asks the Head of SCM to release the order now, before the next index rise",
                  cost=_rs(0, "orders at today's index"), cost_basis=f"stops the {inr(amount)} a month")
        R.append(commit(r, session, value, doa.COMMITMENT, owner_id, "the items' value"))
        vids = []
        from app.domain.orders.service import all_lines  # noqa: PLC0415

        for x in __import__("app.domain.lookahead.service", fromlist=["items"]).items(session):
            if x.project == pid and x.material:
                last = max((l for l in all_lines(session).values() if l.material == x.material), key=lambda l: l.doc_date, default=None)
                if last and last.identity_id not in vids:
                    vids.append(last.identity_id)
        R.append(Route(kind="negotiate_firm", label="Negotiate a firm price for 6 months", leads_to="request", to=[r for v in vids for r in vendor_to(session, v)],
                       changes="Asks the vendors on file for these items to quote firm for 6 months", cost=None, cost_basis="the vendors' answers"))
        R.append(Route(kind="wait_funding", label="Wait for funding", leads_to="record", changes="Records the wait and its cost", cost=_rs(amount, "a month's delay"),
                       cost_basis="each month it waits"))
    elif k == "price-notice":
        exposed = float(d.at_stake.amount) / 2500 if d.at_stake is not None else 0
        from app.domain.orders.service import all_lines  # noqa: PLC0415

        rate = max((l for l in all_lines(session).values() if l.identity_id == vend), key=lambda l: l.doc_date, default=None)
        r = Route(kind="buy_ahead", label="Buy ahead before the effective date", leads_to="request", to=vendor_to(session, vend),
                  changes="Orders the requirement not yet on PO, acknowledged at today's rate", cost=_rs(-amount, "the rise avoided"), cost_basis=f"saves {inr(amount)}",
                  earliest=d.act_by, earliest_basis="orders acknowledged by then keep today's rate")
        if rate and exposed:
            r = commit(r, session, rate.rate_base * exposed, doa.COMMITMENT, owner_id, "today's rate x the quantity not on PO")
        R.append(r)
        R.append(Route(kind="alternate_vendor", label="Move to an alternate library vendor", leads_to="note", changes="A note to compare the other TMT vendors on file"))
        R.append(Route(kind="accept_price", label="Accept the new price", leads_to="record", cost=_rs(amount, "the rise on the uncovered quantity"), cost_basis="the rise"))
    elif k == "pv-claim":
        comp = next((float(n.value.amount) for n in d.numbers if n.id.endswith(":computed")), None)
        claimed = next((float(n.value.amount) for n in d.numbers if n.id.endswith(":claimed")), None)
        R.append(Route(kind="reply_computed", label="Reply with the computed PV, rights reserved", leads_to="request", to=vendor_to(session, vend),
                       changes=f"Offers {inr(comp, exact=True)} on the PO's base month" if comp else "Offers the PV on the PO's base month",
                       cost=_rs(comp, "PV on the PO's clause") if comp else None, cost_basis="what the clause owes"))
        R.append(Route(kind="ask_evidence", label="Ask for the index evidence", leads_to="request", to=vendor_to(session, vend), changes="Asks for the IEEMA circulars for both months"))
        R.append(Route(kind="accept_claim", label="Accept the claim", leads_to="record", cost=_rs(claimed, "the claim as made") if claimed else None,
                       cost_basis=f"{inr(amount, exact=True)} more than the clause" if amount else ""))
    elif k in ("quote-lapse", "l1-above-last"):
        l1v = vend or next((r.id for r in d.refs if r.type == "supplier"), None)
        if k == "l1-above-last":
            from app.domain.quotes.model import Quote  # noqa: PLC0415

            qs = [session.get(Quote, r.id) for r in d.refs if r.type == "quote"]
            qs = [q for q in qs if q and q.rate is not None]
            l1q = min(qs, key=lambda q: q.rate) if qs else None
            l1v = l1q.identity_id if l1q else l1v
            last = next((float(n.value.amount) for n in d.numbers if n.id.endswith(":last")), None)
            award_value = (l1q.rate * (l1q.qty or 0)) if l1q else 0
            others = [q.identity_id for q in qs if q.identity_id]
        else:
            last, award_value, others = None, amount, [vend] if vend else []
        R.append(Route(kind="extension", label="Ask for an extension", leads_to="request", to=vendor_to(session, l1v), changes="Asks the vendor to hold the price past its validity",
                       earliest=d.act_by, earliest_basis="before it lapses"))
        R.append(Route(kind="negotiate_last", label="Negotiate against the last price", leads_to="request", to=vendor_to(session, l1v),
                       changes=f"Asks L1 to match the last PO rate of {inr(last)}" if last else "Asks L1 for its best price", cost=_rs(-amount, "L1 down to the last rate") if last else None,
                       cost_basis=f"saves up to {inr(amount)}" if last else ""))
        r = Route(kind="award_anyway", label="Award anyway, with a reason", leads_to="record", changes="Records the award at L1 and the reason")
        if award_value:
            r = commit(r, session, award_value, doa.CS, owner_id, "L1 x quantity")
        R.append(r)
        R.append(Route(kind="retender", label="Re-tender", leads_to="request", to=[x for v in others[:3] for x in vendor_to(session, v)], changes="Asks again, with the last rate as the reference"))
    elif k == "rate-spread":
        R.append(Route(kind="ask_why", label="Ask each site's buyer why", leads_to="note", changes="One question per site above the median, to its buyer"))
        R.append(Route(kind="retender_sites", label="Re-tender the sites above the median", leads_to="note", changes="A note to re-tender those sites' next quarter"))
        R.append(Route(kind="record_explained", label="Record the spread as explained", leads_to="record"))
    elif k in ("lc", "abg"):
        R.append(Route(kind="ask_finance", label="Ask Finance to open the LC" if k == "lc" else "Ask Finance to hold the invocation; vendor to renew", leads_to="internal_note",
                       to=person_to(session, "finance_treasury"), changes="Puts the date on record with Treasury", earliest=_reply_window(d.act_by), earliest_basis="the reply asked for"))
        R.append(Route(kind="vendor_extend", label="Ask the vendor to extend the deadline" if k == "lc" else "Ask the vendor to renew the ABG by 6 months", leads_to="request",
                       to=vendor_to(session, vend), changes="Asks the vendor in writing"))
    elif k == "fund-mismatch":
        mis = lookups.mis(session)
        R.append(Route(kind="ask_mis", label="Correct the fund sheet with the requirement", leads_to="internal_note", to=member_to(session, mis) if owner_id != (mis.id if mis else None) else person_to(session, "finance_funds"),
                       changes="Sends Finance the corrected heads" if owner_id == (mis.id if mis else None) else "Asks MIS to correct the heads", earliest=d.act_by, earliest_basis="Finance's date"))
        R.append(Route(kind="ask_projects", label="Ask Projects to confirm the requirement", leads_to="internal_note",
                       to=[r for p in [x.id for x in d.projects][:4] for r in person_to(session, "planner", p)], changes="Asks each planner to confirm the month's requirement"))
        R.append(Route(kind="accept_fund", label="Accept the fund figure", leads_to="record"))
    elif k == "late-streak":
        sole = d.vendor is not None and len(d.vendor.library) <= 1
        R.append(Route(kind="firm_dates", label="Ask for firm dates", leads_to="request", to=vendor_to(session, vend), changes="Asks for a firm date on every open line",
                       earliest=_reply_window(d.act_by), earliest_basis="the reply asked for"))
        R.append(Route(kind="alternate_vendor", label="Line up an alternate library vendor", leads_to="note", changes="A note to quote the next library vendor for the open lines",
                       also_start=True, also_why=d.vendor.streak_line if d.vendor else "late on its last receipts"))
        R.append(Route(kind="ld_reminder", label="Remind it of the LD clause", leads_to="request", to=vendor_to(session, vend), changes="Reminds the vendor of liquidated damages"))
        R.append(Route(kind="recheck", label="Re-check on a date", leads_to="record"))
    elif k == "supply-stop":
        R.append(Route(kind="alt_supply", label="Confirm alternate supply and rate", leads_to="request", to=vendor_to(session, vend) if vend else [],
                       changes="Asks the vendor for supply from another source and its rate"))
        R.append(Route(kind="stockpile", label="Draw from the site stockpile", leads_to="internal_note", to=[r for p in [x.id for x in d.projects][:3] for r in person_to(session, "planner", p)],
                       changes="Asks the site how many days its stockpile covers"))
        R.append(Route(kind="tell_projects", label="Tell Projects the expected slowdown", leads_to="internal_note",
                       to=[r for p in [x.id for x in d.projects][:3] for r in person_to(session, "project_head", p)], changes="Warns the project heads"))
    elif k == "inspection-fail":
        head = lookups.head(session)
        r = Route(kind="supply_po_oem", label="Switch to a supply PO from an approved OEM", leads_to="internal_note", to=member_to(session, head),
                  changes="Asks the Head of SCM to approve a supply PO; the contractor keeps laying only")
        R.append(commit(r, session, amount, doa.COMMITMENT, owner_id, "the WO's supply value, re-bought") if amount else r)
        R.append(Route(kind="reinspect", label="Re-inspect the contractor's material", leads_to="internal_note", to=person_to(session, "qa"), changes="Asks QA for a re-test"))
    elif k == "renamed":
        R.append(Route(kind="verify_entity", label="Verify the new entity and ask for its GST certificate", leads_to="request", to=vendor_to(session, vend),
                       changes="Asks for the GST certificate; verify by phone with the contact on file"))
        R.append(Route(kind="amend_pos", label="Amend the open POs to the new code (in SAP)", leads_to="note", changes="The open lines to move to the new code in SAP"))
        R.append(Route(kind="keep_old", label="Keep the old code until verified", leads_to="record"))
    elif k == "unknown":
        R.append(Route(kind="ask_owner", label="One question to each owner", leads_to="note", changes="Logs each question for the person who can answer it"))
    for r in R:
        if r.leads_to == "request" and not r.to:
            r.changes = (r.changes + " (no contact on file: nothing can be drafted)").strip()
    return R
