#!/usr/bin/env python3
"""Generate the dummy H.G. Infra Engineering dataset in data/, so the HG recipe can build the database and the app can run.

What it writes, in the shapes SCM downloads or builds (see docs/hg/PLAN.md §5): SAP exports (ME5A, ME2N, MB51, FBL1N, vendor and material
master, purchasing groups), the hand-built sheets (3-month material requirement for roads and railway in their multi-row layout, the monthly
fund requirement in ₹ Cr, the October payment projection, the long-lead look-ahead, the vendor library, budget rates, the DoA, the RFQ/CS,
expediting and LC/BG trackers, the MIS turnaround report), a commodity index, and 23 inbox messages. It plants the data defects the recipe
handles, one step each, and makes the demo stories true in the records. Everything is deterministic (fixed seed) and fictional except the
project names, plant codes, materials, units and sheet rates, which are H.G. Infra's own.

    backend/.venv/bin/python dummy_data/generate_hg.py      # then: make build-data && make run
"""
from __future__ import annotations

import csv
import math
import random
import re
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from hg_cast import (_FIRST, _LAST, AGGREGATE_GROUPS, AGGREGATE_SITES, DESK_OF_GROUP, DESK_OF_MATERIAL, FIRST_CAST, FUNCTIONS, HO_PLANT,  # noqa: E402
                     INTERNAL_DOMAIN, MATERIALS, ORGANOGRAM, PAYMENT_TERMS, PROJECTS, PURCH_GROUPS, RAILWAY_EXTRA_ROWS, RAILWAY_ORDER, RAILWAY_SHEET,
                     RAILWAY_UNITS, REPORTS_TO, ROADS_EXTRA_ROWS, ROADS_SHEET, ROADS_UNITS, SHEET_MATERIALS, STATE_GST, TEAM, VENDORS)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
AS_OF = date(2026, 10, 20)
START = date(2025, 11, 1)
rng = random.Random(20261020)

PROJ = {p[0]: dict(id=p[0], name=p[1], vertical=p[2], stage=p[3], state=p[4], district=p[5], plants=p[6], tracking=p[7], start=p[8], sap_name=p[9],
                   fronts=p[10]) for p in PROJECTS}
MAT = {m[0]: dict(code=m[0], desc=m[1], group=m[2], uom=m[3], alt=m[4], alt_per=m[5], lead=m[6], pv=m[7]) for m in MATERIALS}
TEAM_BY = {t[0]: dict(id=t[0], name=t[1], initials=t[2], role=t[3], groups=t[4], verticals=t[5], sap=t[6], limit=t[7], countersigns=t[8]) for t in TEAM}
GROUP_PERSON = {g: t[0] for t in TEAM for g in t[4]}


# ================================================================================================================== small helpers
def dmy(d: date | None) -> str:
    return d.strftime("%d.%m.%Y") if d else ""


def ym(d: date) -> str:
    return d.strftime("%Y-%m")


def month_start(m: str) -> date:
    return date(int(m[:4]), int(m[5:7]), 1)


def add_months(m: str, n: int) -> str:
    y, mm = divmod(int(m[5:7]) - 1 + n, 12)
    return f"{int(m[:4]) + y:04d}-{mm + 1:02d}"


def months(a: str, b: str) -> list[str]:
    out, m = [], a
    while m <= b:
        out.append(m)
        m = add_months(m, 1)
    return out


def month_end(m: str) -> date:
    return month_start(add_months(m, 1)) - timedelta(days=1)


def jitter(lo: int, hi: int) -> int:
    return rng.randint(lo, hi)


def us_group(x: float, places: int = 0) -> str:
    return f"{x:,.{places}f}"


def in_group(n: float) -> str:
    """12345678 -> '1,23,45,678' (Indian grouping)."""
    neg, s = n < 0, str(int(round(abs(n))))
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ("-" if neg else "") + ",".join(parts + [tail]) if parts else ("-" if neg else "") + tail


def sheet_num(x: float | None) -> str:
    """How the roads sheet's accounting format exports a quantity: '  51,485 '; blank stays blank."""
    if x is None or x == "":
        return ""
    return f"  {x:,.0f} " if abs(x) >= 1 else f"  {x:g} "


def write_csv(rel: str, header: list[str] | None, rows: list[list], pre: list[str] | None = None) -> int:
    path = DATA / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        for line in pre or []:
            f.write(line + "\n")
        w = csv.writer(f)
        if header:
            w.writerow(header)
        w.writerows(rows)
    return len(rows)


COUNTS: dict[str, int] = {}

_GST_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_checksum(s14: str) -> str:
    total = 0
    for i, c in enumerate(s14):
        p = _GST_CHARS.index(c) * (1 if i % 2 == 0 else 2)
        total += p // 36 + p % 36
    return _GST_CHARS[(36 - total % 36) % 36]


def make_pan(name: str, kind: str) -> str:
    letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    return "".join(rng.choice(letters) for _ in range(3)) + kind + name[0].upper() + f"{rng.randint(1000, 9999)}" + rng.choice(letters)


def make_gstin(state: str, pan: str, entity: str = "1") -> str:
    s14 = STATE_GST[state] + pan + entity + "Z"
    return s14 + gstin_checksum(s14)


_used_names: set[str] = set()


def person(seed_first: list[str] | None = None) -> str:
    while True:
        n = f"{rng.choice(seed_first or _FIRST)} {rng.choice(_LAST)}"
        if n not in _used_names and n.split()[0] not in FIRST_CAST:
            _used_names.add(n)
            return n


def email_of(name: str, domain: str) -> str:
    words = name.lower().split()
    return f"{words[0]}.{words[-1]}@{domain}" if len(words) > 1 else f"{words[0]}@{domain}"


# ================================================================================================================== commodity index
INDEX_MONTHS = months("2025-04", "2026-10")


def _series(start: float, steps: list[tuple[str, float]]) -> dict[str, float]:
    """Monthly values from `start` (Apr 2025), compounding the rate of the last step whose month has begun, with a little noise."""
    out, v = {}, start
    for m in INDEX_MONTHS:
        rate = next((r for since, r in reversed(steps) if m >= since), 0.0)
        if m != INDEX_MONTHS[0]:
            v *= 1 + rate + rng.uniform(-0.0015, 0.0015)
        out[m] = v
    return out


INDEX = {
    "IEEMA_TFR": (_series(161.2, [("2025-05", 0.004), ("2026-01", 0.009)]), "index points", 1),
    "IEEMA_SWG": (_series(148.4, [("2025-05", 0.003), ("2026-02", 0.0065)]), "index points", 1),
    "IEEMA_ACSR": (_series(238000, [("2025-05", 0.002), ("2026-01", 0.0185), ("2026-03", 0.0105)]), "INR per MT (EC-grade aluminium)", 0),
    "LME_AL": (_series(2380, [("2025-05", 0.004), ("2026-01", 0.013)]), "USD per tonne", 0),
    "LME_CU": (_series(9150, [("2025-05", 0.003), ("2026-02", 0.0105)]), "USD per tonne", 0),
    "STEEL_TMT": (_series(51800, [("2025-05", -0.001), ("2026-06", 0.0115)]), "INR per MT (TMT Fe500D, Raipur)", 0),
    "STEEL_STRUCT": (_series(58500, [("2025-05", 0.0), ("2026-04", 0.009)]), "INR per MT (structural)", 0),
    "CEMENT_WPI": (_series(127.8, [("2025-05", 0.0012)]), "WPI index points", 1),
    "HSD": (_series(89.6, [("2025-05", 0.0009)]), "INR per litre (Delhi retail)", 2),
}
for k, (s, _, places) in INDEX.items():
    for m in s:
        s[m] = round(s[m], places)
# the PV story's anchors: the base month the conductor PO cites and the month before the claimed dispatch
INDEX["IEEMA_ACSR"][0]["2025-12"] = 241000
INDEX["IEEMA_ACSR"][0]["2026-01"] = 245500
INDEX["IEEMA_ACSR"][0]["2026-08"] = 268800


def idx(name: str, m: str) -> float:
    s = INDEX[name][0]
    return s.get(m) or s[max(k for k in s if k <= m)]


# ================================================================================================================== people outside SCM
DIRECTORY = []      # project directory rows
HEADS, PLANNERS = {}, {}
for pid, p in PROJ.items():
    head, planner = person(), person()
    HEADS[pid], PLANNERS[pid] = head, planner
    DIRECTORY.append([p["name"], {"roads": "Roads", "railway": "Railway", "bess": "BESS", "solar": "Solar", "td": "T&D"}[p["vertical"]],
                      {"new": "New", "running": "Running", "nearing_completion": "Nearing completion"}[p["stage"]], p["state"], p["district"],
                      "-".join(p["plants"]), p["tracking"], head, email_of(head, INTERNAL_DOMAIN), planner, email_of(planner, INTERNAL_DOMAIN), p["sap_name"]])
HO_STORES = person()


# ================================================================================================================== vendors
@dataclass
class Vendor:
    code: str
    name: str
    category: str
    state: str
    city: str
    msme: bool
    groups: list
    terms: str
    regions: list
    gstin: str = ""
    pan: str = ""
    udyam: str = ""
    contact: str = ""
    email: str = ""
    domain: str = ""
    phone: str = ""
    bank: str = ""
    created: date | None = None
    blocked: str = ""
    otd: float = 0.9


_LEGAL = {"pvt", "ltd", "llp", "co.,", "co.", "company", "and", "the"}


def domain_of(name: str) -> str:
    words = [w for w in name.lower().replace(",", "").replace(".", "").split() if w not in _LEGAL]
    return "".join(words[:2]) + ".example"


VEND: dict[str, Vendor] = {}
for v in VENDORS:
    ven = Vendor(*v)
    ven.domain = "huaxin-ess.example" if "Huaxin" in ven.name else domain_of(ven.name)
    kind = "F" if ("LLP" in ven.name or "Company" in ven.name) else "C" if ("Ltd" in ven.name) else rng.choice("PFC")
    ven.pan = make_pan(ven.name, kind)
    ven.gstin = make_gstin(ven.state, ven.pan) if ven.state else ""
    ven.udyam = f"UDYAM-{STATE_GST.get(ven.state, '00')}-{rng.randint(10, 40):02d}-{rng.randint(1000000, 9999999)}" if ven.msme and ven.state else ""
    ven.contact = "Lin Hao" if "Huaxin" in ven.name else person()
    ven.email = email_of(ven.contact, ven.domain)
    ven.phone = f"+86 755 {rng.randint(2000, 8999)} {rng.randint(1000, 9999)}" if "Huaxin" in ven.name else f"+91 {rng.choice('6789')}{rng.randint(100000000, 999999999)}"
    ven.bank = f"XXXXXXXX{rng.randint(1000, 9999)}"
    ven.created = date(2026, 9, 10) if ven.code == "100512" else date(rng.randint(2014, 2025), rng.randint(1, 12), rng.randint(1, 28))
    ven.otd = rng.uniform(0.72, 0.97)
    VEND[ven.code] = ven
# the renamed vendor: same contact, same PAN family, a new GSTIN for the new company; the old code stays with its open orders
OLD, NEW = VEND["100231"], VEND["100512"]
NEW.contact = OLD.contact
NEW.email = email_of(NEW.contact, NEW.domain)
NEW.phone = OLD.phone
NEW.pan = make_pan("SKR Railtech", "C")
NEW.gstin = make_gstin(NEW.state, NEW.pan)
NEW.udyam = OLD.udyam
VEND["100114"].blocked = "X"       # blocked for payment after a GST mismatch (a plain master fact, no story)
VEND["100601"].otd = 0.86          # the late-streak vendor's record was good until its last four receipts


def vendors_for(group: str, project: str) -> list[Vendor]:
    out = [v for v in VEND.values() if group in v.groups and project in v.regions and v.code not in ("100512",) and not v.blocked]
    return out or [v for v in VEND.values() if group in v.groups and v.code != "100512" and not v.blocked]


# ================================================================================================================== records
@dataclass
class PrItem:
    doc: "PrDoc"
    material: str
    qty: float
    uom: str
    needed_by: date
    item_no: int = 0
    short_text: str = ""
    deletion: str = ""
    closed: str = ""
    changed_on: date | None = None
    po: "PoItem | None" = None
    value_hint: float = 0.0      # qty x expected rate, for the stories' arithmetic
    tag: str = ""


@dataclass
class PrDoc:
    project: str | None
    plant: str
    group: str
    requisitioner: str
    created: date
    released: date | None
    items: list = field(default_factory=list)
    number: str = ""
    tracking: str = ""
    tag: str = ""


@dataclass
class PoItem:
    doc: "PoDoc"
    material: str
    qty: float
    uom: str
    price: float          # per price unit
    price_unit: int
    delivery: date
    pr: PrItem | None = None
    item_no: int = 0
    short_text: str = ""
    receipts: list = field(default_factory=list)
    tag: str = ""


@dataclass
class PoDoc:
    vendor: Vendor
    doc_type: str
    doc_date: date
    plant: str
    project: str | None
    group: str
    terms: str
    validity_end: date | None = None
    pv_clause: str = "N"
    pv_index: str = ""
    items: list = field(default_factory=list)
    number: str = ""
    tag: str = ""


@dataclass
class Receipt:
    item: PoItem
    posting: date
    qty: float
    mvt: str = "101"
    reference: str = ""
    number: str = ""
    line: int = 1


@dataclass
class Quote:
    cs: str
    project: str | None
    pr: PrItem | None
    material: str
    vendor: Vendor | None
    vendor_name: str
    rfq_sent: date
    quote_date: date | None
    qty: float
    uom: str
    rate: float | None
    validity: date | None
    basis: str
    status: str
    approved_by: str = ""
    approved_on: date | None = None
    buyer: str = ""
    remarks: str = ""
    l1: bool = False


PR_DOCS: list[PrDoc] = []
PO_DOCS: list[PoDoc] = []
QUOTES: list[Quote] = []
CS_SEQ = [0]
STORY: dict[str, object] = {}      # the records each story needs, for the mail and the summary


def new_cs() -> str:
    CS_SEQ[0] += 1
    return f"CS/26-27/{CS_SEQ[0]:04d}" if CS_SEQ[0] > 0 else ""


def cs_number(d: date) -> str:
    CS_SEQ[0] += 1
    fy = f"{d.year % 100:02d}-{(d.year + 1) % 100:02d}" if d.month >= 4 else f"{(d.year - 1) % 100:02d}-{d.year % 100:02d}"
    return f"CS/{fy}/{CS_SEQ[0]:04d}"


def buyer_of_group(g: str) -> str:
    return TEAM_BY[GROUP_PERSON[g]]["name"]


def desk_of(project: str | None, material: str) -> str:
    """The purchasing group whose desk buys a material for a project, as the organogram splits the work (hg_cast.DESK_OF_*). The flows pick
    lines and documents by the vertical's desk; SAP's purchasing group on each line is this one. No random draw."""
    if material in DESK_OF_MATERIAL:
        return DESK_OF_MATERIAL[material]
    mg = MAT[material]["group"]
    if mg in AGGREGATE_GROUPS:
        return next((g for g, sites in AGGREGATE_SITES.items() if project in sites), "A00")
    return DESK_OF_GROUP[mg]


def buyer_for(project: str | None, material: str) -> str:
    return buyer_of_group(desk_of(project, material))


def po_desk(po) -> str:
    """A PO's purchasing group (a header field in ME2N): the desk of its largest line."""
    big = max(po.items, key=lambda it: it.qty * it.price / it.price_unit)
    return desk_of(po.project, big.material)


def plant_of(project: str) -> str:
    assert PROJ[project]["plants"], f"{project} has no SAP plant yet, so no SAP records"
    return PROJ[project]["plants"][0]


# ================================================================================================================== rates
BASE_RATE = {   # INR per base unit, for materials and projects the sheets do not price (regional spread applied below)
    "11000010": 760, "11000020": 820, "11000040": 700, "11000110": 600, "11000120": 770, "11000130": 560, "11000140": 650, "11000150": 820,
    "11000160": 700, "11000210": 1050, "11000220": 880, "12000010": 5300, "12000020": 5050, "12000110": 3300, "12000120": 900, "12000130": 24000,
    "12000210": 72, "13000008": 54800, "13000010": 54200, "13000012": 53600, "13000016": 53300, "13000020": 53300, "13000025": 53600, "13000032": 54000,
    "13000110": 66000, "13000210": 62000, "13000220": 90000, "14000010": 62000, "14000020": 60500, "14000030": 73000, "14000110": 82000,
    "14000120": 48000, "14000210": 540, "15000010": 90.5, "15000020": 58, "15000030": 52,
    "21000010": 41, "21000020": 62, "21000030": 21, "21000040": 108, "21000110": 3400, "21000210": 31500, "21000220": 41000, "21000230": 18200,
    "21000310": 680000, "21000320": 945000, "21000410": 1850, "21000420": 46500, "21000510": 348000, "21000520": 236000, "21000610": 2400000,
    "21000620": 14200, "21000710": 640, "21000720": 380, "21000810": 81000000, "31000010": 120000000, "31000020": 125000000, "31000030": 110000000,
    "31000040": 45000000, "31000050": 26400000, "31000110": 96500000, "31000120": 60000000, "31000121": 30000000, "31000130": 55000000,
    "31000131": 20000000, "31000140": 42500000, "31000210": 88000, "31000310": 510000, "31000320": 662609, "31000410": 17000000, "31000510": 330000000,
    "31000610": 66666667, "31000620": 14200000, "31000630": 2500000, "31000640": 2210000, "31000710": 1150000, "31000720": 96000, "31000730": 75000,
    "31000810": 1850000, "31000910": 1210000, "31000920": 2819040, "31000930": 1500000, "32000010": 3150000, "32000020": 410000, "32000030": 160000,
    "32000040": 9800000, "41000010": 0.82, "41000020": 24330, "41000030": 34000, "41000110": 5600, "41000120": 9800, "41000210": 42, "41000220": 70,
    "41000230": 40, "41000310": 2000, "41000410": 2900, "41000510": 980, "41000610": 52, "41000710": 640, "41000810": 18000, "41000820": 38000,
}
SHEET_RATE: dict[tuple[str, str], float] = {}      # (project, material) -> the sheet's Oct rate
for sheet in (ROADS_SHEET, RAILWAY_SHEET):
    for row, cols in sheet.items():
        for pid, (_q, rate) in cols.items():
            for code in SHEET_MATERIALS.get(row, []):
                SHEET_RATE.setdefault((pid, code), rate)
REGION = {pid: rng.uniform(0.92, 1.1) for pid in PROJ}


def rate_of(project: str, code: str, m: str) -> float:
    """The going rate for a material at a project in month m: the sheet rate in Oct 2026, drifted back in time by what moves it."""
    base = SHEET_RATE.get((project, code)) or BASE_RATE[code] * (REGION[project] if MAT[code]["group"] in ("AGGREGATE", "DUST", "GSB", "SAND", "WMM", "BOULDER", "BALLAST", "BLANKET", "CEMENT") else 1)
    g = MAT[code]["group"]
    if g == "TMT":
        return round(base * idx("STEEL_TMT", m) / idx("STEEL_TMT", "2026-10"), -1)
    if g in ("AGGREGATE", "DUST", "GSB", "SAND", "WMM", "BOULDER", "BALLAST", "BLANKET"):
        q = {"2025-11": 0.94, "2025-12": 0.94, "2026-01": 0.96, "2026-02": 0.96, "2026-03": 0.96, "2026-04": 0.98, "2026-05": 0.98, "2026-06": 0.98}.get(m, 1.0)
        return round(base * q)
    if g == "CEMENT":
        return round(base * idx("CEMENT_WPI", m) / idx("CEMENT_WPI", "2026-10"))
    if g == "HSD" and code == "15000010":
        return round(base * idx("HSD", m) / idx("HSD", "2026-10"), 2)
    if g in ("BITUMEN", "EMULSION"):
        k = months("2025-11", "2026-10").index(min(max(m, "2025-11"), "2026-10"))
        return round(base * (0.97 + 0.03 * k / 11))
    return base


# ================================================================================================================== demand: monthly need per project and sheet row
HIST = months("2025-11", "2026-10")
SEASON = {"roads": {"2026-07": 0.55, "2026-08": 0.5, "2026-09": 0.65}, "railway": {"2026-07": 0.8, "2026-08": 0.75, "2026-09": 0.85}}


def ramp(start: str, m: str) -> float:
    if m < start:
        return 0.0
    k = months(start, m).__len__() - 1
    return {0: 0.4, 1: 0.7}.get(k, 1.0)


NEED: dict[tuple[str, str, str], float] = {}       # (project, sheet row, month) -> qty
for sheet, vertical in ((ROADS_SHEET, "roads"), (RAILWAY_SHEET, "railway")):
    for row, cols in sheet.items():
        for pid, (q3, _rate) in cols.items():
            base = sum(q3) / 3
            for m in HIST:
                f = ramp(PROJ[pid]["start"], m) * SEASON[vertical].get(m, 1.0) * rng.uniform(0.85, 1.12)
                NEED[(pid, row, m)] = round(base * f) if m != "2026-10" else q3[0]
            NEED[(pid, row, "2026-11")], NEED[(pid, row, "2026-12")] = q3[1], q3[2]
# the roads projects nearing completion: busy until spring, then tapering to nothing (their sheet columns read 0)
TAPER = {"2025-11": 1.0, "2025-12": 0.95, "2026-01": 0.9, "2026-02": 0.8, "2026-03": 0.65, "2026-04": 0.5, "2026-05": 0.35, "2026-06": 0.2,
         "2026-07": 0.1, "2026-08": 0.05, "2026-09": 0.0, "2026-10": 0.0}
for pid in ("kd01", "kd02", "ap01", "karnal", "gew05"):
    for row, (oct_q, _r) in (("Aggregate", (30000, 0)), ("GSB", (16000, 0)), ("Cement", (2200, 0)), ("Bitumen-VG-40", (520, 0)), ("HSD", (160000, 0))):
        for m in HIST:
            NEED[(pid, row, m)] = round(oct_q * TAPER[m] * rng.uniform(0.85, 1.1))
# the civil works of the BESS, solar and T&D sites: small, steady, bought every two months
for pid in ("banaskantha", "dholera", "bikaner", "jodhpur", "angul"):
    for row, q in (("Aggregate", 2500), ("Cement", 450), ("Steel (HYSD)", 90)):
        for m in HIST:
            if int(m[5:7]) % 2 == 1:
                NEED[(pid, row, m)] = round(q * 2 * ramp(PROJ[pid]["start"], m) * rng.uniform(0.8, 1.2))

ROW_GROUP = {"R01": ("Aggregate", "Dust", "WMM (Air Cooled Slag)", "GSB", "Sand (Wash, Coarse, River, Msand)", "Cement", "GGBS", "Fly Ash", "HSD", "LSHS/LDO",
                     "Aggregate- 10MM", "Aggregate- 20 MM", "GSB/Boulder", "Ballast", "Blanketing Material"),
             "R02": ("Steel (HYSD)", "Bitumen-VG-40", "Bitumen-CRMB", "Emulsion-SS1", "Emulsion-RS1", "HT Strand", "Admixture")}
QUARTERLY_ROWS = {"Hume Pipe 600", "Geogrid", "W Beam Crash Barrier", "Elastomeric Bearing", "POT-PTFE Bearing", "Steel Girder", "Deck Sheet", "Drainage Spout",
                  "Strip Seal Expansion Joint (With Stud & Modular)", "Admixture", "Emulsion-RS1", "HT Strand", "Fly Ash", "GGBS", "LSHS/LDO", "Emulsion-SS1", "WMM (Air Cooled Slag)"}
BIMONTHLY_ROWS = {"Dust", "GSB/Boulder", "Ballast", "Blanketing Material", "Aggregate- 10MM", "Bitumen-CRMB"}      # bought for two months at a time


def group_for(project: str, row: str) -> str:
    """The flows' split of a project's buying into PR documents (R01/R02 roads, L02 railway, T02 BESS and T&D, N01 solar), kept as the first cast
    drew it so every document keeps its number. SAP's purchasing group on each line is the organogram's desk (desk_of)."""
    v = PROJ[project]["vertical"]
    if v == "railway":
        return "L02"
    if v in ("bess",):
        return "T02"
    if v == "solar":
        return "N01"
    if v == "td":
        return "T02"
    return "R02" if row in ROW_GROUP["R02"] or row in QUARTERLY_ROWS - {"Fly Ash", "GGBS"} else "R01"


# ================================================================================================================== flows
RATE_CS: dict[tuple, tuple[Vendor, float, str, date]] = {}     # (project, material, quarter) -> (L1 vendor, rate, cs no, approved on)


def cs_approver(project: str | None, material: str) -> str:
    """Who approves a CS: the GM or AGM the buying desk reports to (the desk's owner, on a GM's own desk)."""
    owner = GROUP_PERSON[desk_of(project, material)]
    return TEAM_BY[REPORTS_TO.get(owner) or owner]["name"]


def quarter(m: str) -> str:
    return f"{m[:4]}Q{(int(m[5:7]) - 1) // 3 + 1}"


def rate_cs(project: str, code: str, m: str, before: date) -> tuple[Vendor, float, str, date]:
    """The quarterly rate CS behind a bulk buy: 2-4 vendors quoted, the L1 approved a few days before the first PR of the quarter."""
    key = (project, code, quarter(m))
    if key in RATE_CS:
        return RATE_CS[key]
    cands = vendors_for(MAT[code]["group"], project)
    rng.shuffle(cands)
    cands = cands[: max(2, min(4, len(cands)))] if len(cands) >= 2 else cands
    l1_rate = rate_of(project, code, m)
    approved = before - timedelta(days=jitter(2, 9))
    rfq = approved - timedelta(days=jitter(5, 9))
    cs = cs_number(approved)
    for n, v in enumerate(cands):
        r = l1_rate if n == 0 else round(l1_rate * rng.uniform(1.03, 1.16), 2 if l1_rate < 200 else 0)
        QUOTES.append(Quote(cs, project, None, code, v, v.name, rfq, rfq + timedelta(days=jitter(2, 4)), 0, MAT[code]["uom"], r,
                            approved + timedelta(days=95), "Firm", "Approved", cs_approver(project, code), approved, buyer_for(project, code), f"Rate CS {quarter(m)}", n == 0))
    RATE_CS[key] = (cands[0], l1_rate, cs, approved)
    return RATE_CS[key]


def receive(item: PoItem, start: date, end: date, n: int, share: float = 1.0, late_days: int = 0) -> None:
    """n receipts between start and end (only those on or before the data date), summing to `share` of the ordered quantity."""
    if n <= 0:
        return
    span = max(0, (end - start).days)
    days = sorted(start + timedelta(days=late_days + (rng.randint(0, span) if span else 0)) for _ in range(n))
    total = item.qty * share
    left = total
    for k, d in enumerate(days):
        if d > AS_OF:
            break
        q = left if k == n - 1 else round(total / n * rng.uniform(0.8, 1.2), 3 if item.uom in ("MT", "KM") else 0)
        q = min(q, left)
        if q <= 0:
            break
        item.receipts.append(Receipt(item, d, round(q, 3)))
        left -= q


def bulk_flows() -> None:
    """Monthly PRs, POs and receipts for every sheet row with a need: the bulk of ME5A, ME2N and MB51."""
    for pid in sorted({k[0] for k in NEED}):
        p = PROJ[pid]
        for m in HIST + ["2026-11"]:
            rows = sorted({k[1] for k in NEED if k[0] == pid and k[2] == m and NEED[k] > 0})
            if m == "2026-11":
                rows = [r for r in rows if r not in QUARTERLY_ROWS]
            by_group: dict[str, list[str]] = defaultdict(list)
            for row in rows:
                if row in QUARTERLY_ROWS and int(m[5:7]) % 3 != 1:
                    continue
                if row in BIMONTHLY_ROWS and int(m[5:7]) % 2 != 1:
                    continue
                by_group[group_for(pid, row)].append(row)
            for g, grp_rows in sorted(by_group.items()):
                created = month_start(m) - timedelta(days=jitter(6, 14) if p["vertical"] == "roads" else jitter(12, 26))
                if created > AS_OF:
                    continue
                released = created + timedelta(days=jitter(1, 4))
                doc = PrDoc(pid, plant_of(pid), g, PLANNERS[pid], created, released if released <= AS_OF else None)
                doc.tracking = p["tracking"]
                for row in grp_rows:
                    qty = NEED[(pid, row, m)] * (3 if row in QUARTERLY_ROWS else 2 if row in BIMONTHLY_ROWS else 1)
                    codes = SHEET_MATERIALS[row]
                    split = [(codes[0], 1.0)]
                    if row == "Steel (HYSD)":
                        split = [(codes[0], 0.6), (codes[1], 0.4)]
                    elif row == "Sand (Wash, Coarse, River, Msand)" and pid in ("tumkur", "tirupati", "jh10", "narol"):
                        split = [(codes[1], 1.0)]
                    for code, share in split:
                        q = round(qty * share, 1 if MAT[code]["uom"] == "MT" and qty < 100 else 0)
                        if q <= 0:
                            continue
                        it = PrItem(doc, code, q, MAT[code]["uom"], month_start(m) + timedelta(days=jitter(0, 5)))
                        it.value_hint = q * rate_of(pid, code, m)
                        doc.items.append(it)
                if doc.items:
                    PR_DOCS.append(doc)
    # orders: one PO per vendor per PR doc, a few days after release
    for doc in [d for d in PR_DOCS if d.project and d.released]:
        by_vendor: dict[str, list[PrItem]] = defaultdict(list)
        lines: dict[int, tuple] = {}
        for it in doc.items:
            m = ym(it.needed_by)
            vendor, rate, cs, _ = rate_cs(doc.project, it.material, m, doc.created)
            by_vendor[vendor.code].append(it)
            lines[id(it)] = (vendor, rate)
        for vcode, its in sorted(by_vendor.items()):
            po_date = doc.released + timedelta(days=jitter(1, 5) if PROJ[doc.project]["vertical"] == "roads" else jitter(3, 12))
            if po_date > AS_OF:
                continue
            vendor = VEND[vcode]
            po = PoDoc(vendor, "ZNB", po_date, doc.plant, doc.project, doc.group, vendor.terms)
            for it in its:
                m = ym(it.needed_by)
                rate = lines[id(it)][1]
                price = round(rate * rng.uniform(0.997, 1.003), 2 if rate < 200 else 0) if not (doc.project == "tumkur" and it.material.startswith("1100002")) else rate
                pi = PoItem(po, it.material, it.qty, it.uom, price, 1, month_end(m) if month_end(m) > po_date else po_date + timedelta(days=7), it)
                it.po = pi
                po.items.append(pi)
                # deliveries through the month of need
                n = 6 if MAT[it.material]["group"] in ("AGGREGATE", "GSB", "BALLAST", "BLANKET", "HSD") else 4 if MAT[it.material]["group"] in ("DUST", "SAND", "CEMENT") else 2
                receive(pi, max(po_date + timedelta(days=1), month_start(m)), month_end(m), n, share=1.0 if rng.random() < 0.94 else rng.uniform(0.85, 0.97))
            PO_DOCS.append(po)


# ---------------------------------------------------------------------------------------------------- specialty buys (RFQ, CS, PO, milestones)
def specialty(project: str | None, plant: str, group: str, created: date, items: list[tuple[str, float, date]], *, vendors: list[str] | None = None,
              tat: tuple[int, int] = (15, 30), po: bool = True, receipt_late: int | None = None, tag: str = "", requisitioner: str | None = None,
              doc_type: str = "ZNB", validity_end: date | None = None, pv: tuple[str, str] = ("N", ""), price_unit: int = 1, same_day: bool = False,
              n_receipts: int = 1, quote_status: str | None = None) -> PrDoc:
    """One PR document of specialty items, its RFQ and CS rows, and (when `po`) the PO and receipts at the material's lead time."""
    released = created + timedelta(days=jitter(1, 4))
    doc = PrDoc(project, plant, group, requisitioner or (PLANNERS[project] if project else HO_STORES), created, released if released <= AS_OF else None)
    doc.tracking = PROJ[project]["tracking"] if project else ""
    doc.tag = tag
    for code, qty, need in items:
        it = PrItem(doc, code, qty, MAT[code]["uom"], need, tag=tag)
        it.value_hint = qty * BASE_RATE[code] * (price_unit and 1)
        doc.items.append(it)
    PR_DOCS.append(doc)
    if same_day:      # the PR is keyed in after the negotiation: the CS is approved first, the PR and the PO follow on one day
        po_date = created + timedelta(days=0 if rng.random() < 0.8 else 1)
        rfq = created - timedelta(days=jitter(25, 45))
        cs_on = created - timedelta(days=jitter(1, 3))
        doc.released = created
    else:
        if not doc.released:
            return doc
        rfq = doc.released + timedelta(days=jitter(2, 6))
        lo, hi = tat
        cs_on = rfq + timedelta(days=jitter(max(4, lo - 6), max(6, hi - 6)))
        po_date = cs_on + timedelta(days=jitter(1, 4))
    cs = cs_number(cs_on)
    for it in doc.items:
        cands = [VEND[c] for c in vendors] if vendors else vendors_for(MAT[it.material]["group"], project or "kanpur")
        cands = cands[:4]
        base = BASE_RATE[it.material]
        approved = cs_on <= AS_OF and quote_status is None
        if rfq > AS_OF:      # the RFQ has not gone out yet on the data date: nothing in the tracker
            continue
        for n, v in enumerate(cands):
            qd = rfq + timedelta(days=jitter(4, 11))
            r = base if n == 0 else round(base * rng.uniform(1.03, 1.15), 2 if base < 200 else 0)
            QUOTES.append(Quote(cs, project, it, it.material, v, v.name, rfq, qd if qd <= AS_OF else None, it.qty, it.uom, r if qd <= AS_OF else None,
                                qd + timedelta(days=60), pv[0] == "Y" and "PV" or "Firm", quote_status or ("Approved" if approved else "Pending"),
                                (TEAM_BY["Satish"]["name"] if it.qty * base > 5e7 else cs_approver(project, it.material)) if approved else "",
                                cs_on if approved else None, buyer_for(project, it.material), "", n == 0))
    if not po or po_date > AS_OF:
        return doc
    v0 = VEND[vendors[0]] if vendors else vendors_for(MAT[doc.items[0].material]["group"], project or "kanpur")[0]
    order = PoDoc(v0, doc_type, po_date, plant, project, group, v0.terms, validity_end, pv[0], pv[1], tag=tag)
    for it in doc.items:
        lead = MAT[it.material]["lead"]
        deliv = max(it.needed_by, po_date + timedelta(days=lead))
        pi = PoItem(order, it.material, it.qty, it.uom, BASE_RATE[it.material] * (price_unit if price_unit > 1 else 1), price_unit, deliv, it, tag=tag)
        it.po = pi
        order.items.append(pi)
        late = receipt_late if receipt_late is not None else (0 if rng.random() < v0.otd else jitter(3, 18))
        if deliv + timedelta(days=late) <= AS_OF:
            receive(pi, deliv - timedelta(days=jitter(0, 4)) + timedelta(days=late), deliv + timedelta(days=late + 6), n_receipts, share=1.0)
    PO_DOCS.append(order)
    return doc


def specialty_flows() -> None:
    d = lambda y, m, dd: date(y, m, dd)  # noqa: E731
    # railway P-Way fittings, quarterly per project
    pway = {"dhule": ["100601", "100231", "100603"], "aurangabad": ["100603", "100601", "100231"], "kanpur": ["100604", "100601"], "rvnl": ["100231", "100604"],
            "gaya": ["100604", "100603"], "anuppur": ["100604", "100601"], "dlf": ["100604", "100603"]}
    for pid, vs in pway.items():
        for k, m in enumerate(["2025-11", "2026-02", "2026-05", "2026-08"]):
            created = month_start(m) + timedelta(days=jitter(2, 12))
            need = created + timedelta(days=75)
            vlist = vs[k % len(vs):] + vs[:k % len(vs)]
            specialty(pid, plant_of(pid), "L02", created, [("21000010", jitter(18, 60) * 1000, need), ("21000020", jitter(10, 30) * 1000, need),
                                                           ("21000030", jitter(10, 40) * 1000, need)], vendors=vlist, tat=(14, 26))
    # OHE: masts, cantilevers, wires, insulators
    for pid in ("gaya", "aurangabad", "kanpur", "rvnl", "ndls"):
        for m in ["2025-12", "2026-04", "2026-07"]:
            created = month_start(m) + timedelta(days=jitter(2, 15))
            need = created + timedelta(days=90)
            specialty(pid, plant_of(pid), "L01", created, [("21000210", jitter(120, 400), need), ("21000230", jitter(80, 300), need),
                                                           ("21000410", jitter(400, 1500), need)], vendors=["100611", "100613", "100614"], tat=(14, 24))
        specialty(pid, plant_of(pid), "L01", d(2026, 3, 9) + timedelta(days=jitter(0, 20)), [("21000310", jitter(20, 60), d(2026, 7, 15)),
                                                                                              ("21000320", jitter(20, 60), d(2026, 7, 15))], vendors=["100612"], tat=(16, 26))
    # S&T: cables, relays, ducts
    for pid in ("aurangabad", "kanpur", "gaya", "ndls", "rvnl"):
        for m in ["2026-01", "2026-06"]:
            created = month_start(m) + timedelta(days=jitter(2, 15))
            need = created + timedelta(days=95)
            specialty(pid, plant_of(pid), "L01", created, [("21000510", jitter(8, 30), need), ("21000620", jitter(40, 160), need), ("21000710", jitter(2000, 8000), need)],
                      vendors=["100621", "100623", "100624"], tat=(18, 30))
    # traction transformers: RVNL delivered, Aurangabad (MFC story), Gaya (inspection story)
    specialty("rvnl", plant_of("rvnl"), "L01", d(2025, 11, 4), [("21000810", 2, d(2026, 7, 31))], vendors=["100701", "100704"], tat=(30, 40), tag="rvnl_tfr", n_receipts=1)
    STORY["mfc_pr"] = specialty("aurangabad", plant_of("aurangabad"), "L01", d(2025, 12, 1), [("21000810", 2, d(2027, 3, 31))], vendors=["100701", "100704"], tat=(32, 40),
                                tag="mfc", validity_end=d(2026, 10, 31))
    STORY["insp_pr"] = specialty("gaya", plant_of("gaya"), "L01", d(2026, 1, 27), [("21000810", 1, d(2026, 11, 30))], vendors=["100701", "100704"], tat=(30, 36),
                                 tag="inspection", validity_end=d(2027, 3, 31))
    # the late-streak vendor's open order for Dhule (its revised schedule is in the mail)
    STORY["streak_pr"] = specialty("dhule", plant_of("dhule"), "L02", d(2026, 8, 24), [("21000010", 54000, d(2026, 11, 10)), ("21000020", 26000, d(2026, 11, 10))],
                                   vendors=["100601", "100603"], tat=(14, 20), tag="streak_open")
    # the renamed vendor's open lines under its old code
    STORY["rename_pr"] = specialty("dhule", plant_of("dhule"), "L02", d(2026, 8, 3), [("21000040", 22000, d(2026, 11, 20)), ("21000030", 30000, d(2026, 12, 5))],
                                   vendors=["100231", "100604"], tat=(14, 20), tag="rename_open")
    # Gaya OHE masts due 6 Nov, needed for mast erection by 12 Nov (the vendor moves them to 20 Nov in the mail)
    STORY["masts_pr"] = specialty("gaya", plant_of("gaya"), "L01", d(2026, 8, 6), [("21000210", 320, d(2026, 11, 12)), ("21000220", 80, d(2026, 11, 12))],
                                  vendors=["100611", "100613"], tat=(14, 18), tag="masts")
    # Kanpur: the WO whose contractor's cables failed inspection (supply ~90% of the value), and S&T cable
    STORY["wo_pr"] = specialty("kanpur", plant_of("kanpur"), "L02", d(2026, 5, 18), [("21000510", 18, d(2026, 8, 31)), ("41000820", 18, d(2026, 9, 30))],
                               vendors=["100801"], tat=(14, 20), tag="wo", doc_type="ZWO", n_receipts=2)
    # BESS: PRs keyed in after the negotiation (same day as the PO)
    bess_items = [
        ("dholera", "100732", [("31000620", 24, d(2026, 6, 30))], d(2025, 12, 18)),
        ("dholera", "100706", [("31000050", 10, d(2026, 8, 31))], d(2025, 12, 12)),
        ("dholera", "100702", [("31000110", 2, d(2026, 9, 30))], d(2026, 1, 20)),
        ("dholera", "100721", [("32000010", 42, d(2026, 7, 31))], d(2026, 3, 2)),
        ("dholera", "100742", [("31000910", 6, d(2026, 5, 31))], d(2026, 2, 16)),
        ("dholera", "100703", [("31000630", 18, d(2026, 7, 15))], d(2026, 3, 10)),
        ("banaskantha", "100731", [("31000610", 24, d(2026, 8, 31))], d(2025, 12, 22)),
        ("banaskantha", "100732", [("31000620", 12, d(2026, 7, 31))], d(2026, 1, 8)),
        ("banaskantha", "100721", [("32000010", 30, d(2026, 7, 31))], d(2026, 3, 4)),
        ("banaskantha", "100742", [("31000910", 4, d(2026, 5, 31))], d(2026, 2, 18)),
        ("banaskantha", "100703", [("31000640", 2, d(2026, 6, 30))], d(2026, 3, 12)),
        ("dholera", "100703", [("31000640", 2, d(2026, 7, 15))], d(2026, 4, 6)),
        ("banaskantha", "100705", [("31000130", 1, d(2026, 9, 15))], d(2026, 6, 2)),
        ("dholera", "100705", [("31000130", 1, d(2026, 9, 15))], d(2026, 6, 2)),
        ("dholera", "100703", [("31000930", 1, d(2026, 8, 31))], d(2026, 7, 7)),
        ("banaskantha", "100703", [("31000930", 1, d(2026, 8, 31))], d(2026, 7, 7)),
    ]
    for pid, vcode, its, created in bess_items:
        doc = specialty(pid, plant_of(pid), "T02" if MAT[its[0][0]]["group"] in ("CABLE", "ELE-MISC") else "N01", created, its, vendors=[vcode], same_day=True,
                        tag="ida" if its[0][0] == "31000050" else "")
        if its[0][0] == "31000050":
            STORY["idt_pr"] = doc
    # the Dholera BESS containers: an import PO, its LC still to be opened
    STORY["containers_pr"] = specialty("dholera", plant_of("dholera"), "N01", d(2026, 9, 25), [("31000610", 48, d(2027, 3, 31))], vendors=["100731"], same_day=True,
                                       doc_type="ZIMP", tag="containers")
    # solar
    for pid in ("bikaner", "jodhpur"):
        for code, qty, created in (("31000710", 40, d(2025, 12, 3)), ("31000720", 620, d(2026, 1, 12)), ("32000020", 35, d(2026, 2, 9)),
                                   ("31000050", 4, d(2026, 2, 23)), ("32000030", 18, d(2026, 4, 14)), ("31000130", 1, d(2026, 5, 11))):
            specialty(pid, plant_of(pid), "N01" if code in ("31000710", "31000050") else "T02", created, [(code, qty, created + timedelta(days=MAT[code]["lead"] + 30))],
                      tat=(20, 32))
    # solar O&M spares raised in Aug-Sep and not converted (the TAT report prints 0 for them)
    for pid, n in (("bikaner", 6), ("jodhpur", 1)):
        for k in range(n):
            specialty(pid, plant_of(pid), "N01", d(2026, 8, 4) + timedelta(days=7 * k), [("31000730", jitter(2, 8), d(2026, 11, 30))], po=False, tag="om_open")
    # T&D: Angul towers and conductor (PV), insulators
    STORY["cond_pr"] = specialty("angul", plant_of("angul"), "T02", d(2026, 1, 5), [("31000310", 350, d(2026, 9, 30))], vendors=["100712", "100713"], tat=(30, 38),
                                 pv=("Y", "IEEMA-ACSR | Base 01/2026 | Variable 75%"), tag="pvclaim")
    specialty("angul", plant_of("angul"), "T02", d(2026, 1, 8), [("31000210", 2400, d(2026, 10, 31))], vendors=["100711"], tat=(28, 36),
              pv=("Y", "STEEL-STRUCT | Base 01/2026 | Variable 70%"), n_receipts=3)
    specialty("angul", plant_of("angul"), "T01", d(2026, 3, 16), [("31000410", 1, d(2027, 1, 31))], vendors=["100714", "100614"], tat=(30, 40))
    # Gaya: a DG delivered in August and commissioned
    specialty("gaya", plant_of("gaya"), "L02", d(2026, 4, 6), [("31000810", 1, d(2026, 8, 15))], vendors=["100741"], tat=(14, 20), tag="gaya_dg")
    # roads bridge items, quarterly (AAC blocks and admixture priced per 1,000)
    for pid in ("jh10", "jec", "narol", "ayodhya", "tirupati", "jh13", "tumkur"):
        for m in ["2026-01", "2026-04", "2026-07"]:
            if m < PROJ[pid]["start"]:
                continue
            created = month_start(m) + timedelta(days=jitter(1, 12))
            need = created + timedelta(days=40)
            specialty(pid, plant_of(pid), "R02", created, [("41000610", jitter(20, 80) * 1000, need)], vendors=["100506"], tat=(6, 12), price_unit=1000)
            specialty(pid, plant_of(pid), "R02", created + timedelta(days=jitter(0, 6)), [("41000710", jitter(800, 3000), need)], vendors=["100506"], tat=(6, 12))
    # the pipeline: PRs raised in September and October whose RFQ is out or whose CS is pending on the data date
    pipe = [("rvnl", "L02", "21000040"), ("anuppur", "L02", "21000010"), ("dlf", "L02", "21000020"), ("ndls", "L01", "21000620"), ("thane", "L01", "21000710"),
            ("kanpur", "L01", "21000410"), ("aurangabad", "L01", "21000230"), ("bikaner", "N01", "31000710"), ("jodhpur", "T02", "32000020"), ("angul", "T02", "31000910"),
            ("dholera", "T02", "31000930"), ("rvnl", "L01", "21000510"), ("dhule", "L02", "21000030"), ("gaya", "L02", "41000710")]
    for k in range(48):
        pid, grp, code = pipe[k % len(pipe)]
        created = date(2026, 9, 1) + timedelta(days=jitter(0, 46))
        qty = {"KM": jitter(4, 20), "NO": jitter(50, 900) if BASE_RATE[code] > 1000 else jitter(2000, 20000), "SET": jitter(20, 120), "LOT": 1, "RM": jitter(800, 4000),
               "SQM": jitter(500, 2500)}[MAT[code]["uom"]]
        specialty(pid, plant_of(pid), grp, created, [(code, qty, created + timedelta(days=MAT[code]["lead"] + 40))], tat=(30, 45), po=False,
                  quote_status="Pending" if created < date(2026, 10, 1) else None)
    # HO stores: PRs with no project (no tracking number)
    for k in range(14):
        code = rng.choice(["31000910", "41000710", "21000720", "21000620", "32000030", "41000410"])
        specialty(None, HO_PLANT[0], rng.choice(["L02", "T02", "R02"]), date(2026, 3, 2) + timedelta(days=13 * k), [(code, jitter(5, 60), date(2026, 3, 2) + timedelta(days=13 * k + 45))],
                  tat=(10, 20), requisitioner=HO_STORES, tag="no_project")


# ---------------------------------------------------------------------------------------------------- the stories that are PRs (not ordered)
def story_prs() -> None:
    d = lambda y, m, dd: date(y, m, dd)  # noqa: E731
    # 1. Kanpur signalling cable: needed in 3 weeks, 10 weeks' lead time
    doc = PrDoc("kanpur", plant_of("kanpur"), "L01", PLANNERS["kanpur"], d(2026, 10, 13), d(2026, 10, 15))
    doc.tracking, doc.tag = PROJ["kanpur"]["tracking"], "late_pr"
    it = PrItem(doc, "21000510", 18, "KM", d(2026, 11, 3), tag="late_pr")
    it.value_hint = 18 * 348000
    doc.items.append(it)
    PR_DOCS.append(doc)
    STORY["late_pr"] = doc
    cs = cs_number(d(2026, 10, 16))
    for v, rate, qd, valid, remark in (("100621", 348000, d(2026, 10, 19), d(2026, 12, 18), "Delivery 10 weeks from PO"),
                                       ("100624", 362000, d(2026, 10, 19), d(2026, 11, 30), "Delivery 9-10 weeks"),
                                       ("100625", 410000, d(2026, 10, 18), d(2026, 10, 31), "Stockist: 6 KM ex-stock in 2 weeks, balance 10 weeks")):
        QUOTES.append(Quote(cs, "kanpur", it, "21000510", VEND[v], VEND[v].name, d(2026, 10, 16), qd, 18, "KM", rate, valid, "Firm", "Pending", buyer=buyer_for("kanpur", "21000510"),
                            remarks=remark, l1=v == "100621"))
    # 21. Aurangabad IPS: RFQ out, the vendors cannot quote without the spec; Projects has not sent it
    doc = PrDoc("aurangabad", plant_of("aurangabad"), "L01", PLANNERS["aurangabad"], d(2026, 9, 16), d(2026, 9, 18))
    doc.tracking, doc.tag = PROJ["aurangabad"]["tracking"], "stuck"
    it = PrItem(doc, "21000610", 2, "SET", d(2026, 12, 15), tag="stuck")
    it.value_hint = 2 * 2400000
    doc.items.append(it)
    PR_DOCS.append(doc)
    STORY["stuck_pr"] = doc
    cs = cs_number(d(2026, 9, 22))
    for v in ("100622", "100623", "100624"):
        QUOTES.append(Quote(cs, "aurangabad", it, "21000610", VEND[v], VEND[v].name, d(2026, 9, 22), None, 2, "SET", None, None, "Firm", "On hold",
                            buyer=buyer_for("aurangabad", "21000610"), remarks="Spec awaited from Projects (asked 27.09.2026)"))
    # 2. Gaya: 32 PR lines raised for the Oct-Dec plan, RFQ out to 3-4 vendors, then deleted on Projects' instruction (15 Oct)
    gaya_items = [("21000230", 120), ("21000410", 900), ("21000420", 24), ("21000710", 2600), ("21000720", 1200), ("21000510", 7), ("21000520", 5), ("21000620", 90),
                  ("21000710", 4200), ("21000720", 1800), ("21000010", 28000), ("21000020", 14000), ("21000030", 20000), ("21000040", 9000), ("21000210", 40),
                  ("21000220", 24), ("31000910", 1), ("41000710", 1200), ("32000030", 6), ("21000230", 60), ("21000410", 420), ("21000510", 6), ("21000620", 60),
                  ("21000710", 1800), ("21000010", 12000), ("21000020", 6000), ("21000030", 9000), ("21000040", 4000), ("21000720", 900), ("21000520", 4),
                  ("32000020", 3), ("21000420", 8)]
    docs = []
    for k, (created, rel) in enumerate(((d(2026, 9, 8), d(2026, 9, 12)), (d(2026, 9, 14), d(2026, 9, 18)), (d(2026, 9, 19), d(2026, 9, 24)))):
        g = PrDoc("gaya", plant_of("gaya"), "L01" if k < 2 else "L02", PLANNERS["gaya"], created, rel)
        g.tracking, g.tag = PROJ["gaya"]["tracking"], "cancelled"
        docs.append(g)
        PR_DOCS.append(g)
    quoted_full = set(range(18))
    for n, (code, qty) in enumerate(gaya_items):
        g = docs[0] if n < 12 else docs[1] if n < 24 else docs[2]
        it = PrItem(g, code, qty, MAT[code]["uom"], d(2026, 11, 15) + timedelta(days=15 * (n % 3)), deletion="X", changed_on=d(2026, 10, 15), tag="cancelled")
        it.value_hint = qty * BASE_RATE[code]
        g.items.append(it)
        rfq = g.released + timedelta(days=jitter(5, 9))
        cs = cs_number(rfq)
        vendors = vendors_for(MAT[code]["group"], "gaya")[:4]
        while len(vendors) < 4:
            vendors.append(next(v for v in VEND.values() if MAT[code]["group"] in v.groups and v not in vendors) if any(MAT[code]["group"] in v.groups and v not in vendors for v in VEND.values()) else vendors[0])
        nq = 4 if n in quoted_full else rng.choice([2, 3])
        for j, v in enumerate(vendors[:4]):
            qd = rfq + timedelta(days=jitter(6, 12)) if j < nq else None
            r = round(BASE_RATE[code] * (1 if j == 0 else rng.uniform(1.03, 1.14)), 2 if BASE_RATE[code] < 200 else 0) if qd else None
            QUOTES.append(Quote(cs, "gaya", it, code, v, v.name, rfq, qd if qd and qd <= AS_OF else None, qty, MAT[code]["uom"], r if qd and qd <= AS_OF else None,
                                (qd + timedelta(days=45)) if qd else None, "Firm", "Cancelled (PR deleted)", buyer=buyer_for("gaya", code), l1=j == 0 and qd is not None))
    STORY["gaya_docs"] = docs
    # short-closed lines: a monthly need that fell away before the order (Closed, no PO), most in the monsoon months
    open_items = [i for x in PR_DOCS if x.project and x.tag == "" for i in x.items if i.po is None and not i.deletion and x.released]
    for it in rng.sample([i for x in PR_DOCS if x.project and x.tag == "" and x.created < date(2026, 9, 1) for i in x.items if i.po is not None], 140):
        po_item = it.po
        po_item.doc.items.remove(po_item)
        it.po, it.closed, it.changed_on = None, "X", min(AS_OF, it.doc.created + timedelta(days=jitter(5, 20)))
    for po in [x for x in PO_DOCS if not x.items]:
        PO_DOCS.remove(po)
    # ordinary deletions elsewhere (one or two lines at a time, before any RFQ)
    for k in range(30):
        doc = rng.choice([x for x in PR_DOCS if x.project and x.tag == "" and x.items])
        it = rng.choice(doc.items)
        if it.po is None and not it.deletion:
            it.deletion, it.changed_on = "X", min(AS_OF, doc.created + timedelta(days=jitter(2, 12)))


# ---------------------------------------------------------------------------------------------------- emergency buys, same-day PRs, bags, WO
def odd_records() -> None:
    d = lambda y, m, dd: date(y, m, dd)  # noqa: E731
    # POs with no PR: HSD top-ups, crane hire, cement in an emergency
    for k in range(25):
        pid = rng.choice(["jh10", "ayodhya", "narol", "tirupati", "tumkur", "gaya", "aurangabad", "dholera", "jec"])
        code, qty = rng.choice([("15000010", jitter(8, 30) * 1000), ("41000810", jitter(2, 8)), ("12000010", jitter(60, 240))])
        when = d(2025, 11, 10) + timedelta(days=jitter(0, 330))
        if when > AS_OF:
            continue
        group = "R01" if code != "41000810" else ("L02" if PROJ[pid]["vertical"] == "railway" else "R01")
        vendor = vendors_for(MAT[code]["group"], pid)[0]
        po = PoDoc(vendor, "ZNB", when, plant_of(pid), pid, group, vendor.terms, tag="no_pr")
        pi = PoItem(po, code, qty, MAT[code]["uom"], rate_of(pid, code, ym(when)), 1, when + timedelta(days=2))
        po.items.append(pi)
        receive(pi, when + timedelta(days=1), when + timedelta(days=3), 1)
        PO_DOCS.append(po)
    # PRs keyed in the same day as their PO on roads sites (an urgent buy written up afterwards)
    roads_docs = [x for x in PR_DOCS if x.project and PROJ[x.project]["vertical"] == "roads" and x.tag == "" and all(i.po for i in x.items) and x.items]
    for doc in rng.sample(roads_docs, 14):
        po_doc = doc.items[0].po.doc
        doc.created = po_doc.doc_date
        doc.released = po_doc.doc_date
    # cement bought by the bag from dealers (the order unit is BAG; 20 bags = 1 MT)
    dealer_lines = [pi for po in PO_DOCS for pi in po.items if pi.material in ("12000010", "12000020") and po.vendor.code in ("100204", "100205", "100206", "100207")]
    for pi in rng.sample(dealer_lines, min(30, len(dealer_lines))):
        pi.uom = "BAG"
        pi.qty = round(pi.qty * 20)
        pi.price = round(pi.price / 20, 2)
        for r in pi.receipts:
            r.qty = round(r.qty * 20)
        if pi.pr:
            pi.pr.uom, pi.pr.qty = "BAG", round(pi.pr.qty * 20)


# ================================================================================================================== numbering (SAP numbers rise with time)
def number_everything() -> None:
    for n, doc in enumerate(sorted(PR_DOCS, key=lambda x: (x.created, x.plant)), 1):
        doc.number = f"{1000200000 + n * 7 + rng.randint(0, 5)}"
        for k, it in enumerate(doc.items, 1):
            it.item_no = k * 10
            it.short_text = MAT[it.material]["desc"]
    for n, po in enumerate(sorted(PO_DOCS, key=lambda x: (x.doc_date, x.plant)), 1):
        po.number = f"{4500120000 + n * 3 + rng.randint(0, 2)}"
        for k, it in enumerate(po.items, 1):
            it.item_no = k * 10
            it.short_text = MAT[it.material]["desc"]
    rec = sorted((r for po in PO_DOCS for it in po.items for r in it.receipts), key=lambda r: (r.posting, r.item.doc.plant))
    for n, r in enumerate(rec, 1):
        r.number = f"{5000300000 + n * 2 + rng.randint(0, 1)}"
        r.reference = f"DC/{r.posting.strftime('%y%m')}/{rng.randint(100, 9999)}"


# ================================================================================================================== the story values the mail needs
def fix_stories() -> None:
    d = lambda y, m, dd: date(y, m, dd)  # noqa: E731
    mfc = STORY["mfc_pr"].items[0].po
    mfc.doc.doc_date, mfc.price, mfc.delivery = d(2026, 1, 20), 81000000, d(2027, 3, 31)
    mfc.doc.validity_end = d(2026, 10, 31)
    ins = STORY["insp_pr"].items[0].po
    ins.doc.doc_date, ins.price, ins.delivery = d(2026, 3, 5), 83000000, d(2026, 11, 30)
    cond = STORY["cond_pr"].items[0].po
    cond.doc.doc_date, cond.price, cond.delivery = d(2026, 2, 18), 510000, d(2026, 12, 31)
    cond.receipts = []
    for posted, q in ((d(2026, 7, 21), 60), (d(2026, 8, 24), 60), (d(2026, 9, 18), 70), (d(2026, 9, 29), 50)):
        cond.receipts.append(Receipt(cond, posted, q))
    idt = STORY["idt_pr"].items[0].po
    idt.doc.doc_date, idt.price, idt.delivery = d(2025, 12, 12), 26400000, d(2026, 12, 31)
    idt.receipts = []
    cont = STORY["containers_pr"].items[0].po
    cont.price = 66666667
    cont.receipts = []
    masts = STORY["masts_pr"].items
    for it in masts:
        it.po.delivery, it.po.receipts = d(2026, 11, 6), []
    streak = STORY["streak_pr"].items
    for it in streak:
        it.po.delivery, it.po.receipts = d(2026, 11, 10), []
    for it in STORY["rename_pr"].items:
        it.po.receipts = []
    # the late-streak vendor: its last four receipts were late (6 to 14 days)
    k_items = sorted((pi for po in PO_DOCS if po.vendor.code == "100601" for pi in po.items if pi.receipts and pi.delivery < d(2026, 10, 1)), key=lambda p: p.receipts[-1].posting)
    for pi, late in zip(k_items[-4:], (6, 9, 11, 14)):
        pi.receipts = [Receipt(pi, pi.delivery + timedelta(days=late), pi.qty)]
    for pi in k_items[:-4]:
        pi.receipts = [Receipt(pi, pi.delivery - timedelta(days=jitter(0, 5)), pi.qty)]
    # its lines due in October are late too: received 6 days after the due date, which for a line due 19 Oct is after the data date, so on 20 Oct
    # the last four receipts are the late ones and that line is still open (no random draw changes: the receipt keeps its place in every sample)
    for po in PO_DOCS:
        for pi in po.items:
            if po.vendor.code == "100601" and pi.delivery >= d(2026, 10, 1) and pi.receipts and pi not in [it.po for it in streak]:
                pi.receipts = [Receipt(pi, pi.delivery + timedelta(days=6), pi.qty)]
    # the Kanpur WO: the contractor's cable was received in August and failed inspection in October (no QA record in SAP)
    wo = STORY["wo_pr"].items[0].po
    wo.doc.doc_date = d(2026, 6, 10)
    wo.receipts = [Receipt(wo, d(2026, 8, 26), 10), Receipt(wo, d(2026, 9, 9), 8)]
    lay = STORY["wo_pr"].items[1].po
    lay.receipts = []


# ================================================================================================================== writers
def write_ref_files() -> None:
    COUNTS["sheets/Project Directory.csv"] = write_csv("sheets/Project Directory.csv",
                                                       ["Project", "Vertical", "Stage", "State", "District", "Plant", "Tracking No.", "Project Head", "Head Email",
                                                        "Planner", "Planner Email", "SAP Plant Name"], DIRECTORY)
    pre = ["Purchasing Groups (T024) | Exported 02.04.2026 11:05:12 | User SSINGH"]
    for _ in range(10):      # the draws the first cast's ten group telephones took: kept, so every later draw keeps its place
        rng.randint(100000, 999999)
    COUNTS["sap/purchasing_groups.csv"] = write_csv("sap/purchasing_groups.csv", ["Purch. Group", "Description", "Telephone", "E-Mail Address"],
                                                    [[g, desc, f"+91 141 41{20 + n:02d} {200 + n}", email_of(buyer_of_group(g), INTERNAL_DOMAIN)]
                                                     for n, (g, desc) in enumerate(PURCH_GROUPS.items())], pre)
    shutil.copyfile(Path(__file__).parent / ORGANOGRAM, DATA / "sheets/SCM Material Organogram.csv")      # HG's own sheet, as it was supplied
    COUNTS["sheets/SCM Material Organogram.csv"] = sum(1 for _ in csv.reader((DATA / "sheets/SCM Material Organogram.csv").open(encoding="utf-8")))
    pre = [f"Material Master (MM60) | Exported 19.10.2026 18:42:07 | User SSINGH"]
    rows = [[m["code"], m["desc"], m["group"], m["uom"], m["alt"] or "", str(m["alt_per"] or ""), str(m["lead"]), m["pv"] or ""] for m in MAT.values()]
    COUNTS["sap/material_master.csv"] = write_csv("sap/material_master.csv", ["Material", "Material Description", "Material Group", "Base Unit of Measure",
                                                                               "Alternative Unit", "Alt. Units per Base Unit", "Planned Deliv. Time (days)", "PV Index"], rows, pre)
    pre = [f"Vendor Master (XK03 list) | Exported 19.10.2026 18:40:51 | User SSINGH"]
    rows = [[v.code, v.name, v.gstin, v.pan, "Y" if v.msme else "N", v.udyam, v.city, v.state or "China", v.bank, v.contact, v.email, v.phone, v.blocked, dmy(v.created)]
            for v in sorted(VEND.values(), key=lambda v: v.code)]
    COUNTS["sap/vendor_master.csv"] = write_csv("sap/vendor_master.csv", ["Vendor", "Name 1", "GSTIN", "PAN", "MSME", "Udyam Reg. No.", "City", "Region",
                                                                           "Bank Account", "Contact Person", "E-Mail Address", "Telephone", "Payment Block", "Created On"], rows, pre)


def pr_rows() -> list[list]:
    rows = []
    for doc in sorted(PR_DOCS, key=lambda x: x.number):
        for it in doc.items:
            po_no = it.po.doc.number if it.po else ""
            po_item = str(it.po.item_no) if it.po else ""
            rows.append([doc.number, str(it.item_no), it.material, it.short_text, f"{it.qty:g}", it.uom, doc.plant, desk_of(doc.project, it.material), doc.requisitioner, dmy(doc.created),
                         dmy(doc.released), dmy(it.needed_by), po_no, po_item, doc.tracking, it.deletion, it.closed, dmy(it.changed_on)])
    return rows


def po_rows() -> list[list]:
    rows = []
    for po in sorted(PO_DOCS, key=lambda x: x.number):
        group = po_desk(po)
        for it in po.items:
            rows.append([po.number, str(it.item_no), po.doc_type, po.vendor.code, it.material, it.short_text, f"{it.qty:g}", it.uom, f"{it.price:.2f}",
                         str(it.price_unit), "INR", dmy(po.doc_date), dmy(it.delivery), po.plant, group, TEAM_BY[GROUP_PERSON[group]]["sap"],
                         it.pr.doc.number if it.pr else "", str(it.pr.item_no) if it.pr else "", dmy(po.validity_end), po.pv_clause, po.pv_index, po.terms])
    return rows


def plant_name(plant: str) -> str:
    if plant == HO_PLANT[0]:
        return HO_PLANT[1]
    return next(p["sap_name"] for p in PROJ.values() if plant in p["plants"])


def mb51_rows() -> list[list]:
    rows, extra = [], []
    for po in PO_DOCS:
        for it in po.items:
            for r in it.receipts:
                amount = r.qty * it.price / it.price_unit
                rows.append((r.posting, [r.number, "1", r.mvt, dmy(r.posting), it.material, it.short_text, po.plant, plant_name(po.plant), f"{r.qty:.3f}", it.uom,
                                         f"{amount:.2f}", po.number, str(it.item_no), po.vendor.code, r.reference, dmy(r.posting)]))
    # reversals (102) of a wrong receipt, posted the same or the next day; and returns to the vendor (122)
    recs = [x for x in rows if x[1][2] == "101" and x[0] < AS_OF - timedelta(days=2)]
    for when, row in rng.sample(recs, 70):
        d2 = when + timedelta(days=rng.choice([0, 0, 1]))
        q = float(row[8]) * rng.choice([1.0, 1.0, 0.5])
        amt = float(row[10]) * q / float(row[8])
        extra.append((d2, [f"{int(row[0]) + 1}", "1", "102", dmy(d2), row[4], row[5], row[6], row[7], f"{-q:.3f}", row[9], f"{-amt:.2f}", row[11], row[12], row[13],
                           row[14], dmy(d2)]))
    for when, row in rng.sample(recs, 20):
        d2 = when + timedelta(days=jitter(3, 15))
        if d2 > AS_OF:
            continue
        q = round(float(row[8]) * rng.uniform(0.05, 0.2), 3)
        amt = float(row[10]) * q / float(row[8])
        extra.append((d2, [f"{int(row[0]) + 1}", "2", "122", dmy(d2), row[4], row[5], row[6], row[7], f"{-q:.3f}", row[9], f"{-amt:.2f}", row[11], row[12], row[13],
                           row[14] + "-RET", dmy(d2)]))
    for k, (_d, row) in enumerate(sorted(extra, key=lambda x: (x[0], x[1][11])), 1):      # reversals and returns: their own documents, numbered in posting order
        row[0] = f"{4900500000 + k * 3}"
    out = [r for _, r in sorted(rows + extra, key=lambda x: (x[0], x[1][0]))]
    # duplicate rows: the same line exported twice (a download that was appended to)
    for i in sorted(rng.sample(range(len(out)), 18), reverse=True):
        out.insert(i + 1, list(out[i]))
    return [r for r in out if datetime.strptime(r[3], "%d.%m.%Y").date() <= AS_OF]      # an export taken on the data date holds nothing posted later


def write_sap() -> None:
    COUNTS["sap/ME5A_purchase_requisitions.csv"] = write_csv(
        "sap/ME5A_purchase_requisitions.csv",
        ["Purchase Requisition", "Item of Requisition", "Material", "Short Text", "Quantity Requested", "Unit of Measure", "Plant", "Purchasing Group",
         "Name of Requisitioner/Requester", "Requisition Date", "Release Date", "Delivery Date", "Purchase Order", "Purchase Order Item",
         "Requirement Tracking Number", "Deletion Indicator", "Closed", "Changed On"], pr_rows(),
        ["ME5A - List Display of Purchase Requisitions | Exported 20.10.2026 08:12:41 | User SSINGH | Variant /SCM_ALL"])
    COUNTS["sap/ME2N_purchase_orders.csv"] = write_csv(
        "sap/ME2N_purchase_orders.csv",
        ["Purchasing Document", "Item", "Document Type", "Supplier", "Material", "Short Text", "Order Quantity", "Order Unit", "Net Price", "Price Unit", "Currency",
         "Document Date", "Delivery Date", "Plant", "Purchasing Group", "Created By", "Purchase Requisition", "Item of Requisition", "Validity Per. End",
         "PV Clause", "PV Index", "Terms of Payment"], po_rows(),
        ["ME2N - Purchasing Documents per Document Number | Exported 20.10.2026 08:15:09 | User SSINGH | Variant /SCM_OPEN_CLOSED"])
    COUNTS["sap/MB51_goods_receipts.csv"] = write_csv(
        "sap/MB51_goods_receipts.csv",
        ["Material Document", "Material Doc.Item", "Movement Type", "Posting Date", "Material", "Material Description", "Plant", "Name 1", "Quantity",
         "Unit of Entry", "Amount in LC", "Purchase Order", "Item", "Supplier", "Reference", "Entry Date"], mb51_rows(),
        ["MB51 - Material Document List | Exported 20.10.2026 08:21:30 | User SSINGH | Mvt 101,102,122"])


def write_drift_fixture() -> None:
    """An export the recipe has not seen, for the Data steward on Import: the railway site office's own ME2N download for October, with its columns
    renamed, slash dates, Indian digit grouping and the plant written as the site's name (one of them misspelt as the fund sheet writes it). Not read
    by the build: it waits in data/incoming until a person has the steward read it. No random draw: it is cut from the ME2N rows already written."""
    rows = [r for r in csv.reader((DATA / "sap/ME2N_purchase_orders.csv").open(encoding="utf-8"))][2:]
    site = {"1905": "Arurangabad", "1906": "Gaya", "1904": "Dhule", "1903": "Kanpur"}
    keep = [r for r in rows if r[13] in site and r[11][3:] in ("09.2026", "10.2026")][:60]
    def grouped(x: str) -> str:
        whole, _, dec = x.partition(".")
        head, tail = whole[:-3], whole[-3:]
        g = ",".join(re.findall(r"\d{1,2}", head[::-1]))[::-1] if head else ""
        return (f"{g},{tail}" if g else tail) + (f".{dec}" if dec else "")
    out = [[r[0], r[1], r[3], r[4], r[5], grouped(r[6].split(".")[0]), r[7], grouped(r[8]), r[11].replace(".", "/"), r[12].replace(".", "/"), site[r[13]], r[14], r[16]] for r in keep]
    COUNTS["incoming/ME2N_site_office_Oct26.csv"] = write_csv("incoming/ME2N_site_office_Oct26.csv",
        ["PO Number", "Line", "Vendor Code", "Material No", "Description", "Qty Ordered", "UoM", "Rate (Rs.)", "PO Date", "Delivery", "Site", "Buyer Group", "PR No"], out)


# ================================================================================================================== main
def main() -> None:
    if DATA.exists():
        shutil.rmtree(DATA)
    DATA.mkdir()
    bulk_flows()
    specialty_flows()
    story_prs()
    odd_records()
    fix_stories()
    number_everything()
    import hg_sheets      # noqa: PLC0415  (the hand-built sheets, the trackers, the index and the inbox read the records built above)

    write_ref_files()
    write_sap()
    write_drift_fixture()
    hg_sheets.write_all(sys.modules[__name__])
    print(hg_sheets.summary(sys.modules[__name__]))


if __name__ == "__main__":
    main()
