"""Small constructors for the value objects, so every service builds Money, Quantity and Unknown the same way."""

from __future__ import annotations

from decimal import Decimal

from app.domain.common import EntityRef, Money, Provenance, Quantity, Unknown


def prov(method: str, source: str, *, row: str | None = None, raw: str | None = None,
         inputs: list[EntityRef] | None = None, rule: str | None = None, by: str = "recipe") -> Provenance:
    return Provenance(method=method, source=source, row=row, raw=raw, inputs=inputs or [], rule=rule, by=by)


def usd(amount: float | Decimal, provenance: Provenance, places: int = 2) -> Money:
    """A USD amount. Rounded to cents on the way out (`places=6` for a per-piece price); arithmetic stays in the caller's floats until the end."""
    d = Decimal(str(round(float(amount), places)))
    return Money(amount=d, currency="USD", usd=d, provenance=provenance)


def qty(value: float | Decimal, uom: str, provenance: Provenance) -> Quantity:
    d = Decimal(str(round(float(value), 6)))
    return Quantity(value=d, uom=uom, ea=d if uom == "EA" else None, provenance=provenance)


def unknown(what: str, why: str, owner: str, question: str, refs: list[EntityRef] | None = None) -> Unknown:
    if owner == "unassigned" and "ask planning" not in question:   # nobody in the data owns it: say so, and who to ask
        question = f"{question} (unassigned: ask planning)"
    return Unknown(what=what, why_it_blocks=why, owner=owner, question=question, refs=refs or [])


def ref(type_: str, id_: str, label: str | None = None) -> EntityRef:
    return EntityRef(type=type_, id=id_, label=label)
