"""Purchase requisitions (SAP ME5A), and the MIS turnaround report kept beside them. The PR is a first-class record: PR -> PO turnaround is a
headline measure, and the time a PR waits is attributed to whoever held it."""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class PrLine(Base):
    __tablename__ = "pr_lines"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # "<PR>/<item>"
    pr_no: Mapped[str] = mapped_column(String)
    item: Mapped[int] = mapped_column(Integer)
    material: Mapped[str | None] = mapped_column(ForeignKey("materials.code"))
    short_text: Mapped[str | None] = mapped_column(String)
    qty: Mapped[float] = mapped_column(Float)
    qty_raw: Mapped[str] = mapped_column(String)
    uom: Mapped[str] = mapped_column(String)
    qty_base: Mapped[float | None] = mapped_column(Float)  # in the material's base unit (bags of cement -> MT)
    plant: Mapped[str] = mapped_column(String)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"))
    purch_group: Mapped[str] = mapped_column(String)
    buyer_id: Mapped[str | None] = mapped_column(String)
    requisitioner: Mapped[str | None] = mapped_column(String)
    created: Mapped[str] = mapped_column(String)
    created_raw: Mapped[str] = mapped_column(String)
    released: Mapped[str | None] = mapped_column(String)
    released_raw: Mapped[str | None] = mapped_column(String)
    needed_by: Mapped[str | None] = mapped_column(String)
    needed_by_raw: Mapped[str | None] = mapped_column(String)
    po_no: Mapped[str | None] = mapped_column(String)
    po_item: Mapped[int | None] = mapped_column(Integer)
    po_line_id: Mapped[str | None] = mapped_column(String)
    tracking_no: Mapped[str | None] = mapped_column(String)
    deletion: Mapped[int] = mapped_column(Integer)
    closed: Mapped[int] = mapped_column(Integer)
    changed_on: Mapped[str | None] = mapped_column(String)
    changed_on_raw: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)  # open | converted | deleted | closed
    flags: Mapped[str] = mapped_column(Text)
    src_row: Mapped[int] = mapped_column(Integer)


class TatReportRow(Base):
    """A row of the MIS PR -> PO turnaround sheet, as printed, with its '0 = nothing closed' read as no measurement."""

    __tablename__ = "tat_report"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vertical: Mapped[str] = mapped_column(String)
    group: Mapped[str | None] = mapped_column(String)
    project_as_printed: Mapped[str] = mapped_column(String)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"))
    raised: Mapped[int] = mapped_column(Integer)
    closed: Mapped[int] = mapped_column(Integer)
    avg_tat: Mapped[float | None] = mapped_column(Float)  # None where nothing closed
    avg_tat_raw: Mapped[str] = mapped_column(String)
    src_row: Mapped[int] = mapped_column(Integer)
