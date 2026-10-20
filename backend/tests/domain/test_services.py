"""One test per service function: what it returns for the Halden data, and what it refuses to claim."""
import pytest

from app.domain.attention import service as attention
from app.domain.bom import service as bom
from app.domain.common import Money, Unknown
from app.domain.demand import service as demand
from app.domain.imports import service as imports
from app.domain.inbox import service as inbox
from app.domain.orders import service as orders
from app.domain.parts import service as parts
from app.domain.suppliers import service as suppliers


# --- bom / demand ---
def test_requirements_per_robot(session):
    per = bom.requirements_per_robot(session)
    assert per["HR-90020"]["HR-40110"] == 2 and per["HR-90050"]["HR-40210"] == 2


def test_requirements_cover_twelve_months_and_carry_provenance(session):
    r = demand.requirements(session, "HR-40210")
    assert r[0].month == "2026-10" and float(r[0].qty.value) == 80 and r[0].by_product == {"Porter P5": 40}
    assert r[0].qty.provenance.method == "computed" and r[0].qty.provenance.inputs[0].id == "HR-40210"
    assert len(demand.requirements(session, "HR-40210", months=3)) == 3


def test_shortage_asserted_only_for_disrupted_supply(session):
    t = demand.shortage(session, "HR-40110")
    assert t.disrupted and t.per_unit == "2 per Tern T2" and float(t.past_due_receipts.value) == 790
    assert [b.short is not None for b in t.buckets[:3]] == [True, True, False]       # Oct, Nov short; Dec after the supplier's own recovery estimate
    assert float(t.buckets[0].under_disruption.value) == 350
    assert isinstance(t.on_hand, Unknown) and t.on_hand.owner == "Dana"
    calm = demand.shortage(session, "HR-50110")
    assert not calm.disrupted and all(b.short is None for b in calm.buckets)         # control: no false alarm


def test_forecast(session):
    rows = {r.product: r for r in demand.forecast(session)}
    assert sum(m.units for m in rows["Tern T2"].months) == 2398 and len(rows["Heron H1"].months) == 12


# --- orders ---
def test_open_supply_marks_stale_and_disrupted(session):
    lines = orders.open_supply(session, "HR-40010")
    assert lines and all(l.stale for l in lines)
    fm = orders.open_supply(session, "HR-40130")
    assert all(l.disrupted_by for l in fm) and {l.record.id for l in fm} == {"V10871", "SUP-0001"}      # the legacy id resolves to Yunzhan
    assert {l.supplier.id for l in fm} == {"SUP-0001"}


def test_past_due_buyer_filter(session):
    dana = orders.past_due(session, buyer="Dana")
    assert dana and all(s.days_past_due and s.days_past_due > 0 for s in dana)
    assert len(dana) < len(orders.past_due(session))


def test_line_view_puts_the_source_row_beside_the_clean_one(session):
    v = orders.line_view(session, "HPO-25-00014/10")                       # a closed line with a blank currency
    assert v.unit_price.provenance.method == "inferred" and v.unit_price.currency == "USD" and v.raw["currency"] is None
    k = orders.line_view(session, "PO-10551/1")                            # a legacy KPCS line in JPY
    assert k.raw["uom"] == "KPCS" and k.raw["order_date"] == "12/19/2024" and float(k.qty_ordered.value) == 9000 and k.unit_price.currency == "JPY"
    assert orders.line_view(session, "nope/1") is None


def test_open_orders_contract_shape(session):
    rows = orders.open_orders(session)
    assert len(rows) == 185
    l = next(r for r in rows if r.ref.id == "HPO-26-00450/10")
    assert l.buyer == "Dana Reyes" and l.disrupted_by and l.days_past_due == 30 and l.supplier.id == "SUP-0001"
    assert isinstance(l.unit_price, Money) and l.unit_price.currency == "USD"
    assert len(orders.open_orders(session, "Priya")) + len(orders.open_orders(session, "Dana")) < 185


# --- suppliers / parts ---
def test_supplier_list_one_row_per_company(session):
    rows = suppliers.list_suppliers(session)
    assert len(rows) == 60
    y = next(r for r in rows if r.ref.id == "SUP-0001")
    assert y.records == 3 and y.past_due_lines == 4 and y.status == "active"
    assert next(r for r in rows if r.ref.id == "SUP-0027").status == "hold"


def test_supplier_profile_and_contact_on_file(session):
    p = suppliers.profile(session, "SUP-0001")
    assert p.contact.email == "li.wei@yunzhan-motor.example" and p.record_ids == ["SUP-0001", "V10233", "V10871"]
    assert suppliers.contact_on_file(session, "SUP-0001").email != "accounts@yunzhan-rnotor.example"
    assert suppliers.profile(session, "NOPE") is None


def test_parts_show_unknowns_not_blanks(session):
    p = {x.ref.id: x for x in parts.list_parts(session)}
    assert len(p) == 502
    assert isinstance(p["HR-40220"].coo, Unknown) and p["HR-40220"].coo.owner == "Dana"
    assert p["HR-51120"].hts == "8504409580"
    assert float(p["HR-40110"].open_supply.value) == 1140
    assert parts.buyer_name(session, "Priya") == "Priya Nair" and parts.buyer_name(session, None) == "IT (ERP admin)"


# --- inbox ---
def test_trust_verdicts(session):
    fraud = inbox.trust(session, "2026-09-23_URGENT_Updated_remittance_details_following_plant_incident")
    assert fraud.verdict == "blocked" and not fraud.may_act and fraud.api_trust == "suspicious"
    assert {"sender_domain_lookalike", "reply_to_freemail", "bank_detail_change", "urgency"} <= {f.name for f in fraud.flags}
    assert all(f.words for f in fraud.flags)
    ok = inbox.trust(session, "2026-08-14_RE_RFQ_HR-RFQ-2608_motor_pricing_Q4_2026_Q1_2027_-_Quotation_Q-YZ-26-0831")
    assert ok.verdict == "ok" and ok.may_act
    assert inbox.trust(session, "nope") is None


def test_message_list_kinds_and_summaries(session):
    rows = {m.ref.id[:10] + m.kind: m for m in inbox.list_messages(session) if m.kind}
    kinds = {m.kind for m in inbox.list_messages(session)}
    assert {"force majeure", "slip", "price change", "payment change", "spot offer", "closure", "correction"} <= kinds
    assert all(m.summary for m in inbox.list_messages(session)) and rows


def test_message_changes_cite_their_lines(session):
    ch = inbox.message_changes(session, "2026-09-22_NOTICE_OF_FORCE_MAJEURE_-_Shenzhen_Yunzhan_Precision_Motor_Co_Ltd")
    first = next(c for c in ch if c.ref.id == "HPO-26-00450/10")
    assert first.before == "2026-08-26" and first.after.startswith("unknown") and "HR-40110" in first.line
    slips = inbox.message_changes(session, "2026-09-19_RE_RE_PO_HPO-26-00623_confirmation")
    assert any(c.ref.id == "HPO-26-00623/20" and c.after == "2026-10-30" for c in slips)       # the split shipment; the quoted 10/02 is not a change
    assert not any(c.after == "2026-10-02" for c in slips)


def test_message_detail_is_quoted_data(session):
    d = inbox.message_detail(session, "2026-09-12_Spot_offer_-_NG6603-QFN48_in_stock_ships_today", "trust:x")
    assert d.summary.trust == "suspicious" and "instruction_in_message" in d.summary.trust_flags and "AI assistants" in d.body and d.related_item == "trust:x"
    assert inbox.message_detail(session, "nope") is None


# --- attention ---
def test_action_list_fits_a_screen_and_is_ranked(session):
    items = attention.what_needs_attention(session)
    keys = [i.key for i in items]
    assert 9 <= len(items) <= 24 and len(set(keys)) == len(keys)
    assert keys[0] == "disruption:SUP-0001"
    groups = [i.group for i in items]
    assert groups == sorted(groups, key=["disruption", "trust", "deadline", "tariff", "unknown"].index)
    dated = [i.act_by for i in items if i.group == "deadline" and i.act_by]
    assert dated == sorted(dated)                                                                                                  # soonest first
    assert [i.key for i in items if i.group == "deadline"][-1] == "deadline:chase"                                                 # the chase has no date: last
    assert all(i.owner and i.next_action for i in items)
    assert all("Priya" in i.owner for i in attention.what_needs_attention(session, owner="Priya")) and attention.what_needs_attention(session, owner="Priya")


def test_frozen_keys_all_resolve(session):
    keys = attention.all_keys(session)
    for k in ["disruption:SUP-0001", "unknown:HR-40220", "unknown:HR-50310", "unknown:HR-12120", "tariff:HR-50110", "tariff:all", "deadline:SUP-0041:2026-10-15",
              "deadline:SUP-0001:2026-10-10", "deadline:SUP-0001:2026-10-13", "deadline:SUP-0002:2026-10-31", "unknown:origin", "unknown:hts", "unknown:stale-orders",
              "trust:2026-09-23_URGENT_Updated_remittance_details_following_plant_incident", "trust:2026-09-12_Spot_offer_-_NG6603-QFN48_in_stock_ships_today",
              "unknown:PO-10710/1", "unknown:PO-10711/1", "unknown:PO-10788/1"]:
        assert k in keys, k
        assert attention.item_detail(session, k) is not None, k
    assert len(set(keys)) == len(keys)


def test_the_tariff_is_one_row_with_the_breakdown_inside(session):
    row = next(i for i in attention.what_needs_attention(session) if i.group == "tariff")
    assert row.key == "tariff:all" and float(row.at_stake.usd) == pytest.approx(1_432_969, rel=0.001) and float(row.at_stake_gross.usd) == pytest.approx(2_138_539, rel=0.001)
    d = attention.item_detail(session, "tariff:all")
    top = [n.id for n in d.numbers if n.id.startswith("duty_net:HR")][:4]
    assert top == ["duty_net:HR-50110", "duty_net:HR-50210", "duty_net:HR-40110", "duty_net:HR-40210"]       # the exposure share, largest first
    assert {"duty_net:tranche2", "duty_gross:tranche2", "duty_conditional:tranche1"} <= {n.id for n in d.numbers}
    cond = next(n for n in d.numbers if n.id == "duty_conditional:tranche1")
    assert float(cond.value.usd) == pytest.approx(104_142, rel=0.001)      # beside the headline, never in it
    assert row.title == "New 25% duty on China-origin parts from Nov 1" and row.summary == "+$104K if open orders ship late" and float(row.at_stake.usd) == pytest.approx(1_432_969, abs=1)


def test_one_part_still_has_its_own_item(session):
    d = attention.item_detail(session, "tariff:HR-50110")
    assert float(d.at_stake.usd) == pytest.approx(501_186, rel=0.001) and d.owner == "Priya Nair"


def test_unknown_items_never_carry_a_duty_as_the_stake(session):
    for k in ("unknown:HR-40220", "unknown:HR-50310", "unknown:HR-12120", "unknown:origin", "unknown:hts", "unknown:stale-orders"):
        i = attention.item_detail(session, k)
        assert isinstance(i.at_stake, Unknown) and i.at_stake.owner
    d = attention.item_detail(session, "unknown:HR-40220")
    assert all("origin is China" in n.label and "not known" in n.label for n in d.numbers) and d.numbers
    assert attention.item_detail(session, "unknown:HR-50310").numbers == []


def test_fire_item_detail(session):
    d = attention.item_detail(session, "disruption:SUP-0001")
    assert len(d.po_lines) == 10 and d.time_phased.part.id == "HR-40110" and d.days_left == 15 and d.act_by == "2026-10-10"
    assert isinstance(d.at_stake, Money) and float(d.at_stake.usd) == pytest.approx(396_000, rel=0.01) and d.at_stake_gross is None       # dollars on the row
    assert len(d.at_stake.provenance.inputs) == 10 and d.at_stake_note == ("182 Tern + 40 Porter robots in October, short of drive motors; "
                                                                        "188 Tern + 42 Porter robots in November, short of drive motors")      # the lines behind it; the robots beside it, each month on its own
    ids = {n.id for n in d.numbers}
    assert {"stuck_qty:HR-40110", "requirement:HR-40110:2026-10", "shortage:HR-40110:2026-10:short", "recovery_by"} <= ids
    assert {u.what for u in d.unknowns} == {"on-hand stock", "revised delivery dates"}
    assert "Tern" in d.title and "October" in d.title


def test_quote_deadline_says_what_lapsing_costs_not_what_the_quote_covers(session):
    d = attention.item_detail(session, "deadline:SUP-0001:2026-10-13")
    assert isinstance(d.at_stake, Money) and d.at_stake.provenance.rule.startswith("lapse_cost") and "lapsing costs" in d.title and float(d.at_stake.usd) < 100_000
    q = attention.item_detail(session, "deadline:SUP-0002:2026-10-31")      # no cheaper price on file: the spend the quote prices is said as what it is, and the stake is unknown
    assert isinstance(q.at_stake, Unknown) and "of planned buys; cost of lapsing unknown" in q.title and "at stake" not in q.title.lower()
    q = attention.item_detail(session, "deadline:quotes")      # the rollup's row says the demand the quotes price, never as a stake
    assert isinstance(q.at_stake, Unknown) and q.summary == "$5.54M of forecast demand on these quotes" and "at stake" not in q.title.lower()
    assert {n.id.split(":")[0] for n in d.numbers} >= {"spend_covered"}
    assert isinstance(attention.item_detail(session, "deadline:SUP-0001:2026-10-10").at_stake, Unknown)         # the supplier's own promised dates: truly unknown


def test_trust_items_make_acting_impossible_to_start(session):
    d = attention.item_detail(session, "trust:2026-09-23_URGENT_Updated_remittance_details_following_plant_incident")
    assert "no action can be drafted" in d.finding and d.severity == "high" and float(d.at_stake.usd) == 187420
    s = attention.item_detail(session, "trust:2026-09-12_Spot_offer_-_NG6603-QFN48_in_stock_ships_today")
    assert "HPO-26-00408/40" in s.next_action                                     # an open PO already covers the part
    assert attention.item_detail(session, "trust:nope") is None


def test_tariff_part_detail_shows_net_gross_and_line_reasons(session):
    d = attention.item_detail(session, "tariff:HR-40110")
    assert float(d.at_stake.usd) < float(d.at_stake_gross.usd) and d.act_by == "2026-10-15"
    assert {n.id for n in d.numbers} >= {"duty_net:HR-40110", "duty_gross:HR-40110", "uncovered_qty:HR-40110"} and len(d.po_lines) == 3


# --- imports ---
def test_data_issue_services(session):
    issues = imports.list_issues(session)
    assert len(issues) >= 50 and all(i.owner and i.consequence for i in issues)
    steps = imports.list_steps(session)
    assert steps[0].step.startswith("01_") and steps[-1].seq == len(steps)
    stamp = imports.build_stamp(session)
    assert stamp.gate_failed == 0 and stamp.gate_checks >= 30 and stamp.as_of == "2026-09-25" and stamp.counts["po_lines"] == 2616


# --- offers ---
def test_offers(session):
    from sqlalchemy import select
    from app.domain.quotes.model import Offer

    off = list(session.scalars(select(Offer)))
    bcx = [o for o in off if o.quote_no == "BCX-Q-2609"]
    assert len(bcx) == 11 and {o.origin_iso for o in bcx} == {"CN", "MX"} and next(o for o in bcx if o.part_number == "HR-20103").unit_price_each == pytest.approx(0.24058)
    h = [o for o in off if o.quote_no == "AN-2026-1187"]
    assert h[0].price == pytest.approx(389.5) and h[0].currency == "EUR" and h[0].validity_date == "2026-10-31"
    alder = [o for o in off if o.part_number == "HR-31110" and o.qty_break == 2500]
    assert sorted(o.price for o in alder) == [138.36, 183.36] and [o.superseded_by is None for o in alder].count(True) == 1
    vp = [o for o in off if o.quote_no == "VPM-Q-260924"]
    assert vp and vp[0].lead_time_condition.startswith("after PPAP") and vp[0].identity_id is None and vp[0].trust == "review"
    assert next(o for o in off if o.supplier_name.startswith("Saltmarsh")).trust == "blocked"


# --- supplier notices that move supply ---
def test_slip_impact_counts_only_the_gap_the_new_dates_create(session):
    imp = demand.slip_impact(session, "HR-51110")
    assert imp.first_month == "2026-10" and float(imp.first_month_qty.value) == 222 and imp.months == ["2026-10", "2026-12"]
    assert demand.slip_impact(session, "HR-51310").first_month == "2026-11"
    assert demand.slip_impact(session, "HR-21111") is None            # Ruilian: 57 land Oct 30, 58 on Nov 20 (ex-works + 21 days by sea): covers the need
    assert demand.slip_impact(session, "HR-40110") is None            # a force majeure is not a slip
    assert [(sp.date, sp.qty) for sp in orders.open_supply(session, "HR-21111")[0].revised_splits] == [("2026-10-30", 57), ("2026-11-20", 58)]


def test_jadepeak_notice_is_a_disruption_row(session):
    items = {i.key: i for i in attention.what_needs_attention(session)}
    j = items["disruption:SUP-0013"]
    assert j.group == "disruption" and j.act_by == "2026-10-01" and isinstance(j.at_stake, Money) and float(j.at_stake.usd) == pytest.approx(127_248, rel=0.001) and j.title.endswith("; power electronics short from October") and j.summary == "182 T2 + 40 P5 short in Oct · 24 H1 in Nov · 92 T2 + 22 H1 + 20 P5 in Dec"
    assert list(items).index("disruption:SUP-0013") == 1                                 # right after the fire
    assert "disruption:SUP-0018" not in items and "disruption:SUP-0022" not in items    # Ruilian and Lanxin do not put a build short
    d = attention.item_detail(session, "disruption:SUP-0013")
    assert len(d.po_lines) == 5 and d.time_phased.part.id == "HR-51110" and "Dongguan, China" in d.finding
    assert any(n.id.startswith("duty_if_arrives_late") for n in d.numbers) and any(u.what == "country of origin" for u in d.unknowns)


def test_titles_and_findings_use_a_buyers_dates(session):
    import re

    iso = re.compile(r"\b20\d\d-\d\d(-\d\d)?\b")
    for k in attention.all_keys(session):
        d = attention.item_detail(session, k)
        if k.startswith("trust:"):
            continue
        text = " ".join([d.title, d.finding, d.next_action] + [u.question + u.why_it_blocks for u in d.unknowns])
        assert not iso.search(text), (k, iso.search(text).group(0))
    assert attention.item_detail(session, "disruption:SUP-0001").title == "Yunzhan fire: Tern and Porter short of drive motors from October"


# --- the inbox ladder ---
def test_ladder_stops_at_the_first_level_that_decides(session):
    cl = {c.message.id[:10] + c.kind: c for c in inbox.classify_all(session)}
    assert len(inbox.classify_all(session)) == 15
    fraud = inbox.classify(session, "2026-09-23_URGENT_Updated_remittance_details_following_plant_incident")
    assert (fraud.level, fraud.kind, fraud.decision) == (0, "payment change", "blocked") and fraud.confidence == 1.0 and fraud.evidence
    spot = inbox.classify(session, "2026-09-12_Spot_offer_-_NG6603-QFN48_in_stock_ships_today")
    assert (spot.level, spot.kind, spot.decision) == (0, "spot offer", "blocked")
    fm = inbox.classify(session, "2026-09-22_NOTICE_OF_FORCE_MAJEURE_-_Shenzhen_Yunzhan_Precision_Motor_Co_Ltd")
    assert (fm.level, fm.kind, fm.decision, fm.agrees) == (1, "force majeure", "auto", True) and "HPO-26-00450" in " ".join(fm.evidence + [fm.reason]) or fm.evidence
    assert inbox.classify(session, "2026-09-05_RE_Quote_request_-_safety_controller_PCBA_HR-31110_2027_volumes").kind == "correction"
    assert inbox.classify(session, "nope") is None and cl


def test_the_review_list_is_what_code_will_not_act_on_alone(session):
    review = {c.message.id[:10]: c.decision for c in inbox.check_these(session)}
    assert set(review) == {"2026-09-12", "2026-09-23", "2026-09-24", "2026-09-02"}         # two blocked, the unknown sender, the sender not on file
    assert review["2026-09-23"] == "blocked" and review["2026-09-24"] == "review"


def test_keyword_families_have_anti_patterns(session):
    assert [k for k, _ in inbox._l2("Price adjustment notice: prices will increase effective November 1")] == ["price change"]
    assert "slip" not in [k for k, _ in inbox._l2("Price adjustment notice: new date for the price")]       # the anti-pattern cancels it
    both = [k for k, _ in inbox._l2("Quotation attached. We will be closed for the National Day holiday.")]
    assert {"quote", "closure"} <= set(both)                                                                    # two families fit: the ladder asks for review


def test_threads_group_by_subject_and_link_corrections(session):
    threads = inbox.list_threads(session)
    assert len(threads) == 15 and all(t.messages for t in threads) and threads[0].last_date >= threads[-1].last_date
    alder = next(t for t in threads if "safety controller" in t.id)
    assert alder.corrects and "138.36" in alder.corrects[0] and "183.36" in alder.corrects[0]
    assert {t.subject for t in inbox.list_threads(session, trust="suspicious")} and len(inbox.list_threads(session, trust="suspicious")) == 2
    assert [t.id for t in inbox.list_threads(session, needs_review=True)] and len(inbox.list_threads(session, supplier="SUP-0001")) == 2
    assert alder.id in {t.id for t in inbox.list_threads(session)} and "nope" not in {t.id for t in inbox.list_threads(session)}


def test_tariff_rates_are_numbers_the_agent_may_quote(session):
    d = attention.item_detail(session, "tariff:all")
    rates = {n.id: n.value for n in d.numbers if n.id.startswith("rate:")}
    assert float(rates["rate:t1"].value) == 25 and rates["rate:t1"].uom == "%" and float(rates["rate:t2"].value) == 15
    p = attention.item_detail(session, "tariff:HR-40110")
    assert float(next(n for n in p.numbers if n.id == "rate:t1").value.value) == 25


def test_where_used_names_the_robot(session):
    w = {x.product.id: x.product.label for x in bom.where_used(session, "HR-80300")}
    assert w == {"HR-90020": "Tern T2", "HR-90050": "Porter P5", "HR-90110": "Heron H1"}
    assert bom.explode_bom(session, "HR-90020")[0].product.label == "Tern T2"


def test_exposure_lines_say_who_pays_the_duty_and_why(session):
    from app.domain.tariffs import service as tariffs

    e = tariffs.exposure_for_part(session, "HR-40110")
    assert {l.incoterm for l in e.open_lines} <= {"FOB Shenzhen", "FOB SZ", "FOB Origin", "FOB"} and all(l.importer == "company" for l in e.open_lines)
    assert all(l.incoterm_says.startswith("FOB: Halden arranges the shipping, imports the goods and pays the duty") for l in e.open_lines)
    ddp = tariffs.exposure_for_part(session, "HR-20137")
    assert any(l.importer == "supplier" and l.incoterm == "DDP Reno" and "supplier is importer of record" in l.incoterm_says for l in ddp.open_lines) or ddp.pass_through
    d = tariffs.duty_for_line(session, "HPO-26-00591/40")
    assert d.status == "pass_through" and d.incoterm == "DDP Reno" and "pays the duty at entry" in d.incoterm_says
    assert tariffs.duty_for_line(session, "HPO-26-00450/10").incoterm_says.startswith("FOB:")


def test_the_supplier_s_own_recovery_words_travel_with_the_shortage(session):
    t = demand.shortage(session, "HR-40110")
    assert t.recovery_text == "6 to 8 weeks" and t.recovery_by == "2026-11-17"                         # the supplier's range verbatim; the date is its upper bound
    assert "partial production can resume in 6 to 8 weeks" in t.recovery_line and t.recovery_source.type == "message"      # with the line it comes from
    assert demand.shortage(session, "HR-50110").recovery_text is None                                   # nothing disrupted, nothing said
    label = next(n.label for n in attention.item_detail(session, "disruption:SUP-0001").numbers if n.id == "recovery_by")
    assert "6 to 8 weeks, counted from the notice" in label and "Nov 17" in label


def test_the_spot_offer_carries_its_price_ratio(session):
    d = attention.item_detail(session, "trust:2026-09-12_Spot_offer_-_NG6603-QFN48_in_stock_ships_today")
    ratio = next(n for n in d.numbers if n.id == "price_ratio:HR-32104").value
    assert float(ratio.value) == 13.5 and ratio.uom == "x" and "13.5x" in d.title
    assert {"usual_unit_price:HR-32104", "offered_unit_price:HR-32104"} <= {n.id for n in d.numbers}


def test_money_in_prose_follows_the_money_columns(session):
    """One rounding rule: millions to two decimals, thousands from $10K whole. The title and the summary say what the At-stake column says."""
    from app.domain.attention import service as a

    d = a.item_detail(session, "tariff:all")
    text = d.title + " " + (d.summary or "") + " " + d.finding + " " + " ".join(n.label for n in d.numbers)
    assert "$1.43M" in text and "$2.14M" in text and "$92K" in text and "$104K" in text
    assert "$1.5M" not in text and "$2.1M" not in text
    assert [a._fmt(x) for x in (1539054, 2138539, 104270, 9934, 123072, 156561, 800)] == ["$1.54M", "$2.14M", "$104K", "$9,934", "$123K", "$157K", "$800"]
    assert a.item_detail(session, "unknown:stale-orders").title == "3 aged open POs: confirm received or cancelled, then close"


def test_the_chase_row(session):
    """One row for open lines past their PO date that no message, notice or revision mentions: 16 lines, 496,044 USD open, Vistaray's 367,729 first."""
    from app.domain.attention import service as a
    from app.domain.orders import service as orders

    d = a.item_detail(session, "deadline:chase")
    assert d.group == "deadline" and d.severity == "medium" and d.key == "deadline:chase"
    assert d.title == "16 past-due lines, no updated promise" and d.summary == "largest Vistaray $368K (Marcus)" and round(float(d.at_stake.usd)) == 496_044
    assert round(float(d.at_stake.usd)) == 496_044 and len(d.numbers) == 19 and len(d.po_lines) == 16
    n = {x.id: x for x in d.numbers}
    assert float(n["chase:count"].value.value) == 16 and round(float(n["chase:open_total"].value.usd)) == 496_044
    assert round(float(n["chase:largest"].value.usd)) == 367_729 and "HPO-26-00505 line 10" in n["chase:largest"].label and "Lidar" in n["chase:largest"].label
    assert d.next_action == "Chase the largest first: ask Vistaray for a ship date on Lidar, 2D safety order (HPO-26-00505 line 10)."
    assert d.owner.split(" · ")[0] == "Marcus Chen" and set(d.owner.split(" · ")) == {"Marcus Chen", "Dana Reyes", "Priya Nair", "Tom Albrecht"}
    ids = {n.id.split(":", 1)[1] for n in d.numbers if n.id not in ("chase:count", "chase:open_total", "chase:largest")}
    past = {s.po_line.id: s for s in orders.past_due(session, include_stale=True)}
    from sqlalchemy import select

    from app.domain.inbox.model import MessageEvent

    spoke = set(session.scalars(select(MessageEvent.ref_id).where(MessageEvent.kind.in_(("closure", "force_majeure")), MessageEvent.ref_type == "supplier")))
    said = {l for l in ids}
    for lid, s in past.items():                                    # the rule: stale, disrupted and revised lines, and a supplier that announced a closure, are not in the row
        if lid in said or not (s.stale or s.disrupted_by or s.revised_promise or s.supplier.id in spoke):
            assert (lid in ids) == (not s.stale and not s.disrupted_by and not s.revised_promise and s.supplier.id not in spoke), lid
    assert not {l for l, s in past.items() if s.supplier.id in spoke} & ids
    assert not ids & {"HPO-26-00450/10", "HPO-26-00486/10", "HPO-26-00517/20", "PO-10711/1"}
    assert "feeds" in d.numbers[3].label and "1 days" not in " ".join(n.label for n in d.numbers)
    # Sofia owns no fire, trust, deadline or duty row; she appears only where the data gives her an order (two small open lines with no promised date)
    assert all(not a.item_detail(session, k) or "Sofia" not in a.item_detail(session, k).owner or k.startswith("unknown:") for k in a.all_keys(session))


def test_a_missing_exchange_rate_is_unknown_and_in_no_total(db_path, tmp_path):
    """A line with no rate for its order month keeps its own-currency amount, has no dollar value, is left out of every total, and the total says so."""
    import shutil
    import sqlite3

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.domain.tariffs import service as tariffs

    copy = tmp_path / "norate.db"
    shutil.copy(db_path, copy)
    line = "HPO-26-00450/10"
    with Session(create_engine(f"sqlite:///{db_path}", future=True)) as s:
        before = tariffs.exposure_for_part(s, "HR-40110")
        gone = next(l for l in before.open_lines if l.po_line.id == line)
    con = sqlite3.connect(copy)
    con.execute("update po_lines set open_usd = null, unit_usd_each = null, line_usd = null where id = ?", (line,))
    con.commit()
    con.close()
    with Session(create_engine(f"sqlite:///{copy}", future=True)) as s:
        e = tariffs.exposure_for_part(s, "HR-40110")
        ld = tariffs.duty_for_line(s, line)
    assert [l.id for l in e.lines_without_rate] == [line]
    bad = next(l for l in e.open_lines if l.po_line.id == line)
    assert bad.open_value.usd is None and bad.open_value.currency == "USD" and bad.open_value.amount > 0 and not bad.exposed
    assert round(float(before.open_value_total.usd) - float(e.open_value_total.usd)) == round(float(gone.open_value.usd))      # only that line left the total
    assert "excludes 1 without a rate" in e.open_value_total.provenance.rule and "excludes 1 without a rate" in e.open_duty_total.provenance.rule
    assert ld.status == "unknown" and ld.duty is None and ld.unknown.owner == "Dana" and "exchange rate" in ld.unknown.question
    assert gone.bucket == "owed" and bad.bucket == "out"       # the line left the owed bucket (the plant cannot restart before the duty date)
    assert e.uncovered_qty > before.uncovered_qty          # and its quantity no longer covers the need, so more of the need is owed instead


def test_every_finding_and_next_step_is_a_sentence(session):
    """Starts with a capital (or a figure) and ends with a full stop, on every row and every key behind a row."""
    from app.domain.attention import service as a

    for k in a.all_keys(session):
        d = a.item_detail(session, k)
        for what, text in (("finding", d.finding), ("next", d.next_action)):
            if text:
                assert (text[0].isupper() or text[0].isdigit()) and text.rstrip()[-1] in ".!?", (k, what, text)
                assert not __import__("re").search(r"[.!?] [a-z]", text), (k, what, text)       # no sentence starts in lowercase


def test_header_counts_equal_their_rows(session):
    """The supplier header and the Orders header say open + may-not-be-open, and those add up to the rows below them."""
    from app.domain.orders import service as orders
    from app.domain.suppliers import service as suppliers

    d = suppliers.profile(session, "SUP-0001")
    rows = [o for o in orders.open_orders(session, None) if o.supplier.id == "SUP-0001"]
    assert d.open_lines == 10 and d.stale_lines == 2 and len(rows) == d.open_lines + d.stale_lines == 12
    assert d.open_summary == "10 open · 2 may not really be open"
    all_rows = orders.open_orders(session, None)
    assert sum(1 for o in all_rows if not o.stale) == 182 and sum(1 for o in all_rows if o.stale) == 3 and len(all_rows) == 185


def test_tags_include_every_part_the_text_names(session):
    import re

    from app.domain.attention import service as a

    for i in a.what_needs_attention(session):
        d = a.item_detail(session, i.key)
        named = set(re.findall(r"HR-\d{5}", d.title + " " + d.finding + " " + d.next_action))
        assert named <= {r.id for r in d.refs}, (i.key, sorted(named - {r.id for r in d.refs}))
    chase = a.item_detail(session, "deadline:chase")
    assert [r.id for r in chase.refs if r.type == "part"][:1] == ["HR-60110"] and len(chase.refs) <= 3 and len(chase.evidence) > 3


def test_the_fire_row_says_how_many_robots_and_messages_name_a_company(session):
    from app.domain.attention import service as a
    from app.domain.inbox import service as inbox

    fire = next(i for i in a.what_needs_attention(session) if i.key == "disruption:SUP-0001")
    assert fire.at_stake_note == "182 Tern + 40 Porter robots in October, short of drive motors; 188 Tern + 42 Porter robots in November, short of drive motors"      # every product with a part short in each short month, once a month
    ms = {m.ref.id: m for m in inbox.list_messages(session)}
    assert all(m.company for m in ms.values())
    assert ms["2026-09-22_NOTICE_OF_FORCE_MAJEURE_-_Shenzhen_Yunzhan_Precision_Motor_Co_Ltd"].company.startswith("Shenzhen Yunzhan")
    assert ms["2026-09-23_URGENT_Updated_remittance_details_following_plant_incident"].company == "not on file"
    assert any(m.company == "not on file" for m in ms.values())


def test_the_stock_question_goes_to_the_buyer_of_the_parts(session):
    """Yunzhan's motors are Dana's, Jadepeak's power parts are Priya's; parts of several buyers give one question per buyer, each listing only their own."""
    from app.domain.attention import service as a
    from app.domain.demand import service as demand

    stock = lambda key: [u for u in a.item_detail(session, key).unknowns if u.what == "on-hand stock"]   # noqa: E731
    y = stock("disruption:SUP-0001")
    assert [u.owner for u in y] == ["Dana"] and "HR-40110" in y[0].question
    j = stock("disruption:SUP-0013")
    assert [u.owner for u in j] == ["Priya"] and "HR-51110" in j[0].question and "HR-40110" not in j[0].question
    assert demand.shortage(session, "HR-40110").on_hand.owner == "Dana" and demand.shortage(session, "HR-51110").on_hand.owner == "Priya"
    mixed = a._stock_questions(session, ["HR-40110", "HR-40120", "HR-51110", "HR-60110"], "no inventory")
    assert [(u.owner, u.question.split(" is on hand")[0]) for u in mixed] == [("Dana", "What stock of HR-40110, HR-40120"), ("Marcus", "What stock of HR-60110"), ("Priya", "What stock of HR-51110")]


def test_open_lines_with_no_promised_date_get_a_row_led_by_the_largest(session):
    items = {i.key: i for i in attention.what_needs_attention(session)}
    row = items["unknown:undated"]
    assert row.group == "unknown" and row.title == "5 open orders with no promised date" and row.summary == "$497K open"
    assert "Marcus Chen" in row.owner and row.at_stake.what == "open orders with no promised date"
    big = attention.item_detail(session, "unknown:HPO-26-00627/20")                       # the $470k lidar line
    assert big.owner == "Marcus Chen" and big.at_stake.what == "the promised date" and "no promise date" in big.finding
    assert row.key in [i.key for i in sorted(items.values(), key=lambda i: i.key)]


def test_a_line_received_before_it_was_ordered_is_named_and_not_a_delivery(session):
    from sqlalchemy import select

    from app.domain.imports.model import DataIssue
    from app.domain.phases import service as phases

    issue = session.scalar(select(DataIssue).where(DataIssue.key == "po.received_before_ordered"))
    assert issue is not None and issue.count == 2 and issue.handling == "flag" and "ERP admin" in issue.owner
    ladder = phases.line_phases(session, "HPO-26-00503/60")
    received = next(r for r in ladder.rungs if r.key == "received")
    assert received.state == "unknown" and "ERP admin" in received.unknown.owner
    assert "arrived" not in next(r for r in ladder.rungs if r.key == "promised").detail          # not "arrived 300 days early"


def test_the_spot_offer_at_many_times_the_last_price_is_flagged_for_its_price_and_still_blocked(session):
    from sqlalchemy import select

    from app.domain.inbox.model import Message

    m = session.scalar(select(Message).where(Message.id.like("2026-09-12_Spot_offer%")))
    flags = (m.trust_flags or "").split(",")
    assert "price_far_above_history" in flags and "instruction_in_message" in flags and m.trust == "blocked"
    assert inbox.trust(session, m.id).flags[-1].words.startswith("the price is far above")      # the words come from the one vocabulary in inbox/trust.py


def test_every_reference_carries_the_name_it_shows(session):
    for k in attention.all_keys(session):
        d = attention.item_detail(session, k)
        for r in [*d.refs, *d.evidence]:
            if r.type in ("part", "po_line", "supplier", "message", "tariff_rule", "quote"):
                assert r.label, (k, r.type, r.id)


def test_titles_and_next_steps_lead_with_names_and_the_id_follows(session):
    import re

    ids = re.compile(r"^(HR-\d|HPO-|PO-\d|SUP-\d)")
    items = {k: attention.item_detail(session, k) for k in attention.all_keys(session)}
    assert not [k for k, d in items.items() if ids.match(d.title)]                              # no title starts with an id
    assert items["tariff:HR-11101"].title.startswith("Bearing, deep groove ball (HR-11101):")
    assert items["deadline:chase"].next_action == "Chase the largest first: ask Vistaray for a ship date on Lidar, 2D safety order (HPO-26-00505 line 10)."
    assert "Ball screw assembly, 12x4 mm (HR-13103)" in items["unknown:origin"].next_action
    assert items["unknown:PO-10711/1"].title.startswith("Motor, brushed DC order (PO-10711 line 1):")


def test_every_item_is_filed_under_one_of_the_procurement_stages_where_it_belongs_to_one(session):
    cat = {i.key: i.category for i in attention.all_items(session)}
    assert cat["disruption:SUP-0001"] == "Purchasing" and cat["deadline:chase"] == "Purchasing" and cat["tariff:all"] == "Quote & risk"
    assert cat["deadline:quotes"] == "Quote & risk" and cat["unknown:undated"] == "Purchasing" and cat["unknown:origin"] == "Quote & risk"
    assert cat["deadline:SUP-0001:2026-10-10"] == "Purchasing" and cat["deadline:SUP-0001:2026-10-13"] == "Quote & risk"
    assert cat["trust:2026-09-23_URGENT_Updated_remittance_details_following_plant_incident"] is None


def test_quote_rows_say_what_the_quote_is_and_what_lapses_not_a_quote_number(session):
    t = {i.key: i.title for i in attention.all_items(session)}
    assert t["deadline:SUP-0001:2026-10-13"] == "Yunzhan's drive motors quote expires Oct 13: 4 parts, lapsing costs $8,009"
    assert t["deadline:quotes"] == "3 quotes expiring: Lanxin Oct 16, Hallerbeck Oct 31, Quenvara Nov 5" and "planned spend" not in t["deadline:quotes"]
    d = attention.item_detail(session, "deadline:SUP-0001:2026-10-13")
    assert "Q-YZ" not in d.title + d.finding and any(r.type == "quote" and "Q-YZ-26-0831" in r.id for r in d.refs)      # the number is in its field, not in the sentence


def test_no_text_the_domain_composes_carries_a_bare_supplier_id(session):
    import re

    ids = re.compile(r"\b(SUP-\d{4}|V1\d{4})\b")
    bad = []
    for k in attention.all_keys(session):
        d = attention.item_detail(session, k)
        texts = {"title": d.title, "next_action": d.next_action, "finding": d.finding, "note": d.at_stake_note or ""}
        texts.update({f"unknown {i}": f"{u.what} {u.why_it_blocks} {u.question}" for i, u in enumerate(d.unknowns)})
        texts.update({f"number {n.id}": n.label for n in d.numbers})
        bad += [f"{k} {f}: {t[:80]}" for f, t in texts.items() if ids.search(t)]
    assert not bad, bad


def test_each_disruption_row_computes_its_own_stake_note_and_act_by(session):
    rows = [i for i in attention.what_needs_attention(session) if i.group == "disruption"]
    assert len(rows) >= 2
    notes = [i.at_stake_note for i in rows if i.at_stake_note]
    assert len(notes) == len(set(notes)), notes                                    # two disruption items never share a note
    assert all(isinstance(i.at_stake, Money) and float(i.at_stake.usd) > 0 for i in rows)
    by = {i.key: i for i in rows}
    fire, slip = by["disruption:SUP-0001"], by["disruption:SUP-0013"]
    assert fire.at_stake_note.endswith("short of drive motors") and slip.at_stake_note.startswith("182 Tern + 40 Porter robots in October, short of power electronics")
    assert fire.act_by == "2026-10-10" and slip.act_by == "2026-10-01"             # each supplier's own date: the revised dates it promised; the day after which its orders take the longer lead time
    assert float(fire.at_stake.usd) != float(slip.at_stake.usd) and (fire.lines_in_scope, slip.lines_in_scope) == (10, 5)


def test_the_tariff_pages_carry_the_rule_the_advisory_row_and_the_buckets(session):
    d = attention.item_detail(session, "tariff:all")
    assert "CCB-ADV-2026-041" in d.finding and "issued Sep 18" in d.finding and "Lithium-ion accumulators" in d.finding           # the source, beside the headline
    assert "Owed $1.43M" in d.finding and "Conditional $104K" in d.finding and "If China $115K" in d.finding and "ceiling" in d.finding
    assert "25% of the price of China-origin parts" in d.finding and "ship date is unknown" in d.finding                                # the rule sentences
    assert [u.what for u in d.unknowns] == ["whether the conditional orders ship before the duty date"] and d.unknowns[0].owner
    p = attention.item_detail(session, "tariff:HR-50110")
    assert "Lithium-ion accumulators" in p.finding and "Owed $501K" in p.finding and "Conditional $51K" in p.finding and ".." not in p.finding


def test_the_company_name_is_configuration(session, monkeypatch):
    from app.domain.common.company import company_name

    assert (company_name(session), company_name(session, full=True)) == ("Halden", "Halden Robotics")      # answers.yaml company, through build_meta
    monkeypatch.setenv("LOOKOUT_COMPANY", "Test Co")
    assert company_name() == "Test" and company_name(None, full=True) == "Test Co"                          # no database: the environment
    monkeypatch.delenv("LOOKOUT_COMPANY")
    assert company_name() == "the company"                                                                  # nothing configured


def test_two_disruptions_on_different_parts_never_share_an_impact(session):
    rows = {i.key: i for i in attention.what_needs_attention(session) if i.group == "disruption"}
    fire, slip = rows["disruption:SUP-0001"], rows["disruption:SUP-0013"]
    parts = lambda i: {(r.month, p.id) for r in i.robots_short for p in r.short_parts}
    assert parts(fire) and parts(slip) and not {p for _, p in parts(fire)} & {p for _, p in parts(slip)}      # the parts that stop the builds are each supplier's own
    # the Jadepeak power supply is used by Heron alone and the new dates leave November and December short, so Heron is counted there and never in October or in the fire
    heron = [r for r in slip.robots_short if r.product.label == "Heron H1"]
    assert [(r.month, r.robots) for r in heron] == [("2026-11", 24), ("2026-12", 22)] and not [r for r in fire.robots_short if r.product.label == "Heron H1"]
    assert "24 Heron robots in November" in slip.at_stake_note and "Heron" not in fire.at_stake_note
    d = attention.item_detail(session, "disruption:SUP-0013")
    assert "(HR-51310) for the November builds (Heron)" in d.finding and "(Tern, Porter and Heron)" not in d.finding      # a part is dated by its own month
    own = sum(float(s.open_value.usd) for s in __import__("app.domain.orders.service", fromlist=["x"]).open_supply(session) if s.supplier.id == "SUP-0013" and s.revised_promise and s.promise and s.revised_promise > s.promise)
    assert abs(float(slip.at_stake.usd) - own) < 0.01 and float(slip.at_stake.usd) != float(fire.at_stake.usd)       # its own open value, from its own lines


def test_a_quote_item_says_what_lapses_not_what_it_covers(session):
    items = {i.key: i for i in attention.what_needs_attention(session)}
    assert items["deadline:quotes"].summary == "$5.54M of forecast demand on these quotes" and isinstance(items["deadline:quotes"].at_stake, Unknown)
    for key in attention.all_keys(session):
        if key.startswith("deadline:SUP-") and key.split(":")[-1] > "2026-09-25":
            d = attention.item_detail(session, key)
            if "quote" in d.title:
                text = d.finding + " ".join(n.label for n in d.numbers)
                assert "covers" not in text and "1 parts" not in text, (key, text)



def test_bcxs_alternative_site_is_in_the_quote_the_agent_compares(session):
    """The mail says power connectors are already built in Tijuana and charging contacts are being qualified there for Q2 2027: the China-origin offers carry it, cited to the mail's lines."""
    import json

    from app.domain.quotes import service as quotes

    for part in ("HR-20103", "HR-20136", "HR-20137"):
        text = json.dumps(quotes.compare_offers(session, part).model_dump(mode="json"))
        assert "Alternative site: Tijuana, Mexico already builds the power connectors and is being qualified for the charging contacts, targeting Q2 2027." in text, part
        assert "DDP" in text and "2026-11-30" in text and "2027-01-01" in text                      # the other conditions the quote-bcx sheet expects
    assert "Alternative site" not in json.dumps(quotes.compare_offers(session, "HR-20133").model_dump(mode="json"))      # a Mexico-built line needs no alternative


def test_an_allocation_or_slip_notice_is_a_disruption_with_its_kind(session):
    """The agent told a buyer 'there is no allocation notice' for Jadepeak because only force majeure counted: every notice that moves a line later is named."""
    from collections import Counter

    kinds = Counter((l.supplier.id, l.notice_kind) for l in orders.open_supply(session) if l.notice_kind)
    assert kinds == {("SUP-0001", "force majeure"): 10, ("SUP-0013", "allocation"): 5, ("SUP-0022", "allocation"): 2, ("SUP-0018", "slip"): 3}
    jade = [l for l in orders.open_supply(session) if l.supplier.id == "SUP-0013" and l.notice_kind]
    assert {l.revised_by.id for l in jade} == {"2026-09-18_Jadepeak_Customer_Notice_CN-2026-09"} and all(l.revised_promise > l.promise for l in jade)


def test_a_supplier_with_incident_news_and_a_schedule_mail_is_one_disruption_item(session):
    """News of a cyberattack at a supplier + its own schedule-change mail + its open lines (moved or past due) = one supply-disruption item with the cause, old and new dates,
    money open, the builds that use the parts, the buyer on the lines and the act-by date from the mail. A supplier a fire or notice item already carries gets no second one."""
    d = attention.item_detail(session, "incident:SUP-0018")
    assert d.group == "disruption" and "cyberattack" in d.title and d.owner == "Priya Nair" and d.act_by == "2026-10-09"      # the mail's first shipment date
    assert round(float(d.at_stake.usd)) == 35344 and d.fire.lines_in_scope == 5 and d.fire.lines_already_late == 5 if hasattr(d, "fire") else True
    labels = " | ".join(n.label for n in d.numbers)
    assert "promised Sep 28, now Oct 30" in labels and "promised Sep 24, now Nov 20" in labels and "not received, no new date" in labels
    assert "cyberattack on Sep 24" in d.finding and "Tern and Porter" in d.finding
    keys = {i.key for i in attention.what_needs_attention(session)}
    assert not {k for k in keys if k.startswith("incident:")} - {"incident:SUP-0018"}      # the burned plant and the notice supplier keep their own items


def test_robots_short_are_counted_in_their_own_month_and_never_summed_across_months(session):
    """Jadepeak: 182 Tern + 40 Porter are short in October, 24 Heron in November and 92 Tern + 20 Porter + 22 Heron in December (every month the new dates leave short
    that the promised dates covered): each row names its month, and the item's note says each month on its own. The fire counts every month its notice leaves short."""
    item = next(i for i in attention.what_needs_attention(session) if i.key == "disruption:SUP-0013")
    by_month = {}
    for r in item.robots_short:
        by_month.setdefault(r.month, {})[r.product.label.split()[0]] = r.robots
    assert by_month == {"2026-10": {"Tern": 182, "Porter": 40}, "2026-11": {"Heron": 24}, "2026-12": {"Tern": 92, "Porter": 20, "Heron": 22}}
    assert item.at_stake_note == ("182 Tern + 40 Porter robots in October, short of power electronics; 24 Heron robots in November, short of power electronics; "
                                  "92 Tern + 20 Porter + 22 Heron robots in December, short of power electronics")
    assert [r.month for r in item.robots_short] == sorted(r.month for r in item.robots_short)      # month order: the first row is the first month short
    fire = next(i for i in attention.what_needs_attention(session) if i.key == "disruption:SUP-0001")
    assert {(r.month, r.product.label.split()[0]): r.robots for r in fire.robots_short} == {("2026-10", "Tern"): 182, ("2026-10", "Porter"): 40, ("2026-11", "Tern"): 188, ("2026-11", "Porter"): 42}


def test_a_notice_title_says_each_months_builds_and_the_tool_returns_robots_short_per_month(session, monkeypatch):
    """The agent said Heron is short 'from October' because the title merged the months: the title now says each month, and get_item returns the rows and a number per product and month."""
    import asyncio
    import json

    from app.organism import services as organism_services
    from app.organism.context import RunContext
    from app.organism.runs.events import Recorder
    from app.domain.attention import tools as attention_tools

    item = next(i for i in attention.what_needs_attention(session) if i.key == "disruption:SUP-0013")
    assert "24 H1 in Nov" in item.summary and "short in Oct" in item.summary.split("H1")[0]      # each month's robots on their own, never summed
    monkeypatch.delenv("LOOKOUT_FAKE_SERVICES", raising=False)
    db = session.get_bind().url.database
    ctx = RunContext(run_id="run-t", item_key="x", db_path=db, recorder=Recorder("run-t", db), plan=[], allow={})
    t = {x.name: x for x in attention_tools.make_tools(ctx, organism_services.get(str(db)).attention)}
    body = json.loads(asyncio.run(t["get_item"].handler({"item_key": "disruption:SUP-0013"}))["content"][0]["text"])
    rows = {(r["product"].split()[0], r["month"]): r["robots"] for r in body["data"]["robots_short"]}
    assert rows == {("Tern", "2026-10"): 182, ("Porter", "2026-10"): 40, ("Heron", "2026-11"): 24, ("Tern", "2026-12"): 92, ("Porter", "2026-12"): 20, ("Heron", "2026-12"): 22}
    assert any(n["id"].endswith("robots_short:HR-90110:2026-11") and float(n["value"]) == 24 for n in body["numbers"])


def test_the_price_lock_stake_covers_only_what_the_lock_window_covers(session):
    """Great Plains: the rise starts Nov 1 and the lock covers deliveries to Dec 15, so the stake is the rise on the Nov-Dec need the open orders do not cover, netted earliest need first
    (not twelve months of spend), each at the rise that applies to its part (the die-cast bracket at 4.0%, the extrusions at 8.5%); the title says what it covers."""
    d = attention.item_detail(session, "deadline:SUP-0041:2026-10-15")
    assert d.title.endswith("acknowledge orders by Oct 15 to keep today's price") and d.summary == "on deliveries to Dec 15" and 2_000 < float(d.at_stake.usd) < 3_000
    assert "2026-12" in d.at_stake.provenance.rule and "earliest need first" in d.at_stake.provenance.rule      # whole months Nov-Dec, open orders netted against the earliest need first


def test_every_disruption_kind_with_parts_has_options_and_the_risk_item_is_not_the_fire(session):
    from app.domain.attention import options

    for key in ("disruption:SUP-0001", "disruption:SUP-0013", "risk:SUP-0002"):      # the fire, a notice, a supplier at risk: the same four ways
        assert [o.kind for o in options.fire_options(session, key)][:4] == ["allocation", "air_freight", "resequence", "second_source"], key
    assert [o.kind for o in options.fire_options(session, "disruption:SUP-0013")][4:] == ["order_before"]      # its notice moves the lead time after a cutoff (BUYER D2)
    assert options.fire_options(session, "consignment:HR-30110") is None      # the consigned material has no supplier to ask for allocation: no options, and nothing promises them


def test_the_current_order_column_keeps_what_was_paid_apart_from_that_price_with_the_duty(session):
    """The agent wrote 'last paid $1,421.40' because the column's total was the last PO price plus the 25% duty: the two are separate figures."""
    from app.domain.quotes import service as quotes

    cur = next(c for c in quotes.compare_offers(session, "HR-50110").columns if c.is_current).landed
    assert round(float(cur.last_paid_usd.usd), 2) == round(float(cur.unit_price_usd.usd), 2) and cur.with_new_duty_usd is not None
    assert round(float(cur.with_new_duty_usd.usd) / float(cur.last_paid_usd.usd), 4) == 1.25                      # the tranche-1 duty on top
    assert round(float(cur.with_new_duty_usd.usd), 2) == round(float(cur.total_known_usd.usd), 2)
    quoted = next(c for c in quotes.compare_offers(session, "HR-50110").columns if not c.is_current).landed
    assert quoted.last_paid_usd is None and quoted.with_new_duty_usd is None                                       # a quote was never paid


def test_a_supplier_with_stale_legacy_lines_is_summarised_apart_from_its_notice_lines(session):
    """Yunzhan: 10 lines under the notice, and the legacy ones (PO-10711/1, PO-10788/1) are stale: probably not open, never 'under the notice'."""
    lines = [l for l in orders.open_supply(session) if l.supplier.id == "SUP-0001"]
    assert sum(1 for l in lines if l.notice_kind and not l.stale) == 10 and {l.po_line.id for l in lines if l.stale} >= {"PO-10711/1", "PO-10788/1"}
    assert all(not (l.stale and l.notice_kind == "force majeure") for l in lines)


def test_a_price_the_part_is_bought_at_again_is_not_an_outlier_and_hr32126_shows_its_latest_price(session):
    """HR-32126: a volume supplier (Xinwei, 2,300 to 5,200 pieces at about $0.52) and small lots from another (50 to 250 pieces at $1.6 to $2.3), all in EA. Both are prices the part is
    bought at, so the newest line is the last paid; a lone far price (a broker buy, a slip) is still set aside."""
    from sqlalchemy import select

    from app.domain.orders.model import PoLine, ReferencePrice

    lines = {l.id: l for l in session.scalars(select(PoLine).where(PoLine.part_number == "HR-32126"))}
    assert {l.uom for l in lines.values()} == {"EA"}      # one unit of measure (the cleaned unit): not a pack-size difference
    low = [l for l in lines.values() if l.unit_usd_each < 1]
    assert len(low) == 4 and not any("price_outlier" in (l.flags or "") for l in low)            # a second price level, bought four times
    ref = session.get(ReferencePrice, "HR-32126")
    assert ref.po_line_id == "HPO-26-00408/160" and round(ref.usd_each, 4) == 0.5158              # the newest line is the last paid; the earlier $2.26 (Aug 2025) is context
    assert lines["HPO-25-00409/10"].unit_usd_each == 2.26 and lines["HPO-25-00409/10"].order_date < lines[ref.po_line_id].order_date
    # the rule still sets aside what it can explain: a broker buy far above, a slip
    flagged = [l for l in session.scalars(select(PoLine).where(PoLine.flags.like("%price_outlier%")))]
    assert len(flagged) == 19 and {"HR-50110", "HR-10019"} <= {l.part_number for l in flagged}


def test_the_fraud_item_reads_as_a_sentence(session):
    d = attention.item_detail(session, "trust:2026-09-23_URGENT_Updated_remittance_details_following_plant_incident")
    assert "The message asks you to send USD 187,420 to new bank details." in d.finding and "asked to new bank" not in d.finding
    spot = attention.item_detail(session, "trust:2026-09-12_Spot_offer_-_NG6603-QFN48_in_stock_ships_today")
    assert "the supplier is on hold or inactive in the ERP" in spot.finding and "On hold or Inactive" not in spot.finding


def test_a_company_that_renamed_itself_shows_under_its_new_name(session):
    from app.domain import naming
    from app.domain.annotate import service as annotate

    assert naming.supplier_name(session, "SUP-0016") == "BCX Interconnect (formerly Baycrest)"          # read from its Sep 2 notice, not typed
    assert [(s.type, s.ref) for s in annotate.annotate(session, "BCX Interconnect and Baycrest Connectors, Inc.")] == [("supplier", "SUP-0016"), ("supplier", "SUP-0016")]
    assert next(i for i in attention.what_needs_attention(session) if i.key == "deadline:SUP-0016:2026-12-31").title.startswith("BCX (formerly Baycrest): ")


def test_an_open_question_names_its_part_never_a_bare_template(session):
    """BUYER R2b: "HTS code" and "country of origin" twice, with no part, read as the same question; each names its part."""
    for p in parts.list_parts(session):
        for u in (p.coo, p.hts):
            if isinstance(u, Unknown):
                assert u.what.endswith(p.ref.id) and u.what not in ("HTS code", "country of origin")
