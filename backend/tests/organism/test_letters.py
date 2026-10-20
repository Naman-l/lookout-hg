"""BUYER R2 final: the letter a buyer signs is in house style whether the clerk staged it live or a recording was replayed."""

import sqlite3

from app.domain.actions.letters import house_style, reservation

FIRE = "Dear Li Wei,\n\nPlease confirm revised dates for 1320 EA on HPO-26-00450/10.\n\nRegards,\nDana Reyes"


def _db(tmp_path):
    db = str(tmp_path / "l.db")
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE parts (part_number TEXT, description TEXT)")
        con.execute("CREATE TABLE supplier_records (contact_name TEXT, contact_email TEXT)")
        con.execute("INSERT INTO supplier_records VALUES ('Wang Fang', 'wang.fang@q.example')")
        con.executemany("INSERT INTO parts VALUES (?, ?)", [("HR-72101", "Corner bracket, 20 series, zinc"), ("HR-72130", "Corner bracket, 40 series, zinc")])
    return db


def test_quantities_read_with_their_thousands_separator_and_years_or_ids_do_not():
    out = house_style(FIRE)
    assert "1,320 EA" in out and "HPO-26-00450/10" in out and house_style("in 2026, 445 EA") == "in 2026, 445 EA"


def test_a_force_majeure_letter_keeps_the_reservation_of_rights_once():
    out = house_style(FIRE, item_key="disruption:SUP-0001", subject="Force majeure notice: revised dates", company_short="Acme")
    assert reservation("Acme") in out and out.index(reservation("Acme")) < out.index("Regards,")                  # above the sign-off
    assert house_style(out, item_key="disruption:SUP-0001", subject="Force majeure notice", company_short="Acme").count("waives") == 1
    assert "waives" in house_style(FIRE, item_key="incident:SUP-0018", subject="Your notice: new dates", company_short="Acme")   # any notice answered reserves rights (BUYER R1)
    assert "waives" in house_style(FIRE, item_key="disruption:SUP-0013", subject="Allocation notice", company_short="Acme")
    assert "waives" not in house_style(FIRE, item_key="deadline:chase", subject="Ship date please", company_short="Acme")   # no notice answered, no insolvency on file


def test_an_added_ask_is_its_own_paragraph_without_also_please_also():
    body = "Dear H,\n\nA ship date please.\n\nAlso: Please also send the certificate of origin.\n\nRegards,\nTom"
    assert "\n\nPlease send the certificate of origin." in house_style(body) and "Also" not in house_style(body)


def test_a_part_number_carries_its_name_unless_the_name_is_beside_it(tmp_path):
    db = _db(tmp_path)
    out = house_style("HPO-26-00675/10 (70 EA, HR-72101, promised 25 September). Corner bracket, 40 series (HR-72130) · 721 EA", db_path=db)
    assert "Corner bracket, 20 series (HR-72101)" in out and out.count("Corner bracket, 40 series") == 1


async def test_a_replayed_recording_is_staged_in_house_style(tmp_path):
    from app.domain.actions import ledger
    from app.organism import recordings
    from app.organism.runs import store
    from app.organism.runs.events import Recorder

    db = tmp_path / "r.db"
    store.connect(db).close()
    doc = {"run_id": "run-old", "item_key": "disruption:SUP-0001", "recorded_at": "2026-10-14T00:00:00+00:00",
           "run": {"model": "m", "prompt_hash": "p", "toolset_hash": "t", "sdk_version": "s"}, "events": [], "recommendation": None, "verifier": None,
           "actions": [{"action_id": "A-old", "type": "supplier_request", "item_key": "disruption:SUP-0001", "target": None, "recipient": "li@y.example",
                        "subject": "Force majeure notice: revised dates", "body": FIRE, "change": None}]}
    await recordings.replay(doc, db_path=db, run_id="run-r", recorder=Recorder("run-r", db), speed=1000.0, max_gap_s=0)
    body = next(a for a in ledger.list_actions(str(db)) if a.type == "supplier_request").body
    assert "1,320 EA" in body and "waives any of" in body


def test_a_letter_to_a_contact_on_file_opens_with_the_contact_s_name(tmp_path):
    """AGENT-EXPERT on 5a5bc44: the quotes letters opened 'Dear <supplier> team,' with the contact on file."""
    db = _db(tmp_path)
    body = "Dear Quenvara Energy team,\n\nPlease extend the quote.\n\nRegards,\nDana"
    assert house_style(body, db_path=db, recipient="wang.fang@q.example").startswith("Dear Wang Fang,\n")
    assert house_style(body, db_path=db, recipient="nobody@x.example").startswith("Dear Quenvara Energy team,")   # no contact on file: the team stays


def test_a_reply_asked_for_on_the_day_a_quote_lapses_is_asked_for_a_week_before(tmp_path):
    """BUYER 02: 'Please reply by 31 October' when quote AN-2026-1187 lapses on 31 October left no time to act on the answer."""
    db = _db(tmp_path)
    body = "Dear Katrin Vogel,\n\nDo the prices hold before the quote lapses on 31 October?\n\nPlease reply by 31 October, and sooner if you can.\n\nRegards,\nDana"
    assert "Please reply by 24 October, and sooner" in house_style(body, db_path=db)
    early = body.replace("Please reply by 31 October", "Please reply by 9 October")
    assert house_style(early, db_path=db) == early   # already before the lapse: unchanged
    no_quote = body.replace("before the quote lapses on 31 October", "soon")
    assert house_style(no_quote, db_path=db) == no_quote   # no lapse named: unchanged
