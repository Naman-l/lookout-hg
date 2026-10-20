"""Stand-ins for the parts of DOMAIN's services that have not landed, and an in-memory copy of the Yunzhan
HR-40110 data for tests that must not need a database. They are built from DOMAIN's own schema classes
(orders, demand and bom), so they cannot drift from the real shapes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from ...domain.bom.schema import WhereUsedRow
from ...domain.common import AS_OF, EntityRef, Money, Provenance, Quantity, Unknown
from ...domain.demand.schema import MonthBucket, MonthQty, TimePhased
from ...domain.orders.schema import SupplyLine
from ...domain.tariffs.schema import CooStatus, ExposureLine, LineDuty, PartExposure, TariffRuleView, TariffStatus

FM_ID = "2026-09-22_NOTICE_OF_FORCE_MAJEURE_-_Shenzhen_Yunzhan_Precision_Motor_Co_Ltd"  # the message's id: its file stem
FM = EntityRef(type="message", id=FM_ID, label="Yunzhan force majeure, 2026-09-22")
_P = Provenance(method="computed", source="fake", by="fake")


def _qty(v: int) -> Quantity:
    return Quantity(value=Decimal(v), uom="EA", ea=Decimal(v), provenance=_P)


_REQ = {"2026-10": 364, "2026-11": 376, "2026-12": 352, "2027-01": 340}
# The ten lines of the force majeure notice (data/quotes/2026-09-22_NOTICE_OF_FORCE_MAJEURE...): line, part, qty, promise.
_LINES = [
    ("HPO-26-00450/20", "HR-40120", 445, "2026-08-25"), ("HPO-26-00450/10", "HR-40110", 355, "2026-08-26"),
    ("HPO-26-00532/10", "HR-40130", 1320, "2026-08-28"), ("HPO-26-00614/10", "HR-40110", 435, "2026-09-23"),
    ("HPO-26-00614/30", "HR-40230", 250, "2026-09-25"), ("HPO-26-00532/20", "HR-40210", 163, "2026-09-30"),
    ("HPO-26-00614/20", "HR-40110", 350, "2026-10-26"), ("HPO-26-00670/10", "HR-40120", 400, "2026-10-30"),
    ("HPO-26-00670/20", "HR-40130", 1030, "2026-11-24"), ("HPO-26-00532/30", "HR-40210", 144, "2026-11-26"),
]


def open_supply(part: str | None = None, *, as_of=AS_OF) -> list[SupplyLine]:
    return [
        SupplyLine(po_line=EntityRef(type="po_line", id=pl), part=EntityRef(type="part", id=p), record=EntityRef(type="supplier_record", id="SUP-0001"),
                   supplier=EntityRef(type="supplier", id="SUP-0001", label="Shenzhen Yunzhan"), status="open", qty=_qty(q), open_value=Money(amount=Decimal(0), currency="USD", usd=Decimal(0), provenance=_P),
                   promise=d, revised_promise=None, days_past_due=None, disrupted_by=FM, notice_kind="force majeure", stale=False, flags=[])
        for pl, p, q, d in _LINES if part is None or p == part
    ]


def requirements(part: str, months: int = 12) -> list[MonthQty]:
    if part != "HR-40110":
        return []
    return [MonthQty(month=m, qty=_qty(q), by_product={"Tern T2": q // 2}) for m, q in _REQ.items()][:months]


def shortage(part: str) -> TimePhased:
    on_hand = Unknown(what=f"On-hand stock of {part}", why_it_blocks="Projected available cannot be shown without it", owner="Dana", question=f"How many {part} are on the shelf at Plant 1?")
    ref = EntityRef(type="part", id=part)
    if part != "HR-40110":
        return TimePhased(part=ref, per_unit="", past_due_receipts=_qty(0), buckets=[], on_hand=on_hand, first_short_month=None, disrupted=False)
    # Disrupted lines are not counted as arriving: scheduled receipts are zero where the supplier cannot ship.
    buckets = [MonthBucket(month=m, requirements=_qty(q), scheduled_receipts=_qty(0), under_disruption=_qty(0), short=_qty(q)) for m, q in _REQ.items()]
    return TimePhased(part=ref, per_unit="2 per Tern T2", past_due_receipts=_qty(0), buckets=buckets, on_hand=on_hand, first_short_month="2026-10", disrupted=True)


def where_used(part: str) -> list[WhereUsedRow]:
    if part != "HR-40110":
        return []
    return [WhereUsedRow(product=EntityRef(type="product", id="HR-90020", label="Tern T2"), part=EntityRef(type="part", id=part), qty_per_robot=Decimal(2), paths=[["HR-90020", "HR-80110", part]])]


def explode_bom(product: str):
    return []


@dataclass
class ItemNumber:
    id: str
    label: str
    value: Money | Quantity | Unknown


@dataclass
class Item:
    """The shape of the contract's ActionItemDetail, reduced to what a run reads. DOMAIN's attention service
    returns the same fields. The items below are TEST FIXTURES, not Halden's figures."""

    key: str
    group: str  # disruption | deadline | tariff | unknown | trust
    title: str
    owner: str
    finding: str = ""
    next_action: str = ""
    act_by: str | None = None
    days_left: int | None = None
    at_stake: Money | Quantity | Unknown | None = None
    numbers: list = field(default_factory=list)
    unknowns: list = field(default_factory=list)
    refs: list = field(default_factory=list)
    evidence: list = field(default_factory=list)


def _usd(v: int) -> Money:
    return Money(amount=Decimal(v), currency="USD", usd=Decimal(v), provenance=_P)


_ITEMS = {
    "disruption:SUP-0001": Item(
        "disruption:SUP-0001", "disruption", "Yunzhan force majeure: Tern drive motor", "Dana",
        refs=[EntityRef(type="supplier", id="SUP-0001", label="Shenzhen Yunzhan"), EntityRef(type="part", id="HR-40110")], evidence=[FM],
    ),
    "tariff:HR-40110": Item(
        "tariff:HR-40110", "tariff", "New 25% duty on HR-40110 from 2026-11-01", "Marcus", finding="China-origin motor on a listed HTS prefix; duty follows origin.",
        next_action="Confirm origin and request the certificate of origin from the supplier.", act_by="2026-10-15", days_left=20, at_stake=_usd(1000),
        numbers=[ItemNumber("duty_open_orders", "Duty on open orders, net", _usd(1000)), ItemNumber("rate", "Duty rate in percent", Quantity(value=Decimal(25), uom="PCT", provenance=_P))],
        refs=[EntityRef(type="supplier", id="SUP-0001", label="Shenzhen Yunzhan"), EntityRef(type="part", id="HR-40110")],
    ),
    "deadline:price-lock": Item(
        "deadline:price-lock", "deadline", "Quote price lock expires in 5 days", "Priya", finding="The quote is valid only until the date below.",
        next_action="Acknowledge the price lock with the supplier before it lapses.", act_by="2026-10-13", days_left=5,
        numbers=[ItemNumber("days_left", "Days left", Quantity(value=Decimal(5), uom="days", provenance=_P))],
        refs=[EntityRef(type="supplier", id="SUP-0001", label="Shenzhen Yunzhan")],
    ),
    "unknown:HR-40220": Item(
        "unknown:HR-40220", "unknown", "Country of origin unknown for HR-40220", "Dana", finding="The item master has no country of origin for this part, so the duty cannot be computed.",
        next_action="Ask the owner of the part to confirm origin.",
        unknowns=[Unknown(what="Country of origin of HR-40220", why_it_blocks="Duty follows origin, so the exposure cannot be computed", owner="Dana", question="Where is HR-40220 made?")],
        refs=[EntityRef(type="part", id="HR-40220")],
    ),
    "trust:fraud-remittance": Item(
        "trust:fraud-remittance", "trust", "Remittance change from a look-alike sender", "Sofia",
        finding="The sender domain is a look-alike of a supplier's and the reply-to is a free-mail address; it asks to change bank details. Verify by phone with the contact on file.",
        next_action="Do not act on it. Report it and verify by phone.", refs=[EntityRef(type="message", id="2026-09-23_URGENT_Updated_remittance_details")],
    ),
}


def get_item(item_key: str) -> Item:
    if item_key not in _ITEMS:
        raise KeyError(f"no such item: {item_key}")
    return _ITEMS[item_key]


def list_items(owner: str | None = None):
    return [i for i in _ITEMS.values() if owner is None or i.owner == owner]


attention = SimpleNamespace(get_item=get_item, list_items=list_items, stage_of=lambda item: None, options=lambda key: None, requests_for=lambda item_key=None, supplier_id=None: [])
orders = SimpleNamespace(open_supply=open_supply, supplier_delivery=lambda limit=10: [])
demand = SimpleNamespace(requirements=requirements, shortage=shortage)
bom = SimpleNamespace(where_used=where_used, explode_bom=explode_bom, product_families=lambda: ["Tern", "Porter", "Heron"])  # a stand-in for the products table


# ---- supplier contact and inbox threads (stand-ins; DOMAIN publishes the real signatures) ---------------------

@dataclass
class Contact:
    name: str
    email: str


@dataclass
class Thread:
    message_id: str
    subject: str
    sender: str
    date: str
    trust: str  # "trusted" | "flagged"
    flags: list
    body: str


_FM_BODY = """Dear Dana, dear Sofia,

We regret to inform you that on 18 September 2026 a fire broke out in the coil winding workshop of our Bao'an
Plant 2. No one was injured. The local authority has suspended the operation of Plant 2 pending safety
inspection ... we hereby give formal notice that we are unable to perform deliveries from Plant 2 for the
time being. Following open orders of Halden Robotics are affected:
HPO-26-00450 line 10 HR-40110 355 (confirmed 2026-08-26) · HPO-26-00614 line 10 HR-40110 435 (2026-09-23) ·
HPO-26-00614 line 20 HR-40110 350 (2026-10-26) · and seven other lines.
Our current estimation is partial production can resume in 6 to 8 weeks. We will give priority to long-term
customers. We will provide revised delivery dates no later than 10 October 2026.
Li Wei, Sales Manager, Shenzhen Yunzhan Precision Motor Co., Ltd."""


def contact_for(identity_id: str) -> Contact | None:
    return {"SUP-0001": Contact("Li Wei", "li.wei@yunzhan-motor.example")}.get(identity_id)


def read_thread(message_id: str) -> Thread:
    if message_id != FM_ID:
        raise KeyError(f"no such message: {message_id}")
    return Thread(message_id, "NOTICE OF FORCE MAJEURE - Shenzhen Yunzhan Precision Motor Co., Ltd.", "Li Wei <li.wei@yunzhan-motor.example>",
                  "2026-09-22", "trusted", [], _FM_BODY)


suppliers = SimpleNamespace(contact_for=contact_for)
inbox = SimpleNamespace(read_thread=read_thread, message_offers=lambda message_id: [])


# ---- tariffs (HR-40110 only: a China-origin motor on a listed prefix, three open lines under force majeure) ---------

_RULE = TariffRuleView(id=1, tranche=1, hts_prefix="8501.31", description="DC motors and generators, output not exceeding 750 W", rate=0.25, effective_date="2026-11-01",
                       origin="CN", in_transit="Exported from China before 2026-11-01 and entered before 2026-12-01: not subject.")
_LV = {"HPO-26-00450/10": 54318.55, "HPO-26-00614/10": 66072.15, "HPO-26-00614/20": 53501.0}


def _usd_exact(v: float) -> Money:
    return Money(amount=Decimal(str(v)), currency="USD", usd=Decimal(str(v)), provenance=_P)


def exposure_for_part(part: str) -> PartExposure:
    ref = EntityRef(type="part", id=part)
    if part != "HR-40110":
        return PartExposure(part=ref, tariff=TariffStatus(part=ref, status="not_listed"), coo=CooStatus(part=ref, status="other", coo="DE"), status="not_applicable", rate=None, net=None,
                            gross=None, open_lines=[], uncovered_qty=0.0, reference_price=None, unpriced=False, effective_date=None)
    lines = [ExposureLine(po_line=EntityRef(type="po_line", id=k), open_value=_usd_exact(v), exposed=True, importer="company", why="under force majeure: its promise date no longer holds") for k, v in _LV.items()]
    return PartExposure(part=ref, tariff=TariffStatus(part=ref, status="listed", rule=_RULE), coo=CooStatus(part=ref, status="china", coo="CN"), status="china_listed", rate=0.25,
                        net=_usd_exact(183186.97), gross=_usd_exact(226752.07), open_lines=lines, uncovered_qty=3656.0, reference_price=_usd_exact(152.86), unpriced=False, effective_date="2026-11-01",
                        open_value_total=_usd_exact(round(sum(_LV.values()), 2)), open_duty_total=_usd_exact(round(sum(_LV.values()) * 0.25, 2)))


def duty_for_line(po_line_id: str) -> LineDuty:
    v = _LV[po_line_id]
    return LineDuty(po_line=EntityRef(type="po_line", id=po_line_id), status="owed", duty=_usd_exact(round(v * 0.25, 2)), importer="company", why="enters on or after the effective date, or its date is unknown")


tariffs = SimpleNamespace(exposure_for_part=exposure_for_part, duty_for_line=duty_for_line, buyer_of=lambda part: "Dana")


# ---- quotes (HR-40110: Yunzhan's own quote, the Vinh Phuc alternative whose origin is still to confirm, the last PO) --------

from ...domain.common import Conditional  # noqa: E402
from ...domain.quotes.schema import BidColumn, BidTab, LandedCost, OfferView  # noqa: E402


def _offer(n: int, name: str, quote: str | None, price: float, *, supplier: str | None, incoterm: str | None, origin: str | None, claim: str | None,
           lead: Conditional | None, valid: str | None) -> OfferView:
    return OfferView(offer_id=n, supplier=EntityRef(type="supplier", id=supplier) if supplier else None, supplier_name=name, message=EntityRef(type="message", id="q"),
                     quote_no=quote, part=EntityRef(type="part", id="HR-40110"), qty_break=500, price=_usd_exact(price), price_basis="each", unit_price_usd=_usd_exact(price),
                     incoterm=incoterm, origin_claim=claim, origin=origin, lead_time=lead, valid_until=valid, days_left=None, expired=False, moq=None, tooling_usd=None,
                     payment_terms=None, conditions=None, trust="on_file")


def compare_offers(part: str, qty: int | None = None) -> BidTab:
    ref = EntityRef(type="part", id=part)
    if part != "HR-40110":
        return BidTab(part=ref, qty=qty, columns=[], note="")
    vpm = _offer(1, "Vinh Phuc Motor Technology Co., Ltd. (Vietnam)", "VPM-Q-260924", 165.54, supplier=None, incoterm="FOB Hai Phong", origin=None, claim="Vietnam; magnets sourced from China",
                 lead=Conditional(value="60 days", condition="after PPAP approval (samples: 10 pcs free, 4 weeks)", provenance=_P), valid=None)
    yz = _offer(2, "Shenzhen Yunzhan Precision Motor Co., Ltd. (China)", "Q-YZ-26-0831", 154.55, supplier="SUP-0001", incoterm="FOB Shenzhen", origin="CN", claim="China",
                lead=Conditional(value="35 days", condition="after receipt of order (ARO)", provenance=_P), valid="2026-10-13")
    cur = _offer(3, "Shenzhen Yunzhan Precision Motor Co., Ltd. (last PO 2026-08-05)", None, 152.86, supplier="SUP-0001", incoterm=None, origin="CN", claim="CN", lead=None, valid=None)
    more = Unknown(what="Origin ruling", why_it_blocks="Duty depends on where the goods are ruled to originate", owner="broker", question="Which country is the origin?")
    cols = [
        BidColumn(label="Vinh Phuc", landed=LandedCost(offer=vpm, unit_price_usd=_usd_exact(165.54), surcharge_usd=None, duty_status="unknown_origin", duty_usd=None, duty_if_china_usd=_usd_exact(41.385),
                                                      tooling_per_unit_usd=None, total_known_usd=_usd_exact(165.54), total_if_china_usd=_usd_exact(206.925), unknowns=[more], notes=[])),
        BidColumn(label="Current", is_current=True, landed=LandedCost(offer=cur, unit_price_usd=_usd_exact(152.86), surcharge_usd=None, duty_status="owed", duty_usd=_usd_exact(38.22), duty_if_china_usd=None,
                                                                    tooling_per_unit_usd=None, total_known_usd=_usd_exact(191.08), total_if_china_usd=None, unknowns=[], notes=[])),
        BidColumn(label="Yunzhan", landed=LandedCost(offer=yz, unit_price_usd=_usd_exact(154.55), surcharge_usd=None, duty_status="owed", duty_usd=_usd_exact(38.6375), duty_if_china_usd=None,
                                                    tooling_per_unit_usd=None, total_known_usd=_usd_exact(193.1875), total_if_china_usd=None, unknowns=[], notes=[])),
    ]
    return BidTab(part=ref, qty=qty or 500, columns=cols, note="Totals are per piece and cover price, surcharge, known duty and tooling; freight and insurance are not.")


quotes = SimpleNamespace(compare_offers=compare_offers)


# ---- the stage ladder: nothing in the unit tests needs a database, and a part with no records has no ladder -----------------
phases = SimpleNamespace(part_phases=lambda part: None, line_phases=lambda line: None, build_readiness=lambda product, month: None)
