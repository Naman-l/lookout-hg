"""What a supplier's notice says beyond the revised dates, as fields: the lead time it sets for new orders, where each family is made and what duty that brings, and the shortage the new dates cause.

Read from the notice's own records (its message events: the lead-time deadline, the origin claim per line) and from the demand and tariff services; nothing here names a customer, a
supplier or a part. Every field is plain text or an ISO date, with the message line it was read from."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.demand import service as demand
from app.domain.inbox.model import MessageEvent
from app.domain.orders.model import PoLine
from app.domain.tariffs import service as tariffs


def _duty_note(session: Session, part: str, country: str) -> str:
    """'no new duty' for a country the tariff does not touch; the rate and date where the part's code is on the list and the notice says it is made in China."""
    if country.strip().lower() not in ("china", "prc", "cn"):
        return f"no new duty: made in {country}"
    ts = tariffs.tariff_rule_for(session, part)
    if ts.status == "listed":
        return f"{ts.rule.rate:.0%} from {ts.rule.effective_date}"
    return "made in China; the part's code is not on the duty list" if ts.status != "unknown" else "made in China; the part's tariff code is unknown"


def notice_terms(session: Session, message_id: str, parts: list[str]) -> dict:
    """The notice `message_id` as fields; `parts` are the parts of the lines it moves."""
    events = list(session.scalars(select(MessageEvent).where(MessageEvent.message_id == message_id).order_by(MessageEvent.id)))
    lead = next((e for e in events if e.kind == "deadline" and "lead time" in (e.line_ref or "") + (e.detail or "")), None)
    terms: dict = {"notice": message_id, "lead_time_new_orders": None, "site_by_family": [], "next_shortage": None}
    if lead is not None:
        m = re.search(r"(\d+ \w+) becomes (\d+ \w+)", lead.detail or "")
        terms["lead_time_new_orders"] = {"text": m.group(2) if m else lead.detail, "was": m.group(1) if m else None, "from_date": lead.date_to, "applies_to": "orders placed after the date", "line": lead.line_ref}
    sites: dict[tuple[str, str], dict] = {}
    for e in events:
        if e.kind != "origin_claim" or e.ref_type != "po_line":
            continue
        m = re.match(r"(?P<model>\S+) \((?P<family>[^)]+)\) is manufactured in (?P<city>[^,]+), (?P<country>[^(]+?)\s*(?:\(|$)", e.detail or "")
        line = session.get(PoLine, e.ref_id)
        if not m or line is None:
            continue
        row = sites.setdefault((m.group("family"), m.group("city")), {"family": m.group("family"), "site": m.group("city"), "country": m.group("country"), "parts": [], "models": [], "lines": [],
                                                                      "duty_note": _duty_note(session, line.part_number, m.group("country")), "line": e.line_ref})
        for key, val in (("parts", line.part_number), ("models", m.group("model")), ("lines", e.ref_id)):
            if val not in row[key]:
                row[key].append(val)
    terms["site_by_family"] = sorted(sites.values(), key=lambda r: (r["site"], r["family"]))
    hits = [(imp.first_month, p, float(imp.first_month_qty.value)) for p in sorted(set(parts)) if (imp := demand.slip_impact(session, p))]
    if hits:
        month, part, qty = min(hits)
        terms["next_shortage"] = {"part": part, "month": month, "qty": qty, "all": [{"part": p, "month": mo, "qty": q} for mo, p, q in sorted(hits)]}
    return terms
