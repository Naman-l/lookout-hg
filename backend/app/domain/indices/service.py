"""Commodity indices and price variation: the PV a clause owes (quantity x rate x the variable share x (index now / index at the base month - 1)),
an index's movement over months, and what a month's delay costs on a PV-linked item not yet ordered."""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import lookups
from app.domain.cache import memo
from app.domain.common import AS_OF
from app.domain.indices.model import IndexValue


class PvResult(BaseModel):
    qty: float
    rate: float
    share: float
    base_month: str
    base_index: float | None
    current_month: str
    current_index: float | None
    pv: float | None  # None when an index value is missing
    formula: str  # the sum written out, every figure from the records


@memo
def series(session: Session) -> dict[str, dict[str, float]]:
    """{index: {YYYY-MM: value}} up to the data date's month."""
    out: dict[str, dict[str, float]] = {}
    for v in session.scalars(select(IndexValue).order_by(IndexValue.month)):
        if v.month <= AS_OF.isoformat()[:7]:
            out.setdefault(v.index, {})[v.month] = v.value
    return out


def value(session: Session, index: str, month: str) -> float | None:
    return series(session).get(index, {}).get(month)


def latest_month(session: Session, index: str) -> str | None:
    s = series(session).get(index) or {}
    return max(s) if s else None


def pv(session: Session, *, qty: float, rate: float, share: float, index: str, base_month: str, current_month: str) -> PvResult:
    b, c = value(session, index, base_month), value(session, index, current_month)
    amount = qty * rate * share * (c / b - 1) if b and c else None
    from app.domain.fmt import en_in  # noqa: PLC0415

    formula = (f"{en_in(qty)} x ₹{en_in(rate)} x {share:g} x ({en_in(c) if c else '?'} / {en_in(b) if b else '?'} - 1)"
               + (f" = ₹{en_in(amount)}" if amount is not None else ""))
    return PvResult(qty=qty, rate=rate, share=share, base_month=base_month, base_index=b, current_month=current_month, current_index=c, pv=amount, formula=formula)


def monthly_change(session: Session, index: str, months: int = 6) -> float | None:
    """The average month-on-month change of the index over the last `months` months, as a share (0.012 = 1.2% a month)."""
    s = series(session).get(index) or {}
    keys = sorted(s)[-(months + 1):]
    if len(keys) < 2:
        return None
    steps = [s[b] / s[a] - 1 for a, b in zip(keys, keys[1:])]
    return sum(steps) / len(steps)


def change_since(session: Session, index: str, month: str) -> float | None:
    s = series(session).get(index) or {}
    last = latest_month(session, index)
    return s[last] / s[month] - 1 if last and month in s and s[month] else None


def variable_share(session: Session, index: str | None) -> float | None:
    """The share a PV clause moves with this index: a PO on file's own clause, else the recipe's usual weight for the index."""
    if not index:
        return None
    from app.domain.orders.service import all_lines  # noqa: PLC0415

    on_file = [l.pv_variable_share for l in all_lines(session).values() if l.pv_index == index and l.pv_variable_share]
    if on_file:
        return sorted(on_file)[len(on_file) // 2]
    return (lookups.answers().get("pv_variable_share") or {}).get(index)
