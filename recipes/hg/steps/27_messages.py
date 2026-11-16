"""Read the SCM shared inbox into messages and the records they name; compute trust before anyone reads.

Defect: the inbox is free text, from vendors on file, from people on the company domain, and from senders that are neither. Two imitate a known
domain: a steel vendor's ("rn" for "m", with a free-mail reply-to, asking for payment to a new bank account) and the company's own ("l" for "i",
"the MD's office" asking for an urgent transfer). One spot offer carries an instruction aimed at automated systems. A thread quotes the older
mail it answers.
Rule: parse headers and body as DATA. The sender is internal when its domain is the company's (matched to the person on file), a vendor when its
domain is a vendor record's (matched to the company), a look-alike when its domain folds to one of those (rn/m, l/i, 0/o), else unknown. PRs,
POs, PO lines ("PO … item 10") and projects are found by pattern only in the newest unquoted text (lines after "-----Original Message-----" or
starting with ">" are recorded as quoted). Trust is computed here, in code, by the shared rules (`app.domain.inbox.trust`): a look-alike sender, a
free-mail reply-to, a change of bank details or an instruction aimed at software blocks a message; anything else noteworthy asks for review.
Consequence if ignored: a forged payment request or a "pre-approved" order reaches a person or an agent as if a vendor or the MD had sent it.
"""
import email
import re
from email import policy
from email.utils import parsedate_to_datetime

import pandas as pd

from app.domain.inbox import trust as trust_rules

PR_RE, PO_RE = re.compile(r"\b(10\d{8})\b"), re.compile(r"\b(45\d{8})\b")
ITEM_RE = re.compile(r"\bitem (\d{1,3})\b", re.I)


def _parse(path):
    msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    part = msg.get_body(preferencelist=("plain",))
    frm = msg["from"].addresses[0] if msg["from"] and msg["from"].addresses else None
    rto = msg["reply-to"].addresses[0].addr_spec if msg["reply-to"] and msg["reply-to"].addresses else None
    to = ", ".join(a.addr_spec for h in ("to", "cc") if msg[h] for a in msg[h].addresses)
    return dict(when=parsedate_to_datetime(msg["date"]), from_name=frm.display_name if frm else None, from_email=frm.addr_spec.lower() if frm else None,
                reply_to=rto, to=to, subject=" ".join(str(msg["subject"] or "").split()), body=part.get_content() if part else "",
                atts=[p.get_filename() for p in msg.iter_attachments() if p.get_filename()])


def _lines(body: str) -> list[tuple[int, str, bool]]:
    """(line number, text, quoted) for every line of the body."""
    out, quoted = [], False
    for n, line in enumerate(body.splitlines(), 1):
        if line.strip().startswith("-----Original Message-----"):
            quoted = True
        out.append((n, line, quoted or line.lstrip().startswith(">")))
    return out


def run(ctx):
    internal = ctx.answers["internal_domain"].lower()
    rec = ctx.t["supplier_records"]
    by_domain = dict(zip(rec.email_domain, rec.identity_id))
    contacts = set(rec.contact_email)
    people = {e.lower(): b for e, b in zip(ctx.t["buyers"].email, ctx.t["buyers"].id) if e}
    people.update({str(e).lower(): c for e, c in zip(ctx.t["contacts"].email, ctx.t["contacts"].id) if e})
    projects = ctx.t["projects"]
    names = sorted(((n, i) for n, i in zip(projects.name, projects.id)), key=lambda x: -len(x[0]))
    msgs, refs = [], []
    files = ctx.find(ctx.answers["sources"]["inbox"]["glob"])
    for rel in files:
        m = _parse(ctx.data / rel)
        day = m["when"].date()
        if day > ctx.as_of:
            continue      # not yet received on the data date
        mid = rel.split("/")[-1].rsplit(".", 1)[0]
        addr = m["from_email"] or ""
        dom = addr.split("@")[1] if "@" in addr else ""
        known = set(by_domain) | {internal}
        match, flags = trust_rules.sender_flags(addr, m["reply_to"], known, contacts | set(people))
        imitated = trust_rules.imitated_domain(dom, known) if match in ("lookalike", "near") else None
        if dom == internal:
            cls, contact, ident = "internal", people.get(addr), None
            flags = [f for f in flags if f != "sender_not_contact_on_file"] + ([] if addr in people else ["sender_not_on_file"])
            match = "internal"
        elif imitated and imitated[0] == internal:
            cls, contact, ident = "lookalike_internal", None, None
        elif imitated:
            cls, contact, ident = "lookalike_vendor", None, by_domain.get(imitated[0])
        elif dom in by_domain:
            cls, contact, ident = "vendor", None, by_domain[dom]
        else:
            cls, contact, ident = "unknown", None, None
        lines = _lines(m["body"])
        fresh = "\n".join(t for _, t, q in lines if not q)
        flags += trust_rules.content_flags(m["subject"], fresh)
        flags = list(dict.fromkeys(flags))
        msgs.append(dict(id=mid, file=rel, date=m["when"].isoformat(), kind="eml", from_name=m["from_name"], from_email=addr, from_domain=dom, reply_to=m["reply_to"],
                         to_addrs=m["to"], subject=m["subject"], body=m["body"], identity_id=ident, sender_class=cls, contact=contact, sender_match=match,
                         trust_flags=",".join(flags), trust=trust_rules.verdict(flags), attachments=",".join(m["atts"])))
        for n, text, quoted in [(0, m["subject"], False)] + lines:
            for pr in PR_RE.findall(text):
                refs.append(dict(message_id=mid, ref_type="pr", ref_id=pr, line_ref=f"L{n}", quoted=int(quoted)))
            for po in PO_RE.findall(text):
                items = ITEM_RE.findall(text)
                refs.append(dict(message_id=mid, ref_type="po", ref_id=po, line_ref=f"L{n}", quoted=int(quoted)))
                refs += [dict(message_id=mid, ref_type="po_line", ref_id=f"{po}/{i}", line_ref=f"L{n}", quoted=int(quoted)) for i in items]
            for pl in re.findall(r"PR (10\d{8}) / (\d{1,3})", text):
                refs.append(dict(message_id=mid, ref_type="pr_line", ref_id=f"{pl[0]}/{pl[1]}", line_ref=f"L{n}", quoted=int(quoted)))
            low = text.lower()
            for name, pid in names:
                if re.search(rf"(?<![\w-]){re.escape(name.lower())}(?![\w-])", low):
                    refs.append(dict(message_id=mid, ref_type="project", ref_id=pid, line_ref=f"L{n}", quoted=int(quoted)))
        # a PO line named by its item number on a line of its own under a mail that names one PO ("B-150 masts (320 nos., item 10)")
        pos = {r["ref_id"] for r in refs if r["message_id"] == mid and r["ref_type"] == "po" and not r["quoted"]}
        if len(pos) == 1:
            po = next(iter(pos))
            for n, text, quoted in lines:
                if not quoted and not PO_RE.search(text):
                    refs += [dict(message_id=mid, ref_type="po_line", ref_id=f"{po}/{i}", line_ref=f"L{n}", quoted=0) for i in ITEM_RE.findall(text)]
    cols = ["id", "file", "date", "kind", "from_name", "from_email", "from_domain", "reply_to", "to_addrs", "subject", "body", "identity_id", "sender_class", "contact",
            "sender_match", "trust_flags", "trust", "attachments"]
    df = pd.DataFrame(msgs, columns=cols)
    ctx.t["messages"] = df
    r = pd.DataFrame(refs).drop_duplicates(subset=["message_id", "ref_type", "ref_id", "quoted"]) if refs else pd.DataFrame(columns=["message_id", "ref_type", "ref_id", "line_ref", "quoted"])
    r.insert(0, "id", range(1, len(r) + 1))
    ctx.t["message_refs"] = r
    held = df[df.trust == "blocked"]
    ctx.issue("inbox.held", "inbox", "Messages held before anyone read them (look-alike sender, free-mail reply-to, bank change, text aimed at software)", len(held), "flag",
              "Held: no model reads them and nothing can be drafted from them; each failed check is stated in plain words.",
              "A forged payment request or a 'pre-approved' order reaches a person or an agent as genuine.",
              "; ".join(f"{x.from_email}: {x.trust_flags}" for x in held.head(3).itertuples()), "Satish")
    unknown = df[df.sender_class == "unknown"]
    ctx.issue("inbox.unknown_senders", "inbox", "Messages from senders in neither the vendor master nor the company", len(unknown), "flag",
              "Marked as from a sender not on file; trust decides whether anything may follow.", "A stranger's quote reads like a vendor's.",
              "; ".join(unknown.from_email.head(3)), "Satish")
