"""Where the organism gets DOMAIN's services.

DOMAIN's real services, bound to a session on the run's database. The item, the
supplier contact and the message thread are DOMAIN's attention, suppliers and inbox services, adapted to the shapes
the tools read. `LOOKOUT_FAKE_SERVICES=1` (the unit tests) uses the in-memory fakes for everything."""

from __future__ import annotations

import os
from functools import partial
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session



class Services(SimpleNamespace):
    def close(self) -> None:
        if getattr(self, "_session", None) is not None:
            self._session.close()


def get(db_path: str | None = None) -> Services:
    if os.environ.get("LOOKOUT_FAKE_SERVICES") == "1" or db_path is None:
        from .dev import fakes  # noqa: PLC0415  test stand-ins: loaded only when asked for

        return Services(phases=fakes.phases, quotes=fakes.quotes, tariffs=fakes.tariffs, orders=fakes.orders, demand=fakes.demand, bom=fakes.bom, attention=fakes.attention, suppliers=fakes.suppliers, inbox=fakes.inbox, _session=None)
    from ..domain.attention import service as attention
    from ..domain.bom import service as bom
    from ..domain.demand import service as demand
    from ..domain.inbox import service as inbox
    from ..domain.orders import service as orders
    from ..domain.phases import service as phases
    from ..domain.suppliers import service as suppliers
    from ..domain.quotes import service as quotes
    from ..domain.orders.notice import notice_terms
    from ..domain.tariffs import service as tariffs

    session = Session(create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False}))
    return Services(
        orders=SimpleNamespace(open_supply=partial(orders.open_supply, session), notice_terms=partial(notice_terms, session), supplier_delivery=partial(suppliers.delivery_ranking, session)),
        quotes=SimpleNamespace(compare_offers=partial(quotes.compare_offers, session)),
        phases=SimpleNamespace(part_phases=partial(phases.part_phases, session), line_phases=partial(phases.line_phases, session), build_readiness=partial(phases.build_readiness, session)),
        tariffs=SimpleNamespace(exposure_for_part=partial(tariffs.exposure_for_part, session), duty_for_line=partial(tariffs.duty_for_line, session), buyer_of=partial(_buyer_of, session)),
        demand=SimpleNamespace(requirements=partial(demand.requirements, session), shortage=partial(demand.shortage, session)),
        bom=SimpleNamespace(where_used=partial(bom.where_used, session), explode_bom=partial(bom.explode_bom, session), product_families=partial(_product_families, session)),
        attention=SimpleNamespace(get_item=partial(_get_item, attention, session), list_items=partial(attention.what_needs_attention, session),
                                  stage_of=partial(_stage_of, session, db_path), options=partial(_options, session), case_kind=partial(_case_kind, session), option_kinds=partial(_option_kinds, session), findings=partial(_findings, session), requests_for=partial(_requests_for, suppliers, session, db_path)),
        suppliers=SimpleNamespace(contact_for=partial(_contact_for, suppliers, session), list_suppliers=partial(suppliers.list_suppliers, session)),
        inbox=SimpleNamespace(read_thread=partial(_read_thread, inbox, session), message_offers=partial(quotes.offers_in_message, session), list_messages=partial(inbox.list_messages, session), classify=partial(inbox.classify, session),
                              message_detail=partial(inbox.message_detail, session), trust=partial(inbox.trust, session), thread_for=partial(_thread_for, inbox, session), list_suppliers=partial(suppliers.list_suppliers, session), find_records=partial(_find_records, session)),
        _session=session,
    )


def _buyer_of(session, part: str) -> str:
    """The id of the buyer who owns the part (from the data), who owns a question about its lines."""
    from ..domain.ownership import buyer_of_part  # noqa: PLC0415

    return buyer_of_part(session, part)


def _requests_for(suppliers, session, db_path, item_key=None, supplier_id=None) -> list[dict]:
    """Every request to a supplier that the approval ledger holds for an item, a supplier, or the contact either one writes to: what is waiting, approved, sent or rejected, and why. Read only."""
    from ..domain.actions import ledger  # noqa: PLC0415

    drafts = [a for a in ledger.list_actions(db_path) if a.type == "supplier_request"]
    suppliers_in = {supplier_id} if supplier_id else set()
    suppliers_in |= {a.target.id for a in drafts if item_key and a.item_key == item_key and a.target}
    suppliers_in |= {part for part in (item_key or "").split(":") if part and any(a.target and a.target.id == part for a in drafts)}
    contacts = {a.recipient for a in drafts if item_key and a.item_key == item_key and a.recipient}
    for sid in suppliers_in:
        try:
            c = suppliers.contact_on_file(session, sid)
        except Exception:  # noqa: BLE001  a supplier the records do not know has no contact on file
            continue
        if c.email:
            contacts.add(c.email)
    out = []
    for a in drafts:
        if (item_key and a.item_key == item_key) or (a.target and a.target.id in suppliers_in) or (a.recipient in contacts):
            out.append({"action_id": a.action_id, "state": a.state, "recipient": a.recipient, "subject": a.subject, "owner": a.owner, "item_key": a.item_key, "proposed_at": a.proposed_at,
                        "decided_at": a.decided_at, "decided_by": a.decided_by, "rejected_because": a.reason if a.state == "rejected" else None, "sent_at": a.confirmed_at})
    return out


def _product_families(session) -> list[str]:
    """The robots' family names, from the products table: what the prose calls them."""
    from sqlalchemy import select  # noqa: PLC0415

    from ..domain.demand.model import Product  # noqa: PLC0415

    return list(session.scalars(select(Product.family).distinct()))


def _stage_of(session, db_path, item):
    """Where the work on the item stands, from the runs and the ledger (derived, never stored)."""
    from ..domain.attention import stage  # noqa: PLC0415

    return stage.attach(session, db_path, [item])[0].stage


def _options(session, key):
    """The ways through a supplier's disruption, or None for an item that is not one."""
    from ..domain.attention import options  # noqa: PLC0415

    return options.fire_options(session, key)


def _case_kind(session, key):
    """fire, slip, incident, risk, closure or price_lock, from the item's detector; None for any other item."""
    from ..domain.attention import options  # noqa: PLC0415

    return options.case_kind(session, key)


def _option_kinds(session, key):
    """The options of the item's kind of case from the code table (label, leads_to, to, button), or []."""
    from ..domain.attention import option_kinds  # noqa: PLC0415

    return option_kinds.option_kinds(session, key)


def _findings(session, key):
    """The facts code found on the case (findings.md Rev 2), or []."""
    from ..domain.attention import findings  # noqa: PLC0415

    return findings.candidates(session, key)


def _get_item(attention, session, key):
    detail = attention.item_detail(session, key)
    if detail is None:
        raise KeyError(key)
    return detail


def _contact_for(suppliers, session, identity_id):
    c = suppliers.contact_on_file(session, identity_id)
    return c if c.email else None  # no address on file means nothing can be drafted


def _find_records(session, text: str):
    """Vendor records (every spelling and legacy id the ERP holds) whose name contains the text, with the company each is linked to."""
    from sqlalchemy import select

    from ..domain.suppliers.model import SupplierIdentity, SupplierRecord

    rows = session.execute(select(SupplierRecord.record_id, SupplierRecord.name, SupplierRecord.identity_id, SupplierRecord.identity_method, SupplierIdentity.name)
                           .join(SupplierIdentity, SupplierIdentity.id == SupplierRecord.identity_id).where(SupplierRecord.name.ilike(f"%{text}%"))).all()
    return [{"record": r[0], "record_name": r[1], "company": r[2], "company_name": r[4], "linked_by": r[3]} for r in rows]


def _thread_for(inbox, session, message_id):
    return next((t for t in inbox.list_threads(session) if any(m.ref.id == message_id for m in t.messages)), None)


def _read_thread(inbox, session, message_id):
    d = inbox.message_detail(session, message_id)
    if d is None:
        raise KeyError(message_id)
    verdict = inbox.trust(session, message_id)
    return SimpleNamespace(message_id=message_id, subject=d.subject, sender=d.summary.from_, date=d.summary.date,
                           trust=verdict.api_trust, flags=[f.words for f in verdict.flags], body=d.body)
