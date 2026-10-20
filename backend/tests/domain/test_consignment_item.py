"""Consigned material that is late reaches every product that contains the part built from it: it is an Action-list item, not only an API record."""

from __future__ import annotations

import shutil
import sqlite3

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain.attention import service as attention
from app.domain.inbox import service as inbox

SLIP = "2026-09-16_Lead_time_update_-_multilayer_PCB_orders_laminate_allocation"
QUOTE = "2026-09-05_RE_Quote_request_-_safety_controller_PCBA_HR-31110_2027_volumes"


def test_the_late_consigned_board_is_an_item_naming_what_it_delays(session):
    item = next(i for i in attention.what_needs_attention(session) if i.key == "consignment:HR-30110")
    assert item.title == "Safety controllers for every robot slip about 3 weeks: consigned PCB late at Lanxin"
    assert item.group == "disruption" and item.severity == "high" and item.category == "Purchasing" and item.owner == "Marcus Chen"
    assert float(item.at_stake.usd) == 12557.9 and "21 days later than promised" in item.at_stake_note and "6 weeks runs from receipt of consigned material" in item.at_stake_note
    d = attention.item_detail(session, item.key)
    for words in ("Lanxin moved 1 open order for the PCB (HR-30110) from Sep 25 to Oct 16, 21 days later", "consigns that board to Alderpoint Electronics", "safety controller (HR-31110)",
                  "goes into every robot", "6 weeks from receipt of consigned material", "about 3 weeks later too"):
        assert words in d.finding, words
    assert {m.ref.id for m in d.messages} == {SLIP, QUOTE} and d.unknowns and d.po_lines
    assert any(n.id == "consigned_slip_days:HR-30110" and float(n.value.value) == 21 for n in d.numbers)


def test_both_mails_link_to_the_item(session):
    for mid in (SLIP, QUOTE):
        item = next(i.key for i in attention.what_needs_attention(session) if any(r.type == "message" and r.id == mid for r in i.refs))
        assert item == "consignment:HR-30110", mid                      # the message's related item (the API shows the first item that names it)
    assert inbox.message_detail(session, SLIP, "consignment:HR-30110").related_item == "consignment:HR-30110"


def test_no_slip_no_item(db_path, tmp_path):
    copy = tmp_path / "noslip.db"
    shutil.copy(db_path, copy)
    con = sqlite3.connect(copy)
    con.execute("delete from message_events where ref_id = 'HPO-26-00629/10' and kind = 'promise_revision'")
    con.commit()
    con.close()
    with Session(create_engine(f"sqlite:///{copy}", future=True)) as s:
        assert not [i for i in attention.what_needs_attention(s) if i.key.startswith("consignment:")]
