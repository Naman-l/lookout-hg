"""FINAL 07 §12b: the case page's Linked cases come from the same rule as the agent's packet (shared order line, part, supplier or message)."""

from fastapi.testclient import TestClient

from app.main import app


def test_a_case_lists_the_other_cases_it_shares_records_with_strongest_link_first():
    c = TestClient(app)
    linked = c.get("/api/action-items/risk:SUP-0002").json()["linked"]
    assert linked and all(l["key"] != "risk:SUP-0002" and l["title"] and l["why"].startswith("the same ") for l in linked)
    order = ["the same order line", "the same part", "the same supplier", "the same message"]
    ranks = [next(n for n, w in enumerate(order) if l["why"].startswith(w)) for l in linked]
    assert ranks == sorted(ranks) and len(linked) <= 6
