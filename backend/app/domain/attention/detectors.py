"""The detectors: one function per kind of case, code only, each reading the records and the dated facts read from mail. A detector returns the
case in full (the detail a case page shows) and, on a case that spans several SCM members, each member's own share.

Rules (PLAN §7). ₹ at stake carries its rule as provenance; where it cannot be computed it is an Unknown with an owner. Owner: the SCM member on
the lines' purchasing group (a team case has several, each seeing their share). Waiting on: the detector's reading, which the ledger overrides once
a note goes out. Keys are frozen: a key names the case's cause, never a row number.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import lookups
from app.domain.attention.schema import (ActionItemDetail, DatedRow, Deadline, Finding, HeldMessage, Number, ProjectPanel, SiteImpact, VendorPanel)
from app.domain.common import AS_OF, EntityRef
from app.domain.doa import service as doa
from app.domain.fmt import count, dmy, en_in, inr, md, month_year, qty_text
from app.domain.inbox import trust as trust_rules
from app.domain.inbox.model import Message, MessageEvent, MessageRef
from app.domain.indices import service as indices
from app.domain.lookahead.service import items as lookahead_items
from app.domain.milestones.model import Milestone
from app.domain.orders import service as orders
from app.domain.payments.service import guarantees
from app.domain.phases.ladder import ladder
from app.domain.prs import service as prs
from app.domain.quotes import service as quotes
from app.domain.quotes.model import ComparativeStatement, Quote
from app.domain.receipts.service import delivery
from app.domain.requirements import service as req
from app.domain.suppliers.service import library_verticals, msme_due
from app.domain.values import money, prov, qty, ref, unknown

TODAY = AS_OF.isoformat()


@dataclass
class Found:
    item: ActionItemDetail
    shares: dict[str, dict] = field(default_factory=dict)  # member id -> the fields of their slice
    fold_into: str | None = None  # the key of the case this one folds under (it stays resolvable by its own key)


# ------------------------------------------------------------------------------------------------------------------------------- helpers
def left(d: str | None) -> int | None:
    return (date.fromisoformat(d[:10]) - AS_OF).days if d else None


def owners(session: Session, ids: list[str]) -> dict:
    ids = [i for i in dict.fromkeys(ids) if i in lookups.team(session)]
    return dict(owner=" · ".join(lookups.member_name(session, i) for i in ids), owner_ids=ids)


def rs(amount: float, rule: str, inputs: list[EntityRef] | None = None, source: str = "computed", row: str | None = None, raw: str | None = None, method: str = "computed"):
    return money(amount, prov(method, source, row=row, raw=raw, inputs=inputs or [], rule=rule, by="attention.detectors"))


def events(session: Session, kind: str | tuple[str, ...]) -> list[MessageEvent]:
    kinds = (kind,) if isinstance(kind, str) else kind
    return list(session.scalars(select(MessageEvent).where(MessageEvent.kind.in_(kinds)).order_by(MessageEvent.id)))


def msg(session: Session, mid: str) -> Message | None:
    return session.get(Message, mid)


def msg_ref(session: Session, mid: str) -> EntityRef:
    m = msg(session, mid)
    return ref("message", mid, m.subject if m else None)


def addressee(session: Session, mid: str) -> list[str]:
    """The SCM members a message is addressed to (To, in order), by the address on file."""
    m = msg(session, mid)
    if m is None:
        return []
    by_mail = {(b.email or "").lower(): b.id for b in lookups.team(session).values()}
    return [by_mail[a.strip().lower()] for a in (m.to_addrs or "").split(",") if a.strip().lower() in by_mail]


def vendor_panel(session: Session, ident: str | None) -> VendorPanel | None:
    if not ident or ident not in lookups.identities(session):
        return None
    recs = lookups.records_of(session).get(ident, [])
    d = delivery(session, ident)
    name, email = lookups.contact_on_file(session, ident)
    from app.domain.orders.service import all_lines  # noqa: PLC0415

    terms = lookups.answers().get("payment_terms") or {}
    return VendorPanel(ref=ref("supplier", ident, lookups.vendor_name(session, ident)), name=lookups.vendor_name(session, ident), codes=[r.record_id for r in recs],
                       gstin=recs[-1].gstin if recs else None, msme=any(r.msme for r in recs), msme_due_45=len(msme_due(session, ident)),
                       on_time=f"on time {d.on_time_pct}% ({d.on_time}/{d.n})" if d.n else "no receipts on file", avg_days_late=d.avg_days_late, streak_line=d.line if d.streak else "",
                       terms=sorted({(terms.get(l.payment_terms) or {}).get("label", l.payment_terms or "") for l in all_lines(session).values()
                                     if l.identity_id == ident and l.status == "open" and l.payment_terms}),
                       library=library_verticals(session, ident), contact=name, contact_email=email)


def project_panel(session: Session, pid: str | None) -> ProjectPanel | None:
    p = lookups.projects(session).get(pid or "")
    if p is None:
        return None
    tats = [v.turnaround_days for v in (prs.view(session, l) for l in prs.all_lines(session).values() if l.project_id == pid and l.status == "converted")
            if v.turnaround_days is not None]
    return ProjectPanel(ref=ref("project", p.id, p.name), vertical=lookups.VERTICAL_NAMES.get(p.vertical, p.vertical), stage=p.stage.replace("_", " "),
                        plants=lookups.plants_of(session).get(p.id, []), head=p.head_name, planner=p.planner_name,
                        median_pr_po_days=round(statistics.median(tats), 1) if tats else None)


def proj_ref(session: Session, pid: str | None) -> EntityRef | None:
    return ref("project", pid, lookups.project_name(session, pid)) if pid else None


def verticals_of(session: Session, pids: list[str]) -> list[str]:
    return [v for v in lookups.VERTICALS if v in {lookups.vertical_of_project(session, p) for p in pids}]


def impact(session: Session, pid: str | None, materials: list[str], need: str | None, why: str) -> list[SiteImpact]:
    """The fronts of the project that consume these materials stop from `need` (up to: site stock is not in the data)."""
    if not pid or not need:
        return []
    return [SiteImpact(project=proj_ref(session, pid), front=f, month=need[:7], stops_on=need, why=why) for f in req.fronts_for(session, pid, materials)]


def deadline(what: str, d: str | None, source: str) -> list[Deadline]:
    return [Deadline(what=what, date=d, source=source, days_left=left(d))] if d else []


def item(session: Session, *, key: str, kind: str, tab: str, title: str, summary: str, owner_ids: list[str], waiting_on: str, projects: list[str],
         at_stake=None, label: str = "at stake", rule: str = "", act_by: str | None = None, severity: str = "medium", next_action: str = "", **detail) -> ActionItemDetail:
    pids = [p for p in projects if p]
    return ActionItemDetail(key=key, kind=kind, tab=tab, severity=severity, title=title, summary=summary, at_stake=at_stake, at_stake_label=label,
                            at_stake_rule=rule, act_by=act_by, days_left=left(act_by), waiting_on=waiting_on, verticals=verticals_of(session, pids),
                            projects=[proj_ref(session, p) for p in pids], next_action=next_action, **owners(session, owner_ids), **detail)


def pr_value(session: Session, l) -> tuple[float | None, str]:
    """A PR line's value: its quantity at the last PO rate at the plant (else anywhere), else the budget rate for the project, else unknown."""
    v = prs.view(session, l)
    if v.value is not None:
        return float(v.value.amount), "PR quantity x the last PO rate for the material at the plant"
    b = quotes.budget_rate(session, l.project_id, l.material)
    if b:
        return (l.qty_base or l.qty) * b.rate, "PR quantity x the project's budget rate (no PO on file for the material)"
    return None, ""


def lead_days(session: Session, material: str | None) -> tuple[int | None, str]:
    m = lookups.materials(session).get(material or "")
    if m and m.lead_days:
        return m.lead_days, "the material master's planned delivery time"
    la = next((x for x in lookahead_items(session) if x.material == material), None)
    if la:
        return int(la.lead.split("-")[-1].split()[0]) * 30 if la.lead else None, "the look-ahead's lead time"
    return None, ""


# ------------------------------------------------------------------------------------------------------------------------------- Requirement
def pr_late(session: Session) -> list[Found]:
    """An open PR whose needed-by minus its creation date is shorter than the material's lead time: it cannot arrive in time by the normal route."""
    out = []
    by_pr: dict[str, list] = defaultdict(list)
    for l in prs.all_lines(session).values():
        if l.status != "open" or not l.needed_by:
            continue
        lead, _ = lead_days(session, l.material)
        if lead and (date.fromisoformat(l.needed_by) - date.fromisoformat(l.created)).days < lead:
            by_pr[l.pr_no].append(l)
    for pr_no, lines in by_pr.items():
        l = lines[0]
        lead, lead_src = lead_days(session, l.material)
        earliest = (AS_OF + timedelta(days=lead)).isoformat()
        vals = [pr_value(session, x) for x in lines]
        total = sum(v for v, _ in vals if v)
        mname = lookups.materials(session)[l.material].description if l.material in lookups.materials(session) else l.short_text
        msgs = sorted({r.message_id for r in session.scalars(select(MessageRef).where(MessageRef.ref_type == "pr", MessageRef.ref_id == pr_no, MessageRef.quoted == 0))})
        cs = prs.view(session, l).cs
        cv = quotes.cs(session, cs) if cs else None
        quick = [q for q in (cv.quotes if cv else []) if q.remarks and re.search(r"ex-stock|stockist", q.remarks, re.I)]
        pname = lookups.project_name(session, l.project_id)
        f = [Finding(key="lead_time", fact=f"Raised {md(l.created)} for {md(l.needed_by)}: {(date.fromisoformat(l.needed_by) - date.fromisoformat(l.created)).days} days against a lead time of {lead} days ({lead_src})",
                     meaning=f"By the normal route the earliest delivery is about {md(earliest)}, {(date.fromisoformat(earliest) - date.fromisoformat(l.needed_by)).days} days after the site needs it", refs=[ref("pr_line", l.id)])]
        if cv and cv.quotes_in:
            f.append(Finding(key="quotes_in", fact=f"{cv.quotes_in} quotes in on {cv.cs}; L1 {cv.l1.vendor_name if cv.l1 else '—'} at {inr(float(cv.l1.rate.amount)) if cv.l1 and cv.l1.rate else '—'} per {l.uom}",
                             meaning="The CS can be approved now; the delivery each vendor states decides whether any part arrives in time", refs=[ref("cs", cv.cs)]))
        for q in quick:
            f.append(Finding(key="stockist", fact=f"{q.vendor_name}: {q.remarks}", meaning="A stockist can cover part of the need early, at its price", refs=[q.ref]))
        it = item(session, key=f"pr-late:{pr_no}", kind="pr-late", tab="requirement", severity="high",
                  title=f"{pname}: {mname} PR cannot arrive by {md(l.needed_by)}",
                  summary=f"Requirement · needed {md(l.needed_by)} · lead time {lead} days · {count(len(cv.quotes) if cv else 0, 'quote')} in",
                  owner_ids=[x.buyer_id for x in lines], waiting_on="SCM", projects=[l.project_id],
                  at_stake=rs(total, "PR quantity x the last PO rate for the material at the plant", [ref("pr_line", x.id) for x in lines]) if total else
                  unknown("PR value", "no PO or budget rate on file for the material", l.buyer_id or "unassigned", f"What is the expected rate for {mname}?"),
                  rule="PR quantity x the last PO rate for the material at the plant (else the budget rate)", act_by=l.needed_by,
                  next_action="Expedite with the L1 vendor, take part from the stockist, or re-sequence the work front.",
                  finding=f"The site needs it {md(l.needed_by)}; the lead time lands it about {md(earliest)}.", findings=f,
                  numbers=[Number(id=f"pr:{pr_no}:value", label="PR value", value=rs(total, "PR quantity x last PO rate"))] if total else [],
                  pr_lines=[prs.view(session, x) for x in lines], messages=[msg_ref(session, m) for m in msgs], cs=cv,
                  project=project_panel(session, l.project_id), ladder=ladder(session, pr_line_id=l.id),
                  supply=req.supply_by_month(session, l.project_id, [l.material], req.months_ahead()) if l.project_id and l.material else None,
                  deadlines=deadline("Needed at site", l.needed_by, f"pr_lines row {l.src_row}") + deadline("Earliest by lead time", earliest, lead_src),
                  refs=[ref("pr_line", x.id) for x in lines] + [ref("project", l.project_id, pname)] + ([ref("cs", cv.cs)] if cv else []))
        it.site_impact = impact(session, l.project_id, [l.material], l.needed_by, f"needed {md(l.needed_by)}; the lead time lands it about {md(earliest)}")
        out.append(Found(it))
    return out


def pr_stuck(session: Session) -> list[Found]:
    """A released PR not converted past its vertical's turnaround target, shown on its own when a dated mail names the hold, or when it is above ₹25 L
    and the wait is outside SCM (Projects, Management, a vendor): a PR waiting on SCM's own CS is the buyer's queue, on the PR list and Team."""
    targets = lookups.answers().get("turnaround_target_days") or {}
    spec = {e.ref_id: e for e in events(session, "spec_awaited") if e.ref_type == "pr"}
    out = []
    by_pr: dict[str, list] = defaultdict(list)
    for l in prs.all_lines(session).values():
        if l.status != "open" or not l.released:
            continue
        target = targets.get(lookups.vertical_of_project(session, l.project_id) or "")
        if target and (AS_OF - date.fromisoformat(l.released)).days > target:
            by_pr[l.pr_no].append(l)
    for pr_no, lines in by_pr.items():
        total = sum(v for v, _ in (pr_value(session, x) for x in lines) if v)
        l = lines[0]
        L = ladder(session, pr_line_id=l.id)
        if pr_no not in spec and (total <= 25e5 or (L and L.waiting_on == "SCM")):
            continue      # a PR waiting on SCM's own CS is the buyer's queue: it shows on the PR list and Team, not as a case
        lead, lead_src = lead_days(session, l.material)
        act = (date.fromisoformat(l.needed_by) - timedelta(days=lead)).isoformat() if l.needed_by and lead else None
        target = targets.get(lookups.vertical_of_project(session, l.project_id) or "")
        pname = lookups.project_name(session, l.project_id)
        e = spec.get(pr_no)
        msgs = sorted({r.message_id for r in session.scalars(select(MessageRef).where(MessageRef.ref_type == "pr", MessageRef.ref_id == pr_no, MessageRef.quoted == 0))})
        wait = L.waiting_on if L else "SCM"
        held = f"with {wait} for {L.days_waiting} days" if L and L.days_waiting is not None else f"with {wait}"
        it = item(session, key=f"pr-stuck:{pr_no}", kind="pr-stuck", tab="requirement", severity="medium",
                  title=f"{pname}: {l.short_text} PR {held}",
                  summary=f"Requirement · released {md(l.released)} · {(AS_OF - date.fromisoformat(l.released)).days} days against a {target}-day target"
                          + (" · spec awaited from Projects" if e else ""),
                  owner_ids=[x.buyer_id for x in lines], waiting_on=wait if wait in ("SCM", "Projects", "Finance", "QA", "Vendor", "Management") else "SCM",
                  projects=[l.project_id], at_stake=rs(total, "PR quantity x the last PO rate", [ref("pr_line", x.id) for x in lines]) if total else None,
                  rule="PR value: quantity x the last PO rate for the material", act_by=act,
                  next_action="Ask Projects for the specification or a firm date." if e else "Escalate the CS approval or re-issue the RFQ.",
                  finding=f"Released {md(l.released)}; the RFQ went out {md(L.rungs[3].date) if L and L.rungs[3].date else '—'}"
                          + (f"; vendors wait for the specification from Projects since {md(L.waiting_since)}" if e and L else "") + ".",
                  findings=[Finding(key="turnaround", fact=f"{(AS_OF - date.fromisoformat(l.released)).days} days since release; {lookups.VERTICAL_NAMES.get(lookups.vertical_of_project(session, l.project_id), '')} target {target} days",
                                    meaning="Past the target, and the order-by date for its lead time has " + ("passed" if act and act < TODAY else "not yet passed"))]
                  + ([Finding(key="spec", fact=e.detail, meaning=f"The wait is Projects': {L.days_waiting} days so far", refs=[msg_ref(session, e.message_id)])] if e and L else []),
                  pr_lines=[prs.view(session, x) for x in lines], messages=[msg_ref(session, m) for m in msgs], ladder=L, project=project_panel(session, l.project_id),
                  deadlines=deadline("Order by (needed-by less lead time)", act, f"pr_lines row {l.src_row}; {lead_src}") + deadline("Needed at site", l.needed_by, f"pr_lines row {l.src_row}"),
                  refs=[ref("pr_line", x.id) for x in lines] + [ref("project", l.project_id, pname)])
        out.append(Found(it))
    return out


def pr_cancelled(session: Session) -> list[Found]:
    """Five or more PR lines of one project deleted or short-closed on one day after their RFQ went out: the effort spent and the quotes in hand."""
    groups: dict[tuple, list] = defaultdict(list)
    for l in prs.all_lines(session).values():
        if l.status in ("deleted", "closed") and l.changed_on and l.project_id:
            groups[(l.project_id, l.changed_on)].append(l)
    out = []
    for (pid, day), lines in groups.items():
        cs_rows = {}
        for l in lines:
            v = prs.view(session, l)
            if v.cs and v.rfq_sent and v.rfq_sent <= day:
                cs_rows[l.id] = v.cs
        after_rfq = [l for l in lines if l.id in cs_rows]
        if len(after_rfq) < 5:
            continue
        qs = [q for cs_no in set(cs_rows.values()) for q in session.scalars(select(Quote).where(Quote.cs_no == cs_no))]
        priced = [q for q in qs if q.rate is not None]
        quoted_lines = {q.pr_line_id for q in priced}
        vendors_quoted = {q.record_id for q in priced}
        rfqs = len({(q.cs_no, q.record_id) for q in qs})
        asked_per_line = {l.id: len({q.record_id for q in qs if q.pr_line_id == l.id}) for l in after_rfq}
        quoted_per_line = {l.id: len({q.record_id for q in priced if q.pr_line_id == l.id}) for l in after_rfq}
        full = sum(1 for k in quoted_per_line if quoted_per_line[k] and quoted_per_line[k] == asked_per_line[k])
        most = max(asked_per_line.values(), default=0)
        value = 0.0
        for l in after_rfq:
            mine = [q for q in priced if q.pr_line_id == l.id]
            if mine:
                value += min(q.rate for q in mine) * (l.qty_base or l.qty)
        validity = min((q.validity for q in priced if q.validity and q.validity >= TODAY), default=None)
        pname = lookups.project_name(session, pid)
        mids = sorted({r.message_id for r in session.scalars(select(MessageRef).where(MessageRef.ref_type == "pr", MessageRef.ref_id.in_({l.pr_no for l in after_rfq})))}
                      | {e.message_id for e in events(session, ("short_close_instruction", "reasons"))})
        reasons = next((e.detail for e in events(session, "reasons")), None)
        head = lookups.contact_for(session, "project_head", pid)
        it = item(session, key=f"pr-cancelled:{pid}:{day}", kind="pr-cancelled", tab="requirement", severity="high",
                  title=f"{pname}: {len(after_rfq)} PR lines short-closed after the RFQ",
                  summary=f"Requirement · all {most} vendors asked quoted on {full} of {count(len(after_rfq), 'line')} · {inr(value)} enquiry",
                  owner_ids=[l.buyer_id for l in after_rfq], waiting_on="Projects", projects=[pid],
                  at_stake=rs(value, "the enquiry's value: each quoted line's quantity x its lowest quote", [ref("pr_line", l.id) for l in after_rfq]),
                  rule="Enquiry value: each quoted PR line's quantity x its lowest quote", act_by=validity,
                  next_action=f"Ask {head.name if head else 'the project head'} for cancellation approval with the reason; ask the vendors to hold their quotes.",
                  finding=f"{len(after_rfq)} lines of {count(len({l.pr_no for l in after_rfq}), 'PR')} were deleted on {md(day)}, after {count(rfqs, 'RFQ')} went out; "
                          f"every vendor asked quoted on {full} lines, and {len(quoted_lines) - full} more lines had some quotes.",
                  findings=[Finding(key="effort", fact=f"{count(rfqs, 'RFQ')} sent; {count(len(priced), 'quote')} received from {count(len(vendors_quoted), 'vendor')} on {count(len(quoted_lines), 'line')}",
                                    meaning="SCM's work on these lines and the vendors' quotes are spent unless the lines come back"),
                            Finding(key="validity", fact=f"The earliest quote in hand lapses {md(validity)}" if validity else "No quote in hand is still valid",
                                    meaning="Until then the quotes can be held if the requirement returns")]
                  + ([Finding(key="reasons", fact=reasons, meaning="Projects' reasons, as their mail gives them")] if reasons else []),
                  numbers=[Number(id=f"cancel:{pid}:{day}:rfqs", label="RFQs sent", value=qty(rfqs, "NO", prov("computed", "quotes", rule="vendor x CS pairs asked", by="attention.detectors"))),
                           Number(id=f"cancel:{pid}:{day}:vendors", label="Vendors that quoted", value=qty(len(vendors_quoted), "NO", prov("computed", "quotes", rule="vendors with a priced quote", by="attention.detectors"))),
                           Number(id=f"cancel:{pid}:{day}:lines", label="PR lines short-closed after the RFQ", value=qty(len(after_rfq), "NO", prov("computed", "pr_lines", rule="deleted the same day, RFQ on or before it", by="attention.detectors"))),
                           Number(id=f"cancel:{pid}:{day}:value", label="Enquiry value", value=rs(value, "quoted lines x lowest quote"))],
                  pr_lines=[prs.view(session, l) for l in after_rfq], messages=[msg_ref(session, m) for m in mids], project=project_panel(session, pid),
                  deadlines=deadline("Earliest quote lapses", validity, "quotes"),
                  refs=[ref("project", pid, pname)] + [ref("pr", p) for p in sorted({l.pr_no for l in after_rfq})])
        out.append(Found(it))
    return out


# ------------------------------------------------------------------------------------------------------------------------------- After PO
def mfc_validity(session: Session) -> list[Found]:
    """MFC not issued, and the PO's validity ends before the MFC date the vendor needs, or within 60 days while the manufacturing time left
    exceeds the validity left."""
    out = []
    need_by = {e.ref_id: e for e in events(session, "mfc_needed_by")}
    claims = {e.ref_id: e for e in events(session, "price_claim")}
    for m in session.scalars(select(Milestone).where(Milestone.mfc_issued.is_(None), Milestone.mfc_requested.is_not(None))):
        l = orders.line(session, m.po_line_id or "")
        if l is None or not l.validity_end or l.status != "open":
            continue
        valid_left = (date.fromisoformat(l.validity_end) - AS_OF).days
        e = need_by.get(l.po_no)
        hit = (e and e.date_to and e.date_to > l.validity_end) or (0 <= valid_left <= 60 and (m.mfg_days or 0) > valid_left)
        if not hit:
            continue
        claim = claims.get(l.po_no)
        if l.pv_clause and l.pv_index and l.pv_base_month:
            rise = indices.change_since(session, l.pv_index, l.pv_base_month) or 0
            stake = rs(l.open_value * (l.pv_variable_share or 0) * rise, "PV-linked: open value x variable share x index rise since the base month")
            rule = "open value x the index's rise since the PO's base month"
        elif claim:
            stake = rs(claim.qty, "the vendor's stated firm-price claim if the MFC comes after the PO validity", source=f"message:{claim.message_id}", row=claim.line_ref, method="extracted")
            rule = "the vendor's stated claim if the MFC comes after the validity"
        else:
            stake = unknown("the price after the validity", "a firm PO: what the vendor will charge after the validity is not on file", l.buyer_id or "unassigned",
                            f"What will {lookups.vendor_name(session, l.identity_id)} charge if the MFC is issued after {dmy(l.validity_end)}?")
            rule = "a firm PO: unknown until the vendor states its price after the validity"
        mids = [x.message_id for x in (e, claim) if x]
        pname = lookups.project_name(session, l.project_id)
        d = doa.decide(session, doa.MFC, l.value)
        fin = [Finding(key="validity", fact=f"PO {l.po_no} is firm to {dmy(l.validity_end)} ({valid_left} days left); manufacturing takes {m.mfg_days} days from MFC",
                       meaning="The MFC must be issued within the validity, or the price is open"),
               Finding(key="mfc_asked", fact=f"MFC asked {md(m.mfc_requested)}, not issued; the tracker says: {m.remarks}" if m.remarks else f"MFC asked {md(m.mfc_requested)}, not issued",
                       meaning="The hold is on site readiness, which Projects owns")]
        if e:
            fin.append(Finding(key="mfc_by", fact=f"The vendor wants the MFC by {md(e.date_to)} to hold its slot", meaning="After that date the slot and the price are at risk",
                               refs=[msg_ref(session, e.message_id)]))
        lead = lookups.lead_of(session, lookups.team(session).get(l.buyer_id or ""))      # the DoA has the vertical lead issue an MFC: the buyer's lead owns it first
        it = item(session, key=f"mfc-validity:{l.po_no}", kind="mfc-validity", tab="after_po", severity="high",
                  title=f"{pname}: MFC for {l.short_text} not issued; PO firm to {md(l.validity_end)}",
                  summary=f"After PO · {inr(l.value)} PO · MFC asked {md(m.mfc_requested)} · {m.mfg_days} days to make",
                  owner_ids=([lead.id] if lead and not lead.countersigns else []) + [l.buyer_id], waiting_on="SCM", projects=[l.project_id], at_stake=stake,
                  rule=rule, act_by=(e.date_to if e else l.validity_end),
                  next_action="Issue the MFC (Head of SCM countersigns), or ask the vendor to extend the validity at the firm price.",
                  finding=f"PO {l.po_no} is firm only to {dmy(l.validity_end)}; the MFC is on hold for site readiness, and manufacturing takes {m.mfg_days} days.",
                  findings=fin, doa=d, po_lines=[orders.view(session, l)], messages=[msg_ref(session, x) for x in mids],
                  vendor=vendor_panel(session, l.identity_id), project=project_panel(session, l.project_id), ladder=ladder(session, po_line_id=l.id),
                  numbers=[Number(id=f"po:{l.po_no}:value", label="PO value", value=rs(l.value, "ME2N value", source="po_lines", method="stated"))]
                  + ([Number(id=f"po:{l.po_no}:claim", label="Vendor's claim after validity", value=stake)] if claim else []),
                  deadlines=deadline("PO validity ends", l.validity_end, f"po_lines row {l.src_row}") + (deadline("Vendor wants the MFC by", e.date_to, f"message {e.message_id} {e.line_ref}") if e else []),
                  refs=[ref("po_line", l.id), ref("supplier", l.identity_id, lookups.vendor_name(session, l.identity_id)), ref("project", l.project_id, pname)])
        out.append(Found(it))
    return out


def inspection_ready(session: Session) -> list[Found]:
    """An inspection call before the site is ready (the site-ready date is later, or unknown): storage at the vendor's works from the end of the free period."""
    out = []
    rate = {e.ref_id: e for e in events(session, "storage_rate")}
    free = {e.ref_id: e for e in events(session, "free_storage_days")}
    for m in session.scalars(select(Milestone).where(Milestone.inspection_planned.is_not(None), Milestone.inspection_done.is_(None))):
        if m.site_ready_planned and m.site_ready_planned <= m.inspection_planned:
            continue
        l = orders.line(session, m.po_line_id or "")
        if l is None or (m.inspection_planned < TODAY) or not m.inspection_call or m.inspection_call > TODAY:
            continue      # the vendor has not called for the inspection yet (as of the data date): nothing to decide
        r, fdays = rate.get(m.po_no), free.get(m.po_no)
        if r and fdays and m.site_ready_planned:
            start = date.fromisoformat(m.inspection_planned) + timedelta(days=int(fdays.qty))
            days = max(0, (date.fromisoformat(m.site_ready_planned) - start).days)
            stake = rs(days * r.qty, f"storage ₹{en_in(r.qty)} a day x {days} days from the end of free storage ({md(start.isoformat())}) to site ready ({md(m.site_ready_planned)})",
                       source=f"message:{r.message_id}", row=r.line_ref)
        else:
            stake = unknown("the site-ready date", "storage is charged until the site can take it", lookups.contact_for(session, "planner", l.project_id).id if l.project_id else "unassigned",
                            f"When will the {lookups.project_name(session, l.project_id)} site (plinth) be ready?")
        pname = lookups.project_name(session, l.project_id)
        mids = sorted({x.message_id for x in (r, fdays) if x} | {e.message_id for e in events(session, "inspection_call") if e.ref_id == m.po_no})
        it = item(session, key=f"inspection-ready:{m.po_no}", kind="inspection-ready", tab="after_po",
                  title=f"{pname}: {l.short_text} ready for inspection {md(m.inspection_planned)}; site ready {md(m.site_ready_planned) if m.site_ready_planned else 'unknown'}",
                  summary=f"After PO · inspection {md(m.inspection_planned)} · {int(fdays.qty) if fdays else '—'} days free storage · plinth {md(m.site_ready_planned) if m.site_ready_planned else 'not dated'}",
                  owner_ids=[l.buyer_id], waiting_on="Projects", projects=[l.project_id], at_stake=stake,
                  rule="storage rate x days from the end of free storage to site ready", act_by=m.inspection_planned,
                  next_action="Inspect now and hold dispatch; ask the site for the plinth-ready date.",
                  finding=f"The vendor calls for inspection on {md(m.inspection_planned)}; the site (plinth) is planned ready {md(m.site_ready_planned) if m.site_ready_planned else 'on no date'}.",
                  findings=[Finding(key="storage", fact=stake.provenance.rule if hasattr(stake, "provenance") else "the site-ready date is not on file",
                                    meaning="Storage runs until the site can take the transformer")],
                  po_lines=[orders.view(session, l)], messages=[msg_ref(session, x) for x in mids], vendor=vendor_panel(session, l.identity_id),
                  project=project_panel(session, l.project_id), ladder=ladder(session, po_line_id=l.id),
                  deadlines=deadline("Inspection", m.inspection_planned, f"milestones row {m.src_row}") + deadline("Site (plinth) ready", m.site_ready_planned, f"milestones row {m.src_row}"),
                  refs=[ref("po_line", l.id), ref("supplier", l.identity_id, lookups.vendor_name(session, l.identity_id)), ref("project", l.project_id, pname)])
        out.append(Found(it))
    return out


def commissioning(session: Session) -> list[Found]:
    """Equipment received with no commissioning date, and its warranty from supply ending within 60 days."""
    out = []
    offers = {e.ref_id: e for e in events(session, "offer")}
    for m in session.scalars(select(Milestone).where(Milestone.delivered.is_not(None), Milestone.commissioned.is_(None), Milestone.warranty_end.is_not(None))):
        if (m.warranty_from or "Supply") != "Supply" or not (0 <= (left(m.warranty_end) or -1) <= 60):
            continue
        l = orders.line(session, m.po_line_id or "")
        o = offers.get(m.po_no)
        mids = sorted({e.message_id for e in events(session, ("warranty_end", "offer", "supplied_on")) if e.ref_id == m.po_no})
        owner = (l.buyer_id if l else None) or next(iter(addressee(session, mids[0])), None) if mids else (l.buyer_id if l else None)
        stake = rs(o.qty, "the vendor's price for a 12-month extension from commissioning", source=f"message:{o.message_id}", row=o.line_ref, method="extracted") if o else \
            (rs(l.value, "the PO value out of warranty") if l else unknown("the equipment's value", "the PO is older than the ME2N export", owner or "unassigned", f"What is PO {m.po_no} worth?"))
        pname = lookups.project_name(session, m.project_id)
        it = item(session, key=f"commissioning:{m.po_no}", kind="commissioning", tab="after_po",
                  title=f"{pname}: {m.item_text or 'equipment'} never commissioned; warranty ends {md(m.warranty_end)}",
                  summary=f"After PO · delivered {md(m.delivered)} · {m.warranty_months}-month warranty from supply · extension quoted",
                  owner_ids=[owner], waiting_on="Projects", projects=[m.project_id], at_stake=stake,
                  rule="the vendor's extension price (else the equipment's value out of warranty)", act_by=m.warranty_end,
                  next_action="Ask Projects for a commissioning date; decide on the warranty extension before it lapses.",
                  finding=f"Delivered {dmy(m.delivered)}, not commissioned; the warranty runs from supply and ends {dmy(m.warranty_end)}.",
                  findings=[Finding(key="warranty", fact=f"{m.warranty_months} months from supply ({md(m.delivered)}) ends {md(m.warranty_end)}; the tracker says: {m.remarks}",
                                    meaning="After that a fault on first start-up is the company's cost")],
                  po_lines=[orders.view(session, l)] if l else [], messages=[msg_ref(session, x) for x in mids], project=project_panel(session, m.project_id),
                  vendor=vendor_panel(session, l.identity_id if l else lookups.identity_of(session, m.record_id) or next((msg(session, x).identity_id for x in mids if msg(session, x)), None)),
                  deadlines=deadline("Warranty ends", m.warranty_end, f"milestones row {m.src_row}"),
                  refs=[ref("po", m.po_no), ref("project", m.project_id, pname)])
        out.append(Found(it))
    return out


def schedule_slip(session: Session) -> list[Found]:
    """A vendor's message moves PO delivery dates past the project's need (the PR's needed-by)."""
    by_vendor: dict[str, list] = defaultdict(list)
    for line_id, revs in orders.revisions(session).items():
        l = orders.line(session, line_id)
        if l is None or l.status != "open":
            continue
        pr = prs.all_lines(session).get(l.pr_line_id or "")
        need = (pr.needed_by if pr else None) or l.delivery_date
        last = max(r.date for r in revs)
        if need and last > need:
            by_vendor[l.identity_id].append((l, revs, need))
    out = []
    for ident, rows in by_vendor.items():
        lines = [r[0] for r in rows]
        need = min(r[2] for r in rows)
        new = min(r.date for _l, revs, _n in rows for r in revs)
        mids = sorted({r.message for _l, revs, _n in rows for r in revs})
        pid = lines[0].project_id
        pname = lookups.project_name(session, pid)
        total = sum(l.open_value for l in lines)
        mats = sorted({l.material for l in lines if l.material})
        it = item(session, key=f"schedule-slip:{ident}", kind="schedule-slip", tab="after_po",
                  title=f"{pname}: {lookups.vendor_name(session, ident)} moves {count(len(lines), 'line')} past the need date",
                  summary=f"After PO · was {md(lines[0].delivery_date)}, now {md(new)} · needed {md(need)}",
                  owner_ids=[l.buyer_id for l in lines], waiting_on="Vendor", projects=sorted({l.project_id for l in lines if l.project_id}),
                  at_stake=rs(total, "open value of the moved lines", [ref("po_line", l.id) for l in lines]), rule="open value of the lines the vendor moved", act_by=need,
                  next_action="Hold the original date or ask for a partial dispatch; or re-sequence the work front.",
                  finding=f"The vendor moved {count(len(lines), 'line')} from {md(lines[0].delivery_date)} to {md(new)}; the site needs them from {md(need)}.",
                  findings=[Finding(key="slip", fact=f"{l.ref_id if hasattr(l, 'ref_id') else l.id}: {md(l.delivery_date)} → {', '.join(md(r.date) for r in revs)}",
                                    meaning=f"{(date.fromisoformat(max(r.date for r in revs)) - date.fromisoformat(n)).days} days after the need date") for l, revs, n in rows],
                  po_lines=[orders.view(session, l) for l in lines], messages=[msg_ref(session, x) for x in mids], vendor=vendor_panel(session, ident),
                  project=project_panel(session, pid), supply=req.supply_by_month(session, pid, mats, req.months_ahead()) if pid and mats else None,
                  deadlines=deadline("Needed at site", need, "pr_lines") + deadline("New dispatch", new, f"message {mids[0]}"),
                  refs=[ref("po_line", l.id) for l in lines] + [ref("supplier", ident, lookups.vendor_name(session, ident))] + [ref("project", pid, pname)])
        it.site_impact = impact(session, pid, mats, need, f"{lookups.vendor_name(session, ident).split()[0]} now dispatches {md(new)}; needed {md(need)}")
        out.append(Found(it))
    return out


# ------------------------------------------------------------------------------------------------------------------------------- Price
def pv_longlead(session: Session) -> list[Found]:
    """PV-linked look-ahead items with no PO, past or within 30 days of their order-by date, while their index rises: each month's wait costs."""
    by_project: dict[str, list] = defaultdict(list)
    horizon = (AS_OF + timedelta(days=30)).isoformat()
    for x in lookahead_items(session):
        if x.price_basis == "PV" and not x.ordered and x.order_by and x.order_by <= horizon and x.delay_cost:
            by_project[x.project].append(x)
    out = []
    for pid, rows in by_project.items():
        cost = sum(x.delay_cost for x in rows)
        since = sum(x.since_lookahead or 0 for x in rows)
        value = sum(x.value for x in rows)
        v = lookups.vertical_of_project(session, pid)
        lead = lookups.vertical_lead(session, v)
        head = lookups.head(session)
        pname = lookups.project_name(session, pid)
        first = min(x.order_by for x in rows)
        it = item(session, key=f"pv-longlead:{pid}", kind="pv-longlead", tab="price", severity="high",
                  title=f"{pname}: {count(len(rows), 'long-lead PV item')} not ordered; each month costs {inr(cost)}",
                  summary=f"Price · {inr(value)} of items · order-by {md(first)} passed" + (f" · {inr(since)} since then" if since else ""),
                  owner_ids=[lead.id if lead else "", head.id if head else ""], waiting_on="Management", projects=[pid],
                  at_stake=rs(cost, "a month's delay: item value x variable share x the index's average monthly rise over 6 months", [ref("lookahead", str(x.id)) for x in rows]),
                  rule="cost of one month's delay = item value x PV weight x average monthly index change over 6 months", act_by=first,
                  next_action="Order now (Head of SCM signs), negotiate a firm price, or record the wait for funding with its cost.",
                  finding=f"{count(len(rows), 'item')} worth {inr(value)} are PV-linked and not ordered; their indices rose every month. Each month of waiting adds about {inr(cost)}.",
                  findings=[Finding(key=f"la:{x.id}", fact=f"{x.item}: {inr(x.value)}, order by {md(x.order_by)}, {x.index} {x.monthly_change * 100:.2f}% a month; status: {x.status}",
                                    meaning=f"About {inr(x.delay_cost)} a month" + (f"; {inr(x.since_lookahead)} since the order-by date" if x.since_lookahead else ""), refs=[ref("lookahead", str(x.id), x.item)])
                            for x in rows],
                  numbers=[Number(id=f"la:{x.id}:delay_cost", label=f"{x.item}: a month's delay", value=rs(x.delay_cost, "value x share x monthly index change")) for x in rows],
                  project=project_panel(session, pid), doa=doa.decide(session, doa.COMMITMENT, value),
                  deadlines=[Deadline(what=f"Order by: {x.item}", date=x.order_by, source=f"lookahead_items row {x.src_row}", days_left=left(x.order_by)) for x in rows],
                  refs=[ref("project", pid, pname)] + [ref("lookahead", str(x.id), x.item) for x in rows])
        out.append(Found(it))
    return out


def price_notice(session: Session) -> list[Found]:
    """A vendor's price increase from a date: the increase on the requirement from that date that open POs do not cover."""
    out = []
    locks = {e.message_id: e for e in events(session, "price_lock")}
    for e in events(session, "price_change"):
        m = msg(session, e.message_id)
        if m is None or m.trust == "blocked" or not m.identity_id:
            continue
        ident = m.identity_id
        mine = [l for l in orders.all_lines(session).values() if l.identity_id == ident]
        mats = sorted({l.material for l in mine if l.material})
        pids = sorted({l.project_id for l in mine if l.project_id})
        months = [k for k in req.months_ahead() if k >= e.date_from[:7]]
        per: dict[str, tuple[float, float]] = {}
        for p in pids:
            n = sum(r.qty for r in req.all_lines(session) if r.project_id == p and r.month in months and set((r.material_codes or "").split(",")) & set(mats))
            c = sum(l.open_base for l in orders.all_lines(session).values() if l.material in mats and l.project_id == p and l.status == "open" and (l.delivery_date or "") >= e.date_from)
            per[p] = (n, c)
        need, covered = sum(n for n, _ in per.values()), sum(c for _, c in per.values())
        exposed = sum(max(0.0, n - c) for n, c in per.values())
        lock = locks.get(e.message_id)
        act = lock.date_to if lock else (date.fromisoformat(e.date_from) - timedelta(days=1)).isoformat()
        buyer_of = {p: Counter_most([l.buyer_id for l in mine if l.project_id == p]) for p in pids}
        shares: dict[str, dict] = {}
        for p, (n, c) in per.items():
            if n - c > 0 and buyer_of.get(p):
                sh = shares.setdefault(buyer_of[p], dict(mt=0.0, projects=[]))
                sh["mt"] += n - c
                sh["projects"].append(p)
        owner_ids = list(dict.fromkeys(addressee(session, e.message_id) + sorted(shares, key=lambda b: -shares[b]["mt"])))
        it = item(session, key=f"price-notice:{ident}:{e.date_from}", kind="price-notice", tab="price",
                  title=f"{lookups.vendor_name(session, ident)}: +₹{en_in(e.qty)}/MT from {md(e.date_from)}",
                  summary=f"Price · {qty_text(round(exposed), 'MT')} required from {md(e.date_from)} not on open POs · orders acknowledged by {md(act)} keep today's rate",
                  owner_ids=owner_ids, waiting_on="SCM", projects=[p for p in pids if per[p][0] > per[p][1]],
                  at_stake=rs(exposed * e.qty, f"₹{en_in(e.qty)} x {en_in(round(exposed))} MT (requirement from {md(e.date_from)} for its projects less open POs due from then)",
                              source=f"message:{e.message_id}", row=e.line_ref),
                  rule="increase x requirement from the effective date not covered by open POs", act_by=act,
                  next_action="Buy ahead before the effective date, move to another library vendor, or accept the new price.",
                  finding=f"From {dmy(e.date_from)} the price rises ₹{en_in(e.qty)} per MT; {qty_text(round(exposed), 'MT')} of the requirement from then is not on an open PO.",
                  findings=[Finding(key="requirement", fact=f"Requirement {', '.join(months)} for {', '.join(lookups.project_name(session, p) for p in pids[:6])}: {qty_text(round(need), 'MT')}; open POs due from {md(e.date_from)}: {qty_text(round(covered), 'MT')}",
                                    meaning="The rest is bought at the new price unless ordered and acknowledged before then")],
                  messages=[msg_ref(session, e.message_id)], vendor=vendor_panel(session, ident),
                  deadlines=deadline("Acknowledge orders by", act, f"message {e.message_id} {lock.line_ref if lock else ''}") + deadline("New price from", e.date_from, f"message {e.message_id} {e.line_ref}"),
                  refs=[ref("supplier", ident, lookups.vendor_name(session, ident))] + [ref("material", x) for x in mats])
        f = Found(it)
        for b, sh in shares.items():
            f.shares[b] = dict(at_stake=rs(sh["mt"] * e.qty, f"₹{en_in(e.qty)} x your projects' {en_in(round(sh['mt']))} MT not on open POs"),
                               projects=[proj_ref(session, p) for p in sh["projects"]],
                               summary=f"Price · {qty_text(round(sh['mt']), 'MT')} for {', '.join(lookups.project_name(session, p) for p in sh['projects'][:4])} not on open POs · acknowledge by {md(act)}")
        out.append(f)
    return out


def pv_claim(session: Session) -> list[Found]:
    """A vendor's PV claim against the PV computed from the PO's own clause (base month, variable share, index)."""
    out = []
    claims = events(session, "pv_claim")
    for c in claims:
        l = next((x for x in orders.lines_of_po(session, c.ref_id or "") if x.pv_clause), None)
        if l is None:
            continue
        same = lambda k: next((e for e in events(session, k) if e.message_id == c.message_id), None)  # noqa: E731
        q, cur = same("pv_claim_qty"), same("pv_claim_index")
        base_used = same("pv_claim_base")
        ours = indices.pv(session, qty=q.qty, rate=l.rate_base, share=l.pv_variable_share, index=l.pv_index, base_month=l.pv_base_month, current_month=cur.date_from)
        theirs = indices.pv(session, qty=q.qty, rate=l.rate_base, share=l.pv_variable_share, index=l.pv_index, base_month=base_used.date_from, current_month=cur.date_from)
        diff = c.qty - (ours.pv or 0)
        act = (date.fromisoformat(msg(session, c.message_id).date[:10]) + timedelta(days=15)).isoformat()
        pname = lookups.project_name(session, l.project_id)
        it = item(session, key=f"pv-claim:{l.po_no}", kind="pv-claim", tab="price",
                  title=f"{lookups.vendor_name(session, l.identity_id)}: PV claim {inr(c.qty, exact=True)} on the wrong base month",
                  summary=f"Price · claimed {inr(c.qty)} · PO clause gives {inr(ours.pv)} · base {base_used.date_from} used, PO says {l.pv_base_month}",
                  owner_ids=[l.buyer_id], waiting_on="SCM", projects=[l.project_id],
                  at_stake=rs(diff, f"claimed {inr(c.qty, exact=True)} less the PV from the PO's clause {inr(ours.pv, exact=True)}", source=f"message:{c.message_id}", row=c.line_ref),
                  rule="claimed minus the PV computed from the PO's clause and the index", act_by=act,
                  next_action="Reply with the PV computed on the PO's base month, rights reserved.",
                  finding=f"The claim uses {base_used.date_from} as the base; PO {l.po_no}'s clause says {l.pv_base_month}. On the PO's base the PV is {inr(ours.pv, exact=True)}, not {inr(c.qty, exact=True)}.",
                  findings=[Finding(key="ours", fact=f"PO clause: {ours.formula}", meaning="What the PO owes"),
                            Finding(key="theirs", fact=f"The claim: {theirs.formula}", meaning=f"{inr(diff, exact=True)} more than the clause allows")],
                  numbers=[Number(id=f"pv:{l.po_no}:claimed", label="PV claimed", value=rs(c.qty, "the vendor's claim", source=f"message:{c.message_id}", row=c.line_ref, method="extracted")),
                           Number(id=f"pv:{l.po_no}:computed", label="PV on the PO's base", value=rs(ours.pv, ours.formula)),
                           Number(id=f"pv:{l.po_no}:difference", label="Difference", value=rs(diff, "claimed less computed"))],
                  po_lines=[orders.view(session, l)], messages=[msg_ref(session, c.message_id)], vendor=vendor_panel(session, l.identity_id),
                  project=project_panel(session, l.project_id), deadlines=deadline("Reply within 15 days of the claim", act, f"message {c.message_id}"),
                  refs=[ref("po_line", l.id), ref("supplier", l.identity_id, lookups.vendor_name(session, l.identity_id)), ref("project", l.project_id, pname)])
        out.append(Found(it))
    return out


def quote_lapse(session: Session) -> list[Found]:
    """A quote held only in mail (no CS tracks it) lapsing within 30 days and not awarded: the lapse costs the difference to the next price on file
    where one is known; otherwise the case states the spend the quote covers (never 'at stake'). CS-tracker quotes are SCM's tracked pipeline."""
    out = []
    horizon = (AS_OF + timedelta(days=30)).isoformat()
    for q in quotes.mail_quotes(session):
        m = msg(session, q.message_id)
        if m is None or m.trust == "blocked" or not q.validity or not (TODAY <= q.validity <= horizon) or not q.identity_id:
            continue
        if len([x for x in quotes.mail_quotes(session, q.message_id)]) > 1:
            continue      # several quotes in one mail are a comparison, not a lapse (the L1 case reads them)
        nxt = [x for x in session.scalars(select(Quote).where(Quote.material == q.material, Quote.source == "tracker", Quote.rate.is_not(None)))
               if (x.project_id == q.project_id or not x.project_id) and x.rate > q.rate]
        best = min(nxt, key=lambda x: x.rate) if nxt else None
        pname = lookups.project_name(session, q.project_id)
        if best:
            stake, lab = rs((best.rate - q.rate) * (q.qty or 1), f"(next price on file {inr(best.rate)} - this quote {inr(q.rate)}) x {en_in(q.qty or 1)} {q.uom}"), "at stake"
        else:
            stake, lab = rs(q.rate * (q.qty or 1), "the spend the quote covers"), "covers"
        it = item(session, key=f"quote-lapse:{q.identity_id}:{q.validity}", kind="quote-lapse", tab="price",
                  title=f"{pname}: {lookups.vendor_name(session, q.identity_id)} quote lapses {md(q.validity)}",
                  summary=f"Price · {inr(q.rate)} per {q.uom} x {en_in(q.qty or 1)} · {q.price_basis}" + (f" · next on file {inr(best.rate)}" if best else ""),
                  owner_ids=addressee(session, q.message_id), waiting_on="SCM", projects=[q.project_id] if q.project_id else [], at_stake=stake, label=lab,
                  rule="lapse cost: (next price on file - this quote) x quantity; else the spend it covers", act_by=q.validity,
                  next_action="Ask for an extension, or award before it lapses.",
                  finding=f"The quote ({q.price_basis}{'; ' + q.pv_formula if q.pv_formula else ''}) holds to {dmy(q.validity)}; no CS tracks it.",
                  findings=[Finding(key="quote", fact=f"{q.vendor_name}: {inr(q.rate, exact=True)} per {q.uom}, valid to {md(q.validity)} ({q.line_ref} of the mail)", meaning="Only in mail")]
                  + ([Finding(key="next", fact=f"{best.vendor_name} on {best.cs_no}: {inr(best.rate, exact=True)} per {best.uom}", meaning="What the lapse would cost")] if best else []),
                  messages=[msg_ref(session, q.message_id)], vendor=vendor_panel(session, q.identity_id), project=project_panel(session, q.project_id),
                  deadlines=deadline("Quote lapses", q.validity, f"message {q.message_id} {q.line_ref}"),
                  refs=[ref("quote", q.id), ref("supplier", q.identity_id, lookups.vendor_name(session, q.identity_id))] + ([ref("project", q.project_id, pname)] if q.project_id else []))
        out.append(Found(it))
    return out


def l1_above_last(session: Session) -> list[Found]:
    """Quotes in hand whose L1 is above the last PO rate for the material at that plant by more than 3%: an open CS in the tracker, or quotes for one
    project and material that came in by mail."""
    out = []
    sets: list[tuple[str, list[Quote], str | None, str | None, str]] = []
    for s in quotes.list_cs(session, "Pending"):
        sets.append((s.cs_no, list(session.scalars(select(Quote).where(Quote.cs_no == s.cs_no))), s.project_id, s.material, "tracker"))
    mail: dict[tuple, list[Quote]] = defaultdict(list)
    for q in quotes.mail_quotes(session):
        m = msg(session, q.message_id)
        if m is not None and m.trust != "blocked":
            mail[(q.project_id, q.material, q.message_id)].append(q)
    for (pid, mat, mid), qs in mail.items():
        if len(qs) > 1:
            sets.append((f"{pid}:{mat}", qs, pid, mat, "mail"))
    for key, qs, pid, mat, src in sets:
        c = quotes.compare(session, qs, pid, mat)
        if c["l1"] is None or c["last"] is None or (c["l1_vs_last"] or 0) <= 3:
            continue
        l1, (last_rate, last_line) = c["l1"], c["last"]
        q_ = l1.qty or 0
        # a rate contract (a CS with no PR behind it) quotes a rate and no quantity: the ₹ waits on what will be called off against it
        stake = (rs((l1.rate - last_rate) * q_, f"(L1 {inr(l1.rate)} - last PO {inr(last_rate)}) x {en_in(q_)} {l1.uom}") if q_
                 else unknown("the quantity this rate will buy", f"a rate contract: {inr(l1.rate - last_rate)} per {l1.uom or 'unit'} above the last PO, on a quantity not stated",
                              l1.buyer_id or "unassigned", f"How much {l1.uom or ''} is expected against this rate contract?".replace("  ", " ")))
        b = c["budget"]
        pname = lookups.project_name(session, pid)
        mname = lookups.materials(session)[mat].description if mat in lookups.materials(session) else mat
        owner = last_line.buyer_id if last_line.project_id == pid else None
        owner_ids = [owner] if owner else (addressee(session, qs[0].message_id) if src == "mail" else [x.buyer_id for x in qs if x.buyer_id])
        ordered = sorted(qs, key=lambda x: (x.rate is None, x.rate or 0))
        it = item(session, key=f"l1-above-last:{key}", kind="l1-above-last", tab="price",
                  title=f"{pname}: {mname} L1 {inr(l1.rate)} against last PO {inr(last_rate)}",
                  summary=f"Price · {count(len([x for x in qs if x.rate]), 'quote')} · +{c['l1_vs_last']:.1f}% on the last PO" + (f" · budget {inr(b.rate)}" if b else ""),
                  owner_ids=owner_ids, waiting_on="SCM", projects=[pid], at_stake=stake,
                  rule="(L1 - last PO rate at the plant) x quantity; the budget rate beside it", act_by=l1.validity,
                  next_action="Negotiate against the last price, ask for an extension, or award with a reason.",
                  finding=f"L1 is {inr(l1.rate)} per {l1.uom or 'unit'}, {c['l1_vs_last']:.1f}% above the last PO rate of {inr(last_rate)} (PO {last_line.po_no}, {md(last_line.doc_date)})"
                          + (f" and {c['l1_vs_budget']:.1f}% above the budget rate of {inr(b.rate)}" if b else "") + ".",
                  findings=[Finding(key=f"q:{x.id}", fact=f"{x.vendor_name}: {inr(x.rate) if x.rate else 'no price'} per {x.uom or 'unit'}, valid to {md(x.validity)}",
                                    meaning="L1" if x is l1 else "") for x in ordered]
                  + [Finding(key="last", fact=f"Last PO {last_line.po_no}: {inr(last_rate)} on {md(last_line.doc_date)}", meaning="The price the site pays now")]
                  + ([Finding(key="budget", fact=f"Budget (tender) rate: {inr(b.rate)}", meaning=f"(L1 - budget) x quantity = {inr((l1.rate - b.rate) * q_)}" if q_ else "No quantity is stated against this rate")] if b else []),
                  numbers=[Number(id=f"l1:{key}:l1", label="L1 rate", value=rs(l1.rate, "lowest quote", method="stated", source="quotes")),
                           Number(id=f"l1:{key}:last", label="Last PO rate", value=rs(last_rate, "newest PO line at the plant", method="stated", source="po_lines")),
                           Number(id=f"l1:{key}:over_last", label="Above the last PO", value=stake if not q_ else rs((l1.rate - last_rate) * q_, "(L1 - last) x qty"))]
                  + ([Number(id=f"l1:{key}:over_budget", label="Above the budget rate", value=rs((l1.rate - b.rate) * q_, "(L1 - budget) x qty"))] if b and q_ else []),
                  messages=[msg_ref(session, qs[0].message_id)] if src == "mail" else [], project=project_panel(session, pid),
                  cs=quotes.cs(session, key) if src == "tracker" else None,
                  deadlines=deadline("L1 valid to", l1.validity, "quotes"),
                  refs=[ref("project", pid, pname), ref("material", mat, mname), ref("po_line", last_line.id)] + [ref("quote", x.id) for x in qs])
        out.append(Found(it))
    return out


def rate_spread(session: Session) -> list[Found]:
    """One material bought at more than twice the price between projects (each project's last PO rate this year): what the sites above the median
    would have paid at the median on their 3-month requirement. Not a saving: the reasons (haul, quality, market, a unit kept differently) are unknown
    per site. The material the most projects buy leads; the other materials with such a spread fold under it, each resolvable on its own."""
    by_mat: dict[str, dict[str, tuple[float, object]]] = defaultdict(dict)
    year = (AS_OF - timedelta(days=365)).isoformat()
    for l in orders.all_lines(session).values():
        if not l.material or not l.project_id or l.doc_date < year:
            continue
        cur = by_mat[l.material].get(l.project_id)
        if cur is None or (l.doc_date, l.id) > (cur[1].doc_date, cur[1].id):
            by_mat[l.material][l.project_id] = (l.rate_base, l)
    cands = []
    for mat, sites in by_mat.items():
        rates = [r for r, _ in sites.values()]
        if len(rates) < 4 or max(rates) <= 2 * min(rates):
            continue
        med = statistics.median(rates)
        months = req.months_ahead()
        above = []
        for pid, (r, l) in sites.items():
            if r <= med:
                continue
            need = sum(x.qty for x in req.all_lines(session) if x.project_id == pid and x.month in months and mat in (x.material_codes or "").split(","))
            above.append((pid, r, l, need, (r - med) * need))
        total = sum(a[4] for a in above)
        if total > 0:
            cands.append((len(sites), total, mat, sites, med, above))
    out = []
    cands.sort(key=lambda c: (-c[0], -c[1]))      # the material the most projects buy leads (its median means most); the others fold under it
    for n, (_sites, total, mat, sites, med, above) in enumerate(cands):
        rates = sorted((r, pid) for pid, (r, _l) in sites.items())
        mname = lookups.materials(session)[mat].description
        lo, hi = rates[0], rates[-1]
        shares: dict[str, dict] = {}
        for pid, r, l, need, amt in above:
            if amt <= 0:
                continue
            s = shares.setdefault(l.buyer_id, dict(amount=0.0, projects=[]))
            s["amount"] += amt
            s["projects"].append(pid)
        gm = lookups.duty(session, "rate_spread")      # a spread across verticals is seen whole by the member who holds it; each buyer sees their own sites
        owner_ids = sorted(shares, key=lambda b: -shares[b]["amount"]) + ([gm.id] if gm and len({lookups.vertical_of_project(session, p) for p in sites}) > 1 else [])
        it = item(session, key=f"rate-spread:{mat}", kind="rate-spread", tab="price", severity="low",
                  title=f"{mname}: {inr(lo[0])} to {inr(hi[0])} per {lookups.materials(session)[mat].base_uom} across projects",
                  summary=f"Price · {count(len(sites), 'project')} · median {inr(med)} · {lookups.project_name(session, lo[1])} lowest, {lookups.project_name(session, hi[1])} highest",
                  owner_ids=owner_ids, waiting_on="SCM", projects=[p for p, *_ in above],
                  at_stake=rs(total, "Σ (site rate - median) x the site's 3-month requirement, sites above the median"), label="if those sites paid the median",
                  rule="Σ (site rate − median) × site 3-month requirement for sites above the median; not a saving", act_by=None,
                  next_action="Ask each site's buyer why; re-tender the sites above the median, or record the spread as explained.",
                  finding=f"The last PO rate for {mname} runs from {inr(lo[0])} ({lookups.project_name(session, lo[1])}) to {inr(hi[0])} ({lookups.project_name(session, hi[1])}). "
                          "The records do not say why (haul distance, quality, market): each site's buyer can.",
                  findings=[Finding(key=f"site:{pid}", fact=f"{lookups.project_name(session, pid)}: {inr(r)} (PO {l.po_no}, {md(l.doc_date)})",
                                    meaning=f"{'+' if r > med else ''}{(r - med) / med * 100:.0f}% on the median", refs=[ref("po_line", l.id)])
                            for r, pid in rates for l in [sites[pid][1]]],
                  unknowns=[unknown(f"why {lookups.project_name(session, pid)} pays {inr(r)}", "a spread is a saving only if the reason is not haul or quality",
                                    l.buyer_id or "unassigned", f"Why does {lookups.project_name(session, pid)} pay {inr(r)} for {mname} against a median of {inr(med)}?",
                                    [ref("po_line", l.id)]) for pid, r, l, need, amt in above if amt > 0],
                  refs=[ref("material", mat, mname)] + [ref("project", p, lookups.project_name(session, p)) for _r, p in rates])
        found = Found(it, fold_into=None if n == 0 else f"rate-spread:{cands[0][2]}")
        for b, s in shares.items():
            found.shares[b] = dict(at_stake=rs(s["amount"], "your sites above the median"), projects=[proj_ref(session, p) for p in s["projects"]],
                                   summary=f"Price · your {count(len(s['projects']), 'site')} above the median {inr(med)}: " + ", ".join(lookups.project_name(session, p) for p in s["projects"][:4]))
        out.append(found)
    return out


# ------------------------------------------------------------------------------------------------------------------------------- Payments
def lc(session: Session) -> list[Found]:
    """An LC to be opened by a date and not opened."""
    out = []
    lcmail = {e.ref_id: e for e in events(session, "lc_deadline")}
    for g in guarantees(session):
        if g.kind != "LC" or g.issued_on or not g.to_open_by or (g.days_left or 0) < 0 or g.days_left > 45:
            continue
        l = next(iter(orders.lines_of_po(session, g.po or "")), None)
        e = lcmail.get(g.po)
        pname = lookups.project_name(session, l.project_id) if l else ""
        it = item(session, key=f"lc:{g.po}", kind="lc", tab="payments", severity="high",
                  title=f"{pname}: LC {inr(g.amount)} for {l.short_text if l else 'the PO'} to open by {md(g.to_open_by)}",
                  summary=f"Payments · {g.status} with Finance · {g.remarks or ''}".rstrip(" ·"),
                  owner_ids=[l.buyer_id] if l else [], waiting_on="Finance", projects=[l.project_id] if l else [],
                  at_stake=rs(g.amount, "the LC value", source="lc_bg", row=str(g.src_row), method="stated"), rule="LC value", act_by=g.to_open_by,
                  next_action="Ask Finance to open the LC; ask the vendor to hold the slot if it cannot be opened in time.",
                  finding=f"The LC for PO {g.po} must be opened by {dmy(g.to_open_by)}" + (f"; the vendor releases its production slot after that ({e.detail})" if e else "") + ".",
                  findings=[Finding(key="tracker", fact=f"LC/BG tracker: {g.status}; {g.remarks}", meaning="Not opened yet")]
                  + ([Finding(key="mail", fact=e.detail, meaning="The vendor's deadline", refs=[msg_ref(session, e.message_id)])] if e else []),
                  po_lines=[orders.view(session, x) for x in orders.lines_of_po(session, g.po or "")], messages=[msg_ref(session, e.message_id)] if e else [],
                  vendor=vendor_panel(session, l.identity_id if l else None), project=project_panel(session, l.project_id if l else None),
                  deadlines=deadline("Open the LC by", g.to_open_by, f"lc_bg row {g.src_row}"),
                  refs=[ref("po", g.po)] + ([ref("supplier", l.identity_id, lookups.vendor_name(session, l.identity_id))] if l else []))
        out.append(Found(it))
    return out


def abg(session: Session) -> list[Found]:
    """An advance bank guarantee expiring within 30 days while the advance it secures is not recovered."""
    out = []
    asks = {e.ref_id: e for e in events(session, "deadline") if e.ref_type == "po"}
    for g in guarantees(session):
        if g.kind != "ABG" or not g.expiry or not (0 <= (g.days_left or -1) <= 30) or not g.unrecovered:
            continue
        l = next(iter(orders.lines_of_po(session, g.po or "")), None)
        e = asks.get(g.po)
        pname = lookups.project_name(session, l.project_id) if l else ""
        act = min(x for x in (g.expiry, e.date_to if e else None) if x)
        it = item(session, key=f"abg:{g.number}", kind="abg", tab="payments", severity="high",
                  title=f"{pname}: ABG {inr(g.amount)} expires {md(g.expiry)}; advance not recovered",
                  summary=f"Payments · {g.vendor_name} · {l.short_text if l else ''} not delivered" if l and l.received_base == 0 else f"Payments · {g.vendor_name}",
                  owner_ids=[l.buyer_id] if l else [], waiting_on="Finance", projects=[l.project_id] if l else [],
                  at_stake=rs(g.unrecovered, "the advance not yet recovered: guarantee amount x the PO's open share", source="lc_bg", row=str(g.src_row)),
                  rule="unrecovered advance", act_by=act,
                  next_action="Ask the vendor to extend the ABG by six months; ask Finance to hold the invocation date.",
                  finding=f"ABG {g.number} for {inr(g.amount, exact=True)} on PO {g.po} expires {dmy(g.expiry)}; nothing has been received against the PO, so the advance is not recovered.",
                  findings=[Finding(key="tracker", fact=f"LC/BG tracker: {g.status}; {g.remarks}", meaning="Live, against the 10% advance")]
                  + ([Finding(key="finance", fact=e.detail, meaning="Finance's deadline", refs=[msg_ref(session, e.message_id)])] if e else []),
                  po_lines=[orders.view(session, x) for x in orders.lines_of_po(session, g.po or "")], messages=[msg_ref(session, e.message_id)] if e else [],
                  vendor=vendor_panel(session, l.identity_id if l else None), project=project_panel(session, l.project_id if l else None),
                  deadlines=deadline("ABG expires", g.expiry, f"lc_bg row {g.src_row}") + (deadline("Finance wants the extension by", e.date_to, f"message {e.message_id} {e.line_ref}") if e else []),
                  refs=[ref("abg", g.number), ref("po", g.po)])
        out.append(Found(it))
    return out


def fund_mismatch(session: Session) -> list[Found]:
    """The requirement and the fund sheet differ by more than ₹25 L or 10% for a project's head in a month. One case for the next month's sheet
    (the one Finance consolidates); the other months fold under it, and so do the sheet names nobody has resolved."""
    from app.domain.projects.model import ProjectAlias  # noqa: PLC0415

    checks = [c for c in req.fund_checks(session) if c.disagrees]
    if not checks:
        return []
    asked = next(iter(events(session, "deadline")), None)
    asked = next((e for e in events(session, "deadline") if e.ref_type == "project"), None)
    months = sorted({c.month for c in checks})
    nxt = next((m for m in months if m > TODAY[:7]), months[-1])
    mis = lookups.mis(session)
    out = []
    unresolved = list(session.scalars(select(ProjectAlias).where(ProjectAlias.method == "unresolved")))
    for month in months:
        mine = [c for c in checks if c.month == month]
        diff = sum(abs(c.difference) if c.difference is not None else c.fund for c in mine)
        pids = sorted({p for c in mine for p in (c.project_ids or "").split(",") if p})
        act = asked.date_to if asked and month == nxt else f"{month}-01"
        it = item(session, key=f"fund-mismatch:{month}", kind="fund-mismatch", tab="payments", severity="medium" if month == nxt else "low",
                  title=f"{month_year(month + '-01')} fund sheet disagrees with the material requirement on {count(len(mine), 'head')}",
                  summary=f"Payments · {', '.join(sorted({c.column_as_printed for c in mine}))} · {inr(diff)} apart",
                  owner_ids=[mis.id] if mis else [], waiting_on="SCM", projects=pids,
                  at_stake=rs(diff, "Σ |fund - requirement| over the heads that disagree (a head with no requirement counts its whole fund line)", [ref("fund_check", c.id) for c in mine]),
                  rule="Σ |difference| between the fund sheet and the requirement sheet", act_by=act,
                  next_action="Correct the fund sheet with the requirement, or ask Projects to confirm the requirement.",
                  finding=f"For {month_year(month + '-01')}, {count(len(mine), 'project head')} of the fund sheet disagree with the 3-month requirement by more than ₹25 L or 10%.",
                  findings=[Finding(key=c.id, fact=f"{c.column_as_printed} · {c.head}: fund {inr(c.fund)}, requirement {inr(c.requirement) if c.requirement is not None else 'none'}",
                                    meaning=("no requirement for a funded head" if c.requirement is None else f"{'+' if c.difference > 0 else ''}{inr(c.difference)} on the fund sheet"),
                                    refs=[ref("fund_check", c.id)]) for c in mine]
                  + ([Finding(key="unresolved", fact=f"{count(len(unresolved), 'sheet name')} not resolved to a project: " + ", ".join(sorted({a.alias for a in unresolved})[:6]),
                              meaning="Their lines cannot be compared until someone says which project they are")] if unresolved and month == nxt else []),
                  messages=[msg_ref(session, e.message_id) for e in events(session, "fund_mismatch_reported")] if month == nxt else [],
                  deadlines=deadline("Finance wants the sheet by", asked.date_to, f"message {asked.message_id} {asked.line_ref}") if asked and month == nxt else [],
                  sheet_cells=[dict(check=c.id, column=c.column_as_printed, head=c.head, fund=c.fund, requirement=c.requirement, fund_lines=c.fund_line_ids,
                                    requirement_lines=c.requirement_line_ids) for c in mine],
                  refs=[ref("project", p, lookups.project_name(session, p)) for p in pids])
        out.append(Found(it, fold_into=None if month == nxt else f"fund-mismatch:{nxt}"))
    return out


# ------------------------------------------------------------------------------------------------------------------------------- Vendor risk
def late_streak(session: Session) -> list[Found]:
    """A vendor whose last four or more receipts were each later than the line's delivery date, after a record that was on time: it has turned late."""
    out = []
    from app.domain.receipts.service import arrivals  # noqa: PLC0415

    for ident in arrivals(session):
        d = delivery(session, ident)
        if not d.turned:
            continue
        open_ = [l for l in orders.all_lines(session).values() if l.identity_id == ident and l.status == "open"]
        if not open_:
            continue
        nxt = min((l.delivery_date for l in open_ if l.delivery_date and l.delivery_date >= TODAY), default=None)
        name = lookups.vendor_name(session, ident)
        pids = sorted({l.project_id for l in open_ if l.project_id})
        it = item(session, key=f"late-streak:{ident}", kind="late-streak", tab="vendor_risk",
                  title=f"{name}: last {d.streak} receipts late",
                  summary=f"Vendor risk · +{d.streak_days[0]} to +{d.streak_days[1]} days · on time on {d.before_pct}% before · {count(len(open_), 'open line')}",
                  owner_ids=[l.buyer_id for l in open_], waiting_on="Vendor", projects=pids,
                  at_stake=rs(sum(l.open_value for l in open_), "open PO value with the vendor", [ref("po_line", l.id) for l in open_]), rule="open PO value with the vendor",
                  act_by=nxt, next_action="Ask for firm dates; line up an alternate library vendor; remind it of the LD clause.",
                  finding=d.line, findings=[Finding(key=f"r:{a.receipt}", fact=f"{a.po_line}: due {md(a.due)}, received {md(a.posted)}",
                                                    meaning=f"{'+' if a.days_late > 0 else ''}{a.days_late} days") for a in d.last[: d.streak + 2]],
                  po_lines=[orders.view(session, l) for l in open_], vendor=vendor_panel(session, ident),
                  deadlines=deadline("Next delivery due", nxt, "po_lines"), refs=[ref("supplier", ident, name)] + [ref("po_line", l.id) for l in open_])
        out.append(Found(it))
    return out


def inspection_fail(session: Session) -> list[Found]:
    """QA reports that a contractor's material failed inspection on a work order whose supply share is above half its value."""
    out = []
    for e in events(session, "inspection_failed"):
        lines = orders.lines_of_po(session, e.ref_id or "")
        if not lines or lines[0].doc_type != "ZWO":
            continue
        mats = lookups.materials(session)
        supply = [l for l in lines if l.material and mats.get(l.material) and mats[l.material].group != "SERVICE"]
        share = sum(l.value for l in supply) / sum(l.value for l in lines)
        if share <= 0.5:
            continue
        l = supply[0]
        pr_need = [p for p in prs.all_lines(session).values() if p.project_id == l.project_id and p.material == l.material and p.status == "open" and p.needed_by]
        need = min((p.needed_by for p in pr_need), default=None)
        pname = lookups.project_name(session, l.project_id)
        it = item(session, key=f"inspection-fail:{l.po_no}", kind="inspection-fail", tab="vendor_risk", severity="high",
                  title=f"{pname}: {l.short_text} under WO {l.po_no} failed QA",
                  summary=f"Vendor risk · WO {share * 100:.0f}% supply · {lookups.vendor_name(session, l.identity_id)} · {inr(sum(x.value for x in supply))} supply value",
                  owner_ids=[l.buyer_id], waiting_on="Projects", projects=[l.project_id],
                  at_stake=rs(sum(x.value for x in supply), "the WO's supply value", [ref("po_line", x.id) for x in supply]), rule="WO supply value", act_by=need,
                  next_action="Switch to a supply PO from an approved OEM; keep the contractor for laying only.",
                  finding=f"QA rejected the {l.short_text} the contractor supplied under WO {l.po_no}; supply is {share * 100:.0f}% of the WO.",
                  findings=[Finding(key="qa", fact=e.detail, meaning="Cannot be accepted", refs=[msg_ref(session, e.message_id)]),
                            Finding(key="share", fact=f"Supply lines {inr(sum(x.value for x in supply))} of {inr(sum(x.value for x in lines))}", meaning="Mostly a supply order placed as a work order")]
                  + ([Finding(key="need", fact=f"The same material is needed at {pname} by {md(need)} (PR {pr_need[0].pr_no})", meaning="The work front waits on it")] if need else []),
                  po_lines=[orders.view(session, x) for x in lines], messages=[msg_ref(session, e.message_id)], vendor=vendor_panel(session, l.identity_id),
                  project=project_panel(session, l.project_id), deadlines=deadline("Work front needs it", need, "pr_lines"),
                  refs=[ref("po", l.po_no), ref("supplier", l.identity_id, lookups.vendor_name(session, l.identity_id)), ref("project", l.project_id, pname)])
        it.site_impact = impact(session, l.project_id, [l.material], need, f"the contractor's cable failed QA; needed {md(need)}") if need else []
        out.append(Found(it))
    return out


def renamed(session: Session) -> list[Found]:
    """A vendor with two linked codes (a new legal entity) and open POs still on the old code."""
    out = []
    stop = {msg(session, e.message_id).identity_id if msg(session, e.message_id) else None: e for e in events(session, "rename_invoices_from")}
    for ident, recs in lookups.records_of(session).items():
        if len(recs) < 2:
            continue
        old = recs[0]
        open_ = [l for l in orders.all_lines(session).values() if l.record_id == old.record_id and l.status == "open"]
        if not open_:
            continue
        e = stop.get(ident)
        new = recs[-1]
        it = item(session, key=f"renamed:{ident}", kind="renamed", tab="vendor_risk",
                  title=f"{old.name} is now {new.name}: {count(len(open_), 'open line')} on the old code",
                  summary=f"Vendor risk · code {old.record_id} → {new.record_id} · new GSTIN {new.gstin}" + (f" · old entity invoices until {md(e.date_from)}" if e else ""),
                  owner_ids=[l.buyer_id for l in open_], waiting_on="SCM", projects=sorted({l.project_id for l in open_ if l.project_id}),
                  at_stake=rs(sum(l.open_value for l in open_), "open value on the old code", [ref("po_line", l.id) for l in open_]), rule="open value on the old code",
                  act_by=(date.fromisoformat(e.date_from) - timedelta(days=1)).isoformat() if e else None,
                  next_action="Verify the new entity by phone with the contact on file and ask for its GST certificate; then amend the open POs.",
                  finding=f"The vendor master links {old.record_id} and {new.record_id} (linked, never merged); open POs are still on {old.record_id}.",
                  findings=[Finding(key="link", fact=new.identity_evidence or "linked by a person's answer", meaning="Linked on evidence, not merged")],
                  po_lines=[orders.view(session, l) for l in open_], messages=[msg_ref(session, e.message_id)] if e else [], vendor=vendor_panel(session, ident),
                  deadlines=deadline("Old entity stops invoicing", e.date_from, f"message {e.message_id} {e.line_ref}") if e else [],
                  refs=[ref("supplier", ident, lookups.vendor_name(session, ident)), ref("supplier_record", old.record_id), ref("supplier_record", new.record_id)])
        out.append(Found(it))
    return out


def supply_stop(session: Session) -> list[Found]:
    """A closure or strike in a region with requirement or dispatches of the affected material groups inside its window."""
    words = {k.lower(): v for k, v in (lookups.answers().get("material_words") or {}).items()}
    mats = lookups.materials(session)
    out = []
    for e in events(session, ("closure", "strike")):
        m = msg(session, e.message_id)
        if m is None or m.trust == "blocked":
            continue
        text = (m.body or "").lower()
        start = e.date_from
        end = e.date_to or (date.fromisoformat(start) + timedelta(days=30)).isoformat()      # an indefinite strike: the next 30 days
        pids = [p for p in (e.ref_id or "").split(",") if p]
        per_project_groups: dict[str, set[str]] = {}
        for p in pids:
            pname = lookups.project_name(session, p).lower()
            sentences = [s for s in re.split(r"(?<=[.;])\s+", text) if pname in s] or [text]
            per_project_groups[p] = {g for s in sentences for w, gs in words.items() if re.search(rf"\b{re.escape(w)}\b", s) for g in gs}
        rows = []
        for p, groups in per_project_groups.items():
            codes = [c for c, mm in mats.items() if mm.group in groups]
            reqv = 0.0
            for r in req.all_lines(session):
                if r.project_id != p or not set((r.material_codes or "").split(",")) & set(codes) or not r.amount:
                    continue
                m0, m1 = f"{r.month}-01", req.month_end(r.month)
                ov = (min(date.fromisoformat(m1), date.fromisoformat(end)) - max(date.fromisoformat(m0), date.fromisoformat(start))).days + 1
                if ov > 0:
                    reqv += r.amount * ov / ((date.fromisoformat(m1) - date.fromisoformat(m0)).days + 1)
            disp = [l for l in orders.all_lines(session).values() if l.project_id == p and l.material in codes and l.status == "open" and l.delivery_date and start <= l.delivery_date <= end]
            dv = sum(l.open_value for l in disp)
            owner = Counter_most([l.buyer_id for l in orders.all_lines(session).values() if l.project_id == p and l.material in codes])
            rows.append(dict(project=p, groups=sorted(groups), value=reqv or dv, basis="requirement" if reqv else "dispatches", lines=disp, owner=owner))
        empty = [r["project"] for r in rows if not r["value"]]
        rows = [r for r in rows if r["value"]]
        if not rows:
            continue
        total = sum(r["value"] for r in rows)
        what = "Quarry closure" if e.kind == "closure" else "Transport strike"
        names = ", ".join(lookups.project_name(session, r["project"]) for r in rows)
        # the material master's category names the groups in words (ELE-MISC and ELE-SWG are both electrical equipment)
        kinds = lambda groups: sorted({(next((mm.category for mm in mats.values() if mm.group == g and mm.category), None) or g).lower() for g in groups})  # noqa: E731
        it = item(session, key=f"supply-stop:{e.message_id}", kind="supply-stop", tab="vendor_risk", severity="high",
                  title=f"{what} from {md(start)}: {names}",
                  summary=f"Vendor risk · {', '.join(kinds({g for r in rows for g in r['groups']}))} · {md(start)} to {md(e.date_to) if e.date_to else 'no end date'}",
                  owner_ids=[r["owner"] for r in rows if r["owner"]], waiting_on="Vendor", projects=[r["project"] for r in rows],
                  at_stake=rs(total, "requirement (pro rata by days) or open dispatches of the affected materials inside the window"),
                  rule="value of requirement / dispatches in the window", act_by=start,
                  next_action="Confirm alternate supply and rate with the vendor; draw from site stockpile; tell Projects the expected slowdown.",
                  finding=f"{what} from {dmy(start)}" + (f" to {dmy(e.date_to)}" if e.date_to else " with no end date (the next 30 days counted)") + f": {names}.",
                  findings=[Finding(key=f"p:{r['project']}", fact=f"{lookups.project_name(session, r['project'])}: {', '.join(kinds(r['groups']))} worth {inr(r['value'])} in the window ({r['basis']})",
                                    meaning="Up to: site stock is not in the data", refs=[ref("project", r["project"])]) for r in rows]
                  + ([Finding(key="nothing_on_file", fact=f"{', '.join(lookups.project_name(session, p) for p in empty)}: no open PO due in the window and no requirement sheet for the material",
                              meaning="Nothing on file to be held; ask the site whether anything is in transit")] if empty else []),
                  messages=[msg_ref(session, e.message_id)], vendor=vendor_panel(session, m.identity_id) if e.kind == "closure" else None,
                  deadlines=deadline("Starts", start, f"message {e.message_id} {e.line_ref}") + (deadline("Ends", e.date_to, f"message {e.message_id} {e.line_ref}") if e.date_to else []),
                  refs=[ref("project", r["project"], lookups.project_name(session, r["project"])) for r in rows] + ([ref("supplier", m.identity_id)] if m.identity_id else []))
        imp = []
        for r in rows:
            codes = [c for c, mm in mats.items() if mm.group in set(r["groups"])]
            imp += impact(session, r["project"], codes, start, f"{what.lower()} from {md(start)}")
        it.site_impact = imp
        f = Found(it)
        for r in rows:
            if r["owner"]:
                s = f.shares.setdefault(r["owner"], dict(amount=0.0, projects=[]))
                s["amount"] += r["value"]
                s["projects"].append(r["project"])
        f.shares = {b: dict(at_stake=rs(s["amount"], "your projects' requirement or dispatches in the window"), projects=[proj_ref(session, p) for p in s["projects"]],
                            title=f"{what} from {md(start)}: {', '.join(lookups.project_name(session, p) for p in s['projects'])}") for b, s in f.shares.items()}
        out.append(f)
    return out


def Counter_most(ids: list) -> str | None:
    ids = [i for i in ids if i]
    return max(set(ids), key=ids.count) if ids else None


# ------------------------------------------------------------------------------------------------------------------------------- Trust
CONTROLS = {
    "bank_detail_change": "Do not pay or change the vendor master: confirm by phone with the contact on file, on the number on file",
    "lookalike_vendor": "Report the look-alike domain to IT",
    "lookalike_internal": "Confirm with the sender in person or on the number on file (the internal look-alike)",
    "instruction_in_message": "Do not act on the offer: nothing is pre-approved, and no order is placed from a message",
    "report_instruction": "Report the message to IT: it carries text aimed at automated systems",
    "inform_finance": "Inform Finance (Treasury) so no payment is released",
}


def trust(session: Session) -> list[Found]:
    """A message the trust check held: a look-alike of a vendor's or the company's own domain, a free-mail reply-to, a change of bank details, or text
    aimed at software. Nothing is drafted from it; the controls are recorded with who and when."""
    out = []
    claims = {e.message_id: e for e in events(session, "remittance_change")}
    for m in session.scalars(select(Message).where(Message.trust == "blocked").order_by(Message.date)):
        flags = [f for f in (m.trust_flags or "").split(",") if f]
        known = {r.email_domain for r in lookups.records(session).values() if r.email_domain} | {lookups.answers().get("internal_domain")}
        imit = trust_rules.imitated_domain(m.from_domain or "", known)
        c = claims.get(m.id)
        offer = next(iter(quotes.mail_quotes(session, m.id)), None)
        claimed = c.qty if c else ((offer.rate or 0) * (offer.qty or 0) if offer else None)
        controls = []
        if "bank_detail_change" in flags or c:
            controls += [CONTROLS["bank_detail_change"], CONTROLS["inform_finance"]]
        if m.sender_class == "lookalike_vendor":
            controls.append(CONTROLS["lookalike_vendor"])
        if m.sender_class == "lookalike_internal":
            controls = [CONTROLS["lookalike_internal"], CONTROLS["inform_finance"], CONTROLS["lookalike_vendor"]]
        if "instruction_in_message" in flags:
            controls += [CONTROLS["instruction_in_message"], CONTROLS["report_instruction"]]
        words = [trust_rules.FLAG_WORDS.get(f, f.replace("_", " ")) for f in flags]
        who = {"lookalike_vendor": "look-alike of a vendor", "lookalike_internal": "look-alike of the company's own domain", "unknown": "sender not on file"}.get(m.sender_class, m.sender_class)
        it = item(session, key=f"trust:{m.id}", kind="trust", tab="trust", severity="high",
                  title=f"Held: {m.subject}", summary=f"Trust · {who} · {m.from_email}",
                  owner_ids=addressee(session, m.id), waiting_on="SCM", projects=[p for p in (c.ref_id.split(",") if c and c.ref_type == "project" and c.ref_id else [])],
                  at_stake=rs(claimed, "the amount the message asks for (a claim, not a payable)", source=f"message:{m.id}", row=c.line_ref if c else (offer.line_ref if offer else None),
                              method="extracted") if claimed else None,
                  label="claimed", rule="the message's claim (not a payable)", act_by=TODAY,
                  next_action="Record the controls: nothing is paid, ordered or drafted from this message.",
                  finding=f"Held before anyone read it: {'; '.join(words)}.",
                  findings=[Finding(key=f, fact=w, meaning="Blocks: nothing may follow from the message" if f in trust_rules.BLOCK else "Asks a person to look") for f, w in zip(flags, words)],
                  messages=[msg_ref(session, m.id)],
                  held=HeldMessage(message=msg_ref(session, m.id), sender=f"{m.from_name} <{m.from_email}>", imitates=imit[0] if imit else None, flags=words,
                                   claimed=rs(claimed, "claimed in the message", source=f"message:{m.id}", method="extracted") if claimed else None, controls=controls),
                  refs=[msg_ref(session, m.id)])
        out.append(Found(it))
    return out


# ------------------------------------------------------------------------------------------------------------------------------- Unknowns
def unknowns(session: Session) -> list[Found]:
    out = []
    # PR lines with no project
    lines = [l for l in prs.all_lines(session).values() if not l.project_id and l.status == "open"] or [l for l in prs.all_lines(session).values() if not l.project_id]
    if lines:
        vals = [(l, pr_value(session, l)[0]) for l in lines]
        priced = sum(v for _l, v in vals if v)
        f = Found(item(session, key="unknown:pr-no-project", kind="unknown", tab="unknown", severity="low",
                       title=f"{count(len(lines), 'PR line')} with no project",
                       summary=f"Unknowns · raised at the head-office plant with no tracking number · {inr(priced)} where a rate is on file",
                       owner_ids=[l.buyer_id for l in lines], waiting_on="Projects", projects=[],
                       at_stake=rs(priced, "PR quantity x last PO rate, where one is on file (labelled: the rest has no rate)"), label="where a rate exists",
                       rule="count; value where a rate exists", next_action="Ask each requisitioner which project the PR is for.",
                       finding="These PRs carry no tracking number, so their spend and turnaround land on no project.",
                       unknowns=[unknown(f"the project of PR {l.pr_no}", "spend and turnaround land on no project", l.buyer_id or "unassigned",
                                         f"Which project is PR {l.pr_no} ({l.short_text}) for? (raised by {l.requisitioner})", [ref("pr_line", l.id)]) for l in lines],
                       pr_lines=[prs.view(session, l) for l in lines], refs=[ref("pr_line", l.id) for l in lines]))
        for b in {l.buyer_id for l in lines}:
            mine = [l for l, _v in vals if l.buyer_id == b]
            f.shares[b] = dict(title=f"{count(len(mine), 'PR line')} with no project", pr_lines=[prs.view(session, l) for l in mine],
                               at_stake=rs(sum(v for l, v in vals if l.buyer_id == b and v), "your lines where a rate exists"))
        out.append(f)
    # requirement lines with no budget rate
    missing = []
    for r in req.all_lines(session):
        if not r.project_id:
            continue
        codes = [c for c in (r.material_codes or "").split(",") if c]
        if codes and not any(quotes.budget_rate(session, r.project_id, c) for c in codes):
            missing.append(r)
    pairs = sorted({(r.project_id, r.row_as_printed) for r in missing})
    if pairs:
        groups = {r.project_id: r for r in missing}
        buyer_of = {}
        for r in missing:
            codes = (r.material_codes or "").split(",")
            buyer_of[(r.project_id, r.row_as_printed)] = Counter_most([l.buyer_id for l in orders.all_lines(session).values() if l.material in codes and l.project_id == r.project_id]) or \
                Counter_most([l.buyer_id for l in orders.all_lines(session).values() if l.material in codes])
        f = Found(item(session, key="unknown:no-budget-rate", kind="unknown", tab="unknown", severity="low",
                       title=f"{count(len(pairs), 'requirement line')} with no budget rate",
                       summary=f"Unknowns · {', '.join(sorted({lookups.project_name(session, p) for p, _ in pairs}))} · purchases cannot be compared with the estimate",
                       owner_ids=[b for b in buyer_of.values() if b], waiting_on="Projects", projects=sorted(groups),
                       next_action="Ask each project for the BOQ / tender rate.",
                       finding="Without a budget rate, a quote or a PO for these materials cannot be compared with the estimate.",
                       unknowns=[unknown(f"the budget rate for {row} at {lookups.project_name(session, p)}", "a purchase cannot be compared with the estimate",
                                         lookups.contact_for(session, "planner", p).id if lookups.contact_for(session, "planner", p) else "unassigned",
                                         f"What is the BOQ / tender rate for {row} at {lookups.project_name(session, p)}?") for p, row in pairs],
                       refs=[ref("project", p, lookups.project_name(session, p)) for p in sorted(groups)]))
        out.append(f)
    # POs released to vendors not in the approved library
    outside = [l for l in orders.all_lines(session).values() if "not_in_library" in (l.flags or "")]
    if outside:
        open_ = [l for l in outside if l.status == "open"]
        gm = lookups.duty(session, "vendor_library")      # the library's holder (answers.yaml team duties) owns the question with the buyers
        f = Found(item(session, key="unknown:not-in-library", kind="unknown", tab="unknown", severity="low",
                       title=f"{count(len({l.po_no for l in outside}), 'PO')} to vendors not in the approved library",
                       summary=f"Unknowns · {count(len({l.identity_id for l in outside}), 'vendor')} · {inr(sum(l.open_value for l in open_))} still open",
                       owner_ids=([gm.id] if gm else []) + [l.buyer_id for l in outside], waiting_on="SCM", projects=sorted({l.project_id for l in outside if l.project_id}),
                       at_stake=rs(sum(l.open_value for l in open_), "open value with vendors outside the library (labelled, not a loss)"), label="open, outside the library",
                       rule="open value, labelled", next_action="Ask who approved each vendor, or add it to the library with its approval.",
                       finding="The library approves technical vendors by vertical; these POs went to vendors it does not list.",
                       unknowns=[unknown(f"who approved {lookups.vendor_name(session, i)}", "an unapproved vendor carries quality and payment risk", next(l.buyer_id for l in outside if l.identity_id == i) or "unassigned",
                                         f"Who approved {lookups.vendor_name(session, i)} for {', '.join(sorted({l.short_text for l in outside if l.identity_id == i}))[:80]}?")
                                 for i in sorted({l.identity_id for l in outside})],
                       po_lines=[orders.view(session, l) for l in outside], refs=[ref("supplier", i, lookups.vendor_name(session, i)) for i in sorted({l.identity_id for l in outside})]))
        out.append(f)
    return out


DETECTORS = [pr_late, pr_stuck, pr_cancelled, mfc_validity, inspection_ready, commissioning, schedule_slip, pv_longlead, price_notice, pv_claim, quote_lapse,
             l1_above_last, rate_spread, lc, abg, fund_mismatch, late_streak, inspection_fail, renamed, supply_stop, trust, unknowns]
