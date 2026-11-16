"""Insights (PLAN 13, MAPPING 10): Team, Projects, Pricing, Estimates and each member's Daily brief, computed by code from the records, the
PR-to-payment ladder and Today's cases. Read-only; every figure names the records it rests on.

Rules, in plain words:
- Team. One row per SCM member. The Head of SCM and the GM (`sees_all`) see everyone; anyone else sees only themselves. Listed by vertical, then
  name; never ranked or sorted by a figure. Turnaround is set only against the member's own vertical's median. Savings are the PO rate against
  the previous PO rate for that material at that plant, and against the project's budget rate, x the PO quantity, where that reference exists.
  Days waited are the ladder's own `held` days summed over the member's lines (PLAN 6.2: "the Team and Projects pages add these up").
  No counts of emails, hours or logins.
- Projects. Every project by vertical: open PRs, median PR -> PO days (a PR keyed in the day of its PO is left out), cancelled PR lines, PO value
  against the budget rate x quantity, the 3-month requirement against the fund sheets and against what MB51 received over as many full months
  just past, look-ahead items ordered, ₹ at risk on Today's cases, and the days its lines were held by Projects.
- Pricing. Per material: each project's last PO rate, each vendor's, the spread (highest over lowest site), the monthly average rate over twelve
  months, the last price against its budget and the latest quote, and PV lines against their index. A spread's reasons are not in the records:
  each site above the median says so and names the buyer of that site's lines, who could answer.
- Estimates. Per project and month: requirement, fund and received. A requirement is an over-ask when it exceeds the project's usual month
  (MB51 received value of the same materials, averaged over the full months before the sheet) by both the amount and the share the recipe's
  fund check uses; a repeat over-asker is over in more than one month. Accuracy is measured only on sheet months already past.
- Daily brief. The email a member would get each morning (never sent): their cases whose move is theirs, the oldest open PRs on their groups,
  expediting milestones due within two weeks, what waits on others, and vendors with late open lines.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, timedelta
from typing import get_args

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import lookups
from app.domain.attention import service as attention
from app.domain.cache import memo
from app.domain.common import AS_OF
from app.domain.fmt import count, days as days_word, dmy, en_in, inr, md, month_year
from app.domain.funds.model import FundLine
from app.domain.inbox.model import Message
from app.domain.indices import service as indices
from app.domain.insights.schema import (AgeBucket, Brief, BriefLine, BriefSection, CancelledEffort, CaseRow, EstimateMonth, EstimateRow, EstimatesResponse,
                                        Figure, FunctionWait, IndexPoint, MemberPage, MemberSummary, MonthRate, MoveRow, OldWait, OpenPr, PricingDetail, PricingResponse, PricingRow,
                                        ProjectPage, ProjectFigures, ProjectsResponse, PvItem, QuoteRow, RungCount, Saving, SitePrice, SpreadUnknown, TeamResponse,
                                        TopMaterial, Unresolved, VendorRate, VerticalCount, VerticalTurnaround, Workload)
from app.domain.lookahead.service import items as lookahead_items
from app.domain.milestones.model import Milestone
from app.domain.orders import service as orders
from app.domain.org import service as org
from app.domain.org.schema import OrgNode
from app.domain.orders.model import PoLine
from app.domain.phases.ladder import LABELS, ORDER, ladder
from app.domain.phases.schema import Ladder, Who
from app.domain.projects.model import ProjectAlias
from app.domain.prs import service as prs
from app.domain.prs.model import PrLine
from app.domain.quotes.model import ComparativeStatement, Quote
from app.domain.quotes.service import budget_rate
from app.domain.receipts.model import Receipt
from app.domain.requirements import service as req

TODAY = AS_OF.isoformat()
FUNCTIONS: list[str] = list(get_args(Who))  # the ladder's functions, SCM first
WINDOWS = (30, 90)  # "POs released in the last 30 / 90 days"
BRIEF_DAYS = 14  # milestones due within two weeks
BRIEF_LINES = 8  # lines a brief section shows; the rest are counted
AT_RISK = ("at stake", "claimed")  # the Today labels that are money at risk (not "covers", "if those sites paid the median", ...)
CANCELLED = ("deleted", "closed")


# --------------------------------------------------------------------------------------------------------------------------------- figures
def R(kind: str, id_: str) -> str:
    return f"{kind}:{id_}"


def money_fig(amount: float | None, rule: str, refs: list[str] | None = None, note: str | None = None) -> Figure:
    return Figure(value=round(amount, 2) if amount is not None else None, text=inr(amount) if amount is not None else "—", unit="inr", rule=rule, refs=refs or [], note=note)


def count_fig(n: int, noun: str, rule: str, refs: list[str] | None = None, plural: str | None = None, note: str | None = None) -> Figure:
    return Figure(value=n, text=count(n, noun, plural), unit="count", rule=rule, refs=refs or [], note=note)


def days_fig(n: float | None, rule: str, refs: list[str] | None = None, note: str | None = None, none: str = "—") -> Figure:
    if n is None:
        return Figure(value=None, text=none, unit="days", rule=rule, refs=refs or [], note=note)
    v = round(float(n), 1)
    word = ("1 day" if v == 1 else f"{en_in(v)} days") if v == int(v) else f"{v:g} days"
    return Figure(value=v, text=word, unit="days", rule=rule, refs=refs or [], note=note)


def pct_fig(share: float | None, rule: str, refs: list[str] | None = None, note: str | None = None, signed: bool = True) -> Figure:
    if share is None:
        return Figure(value=None, text="—", unit="pct", rule=rule, refs=refs or [], note=note)
    p = round(100 * share, 1)
    text = f"{'+' if signed and p > 0 else ''}{p:.0f}%" if abs(p) >= 10 else f"{'+' if signed and p > 0 else ''}{p:g}%"
    return Figure(value=p, text=text, unit="pct", rule=rule, refs=refs or [], note=note)


def median(xs: list[float]) -> float | None:
    return round(statistics.median(xs), 1) if xs else None


def months_back(n: int, end: str | None = None) -> list[str]:
    """The n months ending with `end` (YYYY-MM, the data date's month by default), oldest first."""
    y, m = int((end or TODAY)[:4]), int((end or TODAY)[5:7])
    out = []
    for _ in range(n):
        out.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


def month_past(ym: str) -> bool:
    return req.month_end(ym) < TODAY


@memo
def period(session: Session) -> tuple[str, str]:
    """(first date in the exports, "1 Nov 2025 – 20 Oct 2026"): the window every Team and Projects figure covers."""
    firsts = [l.doc_date for l in orders.all_lines(session).values()] + [l.created for l in prs.all_lines(session).values()]
    first = min(firsts) if firsts else TODAY
    return first, f"{dmy(first)} – {dmy(TODAY)}"


# ------------------------------------------------------------------------------------------------------------------- the ladders, once each
@memo
def ladders(session: Session) -> dict[str, Ladder]:
    """Every purchase's ladder, once: one per PR line (it carries its PO), and one per PO line with no PR line on file (an emergency buy).
    Keyed by subject ("pr_line:<id>", "po_line:<id>")."""
    pr = prs.all_lines(session)
    out: dict[str, Ladder] = {}
    for l in pr.values():
        lad = ladder(session, pr_line_id=l.id)
        if lad:
            out[R("pr_line", l.id)] = lad
    for l in orders.all_lines(session).values():
        if not l.pr_line_id or l.pr_line_id not in pr:
            lad = ladder(session, po_line_id=l.id)
            if lad:
                out[R("po_line", l.id)] = lad
    return out


@memo
def subjects(session: Session) -> dict[str, dict]:
    """{ladder key: whose line it is (the PR line's buyer, else the PO line's), its project, its words and its PR status}."""
    pr, po = prs.all_lines(session), orders.all_lines(session)
    out = {}
    for k in ladders(session):
        kind, id_ = k.split(":", 1)
        l = pr.get(id_) if kind == "pr_line" else po.get(id_)
        out[k] = dict(buyer=l.buyer_id, project=l.project_id, text=l.short_text or "", status=l.status if kind == "pr_line" else "po")
    return out


def where_now(lad: Ladder, status: str) -> tuple[str, str | None, int | None]:
    """(the rung a line waits for, whose move it is, days waiting); a line not waiting stands at 'closed', 'cancelled' or its last rung done."""
    now = next((r for r in lad.rungs if r.state == "now"), None)
    if now:
        return now.key, now.held_by, now.days
    if any(r.key == "closed" and r.state == "done" for r in lad.rungs):
        return "closed", None, None
    if status in CANCELLED:
        return "cancelled", None, None
    last = [r for r in lad.rungs if r.state == "done" and r.key != "needed"]
    return (last[-1].key if last else "needed"), None, None


# ----------------------------------------------------------------------------------------------------------------------- shared indexes
@memo
def _quotes_by_line(session: Session) -> dict[str, list[Quote]]:
    out: dict[str, list[Quote]] = defaultdict(list)
    for q in session.scalars(select(Quote).where(Quote.pr_line_id.is_not(None))):
        out[q.pr_line_id].append(q)
    return dict(out)


@memo
def _cs_by_line(session: Session) -> dict[str, ComparativeStatement]:
    out = {}
    for s in session.scalars(select(ComparativeStatement)):
        for x in (s.pr_line_ids or "").split(","):
            if x:
                out[x] = s
    return out


@memo
def _quotes_by_material(session: Session) -> dict[str, list[Quote]]:
    """Priced quotes per material, newest first (quote date, else the RFQ date). A quote read from a message the trust check held is left out:
    nobody may act on it."""
    held = {m.id for m in session.scalars(select(Message).where(Message.trust == "blocked"))}
    out: dict[str, list[Quote]] = defaultdict(list)
    for q in session.scalars(select(Quote).where(Quote.rate.is_not(None), Quote.material.is_not(None))):
        if q.message_id and q.message_id in held:
            continue
        out[q.material].append(q)
    for v in out.values():
        v.sort(key=lambda q: (q.quote_date or q.rfq_sent or "", q.id), reverse=True)
    return dict(out)


def quote_rate(session: Session, q: Quote) -> float | None:
    """A quote's rate per the material's base unit (a quote in bags converted at the master's bags per tonne); None in any other unit."""
    m = lookups.materials(session).get(q.material or "")
    if q.rate is None or m is None:
        return None
    if not q.uom or q.uom == m.base_uom:
        return q.rate
    if q.uom == m.alt_uom and m.alt_per_base:
        return q.rate * m.alt_per_base
    return None


def _quote_fig(session: Session, q: Quote, what: str) -> Figure | None:
    r = quote_rate(session, q)
    if r is None:
        return None
    when = q.quote_date or q.rfq_sent
    conv = f"; {inr(q.rate)} per {q.uom} as quoted" if q.uom and r != q.rate else ""
    return Figure(value=round(r, 2), text=inr(r), unit="rate", rule=f"{what} ({q.vendor_name}, {'mail' if q.source == 'mail' else 'CS tracker'}, {md(when, True) if when else 'undated'}{conv})",
                  refs=[R("quote", q.id)])


@memo
def _receipts(session: Session) -> list[Receipt]:
    return [r for r in session.scalars(select(Receipt)) if r.posting_date <= TODAY]


def turnaround(session: Session, l: PrLine) -> int | None:
    """PR release (else creation) to the PO's date, as the PR record reads it; None when the PR was keyed in the PO's day or is not converted."""
    po = orders.all_lines(session).get(l.po_line_id or "")
    if po is None or "same_day_po" in (l.flags or ""):
        return None
    return (date.fromisoformat(po.doc_date) - date.fromisoformat(l.released or l.created)).days


def age(l: PrLine) -> int:
    return (AS_OF - date.fromisoformat(l.released or l.created)).days


@memo
def _tats(session: Session) -> list[tuple[str, str | None, str | None, int]]:
    """(pr line, buyer, vertical, days) for every converted PR line that measures something."""
    out = []
    for l in prs.all_lines(session).values():
        t = turnaround(session, l)
        if t is not None:
            out.append((l.id, l.buyer_id, lookups.vertical_of_project(session, l.project_id), t))
    return out


@memo
def _prev_rate(session: Session) -> dict[str, PoLine | None]:
    """{PO line: the newest PO line for the same material at the same plant dated before it}: the previous price a buyer would compare with."""
    groups: dict[tuple, list[PoLine]] = defaultdict(list)
    for l in orders.all_lines(session).values():
        if l.material:
            groups[(l.material, l.plant)].append(l)
    out: dict[str, PoLine | None] = {}
    for ls in groups.values():
        ls.sort(key=lambda l: (l.doc_date, l.id))
        best, i = None, 0
        for l in ls:
            while i < len(ls) and ls[i].doc_date < l.doc_date:
                best = ls[i]
                i += 1
            out[l.id] = best
    return out


def _target(vertical: str | None) -> int | None:
    return (lookups.answers().get("turnaround_target_days") or {}).get(vertical or "")


# ------------------------------------------------------------------------------------------------------------------------------------ Team
def _verticals(b) -> list[str]:
    return [v for v in (b.verticals or "").split(",") if v]


def _chart(session: Session) -> dict[str, OrgNode]:
    """The organisation chart as it stands now (the organogram with the edits made on the Organisation page), by box id."""
    return {p.id: p for p in org.chart(session.get_bind().url.database).people}


def team_of(nodes: dict[str, OrgNode], member_id: str) -> str:
    """Whose team the chart puts a member in: the lead under the head they report up to; 'head' for the head; 'none' off the chart."""
    n = nodes.get(member_id)
    if n is None:
        return "none"
    if n.reports_to is None:
        return "head"
    seen = set()
    while n.reports_to in nodes and nodes[n.reports_to].reports_to is not None and n.id not in seen:
        seen.add(n.id)
        n = nodes[n.reports_to]
    return n.id


def team_order(session: Session, nodes: dict[str, OrgNode] | None = None) -> list[str]:
    """Member ids as the organogram draws them: the head, then each lead followed by their team, everyone in the chart's order under their lead.
    Never by a figure. Members the chart does not show come last, by name."""
    nodes = nodes if nodes is not None else _chart(session)
    kids: dict[str | None, list[OrgNode]] = defaultdict(list)
    for n in sorted(nodes.values(), key=lambda x: x.position):
        kids[n.reports_to].append(n)
    seq: list[str] = []
    todo = list(reversed(kids[None]))
    while todo:
        n = todo.pop()
        seq.append(n.id)
        todo.extend(reversed(kids[n.id]))
    t = lookups.team(session)
    by_box = {n.member_id: i for i, n in enumerate(nodes[x] for x in seq) if n.member_id}
    return sorted(t, key=lambda m: (by_box.get(m, len(seq)), t[m].name))


def org_fields(session: Session, member_id: str, nodes: dict[str, OrgNode] | None = None) -> dict:
    """What the chart says of a member, for their row and page: designation, whom they report to, desk, work, and whose team they are in."""
    nodes = nodes if nodes is not None else _chart(session)
    n = next((x for x in nodes.values() if x.member_id == member_id), None)
    g = team_of(nodes, n.id) if n else "none"
    lead = nodes.get(g)
    up = nodes.get(n.reports_to or "") if n else None
    return dict(designation=n.designation if n else None, designation_full=n.designation_full if n else None, reports_to=up.member_id if up else None,
                reports_to_name=up.name if up else None, category=n.category if n else None, responsibilities=n.responsibilities if n else None,
                portfolio=n.portfolio if n else None, group=g,
                group_name="Head of SCM" if g == "head" else lead.name if lead and lead.name else "Not on the organogram",
                group_note=(n.designation if g == "head" and n else lead.portfolio if lead else None))


def see_all_words(session: Session) -> str:
    """'<name> (<role>) and <name> (<role>)': the members who see every Team page, as the team table names them."""
    xs = [f"{b.name} ({b.role})" for b in lookups.team(session).values() if b.sees_all]
    return " and ".join(xs) or "nobody"


def who_sees(session: Session, member_id: str) -> str:
    """Who may see a member's Team page, in words: the member, everyone they report up to, and whoever sees every page."""
    t = lookups.team(session)
    b = t[member_id]
    chain, up = [], lookups.lead_of(session, b)
    while up is not None and not up.sees_all and up.name not in chain:
        chain.append(up.name)
        up = lookups.lead_of(session, up)
    xs = [b.name.split()[0], *chain, see_all_words(session)]
    return ", ".join(xs[:-1]) + " and " + xs[-1] if len(xs) > 1 else xs[0]


def can_see(session: Session, viewer: str | None, member_id: str) -> bool:
    """Whether the viewer may see a member's Team page: the Head sees everyone, a lead their own team (everyone who reports up to them, as the
    team table has it), anyone else only themselves. No viewer: the API answers but says so (the screen always names one)."""
    if viewer is None:
        return True
    v = lookups.member_of(session, viewer)
    return bool(v and (v.sees_all or v.id == member_id or member_id in lookups.under(session, v.id)))


@memo
def _member_lines(session: Session) -> tuple[dict[str, list[PrLine]], dict[str, list[PoLine]]]:
    pr: dict[str, list[PrLine]] = defaultdict(list)
    po: dict[str, list[PoLine]] = defaultdict(list)
    for l in prs.all_lines(session).values():
        if l.buyer_id:
            pr[l.buyer_id].append(l)
    for l in orders.all_lines(session).values():
        if l.buyer_id:
            po[l.buyer_id].append(l)
    return dict(pr), dict(po)


def _saving(lines: list[PoLine], ref_rate, what: str, note: str) -> Saving:
    """Σ (reference rate - PO rate) x PO quantity over the lines with a reference; positive is bought below it."""
    below, above, refs_b, refs_a = 0.0, 0.0, [], []
    for l in lines:
        r = ref_rate(l)
        if r is None:
            continue
        s = (r - l.rate_base) * l.qty_base
        if s >= 0:
            below += s
            refs_b.append(R("po_line", l.id))
        else:
            above += -s
            refs_a.append(R("po_line", l.id))
    rule = f"Σ ({what} − the PO rate) × PO quantity, over the member's PO lines where {note}"
    n = len(refs_b) + len(refs_a)
    return Saving(net=money_fig(below - above if n else None, rule, refs_b + refs_a, note=f"on {count(n, 'line')} where {note}"),
                  below=money_fig(below, f"what the lines bought below {what} saved", refs_b, note=count(len(refs_b), "line")),
                  above=money_fig(above, f"what the lines bought above {what} cost", refs_a, note=count(len(refs_a), "line")), lines=n, of_lines=len(lines))


@memo
def member_page(session: Session, member_id: str) -> MemberPage | None:
    b = lookups.team(session).get(member_id)
    if b is None:
        return None
    pr_all, po_all = _member_lines(session)
    pr, po = pr_all.get(b.id, []), po_all.get(b.id, [])
    first, period_text = period(session)
    lads, subj = ladders(session), subjects(session)
    mine = {k: lad for k, lad in lads.items() if subj[k]["buyer"] == b.id}

    # open PRs and their age, against the vertical's own turnaround target
    open_pr = sorted((l for l in pr if l.status == "open"), key=lambda l: (-age(l), l.id))
    buckets: dict[str, list[str]] = {"within": [], "past": [], "twice": [], "none": []}
    for l in open_pr:
        t = _target(lookups.vertical_of_project(session, l.project_id))
        buckets["none" if t is None else "within" if age(l) <= t else "past" if age(l) <= 2 * t else "twice"].append(R("pr_line", l.id))
    rule_age = "open PR lines by days since release (else creation), against the turnaround target of the project's vertical (answers.yaml)"
    ageing = [AgeBucket(label=lab, lines=count_fig(len(buckets[k]), "line", rule_age, buckets[k])) for k, lab in
              (("within", "Within the vertical's target"), ("past", "Past the target"), ("twice", "Past twice the target"), ("none", "No project, so no target"))]
    oldest = []
    for l in open_pr[:12]:
        lad = lads.get(R("pr_line", l.id))
        rung, who, _d = where_now(lad, l.status) if lad else (None, None, None)
        qs = _quotes_by_line(session).get(l.id, [])
        oldest.append(OpenPr(ref=R("pr_line", l.id), pr=l.pr_no, item=l.item, text=l.short_text or "", project=l.project_id,
                             project_name=lookups.project_name(session, l.project_id) or None, age_days=age(l), since=l.released or l.created, needed_by=l.needed_by,
                             rfq_sent=min((q.rfq_sent for q in qs if q.rfq_sent), default=None), quotes_in=len({q.record_id for q in qs if q.rate}),
                             waiting_on=who, rung=LABELS.get(rung or "", rung)))

    # POs released in the last 30 and 90 days
    win = {}
    for d in WINDOWS:
        cut = (AS_OF - timedelta(days=d)).isoformat()
        ls = [l for l in po if cut < l.doc_date <= TODAY]
        refs = [R("po_line", l.id) for l in ls]
        win[d] = (count_fig(len({l.po_no for l in ls}), "PO", f"POs (distinct numbers) dated in the {d} days to {dmy(TODAY)} on the member's purchasing groups", refs),
                  money_fig(sum(l.value for l in ls), f"Σ PO line value of those POs (ME2N)", refs))

    # PR -> PO turnaround: the member's median on each vertical against that vertical's median
    tats = _tats(session)
    tat_rows = []
    for v in [v for v in lookups.VERTICALS if any(t[1] == b.id and t[2] == v for t in tats)]:
        theirs = [t for t in tats if t[1] == b.id and t[2] == v]
        every = [t for t in tats if t[2] == v]
        tat_rows.append(VerticalTurnaround(
            vertical=v, name=lookups.VERTICAL_NAMES.get(v, v),
            mine=days_fig(median([t[3] for t in theirs]), f"median days from PR release to PO on the member's {count(len(theirs), 'line')} in {lookups.VERTICAL_NAMES.get(v, v)} projects (same-day PRs left out)",
                          [R("pr_line", t[0]) for t in theirs]),
            vertical_median=days_fig(median([t[3] for t in every]), f"median over every buyer's {count(len(every), 'line')} in {lookups.VERTICAL_NAMES.get(v, v)} projects (same-day PRs left out)",
                                     [R("pr_line", t[0]) for t in every])))

    # savings against the previous price at the plant and against the project's budget rate
    prev = _prev_rate(session)
    s_last = _saving(po, lambda l: prev[l.id].rate_base if prev.get(l.id) else None, "the previous PO rate for the material at the plant", "a previous rate exists")

    def _budget(l: PoLine) -> float | None:
        br = budget_rate(session, l.project_id, l.material) if l.project_id and l.material else None
        return br.rate if br else None

    s_budget = _saving(po, _budget, "the project's budget rate", "a budget rate exists")

    # effort on PR lines later cancelled (deleted or short-closed)
    gone = [l for l in pr if l.status in CANCELLED]
    rfq = [l for l in gone if _cs_by_line(session).get(l.id) or any(q.rfq_sent for q in _quotes_by_line(session).get(l.id, []))]
    css = {s.cs_no: s for s in (_cs_by_line(session).get(l.id) for l in gone) if s}
    quotes = sum(len({q.record_id for q in _quotes_by_line(session).get(l.id, []) if q.rate}) for l in gone)
    gone_refs = [R("pr_line", l.id) for l in gone]
    cancelled = CancelledEffort(
        lines=count_fig(len(gone), "line", "PR lines on the member's groups later deleted or short-closed (ME5A)", gone_refs), prs=len({l.pr_no for l in gone}),
        rfq_lines=count_fig(len(rfq), "line", "of them, lines an RFQ went out on (the RFQ/CS tracker)", [R("pr_line", l.id) for l in rfq]),
        enquiries=count_fig(len(css), "enquiry", "comparative statements behind those lines", [R("cs", c) for c in css], plural="enquiries"),
        vendors_asked=count_fig(sum(s.vendors_asked for s in css.values()), "vendor", "vendors asked to quote on those enquiries", [R("cs", c) for c in css]),
        quotes=count_fig(quotes, "quote", "priced quotes received on those lines (a vendor's price on a line)", [R("pr_line", l.id) for l in gone if any(q.rate for q in _quotes_by_line(session).get(l.id, []))]))

    # days items waited, by function: the ladders' own held days, summed
    waits = []
    for f in FUNCTIONS:
        held = [(k, lad.held.get(f, 0)) for k, lad in mine.items() if lad.held.get(f, 0) > 0]
        now = [k for k, lad in mine.items() if lad.waiting_on == f]
        total = sum(d for _, d in held)
        waits.append(FunctionWait(
            function=f, days=days_fig(total, f"Σ days the ladder attributes to {f} over the member's lines (PLAN 6.2)", [k for k, _ in held], none="0 days"),
            per_line=days_fig(total / len(held) if held else None, f"those days over the {count(len(held), 'line')} {f} held", [k for k, _ in held]),
            lines=len(held), now=count_fig(len(now), "line", f"the member's lines whose move is {f}'s on {dmy(TODAY)}", now)))
    w_scm = next(w for w in waits if w.function == "SCM")
    other = [w for w in waits if w.function != "SCM"]
    waited_others = days_fig(sum(w.days.value or 0 for w in other), "Σ days held by Projects, Vendor, QA, Finance and Management over the member's lines",
                             sorted({r for w in other for r in w.days.refs}), none="0 days")
    n = len(mine)
    a_line = lambda days, who, refs: days_fig(days / n if n else None, f"days held by {who} over the member's lines, divided by its {count(n, 'line')} with a ladder", refs)  # noqa: E731
    waited_scm_line = a_line(w_scm.days.value or 0, "SCM", w_scm.days.refs)
    waited_others_line = a_line(waited_others.value or 0, "Projects, Vendor, QA, Finance and Management", waited_others.refs)

    # workload
    open_po = [l for l in po if l.status == "open"]
    cases = attention.what_needs_attention(session, owner=b.id)
    on_you = [c for c in cases if c.waiting_on == "SCM"]
    workload = Workload(
        open_pr_lines=count_fig(len(open_pr), "line", "open PR lines on the member's purchasing groups", [R("pr_line", l.id) for l in open_pr]),
        open_po_lines=count_fig(len(open_po), "line", "PO lines on the member's groups not yet fully received", [R("po_line", l.id) for l in open_po]),
        open_po_value=money_fig(sum(l.open_value for l in open_po), "Σ open quantity x rate of those lines", [R("po_line", l.id) for l in open_po]),
        cases=count_fig(len(cases), "case", "Today's cases the member owns", [R("item", c.key) for c in cases]),
        cases_on_you=count_fig(len(on_you), "case", "of them, cases whose move is SCM's", [R("item", c.key) for c in on_you]))

    return MemberPage(
        id=b.id, name=b.name, initials=b.initials, role=b.role, groups=[x for x in (b.purchasing_groups or "").split(",") if x], verticals=_verticals(b),
        group="", group_name="", email=b.email,
        open_prs=count_fig(len(open_pr), "line", "open PR lines on the member's purchasing groups (ME5A)", [R("pr_line", l.id) for l in open_pr]),
        oldest_open=days_fig(age(open_pr[0]) if open_pr else None, "days since the oldest open PR line was released (else raised)",
                             [R("pr_line", open_pr[0].id)] if open_pr else [], none="none open"),
        pos_30=win[30][0], pos_30_value=win[30][1], pos_90=win[90][0], pos_90_value=win[90][1], turnaround=tat_rows,
        saving_last=s_last.net, saving_budget=s_budget.net, cancelled=cancelled.lines, cancelled_quotes=cancelled.quotes,
        waited_scm=w_scm.days, waited_others=waited_others, waited_scm_line=waited_scm_line, waited_others_line=waited_others_line, workload=workload, ageing=ageing, oldest=oldest, saving_last_detail=s_last, saving_budget_detail=s_budget,
        cancelled_detail=cancelled, waits=waits, period=period_text, as_of=TODAY)


def summary(p: MemberPage) -> MemberSummary:
    return MemberSummary(**{k: getattr(p, k) for k in MemberSummary.model_fields})


def member(session: Session, member_id: str) -> MemberPage | None:
    """A member's page with what the organisation chart says of them now (the figures are read once per build; the chart can change any time)."""
    page = member_page(session, member_id)
    return page.model_copy(update=org_fields(session, member_id)) if page else None


def team(session: Session, viewer: str | None) -> TeamResponse:
    """The Team page: who the viewer may see, as the organogram draws the team."""
    v = lookups.member_of(session, viewer) if viewer else None
    nodes = _chart(session)
    order = team_order(session, nodes)
    seers = see_all_words(session)
    mine = [i for i in order if v and i in lookups.under(session, v.id)]
    if viewer is None:
        ids, scope, note = order, "all", f"No viewer named: every member is listed. On screen, only {seers} see everyone; a lead sees their team, each member their own page."
    elif v is None:
        ids, scope, note = [], "none", f"{viewer} is not a member of the SCM team, so no Team page is shown."
    elif v.sees_all:
        ids, scope, note = order, "all", f"As {v.role} you see every member's page. Listed as the organogram draws the team; nothing here is ranked."
    elif mine:
        ids, scope, note = [v.id, *mine], "team", (f"You see your own page and your team's: the {count(len(mine), 'person', 'people')} who report to you. "
                                                    f"Only {seers} {'sees' if ' and ' not in seers else 'see'} every member's; nobody is ranked.")
    else:
        ids, scope, note = [v.id], "self", f"You see your own page. Your lead and {seers} see it too; nobody is ranked."
    return TeamResponse(viewer=v.id if v else None, viewer_name=v.name if v else None, scope=scope, note=note, order="the organogram's order",
                        period=period(session)[1], as_of=TODAY,
                        members=[summary(member_page(session, i)).model_copy(update=org_fields(session, i, nodes)) for i in ids])


# -------------------------------------------------------------------------------------------------------------------------------- Projects
@memo
def sheet_months(session: Session) -> list[str]:
    """The months the 3-month requirement and fund sheets cover (the next three from the data date when none is on file)."""
    ms = {r.month for r in req.all_lines(session)} | {f.month for f in _fund_lines(session)}
    return sorted(ms) or req.months_ahead()


def recent_months(session: Session) -> list[str]:
    """As many full months as the sheets cover, just before the data date's month: the Projects page reads what was received over them."""
    n = len(sheet_months(session))
    return months_back(n, months_back(2)[0])


@memo
def _fund_lines(session: Session) -> list[FundLine]:
    return list(session.scalars(select(FundLine).order_by(FundLine.month, FundLine.id)))


@memo
def _sheet_materials(session: Session) -> dict[str, set[str]]:
    """{project: the material codes its requirement rows stand for}."""
    out: dict[str, set[str]] = defaultdict(set)
    for r in req.all_lines(session):
        if r.project_id:
            out[r.project_id] |= {c for c in (r.material_codes or "").split(",") if c}
    return dict(out)


def _received(session: Session, pid: str, months: list[str]) -> tuple[dict[str, float], dict[str, list[str]]]:
    """MB51 net received value by month for a project: of the materials its requirement rows name, or every material when no sheet covers it."""
    mats = _sheet_materials(session).get(pid)
    val: dict[str, float] = defaultdict(float)
    refs: dict[str, list[str]] = defaultdict(list)
    for r in _receipts_of(session).get(pid, []):
        m = r.posting_date[:7]
        if m in months and (not mats or r.material in mats):
            val[m] += r.amount or 0.0
            refs[m].append(R("po_line", r.po_line_id) if r.po_line_id else R("receipt", r.id))
    return dict(val), {k: list(dict.fromkeys(v)) for k, v in refs.items()}


@memo
def _receipts_of(session: Session) -> dict[str, list[Receipt]]:
    out: dict[str, list[Receipt]] = defaultdict(list)
    for r in _receipts(session):
        if r.project_id:
            out[r.project_id].append(r)
    return dict(out)


def _received_rule(session: Session, pid: str) -> str:
    return ("MB51 net received value (101 less 102 and 122) of the materials its requirement rows name" if _sheet_materials(session).get(pid)
            else "MB51 net received value (101 less 102 and 122), every material: no requirement sheet covers this project")


@memo
def _cases(session: Session) -> list:
    return attention.what_needs_attention(session)


def _stake(c) -> float | None:
    a = c.at_stake
    return float(a.amount) if a is not None and hasattr(a, "amount") and hasattr(a, "currency") and c.at_stake_label in AT_RISK else None


def _case_row(c, pid: str | None = None) -> CaseRow:
    a = c.at_stake
    amount = float(a.amount) if a is not None and hasattr(a, "currency") else None
    return CaseRow(key=c.key, title=c.title, tab=c.tab, waiting_on=c.waiting_on, owner=c.owner, act_by=c.act_by,
                   at_stake=money_fig(amount, c.at_stake_rule or c.at_stake_label, [R("item", c.key)]) if amount is not None else None,
                   label=c.at_stake_label, at_risk=_stake(c) is not None, shared=bool(pid) and len({p.id for p in c.projects} - {pid}) > 0)


@memo
def project_rows(session: Session) -> dict[str, ProjectFigures]:
    pr_by: dict[str, list[PrLine]] = defaultdict(list)
    po_by: dict[str, list[PoLine]] = defaultdict(list)
    for l in prs.all_lines(session).values():
        if l.project_id:
            pr_by[l.project_id].append(l)
    for l in orders.all_lines(session).values():
        if l.project_id:
            po_by[l.project_id].append(l)
    lad_by: dict[str, list[tuple[str, Ladder]]] = defaultdict(list)
    subj = subjects(session)
    for k, lad in ladders(session).items():
        if subj[k]["project"]:
            lad_by[subj[k]["project"]].append((k, lad))
    months, past = sheet_months(session), recent_months(session)
    names = {p.id: p.name for p in lookups.projects(session).values()}
    la = lookahead_items(session)
    cases = _cases(session)
    order = {v: i for i, v in enumerate(lookups.VERTICALS)}
    out: dict[str, ProjectFigures] = {}
    for p in sorted(lookups.projects(session).values(), key=lambda p: (order.get(p.vertical, 9), p.name)):
        pr, po, lads = pr_by.get(p.id, []), po_by.get(p.id, []), lad_by.get(p.id, [])
        vname = lookups.VERTICAL_NAMES.get(p.vertical, p.vertical)
        open_pr = [l for l in pr if l.status == "open"]
        tats = [(l.id, t) for l in pr for t in [turnaround(session, l)] if t is not None]
        gone = [l for l in pr if l.status in CANCELLED]
        with_budget = [(l, b) for l in po for b in [budget_rate(session, p.id, l.material)] if b and l.material]
        all_value = sum(l.value for l in po)
        b_refs = [R("po_line", l.id) for l, _ in with_budget]
        reqs = [r for r in req.lines_for(session, p.id) if r.month in months]
        funds = [f for f in _fund_lines(session) if p.id in (f.project_ids or "").split(",") and f.month in months]
        shared = sorted({x for f in funds for x in (f.project_ids or "").split(",") if x and x != p.id})
        rec, rec_refs = _received(session, p.id, past)
        items = [i for i in la if i.project == p.id]
        ordered = [i for i in items if i.ordered]
        mine_cases = [c for c in cases if p.id in {x.id for x in c.projects}]
        alone = [c for c in mine_cases if len({x.id for x in c.projects}) == 1 and _stake(c) is not None]
        with_others = [c for c in mine_cases if len({x.id for x in c.projects}) > 1 and _stake(c) is not None]
        held = [(k, lad.held.get("Projects", 0)) for k, lad in lads if lad.held.get("Projects", 0) > 0]
        waiting = [(k, lad.days_waiting or 0) for k, lad in lads if lad.waiting_on == "Projects"]
        out[p.id] = ProjectFigures(
            id=p.id, name=p.name, vertical=p.vertical, vertical_name=vname, stage=p.stage, plants=lookups.plants_of(session).get(p.id, []), head=p.head_name, planner=p.planner_name,
            open_prs=count_fig(len(open_pr), "line", "open PR lines on the project (ME5A)", [R("pr_line", l.id) for l in open_pr]),
            turnaround=days_fig(median([t for _, t in tats]), f"median days from PR release to PO over {count(len(tats), 'converted line')} (a PR keyed in the day of its PO is left out)",
                                [R("pr_line", i) for i, _ in tats], none="none converted"),
            target_days=_target(p.vertical),
            cancelled=count_fig(len(gone), "line", "PR lines deleted or short-closed (ME5A)", [R("pr_line", l.id) for l in gone]),
            budget=money_fig(sum(l.qty_base * b.rate for l, b in with_budget) if with_budget else None, "Σ PO quantity x the project's budget rate (BOQ / tender), on lines with one", b_refs,
                             note=None if with_budget else "no budget rate on file for what it bought"),
            actual=money_fig(sum(l.value for l, _ in with_budget) if with_budget else None, "Σ PO value on the same lines (ME2N)", b_refs),
            budget_cover=pct_fig(sum(l.value for l, _ in with_budget) / all_value if all_value else None, "share of the project's PO value that has a budget rate", b_refs, signed=False),
            requirement=money_fig(sum(r.amount or 0 for r in reqs) if reqs else None, f"Σ quantity x rate on the 3-month requirement sheets, {month_year(months[0])} – {month_year(months[-1])}",
                                  [R("requirement", r.id) for r in reqs], note=None if reqs else "no requirement sheet covers this project"),
            fund=money_fig(sum(f.amount for f in funds) if funds else None, f"Σ the fund sheets' lines for the project, {month_year(months[0])} – {month_year(months[-1])}",
                           [R("fund_line", str(f.id)) for f in funds],
                           note=(f"a column shared with {', '.join(names.get(x, x) for x in shared)}: shown whole" if shared else None) if funds else "not on the fund sheets"),
            received=money_fig(sum(rec.values()), f"{_received_rule(session, p.id)}, {month_year(past[0])} – {month_year(past[-1])}", sorted({r for v in rec_refs.values() for r in v})),
            longlead=Figure(value=len(ordered) if items else None, text=f"{len(ordered)} of {len(items)} ordered" if items else "—", unit="count",
                            rule="look-ahead long-lead items with a PO on file for the material on this project", refs=[R("lookahead", str(i.id)) for i in items],
                            note=None if items else "no long-lead items on the look-ahead"),
            longlead_open=money_fig(sum(i.value for i in items if not i.ordered) if items else None, "Σ value of the look-ahead items not yet ordered",
                                    [R("lookahead", str(i.id)) for i in items if not i.ordered]),
            at_risk=money_fig(sum(_stake(c) for c in alone), "Σ ₹ at stake on Today's cases about this project alone", [R("item", c.key) for c in alone]),
            at_risk_shared=money_fig(sum(_stake(c) for c in with_others), "Σ ₹ at stake on Today's cases this project shares with others, each counted in full",
                                     [R("item", c.key) for c in with_others]),
            held_by_projects=days_fig(sum(d for _, d in held), "Σ days the ladder attributes to Projects over the project's lines (release, spec queries, MFC held for site)",
                                      [k for k, _ in held], note=f"over {count(len(held), 'line')}" if held else None, none="0 days"),
            waiting_on_projects=count_fig(len(waiting), "line", f"its lines whose move is Projects' on {dmy(TODAY)}, {en_in(sum(d for _, d in waiting))} days between them",
                                          [k for k, _ in waiting]))
    return out


def projects(session: Session) -> ProjectsResponse:
    rows = list(project_rows(session).values())
    months, past = sheet_months(session), recent_months(session)
    return ProjectsResponse(
        as_of=TODAY, period=period(session)[1], sheet_months=months, received_months=past,
        verticals=[VerticalCount(id=v, name=lookups.VERTICAL_NAMES[v], projects=sum(1 for r in rows if r.vertical == v)) for v in lookups.VERTICALS],
        rows=rows,
        notes=[f"Requirement and fund cover {month_year(months[0])} – {month_year(months[-1])}; received covers the same number of full months just past "
               f"({month_year(past[0])} – {month_year(past[-1])}), so the three read side by side.",
               "A fund column that covers several projects is shown whole on each of them; it is never split by guess.",
               "₹ at risk counts Today's cases whose figure is money at stake or claimed; a case on several projects is counted in full on each, apart."])


def project_page(session: Session, pid: str) -> ProjectPage | None:
    row = project_rows(session).get(pid)
    if row is None:
        return None
    p = lookups.projects(session)[pid]
    subj = subjects(session)
    lads = [(k, lad) for k, lad in ladders(session).items() if subj[k]["project"] == pid]
    at: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
    waits = []
    for k, lad in lads:
        rung, who, d = where_now(lad, subj[k]["status"])
        at[rung].append((k, who))
        if who and d is not None:
            waits.append(OldWait(ref=k, text=subj[k]["text"], rung=LABELS.get(rung, rung), waiting_on=who, since=lad.waiting_since, days=d))
    keys = [k for k in ORDER if k != "needed"] + ["cancelled"]
    label = {**LABELS, "cancelled": "Cancelled"}
    ladder_rows = []
    for key in keys:
        xs = at.get(key, [])
        if not xs:
            continue
        who: dict[str, int] = defaultdict(int)
        for _, w in xs:
            if w:
                who[w] += 1
        wait = [k for k, w in xs if w]
        stand = [k for k, w in xs if not w]
        ladder_rows.append(RungCount(
            key=key, label=label[key], who=dict(who),
            waiting=count_fig(len(wait), "line", f"the project's lines waiting for this rung on {dmy(TODAY)}", wait) if wait else None,
            standing=count_fig(len(stand), "line", f"the project's lines whose last step is this rung, nothing waiting on anyone" if key not in ("closed", "cancelled")
                               else ("closed: received, invoiced and paid" if key == "closed" else "PR lines deleted or short-closed before a PO"), stand) if stand else None))
    move = []
    for f in FUNCTIONS:
        xs = [(k, lad.days_waiting or 0) for k, lad in lads if lad.waiting_on == f]
        if xs:
            move.append(MoveRow(function=f, lines=count_fig(len(xs), "line", f"the project's lines whose move is {f}'s on {dmy(TODAY)}", [k for k, _ in xs]),
                                days=days_fig(sum(d for _, d in xs), f"Σ days those lines have waited on {f} so far", [k for k, _ in xs], none="0 days")))
    by_mat: dict[str, list[PoLine]] = defaultdict(list)
    for l in orders.all_lines(session).values():
        if l.project_id == pid and l.material:
            by_mat[l.material].append(l)
    mats = lookups.materials(session)
    top = sorted(by_mat.items(), key=lambda kv: -sum(l.value for l in kv[1]))[:8]
    cases = [_case_row(c, pid) for c in _cases(session) if pid in {x.id for x in c.projects}]
    return ProjectPage(
        row=row, state=p.state, aliases=sorted({a.alias for a in lookups.aliases(session).get(pid, []) if a.alias != p.name}),
        work_fronts=[w.name for w in lookups.work_fronts(session).get(pid, [])], ladder=ladder_rows, whose_move=move,
        oldest_waits=sorted(waits, key=lambda w: (-w.days, w.ref))[:8], fronts=req.readiness(session, pid),
        top_materials=[TopMaterial(code=m, description=mats[m].description if m in mats else m, uom=mats[m].base_uom if m in mats else ls[0].base_uom,
                                   qty=round(sum(l.qty_base for l in ls), 3), lines=len(ls),
                                   value=money_fig(sum(l.value for l in ls), "Σ PO line value for the material on this project (ME2N)", [R("po_line", l.id) for l in ls]))
                       for m, ls in top],
        cases=cases, months=estimate_rows(session)[pid].months)


# --------------------------------------------------------------------------------------------------------------------------------- Pricing
def _pricing_months() -> list[str]:
    return months_back(12)


@memo
def _po_by_material(session: Session) -> dict[str, list[PoLine]]:
    out: dict[str, list[PoLine]] = defaultdict(list)
    for l in orders.all_lines(session).values():
        if l.material and l.doc_date <= TODAY:
            out[l.material].append(l)
    for v in out.values():
        v.sort(key=lambda l: (l.doc_date, l.id))
    return dict(out)


def _rate_fig(l: PoLine, what: str) -> Figure:
    return Figure(value=round(l.rate_base, 2), text=inr(l.rate_base), unit="rate", rule=f"{what}: net price / price unit, per base unit (PO {l.po_no}, {md(l.doc_date, True)})",
                  refs=[R("po_line", l.id)])


def _site_rates(session: Session, code: str) -> list[SitePrice]:
    lines = _po_by_material(session).get(code, [])
    last: dict[str, PoLine] = {}
    n: dict[str, int] = defaultdict(int)
    for l in lines:
        if l.project_id:
            last[l.project_id] = l
            n[l.project_id] += 1
    med = statistics.median([l.rate_base for l in last.values()]) if last else None
    quotes = _quotes_by_material(session).get(code, [])
    out = []
    for pid, l in last.items():
        b = budget_rate(session, pid, code)
        q = next((q for q in quotes if q.project_id == pid), None)
        out.append(SitePrice(
            project=pid, project_name=lookups.project_name(session, pid), vertical=lookups.vertical_of_project(session, pid), rate=_rate_fig(l, "the project's last PO rate"),
            date=l.doc_date, vendor=l.identity_id, vendor_name=lookups.vendor_name(session, l.identity_id), buyer=l.buyer_id, buyer_name=lookups.member_name(session, l.buyer_id) or None,
            budget=Figure(value=b.rate, text=inr(b.rate), unit="rate", rule="the project's budget rate (BOQ / tender)", refs=[R("budget_rate", str(b.id))]) if b else None,
            quote=_quote_fig(session, q, "the newest priced quote for this project") if q else None,
            vs_median_pct=round(100 * (l.rate_base - med) / med, 1) if med else None, lines=n[pid]))
    return sorted(out, key=lambda s: (s.rate.value or 0, s.project_name))


def _trend(session: Session, code: str) -> list[MonthRate]:
    by: dict[str, list[PoLine]] = defaultdict(list)
    for l in _po_by_material(session).get(code, []):
        by[l.doc_date[:7]].append(l)
    out = []
    for m in _pricing_months():
        ls = by.get(m, [])
        q = sum(l.qty_base for l in ls)
        out.append(MonthRate(month=m, rate=Figure(value=round(sum(l.value for l in ls) / q, 2), text=inr(sum(l.value for l in ls) / q), unit="rate",
                                                  rule=f"Σ PO value / Σ quantity over {count(len(ls), 'PO line')} dated in {month_year(m)}, every site",
                                                  refs=[R("po_line", l.id) for l in ls]) if ls and q else None))
    return out


@memo
def _flagged(session: Session) -> set[str]:
    """Materials whose spread Today raised as a case (its own rule), folded or not."""
    return {k.split(":", 1)[1] for k in attention.all_keys(session) if k.startswith("rate-spread:")}


def spread_share() -> float:
    """How far above the median a site's rate must be before the page asks why: the recipe's `price_spread_share` when it gives one, else the share
    its fund check counts as material (answers.yaml)."""
    a = lookups.answers()
    return float(a.get("price_spread_share") or (a.get("fund_check") or {}).get("min_share") or 0)


def _above(sites: list[SitePrice], med: float | None) -> list[SitePrice]:
    """The sites whose last rate is materially above the median: each is a question for that site's buyer."""
    return [s for s in sites if med and (s.rate.value or 0) > med * (1 + spread_share())]


def _pricing_row(session: Session, code: str) -> PricingRow | None:
    m = lookups.materials(session).get(code)
    lines = _po_by_material(session).get(code, [])
    if m is None or not lines:
        return None
    sites = _site_rates(session, code)
    lo, hi = (sites[0], sites[-1]) if sites else (None, None)
    spread = None
    if len(sites) > 1 and lo and lo.rate.value:
        ratio = (hi.rate.value or 0) / lo.rate.value
        spread = Figure(value=round(ratio, 2), text=f"{ratio:.1f}×", unit="ratio",
                        rule=f"the highest project's last PO rate ({hi.project_name}, {inr(hi.rate.value)}) over the lowest ({lo.project_name}, {inr(lo.rate.value)})",
                        refs=hi.rate.refs + lo.rate.refs)
    last = lines[-1]
    lb = budget_rate(session, last.project_id, code) if last.project_id else None
    q = next(iter(_quotes_by_material(session).get(code, [])), None)
    trend = _trend(session, code)
    bought = [t for t in trend if t.rate]
    change = None
    if len(bought) > 1 and bought[0].rate.value:
        change = pct_fig(bought[-1].rate.value / bought[0].rate.value - 1, f"the monthly average rate in {month_year(bought[-1].month)} against {month_year(bought[0].month)}",
                         bought[0].rate.refs + bought[-1].rate.refs)
    rates = [s.rate.value for s in sites if s.rate.value is not None]
    return PricingRow(
        code=code, description=m.description, group=m.group, category=m.category, uom=m.base_uom, index=m.pv_index, sites=len(sites), spread=spread, low=lo, high=hi,
        median=round(statistics.median(rates), 2) if rates else None, last=_rate_fig(last, "the newest PO rate, any site"), last_project=last.project_id,
        last_budget=Figure(value=lb.rate, text=inr(lb.rate), unit="rate", rule=f"the budget rate of {lookups.project_name(session, last.project_id)} (BOQ / tender)",
                           refs=[R("budget_rate", str(lb.id))]) if lb else None,
        latest_quote=_quote_fig(session, q, "the newest priced quote, any site") if q else None,
        latest_quote_project=q.project_id if q else None, trend=trend, trend_change=change, pv_lines=sum(1 for l in lines if l.pv_clause),
        flagged=f"rate-spread:{code}" if code in _flagged(session) else None,
        unexplained=bool(_above(sites, statistics.median(rates) if rates else None)))


@memo
def pricing_rows(session: Session) -> list[PricingRow]:
    rows = [r for r in (_pricing_row(session, c) for c in lookups.materials(session)) if r]
    return sorted(rows, key=lambda r: (r.category, r.description))


def pricing(session: Session) -> PricingResponse:
    return PricingResponse(as_of=TODAY, months=_pricing_months(), rows=pricing_rows(session), notes=[
        "Rate by site is each project's last PO rate, per the material's base unit (price units and bags converted).",
        "A spread is the highest site over the lowest. Why a site pays more (haul, quality, the local market) is not in the records: the buyer of that site's lines can say.",
        "The monthly average is Σ PO value / Σ quantity of the month's PO lines, every site together."])


def pricing_detail(session: Session, code: str) -> PricingDetail | None:
    row = _pricing_row(session, code)
    if row is None:
        return None
    lines = _po_by_material(session).get(code, [])
    sites = _site_rates(session, code)
    vend: dict[str, list[PoLine]] = defaultdict(list)
    for l in lines:
        vend[l.identity_id].append(l)
    by_vendor = sorted((VendorRate(vendor=v, vendor_name=lookups.vendor_name(session, v), lines=len(ls), last=_rate_fig(ls[-1], "the vendor's last PO rate"),
                                   low=min(l.rate_base for l in ls), high=max(l.rate_base for l in ls), last_date=ls[-1].doc_date,
                                   projects=sorted({l.project_id for l in ls if l.project_id})) for v, ls in vend.items()), key=lambda v: (v.last.value or 0, v.vendor_name))
    pv: list[PvItem] = []
    for l in lines:
        if not (l.pv_clause and l.pv_index):
            continue
        latest = indices.latest_month(session, l.pv_index)
        share = l.pv_variable_share or indices.variable_share(session, l.pv_index)
        res = indices.pv(session, qty=l.qty_base, rate=l.rate_base, share=share, index=l.pv_index, base_month=l.pv_base_month, current_month=latest) if (share and l.pv_base_month and latest) else None
        pv.append(PvItem(ref=R("po_line", l.id), kind="po", project=l.project_id, project_name=lookups.project_name(session, l.project_id) or None,
                         vendor_name=lookups.vendor_name(session, l.identity_id), index=l.pv_index, base_month=l.pv_base_month, base_index=res.base_index if res else None,
                         latest_month=latest, latest_index=res.current_index if res else None,
                         change_pct=round(100 * (res.current_index / res.base_index - 1), 1) if res and res.base_index and res.current_index else None, share=share,
                         pv=money_fig(res.pv, f"the PO's clause on the ordered quantity at the {month_year(latest)} index: {res.formula}", [R("po_line", l.id)]) if res and res.pv is not None else None))
    for i in lookahead_items(session):
        if i.material == code and i.index and i.price_basis == "PV":
            s = indices.series(session).get(i.index, {})
            latest = max(s) if s else None
            pv.append(PvItem(ref=R("lookahead", str(i.id)), kind="lookahead", project=i.project, project_name=i.project_name, vendor_name=None, index=i.index, base_month=None,
                             base_index=None, latest_month=latest, latest_index=s.get(latest) if latest else None, change_pct=round(100 * i.monthly_change, 2) if i.monthly_change else None,
                             share=i.share, pv=money_fig(i.delay_cost, "a month's wait before ordering: item value x the variable share x the index's average monthly change over six months",
                                                         [R("lookahead", str(i.id))]) if i.delay_cost else None))
    idx = row.index or next((l.pv_index for l in lines if l.pv_index), None)
    series = indices.series(session).get(idx or "", {})
    med = row.median
    unknowns = []
    if med:
        for s in _above(sites, med):
            lo = sites[0]
            moved = ""
            if idx and lo.date[:7] in series and s.date[:7] in series and lo.date[:7] != s.date[:7]:
                moved = f" The {idx} index moved {100 * (series[s.date[:7]] / series[lo.date[:7]] - 1):+.1f}% between {month_year(lo.date)} and {month_year(s.date)}."
            unknowns.append(SpreadUnknown(
                project=s.project, project_name=s.project_name, rate=s.rate.value or 0, ask=s.buyer, ask_name=s.buyer_name, refs=s.rate.refs,
                what=(f"{s.project_name} pays {inr(s.rate.value)} per {row.uom}, {s.vs_median_pct:+.0f}% on the median {inr(med)}. Why is not in the records: "
                      f"haul distance, quality and the local market are not on any PO.{moved}"),
                question=f"Why does {s.project_name} pay {inr(s.rate.value)} for {row.description} against a median of {inr(med)} across {count(len(sites), 'project')}?"))
    quotes = [QuoteRow(ref=R("quote", q.id), vendor_name=q.vendor_name, project=q.project_id, project_name=lookups.project_name(session, q.project_id) or None,
                       date=q.quote_date or q.rfq_sent, rate=q.rate, uom=q.uom, rate_base=quote_rate(session, q), source=q.source, cs=q.cs_no, basis=q.price_basis)
              for q in _quotes_by_material(session).get(code, [])[:20]]
    return PricingDetail(**row.model_dump(), by_site=sites, by_vendor=by_vendor, pv=pv,
                         index_series=[IndexPoint(month=m, value=series[m]) for m in _pricing_months() if m in series], unknowns=unknowns, quotes=quotes)


# ------------------------------------------------------------------------------------------------------------------------------- Estimates
def year_months(session: Session) -> list[str]:
    """The twelve full months before the data date's month, from the first month the exports hold: the project's own record a requirement is read
    against."""
    posted = [r.posting_date for r in _receipts(session)]
    start = min(posted)[:7] if posted else TODAY[:7]
    return [m for m in months_back(12, months_back(2)[0]) if m >= start]


def _over_rule() -> tuple[float, float, str]:
    fc = lookups.answers().get("fund_check") or {}
    amt, share = float(fc.get("min_difference_inr") or 0), float(fc.get("min_share") or 0)
    return amt, share, (f"a month's requirement more than {inr(amt)} and {share * 100:g}% above the most the project received in any one month of the past year "
                        "(the amount and share of the recipe's fund check, answers.yaml)")


@memo
def estimate_rows(session: Session) -> dict[str, EstimateRow]:
    months, year = sheet_months(session), year_months(session)
    shown = year + [m for m in months if m not in year]
    amt, share, _rule = _over_rule()
    checks = req.fund_checks(session)
    names = {p.id: p.name for p in lookups.projects(session).values()}
    order = {v: i for i, v in enumerate(lookups.VERTICALS)}
    span = f"{month_year(year[0])} – {month_year(year[-1])}"
    out: dict[str, EstimateRow] = {}
    for p in sorted(lookups.projects(session).values(), key=lambda p: (order.get(p.vertical, 9), p.name)):
        reqs = req.lines_for(session, p.id)
        funds = [f for f in _fund_lines(session) if p.id in (f.project_ids or "").split(",")]
        rec, rec_refs = _received(session, p.id, shown)
        on_sheet = bool(reqs)
        got = [m for m in year if rec.get(m, 0.0) > 0]
        usual = sum(rec[m] for m in got) / len(got) if got else None
        best = max(got, key=lambda m: rec[m]) if got else None
        peak = rec[best] if best else 0.0
        rows, over, biases, accs = [], 0, [], []
        for m in shown:
            rq = [r for r in reqs if r.month == m]
            fd = [f for f in funds if f.month == m]
            rq_v = sum(r.amount or 0 for r in rq) if rq else None
            is_over = None
            if rq_v is not None and m in months:
                diff = rq_v - peak
                is_over = diff > amt and (peak == 0 or diff / peak > share)
                over += bool(is_over)
                if usual:
                    biases.append(rq_v / usual - 1)
            if rq_v and month_past(m):
                accs.append(1 - abs(rq_v - rec.get(m, 0.0)) / rq_v)
            rows.append(EstimateMonth(
                month=m, past=month_past(m), partial=m == TODAY[:7],
                requirement=money_fig(rq_v, "Σ quantity x rate on the month's requirement-sheet rows", [R("requirement", r.id) for r in rq]) if rq else None,
                fund=money_fig(sum(f.amount for f in fd), "Σ the fund sheet's lines for the project and month (₹ Cr, lakh and rupees read as rupees)",
                               [R("fund_line", str(f.id)) for f in fd]) if fd else None,
                fund_shared_with=sorted({names.get(x, x) for f in fd for x in (f.project_ids or "").split(",") if x and x != p.id}),
                received=money_fig(rec.get(m, 0.0), _received_rule(session, p.id) + (f", to {dmy(TODAY)} (the month is not over)" if m == TODAY[:7] else ""),
                                   rec_refs.get(m, [])) if m <= TODAY[:7] else None,
                over=is_over))
        u_refs = sorted({r for m in got for r in rec_refs.get(m, [])})
        bias = pct_fig(sum(biases) / len(biases), f"the sheet's months against the usual month, averaged (requirement / usual − 1)",
                       [R("requirement", r.id) for r in reqs] + u_refs) if biases else None
        acc = (pct_fig(sum(accs) / len(accs), "1 − |requirement − received| / requirement, over the sheet's months already past", [R("requirement", r.id) for r in reqs], signed=False)
               if accs else (Figure(value=None, text="not yet", unit="pct", rule="measured once a sheet month has passed",
                                    note=f"no sheet month has closed: {month_year(months[0])} closes on {md(req.month_end(months[0]))}") if on_sheet else None))
        out[p.id] = EstimateRow(
            project=p.id, project_name=p.name, vertical=p.vertical, on_sheet=on_sheet, months=rows,
            usual=money_fig(usual, f"{_received_rule(session, p.id)}, averaged over the {count(len(got), 'month')} of {span} it received anything", u_refs) if usual is not None else None,
            peak=money_fig(peak, f"the most received in one month of {span} ({month_year(best)})", rec_refs.get(best, [])) if best else None,
            bias=bias, accuracy=acc, over_months=over, repeat=over > 1,
            fund_disagrees=[c.id for c in checks if c.disagrees and p.id in (c.project_ids or "").split(",")], ask=p.planner_name)
    return out


def estimates(session: Session) -> EstimatesResponse:
    rows = estimate_rows(session)
    _a, _s, rule = _over_rule()
    mis = lookups.mis(session)
    fund_by_name: dict[str, list[FundLine]] = defaultdict(list)
    for f in _fund_lines(session):
        if not f.project_ids:
            fund_by_name[f.column_as_printed].append(f)
    unresolved = []
    for a in session.scalars(select(ProjectAlias).where(ProjectAlias.method == "unresolved").order_by(ProjectAlias.source, ProjectAlias.alias)):
        fl = fund_by_name.get(a.alias, []) if a.source == "fund" else []
        who = mis if a.source in ("fund", "payment_projection") else None
        unresolved.append(Unresolved(name=a.alias, source=a.source, ask=who.id if who else None, ask_name=who.name if who else None,
                                     amount=money_fig(sum(f.amount for f in fl), "Σ the fund lines printed under this name, which no project resolves to", [R("fund_line", str(f.id)) for f in fl]) if fl else None))
    months, year = sheet_months(session), year_months(session)
    return EstimatesResponse(
        as_of=TODAY, sheet_months=months, year_months=year, threshold=rule, rows=list(rows.values()),
        over_askers=[r.project for r in rows.values() if r.repeat], unresolved=unresolved,
        notes=[f"Received is MB51 net value of the materials the sheet asks for. The full months of the past year before {month_year(TODAY)} are the project's own record: "
               "its usual month (the average of the months it received anything) and its best month.",
               f"A requirement month is an over-ask when it is above the project's best month by both the fund check's amount and share; asking above it in more "
               "than one month makes a repeat over-asker. Bias is the sheet against the usual month.",
               "Accuracy is measured only on a sheet month that has passed; a month in progress shows what was received so far, never a forecast of the rest.",
               "Site stock is not in the data: a project that asks above its usual month may be building stock or speeding up. Its planner can say."])


# ----------------------------------------------------------------------------------------------------------------------------------- Brief
def brief(session: Session, person: str) -> Brief | None:
    """The Daily brief: what the member would read in the morning email (never sent). A member who sees everyone gets the team's PRs, milestones and
    vendors; anyone else their own purchasing groups'."""
    b = lookups.member_of(session, person)
    if b is None:
        return None
    first = b.name.split()[0]
    pr_all, po_all = _member_lines(session)
    mine = [b.id, *lookups.under(session, b.id)]
    pr = [l for ls in pr_all.values() for l in ls] if b.sees_all else [l for m in mine for l in pr_all.get(m, [])]
    po = [l for ls in po_all.values() for l in ls] if b.sees_all else [l for m in mine for l in po_all.get(m, [])]
    whose = "the team's" if b.sees_all else "your team's" if len(mine) > 1 else "your"
    cases = attention.what_needs_attention(session, owner=b.id)
    sections: list[BriefSection] = []

    def section(key: str, title: str, lines: list[BriefLine], empty: str) -> None:
        sections.append(BriefSection(key=key, title=title, lines=lines[:BRIEF_LINES], more=max(0, len(lines) - BRIEF_LINES), empty=empty))

    def stake(c) -> str | None:
        a = c.at_stake
        return inr(float(a.amount)) if a is not None and hasattr(a, "currency") else None

    on_you = [c for c in cases if c.waiting_on == "SCM"]
    section("on_you", "Waiting on you", [BriefLine(text=c.title + (f" · act by {md(c.act_by)}" if c.act_by else ""), ref=R("item", c.key), figure=stake(c)) for c in on_you],
            "Nothing on Today waits on you.")

    open_pr = sorted((l for l in pr if l.status == "open"), key=lambda l: (-age(l), l.id))
    by_pr: dict[str, list[PrLine]] = {}
    for l in open_pr:
        by_pr.setdefault(l.pr_no, []).append(l)
    ageing = []
    past_target = 0
    for no, ls in by_pr.items():
        l0 = ls[0]
        t = _target(lookups.vertical_of_project(session, l0.project_id))
        past = t is not None and age(l0) > t
        past_target += past
        where = lookups.project_name(session, l0.project_id) or "no project"
        ageing.append(BriefLine(text=f"PR {no} · {where} · {l0.short_text or ''}" + (f" (+{count(len(ls) - 1, 'line')})" if len(ls) > 1 else "")
                                + (f" · past the {t}-day target" if past else ""), ref=R("pr", no), figure=days_word(age(l0))))
    section("ageing", f"Oldest open PRs on {whose} purchasing groups" if not b.sees_all else "The team's oldest open PRs", ageing, "No open PRs.")

    horizon = (AS_OF + timedelta(days=BRIEF_DAYS)).isoformat()
    po_ids = {l.id for l in po}
    po_projects = defaultdict(lambda: defaultdict(int))
    for ls in po_all.values():
        for l in ls:
            if l.project_id:
                po_projects[l.project_id][l.buyer_id] += 1
    ms = []
    for m in session.scalars(select(Milestone).order_by(Milestone.id)):
        mine = m.po_line_id in po_ids if m.po_line_id else (b.sees_all or (m.project_id and max(po_projects[m.project_id].items(), key=lambda kv: kv[1], default=(None, 0))[0] == b.id))
        if not mine:
            continue
        what = m.item_text or m.po_no
        where = lookups.project_name(session, m.project_id) or ""
        r_ = R("po", m.po_no)
        if m.mfc_requested and not m.mfc_issued:
            ms.append((m.mfc_requested, BriefLine(text=f"MFC asked on {md(m.mfc_requested)}, not issued · {what} · {where} · PO {m.po_no}", ref=r_, figure="pending")))
        if m.inspection_planned and not m.inspection_done and m.inspection_planned <= horizon:
            ms.append((m.inspection_planned, BriefLine(text=f"Inspection {'was due' if m.inspection_planned < TODAY else 'set for'} {md(m.inspection_planned)} · {what} · {where} · PO {m.po_no}"
                                                       + (f" · site ready {md(m.site_ready_planned)}" if m.site_ready_planned else ""), ref=r_, figure=md(m.inspection_planned))))
        if m.inspection_done and not m.dispatch_clearance:
            ms.append((m.inspection_done, BriefLine(text=f"Inspected {md(m.inspection_done)}, dispatch not cleared · {what} · {where} · PO {m.po_no}", ref=r_, figure="dispatch")))
        if m.warranty_end and TODAY <= m.warranty_end <= horizon:
            ms.append((m.warranty_end, BriefLine(text=f"Warranty ends {md(m.warranty_end)}" + ("" if m.commissioned else ", not commissioned") + f" · {what} · {where} · PO {m.po_no}",
                                                 ref=r_, figure=md(m.warranty_end))))
    section("milestones", f"Milestones due by {md(horizon)}", [x for _, x in sorted(ms, key=lambda t: t[0])], f"No inspection, dispatch, MFC or warranty milestone falls due by {md(horizon)}.")

    lads, subj = ladders(session), subjects(session)
    keys = {R("pr_line", l.id) for l in pr} | {R("po_line", l.id) for l in po}
    others = [c for c in cases if c.waiting_on != "SCM"]
    waiting = sorted(((k, lad) for k, lad in lads.items() if k in keys and lad.waiting_on and lad.waiting_on != "SCM" and lad.days_waiting is not None),
                     key=lambda kv: (-(kv[1].days_waiting or 0), kv[0]))
    w_lines = [BriefLine(text=f"With {c.waiting_on}: {c.title}", ref=R("item", c.key), figure=stake(c)) for c in others]
    for k, lad in waiting:
        rung = next((r for r in lad.rungs if r.state == "now"), None)
        w_lines.append(BriefLine(text=f"With {lad.waiting_on} since {md(lad.waiting_since)} for {rung.label if rung else 'the next step'} · {subj[k]['text']} ({k.split(':', 1)[1]})",
                                 ref=k, figure=days_word(lad.days_waiting or 0)))
    tally = defaultdict(int)
    for _k, lad in waiting:
        tally[lad.waiting_on] += 1
    section("others", "Waiting on others", w_lines, "Nothing of yours waits on another function.")
    if tally:
        sections[-1].lines.append(BriefLine(text="In all: " + ", ".join(f"{count(n, 'line')} with {f}" for f, n in sorted(tally.items(), key=lambda kv: FUNCTIONS.index(kv[0])))))

    late = [l for l in po if l.status == "open" and l.delivery_date and l.delivery_date < TODAY and l.open_base > 0]
    by_v: dict[str, list[PoLine]] = defaultdict(list)
    for l in late:
        by_v[l.identity_id].append(l)
    rev = orders.revisions(session)
    v_lines = []
    for v, ls in sorted(by_v.items(), key=lambda kv: -sum(l.open_value for l in kv[1])):
        oldest = min(ls, key=lambda l: l.delivery_date)
        moved = [l for l in ls if rev.get(l.id)]
        v_lines.append(BriefLine(text=f"{lookups.vendor_name(session, v)} · {count(len(ls), 'line')} late, oldest due {md(oldest.delivery_date)} "
                                      f"({days_word((AS_OF - date.fromisoformat(oldest.delivery_date)).days)})" + (f" · {count(len(moved), 'line')} moved by the vendor's mail" if moved else ""),
                                 ref=R("supplier", v), figure=inr(sum(l.open_value for l in ls))))
    section("vendors", "Vendors to chase", v_lines, "No open PO line is past its delivery date.")

    n_on, n_old = len(on_you), past_target
    subject = f"Your brief for {md(TODAY)}: " + ", ".join(x for x in [count(n_on, "case") + " waiting on you" if n_on else "", f"{count(n_old, 'PR')} past target" if n_old else "",
                                                                       f"{count(len(by_v), 'vendor')} to chase" if by_v else ""] if x) if (n_on or n_old or by_v) else f"Your brief for {md(TODAY)}: nothing pressing"
    domain = lookups.answers().get("internal_domain") or "example.com"
    return Brief(person=b.id, name=b.name, role=b.role, sender=f"Lookout <lookout@{domain}>", to=f"{b.name} <{b.email}>" if b.email else b.name, date=TODAY, subject=subject,
                 greeting=f"Good morning {first},", intro=f"Here is what needs you, from the records as of {dmy(TODAY)}." + (" You see the whole team, so the PRs, milestones and vendors below are everyone's." if b.sees_all else ""),
                 sections=sections, sign_off="Lookout")
