"""Independent oracle: recomputes every expected number in evals/cases from the raw files in data/.

Uses only pandas and the standard library, never application code, so an answer sheet can be
re-derived by anyone. Run: python -m evals.oracle [data_dir]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

ASOF = pd.Timestamp("2026-09-25")
EFFECTIVE = {1: pd.Timestamp("2026-11-01"), 2: pd.Timestamp("2027-01-01")}  # each tranche has its own date
TRANCHES = [("850131", .25, 1), ("850132", .25, 1), ("850440", .25, 1), ("850760", .25, 1),
            ("848210", .15, 2), ("848340", .15, 2), ("853669", .15, 2), ("854442", .15, 2)]
EXCLUDED = ("8536694010", "85444220")
COO = {"CN": "CN", "CHINA": "CN", "PRC": "CN", "CHINA (PRC)": "CN", "P.R. CHINA": "CN",
       "US": "US", "UNITED STATES": "US", "USA": "US", "U.S.A.": "US", "TW": "TW", "TAIWAN": "TW",
       "R.O.C.": "TW", "TAIWAN, ROC": "TW", "MY": "MY", "MALAYSIA": "MY", "JP": "JP", "JAPAN": "JP",
       "MX": "MX", "MEXICO": "MX", "DE": "DE", "GERMANY": "DE", "DEUTSCHLAND": "DE", "TH": "TH",
       "THAILAND": "TH", "PH": "PH", "PHILIPPINES": "PH", "KR": "KR", "SOUTH KOREA": "KR", "CH": "CH",
       "SWITZERLAND": "CH", "VN": "VN", "VIETNAM": "VN"}
FM = {("HPO-26-00450", "20"), ("HPO-26-00450", "10"), ("HPO-26-00532", "10"), ("HPO-26-00614", "10"),
      ("HPO-26-00614", "30"), ("HPO-26-00532", "20"), ("HPO-26-00614", "20"), ("HPO-26-00670", "10"),
      ("HPO-26-00670", "20"), ("HPO-26-00532", "30")}
PRODUCTS = {"HR-90020": "tern", "HR-90050": "porter", "HR-90110": "heron"}


def part_no(x: str) -> str:
    """HR-NNNNN from the legacy 'HR51110', stray spaces, lower case and a letter O typed for a zero (HR-211O9)."""
    m = re.fullmatch(r"HR-?([0-9O]{5})", str(x).strip().upper())
    if m:
        return f"HR-{m.group(1).replace('O', '0')}"
    return str(x).strip().upper()


def _date(x):
    if pd.isna(x) or not str(x).strip():
        return pd.NaT
    s = str(x).strip()
    return pd.to_datetime(s, format="%m/%d/%Y" if "/" in s else "%Y-%m-%d")


def tranche(hts):
    """(rate, tranche) for a listed HTS code, None otherwise (letter O read as zero, dots dropped)."""
    if not isinstance(hts, str) or not hts:
        return None
    h = re.sub(r"[^0-9A-Za-z]", "", hts).upper().replace("O", "0")
    if h.startswith(EXCLUDED):
        return None
    return next(((r, t) for pre, r, t in TRANCHES if h.startswith(pre)), None)


def load(d: Path):
    r = lambda f: pd.read_csv(d / f, dtype=str)  # noqa: E731
    po, parts, sup, bom, fc, fx = (r("purchase_orders.csv"), r("parts.csv"), r("suppliers.csv"),
                                   r("bom.csv"), r("demand_forecast.csv"), r("external/fx_rates.csv"))
    raw_rows = len(po)
    po = po.drop_duplicates(subset=["po_number", "line", "part_number", "qty", "unit_price", "order_date"])
    # 9 closed or cancelled lines have a blank currency: inferred from the supplier's invoicing currency.
    sup_cur = dict(zip(sup.supplier_id, sup.currency))
    po = po.assign(pn=po.part_number.map(part_no),
                   cur=po.currency.fillna(po.supplier_id.map(sup_cur)).replace({"RMB": "CNY"}))
    for c in ("order_date", "promised_date", "received_date"):
        po[c + "_d"] = po[c].map(_date)
    mult = po.uom.str.upper().map(lambda u: 1000 if u == "KPCS" else 1)
    fxm = {(m, c): float(v) for m, c, v in zip(fx.month, fx.currency, fx.usd_per_unit)}
    po["fx"] = [1.0 if c == "USD" else fxm[(f"{d:%Y-%m}", c)] for c, d in zip(po.cur, po.order_date_d)]
    po["open_qty"] = (po.qty.astype(float) - po.qty_received.fillna("0").astype(float)).clip(lower=0) * mult
    po["usd_each"] = po.unit_price.astype(float) / mult * po.fx
    po["fm"] = [(a, b) in FM for a, b in zip(po.po_number, po.line)]
    parts["pn"] = parts.part_number.map(part_no)
    parts["coo"] = parts.country_of_origin.map(lambda v: None if pd.isna(v) else COO.get(v.strip().upper()))
    parts["tr"] = parts.hts_code.map(tranche)
    return po, parts.set_index("pn"), sup, bom, fc, raw_rows


def explode(bom: pd.DataFrame):
    b = bom.assign(p=bom.parent_part.map(part_no), c=bom.child_part.map(part_no), q=bom.qty_per.astype(float))
    kids = {k: g for k, g in b.groupby("p")}

    def walk(root, mult, out):
        for _, row in kids.get(root, b.iloc[0:0]).iterrows():
            out[row.c] = out.get(row.c, 0) + mult * row.q
            walk(row.c, mult * row.q, out)
        return out
    return {p: walk(p, 1.0, {}) for p in PRODUCTS}


def earliest_restart(d: Path) -> pd.Timestamp | None:
    """The force-majeure notice's own words: 'partial production will resume in 6 to 8 weeks'. The earliest restart is the notice's date (its file name) plus the low end."""
    for f in sorted((d / "quotes").glob("*NOTICE_OF_FORCE_MAJEURE*.eml")):
        m = re.search(r"resume in (\d+) to (\d+) weeks", " ".join(f.read_text(encoding="utf-8", errors="replace").split()))
        if m:
            return pd.Timestamp(f.name[:10]) + pd.Timedelta(weeks=int(m[1]))
    return None


def in_transit_window(d: Path) -> dict[int, tuple[pd.Timestamp, pd.Timestamp]]:
    """The notice's own sentence: 'Tranche 1 goods exported from China before A and entered before B are not subject'. {tranche: (A, B)}; a tranche the notice does not name has none."""
    text = (d / "external" / "tariff_notice.md").read_text(encoding="utf-8")
    return {int(m[1]): (pd.Timestamp(m[2]), pd.Timestamp(m[3]))
            for m in re.finditer(r"Tranche (\d) goods exported from [\w ]+? before (\d{4}-\d{2}-\d{2}) and entered before (\d{4}-\d{2}-\d{2})", text)}


def rule_table(window) -> list[str]:
    """The oracle's reading of the rules, one line each, so a reader can challenge the reading and not only the arithmetic."""
    rows = ["Duty applies to China-origin goods only, by origin and not by export country; the rate is on the price without freight; DDP: the supplier is importer of record and the duty is a pass-through beside Halden's figure."]
    for tr, eff in EFFECTIVE.items():
        w = window.get(tr)
        rows.append(f"Tranche {tr}: applies to goods entered on or after {eff:%Y-%m-%d}. " + (f"Exempt if exported before {w[0]:%Y-%m-%d} and entered before {w[1]:%Y-%m-%d}." if w else "No in-transit exemption."))
    rows += ["OWED: an open line promised on or after the effective date and, where an exemption window exists, on or after its end; plus the 12-month need from the effective month that is not yet on order, at the latest clean price.",
             "A line under force majeure whose notice puts the earliest restart after the effective date cannot ship before it: OWED.",
             "CONDITIONAL: an open line with no usable entry date (past due, undated, or under force majeure with a restart that may come before the effective date), or inside the exemption window: owed only if it enters in time; never added to OWED.",
             "IF CHINA: a listed part of unknown origin: what it would owe if made in China (owed plus conditional), never in the headline.",
             "A line promised after today and before the effective date enters before the duty applies: in no bucket. Stale legacy lines are in gross only."]
    return rows


def compute(d: Path) -> dict:
    po, parts, sup, bom, fc, raw_rows = load(d)
    qpr = explode(bom)
    fc["pk"] = fc["product"].str.lower().map(lambda n: next(p for p, k in PRODUCTS.items() if k in n))
    fc["u"] = fc.units.astype(float)
    units = fc.groupby(["pk", "month"]).u.sum().unstack(0).fillna(0)
    req = lambda part, months=None: sum(  # noqa: E731
        (units[p] if months is None else units[p].loc[months]).sum() * qpr[p].get(part, 0) for p in PRODUCTS)

    open_ = po[po.status.isin(["OPEN", "PARTIAL"])].copy()
    stale = open_.po_number.str.startswith("PO-") & (open_.promised_date_d < pd.Timestamp("2026-01-01"))
    supply = open_[~stale]
    inactive = set(sup.supplier_id[sup.status == "Inactive"])
    ref = po[(po.status != "CANCELLED") & ~po.supplier_id.isin(inactive) & (po.qty.astype(float) > 0)].copy()
    med = ref.groupby("pn").usd_each.transform("median")
    ref = ref[(ref.usd_each < 3 * med) & (ref.usd_each > med / 3)]  # a price slip is not a reference
    ref = ref.assign(_line=ref.line.astype(int)).sort_values(["order_date_d", "po_number", "_line"])
    late_price = ref.groupby("pn").usd_each.last()
    late_supplier = ref.groupby("pn").supplier_id.last()
    ddp = {sid for sid, inc in zip(sup.supplier_id, sup.incoterms) if isinstance(inc, str) and inc.upper().startswith("DDP")}
    out = {"po_rows_raw": raw_rows - 0, "po_duplicates_dropped": raw_rows - len(po),
           "open_lines": len(open_), "past_due_raw": int((open_.promised_date_d < ASOF).sum()),
           "stale_lines": sorted(f"{a}/{b}" for a, b in zip(open_[stale].po_number, open_[stale].line)),
           "past_due": int((supply.promised_date_d < ASOF).sum()),
           "fm_open_qty": float(po[po.fm].open_qty.sum()),
           "fm_hr40110_open_qty": float(po[po.fm & (po.pn == "HR-40110")].open_qty.sum())}

    window = in_transit_window(d)

    def figures(mask, tr):
        """Duty in three buckets for the parts in `mask` on tranche `tr`, from the raw files, by the notice's own rule:
        OWED (China origin, enters on or after the effective date, with the in-transit window applied where the notice gives one),
        CONDITIONAL (owed only if it enters in time: an open line with no usable date, or inside the window), and the gross beside it.
        A DDP supplier is importer of record: its duty comes back as a price line, so it is counted beside Halden's figure, not in it.
        Returns (owed, gross, per_part_owed, pt_owed, pt_gross, conditional, per_part_conditional, per_line_bucket, per_part_gross)."""
        owed = gross = pt_owed = pt_gross = cond = 0.0
        per_part, per_gross, per_cond, per_line = {}, {}, {}, {}
        eff = EFFECTIVE[tr]
        for part, row in parts[mask].iterrows():
            if not isinstance(row.tr, tuple) or row.tr[1] != tr:
                continue
            rate = row.tr[0]
            lines = supply[supply.pn == part]
            every = open_[open_.pn == part]  # gross counts every open line, the stale legacy ones included
            price = late_price.get(part, 0.0)
            is_ddp = lines.supplier_id.isin(ddp)
            fm_late = lines.fm & (restart is not None and restart > eff)                         # force majeure, and the notice's earliest restart is after the duty date: it cannot ship before it
            no_date = (lines.promised_date_d.isna() | (lines.promised_date_d < ASOF) | lines.fm) & ~fm_late   # force majeure (restart may be early), past due, undated: the entry date is unknown
            before = ~no_date & ~fm_late & (lines.promised_date_d < eff)                        # enters before the duty applies
            inside = ~no_date & ~fm_late & ~before & (lines.promised_date_d < window[tr][1]) if tr in window else pd.Series(False, index=lines.index)
            is_cond, is_owed = no_date | inside, fm_late | (~no_date & ~before & ~inside)
            for (po_, ln), c_, o_, d_ in zip(zip(lines.po_number, lines.line), is_cond, is_owed, is_ddp):
                per_line[f"{po_}/{ln}"] = "pass_through" if d_ else "conditional" if c_ else "owed" if o_ else "not_owed"   # a DDP line's duty is the supplier's, passed back in the price
            val = lines.open_qty * lines.usd_each
            need_after = sum(units[p].loc[[m for m in units.index if m >= f"{eff:%Y-%m}"]].sum() * qpr[p].get(part, 0) for p in PRODUCTS)
            uncovered_owed = min(max(0.0, req(part) - lines.open_qty.sum()), need_after)   # earlier months are covered by what is already in flight
            fc_ddp = late_supplier.get(part) in ddp
            g_open_h, g_open_p = (every[~every.supplier_id.isin(ddp)].open_qty * every[~every.supplier_id.isin(ddp)].usd_each).sum() * rate, (every[every.supplier_id.isin(ddp)].open_qty * every[every.supplier_id.isin(ddp)].usd_each).sum() * rate
            o_h, o_p = val[is_owed & ~is_ddp].sum() * rate, val[is_owed & is_ddp].sum() * rate
            c_h = val[is_cond & ~is_ddp].sum() * rate
            g_h = g_open_h + (0 if fc_ddp else req(part) * price * rate)
            g_p = g_open_p + (req(part) * price * rate if fc_ddp else 0)
            o_h += 0 if fc_ddp else uncovered_owed * price * rate
            o_p += uncovered_owed * price * rate if fc_ddp else 0
            gross += g_h; owed += o_h; cond += c_h; pt_gross += g_p; pt_owed += o_p
            if o_h:
                per_part[part] = round(o_h)
            if c_h:
                per_cond[part] = round(c_h)
            if g_h:
                per_gross[part] = round(g_h)
        figures.last_gross = per_gross  # for the part-by-part comparison with another build
        return round(owed), round(gross), per_part, round(pt_owed), round(pt_gross), round(cond), per_cond, per_line, per_gross

    restart = earliest_restart(d)
    cn = parts.coo == "CN"
    unk = parts.coo.isna() & parts.tr.map(lambda t: isinstance(t, tuple)) & (parts.status == "Active")
    t1 = figures(cn, 1)
    t2 = figures(cn, 2)
    uo = figures(unk, 1)
    uo2 = figures(unk, 2)
    out.update(t1_net=t1[0], t1_gross=t1[1], t1_per_part=dict(sorted(t1[2].items(), key=lambda kv: -kv[1])[:6]),
               t2_per_part=t2[2], t2_net=t2[0], t2_gross=t2[1], t2_pass_through_net=t2[3], t2_pass_through_gross=t2[4],
               t1_pass_through_net=t1[3], unknown_origin_net=uo[0] + uo2[0] + uo[5] + uo2[5], unknown_origin_gross=uo[1] + uo2[1],
               unknown_origin_parts=sorted(parts[unk].index), unknown_hts_china=sorted(
                   p for p, r in parts[(parts.coo == "CN") & parts.hts_code.isna() & (parts.status == "Active")].iterrows()),
               t1_owed=t1[0], t1_conditional=t1[5], t2_owed=t2[0], t2_conditional=t2[5], if_china=uo[0] + uo2[0] + uo[5] + uo2[5],
               owed_by_part={**t1[2], **t2[2]}, t1_owed_by_part=t1[2], conditional_by_part={**t1[6], **t2[6]}, gross_by_part={**t1[8], **t2[8]},
               if_china_by_part={p: round(a + b) for p, a, b in ((p, uo[2].get(p, 0) + uo2[2].get(p, 0), uo[6].get(p, 0) + uo2[6].get(p, 0)) for p in set(uo[2]) | set(uo2[2]) | set(uo[6]) | set(uo2[6]))},
               line_buckets={**t1[7], **t2[7]}, rules=rule_table(window))
    return out


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "data"
    for k, v in compute(root).items():
        print(f"{k}: {v}")


def revised_dates(d: Path) -> dict[tuple[str, int], pd.Timestamp]:
    """New dates suppliers gave in tables of their notices: 'HPO-26-00517  10  JPD150-48S12  630  2026-11-11' (the last date on a PO line row)."""
    row = re.compile(r"^\s*(HPO-\d{2}-\d{5})\s+(\d+)\s+.*?(\d{4}-\d{2}-\d{2})\s*$")
    out = {}
    for f in sorted((d / "quotes").glob("*")):
        if f.suffix not in (".eml", ".txt"):
            continue
        for ln in f.read_text(errors="ignore").splitlines():
            m = row.match(ln)
            if m:
                out[(m.group(1), int(m.group(2)))] = pd.Timestamp(m.group(3))
    return out


def readiness(d: Path, product: str, month: str) -> dict:
    """Where each bought part of a named build stands, from the raw files: counts by state.

    Bought parts are the leaves of the product's BOM tree; the other nodes (below the product itself) are assemblies Halden builds. Supply is the open,
    non-stale PO lines of a part. A part is, in this order: disrupted (a supply line is under a force-majeure notice), past due (a line promised before
    the data date), undated (a line with no promise date), covered (a line lands by the end of the month, so in time for the build), after the build (every line lands after the
    month ends), or has no open order. Stock is not in the data, so nothing is 'in stock'."""
    po, parts, sup, bom, fc, _ = load(d)
    pk = next(p for p, k in PRODUCTS.items() if k in product.lower())
    units = float(fc[(fc["product"].str.lower() == product.lower()) & (fc.month == month)].units.astype(float).sum())
    b = bom.assign(p=bom.parent_part.map(part_no), c=bom.child_part.map(part_no))
    kids = b.groupby("p").c.apply(set).to_dict()
    nodes, stack = set(), [pk]
    while stack:
        for c in kids.get(stack.pop(), ()):
            if c not in nodes:
                nodes.add(c)
                stack.append(c)
    assemblies = {n for n in nodes if n in kids}
    leaves = nodes - assemblies
    open_ = po[po.status.isin(["OPEN", "PARTIAL"])]
    stale = open_.po_number.str.startswith("PO-") & (open_.promised_date_d < pd.Timestamp("2026-01-01"))
    supply = open_[~stale & (open_.open_qty > 0)].copy()
    revised = revised_dates(d)  # a supplier's own notice of a new date beats the date on the PO
    supply["promised_date_d"] = [revised.get((a, int(b)), x) for a, b, x in zip(supply.po_number, supply.line, supply.promised_date_d)]
    start = pd.Timestamp(f"{month}-01")
    end = start + pd.offsets.MonthEnd(0)
    counts: dict[str, int] = {"in_house": len(assemblies)}
    state_of = {}
    for part in sorted(leaves):
        lines = supply[supply.pn == part]
        if lines.empty:
            s = "no_order"
        elif lines.fm.any():
            s = "disrupted"
        elif (lines.promised_date_d < ASOF).any():
            s = "past_due"
        elif lines.promised_date_d.isna().any():
            s = "undated"
        elif (lines.promised_date_d <= end).any():
            s = "covered"
        else:
            s = "after_build"
        state_of[part] = s
        counts[s] = counts.get(s, 0) + 1
    qpr = explode(bom)[pk]
    short = sorted(p for p, st in state_of.items() if st == "covered"
                   and supply[(supply.pn == p) & (supply.promised_date_d <= end)].open_qty.sum() < units * qpr.get(p, 0))
    return {"units": units, "bought_parts": len(leaves), "counts": counts, "state_of": state_of, "covered_but_short_on_quantity": short}


def chase(d: Path) -> dict:
    """Open lines past their PO date with no word from the supplier, from the raw files.

    Open or partial lines promised before the data date; not the stale legacy lines; not a line the Yunzhan force-majeure notice names; not a line of a supplier that has announced a closure or a force majeure; and not a
    line of any PO that a message mentions outside quoted text (a supplier who wrote about the order has said something). Value is the open
    quantity at the line's own price in USD."""
    po, parts, sup, bom, fc, _ = load(d)
    open_ = po[po.status.isin(["OPEN", "PARTIAL"]) & (po.open_qty > 0)]
    stale = open_.po_number.str.startswith("PO-") & (open_.promised_date_d < pd.Timestamp("2026-01-01"))
    mentioned = set()
    for f in (d / "quotes").glob("*"):
        if f.suffix in (".eml", ".txt"):
            for ln in f.read_text(errors="ignore").splitlines():
                if not ln.lstrip().startswith(">"):
                    mentioned.update(re.findall(r"HPO-\d{2}-\d{5}", ln))
    # a supplier whose message announces when it can and cannot ship (a closure "from Oct 1 to Oct 7", or a force-majeure notice) has not gone silent, by its sender's domain
    domain_of = {sid: str(e).split("@")[-1].lower() for sid, e in zip(sup.supplier_id, sup.contact_email) if isinstance(e, str) and "@" in e}
    spoke = set()
    for f in (d / "quotes").glob("*"):
        if f.suffix in (".eml", ".txt"):
            text = f.read_text(errors="ignore")
            flat = " ".join(text.split())
            if re.search(r"clos(?:e|ed|ure)\b[^.]*?\bfrom\s+[A-Z][a-z]+ \d{1,2}(?:,? \d{4})? to [A-Z][a-z]+ \d{1,2}", flat) or "FORCE MAJEURE" in f.name.upper():
                m = re.search(r"^From:.*?([\w.+-]+@([\w.-]+))", text, re.M)
                if m:
                    spoke.add(m.group(2).lower())
    late = open_[~stale & (open_.promised_date_d < ASOF) & ~open_.fm & ~open_.po_number.isin(mentioned) & ~open_.supplier_id.map(lambda s: domain_of.get(s) in spoke)].copy()
    late["usd_open"] = late.open_qty * late.usd_each
    late = late.sort_values("usd_open", ascending=False)
    return {"lines": len(late), "usd_open": float(late.usd_open.sum()), "largest": f"{late.iloc[0].po_number}/{late.iloc[0].line}" if len(late) else None,
            "largest_usd": float(late.usd_open.iloc[0]) if len(late) else 0.0, "buyers": sorted(late.buyer.dropna().unique()),
            "line_ids": sorted(f"{a}/{b}" for a, b in zip(late.po_number, late.line))}
