"""Read the purchasing inbox into messages, references and what each message changes; compute trust before anyone reads.

Defect: the inbox is free text: 13 emails and 2 pasted notes, with threads where a newer message corrects an older one
(Ruilian's 09-19 schedule supersedes the 09-16 one quoted below it), dates that exist only in prose (a quote valid
"60 days", a closure from October 1), senders that are not in the supplier master (Vinh Phuc), one that imitates a
supplier (yunzhan-rnotor.example: "rn" for "m", a freemail Reply-To, a bank change), and one that carries an
instruction aimed at AI systems (Saltmarsh, a supplier the ERP holds).
Rule: parse headers and the body as DATA; match the sender to a supplier by contact domain (or by name for a pasted note);
extract PO lines, parts and dates by pattern, never by a model, and only from the newest unquoted text (quoted lines are
recorded as quoted references). Trust is computed here, in code, by `app.domain.inbox.trust` (general rules: nothing in it
names a supplier, an amount or a part; the sender is compared with the vendor master and the words with vocabularies of intent):
blocked = a look-alike sender, a free-mail reply-to, a change of bank details, or an instruction aimed at software; review = any
other flag (urgency, sender not in the master, supplier on hold, advance payment, a price far above history, set in step 22).
Consequence if ignored: a fabricated remittance change or a 'pre-approved' purchase order reaches a person or an agent as
if it were a supplier's word, and a superseded ship date is shown as current.
"""
import email
import re
from datetime import date, timedelta
from email import policy
from email.utils import parsedate_to_datetime

import pandas as pd

from app.domain.imports.context import examples
from app.domain.inbox import trust as trust_rules

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
PO_RE = PART_RE = LINE_RE = None      # built from the recipe's id shapes in run()


def _short_date(text, year):
    """'Oct 1' or 'September 28' in `year` -> date, or None."""
    m = re.match(r"([A-Z][a-z]+) (\d{1,2})$", text.strip())
    month = next((v for k, v in MONTHS.items() if m and k.startswith(m.group(1).lower()[:3])), None)
    try:
        return date(year, month, int(m.group(2))) if m and month else None
    except ValueError:
        return None


def _text_date(s):
    """'October 15, 2026' or '15 September 2026' -> date."""
    m = re.search(r"\b([A-Z][a-z]+) (\d{1,2}),? (\d{4})\b", s)
    if m and m.group(1).lower() in MONTHS:
        return date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
    m = re.search(r"\b(\d{1,2}) ([A-Z][a-z]+),? (\d{4})\b", s)
    if m and m.group(2).lower() in MONTHS:
        return date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))


def _parse(path):
    raw = path.read_bytes()
    if path.suffix == ".eml":
        msg = email.message_from_bytes(raw, policy=policy.default)
        body_part = msg.get_body(preferencelist=("plain",))
        body = body_part.get_content() if body_part else ""
        atts = [p.get_filename() for p in msg.iter_attachments() if p.get_filename()]
        subject = " ".join(str(msg["subject"] or "").split())
        d = parsedate_to_datetime(msg["date"]).date() if msg["date"] else None
        frm = msg["from"]
        addr = frm.addresses[0] if frm and frm.addresses else None
        rto = msg["reply-to"].addresses[0].addr_spec if msg["reply-to"] and msg["reply-to"].addresses else None
        to = ", ".join(a.addr_spec for h in ("to", "cc") if msg[h] for a in msg[h].addresses)
        return dict(kind="eml", from_name=addr.display_name if addr else None, from_email=addr.addr_spec if addr else None,
                    reply_to=rto, to=to, subject=subject, body=body, atts=atts, date=d)
    text = raw.decode("utf-8")
    head = "\n".join(text.splitlines()[:15])   # a pasted note: its header lines may follow a title
    hdr = dict(re.findall(r"^(From|To|Subject|Sent|Date):\s*(.+)$", head, re.M))
    m = re.match(r"(?s)(.*?)<([^>]+)>", hdr.get("From", ""))
    return dict(kind="txt", from_name=(m.group(1).strip() if m else None),
                from_email=(m.group(2) if m else (re.search(r"[\w.]+@[\w.]+", hdr.get("From", "")) or [None])[0]),
                reply_to=None, to=hdr.get("To"), subject=hdr.get("Subject") or "", body=text, atts=[], date=None)


def run(ctx):
    global PO_RE, PART_RE, LINE_RE
    shapes = ctx.answers["id_shapes"]      # what a part number and a PO look like in this customer's mails
    PO_RE, PART_RE = re.compile(rf"\b({shapes['po_number']})\b"), re.compile(rf"\b{shapes['part']}\b")
    LINE_RE = re.compile(rf"^line (\d+)\s+({shapes['part']})\s+(.*)$")
    rec = ctx.t["supplier_records"]
    parts = ctx.t["parts"]
    po = ctx.t["po_lines"].set_index("id")
    domains = {r.email_domain: r.identity_id for r in rec.itertuples()}
    contacts = {r.contact_email.lower(): r.record_id for r in rec.itertuples() if r.contact_email}
    status = rec.groupby("identity_id").status.agg(lambda s: "Active" if (s == "Active").any() else s.iloc[0])
    names = rec.groupby("identity_id").name.apply(list).to_dict()
    msgs, refs, events = [], [], []

    def add_event(mid, kind, detail, *, ref=None, d_from=None, d_to=None, line_ref=None, method="extracted", qty=None):
        events.append(dict(message_id=mid, kind=kind, qty=qty, ref_type=ref[0] if ref else None, ref_id=ref[1] if ref else None,
                           date_from=d_from, date_to=d_to, detail=detail, line_ref=line_ref, method=method))

    files = sorted(p for p in (ctx.data / "quotes").iterdir() if p.suffix in (".eml", ".txt"))
    for path in files:
        p = _parse(path)
        mid = path.stem
        fdate = date.fromisoformat(path.name[:10])
        mdate = p["date"] or fdate
        if mdate > ctx.as_of:   # sent after the data date: not in the inbox yet
            continue
        body = p["body"]
        lines = body.splitlines()
        quoted_at = next((i for i, l in enumerate(lines) if re.match(r"^On .+ wrote:\s*$", l)), len(lines))
        dom = p["from_email"].split("@")[1].lower() if p["from_email"] else None
        ident, match = None, "unknown_sender"
        flags = []
        if dom:
            match, flags = trust_rules.sender_flags(p["from_email"], p["reply_to"], set(domains), set(contacts))
            if match in ("record", "domain"):
                ident = domains[dom]
        else:  # a pasted note: find the supplier by the distinctive words of its name
            low = re.sub(r"[^a-z]", "", body.lower())
            hits = {i: sum(1 for t in {w.strip('.,()&').lower() for n in ns for w in n.split()} if len(t) >= 5 and t in low)
                    for i, ns in names.items()}
            best = max(hits.values())
            top = [i for i, h in hits.items() if h == best]
            if best and len(top) == 1:
                ident, match = top[0], "domain"
        flags += trust_rules.content_flags(p["subject"], body)
        if ident and status.get(ident) in ("On hold", "Inactive"):
            flags.append("supplier_on_hold")
        trust = trust_rules.verdict(flags)
        msgs.append(dict(id=mid, file=path.name, date=mdate.isoformat(), kind=p["kind"], from_name=p["from_name"],
                         from_email=p["from_email"], from_domain=dom, reply_to=p["reply_to"], to_addrs=p["to"],
                         subject=p["subject"], body=body, identity_id=ident, sender_match=match,
                         trust_flags=",".join(flags) or None, trust=trust, attachments=",".join(p["atts"]) or None))

        # references: every PO, PO line and part named, with the line it sits on; quoted text marked
        seen = set()
        for i, l in enumerate(lines, 1):
            q = int(i > quoted_at or l.startswith(">"))
            for m in PO_RE.finditer(l):
                if (("po", m.group(1)), q) not in seen:
                    seen.add((("po", m.group(1)), q))
                    refs.append(dict(message_id=mid, ref_type="po", ref_id=m.group(1), line_ref=f"L{i}", quoted=q))
            for m in PART_RE.finditer(l):
                if (("part", m.group(0)), q) not in seen:
                    seen.add((("part", m.group(0)), q))
                    refs.append(dict(message_id=mid, ref_type="part", ref_id=m.group(0), line_ref=f"L{i}", quoted=q))
        mpn_parts = []
        for r in parts.dropna(subset=["mpn"]).itertuples():
            if len(r.mpn) >= 8 and r.mpn in body:
                refs.append(dict(message_id=mid, ref_type="part", ref_id=r.part_number, line_ref=f"mpn {r.mpn}", quoted=0))
                mpn_parts.append(r.part_number)

        # what the message changes
        subj = p["subject"].lower()
        tab = re.compile(r"^(HPO-\d{2}-\d{5})\s+(\d+)\s+(\S+)\s+(?:(\d[\d,]*)\s+)?(?:(\d{4}-\d{2}-\d{2})\s+)?(\d{4}-\d{2}-\d{2})\s*$")
        for i, l in enumerate(lines, 1):
            m = tab.match(l.strip()) if i <= quoted_at else None
            if not m:
                continue
            pono, ln, what, qty, d_old, d_new = m.groups()
            lid = f"{pono}/{int(ln)}"
            if "force majeure" in subj:
                add_event(mid, "force_majeure", f"{what} open qty {qty}, confirmed {d_new}: supplier cannot deliver (force majeure)", ref=("po_line", lid), d_from=d_new, line_ref=f"L{i}")
            else:
                old = d_old or (po.promised_date.get(lid) if lid in po.index else None)
                add_event(mid, "promise_revision", f"{what}{' qty ' + qty if qty else ''}: promise {old or '?'} -> {d_new}", ref=("po_line", lid), d_from=old, d_to=d_new, line_ref=f"L{i}", qty=float(qty.replace(",", "")) if qty else None)
        for i, l in enumerate(lines, 1):
            if i > quoted_at or l.startswith(">"):
                continue
            m = LINE_RE.match(l.strip())
            po_in = PO_RE.search(p["subject"] + " " + body)
            if m and po_in:
                lid = f"{po_in.group(1)}/{int(m.group(1))}"
                for q, mm, dd in re.findall(r"(\d+) pcs\s+ship (\d{2})/(\d{2})", l):
                    ship = date(mdate.year, int(mm), int(dd))
                    arrive = ship + timedelta(days=21)  # ship dates are ex-works Wuxi; the ocean leg to Long Beach is about 21 days
                    add_event(mid, "promise_revision", f"{m.group(2)}: {q} pcs ship {ship.isoformat()} ex-works Wuxi, arriving about {arrive.isoformat()} (21 days by sea)",
                              ref=("po_line", lid), d_from=po.promised_date.get(lid) if lid in po.index else None, d_to=arrive.isoformat(), line_ref=f"L{i}", qty=float(q))
        fam = {m.group(1): (m.group(2).strip(), m.group(3).strip()) for l in lines
               for m in [re.search(r"\b(JP[AD]\d+)\b[^\n]*?manufactured in ([^,]+), ([A-Za-z ]+)\s*$", l)] if m}
        for i, l in enumerate(lines, 1):
            m = tab.match(l.strip()) if i <= quoted_at else None
            if m and fam:
                model = m.group(3)
                key = next((k for k in fam if model.startswith(k)), None)
                if key:
                    city, country = fam[key]
                    add_event(mid, "origin_claim", f"{model} ({key} series) is manufactured in {city}, {country} (the notice)", ref=("po_line", f"{m.group(1)}/{int(m.group(2))}"), line_ref=f"L{i}")
        if "force majeure" in subj:
            m = re.search(r"no later than (\d{1,2} [A-Z][a-z]+ \d{4})", body)
            if m:
                add_event(mid, "deadline", "supplier promises revised delivery dates by this date", d_to=_text_date(m.group(1)).isoformat(),
                          ref=("supplier", ident or ""), line_ref="revised dates")
            from datetime import timedelta
            say = next(((i, l.strip()) for i, l in enumerate(lines, 1) if re.search(r"resume in \d+ to \d+ weeks", l)), None)
            words = re.search(r"resume in (\d+ to \d+ weeks)", say[1]).group(1) if say else None
            flat = " ".join(body.split())
            fire_on = re.search(r"on (\d{1,2} [A-Z][a-z]+ \d{4}) an? (fire|flood|earthquake|explosion|outage)", flat)
            what, fire_date = (fire_on.group(2), _text_date(fire_on.group(1))) if fire_on else ("incident", None)
            newsite = re.search(r"new facility in ([A-Z][\w ]+, [A-Z][\w ]+) is scheduled to start production in ([^.]+?)\.", flat)
            add_event(mid, "force_majeure", f"{what} on {fire_date.isoformat() if fire_date else 'an unstated date'}; partial production resumes in {words or 'an unstated time'} (the supplier's words; counted from the notice, by "
                      + (mdate + timedelta(weeks=8)).isoformat() + " at the latest)" + (f"; new facility in {newsite.group(1)} scheduled to start production in {newsite.group(2)}" if newsite else ""),
                      ref=("supplier", ident or ""), d_from=fire_date.isoformat() if fire_date else None, d_to=(mdate + timedelta(weeks=8)).isoformat(), method="extracted", line_ref=f"L{say[0]}" if say else None)
        # a closure and the dates around it, read from the words of any supplier's message: "closed/close ... from Oct 1 to Oct 7", "last shipment ... will leave on
        # September 28", "orders scheduled to ship during the closure will ship on October 12", and an old address that "will forward until December 31, 2026"
        flat_all = " ".join(body.split())
        short_date = lambda t, y=None: _short_date(t, y or mdate.year)   # noqa: E731
        m = re.search(r"clos(?:e|ed|ure)\b[^.]*?\bfrom\s+([A-Z][a-z]+ \d{1,2})(?:,? (\d{4}))? to ([A-Z][a-z]+ \d{1,2})(?:,? (\d{4}))?", flat_all)
        if m and (c_from := short_date(m.group(1), m.group(2) and int(m.group(2)))) and (c_to := short_date(m.group(3), (m.group(4) and int(m.group(4))) or c_from.year)):
            last = re.search(r"[Ll]ast shipment before [^.]*?\bleave on ([A-Z][a-z]+ \d{1,2})", flat_all)
            held = re.search(r"scheduled to ship during the closure will ship on ([A-Z][a-z]+ \d{1,2})", flat_all)
            last_d, held_d = (short_date(last.group(1), c_to.year) if last else None), (short_date(held.group(1), c_to.year) if held else None)
            add_event(mid, "closure", f"factory closed {c_from} to {c_to}" + (f"; last shipment before it {last_d:%b} {last_d.day}" if last_d else "")
                      + (f"; shipments scheduled in the closure ship {held_d:%b} {held_d.day}" if held_d else ""), ref=("supplier", ident or ""), d_from=c_from.isoformat(), d_to=c_to.isoformat())
            if last_d:
                add_event(mid, "deadline", "last shipment before the closure leaves on this date", ref=("supplier", ident or ""), d_to=last_d.isoformat(), line_ref="last shipment")
        ren = re.search(r"Legal name:\s*(.+?),?\s*(?:Inc\.?|LLC|Ltd\.?|GmbH|Co\.?)?\s*\(formerly (.+?),?\s*(?:Inc\.?|LLC|Ltd\.?|GmbH|Co\.?)?\)", flat_all)
        if ren and ident:      # a supplier says it has a new legal name: the company is its new name, formerly the old one
            add_event(mid, "rename", f"{ren.group(1).strip()} (formerly {ren.group(2).strip()})", ref=("supplier", ident), line_ref="legal name")
        fwd = re.search(r"([\w.-]+\.[a-z]+) addresses will forward until ([A-Z][a-z]+ \d{1,2}, \d{4})", flat_all)
        if fwd and _text_date(fwd.group(2)):
            add_event(mid, "deadline", f"the old {fwd.group(1)} addresses forward only until this date", ref=("supplier", ident or ""), d_to=_text_date(fwd.group(2)).isoformat(), line_ref="address forwarding")
        if "price adjustment" in subj:
            add_event(mid, "price_change", "+8.5% extruded profiles, +4.0% die-cast brackets from 2026-11-01", ref=("supplier", ident or ""), d_from="2026-11-01")
            m = re.search(r"acknowledged by ([A-Z][a-z]+ \d+, \d{4}) for delivery by ([A-Z][a-z]+ \d+, \d{4})", body)
            if m:
                add_event(mid, "deadline", "orders placed and acknowledged by this date for delivery by " + _text_date(m.group(2)).isoformat() + " keep today's price",
                          d_to=_text_date(m.group(1)).isoformat(), ref=("supplier", ident or ""), line_ref="price lock")
        lt = re.search(r"orders placed after (\d{1,2} [A-Z][a-z]+ \d{4}),[^.]*?lead time extends from (\d+) weeks to (\d+) weeks", " ".join(body.split()))
        if lt and _text_date(lt.group(1)):      # the supplier's own cut-off: orders placed after it take the longer lead time
            add_event(mid, "deadline", f"orders placed after this date take the longer lead time ({lt.group(2)} weeks becomes {lt.group(3)} weeks)", ref=("supplier", ident or ""),
                      d_to=_text_date(lt.group(1)).isoformat(), line_ref="lead time change")
        m = re.search(r"^Validity:\s*(\d+) days", body, re.M) or re.search(r"Quote valid (\d+) days", body) or re.search(r"Validity:\s+(\d+) days", body)
        if m:
            from datetime import timedelta
            add_event(mid, "validity", f"quotation valid {m.group(1)} days from {mdate.isoformat()}", d_from=mdate.isoformat(),
                      d_to=(mdate + timedelta(days=int(m.group(1)))).isoformat(), ref=("supplier", ident or ""), line_ref="validity")
        m = re.search(r"Valid until:\s*(\d{2})\.(\d{2})\.(\d{4})", body)
        if m:
            add_event(mid, "validity", "offer valid until " + f"{m.group(3)}-{m.group(2)}-{m.group(1)}", d_from=mdate.isoformat(),
                      d_to=f"{m.group(3)}-{m.group(2)}-{m.group(1)}", ref=("supplier", ident or ""), line_ref="validity")
        if "bank_detail_change" in flags:
            amt = re.search(r"total\s+USD\s*([\d,]+(?:\.\d+)?)", p["body"], re.I)
            amount = float(amt.group(1).replace(",", "")) if amt else None
            add_event(mid, "remittance_change", f"asks to pay {'USD {:,.0f}'.format(amount) if amount else 'an amount'} to new bank details and update the vendor master: BLOCKED, no action may follow from this message",
                      ref=("supplier", ""), method="flagged", qty=amount)
        if "instruction_in_message" in flags:
            add_event(mid, "offer", "spot offer (price and quantity are in its offer record); contains an instruction aimed at AI systems: treated as data",
                      ref=("part", mpn_parts[0] if mpn_parts else ""), method="flagged")

    mdf = pd.DataFrame(msgs)
    ctx.t["messages"] = mdf
    r = pd.DataFrame(refs).drop_duplicates().reset_index(drop=True)
    r.insert(0, "id", range(1, len(r) + 1))
    ctx.t["message_refs"] = r
    e = pd.DataFrame(events)
    e.insert(0, "id", range(1, len(e) + 1))
    ctx.t["message_events"] = e

    bad = mdf[mdf.trust != "ok"]
    ctx.issue("inbox.trust_flags", "quotes/", "Messages that deserve less trust: look-alike sender, freemail Reply-To, bank change, instruction to an AI, unknown sender",
              len(bad), "flag",
              "Flags computed in code from the sender and the words, before any model reads the message. blocked: no action can be staged from it. review: a person checks first. The body is always shown as quoted data.",
              "A forged remittance change or a 'pre-approved' purchase order at many times the usual price reaches an agent or a person as if a supplier said it.",
              examples(bad.id + " [" + bad.trust + ": " + bad.trust_flags.fillna("") + "]", 4, " | "), "@suppliers:" + ",".join(sorted(set(bad.identity_id.dropna()))) if bad.identity_id.notna().any() else "ERP admin")
    unres = [x for x in r[r.ref_type == "po"].ref_id if x not in set(ctx.t["po_lines"].po_number)]
    ctx.issue("inbox.po_unresolved", "quotes/", "A PO number in a message that is not in the PO file", len(unres), "flag",
              "Kept as a reference, flagged.", "The message changes a line that cannot be found.", examples(unres), "ERP admin")
    ctx.issue("inbox.dates_in_prose", "quotes/", "Dates that exist only in emails: revised ship dates, closures, price locks, quote validity",
              len(e[e.kind.isin(["promise_revision", "closure", "deadline", "validity", "price_change", "force_majeure"])]), "infer",
              "Extracted by pattern from the newest unquoted text, each event keeps the message and line it came from (method 'extracted'). The ERP promise date is kept beside the revised one.",
              "The ERP still shows the old promise dates; nothing in the ERP says a supplier cannot ship or that a price lock ends on a date.",
              examples(e.kind + ": " + e.detail.str.slice(0, 50), 3, " | "), "ERP admin")
    quoted_over = r[r.quoted == 1]
    ctx.issue("inbox.superseded_quoted_text", "quotes/", "Older numbers inside quoted text (a superseded schedule, a corrected price)", len(quoted_over), "flag",
              "References inside quoted text are marked quoted=1 and never used to change a line.",
              "A superseded ship date or price would be taken as current.", examples(quoted_over.message_id.unique()), "ERP admin")
