"""The verifier, with no model: every claim is matched to a tool output or the run does not pass."""

from decimal import Decimal

import pytest

from app.domain.actions import ledger
from app.domain.common import EntityRef, Unknown
from app.organism.schemas import Number
from app.organism.verifier import numerals, verify

ON_HAND = Unknown(what="On-hand stock of HR-40110", why_it_blocks="x", owner="Dana", question="How many are on the shelf?")


def seed(ctx, db):
    ctx.register([Number(id="shortage:HR-40110:2026-10:short", name="Units short in 2026-10", value=Decimal(364), unit="EA"),
                  Number(id="supply:HR-40110:stuck_qty", name="Quantity on disrupted lines", value=Decimal(1140), unit="EA")])
    ctx.unknowns.append(ON_HAND)
    ctx.seen_dates.add((10, 10))  # the date a tool gave (the notice promises revised dates by 10 October)
    ctx.handoffs.update(supply_planner=object(), buyers_clerk=object())
    ctx.handoffs_seen = set(ctx.handoffs)  # Lookout read both before writing
    a = ledger.propose(db, type="supplier_request", item_key=ctx.item_key, run_id=ctx.run_id, target=EntityRef(type="supplier", id="SUP-0001"),
                       recipient="li.wei@yunzhan-motor.example", subject="Revised promise dates", body="Please confirm revised dates for HPO-26-00614 line 10 by 2026-10-10.")
    ctx.action_ids.append(a.action_id)
    return a


def good(a):
    return {"finding": "October Tern build is 364 EA short; 1,140 EA are stuck at Yunzhan.", "numbers": [
        {"id": "shortage:HR-40110:2026-10:short", "value": 364}, {"id": "supply:HR-40110:stuck_qty", "value": 1140}],
        "assumptions": ["Disrupted lines are not counted as arriving."], "would_change": ["Revised dates before 10 October."],
        "open_questions": [ON_HAND.model_dump()], "action_ids": [a.action_id], "next_step": {"who": "Dana Reyes", "what": "Ask the supplier for revised dates", "by": ""}}


def test_a_faithful_recommendation_passes(ctx, db, services):
    a = seed(ctx, db)
    rec, v = verify(ctx, good(a), services=services)
    assert v.passed, v.failures
    assert (v.numbers_checked, v.numbers_from_tools, v.open_questions_with_owner) == (2, 2, 1)
    assert rec.action_ids == [a.action_id] and rec.numbers[0].name


def test_a_wrong_value_fails(ctx, db, services):
    a = seed(ctx, db); d = good(a); d["numbers"][0]["value"] = 365
    assert any("365" in f for f in verify(ctx, d, services=services)[1].failures)


def test_an_invented_id_fails(ctx, db, services):
    a = seed(ctx, db); d = good(a); d["numbers"].append({"id": "made:up", "value": 5})
    assert any("made:up" in f for f in verify(ctx, d, services=services)[1].failures)


def test_a_number_in_the_prose_that_no_tool_returned_fails(ctx, db, services):
    a = seed(ctx, db); d = good(a); d["finding"] += " That is about 40% of the build."
    r = verify(ctx, d, services=services)[1]; assert r.passed and "40" in r.unchecked and any("prose" in w and "40" in w for w in r.warnings)  # delivered, the figure marked


def test_ids_and_dates_are_not_numerals():
    assert numerals("HPO-26-00614/10 for HR-40110 by 2026-10-13, 10 October, Oct 15 in 2026, Q4, lines 10 and 20") == []
    assert numerals("1. First\n2. Second\nzero is 0") == []
    assert numerals("short by 1,140 and 3.5") == [Decimal(1140), Decimal("3.5")]


def test_an_unknown_a_tool_raised_is_carried_into_the_recommendation_by_code(ctx, db, services):
    a = seed(ctx, db); d = good(a); d["open_questions"] = []
    rec, v = verify(ctx, d, services=services)
    assert v.passed and [q.what for q in rec.open_questions] == ["On-hand stock of HR-40110"]


def test_a_specialist_that_did_not_hand_off_fails(ctx, db, services):
    a = seed(ctx, db); del ctx.handoffs["buyers_clerk"]
    assert any("handoffs" in f for f in verify(ctx, good(a), services=services)[1].failures)


def test_a_draft_stating_an_untooled_number_fails(ctx, db, services):
    a = seed(ctx, db)
    bad = ledger.propose(db, type="supplier_request", item_key=ctx.item_key, run_id=ctx.run_id, target=EntityRef(type="supplier", id="SUP-0001"),
                         recipient="li.wei@yunzhan-motor.example", subject="Allocation", body="Please ship 900 units.")
    ctx.action_ids.append(bad.action_id)
    assert any("900" in f for f in verify(ctx, good(a), services=services)[1].failures)


def test_a_draft_to_an_address_that_is_not_the_contact_on_file_fails(ctx, db, services):
    a = seed(ctx, db)
    evil = ledger.propose(db, type="supplier_request", item_key=ctx.item_key, run_id=ctx.run_id, target=EntityRef(type="supplier", id="SUP-0001"),
                          recipient="payments@yunzhan-motor-pay.example", subject="Details", body="Confirm please.")
    ctx.action_ids.append(evil.action_id)
    assert any("contact on file" in f for f in verify(ctx, good(a), services=services)[1].failures)


def test_nothing_may_be_drafted_on_a_trust_item(ctx, db, services):
    a = seed(ctx, db); ctx.stage_allowed = False
    assert any("allows no drafting" in f for f in verify(ctx, good(a), services=services)[1].failures)


def test_an_unparseable_recommendation_fails_closed(ctx, services):
    rec, v = verify(ctx, {"finding": 3}, services=services)
    assert rec is None and not v.passed
    rec, v = verify(ctx, None, services=services)
    assert rec is None and not v.passed


def test_a_run_over_its_cap_fails(ctx, db, services):
    a = seed(ctx, db)
    assert any("budget" in f for f in verify(ctx, good(a), services=services, cost_usd=2.0, max_cost_usd=1.0)[1].failures)


def test_headline_numbers_are_added_by_code_and_flagged(ctx, db, services):
    a = seed(ctx, db); d = good(a); d["numbers"] = d["numbers"][:1]  # the model cited only one figure
    rec, v = verify(ctx, d, services=services, headline=["supply:HR-40110:stuck_qty", "shortage:HR-40110:2026-10:short"])
    assert v.passed
    assert [(n.id, n.headline) for n in rec.numbers] == [("shortage:HR-40110:2026-10:short", True), ("supply:HR-40110:stuck_qty", True)]


def test_a_kind_that_needs_a_tool_fails_when_nobody_called_it(ctx, db, services):
    a = seed(ctx, db); ctx.tools_called.update({"open_supply"})
    f = verify(ctx, good(a), services=services, required_tools=("open_supply", "shortage"))[1].failures
    assert any("shortage" in x for x in f) and not any("open_supply" in x for x in f)


def test_a_logged_question_for_a_buyer_is_a_valid_action_and_leaves_nothing_to_send(ctx, db, services):
    a = seed(ctx, db)
    note = ledger.record_app_action(db, type="note", item_key=ctx.item_key, target=EntityRef(type="item", id=ctx.item_key), body="Question for Dana: where is it made?", by="Lookout", run_id=ctx.run_id)
    ctx.action_ids.append(note.action_id)
    assert verify(ctx, good(a), services=services)[1].passed
    assert ledger.outbox(db) == []


def test_the_fire_must_examine_the_shortage_of_every_part_it_disrupts(ctx, db, services):
    a = seed(ctx, db); ctx.calls_made.add(("shortage", "HR-40110"))
    f = verify(ctx, good(a), services=services, required_calls=[("shortage", "HR-40110"), ("shortage", "HR-40210")])[1].failures
    assert any("HR-40210" in x for x in f) and not any("HR-40110" in x for x in f)


def test_a_numeral_a_tool_returned_inside_text_may_be_quoted(ctx, db, services):
    a = seed(ctx, db); d = good(a); d["finding"] += " The part is a 30:1 gearhead."
    r = verify(ctx, d, services=services)[1]; assert r.passed and r.unchecked  # not a tool figure: stray, shown marked
    ctx.seen_numerals.update(numerals("gearhead, spur, 30:1, for 60 mm lift motor"))
    assert verify(ctx, d, services=services)[1].passed


def test_a_requirement_may_name_alternatives(ctx, db, services):
    a = seed(ctx, db); ctx.tools_called.add("exposure_for_part")
    assert verify(ctx, good(a), services=services, required_tools=(("get_item", "exposure_for_part"),))[1].passed
    f = verify(ctx, good(a), services=services, required_tools=(("get_item", "compare_offers"),))[1].failures
    assert any("get_item or compare_offers" in x for x in f)


def test_money_is_said_the_way_a_buyer_says_it_and_only_that_rounding_is_allowed(ctx, db, services):
    from app.organism.toolkit import money_words

    assert money_words(1539053.57) == "$1.54M" and money_words(552071.76) == "$552K" and money_words(43472.93) == "$43K" and money_words(8009.32) == "$8,009.32"
    assert money_words(188.9875) == "$188.99" and money_words(191.08) == "$191.08" and money_words(150) == "$150" and money_words(0.24058) == "$0.2406"
    a = seed(ctx, db)
    ctx.register([Number(id="tariff:all:net", name="net", value=Decimal("1539053.57"), unit="USD")])
    d = good(a); d["finding"] = "The new duty is $1.54M net."
    assert verify(ctx, d, services=services)[1].passed
    d["finding"] = "The new duty is $1.6M net."  # a rounding the tool did not offer
    r = verify(ctx, d, services=services)[1]; assert r.passed and any("prose" in w for w in r.warnings) and r.reasons


def test_a_supplier_id_or_a_role_title_in_a_sentence_a_buyer_reads_fails_the_check(ctx, db, services):
    """Round 6, found by the prose judge: 'SUP-0041' and 'planning lead' in buyer-facing text. A PO or part number is fine; a supplier is named."""
    a = seed(ctx, db); d = good(a); d["finding"] += " SUP-0001 cannot ship."
    _, v = verify(ctx, d, services=services)
    assert not v.passed and any(f.startswith("names:") and "SUP-0001" in f for f in v.failures)
    d = good(a); d["would_change"] = ["The planning lead confirming the build plan."]
    _, v = verify(ctx, d, services=services)
    assert not v.passed and any("planning lead" in f for f in v.failures)
    d = good(a); d["open_questions"] = [{"what": "which builds can move", "why_it_blocks": "no plan", "owner": "planning lead", "question": "Can they?"}]
    assert any("role title" in f for f in verify(ctx, d, services=services)[1].failures)  # an owner is a person or a function
    d = good(a); d["points"] = [{"label": "Lines", "text": "PO HPO-26-00450 line 10 and part HR-40110 are named as a buyer does."}]
    assert verify(ctx, d, services=services)[1].passed


def test_a_role_title_a_tool_uses_for_an_owner_is_carried_in_in_a_buyers_words(ctx, db, services):
    from app.domain.common import Unknown

    a = seed(ctx, db)
    ctx.unknowns.append(Unknown(what="which builds can move", why_it_blocks="customer dates are not in the data", owner="planning lead", question="Ask the planning lead which can move."))
    rec, v = verify(ctx, good(a), services=services)
    q = next(x for x in rec.open_questions if x.what == "which builds can move")
    assert v.passed and q.owner == "planning" and "planning lead" not in q.question


def test_the_same_question_for_many_builds_is_one_question_with_a_count(ctx, db, services):
    from app.domain.common import Unknown

    a = seed(ctx, db)
    ctx.unknowns.extend(Unknown(what=f"Whether {n} parts with no open order are in stock for build {i}", why_it_blocks="no stock count is loaded", owner="Dana", question="How many are on the shelf?") for i, n in enumerate((17, 51, 6, 4, 8)))
    rec, v = verify(ctx, good(a), services=services)
    stock = [q for q in rec.open_questions if q.why_it_blocks == "no stock count is loaded"]
    assert len(stock) == 1 and "(and 4 like it)" in stock[0].what and v.open_questions == 2 and v.passed


def test_an_honest_i_dont_know_needs_no_lookup_but_a_claim_does(ctx, db, services):
    ctx.open_plan = True  # Ask: nobody was delegated to, so nobody owes a handoff
    nothing = {"finding": "I can't say: the data does not hold it.", "numbers": [], "next_step": {"who": "Dana Reyes", "what": "Find the on-hand count", "by": ""}, "open_questions": [ON_HAND.model_dump()]}
    assert verify(ctx, nothing, services=services, required_tools=(("get_item",),), lookup_only_if_claims=True)[1].passed
    claim = {"finding": "The shortage is 364 EA.", "numbers": []}
    assert not verify(ctx, claim, services=services, required_tools=(("get_item",),), lookup_only_if_claims=True)[1].passed


def test_dates_are_the_same_date_however_they_are_written():
    from app.organism.verifier import dates_in

    assert dates_in("by 13 November, Nov 13 and 2026-11-13; also October") == {(11, 13)}
    assert dates_in("22 September and 1st October") == {(9, 22), (10, 1)}


def test_a_date_no_tool_returned_is_rejected_in_the_text_and_in_a_draft(ctx, db, services):
    a = seed(ctx, db); d = good(a); d["finding"] += " Yunzhan estimates 13 November."
    f = verify(ctx, d, services=services)[1].failures
    assert any("13 November" in x and "dates" in x for x in f)
    ctx.seen_dates.add((11, 13))
    assert verify(ctx, d, services=services)[1].passed  # once a tool has returned it, it may be quoted


def test_the_prompts_say_today_is_the_data_date_in_words():
    from app.organism.prompts import TODAY_WORDS, build_system_prompt
    from app.organism.specialists.registry import SPECIALISTS

    assert TODAY_WORDS.startswith("Friday 25 September 2026") and "Friday 25 September 2026" in build_system_prompt()
    for s in SPECIALISTS.values():
        assert "Friday 25 September 2026" in s.instructions and "never use any other date as today" in s.instructions


def test_prose_that_says_today_is_another_date_fails_and_days_left_stay_the_tools(ctx, db, services):
    a = seed(ctx, db); d = good(a)
    ctx.seen_dates.add((10, 10))
    d["assumptions"] = ["Today is 10 October, so the quote has about 3 days left and the 18-day figure looks stale."]
    f = verify(ctx, d, services=services)[1].failures
    assert any("says today is 10 October" in x and "25 September" in x for x in f)
    d["assumptions"] = ["Today is 25 September, the data date."]
    ctx.seen_dates.add((9, 25))
    assert verify(ctx, d, services=services)[1].passed


def test_an_answer_written_before_reading_a_handoff_fails_and_is_sent_back(ctx, db, services):
    a = seed(ctx, db)
    ctx.handoffs_seen = {"supply_planner"}  # it read the planner's, not the clerk's
    f = verify(ctx, good(a), services=services)[1].failures
    assert any("before reading the handoff of buyers_clerk" in x for x in f)


def test_words_about_how_the_app_works_are_a_warning_in_the_answer(ctx, db, services):
    from app.organism.verifier import internal_words

    assert internal_words("After the handoff from the specialist, get_handoffs shows the tool result as JSON") == ["get_handoffs", "handoff", "json", "specialist", "tool"]
    assert internal_words("Yunzhan's force majeure leaves the Tern T2 short from October; Dana should call Li Wei.") == []
    a = seed(ctx, db); d = good(a); d["assumptions"] = ["The specialist handed off before the verifier ran."]
    _, v = verify(ctx, d, services=services)
    assert v.passed and any("specialist" in w for w in v.warnings)  # soft: worth a look, never a failure


def test_a_draft_with_plumbing_or_a_supplier_id_is_refused_before_it_exists(ctx, services, db):
    import asyncio

    from app.domain.actions import ledger
    from app.domain.actions import tools as action_tools

    t = {x.name: x for x in action_tools.make_tools(ctx, services.suppliers)}
    for body in ("Per the handoff from our specialist, please confirm.", "Regarding SUP-0001, please confirm dates."):
        out = asyncio.run(t["draft_supplier_request"].handler({"supplier_id": "SUP-0001", "subject": "Dates", "body": body}))
        assert out.get("is_error") and "buyer" in out["content"][0]["text"]
    assert ledger.list_actions(db) == []


def test_a_teammates_title_in_buyer_prose_is_an_internal_word():
    from app.organism.verifier import internal_words

    assert internal_words("The clerk has finished, but the planner found nothing.") == ["clerk", "planner"]
    assert internal_words("I've asked Tom Albrecht and staged a request to Yunzhan.") == []


def test_a_figure_said_of_the_wrong_robot_or_month_fails_though_its_value_is_right(ctx, services):
    from app.organism.schemas import Number
    from app.organism.verifier import binding_failures

    ctx.register([Number(id="req:HR-40110:2026-10", name="Requirements for October for HR-40110", value=364, unit="EA")])
    assert binding_failures(ctx, "The Tern T2 needs 364 of them in October.", services) == []
    wrong_robot = binding_failures(ctx, "The Porter P5 needs 364 of them in October.", services)
    assert wrong_robot and "said of the Porter" in wrong_robot[0] and "Tern" in wrong_robot[0]
    wrong_month = binding_failures(ctx, "The Tern T2 needs 364 of them in November.", services)
    assert wrong_month and "said of November" in wrong_month[0] and "October" in wrong_month[0]
    assert binding_failures(ctx, "The Tern T2 needs 400 of them.", services) == []  # a value no tool gave is the other check's business


def _halden_tables(db):
    import sqlite3

    with sqlite3.connect(str(db)) as con:
        con.execute("CREATE TABLE products (part_number TEXT, name TEXT, family TEXT)")
        con.execute("CREATE TABLE buyers (id TEXT, name TEXT, initials TEXT)")
        con.execute("CREATE TABLE parts (part_number TEXT, kind TEXT, category TEXT, buyer_id TEXT)")
        con.executemany("INSERT INTO products VALUES (?, ?, ?)", [("P1", "Alpha 1", "Alpha"), ("P2", "Beta 2", "Beta")])
        con.executemany("INSERT INTO buyers VALUES (?, ?, ?)", [("Ana", "Ana Ruiz", "AR"), ("Bo", "Bo Lin", "BL")])
        con.executemany("INSERT INTO parts VALUES (?, 'purchased', ?, ?)", [("a", "Gears", "Ana"), ("b", "Gears", "Ana"), ("c", "Cables", "Bo")])


def test_who_halden_is_comes_from_its_tables_not_from_the_prompt_files(db):
    from app.organism.prompts import build_system_prompt, halden_facts

    _halden_tables(db)
    long, short = halden_facts(db)
    assert "Alpha 1" in long and "Beta 2" in long and "Ana Ruiz (Gears)" in long and "Bo Lin (Cables)" in long and "2 buyers" in long
    assert "Alpha" in short and "Ana" not in short
    assert "Ana Ruiz (Gears)" in build_system_prompt(db)
    assert halden_facts(None)[0] == halden_facts(str(db) + "-missing")[0]  # no tables: it says only what it knows without them
    for banned in ("Dana", "Marcus", "Priya", "Sofia", "Tern", "Porter", "Heron", "Yunzhan"):
        assert banned not in build_system_prompt(None), banned


def test_every_agent_prompt_carries_the_glossary_and_the_record_links():
    from app.organism.prompts import build_system_prompt
    from app.organism.specialists.registry import SPECIALISTS

    for text in [build_system_prompt(None)] + [s.instructions for s in SPECIALISTS.values()]:
        assert "Past due" in text and "Single source" in text and "How the records link" in text and "importer of record" in text.lower()


def test_the_facts_queries_match_the_real_tables(tmp_path):
    """Built from the models, so a renamed column fails here instead of quietly thinning the prompt."""
    from sqlalchemy import create_engine

    from app.domain.base import Base
    from app.domain.demand.model import Product
    from app.domain.parts.model import Buyer, Part
    from app.domain.suppliers.model import SupplierIdentity, SupplierRecord  # noqa: F401  (the tables Part points at)
    from app.organism.prompts import halden_facts

    db = tmp_path / "real.db"
    Base.metadata.create_all(create_engine(f"sqlite:///{db}"), tables=[Buyer.__table__, Part.__table__, Product.__table__, SupplierRecord.__table__, SupplierIdentity.__table__])
    assert halden_facts(db)[0].startswith("You live inside the company's procurement workspace")  # empty tables: nothing to add, and no error


def test_the_owner_count_covers_every_open_question_the_recommendation_carries(ctx, db, services):
    """The strip says 'N of M owned': the model wrote one question, the item and the tools raised more, and code carries them in."""
    from app.domain.common import Unknown

    a = seed(ctx, db)
    ctx.unknowns.extend(Unknown(what=f"stock of part {i}", why_it_blocks=f"cover {i}", owner="Dana", question="how many?") for i in range(10))
    ctx.unknowns.append(Unknown(what="who owns it", why_it_blocks="routing", owner="", question="who?"))
    _, v = verify(ctx, good(a), services=services)
    assert v.open_questions == 12 and v.open_questions_with_owner == 11


def test_the_context_packet_links_items_that_share_a_supplier_and_says_why(services):
    from app.organism.context_packet import build, linked_items

    item = services.attention.get_item("disruption:SUP-0001")
    keys = [o.key for o, _ in linked_items(item, services)]
    assert set(keys) == {"tariff:HR-40110", "deadline:price-lock"} and "disruption:SUP-0001" not in keys
    assert keys[0] == "tariff:HR-40110"  # the same part (and supplier) outranks the same supplier alone
    text = build(item, services).text
    assert "Also on the Action list, linked to this item" in text and "the same part: HR-40110" in text and "the same supplier: Shenzhen Yunzhan" in text
    assert build(services.attention.get_item("unknown:HR-40220"), services).text == ""  # nothing shares its refs: no block, no guessing


def test_options_become_cited_numbers_and_the_deciding_unknowns_are_carried(services):
    from types import SimpleNamespace as NS

    from app.domain.attention.schema import DateValue, FireOption, Need
    from app.domain.common import Money, Provenance, Unknown
    from app.organism.context_packet import build

    p = Provenance(method="computed", source="t", rule="r", by="t")
    d = Unknown(what="whether the supplier can allocate", why_it_blocks="no date", owner="Dana", question="Can it?")
    opt = FireOption(kind="air_freight", label="Air-freight what exists", needs=[Need(what="a stock count", owner="Dana")], earliest=DateValue(date="2026-10-20", provenance=p),
                     earliest_basis="the supplier's own promise", cost_delta=Money(amount=Decimal("1200.00"), currency="USD", usd=Decimal("1200.00"), provenance=p), cost_basis="freight versus ocean", decided_by=d)
    svc = NS(attention=NS(list_items=services.attention.list_items, stage_of=lambda it: NS(label="Worked", step=2, of=7, waiting_on="you", next_act="Decide."), options=lambda key: [opt]))
    pk = build(services.attention.get_item("disruption:SUP-0001"), svc)
    opt = [n for n in pk.numbers if n.id.startswith("option:")]                          # the linked cases' at-stake figures come first (F103 R5)
    assert [n.id for n in opt] == ["option:disruption:SUP-0001:air_freight:cost_delta"] and opt[0].value == Decimal("1200.00")
    assert pk.unknowns == [] and "Where this stands: Worked (step 2 of 7), waiting on you. Next: Decide." in pk.text   # the decider stays on its option, not one more open question
    assert "the buyer chooses; recommend one by its kind" in pk.text and "(kind air_freight)" in pk.text and pk.option_kinds == ["air_freight"] and "$1,200 [option:disruption:SUP-0001:air_freight:cost_delta]" in pk.text and "Decided by: whether the supplier can allocate (owner Dana)" in pk.text
    assert opt[0].say == "$1,200"                                   # registered as a say form, so the reason may write the value


def test_the_packet_says_the_air_freight_duty_as_avoided_with_its_value(services):
    """plan-13 1b: the reason can cite the figure, and the $85K reads as duty avoided by shipping in time, not a cost."""
    from decimal import Decimal
    from types import SimpleNamespace as NS

    from app.domain.attention.schema import FireOption
    from app.domain.common import Money, Provenance, Unknown
    from app.organism.context_packet import build

    p = Provenance(method="computed", source="t", rule="r", by="t")
    opt = FireOption(kind="air_freight", label="Air-freight what survived", duty_effect=Money(amount=Decimal("85350.35"), currency="USD", usd=Decimal("85350.35"), provenance=p),
                     decided_by=Unknown(what="what survived", why_it_blocks="x", owner="supplier", question="What survived?"))
    svc = NS(attention=NS(list_items=services.attention.list_items, stage_of=lambda it: None, options=lambda key: [opt]))
    pk = build(services.attention.get_item("disruption:SUP-0001"), svc)
    assert "Duty avoided if it ships before the duty starts: $85K [option:disruption:SUP-0001:air_freight:duty_effect]." in pk.text
    duty = next(n for n in pk.numbers if n.id.startswith("option:"))
    assert "Duty if late" not in pk.text and duty.name.endswith("duty avoided if the goods ship before the duty starts")


def test_the_company_name_comes_from_the_builds_recipe_not_from_a_prompt_file(tmp_path, monkeypatch):
    import sqlite3
    from pathlib import Path

    from app.organism import company, prompts
    from app.organism.prompts import build_system_prompt
    from app.organism.specialists import registry
    from app.organism.specialists.registry import SPECIALISTS

    db = tmp_path / "c.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE build_meta (key TEXT, value TEXT)")
        con.execute("INSERT INTO build_meta VALUES ('company', 'Acme Motion Ltd')")
    assert company.names(db) == ("Acme Motion Ltd", "Acme")
    prompt = build_system_prompt(db)
    assert "Acme Motion Ltd" in prompt and "{company" not in prompt
    own = [Path(prompts.__file__).with_name("constitution.md"), Path(prompts.__file__).with_name("knowledge") / "glossary.md", *(registry._HERE / n / "instructions.md" for n in SPECIALISTS)]
    assert all("Halden" not in f.read_text() for f in own)  # the files this part owns name no company; the domain's own catalogue text is not among them
    assert all("{company" not in sp.instructions_for(db) and "Acme" in sp.instructions_for(db) for sp in SPECIALISTS.values())
    assert company.names(tmp_path / "none.db") == ("the company", "the company")  # no build, no name: nothing is made up
    monkeypatch.setenv("LOOKOUT_COMPANY", "Globex Corp")
    assert company.names(tmp_path / "none2.db") == ("Globex Corp", "Globex")


def test_the_year_in_a_date_in_words_is_the_data_dates_year(monkeypatch):
    from datetime import date

    from app.organism import toolkit

    assert toolkit.month_words("2026-10") == "October" and toolkit.date_words("2026-09-22") == "22 September"
    monkeypatch.setattr(toolkit, "AS_OF", date(2027, 3, 1))
    assert toolkit.month_words("2027-10") == "October" and toolkit.month_words("2026-10") == "October 2026" and toolkit.date_words("2027-09-22") == "22 September"


def test_a_number_a_buyer_reads_names_the_supplier_not_its_id(ctx, services):
    """Round 7: 'Open PO lines for SUP-0041' reached the answer through a number's name, and the judge failed it. The id stays in the number's id."""
    import asyncio
    import json

    from app.domain.orders import tools as orders_tools

    t = {x.name: x for x in orders_tools.make_tools(ctx, services.orders)}
    body = json.loads(asyncio.run(t["open_supply"].handler({"supplier_id": "SUP-0001"}))["content"][0]["text"])
    names = [n["name"] for n in body["numbers"]]
    assert names and all("SUP-0001" not in n for n in names) and any("Shenzhen Yunzhan" in n for n in names)
    assert any(n["id"].startswith("supply:SUP-0001:") for n in body["numbers"]) and "SUP-0001" not in body["summary"]
    body = json.loads(asyncio.run(t["disrupted_supply"].handler({"supplier_id": "SUP-0001"}))["content"][0]["text"])
    assert all("SUP-0001" not in n["name"] for n in body["numbers"]) and "SUP-0001" not in body["summary"]


def test_a_supplier_id_in_a_staged_draft_fails_the_check(ctx, db, services):
    from app.domain.actions import ledger

    a = seed(ctx, db)
    ledger.update_draft(db, a.action_id, subject="Revised promise dates", body="Please confirm for SUP-0001.", edited_by="Dana")
    assert any("SUP-0001" in f for f in verify(ctx, good(a), services=services)[1].failures)


def test_day_counts_are_read_from_prose_and_from_tool_text():
    from app.organism.verifier import day_counts

    assert day_counts("It expires in 36 days; 66-day window; 1,140 days is odd") == {36, 66, 1140}
    assert day_counts('{"days_left": 41, "days_past_due": 3, "lead_time": {"days": "98 days"}}') == {41, 3, 98}
    assert day_counts("6 to 8 weeks, 364 EA, 25%") == set()
    assert day_counts("Payment Net 30 (was 45)") == {30}


def test_a_days_figure_must_be_one_a_tool_returned_the_model_never_subtracts_dates(ctx, db, services):
    from decimal import Decimal

    a = seed(ctx, db)
    d = good(a); d["finding"] += " The duty starts in 41 days."
    _, v = verify(ctx, d, services=services)
    assert not v.passed and any(f.startswith("days:") and "41 days" in f for f in v.failures)
    ctx.seen_day_counts.add(41)  # a day count somewhere in a tool's text is not enough for a countdown...
    ctx.seen_numerals.add(Decimal(41))
    assert any("41 days left" in f for f in verify(ctx, d, services=services)[1].failures)
    ctx.seen_days_left.add(41)  # ...it has to be the days_left a tool returned
    assert verify(ctx, d, services=services)[1].passed
    from decimal import Decimal

    from app.organism.schemas import Number

    ctx.register([Number(id="item:x:days_left", name="Days left to act", value=Decimal(18), unit="days")])
    d2 = good(a); d2["finding"] += " Act within 18 days."
    assert verify(ctx, d2, services=services)[1].passed  # a registered days number counts


def test_a_today_that_is_not_the_data_date_fails_wherever_the_buyer_or_the_supplier_reads_it(ctx, db, services):
    """Round 8: six trials wrote 'today is 15 October' in an answer or a draft while the data is as of 25 September; 15 October is a date some tool returned, so the dates check did not catch it."""
    from app.domain.actions import ledger

    a = seed(ctx, db)
    ctx.seen_dates.add((10, 15))  # a deadline a tool returned
    d = good(a); d["finding"] += " As of today, 15 October, the price lock is open."
    assert any("says today is 15 October" in f for f in verify(ctx, d, services=services)[1].failures)
    d = good(a); d["open_questions"] = [{"what": "which lines", "why_it_blocks": "right now it is 11 October and nothing is booked", "owner": "Dana", "question": "Which?"}]
    ctx.seen_dates.add((10, 11))
    assert any("says today is 11 October" in f for f in verify(ctx, d, services=services)[1].failures)
    ledger.update_draft(db, a.action_id, subject="Revised promise dates", body="Today is 15 October; please confirm the revised dates.", edited_by="Dana")
    assert any("says today is 15 October" in f for f in verify(ctx, good(a), services=services)[1].failures)
    ledger.update_draft(db, a.action_id, subject="Revised promise dates", body="As of today (25 September) please confirm the revised dates.", edited_by="Dana")
    ctx.seen_dates.add((9, 25))
    assert not any("says today" in f for f in verify(ctx, good(a), services=services)[1].failures)  # the data date is fine


def test_a_weekday_beside_a_date_must_be_that_weekday(ctx, db, services):
    from app.organism.verifier import weekday_mismatches

    assert weekday_mismatches("The notice came on Friday 25 September and Monday, 28 September follows.", 2026) == []
    assert weekday_mismatches("Please reply by Monday 25 September, or by Oct 15 (Wed).", 2026) == ["Monday 25 September"]
    a = seed(ctx, db)
    ctx.seen_dates.add((10, 13))
    d = good(a); d["finding"] += " The lock ends on Tuesday 13 October."
    assert not any("weekday" in f for f in verify(ctx, d, services=services)[1].failures)  # 13 October 2026 is a Tuesday
    d["finding"] = good(a)["finding"] + " The lock ends on Monday 13 October."
    assert any("'Monday 13 October' is not that weekday" in f for f in verify(ctx, d, services=services)[1].failures)


def test_each_figure_binds_to_the_robot_of_its_own_clause(ctx, db, services):
    """O3 (run-67d56b23): 'the Tern T2 drive motor HR-40110 is short 364 EA ... and the Porter P5 drive motor HR-40210 is short 80 EA' was failed with '364 is said of the Porter'."""
    from decimal import Decimal

    from app.organism.schemas import Number
    from app.organism.verifier import binding_failures

    ctx.register([Number(id="shortage:HR-40110:2026-10:short", name="Units short in October for HR-40110, the Tern T2 drive motor", value=Decimal(364), unit="EA"),
                  Number(id="shortage:HR-40210:2026-10:short", name="Units short in October for HR-40210, the Porter P5 drive motor", value=Decimal(80), unit="EA")])
    sentence = "In October the Tern T2 drive motor HR-40110 is short 364 EA and the Porter P5 drive motor HR-40210 is short 80 EA."
    assert binding_failures(ctx, sentence, services) == []
    assert binding_failures(ctx, "364 Tern robots and 80 Porter robots are affected.", services) == []  # a figure before its noun still binds to it
    assert any("364" in f and "Porter" in f for f in binding_failures(ctx, "The Porter drive motor is short 364 EA in October.", services))  # a figure said of the wrong robot still fails
    assert any("80" in f and "Tern" in f for f in binding_failures(ctx, "The Tern T2 is short 80 EA.", services))


def test_a_countdown_is_the_tools_days_left_and_other_day_counts_are_unchanged(ctx, db, services):
    """Round 8 trials stated 'in 41 days', '18 days', '66 days' that no tool gave as days left (hr50110, hr40110, bcx)."""
    from app.organism.verifier import days_left_claims, days_left_in

    assert days_left_claims("It lapses in 18 days; 3 days left; 66 days until the quote ends; with 5 days to go") == {18, 3, 66, 5}
    assert days_left_claims("Net 30 and 60 days after PPAP; 30 days past due; within 5 days") == set()  # terms, lateness and requests are not countdowns
    assert days_left_in('{"days_left": 36, "days_to_effective": 37, "days_past_due": 3}') == {36, 37}
    a = seed(ctx, db)
    d = good(a); d["finding"] += " The quote lapses in 18 days."
    ctx.seen_day_counts.add(18); ctx.seen_numerals.add(__import__("decimal").Decimal(18))
    assert any("18 days left" in f for f in verify(ctx, d, services=services)[1].failures)
    ctx.seen_days_left.add(18)
    assert verify(ctx, d, services=services)[1].passed
    d2 = good(a); d2["finding"] += " Nothing for 30 days past due."
    ctx.seen_day_counts.add(30); ctx.seen_numerals.add(__import__("decimal").Decimal(30))
    assert verify(ctx, d2, services=services)[1].passed


def test_a_run_that_reuses_the_open_or_sent_request_of_the_same_contact_passes(ctx, db, services):
    """O16 (#192's side effect): the run reused another item's waiting draft and ended did_not_pass with 'A-... is not in the ledger for this run'."""
    from app.domain.actions import ledger
    from app.domain.common import EntityRef

    base = seed(ctx, db)  # the run's evidence and handoffs; its own staged draft is set aside: this run reuses another item's instead
    ctx.action_ids.clear()
    other = ledger.propose(db, type="supplier_request", item_key="deadline:SUP-0001:2026-10-10", run_id="run-earlier", target=EntityRef(type="supplier", id="SUP-0001"),
                           recipient="li.wei@yunzhan-motor.example", subject="Revised promise dates", body="Please confirm revised dates for HPO-26-00614 line 10 by 2026-10-10.")
    ctx.seen_dates.add((10, 10))
    ledger.link_to_run(db, ctx.run_id, other.action_id)  # what draft_supplier_request does when the ask is covered
    ctx.action_ids.append(other.action_id)
    d = good(base)
    d["action_ids"] = [other.action_id]
    assert verify(ctx, d, services=services)[1].passed, verify(ctx, d, services=services)[1].failures
    # sent: not in ctx.action_ids (nothing new to approve), cited by the model, still the run's own link
    ctx.action_ids.clear()
    a = ledger.approve(db, other.action_id, other.payload_hash, "Dana Reyes")
    assert a.state == "executed"
    rec, v = verify(ctx, d, services=services)
    assert v.passed and v.reasons == [], v.failures
    # an action nobody linked to this run is still refused
    stray = ledger.propose(db, type="supplier_request", item_key="x", run_id="run-else", target=EntityRef(type="supplier", id="SUP-0001"), recipient="b@y.example", subject="s", body="b")
    d2 = good(base); d2["action_ids"] = [stray.action_id]
    assert any("was not staged in this run" in f for f in verify(ctx, d2, services=services)[1].failures)


def test_every_failure_has_a_plain_reason_without_an_id(ctx, db, services):
    from app.organism.verifier import plain_reasons

    a = seed(ctx, db)
    d = good(a); d["numbers"][0]["value"] = 365
    v = verify(ctx, d, services=services)[1]
    assert not v.passed and v.reasons == ["A figure in the answer does not match what the records returned"] and "A-" not in " ".join(v.reasons) and "365" not in " ".join(v.reasons)
    assert plain_reasons(["actions: A-c2d96d49 is not in the ledger for this run", "actions: A-1 is a note", "weird"]) == ["A draft or note the answer mentions was not prepared for this item", "A check on the answer failed"]


def test_the_full_sentence_with_two_clauses_passes_the_whole_verifier_not_only_the_binding(ctx, db, services):
    """The shape that failed live (O3): two robots, two figures, one sentence. Through verify(), so the value check, the binding and the ids all run."""
    from app.organism.schemas import Number

    a = seed(ctx, db)
    ctx.register([Number(id="shortage:HR-40110:2026-10:short", name="Units short in October for HR-40110, the Tern T2 drive motor", value=Decimal(364), unit="EA"),
                  Number(id="shortage:HR-40210:2026-10:short", name="Units short in October for HR-40210, the Porter P5 drive motor", value=Decimal(80), unit="EA")])
    d = good(a)
    d["finding"] = "In October the Tern T2 drive motor HR-40110 is short 364 EA and the Porter P5 drive motor HR-40210 is short 80 EA."
    d["numbers"] = [{"id": "shortage:HR-40110:2026-10:short", "value": 364}, {"id": "shortage:HR-40210:2026-10:short", "value": 80}]
    failures = verify(ctx, d, services=services)[1].failures
    assert not any("is said of" in f for f in failures), failures


def test_a_one_digit_count_is_not_bound_to_a_robot(ctx, db, services):
    """'1 is said of the Porter, but the tool number with that value is about the Tern' must not fire: '1 open line', 'one of the two' and '2 drive motors' are counts, not figures about a robot."""
    from app.organism.schemas import Number
    from app.organism.verifier import binding_failures

    ctx.register([Number(id="shortage:HR-40110:2026-10:short", name="Units short in October for HR-40110, the Tern T2 drive motor", value=Decimal(1), unit="EA"),
                  Number(id="shortage:HR-40210:2026-10:short", name="Units short in October for HR-40210, the Porter P5 drive motor", value=Decimal(80), unit="EA")])
    for text in ("The Porter P5 drive motor has 1 open line.", "Of the 2 drive motors, the Porter P5 is the one that needs a supplier.", "The Porter P5 uses 2 drive motors per robot."):
        assert binding_failures(ctx, text, services) == [], text


def test_a_figure_is_bound_to_the_month_of_its_own_clause(ctx, db, services):
    """F7.5 (run-77fe16e7): a correct sentence failed with '24 is said of October, but the tool number with that value is for November'."""
    from decimal import Decimal

    from app.organism.schemas import Number
    from app.organism.verifier import binding_failures

    ctx.register([Number(id="shortage:HR-40110:2026-10:short", name="Units short in October for HR-40110, the Tern T2 drive motor", value=Decimal(222), unit="EA"),
                  Number(id="shortage:HR-50110:2026-11:short", name="Units short in November for HR-50110, the Heron H1 AC-DC power supply", value=Decimal(24), unit="EA")])
    text = "Tern T2 and Porter P5 short 222 EA of the drive motor in October, and the Heron H1 is short 24 EA of the AC-DC power supply in November."
    assert binding_failures(ctx, text, services) == []
    wrong = "The Heron H1 is short 24 EA of the AC-DC power supply in October."
    assert any("24 is said of October" in f for f in binding_failures(ctx, wrong, services))  # a real mismatch still fails


def test_a_figure_no_tool_returned_in_the_sentences_marks_the_answer_but_a_draft_with_one_is_blocked(ctx, db, services):
    """FEEDBACK 7.1: a follow-up answer was withheld on one unchecked '1' while the Reviewer gave it 100/100."""
    a = seed(ctx, db)
    d = good(a); d["finding"] = "Short by 987 units in October."
    rec, v = verify(ctx, d, services=services)
    assert v.passed and v.unchecked == ["987"] and rec.unchecked == ["987"] and any("could not be checked" in r for r in v.reasons)


def test_a_rating_in_a_part_name_is_not_a_figure_about_a_robot_or_a_month(ctx, db, services):
    """KHALID P0 (run-4f857608, run-e8df72db): '24 is said of October … for November' and '24 is said of the Tern … about the Heron'; the 24 is the voltage in 'DC-DC converter, 48 V to 24 V (HR-51110)'."""
    from decimal import Decimal

    from app.organism.schemas import Number
    from app.organism.verifier import binding_failures, mask_specs, numerals

    ctx.register([Number(id="shortage:HR-50110:2026-11:short", name="Units short in November for the Heron H1 AC-DC power supply", value=Decimal(24), unit="EA"),
                  Number(id="shortage:HR-40110:2026-10:short", name="Units short in October for the Tern T2 drive motor", value=Decimal(222), unit="EA")])
    text = "The Jadepeak allocation covers the DC-DC converter, 48 V to 24 V (HR-51110), which the Tern T2 needs in October, and 222 EA are short."
    assert binding_failures(ctx, text, services) == []
    assert "24" not in mask_specs(text) and numerals(text) == [Decimal(222)]
    assert any("24 is said of" in f for f in binding_failures(ctx, "The Tern T2 is short 24 EA in October.", services))  # a real quantity is still bound


def test_the_answer_is_skimmable_one_decision_sentence_then_at_most_four_short_rows(ctx, db, services):
    """Khalid: when the UI holds all that text it is the same as reading the email. The finding is one sentence of at most 20 words; the detail is rows."""
    a = seed(ctx, db)
    d = good(a)
    d["points"] = [{"label": "Short", "text": "Tern drive motors run out in October."}, {"label": "Needs you", "text": "A decision on the quote."}]
    rec, v = verify(ctx, d, services=services)
    assert v.passed and [p.label for p in rec.points] == ["Short", "Needs you"], v.failures
    long = dict(d, finding=" ".join(["word"] * 21))
    assert any(f.startswith("shape:") and "21 words" in f for f in verify(ctx, long, services=services)[1].failures)
    many = dict(d, points=[{"label": f"L{i}", "text": "x"} for i in range(5)])
    assert any("5 points" in f for f in verify(ctx, many, services=services)[1].failures)
    wordy = dict(d, points=[{"label": "Short", "text": " ".join(["w"] * 41)}])
    assert any("too long" in f for f in verify(ctx, wordy, services=services)[1].failures)
    # figures in a row are checked like any other prose
    stray = dict(d, points=[{"label": "Short", "text": "Short by 987 units."}])
    r = verify(ctx, stray, services=services)[1]
    assert r.passed and "987" in r.unchecked  # a figure no tool returned in a row is shown marked, like any other prose


def test_an_answer_without_a_next_step_fails_and_what_the_run_did_is_listed_from_the_ledger(ctx, db, services):
    from app.domain.actions import ledger

    a = seed(ctx, db)
    d = good(a)
    rec, v = verify(ctx, d, services=services)
    assert v.passed and rec.next_step.who == "Dana Reyes" and [(x.action_id, x.stage) for x in rec.done] == [(a.action_id, "proposed")]
    assert rec.done[0].text.startswith("Drafted a request to ") and rec.done[0].text.endswith("waiting for your approval")
    assert any("without a next step" in f for f in verify(ctx, dict(d, next_step={"who": "", "what": ""}), services=services)[1].failures)
    assert any("next step's date" in f for f in verify(ctx, dict(d, next_step={"who": "Dana", "what": "Call", "by": "9 January"}), services=services)[1].failures)


def test_conditions_a_tool_returned_and_the_answer_dropped_are_added_by_code_as_one_marked_row(ctx, db, services):
    """Khalid: the result assembled in code guarantees completeness; the model writes the words."""
    a = seed(ctx, db)
    ctx.conditions.update({"cond:HR-12210:q1:incoterm": {"text": "Hallerbeck: EXW", "tokens": ["exw"]},
                           "cond:HR-12210:q1:lead_time": {"text": "Hallerbeck: lead time 14 weeks", "tokens": ["14 weeks"]}})
    d = good(a); d["points"] = [{"label": "Terms", "text": "The quote is EXW."}]
    rec, v = verify(ctx, d, services=services)
    row = [p for p in rec.points if p.added_by_code]
    assert v.passed and [p.label for p in row] == ["Conditions"] and row[0].text == "Hallerbeck: lead time 14 weeks" and any("carry:" in w for w in v.warnings)
    assert [p.label for p in rec.points if not p.added_by_code] == ["Terms"]  # the model's own rows are untouched
    ctx.conditions.clear()
    assert not [p for p in verify(ctx, good(a), services=services)[0].points if p.added_by_code]


def test_a_date_after_the_data_date_is_never_written_as_if_it_had_passed(ctx, db, services):
    """FEEDBACK 11.1 (run-9947b79c): 'Yunzhan was due to give revised dates by 10 October and none has come', on 25 September."""
    from app.organism.verifier import future_dates_in_past_tense

    bad = "Yunzhan was due to give revised dates by 10 October and none has come."
    assert future_dates_in_past_tense(bad) and future_dates_in_past_tense("The 15 October price lock has expired.")
    assert not future_dates_in_past_tense("Yunzhan promised revised dates by 10 October (in 15 days).")
    assert not future_dates_in_past_tense("The line promised for 24 September is overdue.")  # already past on the data date
    assert not future_dates_in_past_tense("If the dates have not come by 10 October, call the contact.")  # a condition, not a claim
    a = seed(ctx, db)
    ctx.seen_dates.add((10, 10))
    d = good(a); d["points"] = [{"label": "Asked", "text": bad}]
    v = verify(ctx, d, services=services)[1]
    assert not v.passed and any("still ahead of the data date" in f for f in v.failures)


def test_an_answer_to_a_question_carries_at_most_three_rows(ctx, db, services):
    a = seed(ctx, db)
    d = good(a); d["points"] = [{"label": f"L{i}", "text": "x"} for i in range(4)]
    assert not any("points" in f for f in verify(ctx, d, services=services)[1].failures)  # an item answer may carry four
    ctx.open_plan = True
    assert any("4 points; at most 3 in an answer to a question" in f for f in verify(ctx, d, services=services)[1].failures)


def test_a_count_written_as_a_word_is_held_to_the_tools_count(ctx, db, services):
    """FEEDBACK (flagship item): 'Three … lines are already past due' when the raw POs and the tile say four; the verifier missed it because 'Three' is a word."""
    from decimal import Decimal

    from app.organism.schemas import Number
    from app.organism.verifier import count_claim_failures

    ctx.register([Number(id="item:disruption:S1:lines_already_late", name="late", value=Decimal(4), unit="lines"), Number(id="item:disruption:S1:lines_in_scope", name="scope", value=Decimal(10), unit="lines")])
    bad = "Three Yunzhan lines are already past due: HPO-26-00450/10, HPO-26-00450/20, HPO-26-00532/10."
    assert any("says 3 lines already past due, but the tool counted 4" in f for f in count_claim_failures(bad, ctx))
    assert not count_claim_failures("Four lines are already past due, and 10 lines are under the notice.", ctx)
    assert any("says 9" in f for f in count_claim_failures("9 open lines are under the notice.", ctx))
    assert not count_claim_failures("Three Yunzhan lines are already past due.", type("C", (), {"evidence": {}})())  # nothing counted by a tool: nothing to hold it to
    a = seed(ctx, db)
    d = good(a); d["points"] = [{"label": "Late", "text": bad}]
    v = verify(ctx, d, services=services)[1]
    assert not v.passed and any(f.startswith("counts:") for f in v.failures) and "does not match the records' count" in " ".join(v.reasons)


def test_each_figure_binds_to_the_product_before_it_in_its_own_comma_clause(ctx, db, services):
    """FEEDBACK (run-fa89fc0e): 'the Tern T2 drive motor 364, the Porter P5 brake 80' failed with '364 is said of the Porter'."""
    from decimal import Decimal

    from app.organism.schemas import Number
    from app.organism.verifier import binding_failures

    ctx.register([Number(id="shortage:HR-40110:2026-10:short", name="Units short in October for HR-40110, the Tern T2 drive motor", value=Decimal(364), unit="EA"),
                  Number(id="shortage:HR-40210:2026-10:short", name="Units short in October for HR-40210, the Porter P5 drive motor", value=Decimal(80), unit="EA")])
    for text in ("Short in October: the Tern T2 drive motor 364, the Porter P5 brake 80.", "The Tern T2 drive motor 364 EA, the Porter P5 drive motor 80 EA.",
                 "Short: the Tern T2 drive motor 364; the Porter P5 drive motor 80."):
        assert binding_failures(ctx, text, services) == [], text
    assert any("is said of the Porter" in f for f in binding_failures(ctx, "Short: the Porter P5 drive motor 364, the Tern T2 drive motor 80.", services))  # the swap is still caught


def test_a_count_written_as_a_word_is_a_figure_the_tools_must_have_returned(ctx, db, services):
    """FEEDBACK: 'All ELEVEN parts are China origin' on a tariff item that covers 17 parts."""
    from decimal import Decimal

    from app.organism.verifier import numerals

    assert numerals("All eleven parts are China origin.") == [Decimal(11)] and numerals("One of the parts, a couple of lines.") == []
    a = seed(ctx, db)
    d = good(a); d["finding"] = "All eleven parts are China origin."
    rec, v = verify(ctx, d, services=services)
    assert "11" in v.unchecked and "11" in rec.unchecked  # marked, not trusted


def test_a_deadline_with_its_countdown_is_not_a_claim_about_what_today_is():
    """FEEDBACK (run-3ef1f3ee): 'by 15 October (in 20 days)' failed with 'the text says today is 15 October'."""
    from app.organism.verifier import todays_date_claims

    assert todays_date_claims("Orders acknowledged today must be in by 15 October (in 20 days).") == set()
    assert todays_date_claims("Today (15 October) the price holds, and the old price holds until 1 November (in 37 days).") == {(10, 15)}  # the real claim still counts
    assert todays_date_claims("Today is 10 October.") == {(10, 10)}  # a bare 'today is X' that contradicts the data date still fails
    assert todays_date_claims("As of today, 15 October, the lock is open.") == {(10, 15)}
    assert todays_date_claims("Place orders today, by 15 October.") == set()


def test_a_deadline_to_a_date_after_as_of_today_is_not_a_claim_about_today():
    """FEEDBACK (run-fed855f2): 'the current price held on deliveries to 15 December' failed with 'the text says today is 15 December'."""
    from app.organism.verifier import todays_date_claims

    assert todays_date_claims("As of today, the current price held on deliveries to 15 December is $10.") == set()
    assert todays_date_claims("As of today, 15 October, the lock is open.") == {(10, 15)} and todays_date_claims("Right now it is 11 October.") == {(10, 11)}


def test_a_count_is_bound_to_the_noun_that_follows_it_not_to_a_later_qualifier():
    from types import SimpleNamespace as NS

    from app.organism.verifier import count_claim_failures

    ctx = NS(evidence={"x:lines_already_late": NS(value=Decimal(4))})
    assert not count_claim_failures("10 stuck lines, 4 were already past due.", ctx)  # ten lines are stuck; four of them are late
    assert not count_claim_failures("Ten stuck lines, four were already past due.", ctx)
    assert count_claim_failures("10 stuck lines are already past due.", ctx)  # the qualifier follows the same count: held to the tool's number


def test_a_countdown_in_any_wording_is_a_days_left_claim_only_a_tool_may_give():
    from app.organism.verifier import days_left_claims

    assert days_left_claims("It is 41 days away; 12 days out; 30 days of runway; 7 days to act; a 9-day window; 5 days from today") == {41, 12, 30, 7, 9, 5}
    assert days_left_claims("The part has a 41 day lead time and ships 3 days after PPAP") == set()


def test_a_draft_that_states_a_date_after_the_data_day_as_past_is_caught(monkeypatch):
    from datetime import date

    from app.organism import verifier as verifier_mod

    monkeypatch.setattr(verifier_mod, "AS_OF", date(2026, 9, 17))
    assert verifier_mod.future_dates_in_past_tense("Line 10 was promised for 23 September and has not arrived.")
    assert not verifier_mod.future_dates_in_past_tense("Line 10 is promised for 23 September; please confirm it will arrive.")
    assert not verifier_mod.future_dates_in_past_tense("Line 10 was promised for 12 September and has not arrived.")


def test_a_case_run_carries_no_points(ctx, db, services):
    """F74 P1: the case page has no points slot; points the model wrote anyway are not kept. A non-case answer keeps them."""
    a = seed(ctx, db); d = good(a); d["points"] = [{"label": "Short", "text": "364 EA in October."}]
    ctx.is_case = True
    rec, v = verify(ctx, d, services=services)
    assert v.passed and rec.points == []
    ctx.is_case = False
    assert [p.label for p in verify(ctx, d, services=services)[0].points] == ["Short"]


def _recommend(ctx, db, kind="allocation", reason="dates by 10 October, all 1,140 covered", ids=("supply:HR-40110:stuck_qty",)):
    a = seed(ctx, db); d = good(a)
    ctx.option_kinds = ["allocation", "air_freight", "resequence", "second_source"]
    d["recommended"] = {"kind": kind, "reason": reason, "number_ids": list(ids)}
    return d


def test_a_recommended_way_through_with_cited_figures_is_kept(ctx, db, services):
    rec, v = verify(ctx, _recommend(ctx, db), services=services)
    assert v.passed and rec.recommended.kind == "allocation" and not any(w.startswith("recommended") for w in v.warnings)


@pytest.mark.parametrize("kind,reason,ids,why", [
    ("allocation", "Fastest answer, covering all 1,140 stuck.", (), "1140"),
    ("allocation", "Fastest answer by far, covering all 1,140 stuck pieces.", ("supply:HR-40110:stuck_qty",), "9 words"),
    ("allocation", "Lookout recommends this: 1,140 covered.", ("supply:HR-40110:stuck_qty",), "'Lookout'"),
    ("allocation", "the planning lead agrees; 1,140 covered", ("supply:HR-40110:stuck_qty",), "planning lead"),
    ("allocation", "1,140 covered within 12 days", ("supply:HR-40110:stuck_qty",), "states 12"),
    ("allocation", "Covers 1,500 pieces.", ("supply:HR-40110:stuck_qty",), "1500"),
    ("allocation", "Covers 1,140 pieces.", ("made:up",), "an id no tool returned"),
    ("prepay", "Covers 1,140 pieces.", ("supply:HR-40110:stuck_qty",), "not one of the ways laid out"),
    ("allocation", "Dates by 3 October for 1,140.", ("supply:HR-40110:stuck_qty",), "a date no tool returned"),
])
def test_a_recommended_way_through_that_fails_its_check_is_dropped_and_the_run_still_passes(ctx, db, services, kind, reason, ids, why):
    rec, v = verify(ctx, _recommend(ctx, db, kind, reason, ids), services=services)
    assert v.passed and rec.recommended is None and any(w.startswith("recommended: not shown") and why in w for w in v.warnings)


def test_nothing_is_recommended_where_no_ways_through_are_laid_out(ctx, db, services):
    d = _recommend(ctx, db); ctx.option_kinds = []
    rec, v = verify(ctx, d, services=services)
    assert rec.recommended is None and any("no ways through" in w for w in v.warnings)


def test_an_old_recording_with_no_recommended_still_parses():
    from app.organism.schemas import Recommendation, RecommendationDraft, draft_schema

    assert RecommendationDraft.model_validate({"finding": "x", "numbers": []}).recommended is None
    assert Recommendation.model_validate({"finding": "x", "numbers": []}).recommended is None
    assert draft_schema()["$defs"]["RecommendedDraft"]["properties"]["reason"]["maxLength"] == 60


def test_the_agent_writes_no_line_per_option():
    """ui-ai-contract v2: code writes each option's cells; the agent writes only `recommended`. An old draft with `options` still parses."""
    from app.organism.schemas import Recommendation, RecommendationDraft, draft_schema

    assert "options" not in draft_schema()["properties"] and "options" not in Recommendation.model_fields
    assert RecommendationDraft.model_validate({"finding": "x", "numbers": [], "options": [{"kind": "allocation", "why": "y"}]}).recommended is None


def test_words_a_buyer_does_not_use_are_a_warning_not_a_failure(ctx, db, services):
    """plan-13 item 6: item, ways through, staged, unknown, tranche, conditional, gross, allocation from other capacity, Reviewer."""
    from app.organism.verifier import banned_words

    assert banned_words("The item's gross duty is conditional; two ways through were staged. Allocation from Yunzhan's other capacity.") == [
        "allocation from yunzhan's other capacity", "conditional", "gross", "item", "staged", "ways through"]
    assert banned_words("The case: 10 PO lines, open value $187K, stock not known yet. Options: Recommended allocation.") == []
    a = seed(ctx, db); d = good(a); d["points"] = [{"label": "Needs you", "text": "Stock on hand is unknown for this item."}]
    r = verify(ctx, d, services=services)[1]
    assert r.passed and any("'unknown' is not a buyer's word" in w for w in r.warnings) and any("'item'" in w for w in r.warnings)


def test_a_figure_free_reason_is_kept_only_when_its_option_has_no_figures(ctx, db, services):
    """AGENT-EXPERT 1c condition 3: 'no cost, rights reserved' is a fine reason for a way the records hold no figures for."""
    from decimal import Decimal

    rec, v = verify(ctx, _recommend(ctx, db, reason="no cost, rights reserved", ids=()), services=services)
    assert rec.recommended is not None and rec.recommended.reason == "no cost, rights reserved"
    ctx.register([Number(id="option:disruption:SUP-0001:allocation:cost_delta", name="Allocation: cost versus today", value=Decimal(1200), unit="USD")])
    rec, v = verify(ctx, _recommend(ctx, db, reason="no cost, rights reserved", ids=()), services=services)
    assert rec.recommended is None and any("this option has figures" in w for w in v.warnings)


def test_a_finding_is_kept_only_for_codes_fact_with_a_short_true_meaning(ctx, db, services):
    """F81 / findings.md Rev 2: the agent picks code's facts and says what each means; a bad meaning falls back to code's template."""
    a = seed(ctx, db); d = good(a)
    ctx.finding_facts = {"no_alt_quote": "No other quote on file for 4 of 5 parts (HR-40120, HR-40130, HR-40210, HR-40230)",
                         "past_due": "4 of 10 lines past their promise on Sep 25; 3 were already late before the notice of Sep 22"}
    d["findings"] = [{"key": "no_alt_quote", "meaning": "Alternatives need new quotes first"},
                     {"key": "past_due", "meaning": "3 late before the fire; rights reserved"},
                     {"key": "past_due", "meaning": "duplicate"},
                     {"key": "made_up", "meaning": "Something code never found"},
                     {"key": "no_alt_quote", "meaning": "Only 2 parts can be sourced elsewhere"},
                     {"key": "no_alt_quote", "meaning": "Lookout thinks the planner should ask everyone right now"}]
    rec, v = verify(ctx, d, services=services)
    assert v.passed and [(f.key, f.meaning) for f in rec.case_findings] == [("no_alt_quote", "Alternatives need new quotes first"), ("past_due", "3 late before the fire; rights reserved")]
    w = " ".join(v.warnings)
    assert "made_up is shown with code's template" in w and "states 2, which its fact does not" in w and "words; at most 8" in w


def test_a_short_po_line_is_an_id_only_when_one_full_line_of_this_run_ends_that_way(ctx, db, services):
    """F102 (SIDEQ's rule): 'PO 00554/30' is not the figure 554 when the run saw exactly one HPO-…-00554/30; an ambiguous or unknown one stays unchecked."""
    from decimal import Decimal

    from app.organism.verifier import short_po_refs

    ctx.register([Number(id="chase:HPO-26-00554/30", name="x", value=Decimal(5), unit="EA"),
                  Number(id="chase:HPO-26-00610/10", name="x", value=Decimal(5), unit="EA"), Number(id="chase:XPO-25-00610/10", name="x", value=Decimal(5), unit="EA")])
    assert "554" not in short_po_refs(ctx, "PO 00554/30 is late")
    assert "00610/10" in short_po_refs(ctx, "PO 00610/10 is late")          # two full lines end that way: ambiguous, stays a numeral
    assert "00999/10" in short_po_refs(ctx, "PO 00999/10 is late")          # not seen at all: stays a numeral
    a = seed(ctx, db); d = good(a); d["finding"] += " PO 00610/10 is late."
    r = verify(ctx, d, services=services)[1]
    assert "610" in r.unchecked                                                # the check is never looser


def test_first_person_narration_in_the_answer_is_a_warning(ctx, db, services):
    a = seed(ctx, db); d = good(a); d["points"] = [{"label": "Checked", "text": "I only checked the October build."}]
    r = verify(ctx, d, services=services)[1]
    assert r.passed and any("narration" in w for w in r.warnings)


def test_a_total_after_of_is_not_read_as_the_late_count_but_a_wrong_claim_still_fails(ctx):
    """run-58c80f64 (live Ask): 'Four of the ten open lines were already past due' was failed as '10 lines past due'; ten is the total there.
    The claim before 'of' is still held to the tool's count, and a plain wrong count still fails."""
    from decimal import Decimal

    from app.organism.schemas import Number
    from app.organism.verifier import count_claim_failures

    ctx.register([Number(id="item:disruption:S1:lines_already_late", name="late", value=Decimal(4), unit="lines"), Number(id="item:disruption:S1:lines_in_scope", name="scope", value=Decimal(10), unit="lines")])
    assert not count_claim_failures("Four of the ten open lines were already past due.", ctx)
    assert not count_claim_failures("Four of ten lines under Yunzhan's force majeure are past due.", ctx)
    assert any("says 3" in f for f in count_claim_failures("Three of the ten open lines were already past due.", ctx))  # the claim is still checked
    assert any("says 10" in f for f in count_claim_failures("Ten open lines were already past due.", ctx))         # no 'of': still a claim


def test_filler_in_the_answer_or_the_draft_is_a_slop_warning(ctx, db, services):
    """F112: nothing should look like slop. A warning, never a failure."""
    from app.organism.verifier import slop_words

    assert slop_words("It is important to monitor the situation and keep an eye on various factors.") == ["it is important", "keep an eye on", "monitor the situation", "various"]
    assert slop_words("Yunzhan promised revised dates by 10 October for the 10 lines.") == []
    a = seed(ctx, db); d = good(a); d["finding"] += " Moving forward, stay in close contact."
    r = verify(ctx, d, services=services)[1]
    assert r.passed and any(w.startswith("slop: 'moving forward'") for w in r.warnings)


def test_a_decision_record_awaiting_the_owner_passes_and_says_so_but_a_signed_or_addressed_one_fails(ctx, db, services):
    """BUYER Q5 (run-17fe4f0a): a staged decision failed as 'a note that is not a plain log entry' and read 'Logged a question'. A decision record that
    simply awaits the owner's signature passes and reads 'Prepared a decision'; one already executed or addressed to someone still fails."""
    a = seed(ctx, db)
    d = ledger.propose(db, type="note", item_key=ctx.item_key, run_id=ctx.run_id, target=None, recipient=None, subject="Decision", body="Bridge order HR-12210 · 200 · no prepayment",
                       change={"kind": "record", "reason": "secure the gearbox", "owner": "Dana Reyes"})
    ctx.action_ids.append(d.action_id)
    doc = good(a); doc["action_ids"] = [a.action_id, d.action_id]
    rec, v = verify(ctx, doc, services=services)
    assert v.passed, v.failures
    assert any(x.text.startswith("Prepared a decision: Bridge order HR-12210") and x.stage == "proposed" for x in rec.done)
    ledger.approve(db, d.action_id, d.payload_hash, "Dana Reyes")
    assert any("decision record that is not simply awaiting" in f for f in verify(ctx, doc, services=services)[1].failures)


def test_the_same_open_question_to_the_same_owner_is_carried_once(ctx, db, services):
    """run-38710a03 (BUYER Q3): build_readiness for October and November raised the same shelf question per owner twice (each with its month in
    `what`), and the answer listed each question twice."""
    a = seed(ctx, db)
    for month in ("2026-10", "2026-11"):
        ctx.unknowns.append(Unknown(what=f"Whether 6 parts with no open order are in stock for the T2 {month} build", why_it_blocks="x", owner="Priya", question="How many of these are on the shelf: HR-1, HR-2?"))
    rec, v = verify(ctx, good(a), services=services)
    qs = [q.question for q in rec.open_questions]
    assert qs.count("How many of these are on the shelf: HR-1, HR-2?") == 1 and v.passed, v.failures


def test_questions_to_suppliers_are_grouped_per_supplier_and_conditions_are_carried_once():
    """BUYER R1 #9 / AGENT-EXPERT: 'country of origin (and 2 like it)' hid which supplier owes the answer; the Conditions row repeated Lanxin's terms."""
    from app.domain.common import EntityRef
    from app.organism.verifier import collapse_similar

    q = lambda part: Unknown(what=f"country of origin of {part}", why_it_blocks="no origin on file", owner="supplier", question="Where is it made?", refs=[EntityRef(type="part", id=part)])  # noqa: E731
    who = {"P1": "Linfield", "P2": "Linfield", "P3": "Linfield", "P4": "Xinda", "P5": "Jadepeak"}.get
    out = collapse_similar([q(p) for p in ("P1", "P2", "P3", "P4", "P5")], supplier_of=who)
    assert [x.what for x in out] == ["country of origin of P1 (Linfield: P1, P2, P3)", "country of origin of P4", "country of origin of P5"]
    assert len(collapse_similar([q(p) for p in ("P1", "P2", "P3", "P4", "P5")])) == 1                 # no supplier lookup: the old rule


def test_a_long_situation_on_a_case_is_a_warning_on_replay(ctx, db, services):
    a = seed(ctx, db); d = good(a); d["finding"] = "Yunzhan's fire stops ten open lines, so Terns and Porters are short of motors from October onwards."
    ctx.is_case = True
    r = verify(ctx, d, services=services)[1]
    assert r.passed and any("Situation has 17 words" in w for w in r.warnings)


def test_collapse_keeps_both_rules_per_supplier_grouping_and_one_identical_pair():
    """Fold of fp-agent R1 (per-supplier grouping) with agent2 (an identical pair is one question): both rules hold together."""
    from app.domain.common import EntityRef
    from app.organism.verifier import collapse_similar

    q = lambda part, question="Where is it made?": Unknown(what=f"country of origin of {part}", why_it_blocks="no origin on file", owner="supplier", question=question, refs=[EntityRef(type="part", id=part)])  # noqa: E731
    who = {"P1": "Linfield", "P2": "Linfield", "P3": "Linfield", "P4": "Xinda", "P5": "Xinda"}.get
    out = collapse_similar([q("P1"), q("P2"), q("P3"), q("P4"), q("P5")], supplier_of=who)
    assert [x.what for x in out] == ["country of origin of P1 (Linfield: P1, P2, P3)", "country of origin of P4"]      # Xinda's identical pair is one question
    out2 = collapse_similar([q("P1"), q("P4"), q("P5", "When does it ship?")], supplier_of=who)
    assert [x.what for x in out2] == ["country of origin of P1", "country of origin of P4", "country of origin of P5"]      # a pair asking different things stays two


def test_a_count_before_the_notice_is_refused_at_the_write_and_dropped_from_a_reason_or_meaning(ctx, db, services):
    from app.organism.gate import decide
    from app.organism.verifier import before_notice_claim

    assert before_notice_claim("Four were already past their promised dates before the fire") and not before_notice_claim("Four were past due on 25 September")
    ctx.delegated = list(ctx.plan)
    ctx.handoffs.update({m: object() for m in ctx.plan})
    ctx.handoffs_seen = set(ctx.handoffs)
    ok, why = decide(ctx, None, "StructuredOutput", {"finding": "Four lines were late before the notice; 182 robots short.", "points": []})
    assert not ok and "past due on" in why
    a = seed(ctx, db); d = _recommend(ctx, db, reason="4 lines late before the fire", ids=("supply:HR-40110:stuck_qty",))
    ctx.finding_facts = {"past_due": "4 of 10 lines past their promise on Sep 25"}
    d["findings"] = [{"key": "past_due", "meaning": "Lines were late before the fire"}]
    rec, v = verify(ctx, d, services=services)
    assert v.passed and rec.recommended is None and rec.case_findings == []


def test_the_conditions_row_is_capped_but_the_carry_warning_keeps_every_condition(ctx, db, services):
    """AGENT-EXPERT C1: a capped list must not hide the 5th and 6th condition from the gate's warning."""
    a = seed(ctx, db); d = good(a)
    ctx.conditions = {f"c{i}": {"text": f"condition number {i}", "tokens": [f"tok{i}x"]} for i in range(6)}
    rec, v = verify(ctx, d, services=services)
    w = next(x for x in v.warnings if x.startswith("carry:"))
    assert all(f"condition number {i}" in w for i in range(6))
    row = next(p for p in rec.points if p.label == "Conditions").text
    assert "condition number 3" in row and "condition number 4" not in row and "+2 more" in row


def test_a_full_po_line_id_is_not_a_stray_id():
    """G2 (PREVIEW 2b): HPO-26-00517/10 was warned as an unknown id; only supplier ids are checked by shape there."""
    import inspect

    from app.organism import verifier
    src = inspect.getsource(verifier)
    assert '"supplier", "legacy_supplier").findall' in src and '"po_line", "supplier"' not in src


def test_an_owed_lookup_still_fails_the_run_after_the_deadlock_fix(ctx, db, services):
    """AGENT-EXPERT on 27235b8: the gate no longer blocks Lookout's write, so the verifier is what keeps an owed call honest (must FAIL)."""
    draft = _recommend(ctx, db)
    _, v = verify(ctx, draft, services=services, required_calls=[("shortage", "HR-40120")])
    assert not v.passed and any("shortage was not run for HR-40120" in f for f in v.failures)
    ctx.calls_made.add(("shortage", "HR-40120"))
    _, v = verify(ctx, _recommend(ctx, db), services=services, required_calls=[("shortage", "HR-40120")])
    assert not any("was not run for" in f for f in v.failures)


def test_a_staged_note_awaiting_the_owner_passes_and_reads_prepared_but_a_signed_one_in_the_run_fails(ctx, db, services):
    """LOOKOUT P1: a note the buyer asked for is staged, not recorded. A note with change.kind 'note' must be PROPOSED to no one; its done line says so."""
    a = seed(ctx, db)
    n = ledger.propose(db, type="note", item_key=ctx.item_key, run_id=ctx.run_id, target=None, recipient=None, subject="Note to planning", body="Re-sequence the October builds",
                       change={"kind": "note", "to": "planning", "reason": "short motors", "owner": "Dana Reyes"})
    ctx.action_ids.append(n.action_id)
    doc = good(a); doc["action_ids"] = [a.action_id, n.action_id]
    rec, v = verify(ctx, doc, services=services)
    assert v.passed, v.failures
    assert any(x.text == "Prepared a note to planning: waiting for your approval" and x.stage == "proposed" for x in rec.done)
    ledger.approve(db, n.action_id, n.payload_hash, "Dana Reyes")
    assert any("staged note that is not simply awaiting" in f for f in verify(ctx, doc, services=services)[1].failures)


def test_an_ask_answer_that_claims_it_prepared_an_action_fails_unless_one_waits_for_signature(ctx, db, services):
    """SIDEQ (verifier gap; LOOKOUT P1): an Ask could say 'a note to planning is staged for your signature' with nothing staged. The claim now needs a
    PROPOSED action of this run; negations and offers are not claims."""
    from dataclasses import replace

    ask = replace(ctx, item_key="ask:claim001", run_id="run-claim", action_ids=[])
    ask.register(list(ctx.evidence.values()))
    ask.unknowns.append(ON_HAND)
    ask.handoffs.update(supply_planner=object())
    ask.handoffs_seen = set(ask.handoffs)
    ask.seen_dates.add((10, 10))
    claim = {"finding": "A re-sequencing note to planning is staged for your signature.", "numbers": [], "open_questions": [ON_HAND.model_dump()],
             "next_step": {"who": "Dana Reyes", "what": "Approve the note", "by": ""}}
    v = verify(ask, claim, services=services)[1]
    assert any(f.startswith("claims:") for f in v.failures) and "nothing is waiting for signature" in " ".join(v.reasons)
    ready = {**claim, "finding": "Note to planning on moving October builds is ready for your signature."}  # LOOKOUT live wording
    assert any(f.startswith("claims:") for f in verify(ask, ready, services=services)[1].failures)
    for honest in ("No bridge order is drafted yet; say if you want one.", "An RFQ note for sourcing can be prepared on request.", "The draft to Li Wei waits for your approval.",
                   "The request to Li Wei is already staged from the case run."):
        doc = {**claim, "finding": honest}
        assert not any(f.startswith("claims:") for f in verify(ask, doc, services=services)[1].failures), honest
    n = ledger.propose(db, type="note", item_key="disruption:SUP-0001", run_id="run-claim", target=None, recipient=None, subject="Note to planning", body="Re-sequence",
                       change={"kind": "note", "to": "planning", "owner": "Dana Reyes"})
    ask.action_ids.append(n.action_id)
    assert not any(f.startswith("claims:") for f in verify(ask, {**claim, "action_ids": [n.action_id]}, services=services)[1].failures)  # staged: the claim is true
    case = verify(ctx, {**claim}, services=services)[1]  # a case run's own answers are not held to this Ask rule
    assert not any(f.startswith("claims:") for f in case.failures)


def test_a_figure_no_tool_returned_in_an_open_question_is_marked_too(ctx, db, services):
    """AI-UI-SYNC (a): the model's own questions are read for figures like the rest of the answer."""
    a = seed(ctx, db); d = good(a)
    d["open_questions"] = [{**ON_HAND.model_dump(), "question": "Are about 270 on the shelf?"}]
    r = verify(ctx, d, services=services)[1]
    assert "270" in r.unchecked and r.passed


def test_a_planned_count_said_to_be_short_fails_and_a_true_short_passes(ctx, db, services):
    """AI-UI-SYNC (b): a count that is only planned (the forecast) is never 'short'."""
    a = seed(ctx, db)
    ctx.register([Number(id="item:x:tile:robots:HR-90020:2026-10", name="Tern T2 planned in October", value=Decimal(182), unit="robots")])
    d = good(a); d["finding"] = "Up to 182 Tern T2 robots short in October."; d["numbers"].append({"id": "item:x:tile:robots:HR-90020:2026-10", "value": 182})
    assert any("planned count" in f for f in verify(ctx, d, services=services)[1].failures)
    d = good(a)                                                                 # '364 EA short' cites a shortfall: no claim failure
    assert not any("planned count" in f for f in verify(ctx, d, services=services)[1].failures)
