"""Read the sources as they stood on the data date: nothing dated after it exists yet.

Defect: none in the files. The step exists so the same recipe can rebuild the database as it stood on an earlier day
(`AS_OF=2026-09-01 make build-data`): "would we have seen it coming" is asked of the system that way. On the data's own date it changes nothing
and records nothing.
Rule: a sheet built after the data date is not read at all; a tracker (a running record) is read row by row as of the data date. A PR raised, a PO dated, a receipt posted, a ledger item, a quote's RFQ,
a vendor created or a library approval after the data date is not read (each dropped with the reason). A date after the data date in a row that is kept (a PR's release, its PO, a
deletion, a payment, a CS approval, a milestone) is blanked, as it would have been blank that day. Mail and index months are cut where they are read.
Consequence if ignored: a replay would know next week's orders, receipts and decisions.
"""
from app.domain.imports.helpers import parse_dmy, parse_export_stamp, stamp_in_name


def _after(series, cut):
    return series.map(lambda s: bool(s.strip()) and parse_dmy(s) > cut)


def run(ctx):
    cut, files = ctx.as_of, ctx.t["_files"]
    gone = []
    rows_cut = {k for k, v in ctx.answers["sources"].items() if v.get("cut") == "rows"}
    for f in files.itertuples():
        stamp = stamp_in_name(f.file.split("/")[-1]) if f.stamp == "name" else None
        if stamp and stamp > cut and f.key not in rows_cut:
            gone.append(f.file)
            del ctx.t[f.raw_table]
    ctx.t["_files"] = files[~files.file.isin(gone)].reset_index(drop=True)
    ctx.issue("horizon.sources", "sheets", "Sheets built after the data date", len(gone), "drop",
              f"Not read: the data stands as of {cut}.", "A replay would know sheets nobody had built yet.", "; ".join(gone[:3]), "Sudeep")

    def cut_rows(table: str, col: str, label: str) -> int:
        if table not in ctx.t:
            return 0
        df = ctx.t[table]
        late = _after(df[col], cut)
        for src in df[late].src_row:
            ctx.drop(f"{label} (after the data date)", int(src), f"dated after the data date {cut}", "not read")
        ctx.t[table] = df[~late].copy()
        return int(late.sum())

    n = cut_rows("raw_me5a", "Requisition Date", "ME5A") + cut_rows("raw_me2n", "Document Date", "ME2N") + cut_rows("raw_mb51", "Posting Date", "MB51") \
        + cut_rows("raw_fbl1n", "Document Date", "FBL1N") + cut_rows("raw_cs_tracker", "RFQ Sent", "RFQ CS tracker") \
        + cut_rows("raw_vendor_master", "Created On", "Vendor master") + cut_rows("raw_vendor_library", "Approved On", "Vendor library")
    blanked = 0
    if "raw_me5a" in ctx.t:
        pr = ctx.t["raw_me5a"]
        po_dates = dict(zip(ctx.t["raw_me2n"]["Purchasing Document"], ctx.t["raw_me2n"]["Document Date"]))
        rel = _after(pr["Release Date"], cut)
        pr.loc[rel, "Release Date"] = ""
        no_po = pr["Purchase Order"].map(lambda p: bool(p) and (p not in po_dates or parse_dmy(po_dates[p]) > cut))
        pr.loc[no_po, ["Purchase Order", "Purchase Order Item"]] = ""
        chg = _after(pr["Changed On"], cut)
        pr.loc[chg, ["Deletion Indicator", "Closed", "Changed On"]] = ""
        blanked += int(rel.sum() + no_po.sum() + chg.sum())
    if "raw_fbl1n" in ctx.t:
        led = ctx.t["raw_fbl1n"]
        clr = _after(led["Clearing Date"], cut)
        led.loc[clr, ["Clearing Document", "Clearing Date"]] = ""
        blanked += int(clr.sum())
    if "raw_cs_tracker" in ctx.t:
        cs = ctx.t["raw_cs_tracker"]
        q = _after(cs["Quote Date"], cut)
        cs.loc[q, ["Quote Date", "Quoted Rate (INR)", "Valid Till", "L1"]] = ""
        a = _after(cs["Approved On"], cut)
        cs.loc[a, ["Approved By", "Approved On"]] = ""
        cs.loc[a, "CS Status"] = "Pending"
        blanked += int(q.sum() + a.sum())
    if "raw_expediting" in ctx.t:
        ex = ctx.t["raw_expediting"]
        for col in ("MFC Requested", "MFC Issued", "Inspection Call", "Inspection Done", "Dispatch Clearance", "Delivered", "Commissioned"):
            m = _after(ex[col], cut)
            ex.loc[m, col] = ""
            blanked += int(m.sum())
    if "raw_lc_bg" in ctx.t:
        lc = ctx.t["raw_lc_bg"]
        m = _after(lc["Issued On"], cut)
        lc.loc[m, ["Issued On", "Number"]] = ""
        lc.loc[m, "Status"] = "Pending"
        blanked += int(m.sum())
    if "raw_commodity_index" in ctx.t:
        ci = ctx.t["raw_commodity_index"]
        late = ci.Month > cut.strftime("%Y-%m")
        for src in ci[late].src_row:
            ctx.drop("commodity_index (after the data date)", int(src), f"a month after the data date {cut}", "not read")
        ctx.t["raw_commodity_index"] = ci[~late].copy()
        n += int(late.sum())
    ctx.issue("horizon.rows", "SAP exports and trackers", "Rows dated after the data date", n, "drop", f"Not read: the data stands as of {cut}.",
              "A replay would know orders, receipts, quotes and vendors from after the day it replays.", f"{n} rows", "SAP admin")
    ctx.issue("horizon.dates", "SAP exports and trackers", "Dates after the data date in rows that are kept", blanked, "fix",
              "Blanked, as they were blank that day (a release, a PO, a deletion, a payment, an approval, a milestone).",
              "A replay would show a PR converted or a CS approved before it happened.", f"{blanked} cells", "SAP admin")
