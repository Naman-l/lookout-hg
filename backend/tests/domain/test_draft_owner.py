"""A draft on a shared item is signed by the one buyer it was written for, not by every owner of the item."""

from types import SimpleNamespace

from app.domain.actions import approvers


def _draft(**kw):
    return SimpleNamespace(action_id="A-1", item_key="deadline:chase", run_id=None, target=None, **kw)


def test_a_draft_with_an_owner_is_owned_by_that_buyer_alone(db_path):
    shared = approvers.owners_of(db_path, "deadline:chase")
    assert shared and len(shared) >= 4      # the chase row is shared by four buyers
    assert approvers.owners_of_action(db_path, _draft(owner="Priya Nair")) == {"Priya Nair"}      # one draft, one signer
    assert approvers.owners_of_action(db_path, _draft(owner=None)) == shared      # an old draft with no owner falls back to the item's owners
    assert approvers.owners_of_action(db_path, _draft(owner=None, change={"owner": "Marcus Chen"})) == {"Marcus Chen"}      # the owner a staged request carries in its change
    counted = sum(1 for who in shared for _ in [0] if who in approvers.owners_of_action(db_path, _draft(owner="Priya Nair")))
    assert counted == 1      # of the four owners, only one sees it as to sign
