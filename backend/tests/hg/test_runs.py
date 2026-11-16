"""Runs drafted by code, the mocked recordings, Ask answered by code, and the steward's reading: each checked, each labelled for what it is."""

import time


def wait(client, run_id):
    for _ in range(100):
        r = client.get(f"/api/runs/{run_id}").json()
        if r["status"] != "running":
            return r
        time.sleep(0.05)
    raise AssertionError("the run did not finish")


def test_a_code_run_passes_its_checks_and_prepares_the_recommended_draft(client):
    r = wait(client, client.post("/api/action-items/pv-claim:4500121087/runs", json={"asked_by": "Vishnu"}).json()["run_id"])
    assert r["status"] == "ok" and r["mode"] == "code" and r["recommendation"]["drafted_by"] == "code"
    assert r["recommendation"]["recommended"]["kind"] == "reply_computed" and r["recommendation"]["grade"]["reviewer_score"] == 100
    d = client.get("/api/action-items/pv-claim:4500121087").json()
    assert d["stage"]["key"] == "decision_ready"      # the prepared draft waits for the owner's choice
    a = client.post("/api/action-items/pv-claim:4500121087/routes/reply_computed/choose", json={"by": "Vishnu"}).json()
    assert a["change"]["how"] == "prepared"


def test_a_mocked_recording_is_replayed_and_labelled(client):
    r = wait(client, client.post("/api/action-items/mfc-validity:4500120768/runs", json={}).json()["run_id"])
    assert r["recorded"] and r["status"] == "ok"
    assert any("mocked" in e["summary"] for e in r["events"] if e["type"] == "run.started")


def test_ask_answers_from_the_records_by_code(client):
    q = lambda text, ctx=None, by="Satish Kumar Sharma": wait(client, client.post("/api/ask", json={"question": text, "context": ctx, "asked_by": by}).json()["run_id"])["recommendation"]  # noqa: E731
    assert "Projects for 23 days" in q("Where does PR 1000203689 stand?")["finding"]
    assert q("Which of these 32 PRs had quotes in hand?", {"type": "item", "id": "pr-cancelled:gaya:2026-10-15"})["finding"].startswith("32 of the 32")
    assert "do not say why" in q("Why does Gaya pay more for aggregate than Anuppur?")["finding"]
    refused = q("Prepare a note to the Gaya project head asking for cancellation approval", {"type": "item", "id": "pr-cancelled:gaya:2026-10-15"}, "Jitender Swami")
    assert "Only" in refused["finding"]
    drafted = q("Prepare a note to the Gaya project head asking for cancellation approval", {"type": "item", "id": "pr-cancelled:gaya:2026-10-15"}, "Sambhav Kumar")
    assert drafted["action_ids"]


def test_the_steward_reads_the_site_offices_export_and_asks_about_the_plant(client):
    ex = client.get("/api/imports/steward-example").json()
    r = wait(client, client.post("/api/imports/steward-runs", json={"filename": ex["filename"], "text": ex["text"], "asked_by": "Sudeep"}).json()["run_id"])
    st = r["recommendation"]["steward"]
    assert st["table"] == "ME2N purchase orders" and len(st["mapping"]) >= 12
    assert any("dd/mm/yyyy" in f["issue"] for f in st["findings"])
    assert any("Arurangabad" in q["question"] and "1905" in q["question"] for q in st["questions"])
