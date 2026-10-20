"""The dates that live only in email are dated Action-list items with an owner: a supplier's last shipment before its closure, a closure, an old address's last day.
A supplier that has said when it can and cannot ship is not 'no word from the supplier'."""

from __future__ import annotations

import shutil
import sqlite3

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain.attention import service as attention


def _by_key(session):
    return {i.key: i for i in attention.all_items(session)}      # a supplier's dates under its fire are rows of their own by key


def test_meiyas_last_shipment_is_the_top_of_toms_list(session):
    tom = attention.what_needs_attention(session, owner="Tom")
    assert tom[0].key == "deadline:SUP-0042:2026-09-28"
    item = tom[0]
    assert item.title == "Meiya closed Oct 1 to Oct 8: its last shipment before it is Sep 28" and item.owner == "Tom Albrecht" and item.act_by == "2026-09-28" and item.days_left == 3
    assert item.severity == "high" and float(item.at_stake.usd) == 7477.47 and "3 open lines due by Oct 8, 3 already late" in item.at_stake_note
    d = attention.item_detail(session, item.key)
    assert "Meiya is closed Oct 1 to Oct 8" in d.finding and "ship Oct 12" in d.finding and len(d.po_lines) == 3
    assert {n.id for n in d.numbers} >= {"act_by", "closed_from", "closed_to", "closure_open_value:SUP-0042"}


def test_yunzhans_closure_and_bcxs_old_addresses_are_items_with_owners(session):
    items = _by_key(session)
    y = items["deadline:SUP-0001:2026-10-01"]
    assert y.title == "Yunzhan closed Oct 1 to Oct 7" and y.owner == "Dana Reyes" and y.act_by == "2026-10-01" and y.at_stake is None
    assert "No open line falls due in the closure" in attention.item_detail(session, y.key).finding        # its lines are the fire's, not this row's
    b = items["deadline:SUP-0016:2026-12-31"]
    assert "old addresses forward only until Dec 31" in b.title and b.summary == "update the supplier contact" and b.owner == "Priya Nair" and b.severity == "low"
    assert "orders@bcxinterconnect.example" in b.next_action and b.days_left == 97


def test_a_supplier_that_wrote_about_its_closure_is_not_silent(session):
    chase = attention.item_detail(session, "deadline:chase")
    assert not any("SUP-0042" in n.id or "Meiya" in n.label for n in chase.numbers)
    assert chase.title.startswith("16 past-due lines, no updated promise")                      # Meiya's three lines are out


def test_the_dates_are_read_from_the_words_not_typed(db_path, tmp_path):
    """A different closure in a message (another supplier, other dates) becomes the same kind of row."""
    copy = tmp_path / "other.db"
    shutil.copy(db_path, copy)
    con = sqlite3.connect(copy)
    con.execute("update message_events set date_from = '2026-10-05', date_to = '2026-10-09', detail = 'factory closed 2026-10-05 to 2026-10-09' where kind = 'closure' and ref_id = 'SUP-0001'")
    con.commit()
    con.close()
    with Session(create_engine(f"sqlite:///{copy}", future=True)) as s:
        y = _by_key(s)["deadline:SUP-0001:2026-10-05"]
        assert y.title == "Yunzhan closed Oct 5 to Oct 9" and y.days_left == 10
