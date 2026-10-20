"""Entity annotation: the things a text mentions, matched against the records, deterministic. Ambiguous matches are dropped, never guessed."""

from __future__ import annotations

import pytest

from app.domain.annotate import service as annotate
from app.domain.attention import service as attention
from app.domain.inbox import service as inbox

FM = "2026-09-22_NOTICE_OF_FORCE_MAJEURE_-_Shenzhen_Yunzhan_Precision_Motor_Co_Ltd"
FRAUD = "2026-09-23_URGENT_Updated_remittance_details_following_plant_incident"


def js_slice(text: str, start: int, end: int) -> str:
    """What JavaScript's text.slice(start, end) returns: indices count UTF-16 code units."""
    units = text.encode("utf-16-le")
    return units[2 * start:2 * end].decode("utf-16-le")


def by(spans, type_):
    return [s for s in spans if s.type == type_]


def test_the_force_majeure_notice_is_read_against_the_records(session):
    d = inbox.message_detail(session, FM)
    spans = d.entities
    assert all(js_slice(d.body, s.start, s.end) == s.text for s in spans)            # offsets are JavaScript string indices
    parts = {s.ref: s.label for s in by(spans, "part")}
    assert parts["HR-40110"] == "Motor, BLDC (HR-40110) · Tern" and parts["HR-40210"].endswith("· Porter") and "HR-40130" in parts
    assert {s.ref for s in by(spans, "supplier")} == {"SUP-0001"} and any(s.text.startswith("Shenzhen Yunzhan") for s in by(spans, "supplier"))      # the longest name wins
    assert {"2026-09-18", "2026-10-10", "2026-08-25"} <= {s.ref for s in by(spans, "date")}
    assert any(s.type == "person" and s.ref.endswith("/Li Wei") and s.label == "Li Wei (Yunzhan)" for s in spans)
    assert {s.ref for s in by(spans, "person") if "/" not in s.ref} >= {"Dana", "Sofia"}                                                          # buyers
    assert [s.ref for s in d.subject_entities] == ["SUP-0001"] and d.subject_entities[0].text.startswith("Shenzhen Yunzhan")
    assert all(a.end <= b.start for a, b in zip(spans, spans[1:]))                                                                            # nothing overlaps


def test_the_fraud_mails_look_alike_sender_is_never_the_supplier(session):
    from app.domain.inbox.model import Message

    d = inbox.message_detail(session, FRAUD)
    address = session.get(Message, FRAUD).from_email
    sender = annotate.annotate(session, address)
    assert [(s.type, s.ref) for s in sender] == [("supplier_lookalike", address)]
    assert "SUP-0001" not in sender[0].ref and "imitates Yunzhan's domain, not Yunzhan" in sender[0].label
    assert not any(s.type == "supplier" and s.text == address for s in d.entities)
    money = by(d.entities, "money")
    assert money and money[0].ref == "USD 187420.00" and money[0].label == "USD 187,420"
    real = annotate.annotate(session, "li.wei@yunzhan-motor.example")
    assert [(s.type, s.ref) for s in real] == [("supplier", "SUP-0001")]                      # the real address is the supplier's


def test_two_parts_that_share_a_description_are_resolved_by_number_only(session):
    assert annotate.annotate(session, "We need the Motor, BLDC for October.") == []         # HR-40110 (Tern) and HR-40210 (Porter) are both 'Motor, BLDC': not guessed
    (one,) = annotate.annotate(session, "Motor, BLDC (HR-40210) is late.")
    assert (one.type, one.ref, one.text) == ("part", "HR-40210", "Motor, BLDC (HR-40210)") and one.label.endswith("· Porter")        # the label and the number are one mention
    two = annotate.annotate(session, "HR-40110 and HR-40210")
    assert [(s.ref, s.label.rsplit("· ", 1)[1]) for s in two] == [("HR-40110", "Tern"), ("HR-40210", "Porter")]
    (unique,) = annotate.annotate(session, "GEARBOX, PLANETARY, 20:1, 120 MM FRAME, HEAVY DUTY, PORTER DRIVE")
    assert unique.ref == "HR-12210"                                                              # a description only one part has is found by it


def test_po_lines_money_dates_and_quantities(session):
    text = "PO 450/10 and HPO-26-00450/20 on Oct 13, 2026, 13 October, EUR 38,950 or $1.5M, 1,140 pcs and 364 robots."
    spans = annotate.annotate(session, text)
    got = [(s.type, s.ref, s.text) for s in spans]
    assert ("po_line", "HPO-26-00450/10", "PO 450/10") in got and ("po_line", "HPO-26-00450/20", "HPO-26-00450/20") in got
    assert ("date", "2026-10-13", "Oct 13, 2026") in got and ("date", "2026-10-13", "13 October") in got
    assert ("money", "EUR 38950.00", "EUR 38,950") in got and ("money", "USD 1500000.00", "$1.5M") in got
    assert ("quantity", "1140 pcs", "1,140 pcs") in got and ("quantity", "364 robots", "364 robots") in got
    assert annotate.annotate(session, "PO 999/99 and HPO-26-99999/10 and 2026-13-45") == []        # not in the records, or not a date


def test_offsets_are_utf16_code_units(session):
    text = "📦 HR-40110 → 2026-10-13"
    spans = annotate.annotate(session, text)
    assert [(s.type, s.start, s.end) for s in spans] == [("part", 3, 11), ("date", 14, 24)]      # the emoji is two units, so a code-point index would be off by one
    assert all(js_slice(text, s.start, s.end) == s.text for s in spans)


def test_the_longest_match_wins_and_names_resolve_to_one_record(session):
    (s,) = annotate.annotate(session, "Shenzhen Yunzhan Precision Motor Co., Ltd.")
    assert (s.type, s.ref, s.text) == ("supplier", "SUP-0001", "Shenzhen Yunzhan Precision Motor Co., Ltd.")
    assert [(x.type, x.ref) for x in annotate.annotate(session, "ask Yunzhan about it")] == [("supplier", "SUP-0001")]
    assert annotate.annotate(session, None) == [] and annotate.annotate(session, "") == [] and annotate.annotate(session, "nothing here to find") == []


def test_entities_sit_beside_every_text_the_screens_show(session):
    items = attention.what_needs_attention(session)
    fire = next(i for i in items if i.key == "disruption:SUP-0001")
    assert any(s.type == "supplier" and s.ref == "SUP-0001" for s in fire.title_entities) and all(js_slice(fire.title, s.start, s.end) == s.text for s in fire.title_entities)
    assert fire.next_action_entities and all(js_slice(fire.next_action, s.start, s.end) == s.text for s in fire.next_action_entities)
    d = attention.item_detail(session, fire.key)
    assert any(s.type == "part" for s in d.finding_entities) and all(js_slice(d.finding, s.start, s.end) == s.text for s in d.finding_entities)


def test_a_draft_carries_entities_beside_its_subject_and_body(db_path, tmp_path, monkeypatch):
    import shutil

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app import db as app_db
    from app.domain.actions import api as actions_api, ledger
    from app.domain.common import EntityRef

    copy = tmp_path / "draft.db"
    shutil.copy(db_path, copy)
    monkeypatch.setattr(app_db, "DB_PATH", copy)
    a = ledger.propose(copy, type="supplier_request", item_key="disruption:SUP-0001", run_id="r1", target=EntityRef(type="supplier", id="SUP-0001"), recipient="li.wei@yunzhan-motor.example",
                       subject="Revised dates for HPO-26-00450/10", body="Li Wei, please confirm HR-40110 by 2026-10-10.")
    app = FastAPI()
    app.include_router(actions_api.router, prefix="/api")
    got = TestClient(app).get(f"/api/actions/{a.action_id}").json()
    assert [(s["type"], s["ref"]) for s in got["subject_entities"]] == [("po_line", "HPO-26-00450/10")]
    assert [(s["type"], s["ref"]) for s in got["body_entities"]] == [("person", "SUP-0001/Li Wei"), ("part", "HR-40110"), ("date", "2026-10-10")]


def test_durations(session):
    got = [(s.type, s.ref, s.text, s.label) for s in annotate.annotate(session, "partial production resumes in 6 to 8 weeks; the quote holds 60 days; 21 days later; 1 week; 4-6 wks")]
    assert ("duration", "6-8 weeks", "6 to 8 weeks", "6 to 8 weeks") in got and ("duration", "60 days", "60 days", "60 days") in got
    assert ("duration", "21 days", "21 days", "21 days") in got and ("duration", "1 week", "1 week", "1 week") in got and ("duration", "4-6 weeks", "4-6 wks", "4 to 6 weeks") in got
    assert annotate.annotate(session, "HR-40110 x 21 pcs on 2026-10-13") and not [s for s in annotate.annotate(session, "HR-40110 x 21 pcs on 2026-10-13") if s.type == "duration"]


SPOT = "2026-09-12_Spot_offer_-_NG6603-QFN48_in_stock_ships_today"
VINH = "2026-09-24_Quotation_VPM-Q-260924_-_BLDC_motor_equivalent_to_YZ-BL86-48-400"


def real_refs(spans):
    return [s for s in spans if s.type in ("supplier", "person") and (s.ref.startswith("SUP-") or "/" in s.ref)]


def test_a_held_message_names_claims_never_records(session):
    d = inbox.message_detail(session, FRAUD)
    spans = d.subject_entities + d.entities
    assert not [s for s in spans if "SUP-0001" in s.ref]                                  # nothing in the fraud mail resolves to the real Yunzhan
    claimed = [s for s in spans if s.type == "supplier_claimed"]
    assert [(s.text, s.label) for s in claimed] == [("Shenzhen Yunzhan Precision Motor Co., Ltd.", "claimed: Yunzhan (unverified)")] and claimed[0].ref.startswith("claimed:")
    assert "Yunzhan Precision (HK) Trading Ltd" not in " ".join(s.text for s in spans)      # the beneficiary is not a supplier
    assert not [s for s in spans if s.start >= d.body.index("Beneficiary") and s.end <= d.body.index("Please update")]       # nor is any line of the bank details
    assert real_refs(spans) == []


def test_the_spot_offers_names_are_claims_and_its_mpn_is_the_part(session):
    d = inbox.message_detail(session, SPOT)
    spans = d.subject_entities + d.entities
    assert real_refs([s for s in spans if s.type == "supplier"]) == [] and all(s.type != "supplier" for s in spans)
    assert any(s.type == "supplier_claimed" and s.label == "claimed: Saltmarsh Components (unverified)" for s in spans)
    mpn = [s for s in spans if s.type == "part"]
    assert mpn and {s.ref for s in mpn} == {"HR-32104"} and all(s.label.endswith("· by MPN") for s in mpn)


def test_an_incoterm_place_and_a_city_are_not_companies(session):
    assert annotate.annotate(session, "FOB Hai Phong") == [] and annotate.annotate(session, "shipped FOB Shenzhen, then DDP Reno") == []
    assert annotate.annotate(session, "Hai Phong") == []                                   # a city alone is a place, not Hai Phong Precision
    assert [(s.type, s.ref) for s in annotate.annotate(session, "Hai Phong Precision Industries")] == [("supplier", "SUP-0054")]      # the company by its own name still resolves
    d = inbox.message_detail(session, VINH)
    assert not [s for s in d.entities if s.type in ("supplier", "supplier_claimed") and "Hai Phong" in s.text]


def test_supplier_model_numbers_resolve_through_the_parts_mpn(session):
    got = {(s.text, s.ref) for s in annotate.annotate(session, "JPD300-48S24, JPD150-48S12, JPD60-48S05 and JPA1000-48D; drop-in equivalent to YZ-BL86-48-400; NG6603-QFN48")}
    assert got == {("JPD300-48S24", "HR-51110"), ("JPD150-48S12", "HR-51120"), ("JPD60-48S05", "HR-51130"), ("JPA1000-48D", "HR-51310"), ("YZ-BL86-48-400", "HR-40110"), ("NG6603-QFN48", "HR-32104")}
    (one,) = annotate.annotate(session, "YZ-BL86-48-400")
    assert one.label == "Motor, BLDC (HR-40110) · Tern · by MPN"


def test_a_trust_item_names_claims_too(session):
    item = next(i for i in attention.what_needs_attention(session) if i.key.startswith("trust:2026-09-23"))
    assert not [s for s in item.title_entities + item.next_action_entities if "SUP-0001" in s.ref]
    assert not [s for s in attention.item_detail(session, item.key).finding_entities if "SUP-0001" in s.ref]
    held = annotate.annotate(session, "Shenzhen Yunzhan Precision Motor Co., Ltd., Li Wei, li.wei@yunzhan-motor.example", held=True)
    assert {s.type for s in held} == {"supplier_claimed"} and not [s for s in held if s.type == "person"]       # a contact's name in a held message is not matched either

