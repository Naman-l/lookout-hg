"""The number oracle: the figures the screens show, recomputed from data/ with pandas alone.

It shares no code with the app (nothing under backend/ is imported) and reads only the raw files plus the recipe's configuration
(answers.yaml: the data date, the head-office plant, the stale limit, the vendor alias a person answered). Each figure is computed the plain
way a person with the files and a spreadsheet would: count the rows, drop the exact repeats, compare two dates. `number_check.py` compares these
with what the API serves. Phase 1 covers the Data page; later phases add Today, the case pages, Records and Insights.
"""

from __future__ import annotations

import csv
import email
import re
from datetime import date, datetime, timedelta  # noqa: F401
from email import policy
from email.utils import parsedate_to_datetime
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RECIPE = ROOT / "recipes" / "hg"
ANSWERS = yaml.safe_load((RECIPE / "answers.yaml").read_text())


def _dmy(s: str) -> date | None:
    s = (s or "").strip()
    return datetime.strptime(s, "%d.%m.%Y").date() if s else None


def _sap(name: str) -> pd.DataFrame:
    """A SAP list export: the first line is its stamp, the second its header."""
    return pd.read_csv(DATA / "sap" / name, skiprows=1, dtype=str, keep_default_na=False)


def _sheet(pattern: str, skip: int = 0) -> pd.DataFrame:
    return pd.read_csv(next((DATA / "sheets").glob(pattern)), skiprows=skip, dtype=str, keep_default_na=False)


def _grid(pattern: str) -> list[list[str]]:
    with next((DATA / "sheets").glob(pattern)).open(newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def figures(as_of: date | None = None) -> dict[str, tuple[float, str]]:
    """{figure id: (value, how it was computed)}."""
    as_of = as_of or date.fromisoformat(ANSWERS["as_of"])
    out: dict[str, tuple[float, str]] = {}
    on = lambda s: _dmy(s) is not None and _dmy(s) <= as_of      # noqa: E731

    pr, po, mb = _sap("ME5A_purchase_requisitions.csv"), _sap("ME2N_purchase_orders.csv"), _sap("MB51_goods_receipts.csv")
    pr, po, mb = pr[pr["Requisition Date"].map(on)], po[po["Document Date"].map(on)], mb[mb["Posting Date"].map(on)]
    out["counts.pr_lines"] = (len(pr), "ME5A rows raised on or before the data date")
    out["counts.po_lines"] = (len(po), "ME2N rows dated on or before the data date")
    out["counts.receipts"] = (len(mb.drop_duplicates()), "MB51 rows on or before the data date, exact repeats removed")
    out["issue.mb51.duplicate_rows"] = (len(mb) - len(mb.drop_duplicates()), "MB51 rows identical in every column to an earlier row")
    out["issue.mb51.reversals"] = (int(mb["Movement Type"].isin(["102", "122"]).sum()), "MB51 rows with movement 102 or 122")
    directory = _sheet("Project Directory.csv")
    out["counts.projects"] = (len(directory), "rows of the project directory")
    out["issue.projects.no_sap_plant"] = (int((directory.Plant.str.strip() == "").sum()), "project directory rows with a blank plant")
    vendors = _sap("vendor_master.csv")
    linked = [a for a in ANSWERS.get("vendor_aliases") or [] if a["record"] in set(vendors.Vendor)]
    out["counts.supplier_identities"] = (len(vendors) - len(linked), "vendor master rows, less the codes a person linked to another company")
    out["issue.vendors.two_codes"] = (len(linked), "vendor codes linked to another company in answers.yaml")
    mails = [parsedate_to_datetime(email.message_from_bytes(p.read_bytes(), policy=policy.default)["date"]).date() for p in (DATA / "inbox").glob("*.eml")]
    out["counts.messages"] = (sum(1 for d in mails if d <= as_of), "mail files dated on or before the data date")
    out["steps"] = (len(list((RECIPE / "steps").glob("[0-9][0-9]_*.py"))), "step files in the recipe")

    out["issue.po.no_pr"] = (int((po["Purchase Requisition"].str.strip() == "").sum()), "ME2N rows with no requisition number")
    out["issue.po.price_per_1000"] = (int((~po["Price Unit"].str.strip().isin(["", "1"])).sum()), "ME2N rows whose price unit is not 1")
    out["issue.po.cement_bags_and_tonnes"] = (int((po["Order Unit"] == "BAG").sum() + (pr["Unit of Measure"] == "BAG").sum()), "ME2N and ME5A rows in bags")
    ho = ANSWERS["ho_plant"]["plant"]
    out["issue.prs.no_project"] = (int(((pr.Plant == ho) & (pr["Requirement Tracking Number"].str.strip() == "")).sum()), "ME5A rows at the head-office plant with no tracking number")
    po_date = {(r["Purchasing Document"], r["Item"]): r["Document Date"] for _, r in po.iterrows()}
    same = sum(1 for _, r in pr.iterrows() if r["Purchase Order"] and po_date.get((r["Purchase Order"], r["Purchase Order Item"])) == r["Requisition Date"])
    out["issue.prs.same_day_po"] = (same, "ME5A rows whose PO is dated the day the PR was raised")
    cs = _sheet("RFQ CS Tracker*.csv")
    cs = cs[cs["RFQ Sent"].map(on)]
    raised = {(r["Purchase Requisition"], r["Item of Requisition"]): _dmy(r["Requisition Date"]) for _, r in pr.iterrows()}
    early = {(r["PR No."], r["PR Item"]) for _, r in cs.iterrows() if (r["PR No."], r["PR Item"]) in raised and _dmy(r["RFQ Sent"]) < raised[(r["PR No."], r["PR Item"])]}
    out["issue.cs.rfq_before_pr"] = (len(early), "PR lines whose RFQ in the CS tracker was sent before the PR was raised")
    tat = _sheet("PR PO TAT Report*.csv", skip=1)
    out["issue.tat.zero_means_none"] = (int(((tat["PR Closed"].str.strip() == "0") & (tat["Avg TAT (Days)"].str.strip() == "0")).sum()), "TAT rows with nothing closed and a turnaround of 0")
    errors = sum(1 for pat in ("Roads Major Material Requirement*.csv", "Railway Material Quantity Summary*.csv") for row in _grid(pat) for c in row if c.strip().startswith("#"))
    out["issue.requirements.sheet_errors"] = (errors, "cells of the two requirement sheets that hold a spreadsheet error")
    unit = re.compile(r"(?i)^\s*[\d,.]+\s*(l|lakh|lac|cr|crore)\s*$|^\s*\d{1,2}(,\d\d)+,\d{3}\s*$")
    fund = [p for p in (DATA / "sheets").glob("SCM Fund Requirement*.csv")]
    out["issue.fund.mixed_units"] = (sum(1 for p in fund for row in csv.reader(p.open(encoding="utf-8")) for c in row[1:] if unit.match(c)),
                                     "fund-sheet cells written in lakh, in crore words, or as rupees with lakh grouping")
    proj = _sheet("Payment Projection*.csv", skip=2)
    words = re.compile(r"(?i)^\s*[\d,.]+\s*(l|lakh|lac|cr|crore)\s*$")
    out["issue.projection.mixed_units"] = (int(proj.RTGS.map(lambda s: bool(words.match(s))).sum() + proj.LC.map(lambda s: bool(words.match(s))).sum()),
                                           "projection amounts written in lakh or crore")
    stale = 0
    limit = timedelta(days=int(ANSWERS["stale_after_days"]))
    for key, src in ANSWERS["sources"].items():
        if src.get("kind") not in ("sap", "sheet"):
            continue
        for p in sorted(DATA.glob(src["glob"])) if src.get("glob") else [DATA / src["file"]]:
            if src.get("stamp") == "header":
                m = re.search(r"Exported (\d{2}\.\d{2}\.\d{4})", p.open(encoding="utf-8").readline())
                when = _dmy(m.group(1)) if m else None
            elif src.get("stamp") == "name":
                m = re.search(r"\((\d{2})\.(\d{2})\.(\d{2})\)", p.name)
                when = date(2000 + int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None
            else:
                when = None
            stale += bool(when and when <= as_of and as_of - when > limit)
    out["issue.sources.stale"] = (stale, f"SAP exports and sheets stamped more than {limit.days} days before the data date")
    return out


def _mail(subject_word: str) -> str:
    """The body of the one mail whose file name holds the word."""
    p = next(p for p in sorted((DATA / "inbox").glob("*.eml")) if subject_word in p.name)
    msg = email.message_from_bytes(p.read_bytes(), policy=policy.default)
    return msg.get_body(preferencelist=("plain",)).get_content()


def _rs(text: str, pattern: str) -> float:
    return float(re.search(pattern, text).group(1).replace(",", ""))


def _num(s: str) -> float:
    return float(str(s).replace(",", "") or 0)


def today_figures(as_of: date | None = None) -> dict[str, tuple[float, str]]:
    """Each story's ₹ at stake, worked out the way a person with the files and a spreadsheet would. Keyed by the case key."""
    as_of = as_of or date.fromisoformat(ANSWERS["as_of"])
    out: dict[str, tuple[float, str]] = {}
    po, pr, mb = _sap("ME2N_purchase_orders.csv"), _sap("ME5A_purchase_requisitions.csv"), _sap("MB51_goods_receipts.csv").drop_duplicates()
    cs = _sheet("RFQ CS Tracker*.csv")
    lcbg = _sheet("LC BG Tracker*.csv")
    exp = _sheet("Expediting Tracker*.csv")
    idx = pd.read_csv(DATA / "external" / "commodity_index.csv", skiprows=1, dtype=str)

    mfc = _mail("MFC_request")
    out["mfc-validity:4500120768"] = (_rs(mfc, r"increase of Rs\. ([\d,]+)"), "the vendor's stated rise if the MFC comes after the PO validity (its mail)")

    deleted = pr[(pr["Deletion Indicator"] == "X") & (pr["Changed On"] == "15.10.2026") & pr["Purchase Requisition"].isin(["1000203559", "1000203669", "1000203718"])]
    value = 0.0
    for _, r in deleted.iterrows():
        q = cs[(cs["PR No."] == r["Purchase Requisition"]) & (cs["PR Item"] == r["Item of Requisition"]) & (cs["Quoted Rate (INR)"].str.strip() != "")]
        if len(q):
            value += min(_num(x) for x in q["Quoted Rate (INR)"]) * _num(r["Quantity Requested"])
    out["pr-cancelled:gaya:2026-10-15"] = (value, "each deleted Gaya PR line's quantity x its lowest quote in the CS tracker")

    pv = _mail("Price_Variation_claim")
    claimed = _rs(pv, r"PV claimed = .*= Rs\. ([\d,]+)")
    km = _rs(pv, r"claim for ([\d,]+) km")
    cur_month = re.search(r"current: Rs\. [\d,]+ per MT \((\w+) (\d{4})\)", pv)
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    cur = f"{cur_month.group(2)}-{months.index(cur_month.group(1)) + 1:02d}"
    line = po[po["Purchasing Document"] == "4500121087"].iloc[0]
    clause = line["PV Clause"] + " " + line["PV Index"]
    bm = re.search(r"Base (\d{2})/(\d{4})", clause)
    share = float(re.search(r"Variable (\d+)%", clause).group(1)) / 100
    base_month = f"{bm.group(2)}-{bm.group(1)}"
    ix = lambda m: float(idx[(idx.Index == "IEEMA_ACSR") & (idx.Month == m)].Value.iloc[0])  # noqa: E731
    ours = km * _num(line["Net Price"]) / _num(line["Price Unit"] or 1) * share * (ix(cur) / ix(base_month) - 1)
    out["pv-claim:4500121087"] = (claimed - ours, "claimed in the mail less quantity x rate x variable share x (index now / index at the PO's base month - 1)")

    ins = _mail("Inspection_call")
    free, rate = _rs(ins, r"free storage at our works for (\d+) days"), _rs(ins, r"Rs\. ([\d,]+) per day")
    row = exp[exp["PO No."] == "4500121346"].iloc[0]
    start = _dmy(row["Inspection Planned"]) + timedelta(days=int(free))
    out["inspection-ready:4500121346"] = (max(0, (_dmy(row["Site Ready (Planned)"]) - start).days) * rate, "storage rate x days from the end of free storage to the plinth date")

    dg = _mail("Warranty_expiry")
    out["commissioning:4500087611"] = (_rs(dg, r"for Rs\. ([\d,]+)"), "the vendor's price for the extended warranty (its mail)")

    lc = lcbg[(lcbg.Type == "LC") & (lcbg["PO No."] == "4500123578")].iloc[0]
    out["lc:4500123578"] = (_num(lc["Amount (INR)"]), "the LC's amount in the LC/BG tracker")
    abg = lcbg[lcbg.Number == "ABG/UTPL/2025/118"].iloc[0]
    got = mb[(mb["Purchase Order"] == abg["PO No."]) & (mb["Movement Type"] == "101")]
    out["abg:ABG/UTPL/2025/118"] = (_num(abg["Amount (INR)"]) * (0 if len(got) else 1), "the ABG amount, none of the PO received yet")

    agg = _mail("Aggregate_quotations")
    l1 = min(float(x.replace(",", "")) for x in re.findall(r"Rs\. ([\d,]+) per MT, delivered", agg))
    qty = _rs(agg, r"approx\. ([\d,]+) MT")
    last = po[(po.Material == "11000020") & (po.Plant == "1138")].copy()
    last["d"] = last["Document Date"].map(_dmy)
    last = last[last.d <= as_of].sort_values(["d", "Purchasing Document"]).iloc[-1]
    out["l1-above-last:tumkur:11000020"] = ((l1 - _num(last["Net Price"]) / _num(last["Price Unit"] or 1)) * qty, "(L1 in the mail - the last PO rate at the plant) x the quantity in the mail")
    return out


if __name__ == "__main__":
    for k, (v, how) in figures().items():
        print(f"{k:40} {v:>10,.0f}  {how}")
    for k, (v, how) in today_figures().items():
        print(f"{k:40} {v:>14,.2f}  {how}")


def _project_of() -> tuple[dict[str, str], dict[str, str]]:
    """(plant -> project name, tracking number -> project name) from the project directory."""
    d = _sheet("Project Directory.csv")
    plants = {pl: r.Project for r in d.itertuples() for pl in re.findall(r"\d{4}", r.Plant)}
    return plants, {r["Tracking No."].strip(): r["Project"] for r in d.to_dict("records") if r["Tracking No."].strip()}


def insights_figures(as_of: date | None = None) -> dict[str, tuple[float, str]]:
    """Insights figures: per project the open and cancelled PR lines and the value received in the three full months before the data date
    (every material), and per material the lowest and highest of the projects' last PO rates."""
    as_of = as_of or date.fromisoformat(ANSWERS["as_of"])
    on = lambda s: _dmy(s) is not None and _dmy(s) <= as_of      # noqa: E731
    plants, tracking = _project_of()
    proj = lambda plant, trk="": plants.get(plant) or tracking.get(trk.strip())      # noqa: E731
    out: dict[str, tuple[float, str]] = {}

    pr = _sap("ME5A_purchase_requisitions.csv")
    pr = pr[pr["Requisition Date"].map(on)].copy()
    pr["project"] = [proj(p, t) for p, t in zip(pr.Plant, pr["Requirement Tracking Number"])]
    gone = (pr["Deletion Indicator"].str.strip() != "") | (pr.Closed.str.strip() != "")
    open_ = ~gone & (pr["Purchase Order"].str.strip() == "")
    for name, n in pr[open_].groupby("project").size().items():
        out[f"project.{name}.open_prs"] = (int(n), "ME5A lines with no PO, not deleted and not closed")
    for name, n in pr[gone].groupby("project").size().items():
        out[f"project.{name}.cancelled"] = (int(n), "ME5A lines deleted or closed")

    mb = _sap("MB51_goods_receipts.csv")
    mb = mb[mb["Posting Date"].map(on)].drop_duplicates().copy()
    first = date(as_of.year, as_of.month, 1)
    months = []
    m = first
    for _ in range(3):
        m = (m - timedelta(days=1)).replace(day=1)
        months.append(m.strftime("%Y-%m"))
    mb["month"] = mb["Posting Date"].map(lambda s: _dmy(s).strftime("%Y-%m"))
    mb = mb[mb.month.isin(months)]
    sign = mb["Movement Type"].map(lambda t: -1 if t in ("102", "122") else 1)      # a reversal is exported with a minus already; count it once
    mb["net"] = sign * mb["Amount in LC"].astype(float).abs()
    mb["project"] = mb.Plant.map(plants)
    for name, v in mb.groupby("project").net.sum().items():
        out[f"project.{name}.received"] = (round(float(v), 2), f"MB51 net value (101 less 102 and 122), {months[-1]} to {months[0]}, exact repeats removed")

    po = _sap("ME2N_purchase_orders.csv")
    po = po[po["Document Date"].map(on) & (po.Material.str.strip() != "")].copy()
    mm = _sap("material_master.csv").set_index("Material")
    po["project"] = po.Plant.map(plants)
    po = po[po.project.notna()]

    def rate(r) -> float:
        x = float(r["Net Price"]) / float(r["Price Unit"] or 1)
        alt = mm.at[r.Material, "Alternative Unit"] if r.Material in mm.index else ""
        return x * float(mm.at[r.Material, "Alt. Units per Base Unit"]) if alt and r["Order Unit"] == alt else x

    po["rate"] = po.apply(rate, axis=1)
    po["d"] = po["Document Date"].map(_dmy)
    po["line"] = po["Purchasing Document"] + "/" + po.Item
    last = po.sort_values(["d", "line"]).groupby(["Material", "project"]).tail(1)
    for mat, g in last.groupby("Material"):
        out[f"pricing.{mat}.low"] = (round(float(g.rate.min()), 2), "the lowest of the projects' last ME2N rates (net / price unit, per base unit)")
        out[f"pricing.{mat}.high"] = (round(float(g.rate.max()), 2), "the highest of the projects' last ME2N rates")
    return out


def records_figures(as_of: date | None = None) -> dict[str, tuple[float, str]]:
    """Records figures: per vendor company the value of every PO line on file with it, and the open value (ordered less received, net of
    reversals, at the line's rate) of the lines still more than 0.5% open. A vendor code a person linked to another company counts under that
    company."""
    as_of = as_of or date.fromisoformat(ANSWERS["as_of"])
    on = lambda s: _dmy(s) is not None and _dmy(s) <= as_of      # noqa: E731
    alias = {a["record"]: a["identity"] for a in ANSWERS.get("vendor_aliases") or []}
    mm = _sap("material_master.csv").set_index("Material")
    po = _sap("ME2N_purchase_orders.csv")
    po = po[po["Document Date"].map(on)].copy()
    mb = _sap("MB51_goods_receipts.csv")
    mb = mb[mb["Posting Date"].map(on)].drop_duplicates()

    def per_base(material: str, unit: str) -> float:
        """How many of `unit` make one base unit of the material (bags to the tonne), 1 when the unit is the base unit."""
        if material in mm.index and unit and unit == mm.at[material, "Alternative Unit"]:
            return float(mm.at[material, "Alt. Units per Base Unit"])
        return 1.0

    got: dict[tuple[str, str], float] = {}
    for r in mb.to_dict("records"):
        key = (r["Purchase Order"], r["Item"])
        got[key] = got.get(key, 0.0) + float(r["Quantity"]) / per_base(r["Material"], r["Unit of Entry"])
    out: dict[str, tuple[float, str]] = {}
    value: dict[str, float] = {}
    open_: dict[str, float] = {}
    for r in po.to_dict("records"):
        f = per_base(r["Material"], r["Order Unit"])
        qty, rate = float(r["Order Quantity"]) / f, float(r["Net Price"]) / float(r["Price Unit"] or 1) * f
        who = alias.get(r["Supplier"], r["Supplier"])
        value[who] = value.get(who, 0.0) + qty * rate
        left = max(0.0, qty - got.get((r["Purchasing Document"], r["Item"]), 0.0))
        if left > 0.005 * qty:      # under 0.5% left open counts as received (the reversals step's stated rule)
            open_[who] = open_.get(who, 0.0) + left * rate
    for who in value:
        out[f"vendor.{who}.po_value"] = (round(value[who], -2), "Σ ME2N order quantity x net price / price unit, per base unit; to ₹100")
        out[f"vendor.{who}.open_value"] = (round(open_.get(who, 0.0), -2), "Σ (ordered less MB51 received, net of reversals) x the line's rate, lines over 0.5% open; to ₹100")
    return out
