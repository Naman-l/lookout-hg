"""Ask: the one agentic workflow. A buyer asks a question, optionally with the record on screen as context, and
Lookout decides whom to ask. There is no fixed plan: any specialist, once each, three at most, on a tighter budget.
The answer has the same shape as any Recommendation and passes the same verifier."""

from __future__ import annotations

import hashlib
import re

from ... import watcher
from ...domain.common import EntityRef
from .. import services as default_services
from ..runner import RunResult, finish, run_agent
from ..runs.events import Recorder
from ..schemas import RecommendationDraft, draft_schema
from ..specialists.registry import SPECIALISTS
from ..verifier import numerals
from .judging import Judging

ASK_BUDGET_USD = 0.5  # a question costs less than working an item
ANY_LOOKUP = (tuple(sorted({t for s in SPECIALISTS.values() for t in s.tools} - {"get_handoffs", "submit_handoff"})),)  # at least one real lookup


def ask_key(question: str, context: EntityRef | None) -> str:
    return "ask:" + hashlib.sha1(f"{question}|{context.type if context else ''}:{context.id if context else ''}".encode()).hexdigest()[:8]


def _allows_drafting(context: EntityRef | None, services) -> bool:
    """Nothing is drafted from a context whose sender is not trusted (a trust item, or a message not on file)."""
    if context is None:
        return True
    if context.id.startswith("trust:"):
        return False
    if context.type == "message":
        try:
            return services.inbox.read_thread(context.id).trust == "on_file"
        except KeyError:
            return False
    return True


def case_of(context: EntityRef | None, db_path: str | None = None) -> str | None:
    """The Action-list case a question is asked on, when there is one: what the run stages belongs to it (Rev 4.1). Never a trust item: nothing is staged there.
    An Ask scoped to a waiting draft ("Ask for changes", Rev 4.1 step 3) is on that draft's case, so the change is an amend its owner signs again."""
    if context is not None and context.type == "action":
        draft = _waiting_draft(context.id, db_path)
        context = EntityRef(type="item", id=draft.item_key) if draft is not None and draft.item_key else None
    if context is None or context.type != "item" or not context.id or context.id.startswith("trust:"):
        return None
    return context.id


def _waiting_draft(action_id: str, db_path: str | None):
    """The draft an Ask for changes is about, while it waits for approval; None for a decided, missing or unreadable one."""
    from ...domain.actions import ledger  # noqa: PLC0415

    try:
        a = ledger.get(db_path, action_id) if db_path else None
    except Exception:  # noqa: BLE001  nothing to change
        return None
    return a if a is not None and a.state == "proposed" else None


_REFERS_BACK = re.compile(r"\b(those|these|them|that one|this one|that line|those lines|the same|same one|the other one|what about|how about|instead|why did you|you recommend)\b", re.I)  # clear pointers only: 'it', 'that' and 'also' are too common to mean the earlier subject


def refers_back(question: str) -> bool:
    """Whether a follow-up points back to the earlier turn ('those', 'it', 'the same', 'what about…'): only then does it carry the earlier subject."""
    return bool(_REFERS_BACK.search(question or ""))


# What each screen is for and what Lookout can do from it (h10): no case names, the same for any company. Lookout cannot click, filter or change the screen.
PAGE_FOR = {
    "today": "the buyer's list of cases that need a decision, theirs or everyone's, by kind",
    "case": "one case: what happened, the evidence, the ways through, the draft and what came back",
    "approvals": "the drafts waiting for a signature",
    "inbox": "supplier messages and the cases they move",
    "build": "one robot's next three months: planned, short, the cases behind it and the parts that land late",
    "supplier": "the supplier records", "part": "the part records", "bom": "a robot's bill of materials", "orders": "the open purchase orders",
    "forecast": "the build plan by month", "data": "the data the app is built from and its checks", "import": "a data import",
    "hood": "how Lookout works: its agents and their rules", "activity": "the agent runs and their traces",
}
PAGE_CAN_CASE = "From here you can stage a decision or a note on this case for its owner's signature, or amend its waiting draft."
PAGE_CAN = "From here you can name a case (it is linked in your answer so the buyer can open it) and stage a decision or a note on a case the buyer names."
PAGE_CANNOT = "You cannot click, filter, sort or change what is on the screen: if the buyer asks for that, say what you can do instead and link the case."


def page_lines(page: dict | None) -> list[str]:
    """The page the buyer asked from, in two lines: where they are and what Lookout can do from there."""
    if not page or not page.get("kind"):
        return []
    kind, label = page["kind"], (page.get("label") or "").strip()
    out = [f"The buyer is on {label or kind} in Lookout" + (f": {PAGE_FOR[kind]}." if kind in PAGE_FOR else ".")]
    out.append((PAGE_CAN_CASE if kind == "case" else PAGE_CAN) + " " + PAGE_CANNOT)
    return out


def build_prompt(question: str, context: EntityRef | None, asked_by: str | None, thread: dict | None = None, page: dict | None = None) -> str:
    lines = [f"A buyer{f' ({asked_by})' if asked_by else ''} asks: {question}"]
    if thread and (thread.get("question") or thread.get("answer")) and not refers_back(question):  # a new subject in the same session: the thread is background, never the subject (BUYER Q6 answered about Q4's supplier)
        lines.append("Earlier in this session (background only): they asked " + (thread.get("question") or "(none)") + " · you answered: " + (thread.get("answer") or "(none)")[:300]
                     + "\nThis question does not point back to that one: work on what THIS question names ('my duty share' is the duty case; a supplier, part or robot it names is that one), not on what the earlier turn was about.")
        thread = {**thread, "question": "", "answer": "", "about": [], "ids": {}}
    if thread and (thread.get("question") or thread.get("answer")):  # a follow-up: what the earlier turn asked, answered and was about, so 'those' and 'it' have something to mean
        lines.append("This follows an earlier turn of the same conversation. Earlier question: " + (thread.get("question") or "(none)") + "\nYour earlier answer: " + (thread.get("answer") or "(none)")[:900]
                     + ("\nIt was about: " + "; ".join(thread["about"]) + "." if thread.get("about") else "")
                     + ("\nIds from that turn, to pass to the tools exactly (a tool takes an id, never a name): " + "; ".join(f"{k} {', '.join(v)}" for k, v in thread["ids"].items()) + "." if thread.get("ids") else "") + "\nWords like 'those', 'it' and 'the same' in the new question mean what that answer was about."
                     + (" Use `get_item`/the specialists on them; do not ask the buyer which ones." if thread.get("about") else ""))
    for t in (thread or {}).get("earlier") or []:  # older turns of the same conversation, newest first: what was decided stays decided
        ctx_ = t.get("context") or {}
        lines.append("Before that, they asked: " + (t.get("question") or "(none)") + " · your answer: " + (t.get("answer") or "(none)")[:300]
                     + (f" · on {ctx_.get('type')} {ctx_.get('id')}" if ctx_.get("id") else ""))
    lines += page_lines(page)
    if context:
        lines.append(f"They are looking at {context.type} {context.id}" + (f" ({context.label})." if context.label else "."))
        if context.type == "item":
            lines.append("Read it with get_item first.")
        if context.type == "action":
            lines.append(f"It is the waiting draft {context.id}. If the buyer asks for a change, add it with amend_draft(action_id='{context.id}', ...): it is added as a numbered paragraph and the owner signs the new text. Never draft a second email for it.")
        if context.type == "message":
            lines.append("Read the message first (the Inbox analyst). If it quotes or reprices parts, then ask the Tariff analyst for the duty on those parts and the Sourcing analyst for the offers beside the current supplier, "
                         "and answer what it would cost and when it could start, from their numbers. A handoff that read nothing is not an answer: ask again.")
    lines.append("Answer with the bound the records support, never 'cannot be given': where stock on hand is not on file, give the tool's 'up to' figure (short by up to N; robots the open orders cover: call open_supply with the PART number, then where_used_for_parts, and cite cover:<part>:<robot>:robots_on_order) and say once that stock on hand is not on file.")
    lines.append(f"Speak to the buyer as 'you'{f' (they are {asked_by})' if asked_by else ''}: never name them in the third person."
                 + (f" 'My' means {asked_by.split()[0]}'s own: on the duty case (get_item tariff:all) that is duty_share:{asked_by.split()[0]}, split into duty_share_fixed (cannot be avoided) and duty_share_open (still depends)." if asked_by else ""))
    lines.append("Say each figure's unit: parts (EA, per part) are never robots, robots are never parts. Give each month's figure on its own; a total across months only if a tool returns that total, never one you add up.")
    lines.append("Say that a line or part stops a build 'first' only when code orders it (a date, or the chase list's stated order); otherwise list the lines with days past due and the robot each feeds, and say the shortfall is not computed without stock data.")
    lines.append("When parts have no quote from another supplier on file, say so by part number, name any alternate on file, and offer to prepare an RFQ note for sourcing (prepare it only if the buyer asks).")
    lines.append("A draft or case owned by another buyer: say 'With <first name>' and that only they can approve it.")
    lines.append("A shortfall of 0 is said 'not short on open orders', never 'short by up to none'.")
    lines.append("A robot count is said only with the robot and the part its figure names (cover:<part>:<robot>, shortage, build): never of another line, part or robot.")
    lines.append("An order decision states the quote's invoiced price per piece, the break it is quoted for and the terms, as compare_offers returned them (pass the order quantity, so the right break applies); never 'to be confirmed' when a tool returned the price. "
                 "Every % change names its basis, both from code: '+X% as invoiced, incl. the surcharge (vs_last_paid_pct) · +Y% on price alone (vs_last_paid_price_pct)', with the break. "
                 "Where the quote demands a prepayment, state the order total (order_<qty>_usd) and the prepayment an order on open terms avoids (order_<qty>_prepayment_usd).")
    lines.append("A 'what if I order …' question: answer it, then offer a planned order for the next need that you can prepare as a decision for signature (quantity to set unless the buyer or a tool gives one).")
    lines.append("A robot count is said as 'up to N <robot> short in <month>' from the tools, never as 'zero can be built'.")
    lines.append("Lists and comparisons (lines, months, quotes, duty by part) are shown beside your answer as tables built from your lookups: do not list them in prose; give the conclusion and the one or two figures that decide it.")
    lines.append("Your answer is shown in the Ask panel beside the page the buyer is on: answer the question in a few plain sentences. You may say which page they are on and what you can do from it; never point to the layout ('below', 'above', options 'laid out'). If there are ways forward, name them in the sentence that gives them.")
    lines.append("No plan is fixed: decide whom to ask, then answer in the Recommendation. If a request to a supplier is the right answer, the clerk can stage it for approval. "
                 "If the buyer asks you to prepare a decision on this case (a bridge or planned order, a choice of option, a decision to wait), the clerk stages it with stage_decision: "
                 "it lands on the case's Approval card for the owner to sign. Do it; do not tell the buyer to do it. "
                 "A note the buyer asks you to prepare for a team inside the company (planning, logistics, Accounts Payable) is stage_decision with `to` set: staged for signature too. log_buyer_question is refused in Ask; never say anything is ready for signature unless a tool staged it.")
    return "\n".join(lines)


def case_brief(case: str | None, services, db_path: str | None):
    """What an Ask on a case starts from (BUYER Q1/Q2/Q10/Q11): the case's own code packet (where it stands, linked cases, the records' facts,
    the ways through with their figures and ids) and the case's current answer, so the run cites them instead of re-deriving or missing them.
    Returns (text, packet, quotable) or ("", None, ""): quotable is the part code wrote, the only part whose figures and dates count as seen."""
    if not case:
        return "", None, ""
    try:
        from ..context_packet import build  # noqa: PLC0415

        item = services.attention.get_item(case)
        packet = build(item, services, db_path)
    except Exception:  # noqa: BLE001  the Ask still runs without the brief
        return "", None, ""
    answer = _case_answer(case, db_path)
    msgs = list(dict.fromkeys([r.id for r in getattr(item, "refs", None) or [] if r.type == "message"]
                              + [m.ref.id for m in getattr(item, "messages", None) or [] if getattr(getattr(m, "ref", None), "id", None)]))[:3]  # a case's notice is in its messages, not its refs
    source = ("The case's source messages (read them with read_message for exact terms such as order cut-offs, lead times and validity): " + "; ".join(msgs) + ".") if msgs else ""
    text = "\n".join(x for x in (packet.text, source, answer) if x)
    quotable = "\n".join(x for x in (packet.text, source) if x)  # code's words only: the earlier answer is a model's text, so nothing in it counts as checked (AGENT-EXPERT M2)
    return (f"What code already knows about {case} (cite these ids; do not re-derive them):\n{text}" if text else ""), packet, quotable


def _case_answer(case: str, db_path: str | None) -> str:
    """The case's current answer from its newest finished run: the finding and the recommended way through with its reason."""
    import json  # noqa: PLC0415
    import sqlite3  # noqa: PLC0415

    if not db_path:
        return ""
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
            row = con.execute("SELECT recommendation_json FROM runs WHERE parent_run_id IS NULL AND item_key = ? AND status = 'ok' AND recommendation_json IS NOT NULL ORDER BY started_at DESC LIMIT 1", (case,)).fetchone()
    except sqlite3.Error:
        return ""
    if not row:
        return ""
    rec = json.loads(row[0])
    r = rec.get("recommended") or {}
    return ("The case's current answer: " + (rec.get("finding") or "").strip()
            + (f" Recommended way through: {r['kind']} ({r.get('reason', '')})." if r.get("kind") else "")
            + " If the buyer asks why, answer from this and the figures it cites.")


def ask_preload(question: str, packet, quotable: str):
    """What an Ask registers before the model runs: the numerals the buyer typed (a decision may restate them), and from the case brief only what
    code wrote (the packet's numbers with ids; its words, dates and day counts). Never the earlier answer's text: a model's figure is not checked by being repeated."""
    def load(c):
        c.asked_numerals.update(numerals(question))
        if packet is not None and quotable:
            from ..verifier import dates_in, day_counts  # noqa: PLC0415

            c.register(packet.numbers)
            c.unknowns.extend(u for u in packet.unknowns if u not in c.unknowns)
            c.seen_numerals.update(numerals(quotable))
            c.seen_day_counts.update(day_counts(quotable))
            c.seen_dates.update(dates_in(quotable))
    return load


async def run_ask(question: str, *, db_path: str, context: EntityRef | None = None, asked_by: str | None = None, services=None,
                  run_id: str | None = None, recorder: Recorder | None = None, thread: dict | None = None, page: dict | None = None) -> RunResult:
    own = services is None
    services = services or default_services.get(db_path)
    key = ask_key(question, context)
    case = case_of(context, db_path)
    brief, packet, quotable = case_brief(case, services, db_path) if _allows_drafting(context, services) else ("", None, "")
    try:
        watcher.emit("agent", "workflow.start", f"Ask: {question[:80]}", item_key=key)
        judging = Judging(kind="ask", title=question, services=services, max_cost=ASK_BUDGET_USD, required_tools=ANY_LOOKUP, lookup_only_if_claims=True)
        result = await run_agent(
            item_key=key, db_path=db_path, plan=list(SPECIALISTS), open_plan=True, prompt=build_prompt(question, context, asked_by, thread, page) + (f"\n{brief}" if brief else ""), services=services,
            workflow="ask", stage_allowed=_allows_drafting(context, services), run_id=run_id, recorder=recorder, asked_by=asked_by, max_budget=ASK_BUDGET_USD,
            tool_caps={"exposure_for_part": 3, "exposure_for_parts": 2, "build_readiness": 3, "open_supply": 3, "compare_offers": 5, "shortage_for_parts": 2, "where_used_for_parts": 2}, output_schema=draft_schema(ask=True),
            started={"summary": f"Asked: {question}", "question": question, "context": context.model_dump() if context else None, "follows": bool(thread), "thread_id": (thread or {}).get("run_id")}, judge=judging,
            action_item_key=case, preload=ask_preload(question, packet, quotable),
        )
        status, rec_json, ver_json = judging.finish(result) if result.status == "ok" else (result.status, None, None)
        finish(result, status=status, recommendation_json=rec_json, verifier_json=ver_json)
        result.status = status
        await judging.grade_after(result)
        return result
    finally:
        if own:
            services.close()
