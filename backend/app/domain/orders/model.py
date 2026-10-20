"""Purchase order lines (both ERPs), FX rates and the reference price per part."""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class FxRate(Base):
    __tablename__ = "fx_rates"

    month: Mapped[str] = mapped_column(String, primary_key=True)  # YYYY-MM
    currency: Mapped[str] = mapped_column(String, primary_key=True)
    usd_per_unit: Mapped[float] = mapped_column(Float)


class PoLine(Base):
    """One PO line. Quantities and prices stay in the line's own unit and currency beside the converted ones."""

    __tablename__ = "po_lines"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # "<po_number>/<line>", e.g. ORD-26-00450/10
    po_number: Mapped[str] = mapped_column(String)
    line: Mapped[int] = mapped_column(Integer)
    system: Mapped[str] = mapped_column(String)  # legacy (PO-) | new (HPO-)
    part_number: Mapped[str] = mapped_column(ForeignKey("parts.part_number"))
    part_raw: Mapped[str] = mapped_column(String)
    record_id: Mapped[str] = mapped_column(ForeignKey("supplier_records.record_id"))
    identity_id: Mapped[str] = mapped_column(ForeignKey("supplier_identities.id"))
    buyer_id: Mapped[str | None] = mapped_column(ForeignKey("buyers.id"))
    buyer_raw: Mapped[str] = mapped_column(String)
    qty_raw: Mapped[str] = mapped_column(String)
    qty: Mapped[float] = mapped_column(Float)  # in the line's unit
    uom_raw: Mapped[str] = mapped_column(String)
    uom: Mapped[str] = mapped_column(String)  # normalised: EA, M, PK, BOX, KPCS
    qty_ea: Mapped[float | None] = mapped_column(Float)  # quantity in the part's unit; None when a BOX or PK size is unknown
    qty_received_raw: Mapped[str] = mapped_column(String)
    qty_received: Mapped[float] = mapped_column(Float)  # in the line's unit
    open_qty_ea: Mapped[float | None] = mapped_column(Float)  # (qty - received) in the part's unit, for OPEN and PARTIAL
    line_usd: Mapped[float | None] = mapped_column(Float)  # qty x price at the order month's rate: known even when qty_ea is not
    open_usd: Mapped[float | None] = mapped_column(Float)  # (qty - received) x price, OPEN and PARTIAL only
    unit_price_raw: Mapped[str] = mapped_column(String)
    currency_raw: Mapped[str] = mapped_column(String)
    currency: Mapped[str] = mapped_column(String)
    currency_method: Mapped[str] = mapped_column(String)  # stated | inferred (blank, from the supplier record)
    unit_price: Mapped[float] = mapped_column(Float)  # per `uom`, in `currency`
    fx_month: Mapped[str | None] = mapped_column(String)
    fx_rate: Mapped[float | None] = mapped_column(Float)
    unit_usd_each: Mapped[float | None] = mapped_column(Float)  # USD per part unit
    order_date_raw: Mapped[str] = mapped_column(String)
    order_date: Mapped[str] = mapped_column(String)
    promised_date_raw: Mapped[str | None] = mapped_column(String)
    promised_date: Mapped[str | None] = mapped_column(String)
    received_date_raw: Mapped[str | None] = mapped_column(String)
    received_date: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)  # OPEN | PARTIAL | CLOSED | CANCELLED
    flags: Mapped[str | None] = mapped_column(Text)  # return, short_closed, stale_open, price_outlier, non_active_supplier, no_promise_date, legacy_id_in_new_po, dup_removed
    src_row: Mapped[int] = mapped_column(Integer)


class ReferencePrice(Base):
    """The USD price used to value demand that has no PO yet. The rule is in docs/design/domain.md."""

    __tablename__ = "reference_prices"

    part_number: Mapped[str] = mapped_column(ForeignKey("parts.part_number"), primary_key=True)
    usd_each: Mapped[float] = mapped_column(Float)
    po_line_id: Mapped[str] = mapped_column(ForeignKey("po_lines.id"))
    n_lines: Mapped[int] = mapped_column(Integer)  # lines that qualified
    n_excluded: Mapped[int] = mapped_column(Integer)  # lines left out (outlier, non-active supplier, cancelled)
