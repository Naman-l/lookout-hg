"""House style, in code, applied before a draft's payload hash so the text a buyer signs is the same whoever drafted it.

A letter to a vendor: "Kind Attn: <the contact on file>" and the company, "Sub:", "Ref: PO No. ... dated ...; your letter dated ...", "Dear Sir/Madam,",
the ask with every figure from the records (quantities with units in Indian digit grouping), "Kindly confirm by <date>.", "This is without prejudice
to our rights under the PO." where the letter answers a claim or a notice, and the signature: name, role, "Supply Chain Management", the company.
A note to someone inside the company is a short memo: To / From / Date / Subject, two or three sentences, the ask and its date.
No draft mentions bank details or payments to an account (refused). Nothing here adds a figure or a date of its own.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from app.domain.common import AS_OF
from app.domain.fmt import dmy, en_in, inr, long_date, md, qty_text

FORBIDDEN = re.compile(
    r"\b(iban|swift|bic\b|ifsc|sort code|routing (number|no)|bank (account|details?|info(rmation)?|transfer|name|code)|account (number|no\b|details?)|wire (transfer|the|us|to)|"
    r"remit(tance)? (details?|address|instructions?)|(new|updated|changed|different) (payment|banking|bank|remittance) (details?|instructions?|account|information)|"
    r"(send|transfer|deposit) (the )?(money|funds|payment)|beneficiary|utr)\b", re.I)
RESERVE = "This is without prejudice to our rights under the PO."
CLOSING = re.compile(r"^(regards|best regards|thanks and regards|thanking you|yours (sincerely|faithfully))\b", re.I)


class DraftRefused(Exception):
    pass


def reply_by(act_by: str | None) -> date:
    """Two weeks before the act-by so the answer can still be acted on, never sooner than five days from the data date, never after the act-by;
    a case already due asks for three days."""
    if not act_by:
        return AS_OF + timedelta(days=5)
    due = date.fromisoformat(act_by[:10])
    if due <= AS_OF:
        return AS_OF + timedelta(days=3)
    return min(due, max(AS_OF + timedelta(days=5), due - timedelta(days=14)))


def signature(member, company: str) -> str:
    return f"Regards,\n{member.name}\n{member.role}\nSupply Chain Management\n{company}"


def vendor_letter(*, contact: str | None, vendor: str, subject: str, refs: list[str], paras: list[str], confirm_by: date, member, company: str,
                  reserve: bool = False) -> str:
    head = (f"Kind Attn: {contact}\n" if contact else "") + f"M/s {vendor}\n\nSub: {subject}\n" + (f"Ref: {'; '.join(refs)}\n" if refs else "")
    body = [head.rstrip(), "Dear Sir/Madam,", *paras, f"Kindly confirm by {dmy(confirm_by.isoformat())}."]
    if reserve:
        body.append(RESERVE)
    body.append(signature(member, company))
    text = "\n\n".join(body)
    return style(text)


def memo(*, to_name: str, to_role: str, member, subject: str, paras: list[str]) -> str:
    head = f"To: {to_name}, {to_role}\nFrom: {member.name}, {member.role}, SCM\nDate: {dmy(AS_OF.isoformat())}\nSubject: {subject}"
    return style("\n\n".join([head, *paras, member.name.split()[0]]))


UNIT_WORDS = {"NO": "Nos.", "KM": "km", "SET": "sets", "LOT": "lots", "RM": "RM", "MT": "MT", "SQM": "sq m", "BAG": "bags", "KG": "kg", "LTR": "litres"}


def q(value: float, uom: str | None) -> str:
    """A quantity as a letter writes it: '2 Nos.', '18 km', '1,28,000 MT'."""
    v = float(value)
    return f"{en_in(v) if v == int(v) else en_in(v, 2)} {UNIT_WORDS.get((uom or '').upper(), uom or '')}".strip()


def style(text: str) -> str:
    """Quantities of a thousand or more read with Indian digit grouping ("27000 NO" -> "27,000 NO"); no ISO date survives."""
    text = re.sub(r"\b(\d{4,})(?=\s?(?:NO|nos\.?|KM|MT|SET|RM|LOT|SQM|bags?)\b)", lambda m: en_in(int(m.group(1))), text)
    text = re.sub(r"\b(20\d\d)-(\d\d)-(\d\d)\b", lambda m: dmy(m.group(0)), text)
    if FORBIDDEN.search(text):
        raise DraftRefused("a draft may not mention bank details or payments to an account")
    return text


def add_paragraph(body: str, para: str) -> str:
    """Add an ask to a letter waiting to the same contact: before its 'Kindly confirm by' line, so the letter still ends on its date and signature."""
    parts = body.split("\n\n")
    at = next((i for i, p in enumerate(parts) if p.startswith("Kindly confirm by")), None)
    if at is None:
        at = next((i for i in range(len(parts) - 1, -1, -1) if CLOSING.match(parts[i])), len(parts))
    return style("\n\n".join([*parts[:at], para, *parts[at:]]))


# ----------------------------------------------------------------------------------------------------------- what each route asks, from the case
def _po_ref(d) -> str | None:
    po = d.po_lines[0] if d.po_lines else None
    return f"PO No. {po.po} dated {dmy(po.doc_date)}" if po else None


def _their_letter(d, msgs: dict) -> str | None:
    m = next((msgs.get(x.id) for x in d.messages if msgs.get(x.id) and msgs[x.id].sender_class == "vendor"), None)
    return f"your letter dated {dmy(m.date[:10])}" if m else None


def _lines_text(d, *, revised: bool = False) -> list[str]:
    out = []
    for l in d.po_lines[:8]:
        line = f"PO {l.po} item {l.item}: {l.text}, {q(l.open_qty, l.uom)} open, due {md(l.delivery_date)}"
        if revised and l.revised:
            line += f" (your revised date {', '.join(md(r.date) for r in l.revised)})"
        out.append("• " + line)
    return out


def vendor_ask(kind: str, d, route, *, vendor: str, msgs: dict) -> tuple[str, list[str], list[str], bool]:
    """(subject, refs, paragraphs, reserve rights) for a letter to a vendor on route `kind` of case `d`. Every figure is the case's."""
    po = d.po_lines[0] if d.po_lines else None
    refs = [x for x in (_po_ref(d), _their_letter(d, msgs)) if x]
    site = d.projects[0].label if d.projects else ""
    k = d.kind
    if kind == "expedite_l1":
        pl = d.pr_lines[0]
        return (f"Expedited delivery: {pl.text}, {site}", [f"Our RFQ under {d.cs.cs}" if d.cs else ""],
                [f"Against your quotation for {q(pl.qty, pl.uom)} of {pl.text} for our {site} project, we need the material at site by {long_date(pl.needed_by)}.",
                 "Kindly confirm your earliest dispatch for the full quantity, and the quantity you can dispatch ahead of that date, so that we can place the order."], False)
    if kind == "stockist_partial":
        pl = d.pr_lines[0]
        return (f"Supply from stock: {pl.text}, {site}", [f"Your quotation under {d.cs.cs}" if d.cs else ""],
                [f"Further to your quotation for {pl.text} for our {site} project, kindly confirm the quantity you hold in stock today and the date you can deliver it to site.",
                 f"We need it at site by {long_date(pl.needed_by)}. The balance will be ordered separately."], False)
    if kind in ("hold_quotes",):
        return (f"Validity of your quotation: {site} enquiry", [], [
            f"The PR lines of our {site} enquiry have been put on hold by the project. Kindly hold your quoted prices and terms for 60 days from the present validity,"
            " so that we can order without a fresh enquiry if the requirement returns."], False)
    if kind == "regret":
        return (f"Enquiry closed: {site}", [], [f"The requirement under our {site} enquiry has been withdrawn by the project, and the enquiry is closed.",
                                                 "We thank you for your quotation and will consider you for future requirements."], False)
    if kind == "reissue_rfq":
        pl = d.pr_lines[0]
        return (f"Enquiry: {pl.text}, {site}", [], [f"We invite your offer for {q(pl.qty, pl.uom)} of {pl.text} for our {site} project, required by {long_date(pl.needed_by)}.",
                                                    "The technical specification will follow with the project's load details."], False)
    if kind == "issue_mfc":
        return (f"Manufacturing clearance: {po.text}, PO No. {po.po}", refs, [
            f"We are pleased to issue the manufacturing clearance (MFC) against the above PO for {q(po.open_qty, po.uom)} of {po.text}, at the PO price and within its validity.",
            "Kindly confirm the manufacturing schedule and the date of the inspection call."], False)
    if kind == "extend_validity":
        return (f"Extension of PO validity: PO No. {po.po}", refs, [
            f"With reference to your letter, the manufacturing clearance for {po.text} depends on the readiness of the {site} site. Kindly extend the validity of the PO price"
            f" beyond {dmy(po.validity_end)} by 90 days, at the same price and terms."], True)
    if kind in ("inspect_hold", "store_at_works"):
        ins = next((x for x in d.deadlines if x.what.startswith("Inspection")), None)
        ready = next((x for x in d.deadlines if "ready" in x.what), None)
        para = [f"We confirm the final inspection of {po.text} on {long_date(ins.date)}." if ins else f"We confirm the final inspection of {po.text}.",
                f"Kindly hold the dispatch after inspection clearance until we confirm the site readiness (plinth planned for {long_date(ready.date)})." if ready else
                "Kindly hold the dispatch after inspection clearance until we confirm the site readiness."]
        if kind == "store_at_works":
            para.append(f"We accept storage at your works at the rate in your letter from the end of the free period; the charge is {inr(float(route.cost.amount), exact=True)} to the planned plinth date." if route.cost else "")
        return (f"Inspection and dispatch: {po.text}, PO No. {po.po}", refs, [p for p in para if p], False)
    if kind == "accept_extension":
        return (f"Extended warranty: {(d.po_lines[0].text if d.po_lines else 'equipment')}, PO No. {d.refs[0].id}", [f"PO No. {d.refs[0].id}", _their_letter(d, msgs) or ""], [
            f"We accept your offer of an extended warranty of 12 months from commissioning for {inr(float(d.at_stake.amount), exact=True)} plus GST, as offered in your letter.",
            "Kindly send the formal offer for our order."], False)
    if kind == "hold_original":
        return (f"Dispatch schedule: PO No. {po.po}", refs, [
            "We note the revised dates in your letter. The site needs the material by the PO dates for the work front planned on them:", *_lines_text(d, revised=True),
            "Kindly hold the PO dates, or dispatch a part of the quantity by them and confirm the quantity and date."], True)
    if kind == "negotiate_firm":
        items = [f.fact.split(":")[0] for f in d.findings][:4]
        return (f"Firm price for long-lead items: {site}", [], [
            f"For our {site} project we plan to order {', '.join(items)}.",
            "Kindly quote a firm price, valid for orders placed within six months, against the price-variation basis of your earlier offers."], False)
    if kind == "buy_ahead":
        mt = q(round(float(d.at_stake.amount) / 2500), "MT") if d.at_stake else ""
        return (f"Orders before the price revision", [_their_letter(d, msgs) or ""], [
            f"With reference to your price revision, we wish to place orders for {mt} of TMT bars (Fe500D) for our projects at the existing rates.",
            f"Kindly confirm that orders acknowledged by {long_date(d.act_by)} will be supplied at the existing rates."], True)
    if kind == "reply_computed":
        comp = next((n for n in d.numbers if n.id.endswith(":computed")), None)
        claimed = next((n for n in d.numbers if n.id.endswith(":claimed")), None)
        f_ours = next((f.fact for f in d.findings if f.key == "ours"), "")
        return (f"Your price variation claim: PO No. {po.po}", refs, [
            f"We have checked your claim of {inr(float(claimed.value.amount), exact=True)} against the PO. The PO's price-variation clause takes {po.pv.base_month if po.pv else ''} as the base month, not the month your claim uses.",
            f"On the PO's base, {f_ours.removeprefix('PO clause: ')}. We will process {inr(float(comp.value.amount), exact=True)} with your invoice for the September lots."], True)
    if kind == "ask_evidence":
        return (f"Your price variation claim: PO No. {po.po}", refs, ["Kindly send the IEEMA circulars for the base month and the current month your claim uses, with the calculation sheet."], True)
    if kind == "extension":
        return (f"Validity of your quotation", [_their_letter(d, msgs) or ""], [f"Kindly extend the validity of your quotation by 30 days from {long_date(d.act_by)}, at the same prices and terms."], False)
    if kind == "negotiate_last":
        last = next((n for n in d.numbers if n.id.endswith(":last")), None)
        return (f"Your quotation: {d.title.split(':')[1].split(' L1')[0].strip() if ':' in d.title else 'material'}, {site}", [_their_letter(d, msgs) or ""], [
            f"Our current order rate for this material at {site} is {inr(float(last.value.amount))} per MT." if last else "Kindly revise your rate.",
            "Kindly revise your rate in line with it, for the same quantity and period."], False)
    if kind == "retender":
        return (f"Enquiry: {site}", [], ["We invite your best offer for the material and quantity in our enquiry, for delivery at site."], False)
    if kind == "vendor_extend":
        if k == "lc":
            return (f"LC opening: PO No. {d.refs[0].id}", [_their_letter(d, msgs) or ""], [
                f"The LC for the above PO is being arranged. Kindly hold the production slot for 15 days beyond {long_date(d.act_by)}."], False)
        g = d.refs[0].id
        return (f"Extension of ABG No. {g}", [_po_ref(d) or ""], [f"ABG No. {g} expires on {long_date(next((x.date for x in d.deadlines if x.what == 'ABG expires'), d.act_by))} while the advance it secures is not recovered.",
                                                                    "Kindly extend it by at least six months and send the amendment from your bank."], False)
    if kind == "firm_dates":
        return ("Firm delivery dates on open POs", refs, ["Your last receipts against our POs arrived after the PO delivery dates. For the open lines below, kindly confirm a firm date for each:",
                                                          *_lines_text(d, revised=True)], True)
    if kind == "ld_reminder":
        return ("Delivery against PO dates", refs, ["The open lines below are due on the PO dates. Kindly note that the PO's liquidated-damages clause applies to delay:", *_lines_text(d, revised=True)], True)
    if kind == "alt_supply":
        return (f"Supply during the closure", [_their_letter(d, msgs) or ""], [
            "With reference to your letter, kindly confirm the quantity you can supply from your other units during the closure, and the rate including the additional lead."], True)
    if kind == "verify_entity":
        return ("Change of name: GST certificate and records", [_their_letter(d, msgs) or ""], [
            "We have noted your letter on the change of name. Before we amend our records and open orders, kindly send the GST registration certificate of the new company and its certificate of incorporation.",
            "We will also confirm the change by phone with your contact on file."], False)
    return (route.label, refs, [route.changes], False)


def internal_ask(kind: str, d, route, *, to) -> tuple[str, list[str]]:
    """(subject, the memo's two or three sentences) for an internal note on route `kind`."""
    site = d.projects[0].label if d.projects else ""
    by = dmy(reply_by(d.act_by).isoformat())
    if kind == "resequence":
        return (f"{site}: re-sequencing the work front", [f"{d.finding}", f"Please let me know by {by} whether the front can be re-sequenced, and from which date."])
    if kind == "ask_projects":
        if d.kind == "fund-mismatch":
            return ("Material requirement for the fund sheet", [d.finding, f"Please confirm the month's requirement for your project by {by}, so the fund sheet can be corrected."])
        return (f"{site}: specification for the PR", [d.finding, f"The vendors cannot quote without it. Please send the specification, or a firm date for it, by {by}."])
    if kind == "escalate_cs":
        return (f"{site}: CS approval pending", [d.finding, f"Please approve or return the CS by {by}."])
    if kind == "close_not_required":
        return (f"{site}: close the PR as not required?", [d.finding, f"Please confirm by {by} whether the PR can be closed."])
    if kind == "cancel_approval":
        n = next((x for x in d.numbers if x.id.endswith(":vendors")), None)
        return (f"{site}: approval for the short-closed PRs", [
            f"{len(d.pr_lines)} PR lines were short-closed on your instruction after the RFQ had gone out; {int(n.value.value) if n else 'several'} vendors had quoted, for an enquiry of {inr(float(d.at_stake.amount))}.",
            f"Please give your approval for the cancellation in writing by {by}, with the reason and who is accountable, so that the closure and the effort spent are on record."])
    if kind == "ask_plinth":
        return (f"{site}: plinth readiness for the transformer", [d.finding, f"Please confirm the plinth-ready date by {by}; storage at the vendor's works is charged after the free period."])
    if kind == "ask_commissioning":
        return (f"{site}: commissioning before the warranty ends", [d.finding, f"Please give a commissioning date before {dmy(d.act_by)}."])
    if kind == "order_now":
        return (f"{site}: order the long-lead PV items now", [d.finding, f"Ordering now stops the monthly increase of about {inr(float(d.at_stake.amount))}. Please approve the release."])
    if kind == "ask_finance":
        return (d.title.split(":")[1].strip() if ":" in d.title else d.title, [d.finding, f"Please confirm by {by} that it will be done in time."])
    if kind == "ask_mis":
        return ("Fund sheet: heads that disagree with the requirement", [d.finding, f"Please correct the heads listed in the case and resend the sheet by {dmy(d.act_by)}."])
    if kind == "stockpile":
        return (f"{site}: stockpile during the supply stop", [d.finding, f"Please let me know by {by} how many days of work the site stockpile covers."])
    if kind == "tell_projects":
        return (f"{site}: expected slowdown", [d.finding, "Supply of the affected materials may be held for the period; we are confirming alternate supply and will update you."])
    if kind == "supply_po_oem":
        return (f"{site}: supply PO from an approved OEM", [d.finding, f"Please approve a supply PO for the cable from an approved OEM, with the contractor retained for laying only."])
    if kind == "reinspect":
        return (f"{site}: re-inspection of the contractor's cable", [d.finding, f"Please arrange a re-test of fresh samples by {by}."])
    return (route.label, [d.finding])
