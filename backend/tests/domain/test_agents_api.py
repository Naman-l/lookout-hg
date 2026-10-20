"""Under the hood (FINAL 08 B-b, B-c): the agents and what the recordings show each did, and the last measured eval round."""

from fastapi.testclient import TestClient

from app.main import app


def test_agents_count_what_the_recordings_show_each_agent_did():
    d = TestClient(app).get("/api/agents").json()
    assert (d["recorded_runs"], d["recorded_cost_usd"], d["earlier_prompt"]) == (59, 7.28, 39)   # the 2026-10-14 re-record: 11 cases re-made, 3 demo Ask turns added, 7 entries off STALE.md; then Quenvara and BCX recorded, consignment, Great Plains and the chase re-recorded (Khalid's yes)
    by = {a["name"]: a for a in d["agents"]}
    assert [a["name"] for a in d["agents"]][0] == "lookout" and by["lookout"]["role"] == "orchestrator" and by["lookout"]["stages"] == ["overview", "decision"]
    assert {n: (by[n]["runs"], by[n]["lookups"]) for n in ("supply_planner", "tariff_analyst", "sourcing_analyst", "inbox_analyst", "data_steward")} == {
        "supply_planner": (16, 84), "tariff_analyst": (7, 19), "sourcing_analyst": (8, 41), "inbox_analyst": (26, 75), "data_steward": (1, 11)}
    assert (by["buyers_clerk"]["runs"], by["buyers_clerk"]["drafts"], by["buyers_clerk"]["questions"], by["buyers_clerk"]["stages"]) == (34, 44, 11, ["approval"])
    assert by["inbox_analyst"]["stages"] == ["analysis"] and by["lookout"]["by_stage"]["decision"]["tools"] == ["get_handoffs"]
    assert "draft_supplier_request" in by["buyers_clerk"]["tools"] and by["sourcing_analyst"]["tools"][0] == "compare_offers"


def test_the_eval_summary_is_the_dated_round_as_measured():
    d = TestClient(app).get("/api/evals/summary").json()
    assert (d["date"], d["round"], d["trials"]) == ("2026-10-12", 12, 2)
    assert {r["label"]: r["value"] for r in d["rows"]} == {
        "Right action": "6 of 7", "Guardrails held": "7 of 8", "Guardrails held, model controls": "8 of 9 trials", "System checks": "8 of 8",
        "Conditions stated": "4 of 7", "Right wording": "2 of 7", "Every figure, owner and date right, in every trial": "1 of 7", "Held-out sheets": "1 of 6"}
