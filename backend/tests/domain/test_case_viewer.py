"""BUYER final review #1: a team case opened by one buyer shows that buyer's slice (title, figure, own lines), as Today's "Yours" does."""

from fastapi.testclient import TestClient

from app.main import app


def test_the_past_due_case_opened_by_a_buyer_is_their_slice_and_the_team_view_is_unchanged():
    c = TestClient(app)
    mine = c.get("/api/action-items/deadline:chase", params={"owner": "Dana Reyes"}).json()
    team = c.get("/api/action-items/deadline:chase").json()
    assert mine["title"].startswith("2 past-due lines") and round(float(mine["at_stake"]["usd"])) == 80_805
    assert {l["buyer"] for l in mine["po_lines"]} == {"Dana Reyes"} and len(mine["po_lines"]) == 2
    assert team["title"].startswith("16 past-due lines") and len(team["po_lines"]) == 16
    fire = c.get("/api/action-items/disruption:SUP-0001", params={"owner": "Dana Reyes"}).json()
    assert len(fire["po_lines"]) == 10      # a case that is already one buyer's keeps every line
