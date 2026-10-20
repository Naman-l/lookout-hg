"""Every figure an eval sheet expects about a quote or an open order is a number with an id the answer can cite, returned by the tool the agent calls, on the real data."""

from __future__ import annotations

import asyncio
import json

from app.organism import services as organism_services
from app.organism.context import RunContext
from app.organism.runs.events import Recorder
from app.domain.orders import tools as orders_tools
from app.domain.quotes import tools as quote_tools


import pytest


@pytest.fixture(autouse=True)
def real_services(monkeypatch):
    monkeypatch.delenv("LOOKOUT_FAKE_SERVICES", raising=False)      # these read the real data, not the stand-ins another test may have switched on; restored afterwards


def _tools(db_path):
    ctx = RunContext(run_id="run-t", item_key="x", db_path=db_path, recorder=Recorder("run-t", db_path), plan=[], allow={})
    svc = organism_services.get(str(db_path))
    return ctx, svc


def _call(tool, **args):
    out = asyncio.run(tool.handler(args))
    return json.loads(out["content"][0]["text"])


def _numbers(body) -> dict:
    return {n["id"]: float(n["value"]) for n in body["numbers"]}


def test_hallerbecks_quote_figures_are_numbers_with_ids(db_path):
    ctx, svc = _tools(db_path)
    t = {x.name: x for x in quote_tools.make_tools(ctx, svc.quotes)}
    n = _numbers(_call(t["compare_offers"], part_number="HR-12210"))
    q = "quote:HR-12210:AN-2026-1187"
    assert n[f"{q}@100:price_quoted"] == 389.50 and n[f"{q}@250:price_quoted"] == 376.10                                   # the quoted prices, in euros, at both breaks
    assert n[f"{q}@100:order_total"] == 40313.25 and abs(n[f"{q}@250:order_total"] - 97315.87) < 0.02                      # the order with the 3.5% surcharge
    assert n[f"{q}@100:prepayment"] == 12093.98 and abs(n[f"{q}@100:prepayment_usd"] - 14319) < 0.5                         # 30% of an order above EUR 25,000, and in dollars
    assert n[f"{q}@100:vs_last_po_pct"] == 23.4                                                                            # against the last PO's EUR 315.53, before the surcharge


def test_bcxs_other_lines_and_2027_duty_are_numbers_with_ids(db_path):
    ctx, svc = _tools(db_path)
    t = {x.name: x for x in quote_tools.make_tools(ctx, svc.quotes)}
    body = _call(t["compare_offers"], part_number="HR-20103")
    n = _numbers(body)
    q = "BCX-Q-2609"
    assert n[f"quote:HR-20103:{q}:price_quoted"] == 0.24058 and n[f"quote:HR-20104:{q}:price"] == 0.28543 and n[f"quote:HR-20140:{q}:price"] == 1.53693 and n[f"quote:HR-20136:{q}:price"] == 9.10
    assert n[f"quote:HR-20136:{q}:duty_next_12_months"] == 5733.00 and abs(n[f"quote:{q}:duty_next_12_months"] - 8838) < 1       # the quote's own estimated annual quantities x price x 15%
    provenance = ctx.evidence[f"quote:HR-20136:{q}:duty_next_12_months"].provenance      # the evidence holds each number's provenance
    assert provenance.method == "computed" and "estimated annual quantity" in provenance.rule
    assert ctx.evidence[f"quote:HR-20103:{q}:price_quoted"].provenance.method == "extracted"      # a quoted price cites the quote's line
    text = json.dumps(body)
    assert "Tijuana" in text and "2027-01-01" in text and "DDP" in text                                                     # the alternative site, the tranche date, the term


def test_quenvaras_penang_option_carries_its_availability(db_path):
    ctx, svc = _tools(db_path)
    t = {x.name: x for x in quote_tools.make_tools(ctx, svc.quotes)}
    body = _call(t["compare_offers"], part_number="HR-50110")
    penang = [c for c in body["data"]["columns"] if "Penang" in (c["origin_claim"] or "")]
    assert penang and penang[0]["terms"]["origin"]["available_from"] == "2027-02-01"                                         # the offer's own field, from its quote line


def test_open_supply_returns_the_value_still_to_arrive(db_path):
    ctx, svc = _tools(db_path)
    t = {x.name: x for x in orders_tools.make_tools(ctx, svc.orders)}
    hall = _numbers(_call(t["open_supply"], part_number="HR-12210"))
    assert round(hall["supply:HR-12210:open_value_eur"]) == 108181                                                          # HPO-26-00404/10 199 x 323.23 + HPO-26-00652/10 139 x 315.53, as the orders are priced
    yz = _numbers(_call(t["open_supply"], part_number="HR-40110"))
    assert round(yz["supply:HR-40110:open_value_usd"]) == 173892                                                            # 355 x 153.01 + 435 x 151.89 + 350 x 152.86


def test_read_message_returns_the_quotes_offers_and_every_offer_has_its_site(db_path):
    from app.domain.inbox import tools as inbox_tools

    ctx, svc = _tools(db_path)
    rd = {x.name: x for x in inbox_tools.make_tools(ctx, svc.inbox)}["read_message"]
    bcx = _call(rd, message_id="2026-09-02_Baycrest_Connectors_is_now_BCX_Interconnect_-_2027_quotation_BCX-Q-2609")
    assert bcx.get("data"), bcx
    offers = bcx["data"]["offers"]
    assert len(offers) == 11 and {o["site"] for o in offers if o["origin_claim"].startswith("China")} == {"Dongguan"} and "Tijuana" in {o["site"] for o in offers}
    first = next(o for o in offers if o["part"] == "HR-20103")
    assert first["incoterm"] == "DDP" and "invoiced" in first["conditions"] and first["line"] and first["price_id"] in {n["id"] for n in bcx["numbers"]}
    t = {x.name: x for x in quote_tools.make_tools(ctx, svc.quotes)}
    quenvara = _call(t["compare_offers"], part_number="HR-50110")["data"]["columns"]
    sites = {c["terms"]["origin"]["claim"]: c["terms"]["origin"]["site"] for c in quenvara if not c["current"]}
    assert sites["China (Huizhou)"] == "Huizhou" and sites["Malaysia (Penang assembly; cells from the Huizhou plant)"] == "Penang"      # the plant, not the port the Incoterm names


def test_get_item_returns_every_line_id_and_a_number_per_past_due_line(db_path):
    from app.domain.attention import tools as attention_tools

    ctx, svc = _tools(db_path)
    t = {x.name: x for x in attention_tools.make_tools(ctx, svc.attention)}
    body = _call(t["get_item"], item_key="deadline:chase")
    ids, late = body["data"]["po_line_ids"], body["data"]["past_due_line_ids"]
    assert len(ids) == 16 and set(late) <= set(ids) and len(late) >= 1      # the chase row's 16 lines, none cut
    nums = {n["id"]: n for n in body["numbers"]}
    assert float(nums["item:deadline:chase:po_line_count"]["value"]) == 16
    assert all(f"item:deadline:chase:past_due:{i}" in nums and float(nums[f"item:deadline:chase:past_due:{i}"]["value"]) > 0 for i in late)
    fire = _call(t["get_item"], item_key="disruption:SUP-0001")["data"]
    assert len(fire["po_line_ids"]) == 10 and len(fire["past_due_line_ids"]) == 4      # the fire's lines, 4 already late


def test_disrupted_supply_carries_what_the_notice_says_beyond_the_dates(db_path):
    ctx, svc = _tools(db_path)
    t = {x.name: x for x in orders_tools.make_tools(ctx, svc.orders)}
    body = _call(t["disrupted_supply"], supplier_id="SUP-0013")
    n = next(x for x in body["data"]["notices"] if x["notice"].startswith("2026-09-18_Jadepeak"))
    assert n["lead_time_new_orders"] == {"text": "16 weeks", "was": "8 weeks", "from_date": "2026-10-01", "applies_to": "orders placed after the date", "line": "lead time change"}
    sites = {(r["family"], r["site"]): r["duty_note"] for r in n["site_by_family"]}
    assert sites[("JPD300 series", "Taoyuan")].startswith("no new duty") and sites[("JPD150 series", "Dongguan")] == "25% from 2026-11-01"      # Taiwan brings none, China brings the tranche rate and date
    assert {"part": "HR-51310", "month": "2026-11", "qty": 24.0} in n["next_shortage"]["all"] and n["next_shortage"]["month"] == "2026-10"
    assert {p["part"] for p in body["data"]["parts"]} == {"HR-51110", "HR-51120", "HR-51130", "HR-51310"}      # the per-part lines are still there
    nums = {x["id"]: x for x in body["numbers"]}
    nov = nums["notice:2026-09-18_Jadepeak_Customer_Notice_CN-2026-09:shortage:HR-51310:2026-11"]      # one number per part and month, the month in words
    assert float(nov["value"]) == 24 and nov["unit"] == "EA" and "November 2026" in nov["name"]


def test_every_number_id_a_quote_comparison_returns_is_unique_and_each_offer_has_its_landed_cost(db_path):
    """Two offers on one quote number (Quenvara's Huizhou and Penang) used to share ids with different values; and each offer has an explicit landed cost per piece after duty."""
    from app.domain.parts.model import Part  # noqa: F401  (the real parts are listed below)

    ctx, svc = _tools(db_path)
    t = {x.name: x for x in quote_tools.make_tools(ctx, svc.quotes)}
    for part in ("HR-50110", "HR-50210", "HR-12210", "HR-20103", "HR-40110"):
        ids = [n["id"] for n in _call(t["compare_offers"], part_number=part)["numbers"]]
        assert len(ids) == len(set(ids)), (part, sorted(i for i in set(ids) if ids.count(i) > 1))
    body = _call(t["compare_offers"], part_number="HR-50110")
    nums = {n["id"]: float(n["value"]) for n in body["numbers"]}
    landed = {k: v for k, v in nums.items() if k.endswith(":landed_usd_each")}
    assert len(landed) == 3      # the current supplier's last PO with the duty, and the Huizhou and Penang offers
    assert any(abs(v - 1444.01) < 0.01 for v in landed.values()) and any(abs(v - 1421.40) < 0.01 for v in landed.values())      # Huizhou 1,155.21 + 25% duty; the current price with the new duty


def test_the_price_lock_item_gives_each_announced_rise_and_every_item_gives_its_act_by_as_an_id(db_path):
    from app.domain.attention import tools as attention_tools

    ctx, svc = _tools(db_path)
    t = {x.name: x for x in attention_tools.make_tools(ctx, svc.attention)}
    body = _call(t["get_item"], item_key="deadline:SUP-0041:2026-10-15")
    rises = {n["id"]: float(n["value"]) for n in body["numbers"] if ":price_increase_pct:" in n["id"]}
    assert rises == {"item:deadline:SUP-0041:2026-10-15:price_increase_pct:extruded_profiles": 8.5, "item:deadline:SUP-0041:2026-10-15:price_increase_pct:die_cast_brackets": 4.0}      # the family is the words the stored price-change event gives, pinned
    assert all(n["unit"] == "%" for n in body["numbers"] if ":price_increase_pct:" in n["id"])
    assert body["data"]["date_ids"]["item:deadline:SUP-0041:2026-10-15:act_by"] == "2026-10-15"
    fire = _call(t["get_item"], item_key="disruption:SUP-0001")["data"]["date_ids"]
    assert fire["item:disruption:SUP-0001:act_by"] == "2026-10-10"


def test_the_open_value_for_hr_50110_is_a_number(db_path):
    ctx, svc = _tools(db_path)
    t = {x.name: x for x in orders_tools.make_tools(ctx, svc.orders)}
    assert round(_numbers(_call(t["open_supply"], part_number="HR-50110"))["supply:HR-50110:open_value_usd"]) == 722737      # the three open lines, in dollars


def test_each_quotes_change_against_last_paid_is_one_code_figure_on_the_invoiced_price(db_path):
    """BUYER Q5 ruling: the change is computed by code on one named basis, the invoiced price (price + surcharge) against last paid; the model's
    +23.4% (a per-break EUR figure before surcharge) was the wrong basis for the card."""
    from decimal import Decimal

    ctx, svc = _tools(db_path)
    t = {x.name: x for x in quote_tools.make_tools(ctx, svc.quotes)}
    n = _numbers(_call(t["compare_offers"], part_number="HR-12210"))
    price, sur, last = (Decimal(str(n[f"quote:HR-12210:{k}"])) for k in ("AN-2026-1187:price", "AN-2026-1187:surcharge", "current:price"))
    want = ((price + sur) / last - 1) * 100
    assert abs(Decimal(str(n["quote:HR-12210:AN-2026-1187:vs_last_paid_pct"])) - want) < Decimal("0.06") and round(float(want), 1) == 24.4
    assert not any(k.startswith("quote:HR-12210:current:vs_") for k in n)  # last paid has no change against itself


def test_with_a_surcharge_both_bases_are_named_code_figures_and_the_break_follows_the_quantity(db_path):
    """SIDEQ/BUYER: the case page says +20% (price alone, 250-piece break) and Ask said +24.4% (as invoiced): both true, so each names its basis.
    For 200 pieces the 100-piece break applies; the table's total and the card's invoiced price are the same code figure."""
    from decimal import Decimal

    ctx, svc = _tools(db_path)
    t = {x.name: x for x in quote_tools.make_tools(ctx, svc.quotes)}
    for qty in (None, 200):
        n = _numbers(_call(t["compare_offers"], part_number="HR-12210", **({"qty": qty} if qty else {})))
        q = "quote:HR-12210:AN-2026-1187"
        price, sur, last = (Decimal(str(n[k])) for k in (f"{q}:price", f"{q}:surcharge", "quote:HR-12210:current:price"))
        assert abs(Decimal(str(n[f"{q}:total"])) - (price + sur)) < Decimal("0.01")  # the table's total = price + surcharge = the card's invoiced price
        assert abs(Decimal(str(n[f"{q}:vs_last_paid_pct"])) - ((price + sur) / last - 1) * 100) < Decimal("0.06")
        assert abs(Decimal(str(n[f"{q}:vs_last_paid_price_pct"])) - (price / last - 1) * 100) < Decimal("0.06")


def test_an_order_of_a_given_quantity_gets_its_invoiced_total_and_the_prepayment_it_avoids(db_path):
    """BUYER Q5: the bridge-order card shows the prepayment the order avoids, as code figures: 200 x the invoiced price, and the quote's 30% above EUR 25,000."""
    from decimal import Decimal

    ctx, svc = _tools(db_path)
    t = {x.name: x for x in quote_tools.make_tools(ctx, svc.quotes)}
    n = _numbers(_call(t["compare_offers"], part_number="HR-12210", qty=200))
    q = "quote:HR-12210:AN-2026-1187"
    inv = Decimal(str(n[f"{q}:price"])) + Decimal(str(n[f"{q}:surcharge"]))
    assert abs(Decimal(str(n[f"{q}:order_200_usd"])) - inv * 200) < Decimal("0.02")
    assert abs(Decimal(str(n[f"{q}:order_200_prepayment_usd"])) - Decimal(str(n[f"{q}:order_200_usd"])) * Decimal("0.3")) < Decimal("0.02")
    assert not any(":order_200" in k for k in _numbers(_call(t["compare_offers"], part_number="HR-12210")))  # no quantity asked: no order figures
