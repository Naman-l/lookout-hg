"""Today: every detector's cases, folded and ranked, and each member's own slice.

Folding (one row per cause): a vendor's revised schedule folds under its late streak; a quote's lapse folds under the long-lead decision of the same
project; the other months of a fund-sheet mismatch fold under the next month's. A folded case stays resolvable by its own key.
Ranking, code only: a work front that stops inside the horizon first, then held mail, then ₹ at stake, then days left. (Signed or sent cases sink on
the screen, from their stage.)
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain import lookups
from app.domain.attention import detectors
from app.domain.attention.schema import ActionItem, ActionItemDetail, DatedRow
from app.domain.cache import memo
from app.domain.common import AS_OF

HORIZON_DAYS = 60


def _amount(i) -> float:
    v = i.at_stake
    return float(v.amount) if v is not None and hasattr(v, "amount") else 0.0


def _stops_soon(i) -> bool:
    return any(s.stops_on and (detectors.left(s.stops_on) or 0) <= HORIZON_DAYS for s in i.site_impact)


def rank_key(i) -> tuple:
    return (0 if _stops_soon(i) else 1, 0 if i.tab == "trust" else 1, -_amount(i) if i.at_stake_label not in ("covers", "where a rate exists", "open, outside the library") else 0,
            i.days_left if i.days_left is not None else 9999, i.key)


@memo
def _found(session: Session) -> dict[str, detectors.Found]:
    """Every case by key, folds applied (children listed on the parent's `dated`)."""
    found: dict[str, detectors.Found] = {}
    for fn in detectors.DETECTORS:
        for f in fn(session):
            found[f.item.key] = f
    for k, f in found.items():
        if f.item.kind == "schedule-slip" and f"late-streak:{k.split(':', 1)[1]}" in found:
            f.fold_into = f"late-streak:{k.split(':', 1)[1]}"
        if f.item.kind == "quote-lapse":
            pid = f.item.projects[0].id if f.item.projects else None
            if pid and f"pv-longlead:{pid}" in found:
                f.fold_into = f"pv-longlead:{pid}"
    for k, f in found.items():
        if f.fold_into and f.fold_into in found:
            parent = found[f.fold_into].item
            parent.dated.append(DatedRow(key=k, title=f.item.title, act_by=f.item.act_by, days_left=f.item.days_left, at_stake=f.item.at_stake))
            parent.dated.sort(key=lambda d: d.act_by or "9999")
            parent.refs += [r for r in f.item.refs if r not in parent.refs]
            parent.messages += [m for m in f.item.messages if m not in parent.messages]
    return found


def _summary(d: ActionItemDetail) -> ActionItem:
    return ActionItem(**{k: getattr(d, k) for k in ActionItem.model_fields})


@memo
def _team(session: Session) -> list[ActionItem]:
    return sorted((_summary(f.item) for f in _found(session).values() if not (f.fold_into and f.fold_into in _found(session))), key=rank_key)


def _member_id(session: Session, owner: str | None) -> str | None:
    b = lookups.member_of(session, owner)
    return b.id if b else None


def _slice(session: Session, f: detectors.Found, member: str) -> ActionItemDetail:
    """The member's own share of a team case: their figure and projects, the team total kept beside it."""
    s = f.shares.get(member)
    if not s:
        return f.item
    upd = {k: v for k, v in s.items() if k in ActionItemDetail.model_fields}
    if "at_stake" in s and f.item.at_stake is not None and hasattr(f.item.at_stake, "amount"):
        upd["team_total"] = f.item.at_stake
    return f.item.model_copy(update=upd)


def what_needs_attention(session: Session, owner: str | None = None) -> list[ActionItem]:
    """The team's list (no owner), or one member's: the cases they own, each as their share. The Head of SCM and the GM own the decisions above a
    vertical (long-lead orders, countersigns); everyone else's Yours is their purchasing group's."""
    if not owner:
        return _team(session)
    member = _member_id(session, owner)
    if member is None:
        return []
    found = _found(session)
    mine = [_summary(_slice(session, f, member)) for f in found.values() if member in f.item.owner_ids and not (f.fold_into and f.fold_into in found)]
    return sorted(mine, key=rank_key)


def item_detail(session: Session, key: str, owner: str | None = None) -> ActionItemDetail | None:
    f = _found(session).get(key)
    if f is None:
        return None
    member = _member_id(session, owner) if owner else None
    return _slice(session, f, member) if member else f.item


def item_context(session: Session, key: str):
    """(the case, its detector record) or None."""
    f = _found(session).get(key)
    return (f.item, f) if f else None


def all_keys(session: Session) -> list[str]:
    return list(_found(session))


def as_of() -> str:
    return AS_OF.isoformat()
