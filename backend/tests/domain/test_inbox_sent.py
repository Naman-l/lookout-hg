"""A request we sent to a sender's company is visible beside that sender's message: a `replied` mark on the row, the request on the page."""
from types import SimpleNamespace

from app.domain.actions import ledger
from app.domain.common import EntityRef
from app.domain.inbox import service
from app.domain.inbox.schema import MessageSummary, SentRequest


def summary(mid, supplier, date):
    return MessageSummary(ref=EntityRef(type="message", id=mid), date=date, **{"from": "x"}, supplier=EntityRef(type="supplier", id=supplier) if supplier else None,
                          trust="on_file", summary="s")


def session_on(path):
    return SimpleNamespace(get_bind=lambda: SimpleNamespace(url=SimpleNamespace(database=str(path))))


def test_only_executed_supplier_requests_are_listed_newest_first(tmp_path):
    path = tmp_path / "a.db"
    a = ledger.propose(path, type="supplier_request", item_key="k", run_id="r", target=EntityRef(type="supplier", id="S1"), recipient="a@x.example", subject="Quote Q-1: validity", body="b")
    ledger.propose(path, type="supplier_request", item_key="k", run_id="r", target=EntityRef(type="supplier", id="S2"), recipient="b@y.example", subject="waits", body="b")
    ledger.approve(path, a.action_id, a.payload_hash, "Dana Reyes")
    got = service.sent_requests(session_on(path))
    assert list(got) == ["S1"] and got["S1"][0].subject == "Quote Q-1: validity" and got["S1"][0].action_id == a.action_id


def test_a_row_is_marked_replied_only_when_a_request_went_to_its_company_on_or_after_its_day(monkeypatch):
    monkeypatch.setattr(service, "sent_requests", lambda s: {"S1": [SentRequest(action_id="A-1", subject="q", sent_on="2026-10-12")]})
    rows = service.mark_replied(None, [summary("M1", "S1", "2026-10-09T10:00:00"), summary("M2", "S1", "2026-10-13T10:00:00"), summary("M3", "S2", "2026-10-09"), summary("M4", None, "2026-10-09")])
    assert [r.replied for r in rows] == [True, False, False, False]
