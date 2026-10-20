"""Supplier offers extracted from the inbox: a price for a part under conditions."""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class Offer(Base):
    __tablename__ = "offers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"))
    source: Mapped[str] = mapped_column(String)  # "email" | "pdf:<file>"
    line_ref: Mapped[str | None] = mapped_column(String)  # where in the source the price sits
    quote_no: Mapped[str | None] = mapped_column(String)
    identity_id: Mapped[str | None] = mapped_column(ForeignKey("supplier_identities.id"))  # None: sender not in the master
    supplier_name: Mapped[str] = mapped_column(String)
    part_number: Mapped[str | None] = mapped_column(String)  # the company's part number; None if the quote names none
    supplier_model: Mapped[str | None] = mapped_column(String)
    qty_break: Mapped[int | None] = mapped_column(Integer)  # price applies from this order quantity
    price_raw: Mapped[str] = mapped_column(String)  # as written ("389,50", "per 1,000 240.58")
    price: Mapped[float] = mapped_column(Float)  # per price_basis unit, in `currency`
    currency: Mapped[str] = mapped_column(String)
    price_basis: Mapped[str] = mapped_column(String)  # each | per_1000
    unit_price_each: Mapped[float] = mapped_column(Float)  # price per piece in `currency`
    incoterm: Mapped[str | None] = mapped_column(String)
    incoterm_place: Mapped[str | None] = mapped_column(String)
    origin_claim: Mapped[str | None] = mapped_column(String)  # as the supplier states it
    origin_iso: Mapped[str | None] = mapped_column(String)  # CN | MX | VN | ... ; None when undetermined
    lead_time: Mapped[str | None] = mapped_column(String)  # "6 weeks"
    lead_time_condition: Mapped[str | None] = mapped_column(String)  # "after sample approval": a value is not valid without it
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    validity_date: Mapped[str | None] = mapped_column(String)
    annual_qty: Mapped[int | None] = mapped_column(Integer)  # the supplier's own estimate of a year's use, as its quote prints it
    moq: Mapped[int | None] = mapped_column(Integer)
    tooling_usd: Mapped[float | None] = mapped_column(Float)
    surcharge_pct: Mapped[float | None] = mapped_column(Float)
    surcharge_included: Mapped[int | None] = mapped_column(Integer)  # 1: the quoted price already includes the surcharge; 0 or None: it is added on top
    payment_terms: Mapped[str | None] = mapped_column(String)
    prepayment: Mapped[str | None] = mapped_column(String)  # what must be paid before the goods ship, as the document states it
    available_from: Mapped[str | None] = mapped_column(String)  # ISO date this offer (an alternative origin, a new site) can start, when the document gives one
    conditions: Mapped[str | None] = mapped_column(Text)  # costs and conditions outside the headline price
    superseded_by: Mapped[int | None] = mapped_column(Integer)  # a later correction replaces this price
    trust: Mapped[str] = mapped_column(String)  # the message's trust verdict; blocked offers are never compared
