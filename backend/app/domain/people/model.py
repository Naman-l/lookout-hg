"""People: the SCM team (the only users: they sign), and the people outside SCM the team writes to (project heads and planners, Finance,
QA, the vendor-master desk), each on file with their function and address. Nothing here names a person; the recipe's answers and the
project directory do."""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class Buyer(Base):
    """A member of the SCM team. `id` is the first name the data uses; `signs_upto` is the DoA limit (None = no limit). The organogram gives the
    designation and the reporting line; the recipe's answers give the rest."""

    __tablename__ = "buyers"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    initials: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)
    purchasing_groups: Mapped[str] = mapped_column(String)  # comma list of SAP purchasing groups
    verticals: Mapped[str] = mapped_column(String)  # comma list
    sap_user: Mapped[str | None] = mapped_column(String)  # ME2N's Created By
    email: Mapped[str | None] = mapped_column(String)
    signs_upto: Mapped[float | None] = mapped_column(Float)
    countersigns: Mapped[int] = mapped_column(Integer)  # 1: signs second on drafts above the DoA threshold
    sees_all: Mapped[int] = mapped_column(Integer)  # 1: sees every member's Team page
    designation: Mapped[str | None] = mapped_column(String)  # as the organogram writes it ("AM", "GM - SCM")
    reports_to: Mapped[str | None] = mapped_column(String)  # the member they report to, as the organogram draws it; None for the Head
    duties: Mapped[str | None] = mapped_column(String)  # comma list: the department-wide questions they hold (a vertical, vendor_library, rate_spread, mis)


class Contact(Base):
    """A person outside SCM on file: the owner of a function a note can go to."""

    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # function, or function:project
    name: Mapped[str] = mapped_column(String)
    function: Mapped[str] = mapped_column(String)  # project_head | planner | finance_treasury | finance_funds | qa | qa_inspection | vendor_master | md_office | ho_stores
    title: Mapped[str | None] = mapped_column(String)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"))
    email: Mapped[str | None] = mapped_column(String)


class PurchasingGroup(Base):
    __tablename__ = "purchasing_groups"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    description: Mapped[str] = mapped_column(Text)
    person_id: Mapped[str | None] = mapped_column(ForeignKey("buyers.id"))
    email: Mapped[str | None] = mapped_column(String)
    src_row: Mapped[int] = mapped_column(Integer)
