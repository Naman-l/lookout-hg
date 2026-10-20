"""Work this item: the one workflow for every item type. Code loads the item, picks the delegation plan,
runs Lookout, and closes the run. The same base handles the fire, the tariff, a deadline and an unknown:
the constitution carries one short playbook per truth, and the plan decides who may be asked."""

from __future__ import annotations

import re

from ... import watcher
from types import SimpleNamespace

from ...domain.common import EntityRef
from .. import services as default_services
from ..runner import MAX_BUDGET, RunResult, finish, run_agent, run_without_model
from ..runs.events import Recorder
from ..schemas import RecommendationDraft, draft_schema
from .. import id_shapes
from ..context_packet import Packet, build as build_packet
from ..toolkit import plural
from ..verifier import verify
from .judging import Judging

ROLL_UPS = {"tariff:all", "unknown:hts"}  # unknown:origin is not one: each part's supplier gets a request for its certificate of origin (suppliers_owed)
CHASE_LARGEST = 5  # the chase writes to the suppliers of the largest past-due lines, plus each owner's oldest
SUPPLY_UNKNOWNS = {"unknown:stale-orders", "unknown:undated"}  # roll-ups of order lines: who chases which supplier is the planner's and the clerk's


# Who works each kind of item. Tariff and unknown-origin or unknown-HTS items go to the Tariff analyst; an order line with no promised date or one that may not be open goes to the Supply planner; the fire and the
# deadline to the Supply planner; a trust item delegates to no one. The clerk always drafts last.
def plan_for(kind: str, key: str = "") -> list:
    if kind in ("triage", "reply"):  # a message: the Inbox analyst reads the thread and judges; the clerk drafts or proposes only if warranted
        return ["inbox_analyst", "buyers_clerk"]
    if kind == "compare":  # Compare quotes on a part: the Sourcing analyst reads the offers and reports; nothing is drafted
        return ["sourcing_analyst"]
    if kind == "trust":
        return []  # the sender is not trusted: explain the flags, delegate nothing, draft nothing
    if key in ROLL_UPS:  # a portfolio view has no single supplier to write to: the analyst reads and reports; actions live on part items
        return ["tariff_analyst"]
    if kind == "unknown" and (key in SUPPLY_UNKNOWNS or "/" in key.split(":", 1)[1]):  # an order with no promised date, or one that may not be open: a supply question, not a duty one
        return ["supply_planner", "buyers_clerk"]
    if kind == "tariff" and key.split(":", 1)[1] not in ("all", ""):  # a part: the duty, and beside it the offers that change where it is made (an alternative origin is a claim to confirm)
        return [["tariff_analyst", "sourcing_analyst"], "buyers_clerk"]
    if kind == "tariff" or kind == "unknown":  # a part with no origin or HTS
        return ["tariff_analyst", "buyers_clerk"]
    if key.startswith("risk:") or key == "deadline:quotes":  # a supplier at risk, or quotes about to lapse: its record, the parts only it supplies and its quote terms are sourcing's
        return ["sourcing_analyst", "buyers_clerk"]
    # The fire stays planner then clerk: adding the Sourcing analyst (even in parallel with the planner) took it past the 30 s
    # target. Alternatives are one question away: Compare quotes on the part, or Ask.
    return ["supply_planner", "buyers_clerk"]


# What each kind of item turns on: tools that must have run before the verifier will pass the run.
REQUIRED_TOOLS = {
    "disruption": ("disrupted_supply", "shortage", "where_used"),
    "risk": ("supplier_delivery", "compare_offers"),  # a supplier at risk (group disruption, but no notice): its record and the quote terms for what only it supplies
    "compare": ("compare_offers",),
    "triage": ("read_message",),
    "reply": ("read_message",),
    # tariff, deadline, unknown and trust items: the system reads the item itself before the model runs (see _preload), and a
    # part-level tariff item must have its own exposure examined (required_calls)
}


def caps_for(kind: str, key: str, item=None) -> dict:
    """Bounded fan-out: how many parts a run may examine. A roll-up item (all parts) is read from its own numbers and
    the three parts that carry most; a part-level item examines its own part."""
    if kind in ("tariff", "unknown"):
        scope = len([r for r in getattr(item, "refs", []) or [] if r.type in ("supplier", "part")])  # an item that spans five suppliers needs five reads: a refusal of an in-scope read never happens
        return {"exposure_for_part": 3, "exposure_for_parts": 2, "open_supply": min(max(3, scope + 1), 12), "compare_offers": 1}
    if kind in ("triage", "reply"):  # a quote message: a few parts' duty and offers, bounded
        return {"exposure_for_part": 3, "exposure_for_parts": 2, "compare_offers": 2}
    return {}


def _compare_item(key: str):
    """Compare quotes is run on a part, not on an Action list item, so the item is made here from the part."""
    from types import SimpleNamespace  # noqa: PLC0415

    part = key.split(":", 1)[1]
    return SimpleNamespace(key=key, group="compare", title=f"Compare quotes for {part}", owner="", refs=[EntityRef(type="part", id=part)])


def _message_item(key: str, services):
    """Triage and Reply run on a message, not on an Action list item, so the item is made here from the message."""
    group, mid = key.split(":", 1)
    d = services.inbox.message_detail(mid)
    if d is None:
        raise KeyError(key)
    s = d.summary
    refs = [EntityRef(type="message", id=mid, label=d.subject)] + ([s.supplier] if s.supplier else [])
    title = f"Triage: {d.subject}" if group == "triage" else f"Reply to {s.from_}: {d.subject}"
    return SimpleNamespace(key=key, group=group, title=title, owner="", refs=refs)


def sender_is_vetted(item_key: str, services) -> bool:
    """A triage or a reply on a message from someone who is not a supplier on file (a new sender) may stage nothing at all: code stops it, the model is not asked to behave."""
    if not item_key.startswith(("triage:", "reply:")):
        return True
    t = services.inbox.trust(item_key.split(":", 1)[1])
    return t.api_trust == "on_file" and t.verdict == "ok"  # a message the trust check does not clear (review or blocked) never starts the clerk: code, not the prompt, keeps it from acting on the mail


def prices_something(item_key: str, services) -> bool:
    """A triage or reply on a message that quotes or reprices parts (its kind, from the inbox's own classification): what it means in money turns on duty and the other offers."""
    if not item_key.startswith(("triage:", "reply:")):
        return False
    try:
        detail = services.inbox.message_detail(item_key.split(":", 1)[1])
    except Exception:  # noqa: BLE001  a message the inbox cannot read is judged as before
        return False
    return bool(detail) and (detail.summary.kind or "") in ("quote", "price change")


def kind_of(item) -> str:
    return getattr(item, "group", None) or item.key.split(":", 1)[0]


def is_case(item) -> bool:
    """An Action-list item (it has its own numbers), not a message, a part comparison or a question: its page is the case page, which has no points slot."""
    return hasattr(item, "numbers") and kind_of(item) != "trust"


def review_kind(item) -> str:
    """The Reviewer's sheet for the item: a supplier at risk and an incident are disruptions with their own questions, not a fire's (F108 preview)."""
    if item.key.startswith("risk:"):
        return "risk"
    if item.key.startswith("incident:"):
        return "incident"
    return kind_of(item)


def judged_as(item) -> str:
    """The kind the verifier judges the run by: a supplier at risk is in the disruption group but has no notice to map, so it has its own checks."""
    return "risk" if item.key.startswith("risk:") else kind_of(item)


def headline_ids(kind: str, ctx) -> list[str]:
    """The figures code guarantees on the page for this kind, so the same data always shows the same headline."""
    if kind == "disruption":
        first_short: dict[str, str] = {}
        for i in sorted(i for i in ctx.evidence if i.startswith("shortage:") and i.endswith(":short")):  # month order within a part
            first_short.setdefault(i.split(":")[1], i)
        return sorted(first_short.values()) + sorted(i for i in ctx.evidence if i.endswith(":stuck_qty") or i.endswith(":disrupted_lines") or i.endswith(":open_lines"))
    if kind == "unknown":  # the item's own computed numbers are the headline: the duty if the origin is China, net and gross
        return sorted(i for i in ctx.evidence if i.startswith("item:"))
    if kind == "tariff":  # the item's own headline, and the exposure net and gross the Tariff analyst looked at
        return sorted(i for i in ctx.evidence if (i.startswith("item:") and (i.endswith(":at_stake") or i.endswith(":days_left")))
                      or (i.startswith("tariff:") and i.endswith((":net", ":gross", ":rate", ":conditional", ":uncovered_qty"))))  # the rate, owed, conditional and uncovered quantity are always cited, by code
    if kind == "compare":
        return sorted(i for i in ctx.evidence if i.startswith("quote:") and i.endswith((":price", ":total")))
    if kind in ("triage", "reply"):  # a quote message: every price and landed total the offer tools returned is cited by id, by code
        return sorted(i for i in ctx.evidence if i.startswith("quote:") and i.endswith((":price", ":total")))
    if kind == "trust":  # a message's claim and the usual price beside it: the item's own figures
        return sorted(i for i in ctx.evidence if i.startswith("item:"))
    return sorted(i for i in ctx.evidence if i.startswith("item:") and (i.endswith(":at_stake") or i.endswith(":days_left")))


def required_calls(kind: str, key: str, ctx) -> list[tuple[str, str]]:
    """Calls the run must have made: the fire's shortage for every part the notice disrupts; a part-level tariff
    item's exposure for its own part."""
    if kind == "disruption":
        return [("shortage", i.split(":")[1]) for i in ctx.evidence if i.endswith(":stuck_qty") and id_shapes.pattern(ctx.db_path, "part", whole=True).match(i.split(":")[1])]  # a part number: a lookup by supplier carries the supplier id in that slot  # a part, not the supplier an `open_supply` by supplier names
    if kind == "tariff" and key.split(":", 1)[1] not in ("all", ""):
        return [("exposure_for_part", key.split(":", 1)[1])]
    return []


def optional_for(item) -> set[str]:
    """Steps Lookout may skip: a triage stages something only if the analyst found evidence; a reply to a sender who is not a supplier on file has nobody to write to."""
    if kind_of(item) == "triage":
        return {"buyers_clerk"}
    if kind_of(item) == "reply" and not any(r.type == "supplier" for r in item.refs):
        return {"buyers_clerk"}
    return set()


def describe_plan(plan: list, optional=()) -> str:
    """The plan in words, one step at a time. Members of a step are independent: they are asked in the same turn."""
    steps = []
    for i, g in enumerate(plan, 1):
        members = [g] if isinstance(g, str) else list(g)
        steps.append(f"Step {i}: " + (" AND ".join(members) + " (independent: call the Agent tool for each of them in the SAME message, at once)" if len(members) > 1 else members[0])
                     + (" (optional: only if the previous step's handoff says there is something to stage; otherwise skip it)" if all(m in optional for m in members) else ""))
    return "\n".join(steps)


def waiting(item) -> bool:
    """An item that is a promise to wait for (a supplier said it will send something by a date): before that date there is nothing to chase."""
    from ...domain.common import AS_OF  # noqa: PLC0415

    until = getattr(item, "waits_until", None)
    return bool(until) and AS_OF.isoformat() < str(until)


def suppliers_owed(item, services, db_path=None) -> dict[str, str | None]:
    """Who must be asked, from the item's own lines: {supplier id: the buyer who owns all its lines here, or None when several do}. For a chase the lines are the ones the item lists as
    past due; for undated orders the ones it names. Stale lines (probably not open) are a decision for a person, not a request. Computed in code so the clerk cannot skip one."""
    if item.key == "unknown:origin":
        return _origin_owed(item, db_path)
    if item.key not in ("deadline:chase", "unknown:undated"):
        return {}
    import sqlite3  # noqa: PLC0415

    from .. import id_shapes  # noqa: PLC0415

    line_rx = id_shapes.pattern(db_path, "po_line", whole=True) if db_path else None
    ids = {r.id for r in item.refs if r.type == "po_line"}
    ids |= {n.id.split(":", 1)[1] for n in getattr(item, "numbers", []) if n.id.startswith(("chase:", "past_due:")) and (line_rx is None or line_rx.match(n.id.split(":", 1)[1]))}
    if not ids or not db_path:
        return {}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        marks = ",".join("?" * len(ids))
        rows = con.execute(f"SELECT p.identity_id, b.name, p.id, COALESCE(p.open_usd, 0), p.promised_date FROM po_lines p LEFT JOIN buyers b ON b.id = p.buyer_id WHERE p.id IN ({marks}) AND p.status IN ('OPEN', 'PARTIAL')", sorted(ids)).fetchall()
        if item.key == "deadline:chase":  # 16 lines over 11 suppliers is too many letters for one run: the 5 largest by open value and each owner's oldest line; the answer names the rest
            pick = {r[2] for r in sorted(rows, key=lambda r: (-float(r[3]), r[2]))[:CHASE_LARGEST]}
            oldest: dict = {}
            for r in sorted(rows, key=lambda r: (r[4] or "9999", r[2])):
                oldest.setdefault(r[1], r[2])
            pick |= set(oldest.values())
            rows = [r for r in rows if r[2] in pick]
    finally:
        con.close()
    owners: dict[str, set] = {}
    for sid, buyer, *_ in rows:
        owners.setdefault(sid, set()).add(buyer)
    return {sid: (next(iter(b)) if len(b) == 1 else None) for sid, b in sorted(owners.items())}


def _origin_parts(item, db_path) -> dict[str, list[str]]:
    """For parts with no country of origin: {supplier id: the parts its latest order line is for}. Each letter names only its own supplier's parts (R2b)."""
    import sqlite3  # noqa: PLC0415

    out: dict[str, list[str]] = {}
    if not db_path:
        return out
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        for part in sorted({r.id for r in item.refs if r.type == "part"}):
            row = con.execute("SELECT identity_id FROM po_lines WHERE part_number = ? AND status != 'CANCELLED' ORDER BY order_date DESC, id DESC LIMIT 1", (part,)).fetchone()
            if row and row[0]:
                out.setdefault(row[0], []).append(part)
    return out


def _origin_owed(item, db_path) -> dict[str, str | None]:
    """For parts with no country of origin: the supplier of each part's latest order line, and the buyer who owns all its parts here. One
    letter per supplier covers all its parts; a supplier already written to by another case gets the question added there (one thread per contact)."""
    import sqlite3  # noqa: PLC0415

    parts = sorted({r.id for r in item.refs if r.type == "part"})
    if not parts or not db_path:
        return {}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        owners: dict[str, set] = {}
        for part in parts:
            row = con.execute("SELECT p.identity_id, b.name FROM po_lines p LEFT JOIN buyers b ON b.id = p.buyer_id WHERE p.part_number = ? AND p.status != 'CANCELLED' "
                              "ORDER BY p.order_date DESC, p.id DESC LIMIT 1", (part,)).fetchone()
            if row and row[0]:
                owners.setdefault(row[0], set()).add(row[1])
    finally:
        con.close()
    return {sid: (next(iter(b)) if len(b) == 1 else None) for sid, b in sorted(owners.items())}


def run_plan(item, services) -> list:
    """The plan this run follows: the item's kind decides it, except that nobody drafts for, or logs a note on, a sender the master does not vouch for.
    The Buyer's clerk is not started for a triage or reply on an unvetted sender; the question for the owner goes in the Recommendation."""
    plan = plan_for(kind_of(item), item.key)
    if kind_of(item) in ("triage", "reply") and not sender_is_vetted(item.key, services):
        return [m for m in plan if m != "buyers_clerk"]
    if waiting(item):  # the trigger date is still ahead: the planner states what is known, nobody drafts
        return [m for m in plan if m != "buyers_clerk"]
    if kind_of(item) in ("triage", "reply") and prices_something(item.key, services):  # a quote: landed cost needs the duty on its parts and the other offers beside it
        return ["inbox_analyst", ["tariff_analyst", "sourcing_analyst"], *plan[1:]]
    return plan


def build_prompt(item, asked_by: str | None = None, context: str = "", plan: list | None = None) -> str:
    from ..prompts import data_date_words  # noqa: PLC0415

    refs = ", ".join(f"{r.type} {r.id}" for r in item.refs)
    plan = plan if plan is not None else plan_for(kind_of(item), item.key)
    head = [
        f"Today, in this data, is {data_date_words()}: 'today', 'now', 'this week' and 'yesterday' are counted from this date, never from a clock on the machine. A date written beside the word today is this date.",
        f"Work this item for the buyer: {item.title}.",
        f"Item key: {item.key}. Kind: {kind_of(item)}." + (f" Owner: {item.owner}." if item.owner else "") + (f" Refers to: {refs}." if refs else ""),
    ]
    if asked_by == "Morning run":  # nobody asked: the owner reads the answer when they arrive
        head.append(f"This is the morning run, prepared before anyone arrived. {item.owner} will read the answer: speak to them as 'you' and 'your'." if item.owner and "·" not in item.owner
                    else f"This is the morning run, prepared before anyone arrived. The item belongs to {item.owner or 'another buyer'}, so name that buyer rather than saying 'you'.")
    elif asked_by:
        mine = bool(item.owner) and item.owner.split()[0].lower() == asked_by.split()[0].lower()
        head.append(f"{asked_by} is asking" + (", and this is their own item: speak to them as 'you' and 'your'." if mine else f"; the item belongs to {item.owner or 'another buyer'}, so name that buyer rather than saying 'you'."))
    decided = [d for d in getattr(item, "decisions", [])[:4] if d.state in ("approved", "rejected")]
    if decided:
        head.append("Already decided on this item (newest first): " + "; ".join(f"{d.type.replace('_', ' ')} {d.state} by {d.by}" + (f" ({d.reason})" if d.reason else "") for d in decided) + ". Do not propose again what was rejected.")
    if context:
        head.append("The system has already gathered this for you (use it; its figures carry ids you cite):\n" + context)
    if item.key.startswith("incident:"):  # the clerk must not write a fire's letter for an incident (R2: an incident's letter asked for allocation)
        head.append("This case is an incident, not a fire: the supplier's production is running and it gave new dates. Its new dates are the supplier's, "
                    "not yet confirmed. The clerk asks that the new dates hold and for dates on the past-due lines; no allocation, nothing burned.")
    if is_case(item):
        head.append("This is a case on the Action list: its page shows the facts, lines and dates from the records, so write no `points`. "
                    "The finding is the Situation: what happened and what it hits (robots, money or a count), with no instruction in it; what to do is the next step.")
    if not plan:
        return "\n".join(head + ["The sender is not trusted: read the item with get_item, explain the flags and what to do instead, and write the Recommendation. Delegate nothing and draft nothing."])
    if waiting(item):
        head.append(f"This item is a promise to wait for: the supplier said it will send what is needed by {item.waits_until}, and that date has not come. Draft nothing and do not chase: state the trigger (what arrives by that date, and what the buyer does if it does not) and what is known meanwhile.")
    if kind_of(item) in ("triage", "reply") and any("tariff_analyst" in (p if isinstance(p, list) else [p]) for p in plan):
        head.append("This message quotes or reprices parts. After the analyst has read it, ask the Tariff analyst for the duty on those parts (origin and HTS, net and gross, who imports) and the Sourcing analyst for the offers beside the current supplier. Your answer says what it means in money and dates: the landed cost per site or offer (price, freight and duty, each from a tool; what is unknown stays unknown with its owner), the date it lapses, and an origin caveat where a site's origin is not confirmed. Never say freight, duty or landed cost is unknown without having asked.")
    unvetted = kind_of(item) in ("triage", "reply") and "buyers_clerk" not in plan
    moves = ("If the message gives new dates on open lines and its supplier already has an item on the Action list (list_items), say which item it moves "
             "and what changed on each line (was → now); nothing is drafted from the message then: the buyer works it in that item.")
    hint = ("The sender is not a supplier on file: nothing is drafted and nothing is logged for this message. Say what it is and what it would change, and put the question for the person who owns the part or the supplier in the Recommendation's open questions, with its owner."
            if unvetted else None) or {"triage": "Judge this message: what it is, what it changes, whether its sender is who they claim to be. The clerk proposes a supplier-alias link only if the analyst found real evidence of a rename, and stages nothing otherwise.",
            "reply": "Draft the reply a buyer would send: the analyst reads the whole thread first; the clerk drafts one reply to the contact on file for the supplier (never to the sender's own address), and stages nothing if the sender is not a supplier on file."}.get(kind_of(item))
    return "\n".join(head + ([hint] if hint else []) + ([moves] if kind_of(item) == "triage" and not unvetted else []) + ["Your plan:", describe_plan(plan, optional_for(item)), "Ask the next step the moment the one before has handed off, without reading the handoffs or writing anything in between (the clerk reads what it needs itself). Read the handoffs once, when every step is done, and write the Recommendation."])


def _preload(item, packet: Packet | None = None, owed: dict | None = None):
    """Register the item's own numbers and open questions, as get_item would return them, before the model runs; and the context packet's."""
    def load(ctx):
        if not hasattr(item, "numbers"):  # the synthetic Compare quotes item has none
            return
        from ...domain.attention.tools import read_item  # noqa: PLC0415

        from ..verifier import dates_in, day_counts, days_left_in, numerals  # noqa: PLC0415

        ctx.is_case = is_case(item)
        ctx.required_suppliers = set(owed or {})
        ctx.owner_for = {k: v for k, v in (owed or {}).items() if v}
        numbers, unknowns, _ = read_item(item)
        ctx.register(numbers)
        ctx.item_number_ids = [n.id for n in numbers]
        ctx.unknowns.extend(u for u in unknowns if u not in ctx.unknowns)
        said = " ".join([item.title, getattr(item, "finding", ""), getattr(item, "next_action", ""), str(getattr(item, "act_by", "") or "")])
        ctx.seen_numerals.update(numerals(said))  # the item's own words may be quoted
        ctx.seen_day_counts.update(day_counts(said))
        ctx.seen_days_left.update(days_left_in(said))
        ctx.seen_dates.update(dates_in(said))
        if packet is not None and packet.text:  # the packet is written by code from the records: its numbers carry ids, its words and dates may be quoted
            ctx.register(packet.numbers)
            ctx.option_kinds = list(packet.option_kinds)
            ctx.finding_facts = dict(packet.finding_facts)
            ctx.unknowns.extend(u for u in packet.unknowns if u not in ctx.unknowns)
            ctx.seen_numerals.update(numerals(packet.text))
            ctx.seen_day_counts.update(day_counts(packet.text))
            ctx.seen_dates.update(dates_in(packet.text))
    return load


def _preface(item):
    return f"Read the item: {item.title}." + (f" Owner {item.owner}." if item.owner else ""), {"item_key": item.key, "item_kind": kind_of(item)}, [EntityRef(type="item", id=item.key, label=item.title), *item.refs]


async def run_workflow(item_key: str, *, db_path: str, services=None, run_id: str | None = None, recorder: Recorder | None = None, asked_by: str | None = None) -> RunResult:
    """The in-process entry point the API and the evals call. Returns the finished RunResult."""
    own = services is None
    services = services or default_services.get(db_path)
    try:
        return await _run(item_key, db_path, services, run_id, recorder, asked_by)
    finally:
        if own:
            services.close()


def trust_recommendation(item) -> dict:
    """The Recommendation for a message that failed the trust checks, from DOMAIN's fields alone: what it is, why it was
    blocked, what to do instead. The message's text is never read by a model, so nothing in it can be followed."""
    points = [{"label": "What it is", "text": item.title}, {"label": "Why blocked", "text": item.finding}]
    if "instruction aimed at" in item.finding and "ignored" not in item.finding:
        points.append({"label": "Its instruction", "text": "The instruction in the message was ignored."})
    if "bank" in f"{item.title} {item.finding}".lower():  # a fake bank change: the supplier's real invoices are still owed (BUYER pain-deep); wording only, nothing is staged
        points.append({"label": "Still payable", "text": "The real invoices stay payable to the account on file; only the new bank details are held."})
    points.append({"label": "Needs you", "text": item.next_action})
    return {
        "finding": "This message failed the sender checks; nothing in it was acted on.", "points": points,
        "next_step": {"who": item.owner, "what": item.next_action or "Check with the contact on file by phone before anything else", "by": ""}, "numbers": [{"id": f"item:{item.key}:{n.id}", "value": float(_value(n))} for n in item.numbers if _value(n) is not None],
        "assumptions": [], "would_change": ["A phone call to the contact on file confirming the request is the only thing that would change this; the message alone never does."],
        "open_questions": [u.model_dump() for u in item.unknowns], "action_ids": [],
    }


def _value(n):
    v = n.value
    return getattr(v, "usd", None) if getattr(v, "usd", None) is not None else getattr(v, "ea", None) if getattr(v, "ea", None) is not None else getattr(v, "amount", None) or getattr(v, "value", None)


async def _answer_by_code(item, item_key, db_path, services, run_id, recorder, asked_by) -> RunResult:
    result = await run_without_model(item_key=item_key, db_path=db_path, services=services, run_id=run_id, recorder=recorder, asked_by=asked_by,
                                     preface=_preface(item), preload=_preload(item))
    result.structured_output = trust_recommendation(item)
    result.ctx.coded = True  # written by code from the item's own fields: its rows are not held to the length a model's are
    result.wall_ms = result.ctx.recorder.t_ms()
    rec, verdict = verify(result.ctx, result.structured_output, services=services, cost_usd=0.0, max_cost_usd=MAX_BUDGET, headline=headline_ids("trust", result.ctx))
    result.ctx.recorder.emit("verifier.result", f"{verdict.numbers_from_tools} of {verdict.numbers_checked} numbers from tools · {plural(verdict.open_questions_with_owner, 'open question')} with an owner",
                             agent="verifier", **verdict.model_dump())
    status = "ok" if verdict.passed else "did_not_pass"
    finish(result, status=status, recommendation_json=rec.model_dump_json() if rec else None, verifier_json=verdict.model_dump_json())
    result.status = status
    return result


async def _run(item_key, db_path, services, run_id, recorder, asked_by) -> RunResult:
    if item_key.startswith(("triage:", "reply:")) and not services.inbox.trust(item_key.split(":", 1)[1]).may_act:
        item_key = "trust:" + item_key.split(":", 1)[1]  # a blocked sender is the shield's, answered by code: nothing is read by a model or drafted
    if item_key.startswith("compare:"):
        item = _compare_item(item_key)
    elif item_key.startswith(("triage:", "reply:")):
        item = _message_item(item_key, services)
    else:
        item = services.attention.get_item(item_key)
    watcher.emit("agent", "workflow.start", f"Work {item_key}", item_key=item_key)
    if not plan_for(kind_of(item), item.key):  # a trust item: the answer is fixed by code, so code writes it
        return await _answer_by_code(item, item_key, db_path, services, run_id, recorder, asked_by)
    judging = Judging(
        kind=review_kind(item), title=item.title, services=services, max_cost=MAX_BUDGET,
        headline_fn=lambda ctx: headline_ids(judged_as(item), ctx), required_tools=REQUIRED_TOOLS.get(judged_as(item), ()),
        required_calls_fn=lambda ctx: required_calls(judged_as(item), item.key, ctx),
    )
    plan = run_plan(item, services)
    try:
        packet = build_packet(item, services, db_path)
    except Exception as e:  # noqa: BLE001  the run goes on without the packet; the failure is on the Watcher, not swallowed
        watcher.emit("agent", "context.failed", f"{type(e).__name__}: {e}", item_key=item_key)
        packet = Packet()
    stage_ok = kind_of(item) != "trust" and sender_is_vetted(item_key, services) and not waiting(item)
    owed = suppliers_owed(item, services, db_path) if "buyers_clerk" in plan and stage_ok else {}
    if owed:  # the list of who must be asked is made by code from the item's lines; the clerk writes each request
        names = []
        for sid, buyer in owed.items():
            c = services.suppliers.contact_for(sid)
            parts = _origin_parts(item, db_path).get(sid) if item.key == "unknown:origin" else None
            names.append((f"{sid} ({c.name})" + (f", for {buyer}'s lines" if buyer else "") if c else sid) + (f", about {', '.join(parts)} only" if parts else ""))
        packet.text = (packet.text + "\n" if packet.text else "") + "Requests required, one per supplier contact, each written for that supplier's own lines: " + "; ".join(names) + ". The clerk may not hand off until each has a request."
    result = await run_agent(
        item_key=item_key, db_path=db_path, plan=plan, prompt=build_prompt(item, asked_by, packet.text, plan), services=services,
        stage_allowed=stage_ok, run_id=run_id, recorder=recorder, asked_by=asked_by,
        output_schema=draft_schema(), preface=_preface(item), preload=_preload(item, packet, owed), tool_caps=caps_for(kind_of(item), item.key, item),
        judge=judging, optional=optional_for(item), turns={"buyers_clerk": len(owed) + 4} if owed else None,
    )
    status, rec_json, ver_json = judging.finish(result) if result.status == "ok" else (result.status, None, None)
    finish(result, status=status, recommendation_json=rec_json, verifier_json=ver_json)
    result.status = status
    await judging.grade_after(result)
    return result
