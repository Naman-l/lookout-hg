"""Goods receipts read as delivery performance: on time is received on or before the PO line's delivery date (MB51 101 posting vs ME2N
delivery date), the run of late receipts a vendor is on, and what has been received against a PO line by month."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.cache import memo
from app.domain.common import AS_OF
from app.domain.fmt import md
from app.domain.orders.model import PoLine
from app.domain.receipts.model import Receipt

STREAK_MIN = 4      # a vendor is on a late streak when its last four receipts or more were each later than the line's delivery date
TURNED_PCT = 75     # ... after a record that was on time on at least this share of the receipts before the run: the vendor has turned late
RECORD_MIN = 5      # ... and a record is at least this many receipts before the run (fewer say nothing about what is usual)


class Arrival(BaseModel):
    receipt: str  # the material document / item
    po_line: str
    posted: str
    due: str | None
    days_late: int | None  # negative: early
    qty: float
    uom: str


class Delivery(BaseModel):
    """A vendor's record on the lines it delivered: every 101 receipt against a line with a delivery date, newest first."""

    n: int
    on_time: int
    on_time_pct: int | None
    late: int
    avg_days_late: float | None  # over the late receipts
    streak: int  # the run of late receipts the vendor is on now (newest first)
    streak_days: tuple[int, int] | None  # the fewest and most days late in that run
    streak_from: str | None
    streak_to: str | None
    before_pct: int | None  # on-time share of the receipts before the run
    turned: bool  # on a late streak after a good record (the run is new, not the vendor's usual)
    last: list[Arrival]  # the newest receipts (up to 10)
    line: str  # one sentence a panel shows


@memo
def arrivals(session: Session) -> dict[str, list[Arrival]]:
    """{vendor identity: its 101 receipts against dated lines, newest first}."""
    lines = {l.id: l for l in session.scalars(select(PoLine))}
    out: dict[str, list[Arrival]] = {}
    for r in session.scalars(select(Receipt).where(Receipt.movement == "101").order_by(Receipt.posting_date.desc(), Receipt.mat_doc.desc())):
        l = lines.get(r.po_line_id or "")
        if l is None:
            continue
        late = (date.fromisoformat(r.posting_date) - date.fromisoformat(l.delivery_date)).days if l.delivery_date else None
        out.setdefault(l.identity_id, []).append(Arrival(receipt=r.id, po_line=l.id, posted=r.posting_date, due=l.delivery_date, days_late=late, qty=r.qty, uom=r.uom))
    return out


def delivery(session: Session, identity_id: str) -> Delivery:
    rows = [a for a in arrivals(session).get(identity_id, []) if a.days_late is not None]
    late = [a for a in rows if a.days_late > 0]
    run = []
    for a in rows:
        if a.days_late <= 0:
            break
        run.append(a)
    pct = round(100 * (len(rows) - len(late)) / len(rows)) if rows else None
    streak = len(run) if len(run) >= STREAK_MIN else 0
    days = (min(a.days_late for a in run), max(a.days_late for a in run)) if streak else None
    before = rows[len(run):]
    before_pct = round(100 * sum(1 for a in before if a.days_late <= 0) / len(before)) if before else None
    turned = bool(streak) and len(before) >= RECORD_MIN and before_pct >= TURNED_PCT
    if not rows:
        line = "No receipts on file against a dated line."
    elif streak:
        line = (f"Last {streak} receipts late ({md(run[-1].posted)} → {md(run[0].posted)}, +{days[0]} to +{days[1]} days)"
                + (f"; on time on {before_pct}% of the {len(before)} before" if before_pct is not None else "") + ".")
    else:
        line = f"On time on {pct}% of {len(rows)} receipts" + (f"; late ones average {sum(a.days_late for a in late) / len(late):.0f} days." if late else ".")
    return Delivery(n=len(rows), on_time=len(rows) - len(late), on_time_pct=pct, late=len(late),
                    avg_days_late=round(sum(a.days_late for a in late) / len(late), 1) if late else None, streak=streak, streak_days=days,
                    streak_from=run[-1].posted if streak else None, streak_to=run[0].posted if streak else None, before_pct=before_pct, turned=turned,
                    last=rows[:10], line=line)


def received_by_month(session: Session, po_line_ids: list[str]) -> dict[str, float]:
    """{YYYY-MM: net quantity received in the base unit} over the given lines (101 less 102 and 122)."""
    out: dict[str, float] = {}
    if not po_line_ids:
        return out
    for r in session.scalars(select(Receipt).where(Receipt.po_line_id.in_(po_line_ids))):
        out[r.posting_date[:7]] = out.get(r.posting_date[:7], 0.0) + float(r.qty_base or 0.0)
    return out


def last_receipt(session: Session, po_line_id: str) -> str | None:
    r = session.scalar(select(Receipt.posting_date).where(Receipt.po_line_id == po_line_id, Receipt.movement == "101").order_by(Receipt.posting_date.desc()).limit(1))
    return r


def as_of() -> str:
    return AS_OF.isoformat()
