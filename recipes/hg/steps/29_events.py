"""What each message states: dated facts and changes, each with the line it was read from and the records it touches.

Defect: the dates and amounts that decide the cases exist only in prose: an MFC wanted by 25 October against a PO valid to 31 October and a
₹1.4 Cr firm-price claim; an inspection on 28 October with storage at ₹18,000 a day after 15 days; a PV claim worked on the wrong base month; a
price rise from 1 November; a quote valid 30 days; an LC to open by 30 October; an ABG expiring 31 October; quarries closed from 25 October for
30 days; a strike from 22 October; a warranty ending 12 November; delivery dates moved, line by line.
Rule: patterns over the newest unquoted text only, one rule per kind of statement (never per vendor or per message); each fact keeps its message,
its line, the PO line, PO, PR or project it names, and the value as a date or a number. A held message is read for its claim only (the amount it
asks for), never for anything to act on. Each dated fact with an owner also becomes a deadline (who must act by when). Limit: the patterns are
written against this inbox's wording; a new kind of statement needs a new rule, and an unmatched sentence is not a fact.
Consequence if ignored: the dates that decide whether money is lost stay in prose, and no case can be dated or ranked by them.
"""
import json
import re
from datetime import date, datetime, timedelta

import pandas as pd

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
DATE = r"(\d{1,2})(?:st|nd|rd|th)? (January|February|March|April|May|June|July|August|September|October|November|December),? (\d{4})"
AMT = r"Rs\.\s?([\d,]+)"


def _date(m, k: int = 1) -> str:
    return date(int(m.group(k + 2)), MONTHS.index(m.group(k + 1).lower()) + 1, int(m.group(k))).isoformat()


def _amt(s: str) -> float:
    return float(s.replace(",", ""))


def run(ctx):
    msgs, refs = ctx.t["messages"], ctx.t["message_refs"]
    out = []
    owner_of = {}
    for m in msgs.itertuples():
        to = (m.to_addrs or "").split(",")[0].strip().lower()
        owner_of[m.id] = next((b.id for b in ctx.t["buyers"].itertuples() if (b.email or "").lower() == to), None)
    for m in msgs.itertuples():
        mine = refs[(refs.message_id == m.id) & (refs.quoted == 0)]
        pos = sorted(set(mine[mine.ref_type == "po"].ref_id))
        prs = sorted(set(mine[mine.ref_type == "pr"].ref_id))
        projs = sorted(set(mine[mine.ref_type == "project"].ref_id))
        main = ("po", pos[0]) if len(pos) == 1 else ("pr", prs[0]) if len(prs) == 1 else ("project", ",".join(projs)) if projs else (None, None)
        sent = date.fromisoformat(m.date[:10])
        lines, quoted = [], False
        for n, line in enumerate((m.body or "").splitlines(), 1):
            quoted = quoted or line.strip().startswith("-----Original Message-----")
            if not quoted and not line.lstrip().startswith(">"):
                lines.append((n, line))
        held = m.trust == "blocked"

        def add(kind, n, *, df=None, dt=None, qty=None, detail="", ref=None):
            rt, rid = ref if ref else main
            out.append(dict(message_id=m.id, kind=kind, ref_type=rt, ref_id=rid, date_from=df, date_to=dt, qty=qty, detail=detail, line_ref=f"L{n}", method="extracted"))

        for n, line in lines:
            low = line.lower()
            if held:      # a held message: only the amount it asks for, as its claim
                if (x := re.search(r"(?:outstanding amount of|an advance of) " + AMT, line)):
                    add("remittance_change", n, qty=_amt(x.group(1)), detail="asks for a payment to new bank details" if "outstanding" in line else "asks for an urgent transfer to a new account")
                continue
            if (x := re.search(r"MFC\)? by " + DATE, line)):
                add("mfc_needed_by", n, dt=_date(x, 1), detail="the vendor wants the manufacturing clearance by this date to hold its slot")
            if (x := re.search(r"firm only up to the PO validity of " + DATE, line)):
                add("po_validity", n, dt=_date(x, 1), detail="the PO price is firm only up to this date")
            if "price" in low and (x := re.search(r"increase of " + AMT, line)):
                add("price_claim", n, qty=_amt(x.group(1)), detail="the revised price the vendor will charge if the MFC comes after the PO validity")
            if (x := re.search(r"manufacturing period is (\d+) days", low)):
                add("manufacturing_days", n, qty=float(x.group(1)), detail="manufacturing period from MFC")
            if "inspect" in low and (x := re.search(r"on " + DATE, line)):
                add("inspection_call", n, dt=_date(x, 1), detail="the vendor calls for inspection on this date")
            if (x := re.search(r"free storage at our works for (\d+) days", low)):
                add("free_storage_days", n, qty=float(x.group(1)), detail="free storage after inspection clearance")
            if (x := re.search(r"storage charges of " + AMT + r" per day", line)):
                add("storage_rate", n, qty=_amt(x.group(1)), detail="storage charge per day after the free period")
            if (x := re.search(r"PV claimed = .*= " + AMT, line)):
                add("pv_claim", n, qty=_amt(x.group(1)), detail=line.strip())
            if (x := re.search(r"IEEMA [^,]*, base: Rs\. ([\d,]+) per MT \((\w+) (\d{4})\)", line)):
                add("pv_claim_base", n, qty=_amt(x.group(1)), df=f"{x.group(3)}-{MONTHS.index(x.group(2).lower()) + 1:02d}", detail="the base index the claim uses")
            if (x := re.search(r"IEEMA [^,]*, current: Rs\. ([\d,]+) per MT \((\w+) (\d{4})\)", line)):
                add("pv_claim_index", n, qty=_amt(x.group(1)), df=f"{x.group(3)}-{MONTHS.index(x.group(2).lower()) + 1:02d}", detail="the current index the claim uses")
            if (x := re.search(r"claim for ([\d,]+) km", line)):
                add("pv_claim_qty", n, qty=_amt(x.group(1)), detail="the quantity the claim covers")
            if (x := re.search(r"increased by " + AMT + r" per MT with effect from " + DATE, line)):
                add("price_change", n, qty=_amt(x.group(1)), df=_date(x, 2), detail="price rise per MT from this date")
            if (x := re.search(r"acknowledged up to " + DATE, line)):
                add("price_lock", n, dt=_date(x, 1), detail="orders acknowledged by this date keep the existing rate")
            if (x := re.search(r"Validity: (\d+) days from the date of this offer", line)):
                add("quote_validity", n, dt=(sent + timedelta(days=int(x.group(1)))).isoformat(), detail=f"{x.group(1)} days from the offer of {sent.isoformat()}")
            if (x := re.search(r"valid till " + DATE, line)) or (x := re.search(r"price validity [^.]*up to " + DATE, line)):
                add("quote_validity", n, dt=_date(x, 1), detail="quoted prices hold until this date")
            if (x := re.search(r"open the LC for INR (\d+) crore [^.]*latest by " + DATE, line)):
                add("lc_deadline", n, dt=_date(x, 2), qty=float(x.group(1)) * 1e7, detail="the LC must be opened by this date, else the production slot is released")
            if "abg" in low and (x := re.search(r"expires on " + DATE, line)):
                add("guarantee_expiry", n, dt=_date(x, 1), detail="the bank guarantee expires")
            if "warranty" in low and (x := re.search(r"expires on " + DATE, line)):
                add("warranty_end", n, dt=_date(x, 1), detail="the warranty from supply ends")
            if (x := re.search(r"delivered to your \w+ site on " + DATE, line)):
                add("supplied_on", n, dt=_date(x, 1), detail="the equipment was delivered to site")
            if (x := re.search(r"extended warranty [^.]* for " + AMT, line)):
                add("offer", n, qty=_amt(x.group(1)), detail="the vendor's price for an extended warranty")
            if (x := re.search(r"(?:before|by) " + DATE + r"(?:,| so that)", line)) and ("abg" in low or "reconcile" in low or "resend" in low):
                add("deadline", n, dt=_date(x, 1), detail=line.strip()[:160])
            if (x := re.search(r"closed from " + DATE + r" for (\d+) days", line)):
                start = date.fromisoformat(_date(x, 1))
                add("closure", n, df=start.isoformat(), dt=(start + timedelta(days=int(x.group(4)) - 1)).isoformat(), detail=re.sub(r"\s+", " ", line.strip())[:200],
                    ref=("project", ",".join(projs)) if projs else None)
            if (x := re.search(r"strike from " + DATE, line)):
                add("strike", n, df=_date(x, 1), detail="indefinite strike from this date", ref=("project", ",".join(projs)) if projs else None)
            if (x := re.search(r"revised from " + DATE + r" to " + DATE, line)):
                old, new = _date(x, 1), _date(x, 4)
                for qty, item in re.findall(r"\(([\d,]+) nos\., item (\d+)\)", line):
                    add("promise_revision", n, df=old, dt=new, qty=_amt(qty), detail=f"dispatch moved from {old} to {new}", ref=("po_line", f"{pos[0]}/{item}") if pos else None)
            for item, q1, d1, q2, d2 in re.findall(r"\(item (\d+)\): ([\d,]+) nos\. by (\d{1,2} \w+ \d{4})(?: and ([\d,]+) nos\. by (\d{1,2} \w+ \d{4}))?", line):
                for q, dd in ((q1, d1), (q2, d2)):
                    if q:
                        new = datetime.strptime(dd, "%d %B %Y").date().isoformat()
                        add("promise_revision", n, dt=new, qty=_amt(q), detail=f"rescheduled: {q} nos. by {new}", ref=("po_line", f"{pos[0]}/{item}") if pos else None)
            if "awaiting the technical specification" in low:
                add("spec_awaited", n, detail="the vendor cannot quote until Projects sends the specification and load details")
            if (x := re.search(r"RFQ dated " + DATE, line)):
                add("rfq_sent", n, dt=_date(x, 1), detail="the RFQ the vendor answers")
            if (x := re.search(r"required at site by " + DATE, line)):
                add("needed_by", n, dt=_date(x, 1), detail="the site needs the material by this date")
            if (x := re.search(r"short-close the following (\d+) PR line items", line)):
                add("short_close_instruction", n, qty=float(x.group(1)), detail="Projects asks SCM to short-close these PR lines")
            if (x := re.match(r"\s*\d+\. PR (10\d{8}) / (\d+)", line)):
                add("short_close", n, detail="a PR line Projects asks to short-close", ref=("pr_line", f"{x.group(1)}/{x.group(2)}"))
            if re.match(r"\s*Main reasons", line, re.I):
                reasons = [l.strip() for k, l in lines if k > n and re.match(r"\s*\d\.", l)]
                add("reasons", n, detail=" ".join(reasons))
            if "converted into" in low and (x := re.search(r"with effect from " + DATE, line)):
                gst = re.search(r"new GSTIN is (\w{15})", m.body or "")
                add("rename", n, df=_date(x, 1), detail=f"the vendor is a new company from this date; new GSTIN {gst.group(1) if gst else 'not stated'}")
            if (x := re.search(r"Invoices from " + DATE, line)):
                add("rename_invoices_from", n, df=_date(x, 1), detail="invoices only under the new GSTIN from this date")
            if "failed on" in low:
                add("inspection_failed", n, detail=re.sub(r"\s+", " ", line.strip())[:200])
            if "do not agree with" in low:
                add("fund_mismatch_reported", n, detail="Finance reports the fund requirement does not agree with the material requirement",
                    ref=("project", ",".join(projs)) if projs else None)
    ev = pd.DataFrame(out, columns=["message_id", "kind", "ref_type", "ref_id", "date_from", "date_to", "qty", "detail", "line_ref", "method"])
    ev.insert(0, "id", range(1, len(ev) + 1))
    ctx.t["message_events"] = ev
    dated = ev[ev.date_to.notna() & ev.kind.isin(["mfc_needed_by", "po_validity", "inspection_call", "price_lock", "quote_validity", "lc_deadline", "guarantee_expiry",
                                                   "warranty_end", "deadline", "needed_by"])]
    ctx.t["deadlines"] = pd.DataFrame(dict(id=range(1, len(dated) + 1), kind=dated.kind, due_date=dated.date_to, identity_id=dated.message_id.map(dict(zip(msgs.id, msgs.identity_id))),
                                           detail=dated.detail, source_type="message", source_id=dated.message_id, owner=dated.message_id.map(owner_of),
                                           refs_json=[json.dumps([{"type": t, "id": i}] if t else []) for t, i in zip(dated.ref_type, dated.ref_id)]))
    ctx.t["events"] = pd.DataFrame(dict(id=range(1, len(msgs) + 1), kind="message", topic=None, date=msgs.date.str[:10], identity_id=msgs.identity_id, title=msgs.subject,
                                        detail=None, source_type="message", source_id=msgs.id, owner=msgs.id.map(owner_of), refs_json=None))
    by_kind = ev.groupby("kind").size().sort_values(ascending=False)
    ctx.issue("inbox.facts_in_prose", "inbox", "Dates and amounts that exist only in prose", len(ev), "infer",
              "Read by one pattern per kind of statement from the newest unquoted text; each fact keeps its line and the record it names.",
              "The dates that decide whether money is lost stay in prose; no case can be dated or ranked by them.",
              ", ".join(f"{k} {v}" for k, v in by_kind.head(6).items()), "Satish")
