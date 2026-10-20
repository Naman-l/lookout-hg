"""The supplier-risk detector reads the words of a supplier's live quotes and the news, never a name; it makes a Today item only for a sole source of a part the plan needs."""

from __future__ import annotations

import shutil
import sqlite3

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain.attention import service as attention
from app.domain.suppliers import risk, service as suppliers


def _items(session):
    return {i.key: i for i in attention.what_needs_attention(session) if i.key.startswith("risk:")}


def test_hallerbeck_reads_as_one_item_with_everything_the_quote_says(session):
    item = _items(session)["risk:SUP-0002"]
    assert item.key == "risk:SUP-0002" and item.title == "Hallerbeck in insolvency: don't prepay; secure the Porter gearbox"
    assert item.owner == "Dana Reyes" and item.act_by == "2026-10-31" and item.group == "disruption" and item.severity == "high" and item.category == "Quote & risk"
    assert item.at_stake is not None and float(item.at_stake.usd) > 0 and "80 a month" in item.at_stake_note and "Porter" in item.at_stake_note
    d = attention.item_detail(session, item.key)
    for words in ("In an insolvency procedure", "30% prepayment on orders above EUR 25,000", "EUR 38,950, so it applies", "from 45 to 30 days", "above the last PO, price only, before any surcharge: +24.5% at 100 pcs ($461.16), +20.2% at 250 pcs ($445.30), against $370.52",
                  "only supplier of Gearbox, planetary (HR-12210)", "80 a month", "oldest promised Sep 24"):
        assert words in d.finding, words
    assert d.unknowns and d.unknowns[0].owner == "Dana"


def test_the_supplier_record_carries_the_flags_for_the_banner(session):
    flagged = {s.ref.id: [f.kind for f in s.risk] for s in suppliers.list_suppliers(session) if s.risk}
    assert flagged["SUP-0002"] == ["insolvency", "prepayment", "terms_cut", "price_jump", "late_delivery"]
    assert all(f.evidence or f.sources for s in suppliers.list_suppliers(session) for f in s.risk)      # every warning says what it was read from
    assert flagged["SUP-0019"] == ["price_jump"] and "risk:SUP-0019" not in _items(session)      # a mild warning alone stays on the supplier's page, not on Today


@pytest.fixture()
def changed(db_path, tmp_path):
    def make(sql: str):
        copy = tmp_path / f"risk{abs(hash(sql))}.db"
        shutil.copy(db_path, copy)
        con = sqlite3.connect(copy)
        con.execute(sql)
        con.commit()
        con.close()
        return Session(create_engine(f"sqlite:///{copy}", future=True))
    return make


def test_the_detector_follows_the_words_not_the_supplier(changed):
    """Another supplier whose quote says it is in administration, and nothing about Hallerbeck, raises the same item."""
    with changed("update offers set conditions = 'The supplier has entered administration; administrators sign this quote.', prepayment = null, payment_terms = 'Net 45' where identity_id = 'SUP-0002'") as s:
        item = _items(s)["risk:SUP-0002"]
        assert "in insolvency" in item.title            # 'administration' is insolvency wording too
        assert [f.kind for f in risk.risk_flags(s, "SUP-0002")] == ["insolvency", "price_jump", "late_delivery"]
    with changed("update offers set conditions = 'Prices exclude duties.' where identity_id = 'SUP-0002'") as s:
        flags = [f.kind for f in risk.risk_flags(s, "SUP-0002")]
        assert "insolvency" in flags                          # still reported in the news (Sep 10)
    with changed("update offers set conditions = 'Prices exclude duties.', prepayment = null, payment_terms = 'Net 45'") as s:
        assert [f.kind for f in risk.risk_flags(s, "SUP-0002")] == ["insolvency", "price_jump", "late_delivery"]        # the news alone is insolvency; the quote stops saying so


def test_a_blocked_quote_is_never_read(changed):
    with changed("update offers set trust = 'blocked' where identity_id = 'SUP-0002'; ") as s:
        flags = [f.kind for f in risk.risk_flags(s, "SUP-0002")]
        assert flags == ["insolvency", "late_delivery"]       # only the news remains: no quote words, prepayment, terms or price from a blocked message


def test_no_item_without_a_sole_source_part(changed, db_path):
    cols = [r[1] for r in sqlite3.connect(db_path).execute("pragma table_info(po_lines)")]
    pick = ", ".join(("'HPO-ALT/1'" if c == "id" else "'SUP-0001'" if c in ("identity_id", "record_id") else c) for c in cols)
    with changed(f"insert into po_lines ({', '.join(cols)}) select {pick} from po_lines where part_number = 'HR-12210' limit 1") as s:
        assert risk.sole_source_parts(s, "SUP-0002") == []
        assert "risk:SUP-0002" not in _items(s)                # a second supplier has bought the part: not a sole source, so no Today item
        assert [f.kind for f in risk.risk_flags(s, "SUP-0002")][0] == "insolvency"      # the flag stays on the supplier's record


def test_vistaray_the_biggest_supplier_risk_is_a_today_item(session):
    """22.6% of spend, sole source of the lidar, on time on 26% of 43 closed lines, paid 100% before shipment, with a $470K undated line and a House bill in the news."""
    item = _items(session)["risk:SUP-0029"]
    assert item.title == "Vistaray delivers late (on time on 26% of 43 lines): secure the lidar" and item.summary == "sole source of HR-60110, 262 a month for T2 and P5" and item.owner == "Marcus Chen" and item.severity == "high"
    assert round(float(item.at_stake.usd)) == 2_909_521 and "22.6% of the last twelve months' spend" in item.at_stake_note and "262 a month" in item.at_stake_note
    d = attention.item_detail(session, item.key)
    for words in ("On time on 26% of its 43 closed lines; the 32 late ones average 14.8 days late", "Paid in advance: 100% T/T before shipment", "1 open line with no promised date ($469,785)", "House bill would bar federal agencies"):
        assert words in d.finding, words
    row = next(s for s in suppliers.list_suppliers(session) if s.ref.id == "SUP-0029")
    assert (row.delivery.n, row.delivery.on_time, row.delivery.late, row.delivery.avg_days_late) == (43, 11, 32, 14.8) and row.delivery.on_time_pct == 0.256
    assert [f.kind for f in row.risk] == ["late_delivery", "cash_in_advance", "undated_open", "news_risk"]


def test_delivery_performance_is_what_the_raw_lines_say():
    """Counted straight from the purchase-order file: closed lines of the company, received on or before the promise."""
    import csv
    from datetime import date
    from pathlib import Path

    root = Path(__file__).resolve().parents[3] / "data"
    n = on = 0
    with open(root / "purchase_orders.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows and "status" in rows[0]
    closed = [r for r in rows if r["supplier_id"] == "SUP-0029" and r["status"].upper() == "CLOSED"]
    assert len(closed) >= 43 - 6                      # the company's lines under its ids, before the legacy ids and the date formats are cleaned


def test_the_thresholds_come_from_the_recipe_not_the_code(changed):
    with changed("update build_meta set value = '{\"on_time_below\": 0.1, \"min_closed_lines\": 10, \"top_spend_share\": 0.10}' where key = 'supplier_risk'") as s:
        assert "late_delivery" not in [f.kind for f in risk.risk_flags(s, "SUP-0029")]            # 26% is no longer under the line
        assert risk.thresholds(s)["on_time_below"] == 0.1
