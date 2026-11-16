"""Ask, answered by code when no model is connected: the question is read for what it names (a PR or PO number, a vendor, a project or one of its
aliases, a material, a member of the team, the case on screen) and what it wants, and answered from the same tools a specialist would call: the
case's own questions here, everything across the company's records by the planner (planner.py), every figure from its row, with what the
records cannot say and who could. A request to prepare a note or a letter stages the route's draft for the owner's signature. Every answer says
it was answered by code, and what a model would add is never claimed.
"""

from __future__ import annotations

import asyncio
import re

from sqlalchemy.orm import Session

from app import db as app_db
from app.domain import lookups
from app.domain.attention import service as attention
from app.domain.fmt import dmy, en_in, inr, md
from app.domain.search import service as search

from . import coderun, planner, tools
from .runs.events import LABELS, Recorder

PR, PO = re.compile(r"\b(10\d{8})\b"), re.compile(r"\b(45\d{8})\b")


def examples(session: Session, page: str | None = None, key: str | None = None, ctx: dict | None = None) -> list[dict]:
    """Seeded suggestions: the case's own, then the record's or the page's (planner.suggestions). Each has an answer by code."""
    out: list[dict] = []
    d = attention.item_detail(session, key) if key else None
    if d is not None:
        pname = d.projects[0].label if d.projects else ""
        per = {
            "pr-cancelled": [f"Which of these {len(d.pr_lines)} PRs had quotes in hand?", f"Prepare a note to the {pname} project head asking for cancellation approval"],
            "pv-longlead": [f"What does a month's wait cost on the {next((f.fact.split(':')[0] for f in d.findings), 'items')}?", "Which of these items is firm and which is PV-linked?"],
            "rate-spread": [f"Why does {pname} pay above the median?", "Which sites pay above the median?"],
            "mfc-validity": ["What happens if the MFC is issued after the validity?", "Where does the PO stand from PR to payment?"],
            "pr-stuck": ["How long has the PR waited on Projects?", "Prepare a note to the planner asking for the specification"],
            "late-streak": ["What is still open with this vendor?", "Which receipts were late?"],
            "pv-claim": ["What does the PO's clause owe?", "Prepare the reply with the computed PV"],
        }.get(d.kind, ["Where does it stand from PR to payment?", "What do we not know yet, and who can say?"])
        out += [{"question": q, "context": {"type": "item", "id": key, "label": d.title}} for q in per]
    eg = _samples(session)
    pr, po, vendor = f"Where does PR {eg.get('pr_line', '')} stand?", f"Where does PO {eg.get('po_line', '')} stand?", f"What is open with {eg.get('supplier', '')}?"
    page_qs = planner.suggestions(session, page, ctx)
    if page in ("prs", "pos") and eg.get(f"{page[:2]}_line"):
        page_qs.insert(1, pr if page == "prs" else po)
    elif not page_qs and d is None:
        page_qs = [pr, vendor, "Which cases wait on Projects?"]
    out += [{"question": q, "context": None} for q in page_qs if q not in {x["question"] for x in out}]
    return out[:6]


def everywhere(session: Session) -> list[dict]:
    """Questions about the whole company, each answered by the planner."""
    return [{"question": q, "context": None} for q in planner.everywhere(session)]


def _samples(session: Session) -> dict[str, str]:
    """The first PR line, PO line and vendor that today's cases name, so a suggestion asks about a real record."""
    eg: dict[str, str] = {}
    for i in attention.what_needs_attention(session):
        for r in i.refs:
            if r.type in ("pr_line", "po_line") and r.type not in eg:
                eg[r.type] = r.id.split("/")[0]
            elif r.type == "supplier" and r.label and r.type not in eg:
                eg[r.type] = r.label
    return eg


def _table(title: str, by: str, columns: list[str], rows: list[dict]) -> dict:
    return {"kind": "rows", "title": title, "by": by, "columns": columns, "rows": rows[:8], "more": max(0, len(rows) - 8)}


def answer(session: Session, q: str, context: dict | None, asked_by: str | None, run_id: str | None = None) -> tuple[dict, list[tuple[str, dict, dict]]]:
    """(the Recommendation, the lookups made as (tool, args, result))."""
    calls: list[tuple[str, dict, dict]] = []

    def call(tool: str, **args):
        res = getattr(tools, tool)(session, **args)
        calls.append((tool, args, res))
        return res

    low = q.lower()
    key = context.get("id") if context and context.get("type") == "item" else None
    d = attention.item_detail(session, key) if key else None
    nums = lambda res: [{"id": n.id, "value": str(n.value), "unit": n.unit, "name": n.name, "say": n.say} for n in res.get("numbers", [])]  # noqa: E731

    # a request to prepare a note or a letter: the case's route, drafted for the owner's signature
    if d is not None and re.search(r"\b(prepare|draft|write)\b", low) and re.search(r"\b(note|letter|email|reply|memo)\b", low):
        rs = tools.routes_of(session, key, asked_by)
        words = {"cancel": "cancel_approval", "specification": "ask_projects", "spec": "ask_projects", "extension": "extension", "validity": "extend_validity", "reply": "reply_computed",
                 "firm date": "firm_dates", "plinth": "ask_plinth", "commission": "ask_commissioning", "finance": "ask_finance", "hold": "hold_quotes"}
        kind = next((v for k, v in words.items() if k in low and v in {r.kind for r in rs}), None)
        if kind is None:
            from .coderun import recommend  # noqa: PLC0415

            kind = recommend(d, rs)[0]
        me = lookups.member_of(session, asked_by)
        if me is None or me.name not in d.owner.split(" · "):
            return ({"finding": f"Only {d.owner.replace(' · ', ' or ')} can have a draft prepared on this case: a draft is signed by its owner.", "numbers": [], "drafted_by": "code"}, calls)
        from app.domain.actions.routes import RouteError, draft_route  # noqa: PLC0415

        try:
            out, how = draft_route(session, app_db.DB_PATH, key, kind, me.name, run_id=run_id)
        except RouteError as e:
            return ({"finding": f"Not drafted: {e.message}", "numbers": [], "drafted_by": "code"}, calls)
        a = out[0]
        to = a.recipient or "the record"
        return ({"finding": f"Drafted {'a note' if a.type != 'supplier_request' else 'a letter'} to {to} for your signature ({how}): \"{a.subject}\". Nothing is sent until you sign it in Approvals.",
                 "points": [{"label": "Route", "text": next((r.label for r in rs if r.kind == kind), kind)}, {"label": "Next", "text": "Sign or edit it in Approvals"}],
                 "numbers": [], "action_ids": [x.action_id for x in out], "drafted_by": "code"}, calls)

    # the cancelled enquiry: which lines had quotes in hand
    if d is not None and d.kind == "pr-cancelled" and "quote" in low:
        res = call("get_item", key=key)
        from app.domain.quotes.model import Quote  # noqa: PLC0415

        rows = []
        for l in d.pr_lines:
            qs = [x for x in session.query(Quote).filter(Quote.pr_line_id == l.ref.id, Quote.rate.is_not(None))]
            if qs:
                best = min(qs, key=lambda x: x.rate)
                rows.append({"label": f"PR {l.ref.id} · {l.text}", "ref": {"type": "pr_line", "id": l.ref.id},
                             "cells": [{"say": str(len(qs)), "id": f"pr:{l.ref.id}:quotes"}, {"say": inr(best.rate), "id": f"pr:{l.ref.id}:l1"}, {"say": md(best.validity), "id": f"pr:{l.ref.id}:valid"}]})
        return ({"finding": f"{len(rows)} of the {len(d.pr_lines)} short-closed PR lines had priced quotes in hand when they were deleted; the earliest lapses {md(d.act_by)}.",
                 "numbers": nums(res), "points": [{"label": "Enquiry value", "text": inr(float(d.at_stake.amount))}], "drafted_by": "code",
                 "tables": [_table("Lines with quotes in hand", "Sourcing analyst", ["Quotes", "Lowest", "Valid to"], rows)]}, calls)

    # a month's wait on long-lead PV items
    if re.search(r"month'?s wait|cost of waiting|delay cost|each month", low):
        pid = next((p.id for p in d.projects), None) if d is not None else None
        res = call("lookahead", project=pid)
        items = [i for i in res["items"] if not i["ordered"] and i["basis"] == "PV"]
        hit = [n for n in res["numbers"] if n.id.endswith(":delay_cost")]
        words = [w for w in re.findall(r"[a-z0-9]{2,}", low) if w not in ("what", "does", "month", "wait", "cost", "the", "items", "on", "of", "s")]
        score = {n.id: sum(1 for w in words if w in n.name.lower()) for n in hit}
        top = max(score.values(), default=0)
        use = [n for n in hit if top and score[n.id] == top] or hit
        total = sum(float(n.value) for n in use)
        return ({"finding": f"Each month these {len(use)} PV-linked item(s) wait costs about {inr(total)} at the indices' average rise over six months" + (f" ({', '.join(n.name.split(':')[0] for n in use[:3])})." if use else "."),
                 "numbers": [x for x in nums(res) if x["id"] in {n.id for n in use}], "drafted_by": "code",
                 "points": [{"label": "Not ordered", "text": f"{len(items)} PV item(s)"}, {"label": "Rule", "text": "value x variable share x average monthly index change"}],
                 "tables": [_table("A month's wait", "Price and PV analyst", ["Per month"], [{"label": n.name.split(":")[0], "cells": [{"say": n.say, "id": n.id}]} for n in use])]}, calls)

    # why one site pays more than another
    if re.search(r"\bwhy\b.*\b(pay|paid|costs?)\b.*\bmore\b", low):
        mat = next((code for code, m in lookups.materials(session).items() if m.description.lower().split()[0] in low), "11000020")
        res = call("rate_history", material=mat)
        sites = res.get("sites", [])
        named = [s for s in sites if s["project"].lower() in low]
        return ({"finding": "The records do not say why: they hold each site's rate, not the reason (haul distance, quality, the unit kept, the local market). "
                            + ("; ".join(f"{s['project']} paid {inr(s['rate'])} ({s['vendor']}, {md(s['date'])})" for s in named) + "." if named else ""),
                 "numbers": nums(res), "drafted_by": "code",
                 "open_questions": [{"what": f"why {s['project']} pays {inr(s['rate'])}", "why_it_blocks": "a spread is a saving only if the reason is not haul or quality",
                                     "owner": next((l.buyer_id for l in tools.orders.all_lines(session).values() if l.material == mat and l.project_id == lookups.resolve_project(session, s["project"])), "unassigned"),
                                     "question": f"Why does {s['project']} pay {inr(s['rate'])}?", "refs": []} for s in (named or sites[-2:])],
                 "points": [{"label": "Who can say", "text": "each site's buyer (the open questions name them)"}]}, calls)

    # on a PR's or a PO's page, a question that names no other number is about that one
    if context and context.get("type") in ("pr", "po") and not PR.search(q) and not PO.search(q) and not re.search(r"\b(which|list|how many|top|all|every)\b", low):
        q = f"{q} ({context['type'].upper()} {context['id']})"
    m = PR.search(q)
    if m:
        lines = [l for l in tools.prs.lines_of_pr(session, m.group(1))]
        if lines:
            res = call("pr_ladder", pr_line=lines[0].id)
            now = next((r for r in res["rungs"] if r["state"] == "now"), None)
            return ({"finding": f"PR {m.group(1)} ({lines[0].short_text}) is at '{now['rung'] if now else 'closed'}', with {res.get('waiting_on') or 'nobody'}"
                                + (f" for {next((int(n.value) for n in res['numbers'] if n.id.endswith('days_waiting')), 0)} days." if now else "."),
                     "numbers": nums(res), "drafted_by": "code",
                     "points": [{"label": r["rung"], "text": f"{md(r['date']) if r['date'] else r['state']}" + (f" · {r['held_by']} {r['days']} d" if r.get("held_by") and r.get("days") else "")} for r in res["rungs"] if r["state"] in ("done", "now")][-4:]}, calls)
    m = PO.search(q)
    if m:
        lines = tools.orders.lines_of_po(session, m.group(1))
        if lines:
            res = call("po_ladder", po_line=lines[0].id)
            res2 = call("open_pos", vendor=lines[0].identity_id)
            mine = [r for r in res2["rows"] if r["po_line"].startswith(m.group(1))]
            return ({"finding": f"PO {m.group(1)} with {lookups.vendor_name(session, lines[0].identity_id)}: " + ("; ".join(f"item {r['po_line'].split('/')[1]} {en_in(r['open_qty'])} {r['uom']} open, due {md(r['due'])}" + (f", the vendor now says {', '.join(md(x) for x in r['revised'])}" if r["revised"] else "") for r in mine) or "fully received") + ".",
                     "numbers": nums(res) + nums(res2), "drafted_by": "code"}, calls)

    found = planner.plan(session, q, context, asked_by)
    if found is not None:
        rec, looks = found
        return rec, calls + looks

    if d is not None:
        res = call("get_item", key=key)
        if d.ladder is not None and re.search(r"stand|pr to payment|where", low):
            L = d.ladder
            return ({"finding": f"Now with {L.waiting_on or 'nobody'}" + (f" for {L.days_waiting} days" if L.days_waiting else "") + ". Days held so far: " + ", ".join(f"{k} {v}" for k, v in L.held.items()) + ".",
                     "numbers": nums(res), "drafted_by": "code"}, calls)
        return ({"finding": d.finding or d.title, "numbers": nums(res), "drafted_by": "code",
                 "points": [{"label": "Waiting on", "text": d.waiting_on}, {"label": "Act by", "text": md(d.act_by) if d.act_by else "no date"}],
                 "open_questions": [u.model_dump() for u in d.unknowns][:6]}, calls)

    hits = search.search(session, q, limit=6)
    calls.append(planner.Look("lookout", "search", {"q": q}, "Search the records for the question's words.", f"{len(hits)} records match"))
    can = "vendors, POs, PRs, projects, materials and rates, cases, MSME dues, LCs and BGs, long-lead items, work fronts, the inbox, the team and your approvals"
    return ({"finding": (f"I could not tell what to look up from that question, so I searched the records for its words: {len(hits)} match." if hits else
                         "I could not tell what to look up from that question, and no record matches its words.") + f" I answer by code across {can}: name one, or a vendor, a project or a material.",
             "numbers": [], "drafted_by": "code",
             "tables": [planner._table("Records that match", "Lookout", ["What"], [planner._row(h.label, h.url, [h.type.replace("_", " ")], sub=h.sublabel) for h in hits if h.url])] if hits else [],
             "follow_ups": planner.everywhere(session)[:3], "plan": [{"agent": "lookout", "tool": "search", "why": "Search the records for the question's words.", "found": f"{len(hits)} records match"}]}, calls)


async def run_ask(rec: Recorder, question: str, context: dict | None, asked_by: str | None) -> dict:
    with app_db.SessionLocal() as s:
        rec.emit("run.started", f"Asked: {question}", question=question, mode="code")
        await asyncio.sleep(coderun.PACE)
        rec.emit("step.text", "I read the question for what it names and wants, then look it up in the records (by code: no model is connected here).")
        rec_out, calls = answer(s, question, context, asked_by, rec.run_id)
        looks = [c for c in calls if isinstance(c, planner.Look)]
        if looks:
            specs = list(dict.fromkeys(l.agent for l in looks if l.agent != "lookout"))
            rec.emit("step.text", "Planned: " + (", then ".join(LABELS.get(x, x) for x in specs) if specs else "Lookout reads the records") + ".")
        current = None
        for c in calls:
            if isinstance(c, planner.Look):
                if c.agent != current:
                    if current not in (None, "lookout"):
                        rec.emit("child.finished", f"{LABELS.get(current, current)} handed off.", agent=current)
                    if c.agent != "lookout":
                        rec.emit("child.started", f"{LABELS.get(c.agent, c.agent)}: {c.why}", agent=c.agent)
                    current = c.agent
                rec.emit("tool.called", c.tool, agent=c.agent, tool=c.tool, args={k: v for k, v in c.args.items() if v is not None}, gate="allowed", why=c.why)
                rec.emit("tool.result", c.found, agent=c.agent, tool=c.tool, numbers=[])
            else:
                tool, args, res = c
                rec.emit("tool.called", tool, agent="lookout", tool=tool, args=args, gate="allowed")
                rec.emit("tool.result", f"{len(res.get('numbers', []))} figures", agent="lookout", tool=tool, numbers=[n.model_dump(mode="json") for n in res.get("numbers", [])][:24])
            await asyncio.sleep(coderun.PACE)
        if current not in (None, "lookout"):
            rec.emit("child.finished", f"{LABELS.get(current, current)} handed off.", agent=current)
        for a in rec_out.get("action_ids") or []:
            rec.emit("action.staged", "Drafted for the owner's signature.", agent="buyers_clerk", action_id=a)
        rec.emit("run.finished", rec_out["finding"][:200], status="ok")
        return {"status": "ok", "recommendation": rec_out}
