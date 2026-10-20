"""What a supplier's own notice states, read as fields by one rule per kind of statement, never per supplier or per message: the routes and the
findings build on these fields, so the same code answers any supplier whose notice says the same kind of thing in other words or on other dates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.inbox.model import Message

_DAY = r"\d{4}-\d{2}-\d{2}|\d{1,2} [A-Za-z]+,? \d{4}|[A-Za-z]+ \d{1,2},? \d{4}"
_LEAD_TIME = re.compile(rf"orders (?:placed|received|booked) (?P<when>after|on or after|from|starting) (?P<day>{_DAY})[^.]*?lead[- ]time[^.]*?(?:from )?(?P<old>\d+) weeks? to (?P<new>\d+) weeks?", re.I)


@dataclass(frozen=True)
class LeadTimeChange:
    """A lead-time change with a cutoff, as the supplier's notice states it: orders placed by `order_by` keep `old_weeks`; later ones wait `new_weeks`."""

    order_by: date        # the last day an order keeps the old lead time
    when: str             # how the notice ties the change to the cutoff: "after", "on or after", "from", "starting"
    cutoff_text: str      # the cutoff as the notice writes it ("1 October 2026")
    old_weeks: int
    new_weeks: int
    message_id: str
    notice_date: str      # the message's date (YYYY-MM-DD)


def _day(text: str) -> date | None:
    text = " ".join(text.replace(",", " ").split())
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%B %d %Y", "%d %b %Y", "%b %d %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def lead_time_change(session: Session, ident: str | None) -> LeadTimeChange | None:
    """The newest lead-time change with a cutoff in the supplier's own messages ("for orders placed after 1 October 2026, standard lead time extends from
    8 weeks to 16 weeks"), or None. "after" keeps the cutoff day itself; "on or after", "from" and "starting" make the day before the last one."""
    if not ident:
        return None
    for m in session.scalars(select(Message).where(Message.identity_id == ident).order_by(Message.date.desc())):
        hit = _LEAD_TIME.search(" ".join((m.body or "").split()))
        day = _day(hit.group("day")) if hit else None
        if hit and day and int(hit.group("new")) > int(hit.group("old")):
            order_by = day if hit.group("when").lower() == "after" else day - timedelta(days=1)
            return LeadTimeChange(order_by=order_by, when=hit.group("when").lower(), cutoff_text=hit.group("day"), old_weeks=int(hit.group("old")), new_weeks=int(hit.group("new")),
                                  message_id=m.id, notice_date=(m.date or "")[:10])
    return None
