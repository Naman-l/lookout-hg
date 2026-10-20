"""The new China duty: does it apply, to what, and how much. Code does every sum; each result carries its rule.

One exposure rule for every money figure. A line is *exposed* if it is promised on or after the rule's effective date, has
no promise date, is past due at AS_OF (entry date unknown: at risk unless it lands first), or is under force majeure. Stale
legacy lines are excluded from net. **Net** = exposed open lines + the 12-month requirement not covered by open supply,
valued at the reference price. **Gross** = every open line + the full 12-month requirement. Duty = base x rate.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.cache import memo
from app.domain.common.company import company_name
from app.domain.fmt import md
from app.domain.inbox.model import Message, MessageEvent
from app.domain.common import AS_OF
from app.domain.demand import service as demand
from app.domain.orders import service as orders
from app.domain.orders.model import ReferencePrice
from app.domain.parts.model import Part
from app.domain.tariffs.model import TariffExclusion, TariffRule
from app.domain.suppliers.model import SupplierRecord
from app.domain.orders.model import PoLine
from app.domain.tariffs.schema import CooStatus, ExposureLine, LineDuty, PartExposure, TariffRuleView, TariffStatus
from app.domain.ownership import buyer_of_part
from app.domain.values import prov, ref, unknown, usd

@memo
def tariff_categories(session: Session) -> frozenset[str]:
    """Categories that hold at least one part on a listed code (motors, converters, batteries ... in this master): a blank code matters only
    for a China-origin part in one of these. A blank code on a grommet is a data defect, not a tariff question. Learned from the rules and
    the item master, so a new category or a new rule needs no edit here."""
    prefixes = tuple(r.hts_prefix for r in session.scalars(select(TariffRule)))
    return frozenset(p.category for p in session.scalars(select(Part).where(Part.hts.is_not(None))) if p.category and p.hts.startswith(prefixes))


@memo
def restart_window(session: Session, identity_id: str) -> tuple[str, str, str, str] | None:
    """When a supplier under force majeure says it can ship again, read from its notice's event record: (earliest, latest, notice date, notice message id),
    or None when the notice gives no range. The earliest is the notice date plus the low end of "6 to 8 weeks"; the latest is the record's own end date."""
    ev = session.scalars(select(MessageEvent).where(MessageEvent.kind == "force_majeure", MessageEvent.ref_type == "supplier", MessageEvent.ref_id == identity_id)
                         .order_by(MessageEvent.date_to.desc())).first()
    m = re.search(r"resumes in (\d+) to (\d+) weeks", ev.detail or "") if ev else None
    sent = session.scalar(select(Message.date).where(Message.id == ev.message_id)) if ev else None
    if not (m and sent and ev.date_to):
        return None
    return (date.fromisoformat(sent[:10]) + timedelta(weeks=int(m.group(1)))).isoformat(), ev.date_to, sent[:10], ev.message_id


def _view(r: TariffRule) -> TariffRuleView:
    return TariffRuleView(id=r.id, tranche=r.tranche, hts_prefix=r.hts_prefix, description=r.description, rate=r.rate,
                          effective_date=r.effective_date, origin=r.origin, in_transit=r.in_transit,
                          exported_before=r.exported_before, entered_before=r.entered_before,
                          source_line=r.source_line, advisory_no=r.advisory_no, issued=r.issued)


def rule_sentences(rule: TariffRuleView | TariffRule) -> dict[str, str]:
    """The one sentence that states each bucket's rule for this tariff rule: the same words in the figure, the screen, the agent and the oracle."""
    pct, eff = f"{rule.rate:.0%}", md(rule.effective_date)
    if rule.entered_before:
        last = md((date.fromisoformat(rule.entered_before) - timedelta(days=1)).isoformat())
        owed = (f"{pct} of the price of China-origin parts that will enter on or after {eff}: the need not yet on order, "
                f"open orders due after {last}, and open orders of a supplier whose force majeure notice puts its restart after {eff}.")
        cond = (f"Open orders that owe nothing if the supplier ships them before {md(rule.exported_before)} and they enter before {md(rule.entered_before)}; "
                "the ship date is unknown, ask the supplier.")
    else:
        owed = (f"{pct} of the price of China-origin parts that will enter on or after {eff}: the need from then on that is not yet on order, open orders due then or later, "
                f"and open orders of a supplier whose force majeure notice puts its restart after {eff}.")
        cond = f"Open orders with no known entry date: owed only if they enter on or after {eff}; ask the supplier for the date."
    return {"owed": owed, "conditional": cond,
            "if_china": "Parts whose origin is unknown: what they would owe if they are made in China; ask the supplier for the origin."}


def _owner(session: Session, p: Part | None, part: str | None = None) -> str:
    return buyer_of_part(session, p.part_number if p else part)


def tariff_rule_for(session: Session, part: str) -> TariffStatus:
    """Is the part's HTS code on the list (longest matching prefix), excluded, or unknowable?"""
    p = session.get(Part, part)
    me = ref("part", part)
    if p is None or not p.hts:
        return TariffStatus(part=me, status="unknown_hts", unknown=unknown(
            "HTS code", "the duty depends on the tariff code; this part has none", _owner(session, p, part),
            f"What is the HTS classification of {part}?", [me]))
    for ex in session.scalars(select(TariffExclusion)):
        if p.hts.startswith(ex.hts_prefix):
            return TariffStatus(part=me, status="excluded", excluded_by=f"{ex.hts_prefix_raw}: {ex.description}")
    hits = [r for r in session.scalars(select(TariffRule)) if p.hts.startswith(r.hts_prefix)]
    if not hits:
        return TariffStatus(part=me, status="not_listed")
    r = max(hits, key=lambda r: len(r.hts_prefix))
    return TariffStatus(part=me, status="listed", rule=_view(r))


def coo_status(session: Session, part: str) -> CooStatus:
    p = session.get(Part, part)
    me = ref("part", part)
    if p is None or not p.coo:
        return CooStatus(part=me, status="unknown", coo=None, unknown=unknown(
            "country of origin", "the duty follows origin, not the supplier's country", _owner(session, p, part),
            f"Where is {part} made? Ask the supplier for a certificate of origin.", [me]))
    return CooStatus(part=me, status="china" if p.coo == "CN" else "other", coo=p.coo)


def _importer(session: Session, record_id: str | None) -> str:
    """DDP: the supplier delivers duty paid and is importer of record. FOB, FCA, EXW, DAP, CIF, blank: the company clears the goods."""
    rec = session.get(SupplierRecord, record_id) if record_id else None
    return "supplier" if rec and rec.incoterm == "DDP" else "company"


@memo
def _incoterm(session: Session, record_id: str | None) -> tuple[str | None, str | None]:
    """The record's term as the ERP has it, and what it means for the duty in words: ("FOB Shenzhen", "FOB: the company clears the goods and pays the duty")."""
    c = company_name(session)
    rec = session.get(SupplierRecord, record_id) if record_id else None
    if rec is None or not rec.incoterm:
        return None, f"no Incoterm on the supplier record: who pays the duty is not recorded, so {c} is assumed to"
    term = rec.incoterm + (f" {rec.incoterm_place}" if rec.incoterm_place else "")
    if rec.incoterm == "DDP":
        return term, "DDP: the supplier is importer of record and pays the duty at entry; expect it in the price"
    says = {"FOB": f"{c} arranges the shipping, imports the goods and pays the duty", "FCA": f"{c} arranges the main carriage, imports the goods and pays the duty",
            "EXW": f"{c} collects, imports the goods and pays the duty", "DAP": f"the supplier delivers but {c} clears customs and pays the duty",
            "CIF": f"the supplier pays freight and insurance but {c} clears customs and pays the duty"}.get(rec.incoterm, f"{c} clears the goods and pays the duty")
    return term, f"{rec.incoterm}: {says}"


def exposure_for_part(session: Session, part: str, *, as_of=AS_OF) -> PartExposure:
    t, c = tariff_rule_for(session, part), coo_status(session, part)
    me = ref("part", part)
    base = dict(part=me, tariff=t, coo=c, open_lines=[], uncovered_qty=0.0, reference_price=None, unpriced=False,
                effective_date=None, rate=None, net=None, gross=None)
    p_ = session.get(Part, part)
    if t.status == "unknown_hts":
        if p_ is not None and p_.coo == "CN" and p_.category in tariff_categories(session):
            return PartExposure(status="unknown_hts", unknown=t.unknown, **base)
        return PartExposure(status="not_applicable", **base)
    if t.status != "listed" or c.status == "other":
        return PartExposure(status="not_applicable", **base)
    rate, effective = t.rule.rate, t.rule.effective_date
    supply = orders.open_supply(session, part, as_of=as_of)
    reqs = demand.requirements(session, part)
    need = sum(float(r.qty.value) for r in reqs)
    rp = session.get(ReferencePrice, part)
    price = rp.usd_each if rp else None
    sentences = rule_sentences(t.rule)
    entered_before = t.rule.entered_before
    lines, owed_open, cond_open, gross_open, live_qty, passed = [], 0.0, 0.0, 0.0, 0.0, 0.0
    unrated, counted = [], 0.0
    for s in supply:
        fm = None
        if s.open_value.usd is None:   # no exchange rate for its order month: its dollar value is unknown, so it is in no total
            unrated.append(s.po_line)
            lines.append(ExposureLine(po_line=s.po_line, open_value=s.open_value, exposed=False, bucket="out", importer="company",
                                      why="no exchange rate for its order month: its value in dollars is unknown and it is left out of the totals"))
            continue
        v = float(s.open_value.usd)
        counted += v
        imp = _importer(session, s.record.id)
        term, says = _incoterm(session, s.record.id)
        if imp == "supplier":
            passed += v
            lines.append(ExposureLine(po_line=s.po_line, open_value=s.open_value, exposed=False, bucket="pass_through", importer="supplier", incoterm=term, incoterm_says=says,
                                      why="DDP: the supplier is importer of record and pays the duty; expect it in the price"))
            if not s.stale:
                live_qty += float(s.qty.value)
            continue
        gross_open += v
        if not s.stale:
            live_qty += float(s.qty.value)
        # The promise date is the delivery date, so the goods entered the country before it. Entry on or after the effective date and,
        # where the notice gives an in-transit window, after its end is certain duty; inside the window it depends on the ship date;
        # no usable date (force majeure, past due, undated) is the same unknown.
        if s.stale:
            bucket, why = "out", "ordered over a year ago and still open: probably not open; in gross only"
        elif s.disrupted_by and (rw := restart_window(session, s.supplier.id)) and rw[0] > effective:
            # The notice puts the earliest restart after the duty date, so nothing can ship before it: the goods enter on or after it.
            bucket = "owed"
            why = f"the supplier cannot ship before {md(effective)} (force majeure notice, {md(rw[2])}): its earliest restart is {md(rw[0])}, its latest {md(rw[1])}"
            fm = ref("message", rw[3])
        elif s.disrupted_by or s.promise is None or s.promise < as_of.isoformat():
            why = ("under force majeure: its promise date no longer holds" if s.disrupted_by else "no promise date: entry date unknown" if s.promise is None
                   else "past due: entry date unknown")
            bucket, why = "conditional", f"{why}. " + sentences["conditional"]
        elif s.promise < effective:
            bucket, why = "not_owed", f"promised {s.promise}, before {effective}: enters before the duty applies"
        elif entered_before and s.promise < entered_before:
            bucket, why = "conditional", f"promised {s.promise}, inside the in-transit window. " + sentences["conditional"]
        else:
            bucket, why = "owed", f"promised {s.promise}, after the in-transit window: enters on or after {effective}" if entered_before else f"promised {s.promise}, on or after {effective}"
        owed_open += v if bucket == "owed" else 0.0
        cond_open += v if bucket == "conditional" else 0.0
        lines.append(ExposureLine(po_line=s.po_line, open_value=s.open_value, exposed=bucket in ("owed", "conditional"), bucket=bucket, importer="company", incoterm=term, incoterm_says=says, why=why, under_force_majeure=fm))
    # The need not yet on order is bought now and enters after the effective date; only the months from then on count (earlier months are covered by what is in flight).
    need_after = sum(float(r.qty.value) for r in reqs if r.month >= effective[:7])
    uncovered = max(need - live_qty, 0.0)
    uncovered_owed = min(uncovered, need_after)
    ref_ddp = rp is not None and _importer(session, session.get(PoLine, rp.po_line_id).record_id) == "supplier"
    unpriced = bool((need > 0) and price is None)
    p_ = price or 0.0
    p_prov = prov("computed", "po_lines", row=rp.po_line_id if rp else None, rule="reference price: latest clean PO line, USD each",
                  inputs=[ref("po_line", rp.po_line_id)] if rp else [])
    inputs = [ref("part", part)] + [l.po_line for l in lines]
    gv = prov("computed", "po_lines", rule=f"{rate:.0%} of every open order plus the whole 12-month need, at the reference price (gross)", inputs=inputs, by="tariffs.exposure_for_part")
    if ref_ddp:  # the requirement would be bought from a DDP supplier: pass-through
        passed += need * p_
        owed_amt, gross_amt = owed_open * rate, gross_open * rate
    else:
        owed_amt, gross_amt = (owed_open + uncovered_owed * p_) * rate, (gross_open + need * p_) * rate
    net = owed = usd(owed_amt, prov("computed", "po_lines", rule=sentences["owed"], inputs=inputs, by="tariffs.exposure_for_part"))
    gross = usd(gross_amt, gv)
    conditional = usd(cond_open * rate, prov("computed", "po_lines", rule=sentences["conditional"], inputs=[l.po_line for l in lines if l.bucket == "conditional"], by="tariffs.exposure_for_part")) if cond_open else None
    passm = usd(passed * rate, prov("computed", "po_lines", rule="duty on DDP lines and requirement, borne by the supplier and passed through in price", inputs=inputs, by="tariffs.exposure_for_part")) if passed else None
    status = "china_listed" if c.status == "china" else "unknown_origin"
    ov = prov("computed", "po_lines", rule="open value of the lines that have an exchange rate" + (f"; excludes {len(unrated)} without a rate" if unrated else ""), inputs=[l.po_line for l in lines if l.po_line not in unrated], by="tariffs.exposure_for_part")
    open_value = usd(counted, ov) if lines else None
    open_duty = usd(counted * rate, prov("computed", "po_lines", rule=f"{rate:.0%} of the open value of the lines that have an exchange rate" + (f"; excludes {len(unrated)} without a rate" if unrated else ""),
                                         inputs=[l.po_line for l in lines if l.po_line not in unrated], by="tariffs.exposure_for_part")) if lines and c.status == "china" else None
    if status == "unknown_origin":   # origin unknown: one figure, "if China", never in the headline
        if_china = usd(owed_amt + cond_open * rate, prov("computed", "po_lines", rule=sentences["if_china"], inputs=inputs, by="tariffs.exposure_for_part"))
        net, owed, conditional = if_china, None, None
    else:
        if_china = None
    return PartExposure(part=me, tariff=t, coo=c, status=status, rate=rate, net=net, owed=owed, conditional=conditional, if_china=if_china, rule_sentences=sentences, gross=gross, open_lines=lines, open_value_total=open_value, open_duty_total=open_duty,
                        lines_without_rate=unrated,
                        uncovered_qty=uncovered, reference_price=usd(price, p_prov) if price else None, unpriced=unpriced,
                        effective_date=effective, unknown=c.unknown, pass_through=passm)


@memo
def all_exposures(session: Session) -> list[PartExposure]:
    """Exposure for every part that could be on the list (listed code, or origin/HTS unknown), computed once."""
    out = []
    prefixes = tuple(r.hts_prefix for r in session.scalars(select(TariffRule)))
    for p in session.scalars(select(Part).where(Part.kind == "purchased").order_by(Part.part_number)):
        if p.hts and not p.hts.startswith(prefixes):
            continue  # a code that matches no rule can never be exposed
        if p.coo and p.coo != "CN":
            continue
        e = exposure_for_part(session, p.part_number)
        if e.status != "not_applicable":
            out.append(e)
    return out


def duty_for_line(session: Session, po_line_id: str, *, as_of=AS_OF) -> LineDuty:
    """The new duty on one open PO line: owed, passed through (DDP), before the effective date, not applicable, or unknown."""
    line = session.get(PoLine, po_line_id)
    me = ref("po_line", po_line_id)
    if line is None or line.status not in ("OPEN", "PARTIAL"):
        return LineDuty(po_line=me, status="not_applicable", duty=None, importer=None, why="not an open line")
    t, c = tariff_rule_for(session, line.part_number), coo_status(session, line.part_number)
    if t.status == "unknown_hts":
        return LineDuty(po_line=me, status="unknown", duty=None, importer=None, why="no HTS code on the part", unknown=t.unknown)
    if t.status != "listed" or c.status == "other":
        return LineDuty(po_line=me, status="not_applicable", duty=None, importer=None, why="the part is not on the list, or is not of China origin")
    if c.status == "unknown":
        return LineDuty(po_line=me, status="unknown", duty=None, importer=None, why="origin unknown: the duty depends on it", unknown=c.unknown)
    imp = _importer(session, line.record_id)
    term, says = _incoterm(session, line.record_id)
    if line.open_usd is None:
        return LineDuty(po_line=me, status="unknown", duty=None, importer=None, why="no exchange rate for its order month: the line's value in dollars is unknown",
                        unknown=unknown("the dollar value of this line", "no exchange rate is on file for its order month", buyer_of_part(session, line.part_number, line.buyer_id),
                                        f"What exchange rate applies to {line.id}?", [me]))
    value = line.open_usd
    duty = usd(value * t.rule.rate, prov("computed", "po_lines", row=line.id, rule=f"open value x {t.rule.rate:.0%}", inputs=[me], by="tariffs.duty_for_line"))
    if imp == "supplier":
        return LineDuty(po_line=me, status="pass_through", duty=duty, importer="supplier", incoterm=term, incoterm_says=says, why=f"DDP: the supplier pays at entry; expect it in the price ({company_name(session)}'s own duty is 0)")
    if line.promised_date and as_of.isoformat() <= line.promised_date < t.rule.effective_date and "stale_open" not in (line.flags or ""):
        return LineDuty(po_line=me, status="before_effective_date", duty=duty, importer="company", incoterm=term, incoterm_says=says,
                        why=f"promised {line.promised_date}, before {t.rule.effective_date}: no duty if it enters on time")
    return LineDuty(po_line=me, status="owed", duty=duty, importer="company", incoterm=term, incoterm_says=says, why="enters on or after the effective date, or its date is unknown")
