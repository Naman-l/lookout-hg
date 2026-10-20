"""Offers, landed cost and the bid tab: the sums are code; what is unknown stays beside the total."""
import pytest

from app.domain.common import Conditional, Unknown
from app.domain.quotes import service as quotes


def test_offers_for_part_applies_corrections_and_hides_blocked(session):
    alder = [o for o in quotes.offers_for_part(session, "HR-31110") if o.qty_break == 2500]
    assert len(alder) == 1 and float(alder[0].price.amount) == 183.36                 # the correction, not the quoted 138.36
    assert all(o.supplier_name != "Saltmarsh Components LLC" for o in quotes.offers_for_part(session, "HR-32104"))
    assert any(o.supplier_name.startswith("Saltmarsh") for o in quotes.offers_for_part(session, "HR-32104", include_blocked=True))


def test_per_1000_prices_become_per_piece(session):
    o = next(o for o in quotes.offers_for_part(session, "HR-20103"))
    assert o.price_basis == "per_1000" and float(o.price.amount) == pytest.approx(240.58) and float(o.unit_price_usd.usd) == pytest.approx(0.24058)
    assert o.price.provenance.raw == "per 1,000 240.58" and o.origin == "CN"


def test_euro_offer_converted_at_the_latest_rate_with_its_conditions(session):
    o = quotes.offers_for_part(session, "HR-12210")[0]
    assert o.price.currency == "EUR" and float(o.price.rate) > 1 and o.price.rate_month == "2026-09" and o.valid_until == "2026-10-31" and o.days_left == 36
    assert "prepayment" in o.conditions and isinstance(o.lead_time, Conditional) and o.lead_time.condition == "after receipt of order"


def test_landed_cost_adds_duty_by_rule_and_keeps_unknowns_apart(session):
    yz = next(o for o in quotes.offers_for_part(session, "HR-40110") if o.supplier_name.startswith("Shenzhen") and o.qty_break == 500)
    c = quotes.landed_cost(session, yz.offer_id)
    assert c.duty_status == "owed" and float(c.duty_usd.usd) == pytest.approx(154.55 * 0.25, rel=1e-4) and float(c.total_known_usd.usd) == pytest.approx(154.55 * 1.25, rel=1e-4)
    assert "freight and insurance" in {u.what for u in c.unknowns} and all(isinstance(u, Unknown) for u in c.unknowns)
    vp = next(o for o in quotes.offers_for_part(session, "HR-40110") if o.supplier_name.startswith("Vinh"))
    v = quotes.landed_cost(session, vp.offer_id)
    assert v.duty_status == "unknown_origin" and v.duty_usd is None and "origin ruling" in {u.what for u in v.unknowns}
    assert float(v.total_if_china_usd.usd) == pytest.approx(165.54 * 1.25, rel=1e-4) and float(v.total_known_usd.usd) == pytest.approx(165.54, rel=1e-4)
    assert v.offer.lead_time.condition.startswith("after PPAP")


def test_ddp_china_duty_lands_on_halden_at_cost(session):
    bcx = next(o for o in quotes.offers_for_part(session, "HR-20137"))
    c = quotes.landed_cost(session, bcx.offer_id)
    assert c.duty_status == "at_cost_on_top" and float(c.duty_usd.usd) == pytest.approx(13.24 * 0.15, rel=1e-3)
    assert "freight and insurance" not in {u.what for u in c.unknowns}                 # delivered duty paid: freight is in the price


def test_surcharge_and_tooling(session):
    h = quotes.landed_cost(session, quotes.offers_for_part(session, "HR-12210")[0].offer_id)
    assert float(h.surcharge_usd.usd) == pytest.approx(float(h.unit_price_usd.usd) * 0.035, rel=1e-3)
    mx = next(o for o in quotes.offers_for_part(session, "HR-21103") if o.supplier_name.startswith("Monterrey"))
    assert quotes.landed_cost(session, mx.offer_id).tooling_per_unit_usd is not None and mx.tooling_usd == 1850


def test_bid_tab_orders_columns_and_includes_the_current_price(session):
    tab = quotes.compare_offers(session, "HR-40110", qty=500)
    assert any(c.is_current for c in tab.columns) and len(tab.columns) == 3
    totals = [float(c.landed.total_known_usd.usd) for c in tab.columns]
    assert totals == sorted(totals)
    assert tab.columns[0].label.startswith("Vinh Phuc") and tab.columns[0].landed.total_if_china_usd is not None       # cheapest if the origin holds, and said so
    assert quotes.compare_offers(session, "HR-40110", qty=1000).columns[-1].landed.offer.qty_break in (1000, None)


def test_origin_falls_back_to_the_part_master_and_says_so(session):
    h = quotes.offers_for_part(session, "HR-12210")[0]
    assert h.origin == "DE" and h.origin_source == "stated in the part master"       # the quote states no origin
    bcx = quotes.offers_for_part(session, "HR-20137")[0]
    assert bcx.origin == "CN" and bcx.origin_source == "the quote"
    vp = next(o for o in quotes.offers_for_part(session, "HR-40110") if o.supplier_name.startswith("Vinh"))
    assert vp.origin is None and vp.origin_source is None                            # a claim that needs a ruling stays undetermined


# --- the conditions beside the price, as named fields (what the agent reads) ---

def _terms_for(session, part, qty=None):
    from app.domain.quotes import service as quotes
    from app.domain.quotes.tools import _terms

    return [(c.landed.offer, _terms(c.landed.offer, c.landed)) for c in quotes.compare_offers(session, part, qty).columns if not c.is_current]


def test_every_condition_the_agent_dropped_in_round_six_is_a_named_field(session):
    (o, t), *_ = [x for x in _terms_for(session, "HR-12210", 100) if x[0].qty_break == 100]
    assert (t["incoterm"], t["incoterm_place"]) == ("EXW", "Hannover")                                   # EXW
    assert t["lead_time"] == {"text": "14 weeks", "days": "98 days", "basis": "after receipt of order"}   # 14 weeks, and what they run from
    assert t["valid_until"] == "2026-10-31" and "31 October" == t["valid_until_words"]                    # the validity date
    assert t["surcharge"] == {"pct": "3.5%", "included": "added to the quoted price"}
    assert t["prepayment"] == "30% on orders above EUR 25,000 net" and t["payment_terms"] == "Net 30 (was 45)"
    assert t["duty_rule"]["tranche"] == "2" and t["duty_rule"]["effective_date"] == "2027-01-01" and t["duty_rule"]["in_transit_relief"] == "none"        # 2027-01-01
    assert not any(isinstance(v, (int, float)) for v in t.values()), "terms are text; a figure is a price with an id"


def test_an_alternative_origin_names_its_country_and_the_date_it_can_start(session):
    from app.domain.quotes.tools import origin_alternatives

    rows = []
    for o, t in _terms_for(session, "HR-50110"):
        rows.append({"current": False, "supplier": o.supplier_name, "quote_no": o.quote_no, "origin": o.origin, "origin_claim": o.origin_claim, "terms": t, "price_id": f"id{o.offer_id}"})
    alts = origin_alternatives([{"current": True, "supplier": "last", "quote_no": None, "origin": "CN", "origin_claim": "China (Huizhou)", "terms": rows[0]["terms"], "price_id": "p"}] + rows)
    penang = next(a for a in alts if "Penang" in (a["origin_claim"] or ""))                               # Penang
    assert penang["available_from"] == "2027-02-01" and penang["available_from_words"] == "1 February 2027" and penang["price_id"]
    assert not any(a["origin_claim"] == "China (Huizhou)" for a in alts)                                  # the incumbent's own origin is not an alternative


def test_the_mexican_option_for_a_harness_is_an_alternative_to_the_chinese_incumbent(session):
    from app.domain.quotes import service as quotes
    from app.domain.quotes.tools import _terms, origin_alternatives

    tab = quotes.compare_offers(session, "HR-21103")
    cols = [{"current": c.is_current, "supplier": c.landed.offer.supplier_name, "quote_no": c.landed.offer.quote_no, "origin": c.landed.offer.origin,
             "origin_claim": c.landed.offer.origin_claim, "terms": _terms(c.landed.offer, c.landed), "price_id": f"p{i}"} for i, c in enumerate(tab.columns)]
    alts = origin_alternatives(cols)
    assert any(a["origin_iso"] == "MX" and "Mexico" in a["origin_claim"] for a in alts)                  # Tijuana/Monterrey


def test_prepayment_is_stated_where_the_document_demands_it(session):
    (_, t), *_ = _terms_for(session, "HR-40110")[:1]
    pre = {o.supplier_name: o.prepayment for o, _ in _terms_for(session, "HR-40110")}
    assert any("30% deposit" in (v or "") for v in pre.values())
