"""The questions a sheet expects, with an owner, are named unknowns in the item's packet, derived from the data; and the conditions the sheets expect are in the quote tool's output."""

from __future__ import annotations

import shutil
import sqlite3

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain.attention import service as attention
from app.domain.quotes import service as quotes


def asked(unknowns, key: str, owner: str) -> bool:
    """The sheets' rule: a question counts when its owner is right and it shares a word (over three letters) with the key."""
    words = [w for w in key.lower().replace("_", " ").replace("-", " ").split() if len(w) > 3]
    for u in unknowns:
        said = f"{u.what} {u.why_it_blocks} {u.question}".lower().replace("-", " ").replace("_", " ")
        if u.owner == owner and any(w in said for w in words):
            return True
    return False


def test_the_hr40110_tariff_packet_names_the_new_sources_origin_papers_and_no_in_transit_question(session):
    u = attention.item_detail(session, "tariff:HR-40110").unknowns
    assert asked(u, "vinh_phuc_origin_documentation", "Dana") and [x.what for x in u] == ["origin documentation for Vinh Phuc Motor Technology Co., Ltd.'s quote"]
    assert "substantial transformation" in u[0].why_it_blocks
    assert not asked(u, "in_transit_status", "Dana")      # its lines are owed (the plant restarts after Nov 1): nothing rests on the in-transit clause, and a question there would be over-asking


def test_a_part_with_a_conditional_line_names_the_in_transit_question(session):
    u = attention.item_detail(session, "tariff:HR-50110").unknowns
    assert [x.what for x in u] == ["in-transit status", "origin documentation for Quenvara Energy Technology (Huizhou) Co., Ltd.'s quote"]      # and the Penang option's origin papers
    assert "exported before Nov 1 and entered before Dec 1" in u[0].why_it_blocks and {x.owner for x in u} == {"Priya"}


def test_a_quote_from_a_sole_source_in_trouble_names_the_alternative_source(session):
    d = attention.item_detail(session, "deadline:SUP-0002:2026-10-31")
    assert asked(d.unknowns, "alternative_source_for_HR-12210", "Dana") and [u.what for u in d.unknowns] == ["what lapsing costs", "alternative source for HR-12210"]      # the stake is unknown too: no other price is on file
    assert "Schutzschirm" in d.finding and "protective-shield" in d.finding                       # the risk, in the quote's words and the news headline's
    assert not [u for u in attention.item_detail(session, "deadline:SUP-0001:2026-10-13").unknowns if u.what.startswith("alternative source")]      # Yunzhan's quote: no warning from its own quote


def test_a_price_lock_names_what_is_on_hand(session):
    d = attention.item_detail(session, "deadline:SUP-0041:2026-10-15")
    assert asked(d.unknowns, "on_hand_inventory", "Tom")
    between = [u for u in d.unknowns if u.what.startswith("which price an order placed between")]
    assert len(between) == 1 and between[0].owner.startswith("Tom") and "Oct 15 to Nov 1" in between[0].question      # the lock closes before the rise starts: an owned question, not a guess


DB_PATH_HOLDER: dict = {}


@pytest.fixture()
def changed(db_path, tmp_path):
    DB_PATH_HOLDER["path"] = db_path

    def make(*sql: str):
        copy = tmp_path / f"u{abs(hash(sql))}.db"
        shutil.copy(db_path, copy)
        con = sqlite3.connect(copy)
        for q in sql:
            con.execute(q)
        con.commit()
        con.close()
        return Session(create_engine(f"sqlite:///{copy}", future=True))
    return make


def test_the_unknowns_follow_the_data_not_the_item(changed):
    with changed("update tariff_rules set exported_before = null where exported_before is not null") as s:
        assert not asked(attention.item_detail(s, "tariff:HR-50110").unknowns, "in_transit_status", "Priya")        # no in-transit clause, no in-transit question
    with changed("update offers set origin_claim = 'China (Huizhou)' where part_number = 'HR-40110'") as s:
        assert not asked(attention.item_detail(s, "tariff:HR-40110").unknowns, "origin_documentation", "Dana")      # a source that claims the same origin needs no papers
    cols = [r[1] for r in sqlite3.connect(DB_PATH_HOLDER["path"]).execute("pragma table_info(po_lines)")]
    pick = ", ".join(("'HPO-ALT/1'" if c == "id" else "'SUP-0001'" if c in ("identity_id", "record_id") else c) for c in cols)
    with changed(f"insert into po_lines ({', '.join(cols)}) select {pick} from po_lines where part_number = 'HR-12210' limit 1") as s:
        assert not asked(attention.item_detail(s, "deadline:SUP-0002:2026-10-31").unknowns, "alternative_source_for_HR-12210", "Dana")      # a second supplier has bought it: not a sole source


def test_the_conditions_the_sheets_expect_are_in_the_quote_tool_output(session):
    import json

    hall = json.dumps(quotes.compare_offers(session, "HR-12210").model_dump(mode="json"))
    for w in ("protective-shield", "14 weeks", "EXW", "2026-10-31"):
        assert w in hall, w
    bcx = json.dumps(quotes.compare_offers(session, "HR-20133").model_dump(mode="json"))
    for w in ("Tijuana", "DDP", "2027-01-01", "2026-11-30"):
        assert w in bcx, w
    quen = json.dumps(quotes.compare_offers(session, "HR-50110").model_dump(mode="json"))
    for w in ("Penang", "2027-02-01", "customs-broker"):
        assert w in quen, w
