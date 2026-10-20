"""What Lookout found on a case, as code facts (plan-13 findings.md Rev 2): every fact is counted, summed or rounded by code from the records, with a
template meaning for the page. The agent only picks the 3-4 a buyer most needs and may say what each means in its own words (verified); without it, the page
shows the template, so the block is never empty, even on an old recording."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import naming
from app.domain.attention import service
from app.domain.attention.options import case_kind
from app.domain.common import AS_OF
from app.domain.orders.model import PoLine
from app.domain.quotes import service as quotes
from app.domain.suppliers import service as suppliers
from app.domain.tariffs import service as tariffs


class FindingCandidate(BaseModel):
    key: str
    fact: str  # code's sentence, every figure from the records
    template_meaning: str  # what the page says it means when the run gave no meaning of its own


def _streak(session: Session, ident: str, who: str) -> FindingCandidate | None:
    """The supplier's own record before the case: its latest receipts late in a row, and its late share this year against last (code counts, never the agent)."""
    rows = session.execute(select(PoLine.received_date, PoLine.promised_date).where(PoLine.identity_id == ident, PoLine.status == "CLOSED", PoLine.received_date.is_not(None),
                                                                                   PoLine.promised_date.is_not(None)).order_by(PoLine.received_date.desc())).all()
    late = lambda r: r[0] > r[1]  # noqa: E731  received after the promise
    run = []
    for r in rows:
        if not late(r):
            break
        run.append(r)
    if len(run) < 3:
        return None
    days = [(date.fromisoformat(r[0]) - date.fromisoformat(r[1])).days for r in run]
    fact = f"{who}'s last {len(run)} receipts were late ({service.md(run[-1][0])} → {service.md(run[0][0])}, +{min(days)} to +{max(days)} days)"
    year, prev = str(AS_OF.year), str(AS_OF.year - 1)
    this, last = [r for r in rows if r[0].startswith(year)], [r for r in rows if r[0].startswith(prev)]
    if this and last:
        fact += f"; late on {round(100 * sum(map(late, this)) / len(this))}% of {year} receipts against {round(100 * sum(map(late, last)) / len(last))}% in {prev}"
    return FindingCandidate(key="supplier_streak", fact=fact, template_meaning="The warning was in the records")


def _fire(session: Session, ctx: dict) -> list[FindingCandidate]:
    who, ident, parts = ctx["who"], ctx["ident"], list(ctx["parts"])
    out = []
    alt: dict[str, set] = {}
    for p in parts:
        for o in quotes.offers_for_part(session, p):
            if o.supplier is None or o.supplier.id != ident:   # a quote from a firm not yet on file counts as an alternative (as fire_options' second source does)
                alt.setdefault(naming.supplier_name(session, o.supplier.id) if o.supplier else naming.firm_name(o.supplier_name), set()).add(p)
    on_file = {part: sid for sid, part in session.execute(select(PoLine.identity_id, PoLine.part_number).where(PoLine.part_number.in_(parts), PoLine.identity_id != ident)).all() if sid}
    covered = (set().union(*alt.values()) if alt else set()) | set(on_file)
    bare = [p for p in parts if p not in covered]
    if bare:
        out.append(FindingCandidate(key="no_alt_quote", fact=f"No second source on any PO line or quote for {len(bare)} of {len(parts)} parts ({', '.join(bare)})",
                                    template_meaning="Alternatives need new quotes first"))
    for part, sid in sorted(on_file.items())[:1]:
        out.append(FindingCandidate(key="alt_on_file", fact=f"{naming.supplier_name(session, sid)} has supplied {part} before, on a PO line",
                                    template_meaning=f"A second source for {part} only"))
    for name, ps in sorted(alt.items()):
        rest = [p for p in parts if p not in ps]
        out.append(FindingCandidate(key="alt_quote_coverage", fact=f"{name} quotes {', '.join(sorted(ps))} only ({len(ps)} of {len(parts)} parts)",
                                    template_meaning=f"Still no quote for {', '.join(rest)}" if rest else "Covers every short part"))
        break  # the one alternate the options lay out
    perf = suppliers.delivery_performance(session).get(ident)
    if perf and perf.n:
        out.append(FindingCandidate(key="supplier_otd", fact=f"{who} on time on {perf.on_time_pct * 100 if perf.on_time_pct <= 1 else perf.on_time_pct:.0f}% of its {perf.n} closed lines ({perf.on_time} of {perf.n})"
                                    + (f", {perf.avg_days_late:.1f} days late on average" if perf.avg_days_late else ""), template_meaning="Revised dates may slip"))
    lines = ctx.get("lines") or {}
    rw = tariffs.restart_window(session, ident)
    late = [l for l in lines.values() if l.promised_date and l.promised_date < AS_OF.isoformat()]
    if late:
        before = [l for l in late if rw and l.promised_date < rw[2]]
        out.append(FindingCandidate(key="past_due", fact=f"{len(late)} of {len(lines)} lines past their promise on {service.md(AS_OF.isoformat())}"
                                    + (f"; {len(before)} were already late before the notice of {service.md(rw[2])}" if before else ""),
                                    template_meaning="Rights reserved; ask for every date"))
    if rw:
        out.append(FindingCandidate(key="restart_window", fact=f"Restart estimated {service.md(rw[0])} – {service.md(rw[1])}, from {who}'s notice of {service.md(rw[2])}",
                                    template_meaning=f"Nothing from the burned plant before {service.md(rw[0])}"))
    streak = _streak(session, ident, who)
    if streak:
        out.append(streak)
    return out


def _duty(session: Session, item) -> list[FindingCandidate]:
    """The duty roll-up: the share owed on a burned supplier's lines, which cannot ship before the duty starts (the same number the agent cites)."""
    out = []
    for n in item.numbers:
        if n.id.startswith("duty_owed_fire:"):
            out.append(FindingCandidate(key="fire_lines_duty", fact=f"{service._fmt(float(n.value.usd))} of the duty owed is on {n.label[len('Owed on '):] if n.label.startswith('Owed on ') else n.label}",
                                        template_meaning="Budget it: those lines can't ship in time"))
    return out


def _chase(session: Session, ctx: dict) -> list[FindingCandidate]:
    lines, out = ctx["chase"], []
    out.append(FindingCandidate(key="no_word", fact=f"{len(lines)} lines past their promise with no new date from the supplier", template_meaning="Ask each supplier for a ship date"))
    builds = sorted(set((ctx.get("risk") or {}).values()))      # "<robot> <month>": the build each late part feeds
    if builds:
        out.append(FindingCandidate(key="feeds_robot", fact="The late parts feed the " + ", ".join(builds) + " builds", template_meaning="Those builds wait on these lines"))
    origin = service.item_context(session, "unknown:origin")
    blank = {r.id for r in origin[0].refs if r.type == "part"} if origin else set()
    no_origin = sorted({l.part.id for l in lines} & blank)
    if no_origin:
        out.append(FindingCandidate(key="no_origin", fact=f"{', '.join(no_origin)} also has no country of origin on file", template_meaning="Ask for the origin in the same email"))
    own = sorted({naming.supplier_name(session, l.supplier.id) for l in lines if l.supplier and service.item_context(session, f"risk:{l.supplier.id}")})
    if own:
        out.append(FindingCandidate(key="other_case", fact=f"Lines with {', '.join(own)} are also in {'that supplier' if len(own) == 1 else 'those suppliers'}' own case",
                                    template_meaning="Handled in the supplier's own case"))
    return out


def _money(x: float) -> str:
    """Under $10K with cents (AGENT-EXPERT: amounts under $10K keep cents), else the money columns' rule."""
    return f"${x:,.2f}" if x < 10_000 else service._fmt(x)


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _incident(ctx: dict) -> list[FindingCandidate]:
    out, today = [], AS_OF.isoformat()
    moved = [m for m in ctx.get("moved") or [] if m.revised_promise]
    if moved:
        dates = sorted(m.revised_promise for m in moved)
        out.append(FindingCandidate(key="redated", fact=f"{len(moved)} lines re-dated to {service.md(dates[0])} – {service.md(dates[-1])} ({', '.join(m.po_line.id for m in moved)})",
                                    template_meaning="Confirm the new dates hold"))
    scope = ctx.get("scope") or []
    late_before = [l for l in scope if l.promise and l.promise < today]
    undated = [l for l in ctx.get("late") or [] if not l.revised_promise]
    if late_before:
        out.append(FindingCandidate(key="late_before", fact=f"{len(late_before)} of {len(scope)} lines were already past their promise on {service.md(today)}"
                                    + (f"; {len(undated)} of them have no new date" if undated else ""), template_meaning="Ask dates for the late lines"))
    return out


def _slip(session: Session, ctx: dict, item) -> list[FindingCandidate]:
    out, slipped = [], [x for x in ctx.get("slipped") or [] if x.revised_promise and x.promise]
    if slipped:
        days = [_days(x.promise, x.revised_promise) for x in slipped]
        dates = sorted(x.revised_promise for x in slipped)
        out.append(FindingCandidate(key="moved", fact=f"{len(slipped)} PO lines move out {min(days)} to {max(days)} days, to {service.md(dates[0])} – {service.md(dates[-1], with_year=dates[-1][:4] != str(AS_OF.year))}",
                                    template_meaning="October builds lose these parts"))
    detail = service.item_detail(session, item.key)
    for n in (detail.numbers if detail else []):
        if n.id.startswith("duty_if_arrives_late:") and getattr(n.value, "usd", None):
            out.append(FindingCandidate(key="late_duty", fact=f"{_money(float(n.value.usd))} duty on {n.id.split(':', 1)[1]} if it enters on or after the duty date",
                                        template_meaning="Late arrival adds duty"))
            break
    lt = notice_lead_time(session, ctx.get("ident"))
    if lt:
        out.append(FindingCandidate(key="lead_time", fact=lt, template_meaning="Order before the cutoff"))
    return out


def notice_lead_time(session: Session, ident: str | None) -> str | None:
    """The lead-time change a supplier's own notice states ("orders placed after 1 October 2026 … from 8 weeks to 16 weeks"), quoted from the message, or None."""
    from app.domain.attention.notices import lead_time_change  # noqa: PLC0415

    lt = lead_time_change(session, ident)
    if lt is None:
        return None
    return f"Orders placed {lt.when} {lt.cutoff_text}: lead time {lt.old_weeks} → {lt.new_weeks} weeks (the supplier's notice of {service.md(lt.notice_date)})"


def _cover(ctx: dict) -> FindingCandidate | None:
    """What the open lines cover at the monthly need: code divides, never the agent (BUYER R1: '338 on order ≈ 4 months at 80 a month')."""
    monthly = ctx.get("monthly")
    sole = (ctx.get("sole") or [None])[0]
    live = [l for l in ctx.get("live") or [] if getattr(getattr(l, "part", None), "id", sole) == sole]   # the part the monthly need is for: one figure per part, never two parts added (BUYER R2b: two parts were summed)
    need = float(monthly.qty.value) if monthly and monthly.qty else 0
    on_order = sum(float(l.qty.value) for l in live if getattr(l, "qty", None))
    if not need or not on_order:
        return None
    return FindingCandidate(key="cover", fact=f"{on_order:,.0f} {sole} on order covers about {on_order / need:.0f} months at {need:,.0f} a month", template_meaning="Time to qualify another source")


def _price_lock(item) -> list[FindingCandidate]:
    pcts = [n for n in item.numbers if n.id.startswith("price_increase_pct:")]
    out = []
    if pcts:
        out.append(FindingCandidate(key="rise", fact="Announced rise: " + ", ".join(f"+{float(n.value.value):g}% on {n.label.removeprefix('Announced price rise on ')}" for n in pcts),
                                    template_meaning="Costs rise from the effective date"))
    usd = getattr(item.at_stake, "usd", None)
    if usd:
        out.append(FindingCandidate(key="saving", fact=f"Acknowledging by {service.md(item.act_by)} keeps today's price: ${float(usd):,.2f} on the need open orders don't cover (before stock on hand)", template_meaning="Small, but free to take"))
    return out


_RISK_MEANING = {"insolvency": "Deliveries may stop", "prepayment": "Cash at risk if paid ahead", "price_jump": "Pricier than the last order",
                 "terms_cut": "Less time to pay", "late_delivery": "Dates will likely slip", "cash_in_advance": "Cash out before goods arrive",
                 "undated_open": "No date to plan on", "news_risk": "Watch the news"}


def _cash_at_risk(session: Session, ident: str | None, flags) -> FindingCandidate | None:
    """BUYER R4: a supplier paid in advance on its terms that also delivers late is a finding of its own: the open value of its orders is cash out before
    goods that are likely late (code sums the open lines; the on-time share is the delivery record's)."""
    kinds = {f.kind: f for f in flags or []}
    if not ident or "cash_in_advance" not in kinds or "late_delivery" not in kinds:
        return None
    lines = list(session.scalars(select(PoLine).where(PoLine.identity_id == ident, PoLine.status.in_(("OPEN", "PARTIAL")), PoLine.flags.not_like("%stale_open%"))))   # the live open orders, as the case's open value counts them
    open_usd = sum(float(l.open_usd or 0) for l in lines)
    perf = suppliers.delivery_performance(session).get(ident)
    if not open_usd or not perf or not perf.n:
        return None
    terms = kinds["cash_in_advance"].evidence or "paid in advance"
    return FindingCandidate(key="cash_at_risk", fact=f"{_money(open_usd)} open on {len(lines)} lines under {terms}, with a supplier on time on {round(perf.on_time_pct * 100)}% of {perf.n} lines",
                            template_meaning="Cash out before late goods")


def candidates(session: Session, key: str) -> list[FindingCandidate]:
    """The facts code found for this case, or [] for an item with none built yet."""
    hit = service.item_context(session, key)
    if hit is None:
        return []
    item, ctx = hit
    if key == "deadline:chase":
        return _chase(session, ctx)
    if case_kind(session, key) == "fire":
        return _fire(session, ctx)
    if key == "tariff:all":
        detail = service.item_detail(session, key)
        return _duty(session, detail) if detail else []
    if key == "unknown:hts":
        parts = [r.id for r in item.refs if r.type == "part"]
        return [FindingCandidate(key="no_hts", fact=f"No HTS code for {', '.join(parts)} (China origin): the duty on them cannot be computed", template_meaning="Ask the customs broker to classify")] if parts else []
    if key == "unknown:stale-orders":   # each aged order, as its own row says it (code counts the days)
        return [FindingCandidate(key=f"aged_{m.key.split(':', 1)[1].split('/')[0]}", fact=m.title.split(": probably")[0], template_meaning="Ask Receiving whether it arrived")
                for m, _ in (ctx.get("members") or [])][:4]
    if key == "deadline:quotes":   # each quote about to lapse, as its own row says it
        return [FindingCandidate(key=f"quote_{q.key.split(':')[1]}", fact=q.title, template_meaning="Decide before it lapses") for q, _ in (ctx.get("rest") or [])][:4]
    kind = case_kind(session, key)
    if kind == "price_lock":
        detail = service.item_detail(session, key)
        return _price_lock(detail) if detail else []
    out = _incident(ctx) if kind == "incident" else _slip(session, ctx, item) if kind == "slip" else []
    if ctx.get("risk"):   # a supplier at risk: each flag the detector raised is a fact (its own quote, terms, record, news)
        cash = _cash_at_risk(session, ctx.get("ident"), ctx.get("flags"))
        out += [cash] if cash else []
        out += [FindingCandidate(key=f"risk_{f.kind}", fact=f.text, template_meaning=_RISK_MEANING.get(f.kind, "Watch this supplier")) for f in ctx.get("flags") or []]
        cover = _cover(ctx)
        out += [cover] if cover else []
    sups = [r.id for r in item.refs if r.type == "supplier"]
    ident = ctx.get("ident") or (sups[0] if len(sups) == 1 else None)      # any case about one supplier: its own delivery record
    streak = _streak(session, ident, ctx.get("who") or naming.supplier_name(session, ident)) if ident else None
    return out + ([streak] if streak and not any(c.key == "risk_late_delivery" for c in out) else [])
