"""The context a buyer would otherwise gather: built by code, handed to the agent before it starts.

For one item: where the work stands and the next act (the stage, derived from the runs and the ledger), the other items on the Action
list that touch the same supplier, part or order line and why, and for a supplier's disruption the ways through it, laid out from the
records with what each needs, its earliest date, its cost where one can be computed and the unknown that decides it. Nothing is chosen
for the buyer. The figures in it are registered as evidence with ids, so the agent cites them and the verifier checks them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.common import Unknown
from .schemas import Number
from .toolkit import money_number, money_words, plain_number

LINK_WHY = (("po_line", "the same order line"), ("part", "the same part"), ("supplier", "the same supplier"), ("message", "the same message"), ("build", "the same build"))
MAX_LINKED = 6


@dataclass
class Packet:
    text: str = ""
    numbers: list[Number] = field(default_factory=list)
    unknowns: list[Unknown] = field(default_factory=list)
    finding_facts: dict[str, str] = field(default_factory=dict)  # key -> code's fact: what the run may pick and say the meaning of
    option_kinds: list[str] = field(default_factory=list)  # the kinds of the ways through laid out for the item: the only kinds `recommended` may name


def linked_items(item, services) -> list[tuple[object, str]]:
    """(other item, why) for the items on the list that share a reference with this one, strongest link first, soonest date first."""
    mine = {(r.type, r.id) for r in getattr(item, "refs", [])}
    found = []
    for other in services.attention.list_items():
        if other.key == item.key:
            continue
        shared = [(rank, kind, r.label or r.id) for rank, (kind, _) in enumerate(LINK_WHY) for r in other.refs if r.type == kind and (r.type, r.id) in mine]
        builds = sorted(_builds(item) & _builds(other))   # the same robot short in the same month: ranked last, after any shared record
        if builds:
            shared.append((len(LINK_WHY) - 1, "build", ", ".join(f"{label} {_month(m)}" for label, m in builds[:2])))
        if not shared:
            continue
        rank, kind, label = min(shared)
        found.append((rank, other.act_by or "9999", other, f"{dict(LINK_WHY)[kind]}: {label}"))
    return [(o, why) for _, _, o, why in sorted(found, key=lambda x: (x[0], x[1], x[2].key))[:MAX_LINKED]]


def _builds(item) -> set[tuple[str, str]]:
    """(robot, month) pairs the item's short parts stop, from its own robots_short: an exact build, not every robot that uses a part."""
    return {(r.product.label or r.product.id, r.month) for r in getattr(item, "robots_short", None) or []}


def _month(ym: str) -> str:
    from ..domain.fmt import month  # noqa: PLC0415

    return month(ym)


def _option_numbers(key: str, o) -> tuple[list[Number], dict[str, str]]:
    """The figures of one option as evidence numbers, and the id of each so the text can cite it."""
    nums, ids = [], {}
    for name, label, money in (("cost_delta", "cost versus today", o.cost_delta), ("duty_effect", "duty avoided if the goods ship before the duty starts", o.duty_effect)):
        if money is not None:
            nid = f"option:{key}:{o.kind}:{name}"
            n = money_number(nid, f"{o.label}: {label}", money)
            if n.unit == "USD" and n.value:
                n.say = money_words(n.value)
            nums.append(n)
            ids[name] = f"{n.say} [{nid}]" if n.say else nid      # the figure with its id, so a reason can cite the value, not only the id
    if o.moq:
        nid = f"option:{key}:{o.kind}:moq"
        nums.append(plain_number(nid, f"{o.label}: minimum order", o.moq, "EA"))
        ids["moq"] = nid
    return nums, ids


def _date(d) -> str:
    return d.date if hasattr(d, "date") else str(d)


def requests_with(contact_email: str | None, db_path) -> list:
    """Every request to one supplier contact that is waiting, approved or sent (a rejected one is not a thread), newest first."""
    from ..domain.actions import ledger  # noqa: PLC0415

    if not contact_email or db_path is None:
        return []
    return [a for a in ledger.list_actions(db_path) if a.type == "supplier_request" and a.recipient == contact_email and a.state in ("proposed", "approved", "executed")]


def thread_state(item, services, db_path) -> str:
    """For a triage or a reply on a supplier's message: what has already been asked of this contact, so the run does not ask again (FEEDBACK 3.2: a fifth request to the contact
    went out 25 minutes after one with the same subject was sent)."""
    sup = next((r for r in getattr(item, "refs", []) if r.type == "supplier"), None)
    contact = services.suppliers.contact_for(sup.id) if sup is not None else None
    held = requests_with(getattr(contact, "email", None), db_path)
    if not held:
        return ""
    state = {"proposed": "waiting for approval", "approved": "approved", "executed": "sent"}
    return (f"Already with {contact.name} (this supplier's contact): " + "; ".join(f"{a.action_id} ({state[a.state]}) \"{a.subject}\"" for a in held)
            + ". Ask for what is new in this message only; do not ask again for what these already ask, and say they cover it.")


def build(item, services, db_path=None) -> Packet:
    """The packet for a real Action list item; an item made on the fly (a message, a part comparison) has none, except what has already been asked of a supplier's contact."""
    if not hasattr(item, "numbers"):
        return Packet(text=thread_state(item, services, db_path)) if getattr(item, "group", "") in ("triage", "reply") else Packet()
    lines: list[str] = []
    packet = Packet()
    stage = services.attention.stage_of(item) if hasattr(services.attention, "stage_of") else None
    if stage is not None:
        lines.append(f"Where this stands: {stage.label} (step {stage.step} of {stage.of})" + (f", waiting on {stage.waiting_on}" if stage.waiting_on else "") + f". Next: {stage.next_act}")
    others = linked_items(item, services)
    if others:
        lines.append("Also on the Action list, linked to this item (each at-stake figure is the other case's own, cite it by its id to connect the cases):")
        for o, why in others:
            stake = ""
            usd = getattr(getattr(o, "at_stake", None), "usd", None)
            if usd is not None:
                n = money_number(f"linked:{o.key}:at_stake", f"At stake on the linked case: {o.title}", o.at_stake)
                if n.unit == "USD" and n.value:
                    n.say = money_words(n.value)
                packet.numbers.append(n)
                stake = f", at stake {n.say or n.value} [{n.id}]"
            lines.append(f"- {o.title} (owner {o.owner}" + (f", act by {o.act_by}" if o.act_by else "") + f"{stake}), {why}")
    found = services.attention.findings(item.key) if hasattr(services.attention, "findings") else []
    if found:
        lines.append("What the records show (code's facts; pick the 3-4 a buyer most needs, by key):")
        lines += [f"- [{f.key}] {f.fact}." for f in found]
        packet.finding_facts = {f.key: f.fact for f in found}
    options = (services.attention.options(item.key) if hasattr(services.attention, "options") else None) or []
    table = services.attention.option_kinds(item.key) if hasattr(services.attention, "option_kinds") else []
    if table:  # the case's options and their words come from the code table; the records add needs, dates and cost to the kinds they share
        built = {o.kind: o for o in options}
        rows = [(built[t.kind].model_copy(update={"label": t.label}), t) if t.kind in built else (None, t) for t in table]
    else:
        rows = [(o, None) for o in options]
    if rows:
        lines.append("The ways through, laid out from the records (the buyer chooses; recommend one by its kind):")
        packet.option_kinds = [t.kind if t else o.kind for o, t in rows]
        for i, (o, t) in enumerate(rows, 1):
            if o is None:  # a kind the records hold no figures for: where it leads is the code table's
                goes = {"request": f"an email to {t.to}", "note": f"a note to {t.to}" + (", to enter in the ERP" if t.erp else ""), "record": "the buyer's decision, recorded with a reason"}[t.leads_to]
                linked = f" From the quotes on file: {t.changes}." if getattr(t, "refs", None) else ""      # an option code linked to records (an alternate origin): its figures, from compare_offers
                lines.append(f"{i}. {t.label} (kind {t.kind}): {goes}.{linked}{_also(t)}")
                continue
            nums, ids = _option_numbers(item.key, o)
            packet.numbers += nums
            needs = "; ".join(f"{n.what} ({n.owner})" for n in o.needs) or "nothing more than the supplier's word"
            when = f"{_date(o.earliest)} ({o.earliest_basis})" if o.earliest else (f"not before {_date(o.not_before)} ({o.earliest_basis})" if o.not_before else f"no date the data supports ({o.earliest_basis or 'none given'})")
            cost = f"{ids['cost_delta']} ({o.cost_basis or 'cost versus today'})" if "cost_delta" in ids else "not computable from the records" + (f": {o.cost_unknowns[0].what}" if o.cost_unknowns else "")
            duty = f" Duty avoided if it ships before the duty starts: {ids['duty_effect']}." if "duty_effect" in ids else ""
            lines.append(f"{i}. {o.label} (kind {o.kind}). Needs: {needs}. Earliest: {when}. Cost versus today: {cost}.{duty} Decided by: {o.decided_by.what} (owner {o.decided_by.owner}).{_also(t)}")
            # The decider stays on the option (the screen shows it there); it is not one more open question on the answer.
    packet.text = "\n".join(lines)
    return packet


def _also(t) -> str:
    """Code's also-start on a way through (BUYER D2, D4): started beside whichever one the buyer chooses, with the records' reason; the next step names it."""
    return f" Start it beside the chosen one: {t.also_why}." if t is not None and getattr(t, "also_start", False) else ""
