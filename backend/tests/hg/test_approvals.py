"""Approvals over HTTP: owner-only signing, the DoA countersign on the same hash, internal notes and the wait they put the case in, one letter per
contact, and nothing drafted from a held message."""

KEY = "mfc-validity:4500120768"


def test_an_mfc_above_the_threshold_is_signed_then_countersigned(client):
    a = client.post(f"/api/action-items/{KEY}/routes/issue_mfc/choose", json={"by": "Sambhav"}).json()      # the buyer's lead, who issues an MFC
    assert a["countersign"] == "Satish Kumar Sharma" and "also needs Satish Kumar Sharma" in a["doa_line"]
    assert "Kind Attn:" in a["body"] and "Sub:" in a["body"] and "Kindly confirm by" in a["body"] and "Supply Chain Management" in a["body"]
    assert client.post(f"/api/actions/{a['action_id']}/approve", json={"payload_hash": a["payload_hash"], "approved_by": "Rohit"}).status_code == 403
    signed = client.post(f"/api/actions/{a['action_id']}/approve", json={"payload_hash": a["payload_hash"], "approved_by": "Sambhav"}).json()
    assert signed["state"] == "signed"
    assert client.post(f"/api/actions/{a['action_id']}/approve", json={"payload_hash": a["payload_hash"], "approved_by": "Sambhav"}).status_code == 403
    assert client.get("/api/counts?buyer=Satish").json()["countersign_mine"] == 1
    assert KEY in {i["key"] for i in client.get("/api/action-items?owner=Satish").json()}
    sent = client.post(f"/api/actions/{a['action_id']}/approve", json={"payload_hash": a["payload_hash"], "approved_by": "Satish"}).json()
    assert sent["state"] == "executed" and sent["signed_by"] == "Sambhav Kumar" and sent["decided_by"] == "Satish Kumar Sharma"
    assert len([o for o in client.get("/api/outbox").json() if o["action_id"] == a["action_id"]]) == 1
    d = client.get(f"/api/action-items/{KEY}").json()
    assert d["stage"]["key"] == "sent" and any("countersigned" in x["text"] for x in d["decisions"])


def test_a_stale_hash_is_refused(client):
    a = client.post(f"/api/action-items/{KEY}/routes/extend_validity/choose", json={"by": "Deepanshu"}).json()
    assert client.post(f"/api/actions/{a['action_id']}/approve", json={"payload_hash": "0" * 64, "approved_by": "Deepanshu"}).status_code == 409


def test_an_internal_note_puts_the_case_with_projects_until_they_answer(client, fresh_db):
    key = "pr-stuck:1000203689"
    a = client.post(f"/api/action-items/{key}/routes/ask_projects/choose", json={"by": "Rohit"}).json()
    assert a["type"] == "internal_note" and a["body"].startswith("To: ") and a["countersign"] is None
    client.post(f"/api/actions/{a['action_id']}/approve", json={"payload_hash": a["payload_hash"], "approved_by": "Rohit"})
    row = next(i for i in client.get("/api/action-items").json() if i["key"] == key)
    assert row["stage"]["label"] == "With Projects" and row["waiting_on"] == "Projects"
    from app import db
    from app.domain.inbox import simulate_reply
    with db.SessionLocal() as s:
        assert simulate_reply.simulate_all(s, db.DB_PATH)
    row = next(i for i in client.get("/api/action-items").json() if i["key"] == key)
    assert row["stage"]["key"] == "answered"


def test_one_letter_per_contact_carries_a_second_cases_ask(client):
    first = client.post(f"/api/action-items/{KEY}/routes/extend_validity/choose", json={"by": "Deepanshu"}).json()
    second = client.post("/api/action-items/inspection-ready:4500121346/routes/inspect_hold/choose", json={"by": "Deepanshu"}).json()
    assert second["action_id"] == first["action_id"] and second["change"]["how"] == "amended"
    assert "inspection" in second["body"] and second["body"].rstrip().endswith("H.G. Infra Engineering Ltd.")


def test_nothing_is_drafted_from_a_held_message_and_only_the_owner_chooses(client):
    held = next(i["key"] for i in client.get("/api/action-items").json() if i["tab"] == "trust")
    assert client.post(f"/api/action-items/{held}/routes/x/choose", json={"by": "Rohit"}).status_code == 409
    assert client.post(f"/api/action-items/{KEY}/routes/issue_mfc/choose", json={"by": "Jitender"}).status_code == 403


def test_a_reply_to_a_claim_keeps_rights_and_names_no_bank_details(client):
    a = client.post("/api/action-items/pv-claim:4500121087/routes/reply_computed/choose", json={"by": "Vishnu"}).json()
    assert "This is without prejudice to our rights under the PO." in a["body"]
    from app.domain.actions.letters import DraftRefused, style
    try:
        style("Please send the payment to the new bank account below.")
        raise AssertionError("a bank word must be refused")
    except DraftRefused:
        pass
