"""Search across the whole workspace: action items, messages, suppliers, parts, PO lines and people. Deterministic; no model.

Every word of the query must be found; the best field decides the rank (an exact number or name over a start, over a whole word, over a fragment). The query is also read by
`annotate`, so "Acme Motor", "PN-12345", "PO 450/10" and "Jo Smith" resolve to the record they mean before any text is compared."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import naming
from app.domain.annotate import service as annotate
from app.domain.attention import service as attention
from app.domain.bom.service import where_used
from app.domain.cache import memo
from app.domain.demand.model import Product
from app.domain.inbox import service as inbox
from app.domain.inbox.service import FIELD_WEIGHT
from app.domain.inbox import trust
from app.domain.inbox.model import Message
from app.domain.quotes.model import Offer
from app.domain.orders.model import PoLine
from app.domain.parts.model import Buyer, Part
from app.domain.search.schema import Highlight, Hit
from app.domain.suppliers.model import SupplierIdentity, SupplierRecord

TYPES = ("item", "message", "supplier", "part", "po_line", "person")
PRIORITY = {"supplier": 0, "part": 1, "po_line": 2, "person": 3, "item": 4, "message": 5}


@dataclass
class Entry:
    type: str
    ref: str
    label: str
    sublabel: str
    url: str
    fields: list[tuple[str, int]] = field(default_factory=list)      # (text, weight): the primary names weigh most


def _u16(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


HELD_WORDS = inbox.HELD_WORDS


@memo
def _message_entities(session: Session) -> dict[str, list]:
    """{message id: the spans its subject and body mention}, matched against the records (a held message's names are claims and carry no record)."""
    out = {}
    for m in session.scalars(select(Message)):
        held = m.trust == "blocked" or bool(set((m.trust_flags or "").split(",")) & trust.BLOCK)
        out[m.id] = [(m.body or "", s) for s in annotate.annotate(session, m.body, held=held)]
    return out


@memo
def _all_items(session: Session) -> list:
    """Every row of the Action list and every part, order or quote rolled up into one: each is reachable by its key, so a search finds them too."""
    return [i for k in attention.all_keys(session) if (c := attention.item_context(session, k))[0] and (i := c[0])]


@memo
def _item_refs_text(session: Session) -> dict[str, str]:
    """{item key: what it refers to, as words}: the PO lines (also 'PO 450/10' and '450/10'), the parts, the suppliers (names, former names, domains) and the places its suppliers' offers build in."""
    sup_text: dict[str, str] = {}
    for r in session.scalars(select(SupplierRecord)):
        sup_text[r.identity_id] = sup_text.get(r.identity_id, "") + f" {r.name} {r.email_domain or ''}"
    sites: dict[str, str] = {}
    for o in session.scalars(select(Offer)):
        sites[o.identity_id] = sites.get(o.identity_id, "") + f" {o.origin_claim or ''}"
    out = {}
    shown = {i.key for i in attention.what_needs_attention(session)}
    for it in _all_items(session):
        words = []
        for r in it.refs:
            if r.type == "po_line":
                m = re.match(r".*-0*(\d+)/(\d+)$", r.id)
                words += [r.id] + ([f"PO {m.group(1)}/{m.group(2)}", f"{m.group(1)}/{m.group(2)}"] if m else [])
            elif r.type in ("part", "supplier", "product"):
                words += [r.id, r.label or ""]
                if r.type == "supplier":
                    words += [naming.supplier_name(session, r.id), sup_text.get(r.id, ""), sites.get(r.id, "")]
        d = attention.item_detail(session, it.key) if it.key in shown else None      # the PO lines behind a row (the fire's ten) are in its detail, not its refs
        for l in (d.po_lines if d else []):
            m = re.match(r".*-0*(\d+)/(\d+)$", l.ref.id)
            words += [l.ref.id] + ([f"PO {m.group(1)}/{m.group(2)}", f"{m.group(1)}/{m.group(2)}"] if m else [])
        out[it.key] = " ".join(w for w in words if w)
    return out


@memo
def _index(session: Session) -> list[Entry]:
    out: list[Entry] = []
    fam = {p.part_number: p.family for p in session.scalars(select(Product))}
    sup_name = {i.id: naming.supplier_name(session, i.id) for i in session.scalars(select(SupplierIdentity))}
    recs: dict[str, list[SupplierRecord]] = {}
    for r in session.scalars(select(SupplierRecord)):
        recs.setdefault(r.identity_id, []).append(r)
    for i in session.scalars(select(SupplierIdentity)):
        rs = recs.get(i.id, [])
        canon = next((r for r in rs if r.record_id == i.id), rs[0] if rs else None)
        out.append(Entry("supplier", i.id, sup_name[i.id], f"{i.name}" + (f" · {canon.country}" if canon and canon.country else ""), f"/suppliers/{i.id}",
                         [(i.name, 5), (sup_name[i.id], 5), (i.id, 5)] + [(r.name, 4) for r in rs if r.name != i.name] + [(r.email_domain, 3) for r in rs if r.email_domain] + [(r.contact_name, 3) for r in rs if r.contact_name]))
        for r in {r.contact_name: r for r in rs if r.contact_name}.values():      # a contact on two vendor records of one company is one person
            if r.contact_name:
                out.append(Entry("person", f"{i.id}/{r.contact_name}", r.contact_name, f"contact at {sup_name[i.id]}", f"/suppliers/{i.id}", [(r.contact_name, 5), (r.contact_email or "", 3)]))
    for b in session.scalars(select(Buyer)):
        out.append(Entry("person", b.id, b.name, "buyer", f"/?owner={b.id}", [(b.name, 5), (b.id, 5), (b.initials or "", 2)]))
    for p in session.scalars(select(Part)):
        made = sorted({fam.get(w.product.id, w.product.id) for w in where_used(session, p.part_number)})
        name = naming.part_name(p.description)
        out.append(Entry("part", p.part_number, f"{name} ({p.part_number})", " · ".join(x for x in (", ".join(made), p.category) if x), f"/parts/{p.part_number}",
                         [(p.part_number, 5), (p.description or "", 4), (name, 4), (p.category or "", 2)]))
    for l in session.scalars(select(PoLine)):
        m = re.match(r".*-0*(\d+)/(\d+)$", l.id)
        short = [f"PO {m.group(1)}/{m.group(2)}", f"{m.group(1)}/{m.group(2)}"] if m else []
        who = sup_name.get(l.identity_id, "")
        out.append(Entry("po_line", l.id, l.id, " · ".join(x for x in (who, l.part_number, (l.status or "").lower()) if x), f"/orders?line={l.id}",
                         [(l.id, 5)] + [(x, 5) for x in short] + [(l.part_number, 3), (who, 2)]))
    return out


def _best(entry_fields: list[tuple[str, int]], words: list[str]):
    """(score, text, start, end) for the best field of an entry, or None when some word is found nowhere."""
    total, shown = 0, None
    for w in words:
        best = None
        for text, weight in entry_fields:
            low = (text or "").lower()
            k = low.find(w)
            if k < 0:
                continue
            bonus = (10 if low == w else 4 if k == 0 else 2 if re.search(rf"(?<![\w]){re.escape(w)}(?![\w])", low) else 0) if weight >= 3 else 0      # only a primary field earns a bonus
            if best is None or weight + bonus > best[0]:
                best = (weight + bonus, text, k, k + len(w))
        if best is None:
            return None
        total += best[0]
        if shown is None or best[0] > shown[0]:
            shown = best
    return total, shown[1], shown[2], shown[3]


def search(session: Session, q: str | None, types: list[str] | None = None, limit: int = 30) -> list[Hit]:
    words = [w for w in (q or "").lower().split() if w]
    if not words:
        return []
    want = [t for t in (types or TYPES) if t in TYPES]
    resolved = {(("person" if s.type == "person" else s.type), s.ref) for s in annotate.annotate(session, q) if s.type in ("supplier", "part", "po_line", "person")}
    hits: list[tuple[int, int, Hit]] = []
    for e in _index(session):
        if e.type not in want:
            continue
        r = _best(e.fields, words)
        boost = 100 if (e.type, e.ref) in resolved else 0
        if r is None and not boost:
            continue
        score, text, a, b = r if r else (0, e.label, 0, 0)
        hits.append((score + boost, PRIORITY[e.type], Hit(type=e.type, ref=e.ref, label=e.label, sublabel=e.sublabel, matched_text=text, url=e.url, score=score + boost,
                                                           highlight=Highlight(start=_u16(text[:a]), end=_u16(text[:b])))))
    if "message" in want:
        for m in inbox.search_messages(session, q):
            top = m.matches[0] if m.matches else None
            weight = 2 * (FIELD_WEIGHT[top.field] if top else 1)      # a message ranks by where it matched: the subject over the body
            hits.append((weight, PRIORITY["message"], Hit(type="message", ref=m.ref.id, label=m.ref.label or m.ref.id, sublabel=f"{m.date[:10]} · {m.from_}", url=f"/inbox/{m.ref.id}",
                                                                         matched_text=top.snippet if top else m.summary, highlight=Highlight(start=top.start if top else 0, end=top.end if top else 0), score=weight)))
    if "message" in want:      # a message also matches the records its text mentions: a supplier's name finds what names it under any of its names
        seen_ids = {h.ref for _, _, h in hits if h.type == "message"}
        for mid, spans in _message_entities(session).items():
            if mid in seen_ids:
                continue
            for body, sp in spans:
                if (sp.type in ("supplier", "part", "po_line", "person") and (sp.type, sp.ref) in resolved) or (sp.type == "supplier" and all(w in sp.text.lower() for w in words)):
                    m = session.get(Message, mid)
                    a = max(0, sp.start - 40)
                    shown = body[a:sp.end + 40].replace("\n", " ")
                    k = shown.lower().find(sp.text.lower())
                    hits.append((6, PRIORITY["message"], Hit(type="message", ref=mid, label=m.subject, sublabel=f"{m.date[:10]} · {m.from_name or m.from_email or ''}", url=f"/inbox/{mid}", matched_text=shown,
                                                          highlight=Highlight(start=_u16(shown[:k]), end=_u16(shown[:k + len(sp.text)])), score=6)))
                    break
    exposure: dict[str, float] = {}
    if "item" in want:
        for it in _all_items(session):
            exposure[it.key] = float(it.at_stake.usd) if it.at_stake is not None and getattr(it.at_stake, "usd", None) is not None else 0.0
            tags = HELD_WORDS if it.group == "trust" else ""
            r = _best([(it.title, 5), (it.key, 5), (it.next_action, 2), (it.owner, 3), (it.at_stake_note or "", 2), (_item_refs_text(session).get(it.key, ""), 3), (tags, 3)], words)
            if r:
                score = max(1, r[0] // 2)      # a row ranks below the record a name or number resolves to
                hits.append((score, PRIORITY["item"], Hit(type="item", ref=it.key, label=it.title, sublabel=f"{it.owner} · {it.group}", url=f"/items/{it.key}", matched_text=r[1],
                                                          highlight=Highlight(start=_u16(r[1][:r[2]]), end=_u16(r[1][:r[3]])), score=score)))
    # Open before closed, and the bigger case first, before any cap (LOOKOUT #56, #59): a closed 2025 line never hides an open one.
    closed = lambda h: h.type == "po_line" and (h.sublabel or "").endswith("closed")
    hits.sort(key=lambda t: (closed(t[2]), -t[0], t[1], -exposure.get(t[2].ref, 0.0) if t[2].type == "item" else 0.0, t[2].label))
    per_type = limit if len(want) == 1 else max(3, limit // 4)      # across types, no one kind of record (2,616 PO lines) fills the list
    seen: dict[str, int] = {}
    out = []
    for _, _, h in hits:
        if seen.get(h.type, 0) < per_type:
            seen[h.type] = seen.get(h.type, 0) + 1
            out.append(h)
    return out[:limit]
