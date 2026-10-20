"""Names before ids: how a buyer says a part, an order line, a supplier or a message, and the label every reference carries.

An id is how the ERP files a thing; a buyer says "the lidar" or "the a lidar maker order". `namify` rewrites the ids in a sentence as
name-first, id-after ("Lidar, 2D safety (PN-12345)"), and `label_for` is the label an `EntityRef` carries so a screen can show the name
and keep the id one click away. Nothing here knows a customer: every name comes from the item master, the order lines and the suppliers.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.cache import memo
from app.domain.common import EntityRef
from app.domain.inbox.model import Message
from app.domain.orders.model import PoLine
from app.domain.parts.model import Part
from app.domain.suppliers.model import SupplierRecord
from app.domain.tariffs.model import TariffRule

# Any run of letters, digits, dots, dashes and slashes; a token is renamed only if it is an id the database knows, so no id format is assumed.
_TOKEN = re.compile(r"(?<![\w(:])[A-Za-z0-9][\w./-]*[A-Za-z0-9](?![\w)])")


def part_name(description: str | None) -> str:
    """'Battery pack, 48 V 30 Ah LFP, integrated BMS, Alpha' -> 'Battery pack, 48 V 30 Ah LFP': the first two clauses, at most 48 characters."""
    clauses = [c.strip() for c in (description or "").split(",") if c.strip()]
    name = ", ".join(clauses[:2])
    if name.isupper():          # the ERP sometimes types a description in capitals; an acronym or a size (BLDC, DC, 2D) keeps them
        name = " ".join(w if any(c.isdigit() for c in w) or not any(c in "AEIOUY" for c in w) else w.lower() for w in name.split(" "))
        name = name[:1].upper() + name[1:]
    return name if len(name) <= 48 else name[:47].rstrip(" ,") + "…"


@memo
def _renames(session: Session) -> dict[str, str]:
    """{supplier id: 'New Name (formerly Old)'} for a company that wrote to say it has a new legal name; the old name is its first word, as a buyer says it."""
    from app.domain.inbox.model import MessageEvent

    out = {}
    for e in session.scalars(select(MessageEvent).where(MessageEvent.kind == "rename", MessageEvent.ref_type == "supplier")):
        new, _, old = (e.detail or "").partition(" (formerly ")
        if new and old:
            out[e.ref_id] = f"{new} (formerly {old.rstrip(')').split()[0]})"
    return out


def supplier_name(session: Session, supplier_id: str) -> str:
    """'Acme', 'Acme Extrusion': the name a buyer says. The domain's first word when it is part of the name, else the name's first two words."""
    r = session.get(SupplierRecord, supplier_id)
    if r is None:
        return supplier_id
    if r.identity_id in _renames(session):
        return _renames(session)[r.identity_id]
    label = (r.email_domain or "").split(".")[0].split("-")[0]
    if label and label in r.name.lower().replace(",", " ").split() or (label and label in r.name.lower()):
        return label.capitalize()
    return firm_name(r.name)


def firm_name(name: str) -> str:
    """A legal name a buyer shortens to its first two words, for a firm with no record yet (a quote from a new source)."""
    return " ".join(name.replace(",", " ").split()[:2])


@memo
def _books(session: Session) -> dict:
    parts = {p.part_number: part_name(p.description) for p in session.scalars(select(Part))}
    lines = {l.id: (l.po_number, l.line, l.part_number) for l in session.scalars(select(PoLine))}
    suppliers = {r.record_id: supplier_name(session, r.record_id) for r in session.scalars(select(SupplierRecord))}
    messages = {m.id: m.subject for m in session.scalars(select(Message))}
    rules = {str(r.id): r.description for r in session.scalars(select(TariffRule))}
    return dict(parts=parts, lines=lines, suppliers=suppliers, messages=messages, rules=rules)


def _line_phrase(b: dict, line_id: str) -> str | None:
    hit = b["lines"].get(line_id)
    if not hit:
        return None
    po, line, part = hit
    return f"{b['parts'].get(part, part)} order ({po} line {line})"


def label_for(session: Session, r: EntityRef) -> str | None:
    """The name a reference shows: a part by its description, an order line by its part and PO, a supplier, a message by its subject."""
    b = _books(session)
    if r.type == "part":
        return b["parts"].get(r.id)
    if r.type == "po_line":
        return _line_phrase(b, r.id)
    if r.type in ("supplier", "supplier_record"):
        return b["suppliers"].get(r.id)
    if r.type == "message":
        return b["messages"].get(r.id)
    if r.type == "tariff_rule":
        return b["rules"].get(r.id)
    return None


def labelled(session: Session, refs: list[EntityRef]) -> list[EntityRef]:
    """The same references, each with the name it shows (a label already given is kept)."""
    return [r if r.label else r.model_copy(update={"label": label_for(session, r)}) for r in refs]


def namify(session: Session, text: str | None) -> str:
    """Rewrite the ids in a sentence name-first: 'PN-12345' -> 'Lidar, 2D safety (PN-12345)'; an order line -> 'Lidar, 2D safety order (ORD-26-00450/10 line 10)'.
    An id already in brackets, or already after its name, is left as it is."""
    if not text:
        return text or ""
    b = _books(session)

    def named(m: re.Match, name: str) -> bool:
        return text[:m.start()].rstrip().lower().endswith(name.lower())      # "Acme Extrusion XX-0001": the name is already there

    def one(m: re.Match) -> str:
        ident = m.group(0)
        if ident in b["lines"]:
            return _line_phrase(b, ident)
        for book in ("parts", "suppliers"):
            name = b[book].get(ident)
            if name:
                return f"({ident})" if named(m, name) else f"{name} ({ident})"
        return ident

    return _TOKEN.sub(one, text)
