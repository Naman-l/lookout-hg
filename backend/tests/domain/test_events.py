"""Step 24 writes the dated things the messages, news and notice say as records, each with its source, supplier and owner."""

from __future__ import annotations

import json

from sqlalchemy import select

from app.domain.events.model import Deadline, Event
from app.domain.suppliers.model import SupplierIdentity


def _name(session, identity_id):
    return session.get(SupplierIdentity, identity_id).name if identity_id else None


def test_events_are_the_messages_news_and_notice_written_down_once(session):
    ev = list(session.scalars(select(Event)))
    assert {"force_majeure", "price_change", "closure", "slip", "news", "tariff_notice"} <= {e.kind for e in ev}
    fire = next(e for e in ev if e.kind == "force_majeure")
    assert "Yunzhan" in _name(session, fire.identity_id)
    assert fire.owner == "Dana" and fire.source_type == "message" and len(json.loads(fire.refs_json)) == 10
    assert next(e for e in ev if e.kind == "tariff_notice").source_type == "notice"


def test_news_gets_a_topic_from_the_recipes_vocabulary(session):
    news = list(session.scalars(select(Event).where(Event.kind == "news")))
    topic = {e.source_id: e.topic for e in news}
    assert topic["N-023"] == "cyberattack" and topic["N-014"] == "insolvency" and topic["N-020"] == "fire" and topic["N-019"] == "shortage" and topic["N-010"] == "price_rise"
    assert topic["N-022"] == "denial" and topic["N-001"] == "recall"                                 # a denied rumour is not a closure; a recall is not an insolvency
    assert all(e.identity_id for e in news)                                                          # only news matched to a supplier is an event


def test_deadlines_are_the_dates_that_lived_in_emails(session):
    d = sorted(session.scalars(select(Deadline)), key=lambda x: (x.due_date, x.kind))
    assert [(x.kind, x.due_date) for x in d[:7]] == [("last_shipment", "2026-09-28"), ("lead_time_change", "2026-10-01"), ("revised_dates", "2026-10-10"), ("quote_validity", "2026-10-13"),
                                                      ("exclusion_requests", "2026-10-15"), ("price_lock", "2026-10-15"), ("quote_validity", "2026-10-16")]
    assert d[0].owner == "Tom" and "Meiya" in _name(session, d[0].identity_id)                              # Meiya's last shipment before its holiday, read from its notice
    assert "Jadepeak" in _name(session, d[1].identity_id) and "longer lead time" in d[1].detail             # the supplier's own cut-off, read from its notice
    assert d[2].owner == "Dana" and "Yunzhan" in _name(session, d[2].identity_id)
    assert d[-1].kind == "address_forwarding" and d[-1].due_date == "2026-12-31" and "baycrestconnectors.example" in d[-1].detail   # the old address stops forwarding
    assert all(json.loads(x.refs_json) for x in d if x.kind == "quote_validity")
