"""Milestones after the PO (the expediting tracker): MFC, inspection, dispatch, delivery, site readiness, commissioning and warranty."""

from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class Milestone(Base):
    __tablename__ = "milestones"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # "<PO>/<item>"
    po_no: Mapped[str] = mapped_column(String)
    po_item: Mapped[int] = mapped_column(Integer)
    po_line_id: Mapped[str | None] = mapped_column(String)  # None when the PO is older than the ME2N export
    project_id: Mapped[str | None] = mapped_column(String)
    item_text: Mapped[str | None] = mapped_column(String)
    vendor_name: Mapped[str | None] = mapped_column(String)
    record_id: Mapped[str | None] = mapped_column(String)
    mfc_requested: Mapped[str | None] = mapped_column(String)
    mfc_issued: Mapped[str | None] = mapped_column(String)
    mfg_days: Mapped[int | None] = mapped_column(Integer)
    inspection_call: Mapped[str | None] = mapped_column(String)  # the day the vendor called for inspection
    inspection_planned: Mapped[str | None] = mapped_column(String)  # the day the inspection is set for
    inspection_done: Mapped[str | None] = mapped_column(String)
    dispatch_clearance: Mapped[str | None] = mapped_column(String)
    delivered: Mapped[str | None] = mapped_column(String)
    site_ready_planned: Mapped[str | None] = mapped_column(String)
    commissioned: Mapped[str | None] = mapped_column(String)
    warranty_months: Mapped[int | None] = mapped_column(Integer)
    warranty_from: Mapped[str | None] = mapped_column(String)  # Supply | Commissioning
    warranty_end: Mapped[str | None] = mapped_column(String)  # computed: from supply (or commissioning) plus the months
    remarks: Mapped[str | None] = mapped_column(Text)
    src_row: Mapped[int] = mapped_column(Integer)
