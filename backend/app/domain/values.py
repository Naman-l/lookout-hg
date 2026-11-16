"""Small constructors for the value objects, so every service builds Money, Quantity and Unknown the same way."""

from __future__ import annotations

from decimal import Decimal

from app.domain.common import EntityRef, Money, Provenance, Quantity, Unknown


def prov(method: str, source: str, *, row: str | None = None, raw: str | None = None,
         inputs: list[EntityRef] | None = None, rule: str | None = None, by: str = "recipe") -> Provenance:
    return Provenance(method=method, source=source, row=row, raw=raw, inputs=inputs or [], rule=rule, by=by)


def money(amount: float | Decimal, provenance: Provenance, currency: str | None = None, places: int = 2) -> Money:
    """An amount in the base currency (the recipe's `base_currency`). Rounded on the way out; arithmetic stays in the caller's floats until the end.
    Every line in these records is in the base currency, so `base` is the amount itself."""
    d = Decimal(str(round(float(amount), places)))
    cur = currency or base_currency()
    return Money(amount=d, currency=cur, base=d if cur == base_currency() else None, provenance=provenance)


def base_currency() -> str:
    """The recipe's base currency (answers.yaml `base_currency`), read once."""
    global _BASE
    if _BASE is None:
        import yaml

        from app.domain.common.recipe import recipe_dir

        try:
            _BASE = str(yaml.safe_load((recipe_dir() / "answers.yaml").read_text()).get("base_currency") or "INR")
        except OSError:
            _BASE = "INR"
    return _BASE


_BASE: str | None = None


def qty(value: float | Decimal, uom: str, provenance: Provenance) -> Quantity:
    d = Decimal(str(round(float(value), 6)))
    return Quantity(value=d, uom=uom, provenance=provenance)


def unknown(what: str, why: str, owner: str, question: str, refs: list[EntityRef] | None = None) -> Unknown:
    if owner == "unassigned" and "ask planning" not in question:   # nobody in the data owns it: say so, and who to ask
        question = f"{question} (unassigned: ask planning)"
    return Unknown(what=what, why_it_blocks=why, owner=owner, question=question, refs=refs or [])


def ref(type_: str, id_: str, label: str | None = None) -> EntityRef:
    return EntityRef(type=type_, id=id_, label=label)
