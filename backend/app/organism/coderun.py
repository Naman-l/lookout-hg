"""A run drafted by code, with no model: what Lookout does on a case when no model is connected on this machine, said as what it is.

It follows the same plan a model run would (PLANS: the specialists per kind of case), calls the same tools, streams the same events (each step one
plain line, each lookup with its reason), and ends with the same Recommendation: the case's own finding, the facts code found, the route a rule
recommends (and why, with every figure cited by id), the open questions with their owners, and the Buyer's clerk's draft for that route staged for the
owner's signature. The verifier and the Reviewer check it like any run. Every screen labels it "drafted by code, no model".
"""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal

from sqlalchemy.orm import Session

from app import db as app_db
from app.domain import lookups
from app.domain.attention import service as attention
from app.domain.fmt import inr, md

from . import tools
from .runs.events import Recorder
from .schemas import Number
from .specialists.registry import PLANS, SPECIALISTS

PACE = float(os.environ.get("LOOKOUT_PACE", "0.18"))      # seconds between steps, so a person can watch the steps arrive


# The route a rule recommends per kind of case, and the reason in at most eight words (advice: the owner still chooses).
def recommend(d, routes) -> tuple[str | None, str, list[str]]:
    kinds = [r.kind for r in routes]
    k = d.kind
    stake = f"item:{d.key}:at_stake"
    amount = inr(float(d.at_stake.amount)) if d.at_stake is not None and hasattr(d.at_stake, "amount") else ""
    pick: dict[str, tuple[str, str, list[str]]] = {
        "pr-late": ("stockist_partial", "part early from stock; balance from L1", []) if "stockist_partial" in kinds else ("expedite_l1", "L1's fastest dispatch before the need date", []),
        "pr-stuck": ("ask_projects", "the wait is Projects': ask for the spec", []),
        "pr-cancelled": ("cancel_approval", f"{amount} enquiry spent: put the reason on record", [stake]),
        "mfc-validity": ("issue_mfc", f"avoids {amount} after the validity", [stake]),
        "inspection-ready": ("inspect_hold", "inspect on time; dispatch when the plinth is ready", []),
        "commissioning": ("ask_commissioning", "commission before the warranty ends", []),
        "schedule-slip": ("hold_original", "the site needs them before the new date", []),
        "pv-longlead": ("order_now", f"each month's wait costs {amount}", [stake]),
        "price-notice": ("buy_ahead", f"saves {amount} if acknowledged in time", [stake]),
        "pv-claim": ("reply_computed", f"the claim is {amount} over the clause", [stake]),
        "quote-lapse": ("extension", "hold the price while the CS is decided", []),
        "l1-above-last": ("negotiate_last", f"L1 is {amount} over the last rate", [stake]),
        "rate-spread": ("ask_why", "the reason per site is unknown", []),
        "lc": ("ask_finance", "the slot is lost if the LC is late", []),
        "abg": ("vendor_extend", "the advance is not recovered yet", []),
        "fund-mismatch": ("ask_mis", "Finance wants the sheet by its date", []),
        "late-streak": ("firm_dates", "last receipts all late: ask firm dates", []),
        "supply-stop": ("alt_supply", "supply stops inside the window", []),
        "inspection-fail": ("supply_po_oem", "the cable cannot be accepted", []),
        "renamed": ("verify_entity", "verify before moving open POs", []),
        "unknown": ("ask_owner", "each question goes to who can answer", []),
    }
    kind, reason, ids = pick.get(k, (kinds[0] if kinds else None, "", []))
    return (kind if kind in kinds else (kinds[0] if kinds else None)), reason, ids


def _tool_plan(spec: str, d) -> list[tuple[str, dict]]:
    """The lookups each specialist makes on this case, from the records the case names."""
    pid = d.projects[0].id if d.projects else None
    mat = next((r.id for r in d.refs if r.type == "material"), None) or ((d.pr_lines[0].material.id if d.pr_lines and d.pr_lines[0].material else None)
                                                                         or (d.po_lines[0].material.id if d.po_lines and d.po_lines[0].material else None))
    vend = d.vendor.ref.id if d.vendor else next((r.id for r in d.refs if r.type == "supplier"), None)
    plan: list[tuple[str, dict]] = [("get_item", {"key": d.key})]
    if spec == "site_planner":
        if d.pr_lines:
            plan.append(("pr_ladder", {"pr_line": d.pr_lines[0].ref.id}))
        if d.po_lines:
            plan.append(("po_ladder", {"po_line": d.po_lines[0].ref.id}))
        if pid and mat:
            plan.append(("requirement_for", {"project": pid, "material": mat}))
        if d.site_impact:
            plan.append(("site_impact", {"key": d.key}))
    elif spec == "sourcing_analyst":
        if d.cs or d.kind in ("l1-above-last", "pr-late"):
            plan.append(("compare_quotes", {"cs": d.cs.cs if d.cs else None, "key": d.key}))
        if d.kind == "rate-spread" and mat:
            plan.append(("rate_history", {"material": mat}))
        if vend:
            plan.append(("vendor_record", {"vendor": vend}))
    elif spec == "price_analyst":
        po = next((l.po for l in d.po_lines if l.pv), None)
        if po:
            plan.append(("pv_cost", {"po": po}))
        if d.kind == "pv-longlead":
            plan.append(("lookahead", {"project": pid}))
            idx = next((f.fact.split(", ")[2].split(" ")[0] for f in d.findings if f.fact.count(", ") >= 2), None)
            if idx:
                plan.append(("index_series", {"index": idx, "months": 6}))
    elif spec == "buyers_clerk":
        plan = [("get_item", {"key": d.key})]
    return plan


SAYS = {
    "site_planner": "where the {what} stands, and when the site needs it",
    "sourcing_analyst": "the quotes and the vendor's record",
    "price_analyst": "what the price clause owes and what waiting costs",
    "buyers_clerk": "the draft for the route the owner is most likely to choose",
    "inbox_analyst": "what the message is and whether its sender is who they claim to be",
}


async def run_case(rec: Recorder, key: str, asked_by: str | None = None) -> dict:
    """Work one case by code. Returns the run's stored fields (recommendation, verifier, status)."""
    from . import verify  # noqa: PLC0415

    with app_db.SessionLocal() as s:
        d = attention.item_detail(s, key)
        if d is None:
            rec.emit("run.failed", f"There is no case {key}.")
            return {"status": "failed"}
        rec.emit("run.started", f"Lookout reads the case: {d.title}", refs=[], key=key, mode="code")
        await asyncio.sleep(PACE)
        if d.tab == "trust":
            rec.emit("step.text", "This message was held before anyone read it. Nothing is drafted, paid or ordered from it: the controls are a person's to record.")
            rec.emit("run.finished", "Nothing to draft from a held message.", status="refused")
            return {"status": "refused", "recommendation": {"finding": "Held: nothing is drafted from this message.", "numbers": [], "drafted_by": "code"}}
        plan = PLANS.get(d.kind, ("site_planner", "buyers_clerk"))
        what = "PR" if d.pr_lines else "PO" if d.po_lines else "case"
        rec.emit("step.text", f"No model is connected here, so I work this case by code: {', '.join(SPECIALISTS[p].label for p in plan)}.")
        numbers: dict[str, Number] = {}
        handoffs: list[dict] = []
        routes = tools.routes_of(s, key, asked_by)
        kind, reason, ids = recommend(d, routes)
        drafts = []
        for n, spec in enumerate(plan, 1):
            child = f"{rec.run_id}.{n}"
            rec.emit("child.started", f"{SPECIALISTS[spec].label}: {SAYS.get(spec, '').format(what=what)}.", agent=spec, child_run_id=child)
            await asyncio.sleep(PACE)
            got = []
            if spec == "buyers_clerk":
                rec.emit("tool.called", "get_handoffs", agent=spec, tool="get_handoffs", args={}, gate="allowed")
                rec.emit("tool.result", f"{len(handoffs)} handoffs read", agent=spec, tool="get_handoffs", numbers=[])
                await asyncio.sleep(PACE)
                route = next((r for r in routes if r.kind == kind), None)
                if route is not None and route.leads_to in ("request", "internal_note", "note") and (route.to or route.leads_to == "note"):
                    tool = "draft_vendor_request" if route.leads_to == "request" else "draft_internal_note" if route.leads_to == "internal_note" else "stage_decision"
                    rec.emit("tool.called", tool, agent=spec, tool=tool, args={"route": kind}, gate="staged")
                    try:
                        from app.domain.actions.routes import draft_route  # noqa: PLC0415

                        owner = lookups.member_name(s, d.owner_ids[0]) if d.owner_ids else asked_by
                        out, how = draft_route(s, app_db.DB_PATH, key, kind, owner, run_id=rec.run_id)
                        drafts = out
                        for a in out:
                            rec.emit("action.staged", f"Drafted {('a letter to ' + (a.recipient or '')) if a.type == 'supplier_request' else ('a note to ' + (a.recipient or '')) if a.type == 'internal_note' else 'a note'} for {owner.split()[0]}'s signature ({how}).",
                                     agent=spec, action_id=a.action_id, state=a.state)
                    except Exception as e:  # noqa: BLE001  a route with nobody on file to write to: the run says so and goes on
                        rec.emit("tool.result", f"Not drafted: {getattr(e, 'message', str(e))}", agent=spec, tool=tool, numbers=[])
                else:
                    rec.emit("step.text", "The recommended route is a decision on record: it needs the owner's reason, so nothing is drafted.", agent=spec)
            else:
                for tool_name, args in _tool_plan(spec, d):
                    rec.emit("tool.called", tool_name, agent=spec, tool=tool_name, args={k: v for k, v in args.items() if v is not None}, gate="allowed")
                    fn = getattr(tools, tool_name)
                    res = fn(s, **{k: v for k, v in args.items() if v is not None})
                    nums = res.get("numbers", [])
                    for x in nums:
                        numbers[x.id] = x
                    got += [x.id for x in nums]
                    rec.emit("tool.result", f"{len(nums)} figure{'s' if len(nums) != 1 else ''}" + (f"; {res['error']}" if res.get("error") else ""), agent=spec, tool=tool_name,
                             numbers=[x.model_dump(mode="json") for x in nums[:24]])
                    await asyncio.sleep(PACE)
                lines = [f.fact for f in d.findings][: 3 if spec != "site_planner" else 4]
                for line in lines:
                    rec.emit("step.text", line, agent=spec)
                handoffs.append({"agent": spec, "findings": lines, "number_ids": got})
            rec.emit("child.finished", f"{SPECIALISTS[spec].label} handed off.", agent=spec, child_run_id=child)
            await asyncio.sleep(PACE)
        stake = numbers.get(f"item:{key}:at_stake")
        recommendation = {
            "finding": d.finding or d.title,
            "points": [{"label": "Waiting on", "text": d.waiting_on}, {"label": "Act by", "text": md(d.act_by) if d.act_by else "no date"}],
            "next_step": {"who": d.owner.split(" · ")[0], "what": next((r.label for r in routes if r.kind == kind), "Choose a route"), "by": d.act_by or ""},
            "numbers": [{"id": x.id, "value": str(x.value), "unit": x.unit, "name": x.name, "say": x.say} for x in numbers.values() if x.id in set(ids) | {f"item:{key}:at_stake"}],
            "open_questions": [u.model_dump() for u in d.unknowns][:12],
            "case_findings": [{"key": f.key, "meaning": f.meaning} for f in d.findings][:4],
            "recommended": {"kind": kind, "reason": reason, "number_ids": ids} if kind else None,
            "action_ids": [a.action_id for a in drafts],
            "drafted_by": "code",
        }
        if stake is not None:
            recommendation["at_stake"] = stake.say
        rec.emit("step.text", f"Recommended: {next((r.label for r in routes if r.kind == kind), kind)} ({reason}). The choice is {d.owner.split(' · ')[0]}'s.", agent="lookout")
        v = verify.check(s, d, recommendation, numbers, drafts, routes)
        rec.emit("verifier.result", f"{v['checked'] - len(v['failures'])} of {v['checked']} checks passed", agent="verifier", verifier=v)
        await asyncio.sleep(PACE)
        g = verify.review(s, d, recommendation, drafts, routes)
        recommendation["grade"] = g
        rec.emit("review.result", f"Reviewer {g['reviewer_score']}: {g['summary']}", agent="reviewer", grade=g)
        status = "ok" if not v["failures"] else "did_not_pass"
        rec.emit("run.finished", f"Worked by code in {rec.t_ms() / 1000:.1f} s · {len(drafts)} draft{'s' if len(drafts) != 1 else ''} · {v['checked'] - len(v['failures'])} of {v['checked']} checks · Reviewer {g['reviewer_score']}",
                 status=status)
        return {"status": status, "recommendation": recommendation, "verifier": v}


def as_decimal(x) -> Decimal:
    return Decimal(str(x))
