"""Events (something happened) and deadlines (something lapses), as records: each with its source, its supplier, its owner and the records it touches."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String)  # force_majeure | price_change | closure | slip | news | tariff_notice
    topic: Mapped[str | None] = mapped_column(String)  # news only: cyberattack, insolvency, fire, shortage, price_rise, ... (from the recipe's vocabulary), or 'other'
    date: Mapped[str] = mapped_column(String)  # when it was written or published
    identity_id: Mapped[str | None] = mapped_column(ForeignKey("supplier_identities.id"))
    title: Mapped[str] = mapped_column(Text)  # the message's subject or the headline
    detail: Mapped[str | None] = mapped_column(Text)  # what it says it changes, from the record it was read from
    source_type: Mapped[str] = mapped_column(String)  # message | news | notice
    source_id: Mapped[str] = mapped_column(String)
    owner: Mapped[str | None] = mapped_column(String)  # the buyer on most of the supplier's lines
    refs_json: Mapped[str | None] = mapped_column(Text)  # the po lines and parts it touches, [{"type", "id"}]


class Deadline(Base):
    __tablename__ = "deadlines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String)  # quote_validity | price_lock | revised_dates | last_shipment | address_forwarding | lead_time_change | exclusion_requests
    due_date: Mapped[str] = mapped_column(String)
    identity_id: Mapped[str | None] = mapped_column(ForeignKey("supplier_identities.id"))
    detail: Mapped[str | None] = mapped_column(Text)  # what lapses or is due, from the record it was read from
    source_type: Mapped[str] = mapped_column(String)  # message | offer | notice
    source_id: Mapped[str] = mapped_column(String)
    owner: Mapped[str | None] = mapped_column(String)
    refs_json: Mapped[str | None] = mapped_column(Text)
