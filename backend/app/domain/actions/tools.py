"""Agent tools that stage a proposal. Staging only writes a `proposed` row; approval, rejection and execution
exist only behind the API routes a person calls."""

from __future__ import annotations

import re
from decimal import Decimal

from claude_agent_sdk import tool

from ...organism import company, id_shapes
from ...organism.context import RunContext
from ...organism.toolkit import STAGE, refuse, reply
from ..common import EntityRef
from . import approvers, ledger

# Money movement and bank details are out of reach of every draft (T4: forbidden).
_FORBIDDEN = re.compile(
    r"\b(iban|swift|bic\b|sort code|routing (number|no)|bank (account|details?|info(rmation)?|transfer|name|code)|account (number|no\b|details?)|wire (transfer|the|us|to)|"
    r"remit(tance)? (details?|address|instructions?)|(new|updated|changed|different) (payment|banking|bank|remittance) (details?|instructions?|account|information)|"
    r"pay(ment)? (to|into)|(send|transfer|deposit) (the )?(money|funds|payment)|beneficiary)\b", re.I)


_CLOSING = re.compile(r"^\s*(?:(?:best|kind|warm|many)\s+)?(?:regards|thanks|thank you|sincerely|cheers|with thanks)\b", re.I)



def _case_key(ctx) -> str:
    """The case an action belongs to: the run's own item, or, for a question asked about a case (Ask with an Action-list item on screen), that case,
    so what is staged shows on the case's Approval card and its owner signs it. Whether a waiting draft is this run's own (and so may be rewritten)
    is still judged by the run's key: an Ask on a case adds a paragraph to the case's waiting draft, it never rewrites it (Rev 4.1)."""
    return getattr(ctx, "action_item_key", None) or ctx.item_key

def insert_before_signoff(body: str, text: str) -> str:
    """Add a paragraph to an email body above its closing ('Regards, <name>'), so the amended text still ends with the signature."""
    parts = body.rstrip().split("\n\n")
    for i in range(len(parts) - 1, -1, -1):
        if _CLOSING.match(parts[i]):
            return "\n\n".join([*parts[:i], text, *parts[i:]])
    return f"{body.rstrip()}\n\n{text}"


_SUPPLIER_CAN_ANSWER = re.compile(r"\b(?:promise[ds]?(?: dates?)?|delivery dates?|ship(?:ping)?(?: dates?)?|revised dates?|lead times?|certificates? of origin|origin (?:papers|documents?|documentation)|expedit\w*|quote validity|extend the quote)\b", re.I)


def _supplier_ref(db_path, given: str) -> str:
    """The supplier id for what the model named: the id itself, or a supplier on file whose name is or starts with it (one match only)."""
    import sqlite3  # noqa: PLC0415

    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            if con.execute("SELECT 1 FROM supplier_identities WHERE id = ?", (given,)).fetchone():
                return given
            rows = con.execute("SELECT id FROM supplier_identities WHERE lower(name) = lower(?) OR lower(name) LIKE lower(?) || '%'", (given.strip(), given.strip())).fetchall()
            return rows[0][0] if len(rows) == 1 else given
        finally:
            con.close()
    except sqlite3.Error:      # no records to look in: the id stands as given
        return given


def _buyers_of_lines(db_path, lines: list[str]) -> set[str]:
    """The buyers (full names) of these PO lines, from the orders themselves."""
    import sqlite3  # noqa: PLC0415

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        marks = ",".join("?" * len(lines))
        return {r[0] for r in con.execute(f"SELECT b.name FROM po_lines p JOIN buyers b ON b.id = p.buyer_id WHERE p.id IN ({marks})", list(lines)) if r[0]}
    except sqlite3.Error:
        return set()
    finally:
        con.close()


def with_signature(body: str, name: str, company_full: str) -> str:
    """The email ends with one signature: the person who signs it. A closing the model wrote (any name) is replaced; a body with none gets one."""
    parts = body.rstrip().split("\n\n")
    for i in range(len(parts) - 1, -1, -1):
        if _CLOSING.match(parts[i]):
            word = parts[i].split("\n", 1)[0].strip().rstrip(",") or "Regards"
            return "\n\n".join([*parts[:i], f"{word},\n{name}\n{company_full}"])
    return f"{body.rstrip()}\n\nRegards,\n{name}\n{company_full}"


def _styled(ctx, subject: str, body: str, item_key: str | None = None, recipient: str = "") -> str:
    """The letter in house style before its hash: quantities with separators, part numbers with names, the reservation of rights on a force majeure."""
    from .letters import house_style  # noqa: PLC0415

    from ...organism.verifier import dates_in  # noqa: PLC0415

    styled = house_style(body, db_path=ctx.db_path, item_key=item_key or _case_key(ctx), subject=subject, company_short=company.names(ctx.db_path)[1], recipient=recipient)
    ctx.seen_dates.update(dates_in(styled) - dates_in(body))  # a date the house style computed (a reply asked for before a quote lapses) is the code's, not the model's
    return styled


def _signed(ctx, a):
    """Apply the signer's signature in code at staging: the owner of the draft as the ledger records it, one name. No single owner leaves the text as written."""
    if a.type != "supplier_request" or a.state != "proposed":
        return a
    try:
        owners = approvers.owners_of_action(ctx.db_path, a)
    except Exception:  # noqa: BLE001  nobody to sign: the draft is left unsigned by anyone in particular
        return a
    full = company.names(ctx.db_path)[0]
    if not owners or len(owners) != 1:  # no single signer: the closing the model wrote stays, and the letter still says who it is from (G4)
        body = a.body or ""
        body = body if full in body else f"{body.rstrip()}\n{full}"
    else:
        body = with_signature(a.body or "", next(iter(owners)), full)
    return a if body == a.body else ledger.update_draft(ctx.db_path, a.action_id, subject=a.subject or "", body=body, edited_by="Lookout", run_id=ctx.run_id)


_BEFORE_NOTICE_FIX = ("say 'past due on 25 September' (the date the records give, as the item's count does): a count before the notice is not a tool figure, "
                      "and in a letter that reserves rights a wrong count is a wrong claim")


_STALE_FIX = "a stale order is a note: log_buyer_question for the owning buyer, asking Receiving whether the PO line arrived; no supplier email"
_INCIDENT_FIX = "an incident: ask that the new dates hold and for dates on the past-due lines; no allocation (nothing is under a force majeure)"


def _parts_not_supplied(ctx, supplier_id: str, text: str) -> list[str]:
    """On the missing-origin case, the parts a letter names that this supplier never had an order line for (R2b: four letters carried each other's parts)."""
    if _case_key(ctx) != "unknown:origin" or not ctx.db_path:
        return []
    import sqlite3  # noqa: PLC0415

    named = set(id_shapes.pattern(ctx.db_path, "part").findall(text))
    if not named:
        return []
    con = sqlite3.connect(str(ctx.db_path), timeout=30)
    try:
        mine = {r[0] for r in con.execute("SELECT DISTINCT part_number FROM po_lines WHERE identity_id = ?", (supplier_id,))}
    finally:
        con.close()
    return sorted(named - mine)


def _before_notice(text: str) -> bool:
    from ...organism.verifier import before_notice_claim  # noqa: PLC0415

    return before_notice_claim(text)


def _bad_text(ctx: RunContext, subject: str, body: str) -> str | None:
    """Why a supplier-facing text may not be staged (or added to a staged one): money words, plumbing words or ids, figures and dates no tool returned. None when it may."""
    from ...organism.verifier import internal_words, stray_in_text  # noqa: PLC0415

    text = f"{subject} {body}"
    if _FORBIDDEN.search(text):
        return "a draft may not mention bank details or payments; leave those to a person"
    if _before_notice(text):
        return _BEFORE_NOTICE_FIX
    if _case_key(ctx) == "unknown:stale-orders":
        return _STALE_FIX
    if _case_key(ctx).startswith("incident:") and re.search(r"\ballocat", text, re.I):
        return _INCIDENT_FIX
    plumbing = internal_words(text)
    if plumbing or id_shapes.pattern(ctx.db_path, "supplier", "legacy_supplier").search(text):
        return ("A supplier reads this email: write it as a buyer would, without internal words or supplier ids" + (f" (remove: {', '.join(plumbing)})" if plumbing else "") + ". Name the supplier and the parts; PO and line numbers are fine.")
    nums, days = stray_in_text(ctx, text)
    if nums or days:
        return ("Your text states " + "; ".join(x for x in (f"numbers no tool returned: {', '.join(nums)}" if nums else "", f"dates no tool returned: {', '.join(days)}" if days else "") if x)
                + ". Use only figures and dates from your tool results (get_handoffs, read_message), or leave them out.")
    return None


def make_tools(ctx: RunContext, svc):
    co = company.names(ctx.db_path)[1]  # the company's short name, from the recipe

    @tool(
        "draft_supplier_request",
        "Stage a request to a supplier for approval. Give the supplier id, a short subject and the body, written "
        "the way a buyer writes: the PO and line numbers, the ask, the date you need it by, no promises and no "
        "awards. The recipient is the contact on file; you cannot choose an address. A person approves before "
        f"anything is sent. Not for a question to one of {co}'s own buyers (use log_buyer_question), and not as a reply to a sender who failed the checks.",
        {"type": "object", "required": ["supplier_id", "subject", "body"], "properties": {
            "supplier_id": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"},
            "lines": {"type": "array", "items": {"type": "string"}, "description": "the PO lines the request asks about, as the orders show them: the buyer of those lines signs it. One buyer per request: lines of two buyers are two requests."}}},
        annotations=STAGE,
    )
    async def draft_supplier_request(args):
        if not ctx.stage_allowed:
            return refuse("nothing may be drafted for this item")
        args = {**args, "supplier_id": _supplier_ref(ctx.db_path, args["supplier_id"])}      # the model may name the supplier ("Siam Motion"): the contact on file is found by its id
        owner = ctx.owner_for.get(args["supplier_id"])
        if args.get("lines"):  # the signer is the buyer of the lines the request asks about: code reads them, the model only names the lines
            buyers = _buyers_of_lines(ctx.db_path, args["lines"])
            if len(buyers) > 1:
                return refuse("Those lines belong to " + " and ".join(sorted(buyers)) + ": one request has one signer. Draft one request for each buyer's lines.")
            owner = next(iter(buyers), owner)
        if _FORBIDDEN.search(args["subject"] + " " + args["body"]):
            return refuse("a draft may not mention bank details or payments; leave those to a person")
        from ...organism.verifier import internal_words, stray_in_text  # noqa: PLC0415

        plumbing = internal_words(f"{args['subject']} {args['body']}")
        if plumbing or re.search(r"\bSUP-\d{4}\b|\bV\d{5}\b", f"{args['subject']} {args['body']}"):
            return refuse("A supplier reads this email: write it as a buyer would, without internal words or supplier ids"
                          + (f" (remove: {', '.join(plumbing)})" if plumbing else "") + ". Name the supplier and the parts; PO and line numbers are fine.")

        if _before_notice(f"{args['subject']} {args['body']}"):
            return refuse(_BEFORE_NOTICE_FIX)
        if _case_key(ctx) == "unknown:stale-orders":   # R2b: the aged-POs run emailed two suppliers, one mid-fire; the agreed rule is notes only
            return refuse(_STALE_FIX)
        if _case_key(ctx).startswith("incident:") and re.search(r"\ballocat", f"{args['subject']} {args['body']}", re.I):
            return refuse(_INCIDENT_FIX)
        stray_parts = _parts_not_supplied(ctx, args["supplier_id"], f"{args['subject']} {args['body']}")
        if stray_parts:
            return refuse(f"{', '.join(stray_parts)} {'is' if len(stray_parts) == 1 else 'are'} not on this supplier's order lines: write to each supplier only about its own parts")
        nums, days = stray_in_text(ctx, f"{args['subject']} {args['body']}")
        if nums or days:
            return refuse("Your draft states " + "; ".join(x for x in (f"numbers no tool returned: {', '.join(nums)}" if nums else "", f"dates no tool returned: {', '.join(days)}" if days else "") if x)
                          + ". Use only figures and dates from your tool results (get_handoffs, read_message), or leave them out, and draft again.")
        contact = svc.contact_for(args["supplier_id"])
        if contact is None:
            return refuse(f"no contact on file for {args['supplier_id']}, so nothing can be drafted")
        ctx.suppliers_asked.add(args["supplier_id"])
        held = ledger.open_thread(ctx.db_path, contact.email)
        if held is not None and held.item_key != ctx.item_key:  # one open thread per contact AND owner: another buyer's waiting request is theirs to sign, so this line's buyer gets a request of their own
            try:
                mine = {owner} if owner else approvers.owners_of(ctx.db_path, _case_key(ctx))
                theirs = approvers.owners_of_action(ctx.db_path, held)
            except Exception:  # noqa: BLE001  owners unknown: the one-thread rule stands
                mine = theirs = None
            if mine and theirs and not (mine & theirs):
                held = None
        if held is not None and held.state == "proposed" and getattr(ctx, "action_item_key", None) and ctx.action_item_key != ctx.item_key:  # an Ask on a case: the buyer's ask is ALWAYS appended to the waiting draft, never a rewrite and never 'covered' (a full rewrite reads as the same ask and its new part was dropped, run-ba8770b8)
            ledger.link_to_run(ctx.db_path, ctx.run_id, held.action_id)
            return reply(ctx, f"A request to {contact.name} is waiting for approval ({held.action_id}): add the buyer's ask to it with amend_draft",
                         {"must_amend": held.action_id, "state": held.state, "instruction": f"Do not draft a second email or rewrite this one. If the waiting request already asks exactly what the buyer wants, say so. Otherwise call amend_draft(action_id='{held.action_id}', paragraph=...) with only what it does not ask yet, written for the supplier. It is added as a numbered paragraph and its owner signs the new text."})
        if held is not None and held.state == "proposed" and held.item_key == ctx.item_key and (held.subject, held.body) != (args["subject"], args["body"]):
            held = ledger.update_draft(ctx.db_path, held.action_id, subject=args["subject"], body=args["body"], edited_by="Lookout", run_id=ctx.run_id)  # the same item, worked again: the waiting draft is amended, not doubled
            held = _signed(ctx, held)
            ledger.link_to_run(ctx.db_path, ctx.run_id, held.action_id)
            if held.action_id not in ctx.action_ids:
                ctx.action_ids.append(held.action_id)
            return reply(ctx, f"The waiting draft to {contact.name} was amended: {held.subject}", {"action_id": held.action_id, "state": held.state, "type": held.type, "recipient": held.recipient, "subject": held.subject, "payload_hash": held.payload_hash, "amended": True})
        if held is not None and held.state == "proposed" and held.item_key == ctx.item_key and len(ledger.asks_of(held)) > 1:  # other items' asks were merged into it: this run does not overwrite them
            ledger.link_to_run(ctx.db_path, ctx.run_id, held.action_id)
            if held.action_id not in ctx.action_ids:
                ctx.action_ids.append(held.action_id)
            return reply(ctx, f"The waiting request to {contact.name} already carries this item's ask and others merged into it ({held.action_id}); it is changed with amend_draft only",
                         {"covered_by": held.action_id, "state": held.state, "recipient": held.recipient, "subject": held.subject})
        if held is not None and ctx.item_key not in ledger.asks_of(held) and not ledger.same_ask(f"{held.subject} {held.body}", f"{args['subject']} {args['body']}"):  # another item's request to the same contact does not carry this item's ask
            if held.state == "proposed":  # waiting: this item's ask is merged into it as a numbered paragraph, by amend_draft
                ledger.link_to_run(ctx.db_path, ctx.run_id, held.action_id)
                return reply(ctx, f"A request to {contact.name} is waiting for approval ({held.action_id}) but it does not carry this item's ask: add it with amend_draft",
                             {"must_amend": held.action_id, "state": held.state, "instruction": f"Do not say this item is covered. Call amend_draft(action_id='{held.action_id}', paragraph=...) with only this item's own ask, written for the supplier. It is added to the waiting request as a numbered paragraph and its owner signs the new text."})
            held = None  # approved or sent without this item's ask: a new short request for just that ask is a different ask, not a duplicate
        if held is not None and not (held.item_key == ctx.item_key and held.state == "proposed"):  # the ask is already in the request waiting or sent to this contact
            sent = held.state != "proposed"
            if not sent and held.action_id not in ctx.action_ids:
                ctx.action_ids.append(held.action_id)
            ledger.link_to_run(ctx.db_path, ctx.run_id, held.action_id)
            return reply(ctx, f"A request to {contact.name} is already {'sent' if sent else 'waiting for approval'} ({held.action_id}): no second one is drafted",
                         {"covered_by": held.action_id, "state": held.state, "recipient": held.recipient, "subject": held.subject, "instruction": f"Do not draft another. In your answer say this item's ask is covered by the request to {contact.name} ({held.subject}), {'already sent' if sent else 'waiting in Approvals'}."})
        try:
            a = ledger.propose(
                ctx.db_path, type="supplier_request", item_key=_case_key(ctx), run_id=ctx.run_id,
                target=EntityRef(type="supplier", id=args["supplier_id"]), recipient=contact.email, subject=args["subject"], body=_styled(ctx, args["subject"], args["body"], recipient=contact.email),
                change={"owner": owner} if owner else None,
            )
        except ledger.LedgerError as e:
            return refuse(e.message)
        if a.run_id == ctx.run_id:
            a = _signed(ctx, a)
        if a.action_id not in ctx.action_ids:
            ctx.action_ids.append(a.action_id)
        data = {"action_id": a.action_id, "state": a.state, "type": a.type, "recipient": a.recipient, "subject": a.subject, "payload_hash": a.payload_hash}
        if a.run_id and a.run_id != ctx.run_id:  # the same draft was already waiting, staged by an earlier run: this run links to it and says so
            from ...organism.runs import store  # noqa: PLC0415

            first = store.read_run(ctx.db_path, a.run_id) or {}
            data["already_waiting"] = "prepared this morning" if first.get("asked_by") == "Morning run" else "staged by an earlier run"
            return reply(ctx, f"Draft to {contact.name} was already waiting ({data['already_waiting']}): {a.subject}", data)
        return reply(ctx, f"Draft to {contact.name} awaiting approval: {a.subject}", data)

    @tool(
        "log_buyer_question",
        f"Log a question for a {co} buyer who owns the answer (a buyer named on the item or its open question). It is "
        f"recorded against the item and shown to that buyer; it is an internal note, not sent outside {co}, so it needs no approval. "
        f"Use it when the open question's owner is a person at {co}, not a supplier.",
        {"owner": str, "question": str},
        annotations=STAGE,
    )
    async def log_buyer_question(args):
        if (ctx.item_key or "").startswith("ask:"):  # in Ask, what Lookout prepares for the buyer is staged for signature, never recorded on its own (LOOKOUT P1 live: a note to planning was logged executed)
            return refuse("In Ask nothing is recorded on its own: a note for a team or a buyer is stage_decision (with `to` for who reads it), staged for the owner's signature; an open question goes in the answer with its owner.")
        from ..ownership import buyer_ids_in

        buyers = buyer_ids_in(ctx.db_path)
        first = args["owner"].split()[0] if args["owner"].split() else ""  # a full name and the first name are the same buyer: one note, not a refusal and a retry
        if first not in buyers:
            return refuse(f"log_buyer_question is for {co}'s buyers: {', '.join(buyers)}. Use draft_supplier_request for a supplier.")
        args = {**args, "owner": first}
        stale = _case_key(ctx) == "unknown:stale-orders"  # an aged order is always a note to its buyer for Receiving (no supplier email), so neither refusal below applies
        if not stale and _SUPPLIER_CAN_ANSWER.search(args["question"]):  # what a supplier holds (a date, a document, a confirmation) is asked of the supplier; a note is only for what no supplier can answer
            return refuse("A supplier can answer that: draft a request to the contact on file with draft_supplier_request (owned by this line's buyer), one for each supplier whose lines need it. log_buyer_question is only for what no supplier can answer: stock on hand, an internal decision.")
        if not stale and any((u.owner or "").split()[:1] == [first] for u in ctx.unknowns):  # the unknown with its owner is the one place for the question; a note would only repeat it in the decision history
            return refuse(f"{first} already owns an open question on this item: it is in the answer with {first} as its owner. Do not log a note that repeats it.")
        if first in ctx.asked_buyers:
            return refuse(f"{first} already has a question from this run: put everything for {first} in that one question")
        ctx.asked_buyers.add(first)
        parts = id_shapes.pattern(ctx.db_path, "part")
        mine = set(parts.findall(args["question"]))
        covering = next((n for n in ledger.notes_for(ctx.db_path, first) if mine & set(parts.findall(n.body or ""))), None)
        if covering is not None:  # the same question about the same parts is one note, whichever item raised it
            ledger.link_to_run(ctx.db_path, ctx.run_id, covering.action_id)
            if covering.action_id not in ctx.action_ids:
                ctx.action_ids.append(covering.action_id)
            return reply(ctx, f"{first} already has this question ({covering.action_id}): no second note", {"covered_by": covering.action_id, "instruction": "Do not log it again; refer to the question already logged."})
        a = ledger.record_app_action(ctx.db_path, type="note", item_key=_case_key(ctx), target=EntityRef(type="item", id=_case_key(ctx)),
                                     body=f"Question for {args['owner']}: {args['question']}", by="Lookout", change={"owner": args["owner"]}, run_id=ctx.run_id)
        if a.action_id not in ctx.action_ids:
            ctx.action_ids.append(a.action_id)
        return reply(ctx, f"Logged a question for {args['owner']} (an internal note, not sent outside {co})", {"action_id": a.action_id, "state": a.state, "type": a.type})

    @tool(
        "propose_supplier_alias",
        "Propose that two supplier ids are one company (a rename, a legacy id), with the evidence. It only proposes: a person approves, and nothing is merged "
        "(the records stay as they are and are linked). Use it only when the message or the master gives real evidence, such as the company saying it was renamed.",
        {"supplier_a": str, "supplier_b": str, "evidence": str},
        annotations=STAGE,
    )
    async def propose_supplier_alias(args):
        if not ctx.stage_allowed:
            return refuse("nothing may be proposed for this item")
        a, b = sorted([args["supplier_a"], args["supplier_b"]])
        if a == b:
            return refuse("an alias needs two different supplier ids")
        act = ledger.propose(
            ctx.db_path, type="supplier_alias", item_key=ctx.item_key, run_id=ctx.run_id, target=EntityRef(type="supplier", id=a), recipient=None,
            subject=f"Link {a} and {b} as one supplier", body=args["evidence"], change={"link": [a, b], "merge": False},
        )
        if act.action_id not in ctx.action_ids:
            ctx.action_ids.append(act.action_id)
        return reply(ctx, f"Proposed linking {a} and {b}, awaiting approval", {"action_id": act.action_id, "state": act.state, "type": act.type, "subject": act.subject, "payload_hash": act.payload_hash})

    @tool(
        "amend_draft",
        "Add one paragraph to a request that is still waiting for approval, so it also asks what this item needs (for example, to extend a quote's validity). Give the action id the "
        "request has and the paragraph; the paragraph follows the draft's text, nothing else is changed, and the buyer who owns the request signs the new text. Only for a waiting "
        "request of a buyer who owns this item too; a request already approved or sent is not changed: use draft_supplier_request for a new one.",
        {"action_id": str, "paragraph": str},
        annotations=STAGE,
    )
    async def amend_draft(args):
        if not ctx.stage_allowed:
            return refuse("nothing may be drafted for this item")
        a = ledger.get(ctx.db_path, args["action_id"])
        if a is None or a.type != "supplier_request":
            return refuse("no such request; amend_draft takes the action id of a request to a supplier")
        if a.state != "proposed":
            return refuse(f"that request is already {a.state}: it cannot be changed; draft a new one instead")
        if a.item_key != ctx.item_key:
            mine, theirs = approvers.owners_of(ctx.db_path, _case_key(ctx)), approvers.owners_of(ctx.db_path, a.item_key)
            if not mine or not theirs or not (mine & theirs):
                return refuse(f"that request belongs to {' and '.join(sorted(theirs)) if theirs else 'another buyer'}, not to an owner of this item: it is theirs to change. Draft this item's own request with draft_supplier_request instead; never log a question to get round it")
        paragraph = re.sub(r"^(?:also|additionally|separately|in addition|moreover)\s*[,:]\s*", "", args["paragraph"].strip(), flags=re.I)  # the text gets one connector, "Also:", not two
        if not paragraph:
            return refuse("give the paragraph to add")
        bad = _bad_text(ctx, "", paragraph)  # only the paragraph is new: the subject was written and checked by the run that drafted it (AGENT-EXPERT: an origin amend was refused for a date in the slip run's subject)
        if bad:
            return refuse(bad)
        asks = ledger.asks_of(a)
        merged = ctx.item_key not in asks  # another item's ask joins this request: a numbered paragraph, recorded as "amended for <item>"
        text = re.sub(r"^please also\s+", "Please ", paragraph, flags=re.I)
        text = text[:1].upper() + text[1:]   # another item's ask is its own paragraph: never "Also: Please also" (BUYER R2 final)
        change = {**(a.change or {}), "asks": [*asks, ctx.item_key], "amended_for": [*((a.change or {}).get("amended_for") or []), ctx.item_key]} if merged else None
        new = ledger.update_draft(ctx.db_path, a.action_id, subject=a.subject or "", body=_styled(ctx, a.subject or "", insert_before_signoff(a.body or "", text), a.item_key, recipient=a.recipient or ""), edited_by="Lookout", change=change, run_id=ctx.run_id)
        ledger.link_to_run(ctx.db_path, ctx.run_id, new.action_id)
        if new.action_id not in ctx.action_ids:
            ctx.action_ids.append(new.action_id)
        return reply(ctx, f"A paragraph was added to the waiting request to the supplier: {new.subject}; its owner signs the new text",
                     {"action_id": new.action_id, "state": new.state, "type": new.type, "recipient": new.recipient, "subject": new.subject, "payload_hash": new.payload_hash, "amended": True, "added": text, "amended_for": ctx.item_key if merged else None})

    @tool(
        "stage_decision",
        f"Stage a decision the buyer asked for on this case (a planned or bridge order, a choice of option, a decision to wait) as a record for the case owner's signature. "
        f"It lands on the case's Approval card, PROPOSED; approving records it and sends nothing and writes nothing to the ERP. Give the decision in one line "
        f"(part, quantity, price, terms, as the tools or the buyer gave them) and the reason. For an order, call compare_offers for the part first so the price, its change against last paid and the terms are the quote's. Not for an email to a supplier (draft_supplier_request), and never on a trust item.",
        {"type": "object", "required": ["decision", "reason"], "properties": {
            "decision": {"type": "string", "description": "one line, e.g. 'Planned order <part> · <qty> · <price each> (<change vs last paid>) · no prepayment · deliver by <date>': price, change and date only as a tool returned them; a quantity only as the buyer or a tool gave it, else 'quantity to set'"},
            "reason": {"type": "string"}, "recheck_on": {"type": "string", "description": "YYYY-MM-DD, for a decision to wait"},
            "item_key": {"type": "string", "description": "the case it belongs to, when the question was asked with no case open (from list_items / get_item)"},
            "to": {"type": "string", "description": "for a NOTE to a team inside the company the buyer asked you to prepare (planning, logistics, Accounts Payable): who reads it. It is staged for the owner's signature like a decision, never sent or recorded on its own"}}},
        annotations=STAGE,
    )
    async def stage_decision(args):
        if not (ctx.item_key or "").startswith("ask:"):  # only a decision the buyer asked for in Ask: a case run, the pre-run or a re-record never stages one on its own (AGENT-EXPERT M1)
            return refuse("a decision is staged only when the buyer asks for it in Ask; lay out the options instead")
        key = _case_key(ctx)
        if key.startswith("ask:") and args.get("item_key"):  # asked from Today: the case the agent found; it must be a real case with an owner (checked below)
            key = args["item_key"]
        if not ctx.stage_allowed or key.startswith(("trust:", "ask:")):
            return refuse("a decision is staged only on a case on the Action list (open the case and ask there); never on a trust item")
        text, reason = (args.get("decision") or "").strip(), (args.get("reason") or "").strip()
        if not text or not reason:
            return refuse("give the decision in one line and its reason")
        if _FORBIDDEN.search(f"{text} {reason}"):
            return refuse("a decision may not mention bank details or moving money; leave those to a person")
        from ...organism.verifier import stray_in_text  # noqa: PLC0415

        nums, days = stray_in_text(ctx, f"{text} {reason}")
        nums = [n for n in nums if Decimal(n) not in ctx.asked_numerals]
        if nums or days:
            return refuse("The decision states " + "; ".join(x for x in (f"numbers no tool returned and the buyer did not give: {', '.join(nums)}" if nums else "", f"dates no tool returned: {', '.join(days)}" if days else "") if x)
                          + ". Use the tools' figures or the buyer's own, or leave them out.")
        try:
            owners = approvers.owners_of(ctx.db_path, key)
        except Exception:  # noqa: BLE001  nobody can sign: nothing is staged
            owners = None
        if not owners:
            return refuse(f"{key} has no owner on the Action list, so nobody could sign a decision on it")
        owner = next(iter(sorted(owners))) if len(owners) == 1 else None
        to = (args.get("to") or "").strip()  # a note to a team inside the company (P7's note): staged PROPOSED for the owner, like the Approval card's own path (LOOKOUT P1: a note from Ask was recorded unsigned)
        a = ledger.propose(ctx.db_path, type="note", item_key=key, run_id=ctx.run_id, target=None, recipient=None, subject=f"Note to {to}" if to else "Decision", body=text,
                           change={"kind": "note" if to else "record", "to": to or None, "reason": reason, "lines": None, "recheck_on": args.get("recheck_on"), "option_kind": None, "owner": owner, "by": "Lookout"})
        if a.action_id not in ctx.action_ids:
            ctx.action_ids.append(a.action_id)
        return reply(ctx, f"Staged a {'note to ' + to if to else 'decision'} on {key} for its owner's signature: {text}", {"action_id": a.action_id, "state": a.state, "type": a.type, "subject": a.subject, "payload_hash": a.payload_hash})

    return [draft_supplier_request, log_buyer_question, propose_supplier_alias, amend_draft, stage_decision]
