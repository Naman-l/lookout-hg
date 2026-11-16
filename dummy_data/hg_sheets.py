"""The hand-built sheets, the trackers, the vendor ledger, the commodity index and the summary, written from the records `generate_hg` built.

Each sheet copies the layout SCM really keeps (the review repo's CSV exports): multi-row headers, quantity / rate / amount triplets, amounts in
₹ Cr, subtotal columns, a weekly split, plain-text payment terms. The defects the recipe handles are planted here, each where it naturally occurs.
"""
from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, timedelta

from hg_cast import FUNCTIONS, INTERNAL_DOMAIN, PAYMENT_TERMS, RAILWAY_EXTRA_ROWS, RAILWAY_ORDER, RAILWAY_SHEET, RAILWAY_UNITS, ROADS_EXTRA_ROWS, ROADS_SHEET, ROADS_UNITS, SHEET_MATERIALS, TEAM

rng = random.Random(7_20261020)
M = ["Oct", "Nov", "Dec"]


def cr(x: float) -> float:
    return x / 1e7


def fmt_cr(x: float | None) -> str:
    return "" if x is None else f"{x:.2f}"


# ================================================================================================================== the requirement sheets
ROADS_NEW = ["tumkur", "jh10", "jh13", "jec", "tirupati", "ayodhya", "narol"]
ROADS_NEAR = [("KD-01", ""), ("KD-02", ""), ("KD-01 & KD-02", "1131-1132"), ("AP-01", "1133"), ("GEW-05", "1145"), ("Karnal", "1141")]


def write_roads(g) -> int:
    name = {p: g.PROJ[p]["name"] for p in ROADS_NEW}
    width = 3 + len(ROADS_NEAR) + 1 + len(ROADS_NEW) * 3 + 3 + 2
    head1 = ["Material", "Particulars", "Unit", "Nearly Completion Projects"] + [""] * len(ROADS_NEAR) + ["Newly Started Projects"] + [""] * (len(ROADS_NEW) * 3 + 2) \
        + ["Total [C=A+B]", "Weighted Rate of Material"]
    head1 = head1[:width]
    head2 = ["", "", ""] + [n for n, _ in ROADS_NEAR] + ["Total\n[A]"]
    for p in ROADS_NEW:
        head2 += [name[p], "", ""]
    head2 += ["Total", "", "", "", ""]
    head3 = ["", "", ""] + [c for _, c in ROADS_NEAR] + [""] + ["Oct'26", "Nov'26", "Dec'26"] * (len(ROADS_NEW) + 1) + ["", ""]
    rows = [[""] * width, ["Road Projects - Major Material Requirement (Oct'26 -  Dec'26)"] + [""] * (width - 1), head1, head2, head3]
    order = list(ROADS_SHEET) + ROADS_EXTRA_ROWS
    total_amt = [0.0] * (len(ROADS_NEW) * 3)
    for row in order:
        cols = ROADS_SHEET.get(row, {})
        unit = ROADS_UNITS.get(row, "")
        q, r, a = [row, "Qty.", unit], ["", "Rate", ""], ["", "Amount", "Cr."]
        for nm, _ in ROADS_NEAR:      # nearing completion: nothing planned this quarter (the real sheet prints 0 against a few)
            q.append("0" if nm == "KD-01 & KD-02" else "")
            r.append("0" if nm in ("KD-01", "KD-02", "AP-01") else "")
            a.append("0.00" if nm == "KD-01 & KD-02" else "")
        q.append("0"), r.append("0"), a.append("0.00")
        sq = sa = 0.0
        for k, p in enumerate(ROADS_NEW):
            qty3, rate = cols.get(p, ([None, None, None], None))
            for j in range(3):
                qty = qty3[j]
                q.append(g.sheet_num(qty) if qty not in (None, 0) else ("" if qty is None else "  -   "))
                r.append(g.sheet_num(rate) if rate and qty is not None else "")
                amt = cr(qty * rate) if qty and rate else 0.0
                a.append(f"  {amt:.2f} " if amt else "  -   ")
                sq += qty or 0
                sa += amt
                total_amt[k * 3 + j] += amt
        wr = sa * 1e7 / sq if sq else None
        q += [g.sheet_num(sq) if sq else "  -   ", "", g.sheet_num(sq) if sq else "  -   ", ""]
        r += [g.sheet_num(round(wr)) if wr else "  -   ", "", str(round(wr)) if wr else "0", ""]
        a += [f"  {sa:.2f} ", "", f"  {sa:.2f} ", g.sheet_num(round(wr)) if wr else "#DIV/0!"]
        rows += [q[:width], r[:width], a[:width]]
    tot = ["Total", "Amount", "Cr."] + ["0.00"] * (len(ROADS_NEAR) + 1) + [f"  {x:.2f} " for x in total_amt]
    rows.append(tot + [""] * (width - len(tot)))
    rows.append([""] * 7 + ["#REF!", "", "", "#REF!"] + [""] * (width - 11))
    name_ = "sheets/Roads Major Material Requirement Oct-Dec 26 (14.10.26).csv"
    g.write_csv(name_, None, rows)
    return len(rows)


def write_railway(g) -> int:
    projs = RAILWAY_ORDER
    names = [g.PROJ[p]["name"] for p in projs]
    plants = [g.PROJ[p]["plants"][0] for p in projs]
    width = 3 + (len(projs) + 1) * 3 + 2
    head1 = ["Material", "Particulars", "Unit"]
    head2, head3 = ["", "", ""], ["", "", ""]
    for mo in M:
        head1 += [f"{mo}''26"] + [""] * len(projs)
        head2 += names + ["Total"]
        head3 += plants + [""]
    head1 += ["Total Q3", "Weighted Rate of Material"]
    head2 += ["", ""]
    head3 += ["", ""]
    rows = [[""] * width, ["Railway Projects - Major Material Quantity Summary Q-3"] + [""] * (width - 1), head1, head2, head3]
    for row in list(RAILWAY_SHEET) + RAILWAY_EXTRA_ROWS:
        cols = RAILWAY_SHEET.get(row, {})
        q, r, a = [row, "Qty.", RAILWAY_UNITS.get(row, "")], ["", "Rate", ""], ["", "Amount", "Cr."]
        tq = ta = 0.0
        for j in range(3):
            sq = sa = 0.0
            for p in projs:
                qty3, rate = cols.get(p, (None, None))
                qty = qty3[j] if qty3 else None
                q.append(str(qty) if qty is not None else "")
                r.append(str(rate) if rate is not None and qty is not None else "")
                amt = cr(qty * rate) if qty and rate else 0.0
                a.append(f"{amt:.2f}" if qty3 else "0")
                sq += qty or 0
                sa += amt
            q.append(str(round(sq)))
            r.append(str(round(sa * 1e7 / sq)) if sq else "0")
            a.append(f"{sa:.2f}")
            tq += sq
            ta += sa
        q += [f"{tq:,.0f}" if tq else "-", ""]
        r += [f"{ta * 1e7 / tq:,.0f}" if tq else "0", ""]
        a += [f"{ta:.2f}" if tq else "-", f"{ta * 1e7 / tq:,.0f}" if tq else ""]
        rows += [q[:width], r[:width], a[:width]]
    g.write_csv("sheets/Railway Material Quantity Summary Q3 (15.10.26).csv", None, rows)
    return len(rows)


# ================================================================================================================== the fund requirement sheets
FUND_COLS = [  # (column as printed, project ids it stands for, band)
    ("JEC", ["jec"], "new"), ("JH-13", ["jh13"], "new"), ("JH-10", ["jh10"], "new"), ("Ahmedabad", ["narol"], "new"), ("Tumkur", ["tumkur"], "new"),
    ("Tirupati", ["tirupati"], "new"), ("NDRS", ["ndls"], "new"), ("DLF", ["dlf"], "new"), ("Ayodhya", ["ayodhya"], "new"), ("Pune-Shirur", ["pune_shirur"], "new"),
    ("OD CRR", [], "new"), ("DV-10", [], "new"), ("Sub Total for New Projects", None, "new"),
    ("Karnal", ["karnal"], "near"), ("Ganga", ["gew05"], "near"), ("DMRC-DC-01A", [], "near"), ("KD-1&2", ["kd01", "kd02"], "near"), ("Prakasha", [], "near"),
    ("OD-05, 06", [], "near"), ("AP-01", ["ap01"], "near"), ("Sub Total for Nearing Completion Projects", None, "near"),
    ("RVNL", ["rvnl"], "railway"), ("Kanpur", ["kanpur"], "railway"), ("Gaya", ["gaya"], "railway"), ("Arurangabad", ["aurangabad"], "railway"),
    ("Dhule", ["dhule"], "railway"), ("Thane Metro", ["thane"], "railway"), ("Mirzapur", [], "railway"), ("Anuppur", ["anuppur"], "railway"),
    ("Sub Total for Railway Projects", None, "railway"),
    ("Banaskatha & Dholera", ["banaskantha", "dholera"], "ne"), ("Chouraniya", ["chorniya"], "ne"), ("Solar", ["bikaner", "jodhpur"], "ne"),
    ("T&D", ["angul", "upptcl", "jamshedpur"], "ne"), ("Sub Total for BESS+Solar+T&D", None, "ne"), ("Sub Total in Cr.", None, "all"),
]
FUND_HEADS = {  # head -> requirement sheet rows it pays for (None: no counterpart on the requirement sheets)
    "Aggregate, Sand, Blast, GSB": ["Aggregate", "Dust", "WMM (Air Cooled Slag)", "GSB", "Sand (Wash, Coarse, River, Msand)", "Aggregate- 10MM", "Aggregate- 20 MM",
                                    "GSB/Boulder", "Ballast", "Blanketing Material"],
    "Cement": ["Cement"], "GGBS": ["GGBS"], "Petroleum Products": ["Bitumen-VG-40", "Bitumen-CRMB", "Emulsion-SS1", "Emulsion-RS1", "HSD", "LSHS/LDO"],
    "TMT_Primary": ["Steel (HYSD)"], "TMT_Traders": None, "TMT_Advance": None, "HT Strands": ["HT Strand"], "RMC": None,
    "Plates & Structural Steel": ["Steel Girder"], "Shuttering Due Payment": None, "Shuttering Advance Payment": None,
    "Structural Bearing, Expansion Joint & Prestressing": ["Elastomeric Bearing", "POT-PTFE Bearing", "Strip Seal Expansion Joint (With Stud & Modular)"],
    "MBCB": ["W Beam Crash Barrier"], "Gantry Crane/ Launching Girder": None, "Railway Material for S&T ,OHE,PWAY": None, "Tower Testing, Form Box": None,
    "Solar Module,Solar MMS and Misc.(MCCB,ACB & O&M items)": None,
    "Other Misc. (RCC Hume Pipe, Geocell, Geotextile, Deck Sheet etc.)": ["Hume Pipe 600", "Geogrid", "Deck Sheet", "Drainage Spout"],
    "General Consumable_Due": None, "Mechanical_Due": None, "Mechanical_Advance": None, "TMT Transportation": None, "Transportation": None,
    "Supply Electricals": None,
}
# planted disagreements between the fund sheet and the requirement sheet: (month index, column, head) -> factor on the requirement amount
MISMATCH = {(1, "Gaya", "Aggregate, Sand, Blast, GSB"): 1.35, (1, "Arurangabad", "Aggregate, Sand, Blast, GSB"): 0.77, (1, "Ahmedabad", "Cement"): 1.30,
            (1, "JH-13", "Petroleum Products"): 1.45, (0, "Tirupati", "Aggregate, Sand, Blast, GSB"): 1.28, (0, "Thane Metro", "Cement"): 1.6}
# amounts typed in other units, as text, in a sheet that is in Cr: Excel's SUM leaves text out, so the sheet's own totals do not include them
TEXT_CELLS = {(1, "Mechanical_Due", "Karnal"): "45 L", (1, "Transportation", "Ganga"): "23,50,000", (0, "General Consumable_Due", "Dhule"): "1.5 L"}
FUND_ONLY = {(1, "Pune-Shirur", "Aggregate, Sand, Blast, GSB"): 4.48, (0, "Pune-Shirur", "Aggregate, Sand, Blast, GSB"): 3.10, (2, "Pune-Shirur", "Aggregate, Sand, Blast, GSB"): 4.20}


def _req_amount(g, pids: list[str], rows: list[str], j: int) -> float:
    total = 0.0
    for sheet in (ROADS_SHEET, RAILWAY_SHEET):
        for row in rows:
            for p in pids:
                if p in sheet.get(row, {}):
                    q3, rate = sheet[row][p]
                    total += q3[j] * rate
    return cr(total)


def write_funds(g) -> dict[str, int]:
    out = {}
    for j, (mo, long_, built) in enumerate((("Oct", "October", "18.09.26"), ("Nov", "November", "16.10.26"), ("Dec", "December", "16.10.26"))):
        header = ["Description"] + [c for c, _, _ in FUND_COLS]
        rows = [[f"Fund Requirement for the Month of {long_}-26"] + [""] * len(FUND_COLS), header]
        col_tot = defaultdict(float)
        for head, req_rows in FUND_HEADS.items():
            vals, band_tot, all_tot = [], defaultdict(float), 0.0
            for col, pids, band in FUND_COLS:
                if pids is None:
                    v = all_tot if band == "all" else band_tot[band]
                    vals.append(fmt_cr(v) if v else "")
                    continue
                v = 0.0
                if req_rows and pids:
                    v = _req_amount(g, pids, req_rows, j) * rng.uniform(0.98, 1.02)
                    v *= MISMATCH.get((j, col, head), 1.0)
                    if head == "TMT_Primary":      # the steel need is paid partly to primary producers, partly to traders, partly as advances
                        v *= 0.55
                elif head in ("TMT_Traders", "TMT_Advance") and pids:
                    v = _req_amount(g, pids, ["Steel (HYSD)"], j) * (0.35 if head == "TMT_Traders" else 0.10) * rng.uniform(0.98, 1.02)
                elif not req_rows and pids and rng.random() < 0.35:
                    v = rng.uniform(0.02, 0.6)
                elif not pids and rng.random() < 0.5:      # a column the requirement sheets do not carry
                    v = rng.uniform(0.05, 2.5) if head.startswith(("Aggregate", "Cement", "Petroleum", "TMT")) else rng.uniform(0.02, 0.4)
                v = FUND_ONLY.get((j, col, head), v)
                if pids and band == "near" and (req_rows or head.startswith("TMT")):      # nearly complete: only dues and retention, below the fund check's threshold
                    v = rng.uniform(0.02, 0.18) if rng.random() < 0.4 and not head.startswith("TMT") else 0.0
                v = round(v, 2)
                if (j, head, col) in TEXT_CELLS:
                    vals.append(TEXT_CELLS[(j, head, col)])
                    continue
                band_tot[band] += v
                all_tot += v
                col_tot[col] += v
                vals.append(fmt_cr(v) if v else "")
            rows.append([head] + vals)
        rows.append(["Total Cost in Cr."] + [fmt_cr(col_tot[c]) if pids is not None else "" for c, pids, _ in FUND_COLS])
        if j == 0:      # the October sheet carries the weekly split, as the real one does
            rows.append([""] * (len(FUND_COLS) + 1))
            for wk in ("1st Week", "2nd Week", "3rd week", "4th week", "5th week"):
                rows.append([wk] + [fmt_cr(col_tot[c] * w) if pids is not None and col_tot[c] else "" for (c, pids, _), w in
                                    zip(FUND_COLS, [rng.uniform(0.1, 0.3) for _ in FUND_COLS])])
        name = f"sheets/SCM Fund Requirement {long_}-26 ({built}).csv"
        out[name] = g.write_csv(name, None, rows)
    return out


# ================================================================================================================== payment projection, look-ahead
def write_projection(g) -> int:
    rows, n = [], 0
    pre = ["Payment Projection - Till 30/10/2026 (BESS + RAILWAY + SOLAR + T&D),,,,,,", ",,,,,,"]
    short = lambda v: v.name.split()[0] if rng.random() < 0.6 else v.name  # noqa: E731  the sheet often writes the party's first word
    for po in sorted(g.PO_DOCS, key=lambda p: p.number):
        if g.PROJ.get(po.project or "", {}).get("vertical") not in ("bess", "solar", "td", "railway") or po.vendor.terms not in ("ZADV", "ZLC", "ZRTG") and po.tag not in ("mfc", "pvclaim"):
            continue
        it = po.items[0]
        value = it.qty * it.price / it.price_unit
        if value < 5e5:
            continue
        pname = {"banaskantha": "Banaskantha", "dholera": "Dholera", "chorniya": "Chouraniya", "angul": "Angul Odisha"}.get(po.project, g.PROJ[po.project]["name"])
        terms, rtgs, lc = "", "", ""
        if po.tag == "containers":
            lc, terms = f"{value:,.0f}", " LC to be opened by 30/10/2026 "
        elif po.tag == "ida":
            rtgs, terms = "2.64 Cr", " 10% Advance against ABG. Balance before dispatch "
        elif po.tag == "pvclaim":
            rtgs, terms = f"{value * 0.04:,.2f}", " PV Payment "
        elif po.vendor.terms == "ZLC":
            lc, terms = f"{value:,.0f}", " LC Payment "
        elif po.vendor.terms == "ZADV":
            rtgs, terms = f"{value * 0.1:,.2f}", " 10% Advance against ABG. "
        else:
            rtgs, terms = f"{value:,.2f}", " Before Dispatch. "
        n += 1
        rows.append([str(n), pname, short(po.vendor), it.short_text, rtgs, lc, terms])
        if n >= 46:
            break
    rows.append([str(n + 1), "Dholera", "Misc. site services", "Design consultancy fees", "45 L", "", " Before Dispatch "])
    return g.write_csv("sheets/Payment Projection Oct-26 (14.10.26).csv", ["Sr. No.", "Project Name", "Party Name", "Item Name", "RTGS", "LC", "Payment Terms"], rows, pre)


LOOKAHEAD = [  # the review repo's 20 long-lead items (project as printed, item, unit, qty, rate, basis, lead) + need-by, status
    ("immediate", "BESS Chorniya", "180 MVA PTR", "No.", 2, 120000000, "PV", "10-12 Months", "2027-09", "RFQ stage: budgetary quotes"),
    ("immediate", "BESS Chorniya", "220 KV GIS", "Lot", 2, 100000000, "PV", "12 Months", "2027-10", "RFQ stage: 2 quotes, CS pending"),
    ("immediate", "UPPTCL - Mizapur/ Chunar - SS", "160 MVA Auto TFR", "No.", 4, 125000000, "PV", "10-12 Months", "2027-10", "Awaiting management approval for advance funding"),
    ("immediate", "UPPTCL - Mizapur/ Chunar - SS", "40 MVA PTR", "No.", 4, 45000000, "PV", "7-8 Months", "2027-05", "Awaiting management approval for advance funding"),
    ("immediate", "UPPTCL - Mizapur/ Chunar - SS", "220 KV & 145 KV Circuit Breakers", "Lot", 1, 60000000, "Firm", "15 Months", "2027-12", "Technical spec under approval"),
    ("immediate", "UPPTCL - Mizapur/ Chunar - SS", "220 KV & 145 KV CT & CVT", "Lot", 1, 55000000, "Firm", "12 Months", "2027-10", "Technical spec under approval"),
    ("immediate", "UPPTCL - Mizapur/ Chunar - SS", "BPI", "Lot", 1, 42500000, "Firm", "12 Months", "2027-10", "Technical spec under approval"),
    ("immediate", "UPPTCL - Mizapur/ Chunar - TL", "Towers", "MT", 1800, 92000, "PV", "6-9 Months", "2027-06", "Awaiting management approval for advance funding"),
    ("immediate", "UPPTCL - Mizapur/ Chunar - TL", "Conductor - ACSR Zebra", "Km", 440, 525030, "PV", "6-9 Months", "2027-06", "Awaiting management approval for advance funding"),
    ("immediate", "UPPTCL - Mizapur/ Chunar - TL", "Insulators", "Lot", 1, 17000000, "Firm", "12 Months", "2027-09", "Technical spec under approval"),
    ("immediate", "765 KV Angul Odisha - TL", "Towers", "MT", 6500, 92000, "PV", "6-9 Months", "2027-08", "Section A ordered Jan 2026; balance awaiting design approval"),
    ("immediate", "765 KV Angul Odisha - TL", "Conductor - ACSR Zebra", "Km", 1400, 500000, "PV", "6-9 Months", "2027-08", "Section A ordered Feb 2026; balance awaiting design approval"),
    ("immediate", "765 KV Angul Odisha - TL", "Insulators", "Lot", 1, 62500000, "Firm", "12 Months", "2027-10", "Section A ordered Mar 2026; balance with design"),
    ("immediate", "400 KV Jamshedpur - SS", "Extension Bay Work", "Lot", 1, 330000000, "Firm", "12 Months", "2027-11", "Client approval of bay layout awaited"),
    ("q4", "400 KV Jamshedpur - SS", "400 KV CB", "Lot", 1, 30000000, "Firm", "12 Months", "2028-01", "To be started from Q4"),
    ("q4", "400 KV Jamshedpur - SS", "80 MVA Reactor", "No.", 2, 110000000, "PV", "12 Months", "2028-01", "To be started from Q4"),
    ("q4", "400 KV Jamshedpur - SS", "400 KV CT CVT", "Lot", 1, 20000000, "Firm", "9 Months", "2027-11", "To be started from Q4"),
    ("q4", "400 KV Jamshedpur - TL", "Towers", "MT", 11595, 92000, "PV", "6-9 Months", "2027-12", "To be started from Q4"),
    ("q4", "400 KV Jamshedpur - TL", "Conductor - AL59 - Moose Quad", "Km", 4236, 662609, "PV", "6-9 Months", "2027-12", "To be started from Q4"),
    ("q4", "400 KV Jamshedpur - TL", "Insulators", "Lot", 1, 72500000, "Firm", "12 Months", "2028-01", "To be started from Q4"),
]


def write_lookahead(g) -> int:
    rows = []
    for n, (block, proj, item, uom, qty, rate, basis, lead, need, status) in enumerate(LOOKAHEAD, 1):
        sr = n if block == "immediate" else n - 14
        rows.append([str(sr), "Need Immediate Attention" if block == "immediate" else "To be started from Q4", proj, item, uom, str(qty), f"{rate:,}", f"{qty * rate:,}",
                     basis, lead, need.replace("-", "/")[5:] + "/" + need[:4], status])
    pre = ["3-Month Procurement Look-Ahead (Long Lead Items) | Rev. 15.10.2026"]
    return g.write_csv("sheets/Look Ahead Long Lead Items (15.10.26).csv",
                       ["Sr. No.", "Block", "Project", "Item", "UOM", "Qty", "Tentative Rate (INR)", "Amount (INR)", "Price Basis", "Lead Time", "Need By (MM/YYYY)", "Status"], rows, pre)


# ================================================================================================================== the vendor library
_LIB_A = ["Adarsh", "Bharati", "Chandra", "Dhruv", "Ekta", "Gayatri", "Hari", "Indu", "Kiran", "Laxmi", "Mahavir", "Navkar", "Omkar", "Parth", "Riddhi", "Siddhi",
          "Tirth", "Uday", "Vijay", "Yash", "Anmol", "Bhavya", "Devika", "Girnar", "Harsh", "Ishaan", "Jagrati", "Kalash", "Lakshya", "Manthan", "Nirmal", "Ojas"]
_LIB_B = {"P-Way": ["Rail Products", "Track Fittings", "Rail Udyog", "Track Components"], "S&T": ["Signal Works", "Signalling Systems", "Telecom Products", "Relay Industries"],
          "OHE": ["OHE Fittings", "Electro Structures", "Traction Products", "Overhead Equipment"], "Solar": ["Solar Energy", "Solar Structures", "Green Power", "Photovoltaics"],
          "BESS": ["Power Systems", "Energy Storage", "Electricals", "Switchgear"], "Transmission Line": ["Towers", "Conductors", "Line Hardware", "Power Infra"]}
_LIB_C = ["Pvt Ltd", "LLP", "Industries", "Engineering Works", "and Company", "Enterprises"]
LIB_COUNTS = {("Railway", "P-Way"): 32, ("Railway", "S&T"): 45, ("Railway", "OHE"): 43, ("Solar", "Solar"): 163, ("BESS", "BESS"): 50, ("Transmission Line", "Transmission Line"): 18}
LIB_SAP = {  # SAP vendors the library lists, under (vertical, sub-vertical); the renamed vendor under its old name only
    ("Railway", "P-Way"): ["100601", "100231", "100603", "100604"], ("Railway", "S&T"): ["100621", "100622", "100624"],
    ("Railway", "OHE"): ["100611", "100612", "100613", "100614", "100701"], ("Solar", "Solar"): ["100733", "100734", "100723", "100722"],
    ("BESS", "BESS"): ["100731", "100732", "100702", "100703", "100705", "100706", "100721", "100742"],
    ("Transmission Line", "Transmission Line"): ["100711", "100712", "100713", "100714", "100704"],
}


def _approved(d: int, m: int, y: int) -> str:
    """An approval date no later than the day the library was last saved (3 Oct 2026): a later one moves back a year."""
    from datetime import date  # noqa: PLC0415

    return f"{d:02d}.{m:02d}.{y if date(y, m, d) <= date(2026, 10, 3) else y - 1}"


def write_library(g) -> int:
    rows, n, used = [], 0, set()
    for (vert, sub), count in LIB_COUNTS.items():
        sap = LIB_SAP.get((vert, sub), [])
        for k in range(count):
            n += 1
            status = "In Process" if vert == "Transmission Line" else "Approved"
            if k < len(sap):
                v = g.VEND[sap[k]]
                code = v.code if rng.random() < 0.7 else ""      # the library often has no SAP code against a vendor
                rows.append([str(n), vert, sub, v.name, v.category, v.city, v.state or "China", v.gstin, v.contact, v.phone,
                             _approved(rng.randint(1, 28), rng.randint(1, 12), rng.randint(2019, 2026)), status, code, ""])
                continue
            while True:
                nm = f"{rng.choice(_LIB_A)} {rng.choice(_LIB_B[sub])} {rng.choice(_LIB_C)}"
                if nm not in used:
                    used.add(nm)
                    break
            state = rng.choice(["Maharashtra", "Gujarat", "Uttar Pradesh", "Rajasthan", "Delhi", "West Bengal", "Haryana", "Madhya Pradesh", "Odisha", "Telangana"])
            pan = g.make_pan(nm, rng.choice("CFP"))
            rows.append([str(n), vert, sub, nm, sub.lower(), "", state, g.make_gstin(state, pan) if rng.random() < 0.8 else "", "", "",
                         _approved(rng.randint(1, 28), rng.randint(1, 12), rng.randint(2017, 2026)), status, "", "Pending vendor registration" if status != "Approved" else ""])
    return g.write_csv("sheets/Vendor Library (03.10.26).csv", ["Sr. No.", "Vertical", "Sub Vertical", "Vendor Name", "Category", "City", "State", "GSTIN",
                                                               "Contact Person", "Mobile", "Approved On", "Status", "SAP Vendor Code", "Remarks"], rows)


# ================================================================================================================== budget rates, DoA
def write_budget(g) -> int:
    rows, seen = [], set()
    missing = set()
    pairs = []
    for sheet in (ROADS_SHEET, RAILWAY_SHEET):
        for row, cols in sheet.items():
            for p, (_q, rate) in cols.items():
                for code in SHEET_MATERIALS[row][:1] if row != "Steel (HYSD)" else SHEET_MATERIALS[row][:3]:
                    pairs.append((p, code, rate, row))
    for p, code, rate, row in rng.sample(pairs, 12):
        if not (p == "tumkur" and code.startswith("1100")):
            missing.add((p, code))
    for p, code, rate, row in pairs:
        if (p, code) in seen or (p, code) in missing:
            continue
        seen.add((p, code))
        b = 690 if (p == "tumkur" and code.startswith("1100002")) else round(rate * rng.uniform(0.95, 1.07), 2 if rate < 10 else 0)
        rows.append([g.PROJ[p]["name"], g.PROJ[p]["plants"][0], code, g.MAT[code]["desc"], g.MAT[code]["uom"], f"{b:g}" if b < 10 else f"{b:.0f}",
                     "Tender BOQ" if g.PROJ[p]["stage"] == "new" else "Revised estimate"])
    for p in ("tumkur",):      # the story's aggregate: budget for each size the site buys
        for code in ("11000010", "11000040"):
            if (p, code) not in seen:
                rows.append(["Tumkur", g.PROJ[p]["plants"][0], code, g.MAT[code]["desc"], "MT", "690", "Tender BOQ"])
    g.MISSING_BUDGET = sorted(missing)
    return g.write_csv("sheets/budget_rates.csv", ["Project", "Plant", "Material", "Material Description", "Unit", "Budget Rate (INR)", "Basis"], rows)


def write_doa(g) -> int:
    rows = [["PO / WO / Commitment letter", "0", "1,00,00,000", "Buyer (owner of the purchasing group)", ""],
            ["PO / WO / Commitment letter", "1,00,00,000", "5,00,00,000", "Vertical lead or GM SCM", ""],
            ["PO / WO / Commitment letter", "5,00,00,000", "", "Owner", "Head SCM"],
            ["MFC (manufacturing clearance)", "0", "5,00,00,000", "Vertical lead", ""],
            ["MFC (manufacturing clearance)", "5,00,00,000", "", "Vertical lead", "Head SCM"],
            ["CS approval", "0", "1,00,00,000", "Vertical lead", ""],
            ["CS approval", "1,00,00,000", "5,00,00,000", "GM SCM", ""],
            ["CS approval", "5,00,00,000", "", "GM SCM", "Head SCM"],
            ["Request or query letter (no commitment)", "0", "", "Owner", ""]]
    return g.write_csv("sheets/doa.csv", ["Document", "From (INR)", "To (INR)", "Approver", "Countersign"], rows)


# ================================================================================================================== trackers
def write_cs(g) -> int:
    rows = []
    for q in sorted(g.QUOTES, key=lambda q: (q.cs, q.vendor_name)):
        last = None
        if q.pr is not None and q.project:
            last = g.rate_of(q.project, q.material, "2026-09") if g.MAT[q.material]["group"] in ("AGGREGATE", "CEMENT", "TMT") else None
        budget = None
        rows.append([q.cs, g.PROJ[q.project]["name"] if q.project else "", q.pr.doc.number if q.pr else "", str(q.pr.item_no) if q.pr else "", q.material,
                     g.MAT[q.material]["desc"], q.vendor.code if q.vendor else "", q.vendor_name, g.dmy(q.rfq_sent), g.dmy(q.quote_date), f"{q.qty:g}" if q.qty else "",
                     q.uom, f"{q.rate:.2f}" if q.rate is not None else "", g.dmy(q.validity), q.basis, "Y" if q.l1 and q.rate is not None else "",
                     f"{last:.2f}" if last else "", f"{budget:.2f}" if budget else "", q.status, q.approved_by, g.dmy(q.approved_on), q.buyer, q.remarks])
    return g.write_csv("sheets/RFQ CS Tracker (19.10.26).csv",
                       ["CS No.", "Project", "PR No.", "PR Item", "Material", "Material Description", "Vendor Code", "Vendor Name", "RFQ Sent", "Quote Date", "Qty",
                        "Unit", "Quoted Rate (INR)", "Valid Till", "Price Basis", "L1", "Last PO Rate", "Budget Rate", "CS Status", "Approved By", "Approved On",
                        "Buyer", "Remarks"], rows)


EXPEDITED = ("ELE-TFR", "ELE-SWG", "TL-TOWER", "TL-COND", "TL-INSUL", "BESS", "SOLAR", "DG", "RLY-OHEMAST")


def write_expediting(g) -> int:
    d = date
    rows = []
    for po in sorted(g.PO_DOCS, key=lambda p: p.number):
        for it in po.items:
            grp = g.MAT[it.material]["group"]
            if grp not in EXPEDITED or (grp == "SOLAR" and it.material != "31000710") or (grp == "RLY-OHEMAST" and po.tag != "masts"):
                continue
            needs_mfc = grp in ("ELE-TFR", "ELE-SWG", "TL-TOWER", "TL-COND", "BESS")
            first = min((r.posting for r in it.receipts), default=None)
            mfc_req = po.doc_date + timedelta(days=rng.randint(20, 60)) if needs_mfc else None
            mfc_iss = mfc_req + timedelta(days=rng.randint(3, 15)) if mfc_req and mfc_req <= g.AS_OF else None
            mfc_iss = mfc_iss if mfc_iss and mfc_iss <= g.AS_OF else None
            mfg = 120 if grp in ("ELE-TFR", "ELE-SWG") else 90 if grp in ("TL-TOWER", "TL-COND", "BESS") else ""
            insp_plan = (first - timedelta(days=rng.randint(10, 20))) if first and grp in ("ELE-TFR", "ELE-SWG", "BESS", "TL-COND", "DG") else None
            insp_call = insp_plan - timedelta(days=rng.randint(7, 14)) if insp_plan else None
            insp_done = insp_plan + timedelta(days=rng.randint(0, 2)) if insp_plan else None
            disp = first - timedelta(days=rng.randint(3, 8)) if first else None
            site_ready = None
            commissioned = first + timedelta(days=rng.randint(20, 75)) if first and grp in ("ELE-TFR", "ELE-SWG", "DG", "BESS", "SOLAR") and first + timedelta(days=75) <= g.AS_OF else None
            warranty = "18" if grp in ("ELE-TFR", "ELE-SWG", "DG", "BESS", "SOLAR") else ""
            basis = "Supply" if warranty else ""
            remark = ""
            if po.tag == "mfc":
                mfc_req, mfc_iss, insp_call, insp_plan, insp_done, disp, commissioned = d(2026, 8, 20), None, None, None, None, None, None
                remark = "MFC on hold: TSS plinth readiness (Projects)"
            elif po.tag == "inspection":
                mfc_req, mfc_iss, insp_call, insp_plan, insp_done, disp, commissioned = d(2026, 6, 2), d(2026, 6, 10), d(2026, 10, 16), d(2026, 10, 28), None, None, None
                site_ready = d(2026, 12, 15)
                remark = "Final inspection called 28.10.2026; TSS plinth expected 15.12.2026"
            elif po.tag == "ida":
                mfc_req, mfc_iss, insp_call, insp_plan, insp_done, disp, commissioned = d(2026, 1, 30), d(2026, 2, 15), None, None, None, None, None
                remark = "Delivery delayed by vendor: revised to Dec 2026"
            elif po.tag == "containers":
                mfc_req, mfc_iss, insp_call, insp_plan, insp_done, disp, commissioned = None, None, None, None, None, None, None
                remark = "Production slot Nov 2026 subject to LC"
            elif po.tag == "masts":
                remark = "Dispatch 06.11.2026 (galvanizing)"
            elif po.tag == "pvclaim":
                remark = "Section A: 240 km received; PV claim on September lots under review"
            rows.append([po.number, str(it.item_no), g.PROJ[po.project]["name"] if po.project else "", it.short_text, po.vendor.name, g.dmy(mfc_req), g.dmy(mfc_iss),
                         str(mfg), g.dmy(insp_call), g.dmy(insp_plan), g.dmy(insp_done), g.dmy(disp), g.dmy(first), g.dmy(site_ready), g.dmy(commissioned), warranty, basis, remark])
    # the Kanpur DG: ordered in 2025, supplied 12 May 2025, never commissioned (its order is older than the ME2N export)
    rows.append(["4500087611", "10", "Kanpur", "DG set 500 kVA", "Pavan Gensets Pvt Ltd", "", "", "", "21.04.2025", "28.04.2025", "29.04.2025", "05.05.2025", "12.05.2025", "", "",
                 "18", "Supply", "Commissioning not planned yet (site): warranty runs from supply"])
    return g.write_csv("sheets/Expediting Tracker (17.10.26).csv",
                       ["PO No.", "PO Item", "Project", "Item", "Vendor", "MFC Requested", "MFC Issued", "Mfg Period (days)", "Inspection Call", "Inspection Planned", "Inspection Done",
                        "Dispatch Clearance", "Delivered", "Site Ready (Planned)", "Commissioned", "Warranty (months)", "Warranty From", "Remarks"], rows)


def write_lc_bg(g) -> int:
    d = date
    rows = []
    s = g.STORY
    cont = s["containers_pr"].items[0].po
    rows.append(["LC", "", cont.doc.number, cont.doc.vendor.code, cont.doc.vendor.name, f"{cont.qty * cont.price:,.0f}", "30.10.2026", "", "", "", "Pending",
                 "Bank limit enhancement with Finance; draft LC with the bank"])
    idt = s["idt_pr"].items[0].po
    rows.append(["ABG", "ABG/UTPL/2025/118", idt.doc.number, idt.doc.vendor.code, idt.doc.vendor.name, f"{idt.qty * idt.price * 0.1:,.0f}", "", "02.01.2026",
                 "31.10.2026", "Canara Bank (vendor's banker)", "Live", "Against 10% advance; IDT not yet delivered"])
    mfc = s["mfc_pr"].items[0].po
    rows.append(["ABG", "ABG/KPT/2026/031", mfc.doc.number, mfc.doc.vendor.code, mfc.doc.vendor.name, f"{mfc.qty * mfc.price * 0.1:,.0f}", "", "05.02.2026",
                 "31.03.2027", "Union Bank (vendor's banker)", "Live", "Against 10% advance"])
    ins = s["insp_pr"].items[0].po
    rows.append(["ABG", "ABG/KPT/2026/044", ins.doc.number, ins.doc.vendor.code, ins.doc.vendor.name, f"{ins.qty * ins.price * 0.1:,.0f}", "", "20.03.2026",
                 "30.04.2027", "Union Bank (vendor's banker)", "Live", "Against 10% advance"])
    cond = s["cond_pr"].items[0].po
    rows.append(["ABG", "ABG/UCPL/2026/007", cond.doc.number, cond.doc.vendor.code, cond.doc.vendor.name, f"{cond.qty * cond.price * 0.1:,.0f}", "", "03.03.2026",
                 "28.02.2027", "Indian Bank (vendor's banker)", "Live", "Against 10% advance"])
    for po in sorted(g.PO_DOCS, key=lambda p: p.number):
        if po.vendor.terms == "ZLC" and po.tag != "containers" and po.items[0].qty * po.items[0].price > 5e6:
            v = po.items[0].qty * po.items[0].price / po.items[0].price_unit
            opened = po.doc_date + timedelta(days=rng.randint(7, 25))
            rows.append(["LC", f"LC/HG/{opened.strftime('%y%m')}/{rng.randint(10, 99)}", po.number, po.vendor.code, po.vendor.name, f"{v:,.0f}", g.dmy(opened - timedelta(days=2)),
                         g.dmy(opened), g.dmy(opened + timedelta(days=180)), "State Bank of India", "Opened" if opened <= g.AS_OF else "Pending", ""])
        if po.vendor.terms == "ZADV" and po.tag not in ("ida", "mfc", "inspection", "pvclaim") and po.items[0].qty * po.items[0].price > 2e7:
            v = po.items[0].qty * po.items[0].price / po.items[0].price_unit * 0.1
            issued = po.doc_date + timedelta(days=rng.randint(10, 30))
            live = issued <= g.AS_OF
            rows.append(["ABG", f"ABG/{po.vendor.name[:3].upper()}/{issued.year}/{rng.randint(100, 999)}" if live else "", po.number, po.vendor.code, po.vendor.name, f"{v:,.0f}", "",
                         g.dmy(issued) if live else "", g.dmy(issued + timedelta(days=rng.randint(300, 420))) if live else "", "Vendor's banker", "Live" if live else "Awaited",
                         "Against 10% advance" if live else "Awaited before the advance is released"])
    return g.write_csv("sheets/LC BG Tracker (16.10.26).csv", ["Type", "Number", "PO No.", "Vendor Code", "Vendor", "Amount (INR)", "To Open By", "Issued On",
                                                              "Expiry", "Bank", "Status", "Remarks"], rows)


def write_tat(g) -> int:
    lo, hi = date(2026, 8, 1), date(2026, 9, 30)
    defs = [("a", "Railway", "Aurangabad", "P-Way", "aurangabad", ("RLY-PWAY",)), ("b", "Railway", "Aurangabad", "S&T", "aurangabad", ("RLY-SNT",)),
            ("c", "Railway", "Aurangabad", "OHE", "aurangabad", ("RLY-OHEMAST", "RLY-OHEWIRE", "RLY-INSUL", "ELE-TFR")),
            ("2", "Railway", "", "Dhule - P-Way", "dhule", ("RLY-PWAY",)), ("3", "Railway", "", "Gaya - OHE", "gaya", ("RLY-OHEMAST", "RLY-OHEWIRE", "RLY-INSUL")),
            ("4", "Railway", "", "Kanpur", "kanpur", ("RLY-SNT", "RLY-OHEMAST", "RLY-PWAY", "DG", "SERVICE")),
            ("5", "BESS", "", "Banaskantha", "banaskantha", None), ("6", "BESS", "", "Dholera", "dholera", None),
            ("7", "Solar", "", "Bikaner", "bikaner", ("SOLAR-MAIN",)), ("8", "Solar", "", "Jodhpur", "jodhpur", ("SOLAR-MAIN",)),
            ("9", "Solar", "", "Bikaner O&M", "bikaner", ("SOLAR-OM",)), ("10", "Solar", "", "Jodhpur O&M", "jodhpur", ("SOLAR-OM",)),
            ("11", "TL", "", "TBCB - Angul", "angul", None)]
    rows = []
    for sr, vert, grp, name, pid, groups in defs:
        lines = []
        for doc in g.PR_DOCS:
            if doc.project != pid or not (lo <= doc.created <= hi):
                continue
            for it in doc.items:
                mg = g.MAT[it.material]["group"]
                if groups == ("SOLAR-OM",) and it.material != "31000730":
                    continue
                if groups == ("SOLAR-MAIN",) and (mg != "SOLAR" or it.material == "31000730"):
                    continue
                if groups and groups[0] not in ("SOLAR-OM", "SOLAR-MAIN") and mg not in groups:
                    continue
                lines.append(it)
        closed = [it for it in lines if it.po and it.po.doc.doc_date <= hi]
        tat = sum((it.po.doc.doc_date - it.doc.created).days for it in closed) / len(closed) if closed else 0
        rows.append([sr, vert, grp, name, str(len(lines)), str(len(closed)), f"{tat:.2f}".rstrip("0").rstrip(".") if closed else "0"])
    pre = ["Procurement Turn Around Time (PR to PO) 01/08/2026 ~ 30/09/2026"]
    return g.write_csv("sheets/PR PO TAT Report Aug-Sep 26 (03.10.26).csv", ["Sr. No.", "Vertical", "Group", "Project", "PR Raised", "PR Closed", "Avg TAT (Days)"], rows, pre)


# ================================================================================================================== FBL1N, the commodity index
NET_DAYS = {"Z015": 15, "Z030": 30, "Z045": 45, "ZADV": 30, "ZLC": 0, "ZRTG": 0}


def write_fbl1n(g) -> int:
    rows, inv_n, pay_n, adv_n = [], 5105000000, 1500000000, 1700000000
    open_by_vendor = defaultdict(list)
    for po in sorted(g.PO_DOCS, key=lambda p: p.number):
        v = po.vendor
        abbr = "".join(w[0] for w in v.name.split()[:3]).upper()
        if po.vendor.terms == "ZADV":
            amt = sum(it.qty * it.price / it.price_unit for it in po.items) * 0.1
            when = po.doc_date + timedelta(days=rng.randint(12, 25))
            if when <= g.AS_OF and amt > 0:
                adv_n += rng.randint(1, 9)
                rows.append([v.code, str(adv_n), "KA", f"ADV/{po.number}", po.number, g.dmy(when), g.dmy(when), f"{-amt:.2f}", "", "", "Advance against ABG"])
        for it in po.items:
            by_month = defaultdict(list)
            for r in it.receipts:
                by_month[(r.posting.year, r.posting.month)].append(r)
            for (y, m), recs in sorted(by_month.items()):
                qty = sum(r.qty for r in recs)
                amount = qty * it.price / it.price_unit
                inv_date = max(r.posting for r in recs) + timedelta(days=rng.randint(2, 10))
                if inv_date > g.AS_OF or amount <= 0:
                    continue
                inv_n += rng.randint(1, 9)
                days = NET_DAYS.get(po.terms, 30)
                if v.msme:
                    days = min(days or 45, 45)
                due = inv_date + timedelta(days=days)
                paid = due + timedelta(days=rng.choice([-3, 0, 0, 2, 5, 9, 15])) if po.terms not in ("ZLC", "ZRTG") else inv_date - timedelta(days=rng.randint(1, 5))
                ref = f"INV/{abbr}/{inv_date.year % 100}-{inv_date.year % 100 + 1}/{rng.randint(100, 2999):04d}"
                clear, clear_d = "", ""
                if paid <= g.AS_OF - timedelta(days=1):
                    pay_n += rng.randint(1, 9)
                    clear, clear_d = str(pay_n), g.dmy(paid)
                    rows.append([v.code, str(pay_n), "KZ", ref, po.number, g.dmy(paid), g.dmy(paid), f"{amount:.2f}", str(pay_n), g.dmy(paid), "Payment"])
                else:
                    open_by_vendor[v.code].append((ref, amount, inv_date))
                rows.append([v.code, str(inv_n), "RE", ref, po.number, g.dmy(inv_date), g.dmy(due), f"{-amount:.2f}", clear, clear_d, it.short_text[:40]])
    g.OPEN_INVOICES = open_by_vendor
    pre = ["FBL1N - Vendor Line Item Display | Exported 20.10.2026 08:30:02 | User SSINGH | Open and cleared items"]
    return g.write_csv("sap/FBL1N_vendor_line_items.csv", ["Supplier", "Document Number", "Document Type", "Reference", "Assignment", "Document Date",
                                                           "Net Due Date", "Amount in Local Currency", "Clearing Document", "Clearing Date", "Text"], rows, pre)


def write_index(g) -> int:
    src = {"IEEMA_TFR": "IEEMA PV circular", "IEEMA_SWG": "IEEMA PV circular", "IEEMA_ACSR": "IEEMA PV circular (conductor)", "LME_AL": "LME cash settlement, monthly average",
           "LME_CU": "LME cash settlement, monthly average", "STEEL_TMT": "Steel market bulletin", "STEEL_STRUCT": "Steel market bulletin", "CEMENT_WPI": "Office of the Economic Adviser, WPI",
           "HSD": "Oil marketing company retail price, Delhi"}
    rows = []
    for name, (series, unit, _places) in g.INDEX.items():
        for m in sorted(series):
            rows.append([m, name, f"{series[m]:g}", unit, src[name]])
    pre = ["Commodity indices used for price variation | compiled 15.10.2026"]
    return g.write_csv("external/commodity_index.csv", ["Month", "Index", "Value", "Unit", "Source"], rows, pre)


# ================================================================================================================== everything, and the summary
def write_all(g) -> None:
    import hg_mail      # noqa: PLC0415

    # the Chorniya GIS: a budgetary RFQ with no PR yet; one quote in the tracker, the other only in the mail
    cs = g.cs_number(date(2026, 9, 17))
    g.QUOTES.append(g.Quote(cs, "chorniya", None, "31000110", g.VEND["100704"], g.VEND["100704"].name, date(2026, 9, 17), date(2026, 9, 22), 2, "LOT", 102000000,
                            date(2026, 12, 21), "PV", "Pending", buyer=g.buyer_for("chorniya", "31000110"), remarks="Budgetary RFQ from the look-ahead; PR not raised"))
    g.COUNTS["sheets/Roads Major Material Requirement Oct-Dec 26 (14.10.26).csv"] = write_roads(g)
    g.COUNTS["sheets/Railway Material Quantity Summary Q3 (15.10.26).csv"] = write_railway(g)
    g.COUNTS.update(write_funds(g))
    g.COUNTS["sheets/Payment Projection Oct-26 (14.10.26).csv"] = write_projection(g)
    g.COUNTS["sheets/Look Ahead Long Lead Items (15.10.26).csv"] = write_lookahead(g)
    g.COUNTS["sheets/Vendor Library (03.10.26).csv"] = write_library(g)
    g.COUNTS["sheets/budget_rates.csv"] = write_budget(g)
    g.COUNTS["sheets/doa.csv"] = write_doa(g)
    g.COUNTS["sheets/RFQ CS Tracker (19.10.26).csv"] = write_cs(g)
    g.COUNTS["sheets/Expediting Tracker (17.10.26).csv"] = write_expediting(g)
    g.COUNTS["sheets/LC BG Tracker (16.10.26).csv"] = write_lc_bg(g)
    g.COUNTS["sheets/PR PO TAT Report Aug-Sep 26 (03.10.26).csv"] = write_tat(g)
    g.COUNTS["sap/FBL1N_vendor_line_items.csv"] = write_fbl1n(g)
    g.COUNTS["external/commodity_index.csv"] = write_index(g)
    g.COUNTS["inbox/*.eml"] = hg_mail.write_inbox(g)


def summary(g) -> str:
    pr_lines = sum(len(d.items) for d in g.PR_DOCS)
    po_lines = sum(len(p.items) for p in g.PO_DOCS)
    lines = [f"H.G. Infra dummy dataset, as of {g.AS_OF:%d %b %Y} ({g.START:%b %Y} to {g.AS_OF:%b %Y}; look-ahead to Mar 2027)", "",
             "Files (rows):"]
    lines += [f"  {k:<70} {v:>6,}" for k, v in sorted(g.COUNTS.items())]
    lines += ["", f"Records: {len(g.PR_DOCS):,} PR documents / {pr_lines:,} PR lines; {len(g.PO_DOCS):,} POs / {po_lines:,} PO lines; "
              f"{sum(len(i.receipts) for p in g.PO_DOCS for i in p.items):,} goods receipts before reversals; {len(g.QUOTES):,} quotes in the CS tracker", ""]
    by_v = defaultdict(list)
    for p in g.PROJ.values():
        by_v[p["vertical"]].append(f"{p['name']} ({'/'.join(p['plants']) or 'no SAP plant yet'})")
    lines.append("Projects:")
    for v in ("roads", "railway", "bess", "solar", "td"):
        lines.append(f"  {v:<8} {', '.join(by_v[v])}")
    lines += ["", "The SCM team:"] + [f"  {t[1]:<17} {t[3]} · {', '.join(t[4])}" for t in TEAM]
    lines += ["", "Stories planted:"] + [f"  {s}" for s in g.STORY_NOTES]
    return "\n".join(lines)
