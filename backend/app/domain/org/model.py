"""The organisation chart as the SCM organogram draws it: every person and open post, whom they report to, their desk and their work. Edits a
person makes on the Organisation page are kept apart, in the `org_edits` ledger (service.py), and laid over these rows when the chart is read."""

from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class OrgPerson(Base):
    """One box on the organogram: a person, or a post to be filled (`vacancy`). `member_id` links a person to the SCM team (buyers.id)."""

    __tablename__ = "org_people"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # the member id; "tbf-<row>-<col>" for an open post
    name: Mapped[str | None] = mapped_column(String)  # None for an open post
    designation: Mapped[str] = mapped_column(String)
    reports_to: Mapped[str | None] = mapped_column(String)  # an org_people id; None for the head
    category: Mapped[str | None] = mapped_column(String)  # the desk label the sheet writes beside them ("Aggregate", "Logistics")
    portfolio: Mapped[str | None] = mapped_column(Text)  # a lead's line of what their team buys; an open post's desk ("T&D")
    responsibilities: Mapped[str | None] = mapped_column(Text)  # their work, as the sheet words it
    position: Mapped[int] = mapped_column(Integer)  # order under their lead, as drawn
    vacancy: Mapped[int] = mapped_column(Integer)  # 1: "(TBF)", to be filled
    member_id: Mapped[str | None] = mapped_column(String)
    src_row: Mapped[int | None] = mapped_column(Integer)
    src_col: Mapped[str | None] = mapped_column(String)
