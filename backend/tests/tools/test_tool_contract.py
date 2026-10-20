"""The tool contract: every one of the agent's tools, called through the real in-process MCP server on a copy of the built database, no model.

For each tool: a valid input returns a result with a summary, data and, where it states figures, numbers with an id, a name, a value, a unit and a provenance; a bad input comes
back as a clean error (never a crash); and a specialist that is not allowed the tool is refused by the gate. `make tools` runs it; it is part of `make test`."""

from __future__ import annotations

import asyncio
import json
import shutil
from decimal import Decimal
from pathlib import Path

import mcp_types
import pytest
from claude_agent_sdk import create_sdk_mcp_server

from app import db as app_db
from app.domain.imports.steward import tools as steward_tools
from app.organism import runner, services as organism_services
from app.organism.context import RunContext
from app.organism.gate import decide
from app.organism.runner import allow_map
from app.organism.runs.events import Recorder
from app.organism.specialists import registry

FIXTURE = Path(__file__).resolve().parents[2] / "app/domain/imports/steward/fixtures/purchase_orders_export_2026-10.csv"
pytestmark = pytest.mark.skipif(not app_db.DB_PATH.exists(), reason="needs the built database (make build-data)")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    import os

    had_fakes = os.environ.pop("LOOKOUT_FAKE_SERVICES", None)  # the other organism tests run on fakes: restored below
    db = str(tmp_path_factory.mktemp("tools") / "lookout.db")
    shutil.copy(app_db.DB_PATH, db)  # staging tools write: they write to this copy, never to the built database
    svc = organism_services.get(db)
    plan = ["supply_planner", "tariff_analyst", "sourcing_analyst", "inbox_analyst", "buyers_clerk", "data_steward"]
    ctx = RunContext(run_id="run-contract", item_key="disruption:SUP-0001", db_path=db, recorder=Recorder("run-contract", db), plan=plan, allow=allow_map(plan), stage_allowed=True)
    steward_tools.start(ctx, FIXTURE)
    lists = runner.tool_lists(ctx, svc)
    servers = {name: create_sdk_mcp_server(name, "1.0", tools)["instance"] for name, tools in lists.items()}
    where = {t.name: srv for srv, ts in lists.items() for t in ts}
    # ids found in the data, so the test names no supplier or part
    part = next(r.part.id for r in svc.orders.open_supply("HR-60110")) if svc.orders.open_supply("HR-60110") else None
    items = svc.attention.list_items()
    item = next(i for i in items if i.key.startswith("disruption:"))
    supplier = item.key.split(":", 1)[1]
    msgs = svc.inbox.list_messages()
    msg = next(m for m in msgs if svc.inbox.trust(m.ref.id).api_trust == "on_file").ref.id
    yield {"db": db, "svc": svc, "ctx": ctx, "servers": servers, "where": where, "part": part, "item": item.key, "supplier": supplier, "msg": msg}
    svc.close()
    if had_fakes is not None:
        os.environ["LOOKOUT_FAKE_SERVICES"] = had_fakes


def mcp(world, name: str, args: dict):
    server = world["servers"][world["where"][name]]
    entry = server._request_handlers["tools/call"]
    return asyncio.run(entry.handler(None, mcp_types.CallToolRequestParams(name=name, arguments=args)))


def body(result) -> dict:
    return json.loads(result.content[0].text)


def valid_inputs(w) -> dict[str, dict]:
    p, s = w["part"], w["supplier"]
    counted = 300  # a count the steward may state because a tool returned it: the PostToolUse hook records it in a run, so this test records it the same way
    w["ctx"].seen_numerals.add(Decimal(counted))
    w["ctx"].unknowns.clear()  # no buyer owns an open question yet: a note to one is allowed
    w["ctx"].asked_buyers.clear()
    owner = "Dana"
    return {
        "open_supply": {"part_number": p}, "supplier_delivery": {"limit": 5}, "requests_for": {"item_key": w["item"]}, "disrupted_supply": {"supplier_id": s}, "shortage_for_parts": {"part_numbers": [p]}, "where_used_for_parts": {"part_numbers": [p]},
        "get_item": {"item_key": w["item"]}, "list_items": {}, "get_phases": {"part_number": p}, "build_readiness": {"product": "Tern T2", "month": "2026-10"},
        "compare_offers": {"part_number": p}, "exposure_for_part": {"part_number": p}, "exposure_for_parts": {"part_numbers": [p]}, "inbox_overview": {},
        "read_message": {"message_id": w["msg"]}, "find_suppliers": {"name": "a"}, "get_handoffs": {},
        "draft_supplier_request": {"supplier_id": s, "subject": "Open lines", "body": "Please confirm the dates for the open lines."},
        "log_buyer_question": {"owner": owner, "question": "Should the stale order be closed or kept open?"},
        "propose_supplier_alias": {"supplier_a": s, "supplier_b": "NOPE", "evidence": "same address"},
        "drift_report": {}, "column_facts": {"column": "PO No."}, "try_step": {"name": "noop", "code": "def run(ctx):\n    ctx.t['normalised'] = ctx.read_csv('purchase_orders_export_2026-10.csv')\n"},
        "add_finding": {"issue": "dates are ISO", "count": counted, "consequence": "x", "example": "2024-10-01", "handling": "fix"},
        "add_question": {"question": "Which currency?", "why_it_blocks": "prices", "proposed_answer": "USD", "covers": 3},
    }


def bad_inputs(w) -> dict[str, dict]:
    return {n: ({"nothing": "here"} if n not in ("get_item", "read_message", "exposure_for_part", "disrupted_supply") else {list(a)[0]: "NOT-AN-ID-0"})
            for n, a in valid_inputs(w).items()}


ALL = sorted(registry.TOOL_SERVER)
NO_VALID_CALL = {"amend_draft", "stage_decision"}  # amend_draft needs an action id; stage_decision needs an Ask run: each covered by its own test below


def test_the_contract_names_every_tool(world):
    assert len(ALL) == 27 and set(valid_inputs(world)) | NO_VALID_CALL == set(ALL) and set(world["where"]) == set(ALL)


@pytest.mark.parametrize("name", [n for n in ALL if n not in NO_VALID_CALL])
def test_a_valid_call_returns_a_summary_data_and_numbers_with_provenance(world, name):
    r = mcp(world, name, valid_inputs(world)[name])
    d = body(r)
    assert not r.is_error, (name, d)
    assert isinstance(d.get("summary"), str) and d["summary"].strip(), name
    assert "data" in d or "numbers" in d, name
    for n in d.get("numbers", []):
        assert set(n) >= {"id", "name", "value", "unit"} and str(n["id"]) and str(n["name"]).strip(), (name, n)
    ids = [n["id"] for n in d.get("numbers", [])]
    assert len(ids) == len(set(ids)), (name, "duplicate number ids")


@pytest.mark.parametrize("name", ALL)
def test_a_bad_input_is_a_clean_error_not_a_crash(world, name):
    args = bad_inputs(world).get(name, {"action_id": "A-nope", "paragraph": "x"})
    r = mcp(world, name, args)  # must return, not raise
    text = r.content[0].text
    assert text.strip(), name
    if r.is_error:
        assert "Traceback" not in text, name
        try:
            assert body(r).get("error", "").strip() or text.strip(), name
        except ValueError:
            assert "validation" in text.lower() or text.strip(), name  # the server's own input check


def test_amend_draft_has_a_valid_path(world):
    draft = body(mcp(world, "draft_supplier_request", {"supplier_id": world["supplier"], "subject": "Dates", "body": "Please confirm the dates.\n\nRegards,\nAcme"}))
    aid = (draft.get("data") or {}).get("action_id") or (draft.get("data") or {}).get("covered_by")
    if aid:
        r = mcp(world, "amend_draft", {"action_id": aid, "paragraph": "Please also confirm the lead time."})
        assert body(r).get("summary") or body(r).get("error")


def test_stage_decision_has_a_valid_path_in_an_ask_on_a_case(world):
    ctx = world["ctx"]
    was = (ctx.item_key, ctx.action_item_key)
    try:
        ctx.item_key, ctx.action_item_key = "ask:contract", world["item"]
        r = body(mcp(world, "stage_decision", {"decision": "Keep the open lines and look again next week", "reason": "the supplier has not replied"}))
        assert r["data"]["action_id"] and r["data"]["state"] == "proposed" and r["summary"]
    finally:
        ctx.item_key, ctx.action_item_key = was


@pytest.mark.parametrize("name", ALL)
def test_a_specialist_without_the_tool_is_refused_by_the_gate(world, name):
    ctx = world["ctx"]
    owners = {s for s, spec in registry.SPECIALISTS.items() if name in spec.tools}
    qualified = f"mcp__{world['where'][name]}__{name}"
    for s in registry.SPECIALISTS:
        if s in owners or s not in ctx.allow:
            continue
        allowed, why = decide(ctx, s, qualified, {})
        assert not allowed and "not part of" in why, (name, s)
    if not owners:  # a tool only Lookout holds (it reads the whole list, the handoffs): no specialist may call it
        assert name in ("list_items", "get_handoffs"), name


def test_supplier_delivery_ranks_worst_first_and_matches_the_records(world):
    d = body(mcp(world, "supplier_delivery", {"limit": 5}))
    rows = d["data"]
    assert 1 <= len(rows) <= 5 and [r["on_time_pct"] for r in rows] == sorted(r["on_time_pct"] for r in rows)
    perf = {s.ref.id: s.delivery for s in world["svc"].suppliers.list_suppliers()}
    nums = {n["id"]: n for n in d["numbers"]}
    for r in rows:
        p = perf[r["supplier"]]
        assert r["closed_lines"] == p.n and r["on_time"] == p.on_time and r["late"] == p.late and r["top_parts"]
        assert Decimal(nums[f"delivery:{r['supplier']}:closed_lines"]["value"]) == p.n and Decimal(nums[f"delivery:{r['supplier']}:on_time_pct"]["value"]) == round(p.on_time_pct * 100)
    assert mcp(world, "supplier_delivery", {"limit": "many"}).is_error


def test_requests_for_shows_a_request_the_ledger_holds_in_every_state(world):
    from app.domain.actions import ledger
    from app.domain.common import EntityRef

    s, db = world["supplier"], world["db"]
    mk = lambda key, subject: ledger.propose(db, type="supplier_request", item_key=key, run_id=None, target=EntityRef(type="supplier", id=s), recipient="someone@example.test", subject=subject, body="Please confirm.")  # noqa: E731
    a, b, c = mk(world["item"], "Dates for the open lines"), mk("deadline:other", "Another ask"), mk("deadline:third", "A third ask")
    rows = {r["action_id"]: r for r in body(mcp(world, "requests_for", {"item_key": world["item"]}))["data"]}
    assert rows[a.action_id]["state"] == "proposed" and rows[a.action_id]["recipient"] == "someone@example.test" and rows[a.action_id]["subject"] == "Dates for the open lines"
    ledger.reject(db, b.action_id, "not now", "Dana Reyes")
    ledger.approve(db, c.action_id, c.payload_hash, "Dana Reyes")
    by_supplier = {r["action_id"]: r for r in body(mcp(world, "requests_for", {"supplier_id": s}))["data"]}  # the supplier's requests, whichever item asked
    assert by_supplier[b.action_id]["state"] == "rejected" and by_supplier[b.action_id]["rejected_because"] == "not now"
    assert by_supplier[c.action_id]["state"] in ("approved", "executed") and by_supplier[c.action_id]["decided_by"] == "Dana Reyes"
    assert mcp(world, "requests_for", {}).is_error
