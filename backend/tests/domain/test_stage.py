"""Where the work on an item stands, derived from the runs and the ledger and never stored."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domain.attention import stage
from app.domain.attention.schema import ActionItem
from app.domain.common import EntityRef

ITEM = ActionItem(key="deadline:S:2026-10-10", group="deadline", severity="high", title="t", owner="Dana Reyes", act_by="2026-10-10",
                  refs=[EntityRef(type="supplier", id="SUP-1", label="Yunzhan")])


def act(**kw):
    base = dict(action_id="A-1", type="supplier_request", state="proposed", recipient=None, proposed_at="2026-10-11T10:00:00", decided_at=None, confirmed_at=None, reason=None)
    return SimpleNamespace(**{**base, **kw})


def derive(runs=(), actions=(), answered=None, names=None):
    return stage.derive(ITEM, list(runs), list(actions), answered or {}, names)


def test_a_new_item_is_found_and_waits_for_you():
    s = derive()
    assert (s.key, s.step, s.waiting_on) == ("found", 1, "you") and s.next_act.startswith("Work this item")


@pytest.mark.parametrize("status,key,words", [("running", "worked", "working on it"), ("did_not_pass", "worked", "did not finish"), ("failed", "worked", "did not finish"),
                                              ("ok", "decision_ready", "Recommendation")])
def test_a_run_moves_it_along(status, key, words):
    s = derive(runs=[(status, "2026-10-11T09:00:00")])
    assert s.key == key and words in s.next_act


def test_a_waiting_draft_is_drafted_and_names_who_it_goes_to():
    s = derive(runs=[("ok", "x")], actions=[act(recipient="li.wei@example.com")])
    assert (s.key, s.step, s.waiting_on) == ("drafted", 4, "you") and "li.wei@example.com" in s.next_act


def test_an_approved_send_is_sent_and_waits_for_the_supplier_with_the_chase_date():
    a = act(state="executed", recipient="li.wei@example.com", decided_at="2026-10-11T11:00:00", confirmed_at="2026-10-11T11:00:01")
    s = derive(runs=[("ok", "x")], actions=[a])
    assert (s.key, s.step, s.waiting_on) == ("sent", 6, "the supplier") and "Waiting for Yunzhan" in s.next_act and "simulated" in s.next_act


def test_the_sent_line_names_the_contact_and_the_data_date_never_the_address_or_the_wall_clock():
    from app.domain.common import AS_OF
    from app.domain.fmt import md
    a = act(state="executed", recipient="li.wei@example.com", decided_at="2026-10-14T11:00:00", confirmed_at="2026-10-14T11:00:01")
    s = stage.derive(ITEM, [("ok", "x")], [a], {}, None, "Li Wei")
    assert s.next_act.startswith(f"Sent to Li Wei on {md(AS_OF.isoformat())} (simulated). Waiting for Li Wei") and "@" not in s.next_act and "Oct 14" not in s.next_act


def test_a_later_message_from_the_supplier_makes_it_answered():
    a = act(state="executed", decided_at="2026-10-11T11:00:00", confirmed_at="2026-10-11T11:00:01")
    assert derive(actions=[a], answered={"SUP-1": "2026-10-09"}).key == "sent"            # older than the send
    s = derive(actions=[a], answered={"SUP-1": "2026-10-14"})
    assert (s.key, s.step, s.waiting_on) == ("answered", 7, "you")


def test_a_recorded_link_is_approved_and_nothing_waits():
    s = derive(actions=[act(type="supplier_alias", state="executed", decided_at="2026-10-11T11:00:00")])
    assert (s.key, s.waiting_on) == ("approved", None) and "link is recorded" in s.next_act


def test_a_rejected_draft_returns_it_to_you_with_the_reason():
    s = derive(runs=[("ok", "x")], actions=[act(state="rejected", decided_at="2026-10-11T11:00:00", reason="wrong contact")])
    assert s.key == "decision_ready" and "wrong contact" in s.next_act and "Revise it with the agent" in s.next_act


def test_a_note_does_not_move_the_stage():
    assert derive(actions=[act(type="note", state="executed", decided_at="2026-10-11T11:00:00")]).key == "found"



def test_dates_are_the_buyers_day_not_utc():
    from app.domain.fmt import local_date

    assert local_date("2026-10-12T02:30:00+00:00") == "2026-10-11"          # 7:30 pm Pacific on the 11th
    assert local_date("2026-10-12T20:00:00+00:00") == "2026-10-12" and local_date("2026-10-12T02:30:00") == "2026-10-11" and local_date(None) == ""
    s = derive(actions=[act(state="executed", recipient="li.wei@example.com", confirmed_at="2026-10-12T02:30:00+00:00")])
    from app.domain.common import AS_OF
    from app.domain.fmt import md
    assert f"on {md(AS_OF.isoformat())}" in s.next_act and s.action.id == "A-1"      # a simulated send reads on the data date (LOOKOUT QA #21), not the wall clock


def test_a_rejection_reads_once_with_the_local_date_and_one_period():
    s = derive(runs=[("ok", "x")], actions=[act(state="rejected", decided_at="2026-10-12T02:30:00+00:00", reason="wrong contact.")])
    assert "You rejected the draft on Oct 11: wrong contact. Revise it with the agent." in s.next_act and ".." not in s.next_act and "drop" not in s.next_act
    assert derive(actions=[act(state="proposed")]).label == "Needs your OK"


def test_a_request_moves_only_the_item_it_was_drafted_for(db_path, tmp_path):
    """The Yunzhan request drafted on the fire moves the fire (Needs your OK, then Sent with who it waits on); the same supplier's quote, its own item, stays where it is."""
    import shutil

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.domain.actions import ledger
    from app.domain.attention import service as attention
    from app.domain.common import EntityRef

    copy = tmp_path / "stage.db"
    shutil.copy(db_path, copy)
    a = ledger.propose(copy, type="supplier_request", item_key="disruption:SUP-0001", run_id="r1", target=EntityRef(type="supplier", id="SUP-0001"),
                       recipient="li.wei@yunzhan-motor.example", subject="Revised dates", body="Please confirm.")
    with Session(create_engine(f"sqlite:///{copy}", future=True)) as s:
        by = {i.key: i for i in stage.attach(s, copy, attention.all_items(s))}
        assert by["disruption:SUP-0001"].stage.label == "Needs your OK" and by["disruption:SUP-0001"].stage.action.id == a.action_id
        quote = by["deadline:SUP-0001:2026-10-13"]      # the same supplier's quote is another item: the request may not cover it, so it keeps its own stage (B4)
        assert quote.stage.key == "found" and quote.stage.action is None
        assert by["tariff:all"].stage.key == "found"                                  # an item of another supplier is not covered
        ledger.approve(copy, a.action_id, a.payload_hash, "Dana Reyes")
        by = {i.key: i for i in stage.attach(s, copy, attention.all_items(s))}
        assert by["disruption:SUP-0001"].next_action.startswith("Waiting on Li Wei; chase Oct 10")
        assert by["deadline:SUP-0001:2026-10-13"].stage.key == "found"


def test_the_line_names_the_supplier_of_the_request_that_was_sent_not_the_items_first_supplier():
    from app.domain.values import EntityRef
    a = act(state="executed", recipient="k@other.example", confirmed_at="2026-10-12T09:00:00+00:00", target=EntityRef(type="supplier", id="SUP-2"))
    s = derive(actions=[a], names={"SUP-2": "Other GmbH"})
    assert "Other GmbH" in s.next_act and "Waiting for Other GmbH" in s.next_act
    assert derive(actions=[a], names={"SUP-2": "Other GmbH"}, answered={"SUP-1": "2026-10-20"}).key == "sent"      # the item's first supplier answering does not end this wait
    assert derive(actions=[a], names={"SUP-2": "Other GmbH"}, answered={"SUP-2": "2026-10-20"}).key == "answered"


def test_several_requests_in_different_states_are_counted_and_named():
    from app.domain.values import EntityRef
    def r(i, state, sid):
        return act(action_id=f"A-{i}", state=state, target=EntityRef(type="supplier", id=sid), confirmed_at="2026-10-12T09:00:00+00:00" if state == "executed" else None)
    s = derive(actions=[r(1, "executed", "S1"), r(2, "proposed", "S2"), r(3, "proposed", "S3")], names={"S1": "Alpha", "S2": "Beta", "S3": "Gamma"})
    assert s.key == "sent" and s.next_act.startswith("1 of 3 sent (Alpha); 2 wait for your OK (Beta, Gamma).")


def test_a_staged_note_waits_for_the_owner_and_once_signed_the_case_reads_recorded_not_sent():
    """BUILD-3 QA-2 #2: a P7 note signed by its owner moves the case to Recorded (nothing is sent); waiting, it needs the owner's OK."""
    note = dict(type="note", subject="Note to Receiving", change={"kind": "note", "option_kind": "ask_receiving"})
    waiting = derive(runs=[("ok", "x")], actions=[act(**note)])
    assert waiting.key == "drafted" and waiting.waiting_on == "you"
    done = derive(runs=[("ok", "x")], actions=[act(state="executed", decided_at="2026-10-14T03:00:00", **note)])
    assert (done.key, done.label, done.waiting_on) == ("approved", "Recorded", None) and "Nothing is sent" in done.next_act
    plain = derive(runs=[("ok", "x")], actions=[act(type="note", state="executed", change=None)])      # a run's own logged note still does not move the case
    assert plain.key == "decision_ready"


def test_a_recorded_note_does_not_close_a_case_while_its_email_still_waits():
    """LOOKOUT P2: the planning note was signed but the supplier email is still a draft: the case waits on the email, never 'nothing is waiting on you'."""
    note = act(action_id="A-2", type="note", state="executed", decided_at="2026-10-14T03:00:00", subject="Note to planning", change={"kind": "note"})
    s = derive(runs=[("ok", "x")], actions=[note, act(action_id="A-1")])
    assert s.key == "drafted" and s.waiting_on == "you" and "Nothing is" not in s.next_act
