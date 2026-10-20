"""The verifier reads the robots' names from the products table, not from the code."""

import re
import shutil
import sqlite3
from types import SimpleNamespace

from app.organism import services as organism_services
from app.organism.verifier import binding_failures, product_pattern

OLD = re.compile(r"\b(Tern|Porter|Heron)\b")  # what the verifier hard-coded before: the pattern from the table must behave the same on this data
SENTENCES = ["The Tern needs 364 in October.", "Porter P5 and Heron H1 builds are short.", "A Tern T2 motor, the Porter's brake and a Heron arm.", "Nothing about robots here.", "Ternary logic and heroic efforts."]


def test_the_pattern_built_from_the_real_products_table_equals_the_old_one_on_this_data(db_path, monkeypatch):
    monkeypatch.delenv("LOOKOUT_FAKE_SERVICES", raising=False)  # the organism tests set it; this one must read the real table
    svc = organism_services.get(str(db_path))
    try:
        assert sorted(svc.bom.product_families()) == ["Heron", "Porter", "Tern"]
        rx = product_pattern(svc)
        for text in SENTENCES:
            assert [m.group(1) for m in rx.finditer(text)] == [m.group(1) for m in OLD.finditer(text)], text
    finally:
        svc.close()


def test_a_renamed_product_is_picked_up_and_the_old_name_is_dropped(db_path, tmp_path, monkeypatch):
    monkeypatch.delenv("LOOKOUT_FAKE_SERVICES", raising=False)
    changed = tmp_path / "renamed.db"
    shutil.copy(db_path, changed)
    with sqlite3.connect(changed) as con:
        con.execute("UPDATE products SET family = 'Kestrel' WHERE family = 'Heron'")
    svc = organism_services.get(str(changed))
    try:
        rx = product_pattern(svc)
        assert [m.group(1) for m in rx.finditer("The Kestrel arm and the Tern, not the Heron.")] == ["Kestrel", "Tern"]
    finally:
        svc.close()


def test_binding_uses_whatever_robots_the_table_names():
    """'364' is a Tern number: said of a Kestrel it fails when the table says Kestrel is a robot, and is not a robot claim when it does not."""
    from app.organism.context import RunContext
    from app.organism.runs.events import Recorder
    from app.organism.schemas import Number
    from decimal import Decimal

    ctx = RunContext(run_id="r", item_key="k", db_path="x", recorder=Recorder("r", "x"), plan=[], allow={})
    ctx.register([Number(id="shortage:HR-40110:2026-10:short", name="Units short for the Tern T2", value=Decimal(364), unit="EA")])
    services = lambda fams: SimpleNamespace(bom=SimpleNamespace(product_families=lambda: fams, where_used=lambda part: []))
    assert binding_failures(ctx, "The Kestrel needs 364.", services(["Tern", "Kestrel"])) != []
    assert binding_failures(ctx, "The Kestrel needs 364.", services(["Tern"])) == []


def test_the_owners_of_a_real_item_are_read_from_the_action_list(db_path):
    from app.domain.actions import approvers

    assert approvers.owners_of(db_path, "deadline:SUP-0041:2026-10-15") == {"Tom Albrecht"}
    assert approvers.owners_of(db_path, "tariff:all") == {"Priya Nair", "Dana Reyes"}  # two owners: either may sign


def test_a_reply_to_a_contact_on_file_still_reaches_the_clerk_and_may_stage(db_path, monkeypatch):
    """O5: the unvetted-sender stop must not catch Li Wei (Yunzhan's contact on file). Real data: every message from a sender on file keeps the clerk in its plan; only the new sender and the look-alike lose it."""
    monkeypatch.delenv("LOOKOUT_FAKE_SERVICES", raising=False)
    from app.organism import services as organism_services
    from app.organism.workflows.work_item import _message_item, run_plan, sender_is_vetted

    svc = organism_services.get(str(db_path))
    try:
        fm = next(m.ref.id for m in svc.inbox.list_messages() if "FORCE_MAJEURE" in m.ref.id)
        assert svc.inbox.trust(fm).api_trust == "on_file" and sender_is_vetted("reply:" + fm, svc)
        assert run_plan(_message_item("reply:" + fm, svc), svc) == ["inbox_analyst", "buyers_clerk"]
        for m in svc.inbox.list_messages():
            plan = run_plan(_message_item("reply:" + m.ref.id, svc), svc)
            t = svc.inbox.trust(m.ref.id)
            assert ("buyers_clerk" in plan) == (t.api_trust == "on_file" and t.verdict == "ok"), m.ref.id
    finally:
        svc.close()


def test_only_the_promised_dates_item_waits_for_its_trigger_date(db_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.domain.attention import service

    with Session(create_engine(f"sqlite:///{db_path}")) as s:
        items = {i.key: i for i in service.all_items(s)}
    waits = {k: i.waits_until for k, i in items.items() if i.waits_until}
    assert waits == {"deadline:SUP-0001:2026-10-10": "2026-10-10"}  # the quote expiry and the price lock are acted on before their dates, not waited for


async def test_the_no_key_morning_run_on_a_fresh_database_stages_one_draft_to_the_supplier_contact(db_path, tmp_path, monkeypatch):
    """FEEDBACK 8.1/8.3: the saved morning runs staged three drafts to one contact, one chasing dates not yet due."""
    import shutil

    from app.domain.actions import ledger
    from app.organism import prepare as pr

    monkeypatch.delenv("LOOKOUT_FAKE_SERVICES", raising=False)
    monkeypatch.setenv("LOOKOUT_MODE", "recorded")
    monkeypatch.delenv("LOOKOUT_MORNING_ITEMS", raising=False)
    fresh = tmp_path / "fresh.db"
    shutil.copy(db_path, fresh)
    from app.organism.runs import store

    store.connect(fresh).close()
    for table in ("actions", "outbox", "run_actions"):
        try:
            import sqlite3

            with sqlite3.connect(fresh) as con:
                con.execute(f"DELETE FROM {table}")
        except Exception:  # noqa: BLE001  a table this build has not created yet
            pass
    await pr.prepare(db_path=fresh)
    drafts = [a for a in ledger.list_actions(fresh) if a.type == "supplier_request" and a.recipient and a.recipient.startswith("li.wei")]
    assert len(drafts) == 1, [(a.action_id, a.item_key) for a in drafts]
    assert "have not yet received" not in (drafts[0].body or "")


def test_a_quote_message_is_planned_with_the_tariff_and_sourcing_analysts_and_other_messages_are_not(db_path, monkeypatch):
    """FEEDBACK 6.5 (run-6dd3604d): 'What does this mean?' on the battery-pack quote said freight, duty and landed cost are unknown; no tariff call was made."""
    from app.organism.workflows.work_item import build_prompt, prices_something, run_plan

    monkeypatch.delenv("LOOKOUT_FAKE_SERVICES", raising=False)
    svc = organism_services.get(str(db_path))
    try:
        items = {i.key: i for i in svc.attention.list_items()}
        msgs = {m.ref.id: m for m in svc.inbox.list_messages()}
        quotes = [k for k in (f"triage:{m.ref.id}" for m in msgs.values() if (m.kind or "") == "quote")]
        assert quotes, "the data has quote messages"
        # the item for a quote message, whichever of triage/reply the app builds, carries the extra analysts
        class Item:
            def __init__(self, key): self.key, self.group, self.owner, self.title, self.refs, self.waits_until = key, "triage", "x", "t", [], None
        sup = next(k for k in quotes if svc.inbox.trust(k.split(":", 1)[1]).api_trust == "on_file")
        plan = run_plan(Item(sup), svc)
        assert plan == ["inbox_analyst", ["tariff_analyst", "sourcing_analyst"], "buyers_clerk"] and prices_something(sup, svc)
        assert "landed cost per site" in build_prompt(Item(sup), plan=plan)
        other = next(f"triage:{m.ref.id}" for m in msgs.values() if (m.kind or "") not in ("quote", "price change") and svc.inbox.trust(m.ref.id).api_trust == "on_file")
        assert run_plan(Item(other), svc) == ["inbox_analyst", "buyers_clerk"]
    finally:
        svc.close()


def test_the_server_attaches_real_spans_to_an_answer(db_path, monkeypatch):
    from app.organism import entities
    from app.organism.schemas import Point, Recommendation

    monkeypatch.delenv("LOOKOUT_FAKE_SERVICES", raising=False)
    svc = organism_services.get(str(db_path))
    try:
        rec = entities.attach(Recommendation(finding="Order the drive motors from Yunzhan by 2026-10-13.", numbers=[], points=[Point(label="Short", text="HR-40110 is short in October.")]), svc._session)
    finally:
        svc.close()
    kinds = {s["type"] for s in rec.answer_entities}
    assert "date" in kinds and rec.points[0].entities and all(s["text"] for s in rec.answer_entities + rec.points[0].entities)


def _conditions_for(db_path, part, monkeypatch, tmp_path):
    import asyncio
    import json

    from app.domain.quotes import tools as quote_tools
    from app.organism.carry import conditions_from_compare
    from app.organism.context import RunContext
    from app.organism.runner import allow_map
    from app.organism.runs.events import Recorder

    monkeypatch.delenv("LOOKOUT_FAKE_SERVICES", raising=False)
    svc = organism_services.get(str(db_path))
    try:
        ctx = RunContext(run_id="run-c", item_key="x", db_path=str(tmp_path / "c.db"), recorder=Recorder("run-c", str(tmp_path / "c.db")), plan=["sourcing_analyst"], allow=allow_map(["sourcing_analyst"]))
        tool = quote_tools.make_tools(ctx, svc.quotes)[0]
        out = asyncio.run(tool.handler({"part_number": part}))
        return conditions_from_compare(json.loads(out["content"][0]["text"])["data"])
    finally:
        svc.close()


def test_carry_through_holds_the_conditions_the_round_9_answers_left_out(db_path, tmp_path, monkeypatch):
    """Round 9: the Hallerbeck answer dropped the insolvency process, 14 weeks and EXW; the Quenvara one dropped Penang and its start date."""
    from app.organism.carry import missing

    hall = _conditions_for(db_path, "HR-12210", monkeypatch, tmp_path)
    texts = " ".join(c["text"] for c in hall.values())
    assert "EXW" in texts and "14 weeks" in texts and "protective-shield insolvency" in texts and "30% on orders above" in texts
    bare = "The supplier sent a new quote."
    gone = missing(hall, bare)
    assert any("EXW" in t for t in gone) and any("insolvency" in t for t in gone) and any("14 weeks" in t for t in gone)
    assert missing(hall, "Quote is EXW, 14 weeks, valid until 2026-10-31, prepayment on large orders, Net 30, a material surcharge of 3.5% on the net value, a protective-shield insolvency procedure with a court-appointed monitor; prices exclude duties.") == []
    assert missing(hall, bare) == gone == missing(dict(reversed(list(hall.items()))), bare)  # the same conditions in the same order on every trial
    quen = _conditions_for(db_path, "HR-50110", monkeypatch, tmp_path)
    qt = " ".join(c["text"] for c in quen.values())
    assert "customs-broker determination" in qt and any("2027" in c["text"] or "February" in c["text"] for c in quen.values())


def test_the_suppliers_owed_a_request_are_listed_by_code_from_the_items_lines(db_path, monkeypatch):
    """FEEDBACK: the chase covers 16 past-due lines across a dozen suppliers and four buyers; the clerk drafted for three. Every (supplier, owner) is listed by code from the item's own lines."""
    from app.organism.workflows.work_item import suppliers_owed

    monkeypatch.delenv("LOOKOUT_FAKE_SERVICES", raising=False)
    svc = organism_services.get(str(db_path))
    try:
        items = {k: svc.attention.get_item(k) for k in ("deadline:chase", "unknown:undated")}
        items["disruption:SUP-0001"] = svc.attention.get_item("disruption:SUP-0001")
        chase, undated = suppliers_owed(items["deadline:chase"], svc, str(db_path)), suppliers_owed(items["unknown:undated"], svc, str(db_path))
        lines = [n for n in items["deadline:chase"].numbers if n.id.startswith("chase:HPO")]
        assert 6 <= len(chase) < len(lines) and "SUP-0010" in chase  # F102 (AGENT-EXPERT + BUYER): the 5 largest lines' suppliers and each owner's oldest line, not all 11 (the clerk ran out of turns); Xinda is Dana's oldest
        assert {o for o in chase.values() if o} >= {"Dana Reyes", "Marcus Chen", "Priya Nair", "Tom Albrecht"}  # every buyer who owns lines is represented
        assert set(undated) <= {r.id for r in items["unknown:undated"].refs if r.type == "supplier"} and len(undated) == 5
        assert suppliers_owed(items["disruption:SUP-0001"], svc, str(db_path)) == {}  # other kinds have no owed list
    finally:
        svc.close()


def test_a_city_written_beside_a_supplier_must_be_one_of_its_places(db_path, tmp_path, monkeypatch):
    """Review: the compare answer said 'Quenvara's Shenzhen quote' when the offer's site is Huizhou."""
    from app.organism.context import RunContext
    from app.organism.runner import allow_map
    from app.organism.runs.events import Recorder
    from app.organism.verifier import place_claim_failures

    ctx = RunContext(run_id="run-p", item_key="x", db_path=str(db_path), recorder=Recorder("run-p", str(tmp_path / "p.db")), plan=["sourcing_analyst"], allow=allow_map(["sourcing_analyst"]))
    assert any("names Shenzhen" in f for f in place_claim_failures("Quenvara's Shenzhen quote is valid until November.", ctx))
    assert not place_claim_failures("Quenvara's Huizhou quote is valid until November.", ctx)
    assert not place_claim_failures("Yunzhan's Shenzhen plant is under notice.", ctx)
    ctx.site_text["quenvara energy tech"] = "malaysia (penang assembly) made from huizhou cells"
    assert not place_claim_failures("Quenvara's Penang site can start in February.", ctx)  # not a master city: not held to the master
    assert not place_claim_failures("Quenvara's Shenzhen quote.", type("C", (), {"db_path": "/nonexistent.db", "site_text": {}})())  # no records to check against: nothing is claimed


def test_a_request_has_one_signer_the_buyer_of_the_lines_it_asks_about(db_path, tmp_path, monkeypatch):
    """FEEDBACK: on a shared item every owner could sign every draft. The model names the lines; code reads their buyers and refuses a request that spans two."""
    import asyncio
    import json
    import shutil
    import sqlite3

    from app.domain.actions import ledger, tools as action_tools
    from app.organism.context import RunContext
    from app.organism.runner import allow_map
    from app.organism.runs.events import Recorder

    monkeypatch.delenv("LOOKOUT_FAKE_SERVICES", raising=False)
    db = str(tmp_path / "s.db")
    shutil.copy(db_path, db)
    con = sqlite3.connect(db)
    rows = con.execute("SELECT p.id, p.identity_id, b.name FROM po_lines p JOIN buyers b ON b.id = p.buyer_id WHERE p.status IN ('OPEN','PARTIAL')").fetchall()
    con.close()
    by_supplier: dict = {}
    for line, sid, buyer in rows:
        by_supplier.setdefault(sid, {}).setdefault(buyer, []).append(line)
    sid, per_buyer = next((s, b) for s, b in by_supplier.items() if len(b) >= 1 and s in {"SUP-0001", "SUP-0029", "SUP-0035", "SUP-0002"})
    svc = organism_services.get(db)
    try:
        ctx = RunContext(run_id="run-s", item_key="deadline:chase", db_path=db, recorder=Recorder("run-s", db), plan=["buyers_clerk"], allow=allow_map(["buyers_clerk"]), stage_allowed=True)
        tool = {t.name: t for t in action_tools.make_tools(ctx, svc.suppliers)}["draft_supplier_request"]
        call = lambda **a: json.loads(asyncio.run(tool.handler(a))["content"][0]["text"])  # noqa: E731
        buyer, lines = next(iter(per_buyer.items()))
        out = call(supplier_id=sid, subject="Dates for these lines", body="Please confirm the dates for these lines.", lines=lines[:1])
        assert out["data"]["action_id"] and ledger.get(db, out["data"]["action_id"]).owner == buyer
        two = [l[0] for l in per_buyer.values()]
        if len(two) >= 2:
            assert "one signer" in call(supplier_id=sid, subject="Dates again", body="Please confirm the dates again.", lines=two)["error"]
    finally:
        svc.close()


def test_material_a_company_consigns_is_used_wherever_the_part_it_becomes_is(db_path, monkeypatch):
    """FEEDBACK: the recorded consignment answer said the two boards 'appear in no robot's bill of materials', so no build was hit, beside a headline saying every robot's controller slips."""
    monkeypatch.delenv("LOOKOUT_FAKE_SERVICES", raising=False)
    svc = organism_services.get(str(db_path))
    try:
        consigned = svc._session.execute(__import__("sqlalchemy").text("SELECT material_part, into_part FROM consignments LIMIT 1")).fetchone()
        material, into = consigned
        direct = {w.product.id for w in svc.bom.where_used(into)}
        via = svc.bom.where_used(material)
        assert direct and {w.product.id for w in via} == direct  # every product that builds the parent part uses the consigned material
        assert all(w.paths[0][-1] == material and into in w.paths[0] for w in via)  # the route says how: through the part it is built into
    finally:
        svc.close()


def test_one_suppliers_clause_read_for_several_parts_is_one_condition():
    """BUYER: 'Quote the other four parts' carried the same supplier clause three times in Conditions (one per part compared)."""
    from app.organism.carry import conditions_from_compare, missing

    col = {"supplier": "Acme", "key": "Q-1", "conditions": "Prices exclude any new import duty.", "terms": {}}
    conds = {}
    for part in ("P-1", "P-2", "P-3"):
        conds.update(conditions_from_compare({"part": part, "columns": [{"current": True}, col]}))
    assert len(conds) == 3 and missing(conds, "nothing about it") == ["Acme: Prices exclude any new import duty"]


def test_conditions_name_each_supplier_once():
    """BUYER Q2 (run-adb45cf7): 'Shenzhen Yunzhan Precision Motor:' was repeated before each of four conditions."""
    from app.organism.carry import grouped

    assert grouped(["Acme: lead time 35 days", "Acme: Net 60", "Beta: FOB", "Acme: lead time 35 days"]) == ["Acme: lead time 35 days; Net 60", "Beta: FOB"]
