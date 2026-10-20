"""The disruption category's rules (BUYER-F 12-right-solution §Disruption), each proved on the seed and on changed data: the rule reads fields
from the records, so another supplier, another date or other wording gives the matching answer, never the seed's."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.domain.attention import option_kinds, options
from app.domain.inbox.model import Message

SLIP = "disruption:SUP-0013"


def _kinds(session, key):
    return {o.kind: o for o in option_kinds.option_kinds(session, key)}


def _fire(session, key):
    return {o.kind: o for o in options.fire_options(session, key) or []}


# D2 · a lead-time cutoff in the supplier's own notice is a route of its own, and an also-start when its date is on or before the act-by

def test_d2_the_cutoff_is_a_way_through_with_its_date_and_the_uncovered_need(session):
    o = _fire(session, SLIP)["order_before"]
    assert o.earliest.date == "2026-10-01" and o.earliest.provenance.method == "extracted"
    assert "16 weeks instead of 8" in o.earliest_basis and o.needs and "no open order covers" in o.needs[0].what
    k = _kinds(session, SLIP)["order_before"]
    assert k.also_start and k.by == "2026-10-01" and k.erp and "8 → 16 weeks" in k.changes


def test_d2_no_cutoff_no_route(session):
    for key in ("disruption:SUP-0001", "incident:SUP-0018", "risk:SUP-0002", "risk:SUP-0029", "risk:SUP-0011"):
        assert "order_before" not in _fire(session, key) and "order_before" not in _kinds(session, key), key


@pytest.mark.parametrize("sentence, order_by, weeks", [
    ("For orders placed on or after October 20, 2026, standard lead time extends from 10 weeks to 20 weeks.", "2026-10-19", "20 weeks instead of 10"),
    ("Orders received from 2026-09-28: lead-time moves from 6 weeks to 12 weeks.", "2026-09-27", "12 weeks instead of 6"),
])
def test_d2_on_changed_data_the_route_follows_the_notice(session, sentence, order_by, weeks):
    m = session.scalar(select(Message).where(Message.identity_id == "SUP-0013", Message.body.like("%lead time extends%")))
    m.body = " ".join(m.body.split()).replace("For orders placed after 1 October 2026, standard lead time extends from 8 weeks to 16 weeks.", sentence)
    session.flush()
    try:
        o = _fire(session, SLIP)["order_before"]
        assert o.earliest.date == order_by and weeks in o.earliest_basis
        k = _kinds(session, SLIP)["order_before"]
        assert k.by == order_by and k.also_start == (order_by <= "2026-10-01")
    finally:
        session.rollback()


def test_d2_a_notice_without_a_cutoff_drops_the_route(session):
    m = session.scalar(select(Message).where(Message.identity_id == "SUP-0013", Message.body.like("%lead time extends%")))
    m.body = " ".join(m.body.split()).replace("For orders placed after 1 October 2026, standard lead time extends from 8 weeks to 16 weeks.", "")
    session.flush()
    try:
        assert "order_before" not in _fire(session, SLIP) and "order_before" not in _kinds(session, SLIP)
    finally:
        session.rollback()


# D5 · a free ask in the same letter: a quote on file from the letter's supplier that lapses before, or within 14 days after, the reply-by

FIRE_LETTER = ("Dear Li Wei,\n\nPlease send us a revised promise date for each line.\n\nPlease reply by 10 October, or as soon as you can.\n\n"
               "Best regards,\nDana Reyes")


def _style(db, body, recipient="li.wei@yunzhan-motor.example"):
    from app.domain.actions.letters import house_style

    return house_style(body, db_path=db, item_key="disruption:SUP-0001", subject="Revised dates", company_short="", recipient=recipient)


def test_d5_the_fire_letter_asks_that_the_lapsing_quote_hold_before_its_reply_by(db_path):
    out = _style(db_path, FIRE_LETTER)
    paras = out.split("\n\n")
    ask = "Please confirm that quote Q-YZ-26-0831 holds past 13 October."
    assert paras.count(ask) == 1 and paras.index(ask) == paras.index(next(p for p in paras if p.startswith("Please reply by"))) - 1
    assert _style(db_path, out) == out                                                         # styled twice, asked once
    assert _style(db_path, FIRE_LETTER, recipient="lin.yuting@jadepeak.example") == FIRE_LETTER   # a supplier with no quote on file: nothing added


def test_d5_on_changed_data_the_ask_follows_the_quote_on_file(db_path, tmp_path):
    import shutil
    import sqlite3

    db = tmp_path / "changed.db"
    shutil.copy(db_path, db)
    con = sqlite3.connect(db)
    con.execute("UPDATE offers SET validity_date = '2026-11-20' WHERE quote_no = 'Q-YZ-26-0831'")          # lapses 41 days after the reply-by: nothing to ask
    con.execute("UPDATE offers SET identity_id = 'SUP-0013', validity_date = '2026-10-20' WHERE quote_no = 'MA-2026-311'")   # another supplier's quote, inside the window
    con.commit()
    con.close()
    assert "Q-YZ-26-0831" not in _style(db, FIRE_LETTER)
    jade = FIRE_LETTER.replace("Li Wei", "Lin Yu-ting")
    assert "Please confirm that quote MA-2026-311 holds past 20 October." in _style(db, jade, recipient="lin.yuting@jadepeak.example")


# D4 · a second source is started beside the supplier ask whenever the supplier is the only source of a part the case hits, or is under 60% on time

@pytest.mark.parametrize("key, kinds, why", [
    ("disruption:SUP-0001", {"second_source"}, "sole source of HR-40130"),
    ("disruption:SUP-0013", {"second_source"}, "sole source of HR-51110"),
    ("incident:SUP-0018", {"second_source"}, "on time on 57% of 73 lines"),
    ("risk:SUP-0029", {"second_source"}, "on time on 26% of 43 lines"),
    ("risk:SUP-0011", {"second_source"}, "on time on 44% of 48 lines"),
    ("risk:SUP-0002", {"second_source"}, "sole source of HR-12210"),
])
def test_d4_second_source_is_an_also_start_on_every_supplier_case(session, key, kinds, why):
    got = {k: o for k, o in _kinds(session, key).items() if k in ("second_source",)}
    assert set(got) == kinds and all(o.also_start and why in o.also_why for o in got.values())


def test_the_suppliers_own_ask_is_always_started_beside_any_route_and_the_other_plant_says_why(session):
    """Khalid: whatever route she picks, the supplier still owes its dates; the other supplier on file is a buy from a second plant, not an allocation."""
    for key, ask in (("disruption:SUP-0001", "allocation"), ("disruption:SUP-0013", "allocation"), ("incident:SUP-0018", "confirm_dates_hold"), ("risk:SUP-0002", "open_terms")):
        o = _kinds(session, key)[ask]
        assert o.also_start and "still owes" in o.also_why, key
    alt = _kinds(session, "disruption:SUP-0001")["alternate_on_file"]
    assert alt.label == "Buy from Siam Motion (HR-40120)" and alt.also_why == "Siam Motion has supplied HR-40120 on a PO before: a second plant for that part"


def test_d4_on_changed_data_a_second_source_on_file_and_a_good_record_drop_it(session):
    from app.domain.orders.model import PoLine

    parts = ["HR-51110", "HR-51120", "HR-51130", "HR-51310", "HR-60110", "HR-60120"]
    others = session.scalars(select(PoLine).where(PoLine.identity_id == "SUP-0019").limit(len(parts))).all()
    for line, part in zip(others, parts):
        line.part_number = part                      # another supplier has now delivered each part: Jadepeak (67% on time) and Vistaray are no longer the only source
    session.flush()
    try:
        assert not _kinds(session, SLIP)["second_source"].also_start
        vista = _kinds(session, "risk:SUP-0029")["second_source"]
        assert vista.also_start and vista.also_why == "on time on 26% of 43 lines"   # still late: started for that reason alone
    finally:
        session.rollback()


def test_the_agent_reads_each_also_start_with_its_reason(session):
    """The specialist's context lists the ways through with code's also-start and reason, so a live run names them; replay reads the same packet."""
    from types import SimpleNamespace as NS

    from app.domain.attention import findings, service
    from app.organism.context_packet import build

    item = service.item_detail(session, SLIP)
    att = NS(options=lambda k: options.fire_options(session, k), option_kinds=lambda k: option_kinds.option_kinds(session, k),
             findings=lambda k: findings.candidates(session, k), list_items=lambda: service.what_needs_attention(session))
    text = build(item, NS(attention=att)).text
    lines = {ln.split(". ", 1)[1].split(" (kind")[0]: ln for ln in text.splitlines() if "(kind " in ln}
    assert "Start it beside the chosen one: order by Oct 1, on or before the act-by." in lines["Order before the lead-time cutoff"]
    assert "Start it beside the chosen one: sole source of HR-51110" in lines["Alternate source"]
    assert "Start it beside the chosen one: Jadepeak still owes revised dates and allocation for the 5 lines" in lines["Allocation request · Jadepeak"]   # the supplier's own ask goes beside any route


# D6 · when stock is the open unknown, the stock check is started beside the chosen route (keyed by the unknown, not the case)

def test_d6_the_stock_check_is_an_also_start_when_stock_is_unknown(session, monkeypatch):
    k = _kinds(session, "consignment:HR-30110")["cm_stock"]
    assert k.also_start and k.also_why == "the records hold no stock of the board or the built part"
    from app.domain.attention import service

    real = service.item_detail
    monkeypatch.setattr(service, "item_detail", lambda s, key: (lambda d: d.model_copy(update={"unknowns": []}) if d is not None and key.startswith("consignment:") else d)(real(s, key)))
    assert not _kinds(session, "consignment:HR-30110")["cm_stock"].also_start      # changed data: stock known, nothing to start
