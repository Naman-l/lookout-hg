"""The tool wrappers over the (fake) services: numbers get stable ids and land in the evidence register."""

import asyncio
import json
from decimal import Decimal

from app.domain.bom import tools as bom_tools
from app.domain.demand import tools as demand_tools
from app.domain.orders import tools as orders_tools
from app.organism.schemas import Number
from app.organism.specialists.handoff import make_handoff_tool


def call(tool, **args):
    out = asyncio.run(tool.handler(args))
    return json.loads(out["content"][0]["text"])


def by_name(tools):
    return {t.name: t for t in tools}


def test_open_supply_reports_the_stuck_quantity(ctx, services):
    t = by_name(orders_tools.make_tools(ctx, services.orders))
    body = call(t["open_supply"], part_number="HR-40110")
    ids = {n["id"]: n["value"] for n in body["numbers"]}
    assert ids["supply:HR-40110:stuck_qty"] == "1140" and ids["supply:HR-40110:open_lines"] == "3"
    assert ctx.evidence["supply:HR-40110:stuck_qty"].unit == "EA"


def test_shortage_names_the_first_short_month_and_asks_dana_for_on_hand(ctx, services):
    t = by_name(demand_tools.make_tools(ctx, services.demand))
    body = call(t["shortage_for_parts"], part_numbers=["HR-40110"])
    assert body["data"][0]["first_short_month"] == "2026-10"
    assert ctx.evidence["shortage:HR-40110:2026-10:short"].value == 364
    assert body["unknowns"][0]["owner"] == "Dana" and "On-hand" in body["unknowns"][0]["what"]


def test_no_shortage_is_raised_where_nothing_is_disrupted(ctx, services):
    t = by_name(demand_tools.make_tools(ctx, services.demand))
    body = call(t["shortage_for_parts"], part_numbers=["HR-99999"])
    assert body["data"][0]["first_short_month"] is None and body["numbers"] == []


def test_where_used(ctx, services):
    t = by_name(bom_tools.make_tools(ctx, services.bom))
    body = call(t["where_used_for_parts"], part_numbers=["HR-40110", "HR-99999"])
    assert body["data"][0]["used_in"][0]["product"] == "Tern T2" and body["data"][1]["used_in"] == []


def test_read_tools_are_marked_read_only(ctx, services):
    for t in orders_tools.make_tools(ctx, services.orders) + demand_tools.make_tools(ctx, services.demand):
        assert t.annotations.read_only_hint is True and t.annotations.open_world_hint is False


def test_handoff_needs_findings(ctx):
    h = make_handoff_tool(ctx, "supply_planner")
    out = asyncio.run(h.handler({"findings": []}))
    assert out.get("is_error") and "supply_planner" not in ctx.handoffs


def test_handoff_carries_what_the_specialists_tools_returned(ctx, services):
    t = by_name(orders_tools.make_tools(ctx, services.orders))
    call(t["open_supply"], part_number="HR-40110")
    ctx.numbers_by_agent["supply_planner"] = list(ctx.evidence)  # what the PostToolUse hook records
    h = make_handoff_tool(ctx, "supply_planner")
    empty = asyncio.run(h.handler({"findings": ["Nothing found."]}))
    assert empty.get("is_error") and "read nothing yet" in empty["content"][0]["text"]  # a handoff that looked at nothing is not an answer
    ctx.reads_ok["supply_planner"] += 1  # what the PostToolUse hook records for a result
    out = asyncio.run(h.handler({"findings": ["1,140 EA stuck"]}))
    assert not out.get("is_error")
    assert "supply:HR-40110:stuck_qty" in ctx.handoffs["supply_planner"].number_ids


def test_whole_numbers_are_shown_whole():
    from decimal import Decimal

    from app.organism.schemas import Number

    assert str(Number(id="a", name="n", value=Decimal("364.0"), unit="EA").value) == "364"
    assert str(Number(id="a", name="n", value=Decimal("2.50"), unit="EA").value) == "2.5"


def test_disrupted_supply_covers_every_line_of_the_notice_across_parts(ctx, services):
    t = by_name(orders_tools.make_tools(ctx, services.orders))
    body = call(t["disrupted_supply"], supplier_id="SUP-0001")
    ids = {n["id"]: n["value"] for n in body["numbers"]}
    assert ids["supply:SUP-0001:disrupted_lines"] == "10"
    assert ids["supply:HR-40110:stuck_qty"] == "1140" and ids["supply:HR-40210:stuck_qty"] == "307"
    assert ids["supply:HR-40130:HPO-26-00532/10:qty"] == "1320"
    assert {p["part"] for p in body["data"]} == {"HR-40110", "HR-40120", "HR-40130", "HR-40210", "HR-40230"}


def test_disrupted_supply_names_the_kind_of_notice(ctx, services):
    t = by_name(orders_tools.make_tools(ctx, services.orders))
    fire = call(t["disrupted_supply"], supplier_id="SUP-0001")
    assert {l["notice_kind"] for p in fire["data"] for l in p["lines"]} == {"force majeure"} and "notice: force majeure" in fire["summary"]
    assert call(t["disrupted_supply"], supplier_id="SUP-0002")["data"] == []                 # a supplier with no notice has none


def test_open_supply_reports_what_is_not_disrupted(ctx, services):
    t = by_name(orders_tools.make_tools(ctx, services.orders))
    call(t["open_supply"], part_number="HR-40110")
    assert ctx.evidence["supply:HR-40110:unaffected_qty"].value == 0


def test_shortage_for_parts_answers_every_part_in_one_call(ctx, services):
    t = by_name(demand_tools.make_tools(ctx, services.demand))
    body = call(t["shortage_for_parts"], part_numbers=["HR-40110", "HR-99999"])
    assert [d["part"] for d in body["data"]] == ["HR-40110", "HR-99999"]
    assert ctx.evidence["shortage:HR-40110:2026-10:short"].value == 364 and "October" in body["summary"]


def test_buyer_words_for_dates():
    from app.organism.toolkit import date_words, month_words, plural

    assert month_words("2026-10") == "October" and month_words("2027-01") == "January 2027"
    assert date_words("2026-09-22") == "22 September"
    assert plural(1, "open question") == "1 open question" and plural(2, "open question") == "2 open questions"


def test_exposure_for_part_gives_net_beside_gross_and_the_open_line_duty(ctx, services):
    from app.domain.tariffs import tools as tariff_tools

    t = by_name(tariff_tools.make_tools(ctx, services.tariffs))
    body = call(t["exposure_for_part"], part_number="HR-40110")
    ev = ctx.evidence
    assert ev["tariff:HR-40110:net"].value == Decimal("183186.97") and ev["tariff:HR-40110:gross"].value == Decimal("226752.07")
    assert ev["tariff:HR-40110:rate"].value == 25 and ev["tariff:HR-40110:uncovered_qty"].value == 3656
    assert ev["tariff:HR-40110:open_value"].value == Decimal("173891.70") and ev["tariff:HR-40110:open_lines_duty"].value == Decimal("43472.93")
    assert body["data"]["lines"][0]["importer"] == "company" and "1 November" == body["data"]["rule"]["effective_words"]
    assert "October" not in body["summary"] and "183,186" in body["summary"]


def test_compare_offers_keeps_conditions_with_values_and_what_is_unknown(ctx, services):
    from app.domain.quotes import tools as quote_tools

    t = by_name(quote_tools.make_tools(ctx, services.quotes))
    body = call(t["compare_offers"], part_number="HR-40110", qty=500)
    ev = ctx.evidence
    assert ev["quote:HR-40110:VPM-Q-260924:total"].value == Decimal("165.54") and ev["quote:HR-40110:VPM-Q-260924:total_if_china"].value == Decimal("206.925")
    assert ev["quote:HR-40110:current:total"].value == Decimal("191.08") and ev["quote:HR-40110:Q-YZ-26-0831:total"].value == Decimal("193.1875")
    vpm = next(c for c in body["data"]["columns"] if c["quote_no"] == "VPM-Q-260924")
    assert vpm["lead_time"]["condition"].startswith("after PPAP") and vpm["duty_status"] == "unknown_origin"
    assert any(u["what"] == "Origin ruling" and u["owner"] == "broker" for u in body["unknowns"])
    assert next(c for c in body["data"]["columns"] if c["quote_no"] == "Q-YZ-26-0831")["valid_until_words"] == "13 October"


def test_a_draft_with_a_number_or_date_no_tool_returned_is_refused_before_it_exists(ctx, services, db):
    from app.domain.actions import ledger
    from app.domain.actions import tools as action_tools

    t = by_name(action_tools.make_tools(ctx, services.suppliers))
    out = asyncio.run(t["draft_supplier_request"].handler({"supplier_id": "SUP-0001", "subject": "Dates", "body": "Please ship 900 units and confirm by 2 December."}))
    assert out.get("is_error") and "900" in out["content"][0]["text"] and "2 December" in out["content"][0]["text"]
    assert ledger.list_actions(db) == []
    ctx.seen_dates.add((12, 2))
    ctx.seen_numerals.add(Decimal(900))
    ok = asyncio.run(t["draft_supplier_request"].handler({"supplier_id": "SUP-0001", "subject": "Dates", "body": "Please ship 900 units and confirm by 2 December."}))
    assert not ok.get("is_error") and len(ledger.list_actions(db)) == 1


def _rung(key, label, state, detail, owner=None, question=""):
    from app.domain.common import Unknown as U
    from app.domain.phases.schema import Rung

    return Rung(key=key, label=label, state=state, detail=detail, date="2026-08-26" if state in ("done", "disrupted") else None,
                unknown=U(what=f"whether {label.lower()}", why_it_blocks="no data", owner=owner, question=question) if state == "unknown" else None)


def test_get_phases_says_unknown_with_who_to_ask_and_groups_the_questions_by_person(ctx):
    from app.domain.common import EntityRef
    from app.domain.phases import tools as phase_tools
    from app.domain.phases.schema import Ladder

    rungs = [_rung("ordered", "Ordered", "done", "3 open lines"), _rung("promised", "Promised", "disrupted", "named on the notice"),
             _rung("shipped", "Shipped", "unknown", "no ship notice", "supplier", "Has it shipped?"), _rung("in_transit", "In transit", "unknown", "no carrier data", "supplier", "Where is it?"),
             _rung("customs", "Customs", "unknown", "no customs data", "broker", "Has it cleared?"), _rung("closed", "Closed", "na", "per line")]
    ladder = Ladder(subject=EntityRef(type="part", id="HR-40110"), kind="part", rungs=rungs, counts={"done": 1, "disrupted": 1, "unknown": 3, "na": 1}, verdict="1 known, 3 unknown (no data)")
    svc = type("S", (), {"part_phases": lambda self, p: ladder, "line_phases": lambda self, l: None})()
    t = {x.name: x for x in phase_tools.make_tools(ctx, svc)}
    body = call(t["get_phases"], part_number="HR-40110")
    assert body["summary"] == "HR-40110: 1 known, 3 unknown (no data)"
    assert [r["stage"] for r in body["data"]["stages"]] == ["Ordered", "Promised", "Shipped", "In transit", "Customs"]  # a stage that does not apply is left out
    assert ctx.evidence["phases:HR-40110:unknown"].value == 3
    owners = sorted(u["owner"] for u in body["unknowns"])
    assert owners == ["broker", "supplier"]  # three unknown stages, two people to ask
    supplier = next(u for u in body["unknowns"] if u["owner"] == "supplier")
    assert "shipped" in supplier["what"] and "in transit" in supplier["what"] and "Has it shipped?" in supplier["question"]
    assert asyncio.run(t["get_phases"].handler({"part_number": "A", "po_line": "B"})).get("is_error")


def test_build_readiness_counts_never_a_percent_and_no_order_is_unknown_not_covered(ctx):
    from app.domain.common import EntityRef, Quantity
    from app.domain.common import Provenance as Pv
    from app.domain.common import Unknown as U
    from app.domain.phases import tools as phase_tools
    from app.domain.phases.schema import BuildReadiness, ReadyGroup, ReadyPart

    from app.domain.phases.schema import Ask, Qty

    q = lambda v: Qty(value=Decimal(v), uom="EA")  # noqa: E731
    parts = [ReadyPart(part=EntityRef(type="part", id="HR-40110"), state="disrupted", detail="under a notice", need=q(364), cause=EntityRef(type="message", id="fm")),
             ReadyPart(part=EntityRef(type="part", id="HR-99001"), state="no_order", detail="no open order", need=q(10), ask=Ask(owner="Dana", question="On the shelf?")),
             ReadyPart(part=EntityRef(type="part", id="HR-11111"), state="covered", detail="lands in the month", need=q(5))]
    b = BuildReadiness(product=EntityRef(type="product", id="HR-90020", label="Tern T2"), month="2026-10", units=182, verdict="1 covered, 1 disrupted, 1 with no open order",
                       need_source=Pv(method="computed", source="forecast x BOM"), counts={"covered": 1, "disrupted": 1, "no_order": 1},
                       groups=[ReadyGroup(assembly=EntityRef(type="part", id="HR-80110"), parts=parts, counts={"covered": 1})],
                       stock_counted=0, stock_note="No stock count is loaded: parts with no open order are unknown, not covered.")
    svc = type("S", (), {"build_readiness": lambda self, p, m: b if (p, m) == ("Tern T2", "2026-10") else None})()
    t = {x.name: x for x in phase_tools.make_tools(ctx, svc)}
    body = call(t["build_readiness"], product="Tern T2", month="2026-10")
    assert [p["part"] for p in body["data"]["needing_attention"]] == ["HR-40110"]  # covered and unknown parts are not 'problems'
    assert ctx.evidence["build:HR-90020:2026-10:no_order"].value == 1 and ctx.evidence["build:HR-90020:2026-10:units"].value == 182
    assert body["unknowns"][0]["owner"] == "Dana" and "no open order" in body["unknowns"][0]["what"] and "%" not in body["summary"]
    assert asyncio.run(t["build_readiness"].handler({"product": "Heron H1", "month": "2026-10"})).get("is_error")


def test_a_long_tool_answer_is_cut_with_a_note_that_says_how_to_ask_for_less():
    import json as _json

    from app.organism.toolkit import MAX_REPLY_CHARS, _compact

    short = _compact({"summary": "s", "data": {"a": None, "b": []}, "numbers": [], "unknowns": []})
    assert " " not in short and '"a":null' in short and '"b":[]' in short  # compact, and an empty answer is still there
    long = _json.loads(_compact({"summary": "s", "data": ["x" * 100] * 400, "numbers": [{"id": "n"}], "unknowns": []}))
    assert long["data"] is None and long["numbers"] == [{"id": "n"}] and "fewer parts" in long["note"] and MAX_REPLY_CHARS > 5000


def test_the_prompt_knows_who_is_asking_and_what_was_already_decided():
    from types import SimpleNamespace as NS

    from app.organism.workflows.work_item import build_prompt

    item = NS(key="deadline:SUP-0001:2026-10-13", title="Yunzhan date", kind="deadline", owner="Dana Reyes", refs=[], decisions=[NS(type="supplier_request", state="rejected", by="Dana Reyes", reason="too soft")])
    own, other = build_prompt(item, "Dana Reyes"), build_prompt(item, "Marcus Chen")
    assert "their own item" in own and "belongs to Dana Reyes" in other
    assert "supplier request rejected by Dana Reyes (too soft)" in own and "Do not propose again" in own


def test_open_supply_can_be_asked_for_a_supplier_when_a_deadline_names_one_not_a_part(ctx, services):
    t = by_name(orders_tools.make_tools(ctx, services.orders))
    body = call(t["open_supply"], supplier_id="SUP-0001")
    assert body["data"] and {l["supplier"] for l in body["data"]} == {"SUP-0001"}
    assert "error" in call(t["open_supply"])  # neither a part nor a supplier: it says what to give


def test_lookout_always_gets_the_whole_of_what_its_team_handed_back(ctx):
    """A long handoff was cut by the size cap, so Lookout wrote 'I couldn't read what it staged'."""
    from app.organism import lookout_tools
    from app.organism.schemas import Handoff

    ctx.handoffs["buyers_clerk"] = Handoff(findings=["Logged a question for a buyer about the past-due lines. " * 3] * 60, action_ids=["A-1"])
    body = call(by_name(lookout_tools.make_tools(ctx))["get_handoffs"])
    assert len(body["data"]["buyers_clerk"]["findings"]) == 60 and "note" not in body


def test_a_buyer_gets_one_question_per_run_and_a_full_name_is_the_same_buyer(ctx, db):
    from dataclasses import replace

    from app.domain.actions import tools as action_tools

    ctx.db_path, ctx.item_key = str(db), "deadline:chase"
    import sqlite3

    con = sqlite3.connect(str(db))                       # the buyers come from the data's buyers table, not from the code
    con.execute("create table if not exists buyers (id text primary key, name text, initials text)")
    con.executemany("insert or ignore into buyers values (?, ?, ?)", [("Dana", "Dana Reyes", "DR"), ("Marcus", "Marcus Chen", "MC")])
    con.commit()
    con.close()
    t = by_name(action_tools.make_tools(ctx, None))
    a = call(t["log_buyer_question"], owner="Dana Reyes", question="Q?")
    assert "internal note" in json.loads(asyncio.run(t["log_buyer_question"].handler({"owner": "Marcus", "question": "Other?"}))["content"][0]["text"])["summary"]
    again = call(t["log_buyer_question"], owner="Dana", question="Another?")
    assert a["data"]["action_id"] and "already has a question" in again["error"]  # one note per buyer, however it is named
    assert "error" in call(t["log_buyer_question"], owner="Li Wei", question="Q?")
    later = replace(ctx, run_id="run-2", asked_buyers=set())  # the next run asks the same question: the same note, logged once
    assert call(by_name(action_tools.make_tools(later, None))["log_buyer_question"], owner="Dana", question="Q?")["data"]["action_id"] == a["data"]["action_id"]


def test_the_version_hash_covers_every_specialist_prompt_and_every_tool_definition(ctx, services, monkeypatch):
    from dataclasses import replace

    from app.organism import runner
    from app.organism.specialists import registry

    lists = runner.tool_lists(ctx, services)
    a = runner.versions("sys", ["supply_planner"], lists, {"x": 1})
    assert a == runner.versions("sys", ["supply_planner"], lists, {"x": 1}) and a["tool_count"] == len(registry.TOOL_SERVER)
    assert runner.versions("sys", ["supply_planner"], lists, {"x": 2})["prompt_hash"] != a["prompt_hash"]  # the output schema
    monkeypatch.setitem(registry.SPECIALISTS, "supply_planner", replace(registry.SPECIALISTS["supply_planner"], description="changed"))
    monkeypatch.setitem(runner.SPECIALISTS, "supply_planner", registry.SPECIALISTS["supply_planner"])
    assert runner.versions("sys", ["supply_planner"], lists, {"x": 1})["prompt_hash"] != a["prompt_hash"]  # a specialist's text
    lists["orders"][0].description += " changed"
    assert runner.versions("sys", ["supply_planner"], lists, {"x": 1})["toolset_hash"] != a["toolset_hash"]  # a tool's description



def test_working_an_item_the_morning_run_prepared_shows_that_draft_and_says_where_it_came_from(ctx, db):
    from dataclasses import replace
    from types import SimpleNamespace as NS

    from app.domain.actions import ledger, tools as action_tools
    from app.domain.common import EntityRef
    from app.organism.runs import store

    store.insert_run(str(db), run_id="run-morning", item_key="disruption:SUP-0001", workflow="work_item", status="ok", started_at="now", model="m", asked_by="Morning run")
    ctx.db_path, ctx.item_key = str(db), "disruption:SUP-0001"
    morning = replace(ctx, run_id="run-morning")
    svc = NS(contact_for=lambda s: NS(email="li.wei@yunzhan-motor.example", name="Li Wei"))
    args = dict(supplier_id="SUP-0001", subject="Revised dates please", body="Please confirm the revised promise dates and allocation for the open lines.")
    first = call(by_name(action_tools.make_tools(morning, svc))["draft_supplier_request"], **args)
    assert "already_waiting" not in first["data"]
    mine = call(by_name(action_tools.make_tools(ctx, svc))["draft_supplier_request"], **args)  # the buyer works the item later
    assert mine["data"]["action_id"] == first["data"]["action_id"] and mine["data"]["already_waiting"] == "prepared this morning"
    assert "prepared this morning" in mine["summary"] and mine["data"]["action_id"] in ctx.action_ids
    assert len([a for a in ledger.list_actions(db) if a.type == "supplier_request"]) == 1 and ledger.in_run(db, mine["data"]["action_id"], ctx.run_id)


def test_conditional_lines_raise_the_ship_date_as_a_question_with_the_buyer_who_owns_it(ctx, services):
    """Round 6: tariff-hr40110 never asked when the late lines ship, so the in-transit exemption stayed an unstated assumption."""
    from types import SimpleNamespace as NS

    from app.domain.tariffs import tools as tariff_tools

    e = services.tariffs.exposure_for_part("HR-40110")
    late = [l.model_copy(update={"bucket": "conditional"}) for l in e.open_lines[:2]]
    svc = NS(exposure_for_part=lambda part: e.model_copy(update={"open_lines": late + e.open_lines[2:]}), duty_for_line=services.tariffs.duty_for_line, buyer_of=lambda part: "Dana")
    body = call(by_name(tariff_tools.make_tools(ctx, svc))["exposure_for_part"], part_number="HR-40110")
    q = next(u for u in body["unknowns"] if "ship before the duty date" in u["what"])
    assert q["owner"] == "Dana" and "HR-40110" in q["question"] and "no record holds a ship date" in q["why_it_blocks"] and "1 November" in q["why_it_blocks"]
    body = call(by_name(tariff_tools.make_tools(ctx, services.tariffs))["exposure_for_part"], part_number="HR-40110")
    assert not [u for u in body["unknowns"] if "ship before the duty date" in u["what"]]  # no conditional line, no question


def _clerk(ctx, db, item_key, run_id):
    from dataclasses import replace
    from types import SimpleNamespace as NS

    from app.domain.actions import tools as action_tools

    c = replace(ctx, run_id=run_id, item_key=item_key, db_path=str(db), action_ids=[], asked_buyers=set())
    svc = NS(contact_for=lambda s: NS(email="li.wei@yunzhan-motor.example", name="Li Wei"))
    return c, by_name(action_tools.make_tools(c, svc))


def test_one_open_thread_per_supplier_contact_a_second_item_with_the_same_ask_is_covered_not_doubled(ctx, db):
    """FEEDBACK-12: the fire, the 10 October deadline and the 13 October quote each emailed the same contact for the same lines."""
    from app.domain.actions import ledger

    fire, t1 = _clerk(ctx, db, "disruption:SUP-0001", "run-1")
    first = call(t1["draft_supplier_request"], supplier_id="SUP-0001", subject="Revised dates", body="Please confirm the revised promise dates.")
    deadline, t2 = _clerk(ctx, db, "deadline:SUP-0001:2026-10-10", "run-2")
    second = call(t2["draft_supplier_request"], supplier_id="SUP-0001", subject="Revised promise dates", body="Please confirm the revised promise dates for the open lines.")
    assert second["data"]["covered_by"] == first["data"]["action_id"] and "already waiting for approval" in second["summary"] and "Do not draft another" in second["data"]["instruction"]
    assert len([a for a in ledger.list_actions(db) if a.type == "supplier_request"]) == 1  # one thread, one draft
    assert first["data"]["action_id"] in deadline.action_ids and ledger.in_run(db, first["data"]["action_id"], "run-2")  # the second run's record says which draft covers it


def test_a_different_ask_is_merged_into_the_waiting_request_or_sent_as_its_own_when_that_was_sent(ctx, db, monkeypatch):
    """FEEDBACK 8.3: the fire request went out without the quote item's extension ask because the one-thread rule said 'covered'."""
    from app.domain.actions import approvers, ledger

    monkeypatch.setattr(approvers, "owners_of", lambda d, key: {"Dana Reyes"})
    fire, t1 = _clerk(ctx, db, "disruption:SUP-0001", "run-1")
    first = call(t1["draft_supplier_request"], supplier_id="SUP-0001", subject="Revised dates", body="Please confirm the revised promise dates.")["data"]
    quote, t2 = _clerk(ctx, db, "deadline:SUP-0001:2026-10-13", "run-2")
    out = call(t2["draft_supplier_request"], supplier_id="SUP-0001", subject="Quote validity", body="Please extend the quote validity past its end date.")
    assert out["data"]["must_amend"] == first["action_id"] and "covered_by" not in out["data"] and "Do not say this item is covered" in out["data"]["instruction"]
    merged = call(t2["amend_draft"], action_id=first["action_id"], paragraph="Please extend the quote validity past its end date.")["data"]
    assert merged["action_id"] == first["action_id"] and merged["amended_for"] == "deadline:SUP-0001:2026-10-13" and merged["payload_hash"] != first["payload_hash"]
    a = ledger.get(db, first["action_id"])
    assert "\n\nPlease extend the quote validity past its end date.\n\nRegards,\nDana Reyes" in a.body and ledger.asks_of(a) == ["disruption:SUP-0001", "deadline:SUP-0001:2026-10-13"]
    assert len([x for x in ledger.list_actions(db) if x.type == "supplier_request"]) == 1  # one draft containing both asks, linked to both items
    assert ledger.in_run(db, first["action_id"], "run-1") and ledger.in_run(db, first["action_id"], "run-2")
    # the quote item worked again: its ask is already in, so it is covered and the other item's paragraph is not overwritten
    again, t3 = _clerk(ctx, db, "deadline:SUP-0001:2026-10-13", "run-3")
    assert "covered_by" in call(t3["draft_supplier_request"], supplier_id="SUP-0001", subject="Quote validity", body="Please extend the quote validity past its end date.")["data"]
    # the fire request was sent without the extension: a new short request for just that ask, not 'covered'
    sent_db = db
    first2, t4 = _clerk(ctx, db, "disruption:SUP-0001", "run-4")
    fresh = ledger.get(sent_db, first["action_id"])
    ledger.approve(sent_db, fresh.action_id, fresh.payload_hash, "Dana Reyes")
    tariff, t5 = _clerk(ctx, db, "tariff:HR-40110", "run-5")
    new = call(t5["draft_supplier_request"], supplier_id="SUP-0001", subject="Origin papers", body="Please send the certificate of origin for the drive motor.")["data"]
    assert new["action_id"] != first["action_id"] and ledger.get(db, new["action_id"]).state == "proposed"
    assert len([x for x in ledger.list_actions(db) if x.type == "supplier_request"]) == 2


def test_a_request_already_sent_to_the_contact_covers_the_same_ask_and_a_rejected_one_does_not(ctx, db):
    from app.domain.actions import ledger

    c1, t1 = _clerk(ctx, db, "disruption:SUP-0001", "run-1")
    a = call(t1["draft_supplier_request"], supplier_id="SUP-0001", subject="Revised dates", body="Please confirm the revised promise dates.")["data"]
    ledger.approve(db, a["action_id"], a["payload_hash"], "Dana Reyes")
    c2, t2 = _clerk(ctx, db, "deadline:SUP-0001:2026-10-10", "run-2")
    sent = call(t2["draft_supplier_request"], supplier_id="SUP-0001", subject="Promise dates", body="Please confirm the revised promise dates for those lines.")
    assert sent["data"]["covered_by"] == a["action_id"] and "already sent" in sent["summary"] and c2.action_ids == []  # nothing new for the run to cite: it was sent, not waiting
    assert len([x for x in ledger.list_actions(db) if x.type == "supplier_request"]) == 1
    # a rejected thread is not a thread: the next item may start one
    b = ledger.propose(db, type="supplier_request", item_key="x", run_id="run-9", target=None, recipient="other@sup.example", subject="s", body="b")
    ledger.reject(db, b.action_id, "wrong", "Dana Reyes")
    assert ledger.open_thread(db, "other@sup.example") is None


def test_the_same_item_worked_again_amends_its_waiting_draft_instead_of_adding_one(ctx, db):
    from app.domain.actions import ledger

    c1, t1 = _clerk(ctx, db, "disruption:SUP-0001", "run-1")
    first = call(t1["draft_supplier_request"], supplier_id="SUP-0001", subject="Revised dates", body="Please confirm the revised promise dates.")["data"]
    c2, t2 = _clerk(ctx, db, "disruption:SUP-0001", "run-2")
    again = call(t2["draft_supplier_request"], supplier_id="SUP-0001", subject="Revised dates and allocation", body="Please confirm the revised promise dates and the quantities you can allocate.")
    assert again["data"]["action_id"] == first["action_id"] and again["data"]["amended"] and again["data"]["payload_hash"] != first["payload_hash"]
    drafts = [x for x in ledger.list_actions(db) if x.type == "supplier_request"]
    assert len(drafts) == 1 and drafts[0].subject == "Revised dates and allocation" and drafts[0].state == "proposed"


def test_overlapping_stock_questions_for_one_buyer_are_one_note(ctx, db):
    from app.domain.actions import ledger

    c1, t1 = _clerk(ctx, db, "disruption:SUP-0001", "run-1")
    seed_buyers = __import__("tests.organism.conftest", fromlist=["seed_buyers"]).seed_buyers
    seed_buyers(db)
    n1 = call(t1["log_buyer_question"], owner="Dana", question="What stock of HR-40110 and HR-40120 is on hand?")
    c2, t2 = _clerk(ctx, db, "deadline:SUP-0001:2026-10-10", "run-2")
    n2 = call(t2["log_buyer_question"], owner="Dana", question="Is any HR-40110 in stock before the lines arrive?")
    assert n2["data"]["covered_by"] == n1["data"]["action_id"] and "no second note" in n2["summary"]
    c3, t3 = _clerk(ctx, db, "tariff:HR-50110", "run-3")
    other = call(t3["log_buyer_question"], owner="Dana", question="Where is HR-50110 made?")
    assert other["data"]["action_id"] != n1["data"]["action_id"]  # different parts, a different question
    assert len([x for x in ledger.list_actions(db) if x.type == "note"]) == 2


def test_the_sequence_of_feedback_3_2_a_reply_run_does_not_ask_again_for_what_was_sent_minutes_earlier(ctx, db):
    """run-a3cb6869: a reply run on the force-majeure mail staged a fifth request to the contact although one with the same subject had been SENT 25 minutes before."""
    from types import SimpleNamespace as NS

    from app.domain.actions import ledger
    from app.organism.context_packet import build, thread_state

    fire, t_fire = _clerk(ctx, db, "disruption:SUP-0001", "run-fire")
    a = call(t_fire["draft_supplier_request"], supplier_id="SUP-0001", subject="Force majeure notice: revised dates and allocation", body="Please confirm the revised promise dates and allocation.")["data"]
    sent = ledger.approve(db, a["action_id"], a["payload_hash"], "Dana Reyes")
    assert sent.state == "executed" and len(ledger.outbox(db)) == 1
    item = NS(key="reply:fm", group="reply", title="Reply", owner="", refs=[NS(type="supplier", id="SUP-0001", label="Shenzhen Yunzhan")])
    svc = NS(suppliers=NS(contact_for=lambda s: NS(email="li.wei@yunzhan-motor.example", name="Li Wei")))
    text = thread_state(item, svc, str(db))
    assert a["action_id"] in text and "(sent)" in text and "Force majeure notice: revised dates and allocation" in text and "do not ask again" in text
    assert build(item, svc, str(db)).text == text  # the packet of a reply run carries it
    reply_run, t_reply = _clerk(ctx, db, "reply:fm", "run-reply")
    again = call(t_reply["draft_supplier_request"], supplier_id="SUP-0001", subject="Force majeure notice: revised dates and allocation", body="Please confirm the revised promise dates and allocation for those lines.")
    assert again["data"]["covered_by"] == a["action_id"] and a["action_id"] in again["summary"] and "already sent" in again["summary"]
    assert len([x for x in ledger.list_actions(db) if x.type == "supplier_request"]) == 1 and len(ledger.outbox(db)) == 1  # no fifth request, no second send
    other = NS(key="reply:other", group="reply", title="r", owner="", refs=[NS(type="supplier", id="SUP-0099", label="x")])
    assert thread_state(other, NS(suppliers=NS(contact_for=lambda s: NS(email="nobody@elsewhere.example", name="N"))), str(db)) == ""  # another contact: nothing to say


def test_one_call_answers_several_parts_and_several_months(ctx, services):
    """O11: the cap of three exposure_for_part calls truncated a correct five-part plan; twelve build_readiness calls cost nineteen turns, each resending the prompt."""
    import asyncio
    import json
    from types import SimpleNamespace as NS

    from app.domain.phases import tools as phase_tools
    from app.domain.tariffs import tools as tariff_tools

    t = by_name(tariff_tools.make_tools(ctx, services.tariffs))
    one = call(t["exposure_for_part"], part_number="HR-40110")
    many = call(t["exposure_for_parts"], part_numbers=["HR-40110", "HR-40120", "HR-40110", "HR-40130"])  # a repeated part is read once
    assert len(many["data"]) == 3 and many["data"][0] == one["data"] and many["summary"].startswith("Tariff exposure for 3 parts")
    assert {n["id"] for n in one["numbers"]} <= {n["id"] for n in many["numbers"]}
    asked = []
    svc = NS(build_readiness=lambda p, m: asked.append((p, m)) or None)
    pt = {x.name: x for x in phase_tools.make_tools(ctx, svc)}
    out = asyncio.run(pt["build_readiness"].handler({"products": ["Tern T2", "Porter P5"], "months": ["2026-10", "2026-11", "2026-12"]}))
    assert out.get("is_error") and len(asked) == 6  # six combinations, one call; nothing found is a refusal that names them
    assert asyncio.run(pt["build_readiness"].handler({})).get("is_error")
    assert json.loads(out["content"][0]["text"])["error"].startswith("no such product or no forecast for Tern T2 2026-10")


def test_a_specialist_is_sent_only_the_glossaries_of_the_records_it_works_with():
    from app.organism.prompts import glossary
    from app.organism.specialists.registry import SPECIALISTS

    everything = len(glossary())
    for sp in SPECIALISTS.values():
        text = sp.instructions_for(None)
        assert "How the trade talks" in text and "### common" in text.replace("### common", "### common") or "How the records link" in text
        assert len(glossary(sp.entities)) < everything, sp.name
    assert "### tariffs" in glossary(SPECIALISTS["tariff_analyst"].entities) and "### inbox" not in glossary(SPECIALISTS["tariff_analyst"].entities)
    assert "### inbox" in glossary(SPECIALISTS["inbox_analyst"].entities) and "### orders" not in glossary(SPECIALISTS["inbox_analyst"].entities)


def test_build_readiness_names_the_parts_that_land_after_the_build_and_the_disrupted_ones(ctx):
    """F2.2: the agent told a buyer that build readiness 'does not flag these parts' when it does (state after_build); the counts hid them."""
    from app.domain.common import EntityRef
    from app.domain.common import Provenance as Pv
    from app.domain.phases import tools as phase_tools
    from app.domain.phases.schema import BuildReadiness, ReadyGroup, ReadyPart, Qty

    q = lambda v: Qty(value=Decimal(v), uom="EA")  # noqa: E731
    parts = [ReadyPart(part=EntityRef(type="part", id="HR-40110", label="Tern drive motor"), state="disrupted", detail="under a notice", need=q(364)),
             ReadyPart(part=EntityRef(type="part", id="HR-21103", label="Harness"), state="after_build", detail="lands 4 November", need=q(182)),
             ReadyPart(part=EntityRef(type="part", id="HR-21107", label="Harness B"), state="after_build", detail="lands 6 November", need=q(182)),
             ReadyPart(part=EntityRef(type="part", id="HR-11111", label="Fastener"), state="covered", detail="lands in the month", need=q(5))]
    b = BuildReadiness(product=EntityRef(type="product", id="HR-90020", label="Tern T2"), month="2026-10", units=182, verdict="1 covered, 2 after the build, 1 disrupted",
                       need_source=Pv(method="computed", source="forecast x BOM"), counts={"covered": 1, "after_build": 2, "disrupted": 1},
                       groups=[ReadyGroup(assembly=EntityRef(type="part", id="HR-80110"), parts=parts, counts={"covered": 1})], stock_counted=0, stock_note="No stock count is loaded.")
    svc = type("S", (), {"build_readiness": lambda self, p, m: b})()
    t = {x.name: x for x in phase_tools.make_tools(ctx, svc)}
    body = call(t["build_readiness"], product="Tern T2", month="2026-10")
    assert {p["part"] for p in body["data"]["needing_attention"]} == {"HR-40110", "HR-21103", "HR-21107"}  # after_build is flagged
    assert body["summary"].startswith("Tern T2 2026-10: 1 covered, 2 after the build, 1 disrupted") and "after build: Harness (HR-21103), Harness B (HR-21107)" in body["summary"] and "disrupted: Tern drive motor (HR-40110)" in body["summary"]
    both = call(t["build_readiness"], products=["Tern T2"], months=["2026-10", "2026-11"])  # one call, two builds, each named
    assert both["summary"].count("Tern T2") >= 2 and len(both["data"]) == 2


def test_amend_draft_adds_a_paragraph_to_a_waiting_request_and_its_owner_signs_the_new_text(ctx, db, monkeypatch):
    """O17: the quote item rightly says the open request must also ask to extend the quote past 13 October; it could only tell the buyer."""
    from app.domain.actions import approvers, ledger

    first_ctx, t1 = _clerk(ctx, db, "disruption:SUP-0001", "run-1")
    a = call(t1["draft_supplier_request"], supplier_id="SUP-0001", subject="Revised dates", body="Please confirm the revised promise dates.")["data"]
    quote_ctx, t2 = _clerk(ctx, db, "deadline:SUP-0001:2026-10-13", "run-2")
    monkeypatch.setattr(approvers, "owners_of", lambda d, key: {"Dana Reyes"})  # one buyer owns both items
    out = call(t2["amend_draft"], action_id=a["action_id"], paragraph="Please also confirm that the quote stays valid past its current end date.")
    assert out["data"]["amended"] and out["data"]["action_id"] == a["action_id"] and out["data"]["payload_hash"] != a["payload_hash"] and a["action_id"] in quote_ctx.action_ids
    new = ledger.get(db, a["action_id"])
    assert new.body == "Please confirm the revised promise dates.\n\nPlease confirm that the quote stays valid past its current end date." and new.state == "proposed" and ledger.in_run(db, a["action_id"], "run-2")
    # the old hash is void: the owner can only sign the new text
    try:
        ledger.approve(db, a["action_id"], a["payload_hash"], "Dana Reyes")
        raise AssertionError("an approval of the old text went through")
    except ledger.LedgerError as e:
        assert e.code == "hash"
    # another buyer's request is not this run's to change
    monkeypatch.setattr(approvers, "owners_of", lambda d, key: {"Dana Reyes"} if key.startswith("disruption") else {"Tom Albrecht"})
    refused = call(t2["amend_draft"], action_id=a["action_id"], paragraph="One more ask.")
    assert "belongs to Dana Reyes" in refused["error"]
    # no money words, no figures a tool did not return, nothing once it is sent
    monkeypatch.setattr(approvers, "owners_of", lambda d, key: {"Dana Reyes"})
    assert "bank" in call(t2["amend_draft"], action_id=a["action_id"], paragraph="Please send the new bank details.")["error"]
    assert "numbers no tool returned" in call(t2["amend_draft"], action_id=a["action_id"], paragraph="Please ship 777 more units.")["error"]
    fresh = ledger.get(db, a["action_id"])
    ledger.approve(db, fresh.action_id, fresh.payload_hash, "Dana Reyes")
    assert "already executed" in call(t2["amend_draft"], action_id=a["action_id"], paragraph="Late addition.")["error"]
    assert "no such request" in call(t2["amend_draft"], action_id="A-nope", paragraph="x")["error"]


def test_an_amended_body_still_ends_with_the_signature():
    """FEEDBACK 9.3: the amended paragraph landed after 'Regards, ...'."""
    from app.domain.actions.tools import insert_before_signoff

    body = "Hello,\n\nPlease confirm the revised promise dates.\n\nThis request does not change the terms of any PO.\n\nRegards,\nProcurement"
    out = insert_before_signoff(body, "2. Please extend the quote.")
    assert out.endswith("\n\n2. Please extend the quote.\n\nRegards,\nProcurement") and out.count("Regards") == 1
    assert insert_before_signoff("No closing here.", "2. More.") == "No closing here.\n\n2. More."
    assert insert_before_signoff("A.\n\nBest regards,\nX", "Y.").endswith("Y.\n\nBest regards,\nX")


def test_a_draft_is_signed_by_its_owner_not_by_whoever_the_model_named(ctx, db, monkeypatch):
    """O7 / Approvals: the Ask draft in Dana's To sign was signed 'Marcus Chen / Halden Robotics' (the category buyer) while Dana signs it."""
    from app.domain.actions import approvers
    from app.domain.actions.tools import with_signature

    assert with_signature("Hello.\n\nPlease confirm.\n\nRegards,\nMarcus Chen\nHalden Robotics", "Dana Reyes", "Halden Robotics").endswith("Please confirm.\n\nRegards,\nDana Reyes\nHalden Robotics")
    assert with_signature("Please confirm.", "Dana Reyes", "Halden Robotics") == "Please confirm.\n\nRegards,\nDana Reyes\nHalden Robotics"
    monkeypatch.setattr(approvers, "owners_of_action", lambda d, a: {"Dana Reyes"})  # the owner as the ledger records it differs from the category buyer
    _, t = _clerk(ctx, db, "ask:0e6d8c54", "run-9")
    out = call(t["draft_supplier_request"], supplier_id="SUP-0001", subject="Samples", body="Please send samples.\n\nRegards,\nMarcus Chen\nHalden Robotics")["data"]
    from app.domain.actions import ledger

    body = ledger.get(db, out["action_id"]).body
    assert body.endswith("Regards,\nDana Reyes\nthe company") and "Marcus" not in body and out["payload_hash"] == ledger.get(db, out["action_id"]).payload_hash
    monkeypatch.setattr(approvers, "owners_of_action", lambda d, a: {"Dana Reyes", "Tom Albrecht"})  # two owners: nobody is named
    ledger.reject(db, out["action_id"], "test", "Dana Reyes")  # the contact has no open thread now
    _, t2 = _clerk(ctx, db, "ask:other", "run-10")
    both = call(t2["draft_supplier_request"], supplier_id="SUP-0001", subject="Prices", body="Please hold the price.\n\nRegards,\nProcurement")["data"]
    assert ledger.get(db, both["action_id"]).body.endswith("Regards,\nProcurement\nthe company")   # G4: no single signer, still the company's letter


def test_no_note_is_logged_to_a_buyer_who_already_owns_the_open_question(ctx, db):
    """Khalid: the 'Question for Dana' notes repeat the owned unknowns and inflate the decision history; the unknown with its owner is the one place."""
    from app.domain.actions import ledger
    from app.organism.schemas import Unknown

    from tests.organism.conftest import seed_buyers

    seed_buyers(db)
    _, t = _clerk(ctx, db, "deadline:SUP-0001:2026-10-13", "run-1")
    ctx.unknowns.append(Unknown(what="on-hand stock", why_it_blocks="no inventory", owner="Dana", question="What is on hand?", refs=[]))
    out = call(t["log_buyer_question"], owner="Dana", question="What stock is on hand?")
    assert "already owns an open question" in out["error"] and not [a for a in ledger.list_actions(db) if a.type == "note"]
    ok = call(t["log_buyer_question"], owner="Marcus", question="Which PO is this?")  # a buyer who owns no question here still gets one
    assert ok["data"]["action_id"]


def test_two_buyers_sharing_a_supplier_contact_each_get_their_own_request(ctx, db, monkeypatch):
    """Khalid's unknown:undated run: amend_draft refused 'belongs to another buyer' and the clerk logged a question instead; one open thread per contact AND owner."""
    from app.domain.actions import approvers, ledger

    owners = {"line:a": {"Marcus Chen"}, "line:b": {"Sofia Lind"}}
    monkeypatch.setattr(approvers, "owners_of", lambda d, key: owners.get(key))
    monkeypatch.setattr(approvers, "owners_of_action", lambda d, a: owners.get(a.item_key))
    _, t1 = _clerk(ctx, db, "line:a", "run-1")
    a = call(t1["draft_supplier_request"], supplier_id="SUP-0001", subject="Dates", body="Please confirm the dates for the open lines.")["data"]
    _, t2 = _clerk(ctx, db, "line:b", "run-2")
    b = call(t2["draft_supplier_request"], supplier_id="SUP-0001", subject="Dates for my lines", body="Please confirm the dates for my open lines.")["data"]
    assert b["action_id"] != a["action_id"] and ledger.get(db, b["action_id"]).state == "proposed"  # a request of its own, to the same contact, owned by this line's buyer
    assert len([x for x in ledger.list_actions(db) if x.type == "supplier_request"]) == 2
    refused = call(t2["amend_draft"], action_id=a["action_id"], paragraph="Also this.")
    assert "Draft this item's own request with draft_supplier_request" in refused["error"]


def test_a_note_is_only_for_what_no_supplier_can_answer(ctx, db):
    from app.domain.actions import ledger
    from tests.organism.conftest import seed_buyers

    seed_buyers(db)
    _, t = _clerk(ctx, db, "unknown:undated", "run-1")
    out = call(t["log_buyer_question"], owner="Dana", question="When was the delivery promised for these lines, and can the supplier confirm the revised dates?")
    assert "A supplier can answer that" in out["error"] and not [a for a in ledger.list_actions(db) if a.type == "note"]
    assert call(t["log_buyer_question"], owner="Dana", question="Should the stale order be closed or kept open?")["data"]["action_id"]  # a decision only a person makes


def test_a_joined_ask_gets_one_connector_not_two(ctx, db, monkeypatch):
    """FEEDBACK: the amend read 'Also: Separately, PO …'."""
    from app.domain.actions import approvers, ledger

    monkeypatch.setattr(approvers, "owners_of", lambda d, key: {"Dana Reyes"})
    monkeypatch.setattr(approvers, "owners_of_action", lambda d, a: {"Dana Reyes"})
    _, t1 = _clerk(ctx, db, "line:a", "run-1")
    a = call(t1["draft_supplier_request"], supplier_id="SUP-0001", subject="Dates", body="Please confirm the dates.\n\nRegards,\nDana Reyes")["data"]
    _, t2 = _clerk(ctx, db, "line:b", "run-2")
    call(t2["amend_draft"], action_id=a["action_id"], paragraph="Separately, please extend the quote.")
    assert "\n\nPlease extend the quote.\n\nRegards," in ledger.get(db, a["action_id"]).body


def test_the_clerk_cannot_hand_off_until_every_owed_supplier_has_a_request(ctx, db):
    import asyncio

    from app.organism.specialists.handoff import make_handoff_tool

    ctx.required_suppliers = {"SUP-0001", "SUP-0099"}
    _, t = _clerk(ctx, db, "deadline:chase", "run-1")
    handoff = make_handoff_tool(ctx, "buyers_clerk")
    out = asyncio.run(handoff.handler({"findings": ["Done."]}))
    assert out.get("is_error") and "SUP-0001" in out["content"][0]["text"] and "buyers_clerk" not in ctx.handoffs
    call(t["draft_supplier_request"], supplier_id="SUP-0001", subject="Dates", body="Please confirm the dates for the open lines.")
    out = asyncio.run(handoff.handler({"findings": ["Done."]}))
    assert "SUP-0099" in out["content"][0]["text"] and "SUP-0001" not in out["content"][0]["text"]
    ctx.suppliers_asked.add("SUP-0099")  # a supplier whose request was found covering also counts
    assert not asyncio.run(handoff.handler({"findings": ["Done."]})).get("is_error") and "buyers_clerk" in ctx.handoffs


def test_a_thread_joined_by_an_earlier_run_is_not_re_checked_against_this_runs_evidence(ctx, db, services):
    """FEEDBACK: 'A-d12c227c states numbers that no tool returned: 314' — the 314 EA was written by the undated run, verified there."""
    from app.domain.actions import ledger
    from app.domain.common import EntityRef
    from tests.organism.test_verifier import good, seed

    a = seed(ctx, db)
    other = ledger.propose(db, type="supplier_request", item_key="unknown:undated", run_id="run-earlier", target=EntityRef(type="supplier", id="SUP-0001"), recipient="li.wei@yunzhan-motor.example",
                           subject="Dates", body="Line 20, 314 EA, has no promised date.")
    ledger.link_to_run(db, ctx.run_id, other.action_id)
    ctx.action_ids.append(other.action_id)
    d = good(a); d["action_ids"] = [a.action_id, other.action_id]
    from app.organism.verifier import verify

    assert not any("314" in f for f in verify(ctx, d, services=services)[1].failures)


def test_open_supply_separates_lines_under_a_notice_from_stale_legacy_lines(ctx, services):
    """The agent wrote 'all 12 open Yunzhan lines sit under the force majeure': the notice names 10, and two are stale legacy lines."""
    t = by_name(orders_tools.make_tools(ctx, services.orders))
    body = call(t["open_supply"], supplier_id="SUP-0001")
    rows = body["data"]
    assert rows and all({"under_notice", "stale", "notice_kind"} <= set(r) for r in rows)
    assert sum(r["under_notice"] for r in rows) == len(rows) and not any(r["stale"] for r in rows)       # the fakes hold only the fire's lines
    assert "under the notice (force majeure)" in body["summary"] and "stale" not in body["summary"]


def test_an_ask_on_a_case_adds_to_the_cases_waiting_draft_and_a_new_request_is_staged_under_the_case(ctx, db, monkeypatch):
    """Rev 4.1 (F100): a custom direction from Ask on the fire ('also ask Li Wei what stock survived') appends to the fire's waiting draft, never
    rewrites it, and anything new it stages belongs to the case (its Approval card, its owner), not to the ask:… key."""
    from dataclasses import replace

    from app.domain.actions import approvers, ledger

    monkeypatch.setattr(approvers, "owners_of", lambda d, key: {"Dana Reyes"} if key and key.startswith("disruption") else None)   # an ask: key has no owner
    _, fire = _clerk(ctx, db, "disruption:SUP-0001", "run-fire")
    a = call(fire["draft_supplier_request"], supplier_id="SUP-0001", subject="Revised dates", body="Please confirm the revised promise dates.")["data"]
    ask_ctx, ask = _clerk(ctx, db, "ask:1234abcd", "run-ask")
    ask_ctx.action_item_key = "disruption:SUP-0001"
    out = call(ask["draft_supplier_request"], supplier_id="SUP-0001", subject="Stock that survived", body="Please tell us what finished stock survived and whether it can fly.")
    assert out["data"]["must_amend"] == a["action_id"]                                   # the case's draft is not rewritten by the ask
    amended = call(ask["amend_draft"], action_id=a["action_id"], paragraph="Please tell us what finished stock survived and whether it can fly.")
    assert amended["data"]["amended"] and ledger.get(db, a["action_id"]).body.startswith("Please confirm the revised promise dates.")
    ledger.reject(db, a["action_id"], "test", "Dana Reyes")
    new = call(ask["draft_supplier_request"], supplier_id="SUP-0001", subject="Stock that survived", body="Please tell us what finished stock survived.")["data"]
    assert ledger.get(db, new["action_id"]).item_key == "disruption:SUP-0001"           # staged under the case, so its owner signs it
    plain_ctx, plain = _clerk(ctx, db, "ask:feedbeef", "run-ask-2")                    # an ask with no case on screen keeps its own key
    other = call(plain["draft_supplier_request"], supplier_id="SUP-0001", subject="x", body="Please confirm the revised promise dates for the motor.")
    assert "covered_by" in other["data"] or "must_amend" in other["data"] or ledger.get(db, other["data"]["action_id"]).item_key == "ask:feedbeef"


def test_ask_for_changes_on_a_draft_works_on_that_drafts_case_and_is_told_to_amend(db):
    """Rev 4.1 step 3: 'Ask for changes' is an Ask scoped to the draft; it is on that draft's case (an amend, new hash, the owner signs again), never a second email."""
    from app.domain.actions import ledger
    from app.domain.common import EntityRef
    from app.organism.workflows.ask import build_prompt, case_of

    a = ledger.propose(str(db), type="supplier_request", item_key="disruption:SUP-0001", run_id="run-1", target=None, recipient="x@sup.example", subject="s", body="b")
    ctx = EntityRef(type="action", id=a.action_id)
    assert case_of(ctx, str(db)) == "disruption:SUP-0001"
    assert "amend_draft(action_id='" + a.action_id + "'" in build_prompt("Make it firmer on the date", ctx, "Dana Reyes")
    ledger.reject(str(db), a.action_id, "no", "Dana Reyes")
    assert case_of(ctx, str(db)) is None  # only a waiting draft can be changed
    assert case_of(EntityRef(type="action", id="A-nope"), str(db)) is None and case_of(ctx) is None
    t = ledger.propose(str(db), type="supplier_request", item_key="trust:x", run_id="run-2", target=None, recipient="y@sup.example", subject="s", body="b")
    assert case_of(EntityRef(type="action", id=t.action_id), str(db)) is None  # never a trust case


def test_an_ask_on_a_case_always_appends_even_when_its_rewrite_reads_as_the_same_ask(ctx, db, monkeypatch):
    """SIDEQ (1) / run-ba8770b8: the clerk rewrote the whole fire email with one new ask; same_ask judged it the same and the new ask was lost.
    From Ask on a case with a waiting draft, the request ALWAYS goes through amend_draft: the draft keeps all its lines plus a numbered paragraph."""
    from app.domain.actions import approvers, ledger

    monkeypatch.setattr(approvers, "owners_of", lambda d, key: {"Dana Reyes"} if key and key.startswith("disruption") else None)
    lines = "\n".join(f"HPO-26-00{n}/10" for n in range(450, 460))
    _, fire = _clerk(ctx, db, "disruption:SUP-0001", "run-fire")
    a = call(fire["draft_supplier_request"], supplier_id="SUP-0001", subject="Revised dates for the lines in your notice", body=f"Please confirm the revised promise dates for these lines.\n\n{lines}")["data"]
    assert ledger.same_ask(f"Revised dates for the lines in your notice Please confirm the revised promise dates for these lines.\n\n{lines}",
                           f"Revised dates for the lines in your notice Please confirm the revised promise dates for these lines, and ship the past-due lines from the other plant first.\n\n{lines}")  # the trap: it reads as the same ask
    ask_ctx, ask = _clerk(ctx, db, "ask:5a5a5a5a", "run-ask")
    ask_ctx.action_item_key = "disruption:SUP-0001"
    out = call(ask["draft_supplier_request"], supplier_id="SUP-0001", subject="Revised dates for the lines in your notice",
               body=f"Please confirm the revised promise dates for these lines, and ship the past-due lines from the other plant first.\n\n{lines}")
    assert out["data"]["must_amend"] == a["action_id"] and "covered_by" not in out["data"]
    call(ask["amend_draft"], action_id=a["action_id"], paragraph="Please ship the past-due lines from the other plant first.")
    body = ledger.get(db, a["action_id"]).body
    assert all(f"HPO-26-00{n}/10" in body for n in range(450, 460)) and "other plant first" in body and body.startswith("Please confirm the revised promise dates for these lines.")
    assert len([x for x in ledger.list_actions(db) if x.type == "supplier_request"]) == 1


def test_robots_the_open_orders_cover_are_a_tool_figure_whichever_lookup_runs_first(ctx, services):
    """BUYER Q4: 'If Hallerbeck stops today, how many Porters can we still build?' needs open qty / per robot as a code figure ('up to N robots,
    stock not on file'); the model never does the arithmetic. Written by whichever of the two lookups runs second."""
    import math
    from dataclasses import replace

    t = by_name(orders_tools.make_tools(ctx, services.orders))
    call(t["open_supply"], part_number="HR-40110")
    b = by_name(bom_tools.make_tools(ctx, services.bom))
    body = call(b["where_used_for_parts"], part_numbers=["HR-40110"])
    cover = {n["id"]: n for n in body["numbers"] if n["id"].startswith("cover:")}
    per = {n["id"]: n for n in body["numbers"] if n["id"].endswith(":per_robot")}
    assert cover and set(ctx.evidence) >= set(cover)
    for cid, n in cover.items():
        product = cid.split(":")[2]
        expect = math.floor(Decimal(ctx.evidence["supply:HR-40110:open_qty"].value) / Decimal(per[f"bom:HR-40110:{product}:per_robot"]["value"]))
        assert Decimal(n["value"]) == expect and n["unit"] == "robots" and "before stock on hand" in n["name"] and "if all of it goes to the" in n["name"] and "never to be added" in n["name"]
    # the other order: where-used first, then open supply
    c2 = replace(ctx, evidence={}, run_id="run-t2")
    call(by_name(bom_tools.make_tools(c2, services.bom))["where_used_for_parts"], part_numbers=["HR-40110"])
    again = call(by_name(orders_tools.make_tools(c2, services.orders))["open_supply"], part_number="HR-40110")
    assert {n["id"] for n in again["numbers"] if n["id"].startswith("cover:")} == set(cover)


def test_ask_stages_a_bridge_order_as_a_decision_on_the_case_for_its_owner(ctx, db, monkeypatch):
    """BUYER Q5: 'Draft a bridge order of 200' staged nothing and told Dana to do it. It is now a decision record (P7's shape) on the case's Approval card,
    PROPOSED; the owner signs; approving records it and sends nothing."""
    from app.domain.actions import approvers, ledger

    monkeypatch.setattr(approvers, "owners_of", lambda d, key: {"Dana Reyes"} if key and key.startswith("risk:") else None)
    ask_ctx, t = _clerk(ctx, db, "ask:b1d9e000", "run-ask")
    ask_ctx.action_item_key = "risk:SUP-0002"
    ask_ctx.asked_numerals.add(Decimal(200))
    out = call(t["stage_decision"], decision="Planned bridge order HR-12210 · 200 · no prepayment", reason="Hallerbeck may stop; secure the gearbox for Porter")["data"]
    a = ledger.get(db, out["action_id"])
    assert a.item_key == "risk:SUP-0002" and a.state == "proposed" and a.subject == "Decision" and a.change["kind"] == "record" and a.change["owner"] == "Dana Reyes" and a.recipient is None
    assert "777" in call(t["stage_decision"], decision="Planned order HR-12210 · 777", reason="x")["error"]  # a figure neither a tool nor the buyer gave
    assert "bank" in call(t["stage_decision"], decision="Pay into the new bank account", reason="x")["error"]
    done = ledger.approve(db, a.action_id, a.payload_hash, "Dana Reyes")
    assert done.state in ("executed", "approved") and not ledger.outbox(db)  # recorded, nothing sent
    # nowhere to land: an Ask with no case, and never a trust item
    no_case, t2 = _clerk(ctx, db, "ask:00000000", "run-ask-2")
    assert "only on a case" in call(t2["stage_decision"], decision="Wait", reason="x")["error"]
    found = call(t2["stage_decision"], decision="Wait for the reply", reason="x", item_key="risk:SUP-0002")["data"]  # asked from Today: the case the agent found
    assert ledger.get(db, found["action_id"]).item_key == "risk:SUP-0002"
    assert "no owner" in call(t2["stage_decision"], decision="Wait", reason="x", item_key="nope:x")["error"]
    assert "only on a case" in call(t2["stage_decision"], decision="Wait", reason="x", item_key="trust:x")["error"]
    trust, t3 = _clerk(ctx, db, "ask:11111111", "run-ask-3")
    trust.action_item_key = "trust:x"
    assert "only on a case" in call(t3["stage_decision"], decision="Wait", reason="x")["error"]


def test_a_work_item_run_cannot_stage_a_decision_nobody_asked_for(ctx, db, monkeypatch):
    """AGENT-EXPERT M1: stage_decision is in the clerk's tools for every workflow; only an Ask (the buyer asked) may stage a decision."""
    from app.domain.actions import approvers, ledger

    monkeypatch.setattr(approvers, "owners_of", lambda d, key: {"Dana Reyes"})
    case_ctx, t = _clerk(ctx, db, "risk:SUP-0002", "run-case")
    out = call(t["stage_decision"], decision="Planned order of the gearbox", reason="x")
    assert "only when the buyer asks" in out["error"] and not [a for a in ledger.list_actions(db) if a.subject == "Decision"]


def test_a_repeat_handoff_read_waits_for_a_running_teammate_instead_of_burning_turns(ctx, monkeypatch):
    """Live Ask run-5cd3e9d2 (BUYER Q7): Lookout polled get_handoffs while the sourcing analyst worked; each refusal cost a turn, and the run hit
    its turn limit with no answer. A repeat read now waits (bounded) for the running teammate's handoff and returns it."""
    import asyncio as aio

    from app.organism import lookout_tools
    from app.organism.schemas import Handoff

    monkeypatch.setattr(lookout_tools, "HANDOFF_WAIT_S", 3.0)
    t = by_name(lookout_tools.make_tools(ctx))["get_handoffs"]
    ctx.handoffs["supply_planner"] = Handoff(findings=["a"], number_ids=[], unknowns=[], action_ids=[])
    call(t)  # first read
    ctx.running.add("agent-sourcing")

    async def both():
        async def lands():
            await aio.sleep(0.6)
            ctx.handoffs["sourcing_analyst"] = Handoff(findings=["b"], number_ids=[], unknowns=[], action_ids=[])
            ctx.running.discard("agent-sourcing")
        _, out = await aio.gather(lands(), t.handler({}))
        return json.loads(out["content"][0]["text"])

    got = aio.run(both())
    assert "sourcing_analyst" in got["data"]  # waited for it, did not refuse
    again = call(t)  # nothing running, nothing new: refused at once
    assert "Write the Recommendation" in again["error"]


def test_a_draft_that_counts_lines_late_before_the_notice_is_refused(ctx, db):
    """LOOKOUT P1 / AGENT-EXPERT: 'Four were already past their promised dates before the fire' (three were; four on 25 September). Code refuses it; the clerk rewrites."""
    _, t = _clerk(ctx, db, "disruption:SUP-0001", "run-bn")
    bad = call(t["draft_supplier_request"], supplier_id="SUP-0001", subject="Revised dates", body="Four were already past their promised dates before the fire. Please confirm revised dates.")
    assert "past due on 25 September" in bad["error"]
    ok = call(t["draft_supplier_request"], supplier_id="SUP-0001", subject="Revised dates", body="The lines marked below were already past due. Please confirm revised dates.")
    assert "action_id" in ok["data"]                                                   # past due without a "before the notice" count is fine


def test_an_incident_letter_never_asks_for_an_allocation(ctx, db):
    """G3 (PREVIEW 2b): nothing is under a force majeure on an incident, so there is nothing to allocate from."""
    _, t = _clerk(ctx, db, "incident:SUP-0018", "run-g3")
    out = call(t["draft_supplier_request"], supplier_id="SUP-0018", subject="Dates", body="Please allocate from your other line and confirm the new dates.")
    assert out.get("is_error") or "no allocation" in json.dumps(out)
    ok = call(t["draft_supplier_request"], supplier_id="SUP-0018", subject="Dates", body="Please confirm the new dates hold.")
    assert "action_id" in json.dumps(ok)


def test_an_origin_letter_names_only_parts_that_supplier_supplied(ctx, db):
    """BUYER R2b (COO regression): each of the four origin letters listed the other suppliers' parts."""
    import sqlite3

    with sqlite3.connect(db) as con:   # the supplier's own order lines: the only parts its letter may name
        con.execute("CREATE TABLE po_lines (identity_id TEXT, part_number TEXT)")
        con.executemany("INSERT INTO po_lines VALUES (?, ?)", [("SUP-0001", "HR-40210"), ("SUP-0018", "HR-51110")])
    _, t = _clerk(ctx, db, "unknown:origin", "run-coo")
    out = call(t["draft_supplier_request"], supplier_id="SUP-0001", subject="Origin", body="Please send the certificate of origin for HR-40210 and HR-51110.")
    assert "HR-51110" in json.dumps(out) and "action_id" not in json.dumps(out)
    ok = call(t["draft_supplier_request"], supplier_id="SUP-0001", subject="Origin", body="Please send the certificate of origin for HR-40210.")
    assert "action_id" in json.dumps(ok)


def test_the_clerk_is_told_the_r2b_letter_rules():
    """BUYER R2b: units on quantities, a split line written once, quote and part ids, no held quantity or re-confirmed validity, origin letters without the hedge."""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / "app" / "organism" / "specialists" / "buyers_clerk" / "instructions.md").read_text()
    for rule in ('("120 EA")', "A split line is written once", "name the quote by its number and each part by name and part number",
                 'never ask about a quantity "held"', "never ask to confirm a validity date", "between two of the quote's", "Never add a hedge"):
        assert rule in text, rule


def test_a_stale_order_case_never_emails_a_supplier(ctx, db):
    """AGENT-EXPERT / SIDEQ (R2b): the aged-POs run drafted two supplier emails, one to a supplier mid-fire; a stale order is a note to the owning buyer."""
    from app.domain.actions import ledger

    _, t = _clerk(ctx, db, "unknown:stale-orders", "run-stale")
    out = call(t["draft_supplier_request"], supplier_id="SUP-0001", subject="PO-10711", body="Please confirm whether PO-10711 line 1 shipped.")
    assert "a stale order is a note" in json.dumps(out) and "action_id" not in json.dumps(out)       # must FAIL to stage
    assert not [a for a in ledger.list_actions(db) if a.type == "supplier_request"]
    from tests.organism.conftest import seed_buyers

    seed_buyers(db)   # the re-record: log_buyer_question refused the Receiving question as one "a supplier can answer", so the run staged nothing at all
    note = call(t["log_buyer_question"], owner="Dana Reyes", question="Please ask Receiving whether PO-10711 line 1 arrived (promised 21 March 2025) and the quantity received.")
    assert "action_id" in json.dumps(note) and [a.type for a in ledger.list_actions(db)] == ["note"]


def test_a_note_to_planning_asked_in_ask_is_staged_for_the_owners_signature_not_recorded(ctx, db, monkeypatch):
    """LOOKOUT P1 (27a3ed0): 'Prepare a note to planning to re-sequence the October builds' was recorded as executed by log_buyer_question while the
    answer said 'staged for your signature'. A note the buyer asks for is P7's note: PROPOSED on the case, the owner signs, nothing is sent."""
    from app.domain.actions import approvers, ledger

    monkeypatch.setattr(approvers, "owners_of", lambda d, key: {"Dana Reyes"} if key and key.startswith("disruption:") else None)
    ask_ctx, t = _clerk(ctx, db, "ask:note0001", "run-ask")
    ask_ctx.action_item_key = "disruption:SUP-0001"
    out = call(t["stage_decision"], decision="Re-sequence the October builds around the short motors", reason="the motors are short in October", to="planning")["data"]
    a = ledger.get(db, out["action_id"])
    assert a.state == "proposed" and a.subject == "Note to planning" and a.change["kind"] == "note" and a.change["to"] == "planning" and a.change["owner"] == "Dana Reyes" and a.recipient is None
    done = ledger.approve(db, a.action_id, a.payload_hash, "Dana Reyes")
    assert done.state in ("executed", "approved") and not ledger.outbox(db)


def test_in_ask_a_note_cannot_be_recorded_on_its_own_only_staged(ctx, db):
    """LOOKOUT P1 live (d4a735e): the agent logged the planning note as a 'question for Dana', executed and unsigned. In Ask, log_buyer_question is refused."""
    from app.domain.actions import ledger

    ask_ctx, t = _clerk(ctx, db, "ask:note0002", "run-ask")
    out = call(t["log_buyer_question"], owner="Dana", question="Re-sequence the October builds around the short motors")
    assert "stage_decision" in out["error"] and not [a for a in ledger.list_actions(db) if a.type == "note"]


def test_an_amend_checks_only_its_own_paragraph_not_the_waiting_drafts_subject(ctx, db, monkeypatch):
    """AGENT-EXPERT on re-record B: the origin run's paragraph to Jadepeak was refused 3x for '18 September', a date in the SUBJECT the slip run wrote and checked."""
    from app.domain.actions import approvers, ledger

    monkeypatch.setattr(approvers, "owners_of", lambda d, key: {"Dana Reyes"})
    first = ledger.propose(db, type="supplier_request", item_key="disruption:SUP-0001", run_id="run-1", target=None, recipient="li.wei@yunzhan-motor.example",
                           subject="Revised dates after your notice of 18 September", body="Dear Li Wei,\n\nPlease confirm the revised dates.\n\nRegards,\nDana Reyes")
    _, t = _clerk(ctx, db, "unknown:origin", "run-2")
    out = call(t["amend_draft"], action_id=first.action_id, paragraph="Please also send the certificate of origin for the drive motor.")
    assert "action_id" in json.dumps(out) and "18 September" not in json.dumps(out.get("error", ""))
    body = ledger.get(db, first.action_id).body
    assert "\n\nPlease send the certificate of origin" in body and "Also:" not in body and "Please also" not in body
    bad = call(t["amend_draft"], action_id=first.action_id, paragraph="Please confirm by 3 December.")   # must FAIL: a date in the new paragraph is still checked
    assert "3 December" in json.dumps(bad)
