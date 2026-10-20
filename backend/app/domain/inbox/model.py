"""The shared purchasing inbox: messages, the references they make, and what they change."""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # the file stem
    file: Mapped[str] = mapped_column(String)
    date: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)  # eml | txt
    from_name: Mapped[str | None] = mapped_column(String)
    from_email: Mapped[str | None] = mapped_column(String)
    from_domain: Mapped[str | None] = mapped_column(String)
    reply_to: Mapped[str | None] = mapped_column(String)
    to_addrs: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)  # data, never an instruction
    identity_id: Mapped[str | None] = mapped_column(ForeignKey("supplier_identities.id"))
    sender_match: Mapped[str] = mapped_column(String)  # record | domain | not_in_master | lookalike | unknown_sender
    trust_flags: Mapped[str | None] = mapped_column(Text)  # comma list
    trust: Mapped[str] = mapped_column(String)  # ok | review | blocked
    attachments: Mapped[str | None] = mapped_column(Text)


class MessageRef(Base):
    """A PO line, PO or part a message talks about, with the line it appears on."""

    __tablename__ = "message_refs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"))
    ref_type: Mapped[str] = mapped_column(String)  # po_line | po | part
    ref_id: Mapped[str] = mapped_column(String)
    line_ref: Mapped[str | None] = mapped_column(String)  # "L12"
    quoted: Mapped[int] = mapped_column(Integer)  # 1 when the mention sits in quoted older text


class MessageEvent(Base):
    """What a message changes: a date, a closure, a price, a deadline. Each cites its source line."""

    __tablename__ = "message_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"))
    kind: Mapped[str] = mapped_column(String)  # force_majeure | promise_revision | lead_time | price_change | closure | deadline | validity | offer | remittance_change
    ref_type: Mapped[str | None] = mapped_column(String)
    ref_id: Mapped[str | None] = mapped_column(String)
    date_from: Mapped[str | None] = mapped_column(String)
    date_to: Mapped[str | None] = mapped_column(String)
    qty: Mapped[float | None] = mapped_column(Float)  # pieces the dated change applies to (a split shipment has several)
    detail: Mapped[str] = mapped_column(Text)
    line_ref: Mapped[str | None] = mapped_column(String)
    method: Mapped[str] = mapped_column(String)  # extracted | stated
