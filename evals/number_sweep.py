"""Number truth sweep: every figure the screens show, recomputed from the raw files in data/ and never from the database.

`python -m evals.number_sweep` prints one line per figure: what the app shows, what the raw files give, where in them, and whether they agree. The shown values
are read through the same services the screens use (the Action list, an item's tiles, the counts, the suppliers list, the readiness counts); the recomputed values come
from `evals.oracle`'s reader of data/ (clean dates, FX, duplicates) plus the raw CSVs and mails read here. A mismatch is a bug in the app or in this sweep: both get fixed.
`tests/domain/test_number_truth.py` runs it as a test."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from evals import oracle

ROOT = Path(__file__).resolve().parents[1]
ASOF = pd.Timestamp("2026-09-25")


@dataclass
class Row:
    group: str
    name: str
    shown: object
    recomputed: object
    source: str
    ok: bool


def _close(a, b, tol=1.0) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return a == b


class Sweep:
    def __init__(self, db: Path, data: Path):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        self.data, self.rows = data, []
        self.session = Session(create_engine(f"sqlite:///{db}", future=True))
        self.po, self.parts, self.sup, self.bom, self.fc, self.raw_po_rows = oracle.load(data)
        self.po["csv_row"] = self.po.index + 2      # the row in purchase_orders.csv (header is row 1)
        self._units()
        self.domain = {sid: str(e).split("@")[-1].lower() for sid, e in zip(self.sup.supplier_id, self.sup.contact_email) if isinstance(e, str) and "@" in e}
        self._rename_domains()
        self.open_ = self.po[self.po.status.isin(["OPEN", "PARTIAL"]) & (self.po.open_qty > 0)]
        self.stale = self.open_.po_number.str.startswith("PO-") & (self.open_.promised_date_d < pd.Timestamp("2026-01-01"))
        self.live = self.open_[~self.stale]
        self.revised = oracle.revised_dates(data)

    def _units(self):
        """What the oracle leaves in the file's own units, put in the part's: feet of wire are metres (x 0.3048, the price per metre follows), a BOM row in millimetres is metres, and an exact repeat of a BOM row is one row."""
        ft = self.po.uom.str.upper() == "FT"
        self.po.loc[ft, "open_qty"] = self.po.loc[ft, "open_qty"] * 0.3048
        self.po.loc[ft, "usd_each"] = self.po.loc[ft, "usd_each"] / 0.3048
        self.bom = self.bom.drop_duplicates().copy()
        mm = self.bom.uom.str.upper() == "MM"
        self.bom.loc[mm, "qty_per"] = (self.bom.loc[mm, "qty_per"].astype(float) / 1000).astype(str)

    def _rename_domains(self):
        """A company that says it has a new legal name ('Legal name: X (formerly Y)') keeps one identity: its old domain is the new one's."""
        for f in sorted((self.data / "quotes").glob("*")):
            if f.suffix not in (".eml", ".txt"):
                continue
            text = " ".join(f.read_text(errors="ignore").split())
            if re.search(r"Legal name:.*\(formerly", text):
                m = re.search(r"From:.*?@([\w.-]+)", f.read_text(errors="ignore"))
                new = m.group(1).lower() if m else None
                old = next((d for d in self.domain.values() if d.startswith("baycrest")), None)
                if new and old:
                    self.domain = {k: (old if v == new else v) for k, v in self.domain.items()}

    def check(self, group, name, shown, recomputed, source, tol=1.0):
        self.rows.append(Row(group, name, shown, recomputed, source, _close(shown, recomputed, tol)))

    def lines_of(self, df, ident):
        dom = self.domain.get(ident)
        return df[df.supplier_id.map(lambda s: self.domain.get(s) == dom)]

    def src(self, df) -> str:
        rows = sorted(df.csv_row.tolist())
        return "data/purchase_orders.csv rows " + (", ".join(map(str, rows[:6])) + (f" … ({len(rows)} rows)" if len(rows) > 6 else "")) if rows else "data/purchase_orders.csv (no rows)"

    # ---- the figures -------------------------------------------------------------------------------------------------------------------------

    def counts(self):
        import sqlite3

        con = sqlite3.connect(self.session.get_bind().url.database)
        n = lambda q: con.execute(q).fetchone()[0]      # noqa: E731
        self.check("counts", "vendor records", n("select count(*) from supplier_records"), len(self.sup), "data/suppliers.csv rows 2..", 0)
        legacy = sum(1 for s in self.sup.supplier_id if not str(s).startswith("SUP-"))
        companies = len(set(self.domain.values()) | {str(s) for s in self.sup.supplier_id if s not in self.domain})
        self.check("counts", "companies", n("select count(*) from supplier_identities"), companies, f"data/suppliers.csv: {len(self.sup)} records, {legacy} legacy ids, one company per contact domain (a rename keeps its old one)", 0)
        self.check("counts", "parts", n("select count(*) from parts"), len(self.parts), "data/parts.csv", 0)
        bom = pd.read_csv(self.data / "bom.csv", dtype=str)
        self.check("counts", "BOM lines", n("select count(*) from bom_lines"), len(bom.drop_duplicates()), "data/bom.csv (exact repeats dropped)", 0)
        self.check("counts", "PO lines", n("select count(*) from po_lines"), len(self.po), "data/purchase_orders.csv (exact repeats dropped)", 0)
        live_n = len(self.live)
        self.check("counts", "open PO lines (live)", n("select count(*) from po_lines where status in ('OPEN','PARTIAL') and flags not like '%stale_open%'"), live_n, self.src(self.live), 0)
        self.check("counts", "stale open lines", n("select count(*) from po_lines where flags like '%stale_open%'"), int(self.stale.sum()), self.src(self.open_[self.stale]), 0)
        mails = [f for f in (self.data / "quotes").glob("*") if f.suffix in (".eml", ".txt") and f.name[:10] <= "2026-09-25"]
        self.check("counts", "messages", n("select count(*) from messages"), len(mails), "data/quotes/*.eml|txt dated on or before 2026-09-25", 0)
        self.check("counts", "forecast rows", n("select count(*) from demand_forecast"), len(self.fc), "data/demand_forecast.csv", 0)

    def supplier_totals(self):
        """The suppliers list: each company's open value and past-due lines."""
        from app.domain.suppliers import service as suppliers

        for s in suppliers.list_suppliers(self.session):
            mine = self.lines_of(self.live, s.ref.id)
            value = float((mine.open_qty * mine.usd_each).sum())
            late = int((mine.promised_date_d < ASOF).sum() - mine[mine.promised_date_d < ASOF].fm.sum() * 0) if len(mine) else 0
            self.check("suppliers", f"{s.ref.label[:28]}: open value", float(s.open_value.usd), value, self.src(mine), 1.0)
            late_n = int(((mine.promised_date_d < ASOF) & ~mine.promised_date_d.isna()).sum())
            self.check("suppliers", f"{s.ref.label[:28]}: past-due lines", s.past_due_lines, late_n, self.src(mine[mine.promised_date_d < ASOF]), 0)

    def tariff_and_chase(self):
        from app.domain.attention import service as attention

        o = oracle.compute(self.data)
        items = {i.key: i for i in attention.what_needs_attention(self.session)}
        t = attention.item_detail(self.session, "tariff:all")
        nums = {n.id: n.value for n in t.numbers}
        owed = items["tariff:all"].at_stake
        late = nums["tile:if_late"] if "tile:if_late" in nums else nums.get("duty_conditional:tranche1")
        china = nums["tile:if_china"] if "tile:if_china" in nums else None
        if china is None:      # the unknown-origin row holds each part's figure
            china_item = attention.item_detail(self.session, "unknown:origin")
            china_total = sum(float(n.value.usd) for n in china_item.numbers if n.id.startswith("duty_if_china_net:"))
        else:
            china_total = float(china.usd)
        self.check("today", "tariff: owed (tranche 1)", float(owed.usd), o["t1_owed"], "data/parts.csv + purchase_orders.csv + demand_forecast.csv + external/tariff_notice.md", 2.0)
        self.check("today", "tariff: if the open orders ship late", float(late.usd) if late else 0.0, o["t1_conditional"], "data/purchase_orders.csv + external/tariff_notice.md", 2.0)
        self.check("today", "tariff: if China (no recorded origin)", china_total, o["if_china"], "data/parts.csv (blank origin) + purchase_orders.csv", 2.0)
        self.check("today", "tariff: gross (tranche 1)", float(items["tariff:all"].at_stake_gross.usd), o["t1_gross"], "data/purchase_orders.csv + demand_forecast.csv", 2.0)
        # each buyer's share of the duty owed ("Your share" on the case): the part's buyer is the one who placed most of its PO lines,
        # ties to the most recent (the recipe's rule, step 18), read here from the raw PO file; initials and full names are one buyer
        po = pd.read_csv(self.data / "purchase_orders.csv", dtype=str)
        full = sorted({b for b in po.buyer.dropna() if " " in b})
        first = {**{b: b.split()[0] for b in full}, **{"".join(w[0] for w in b.split()): b.split()[0] for b in full}}
        po["who"] = po.buyer.map(first)
        po = po.sort_values("order_date")
        def modal(s):
            vc = s.dropna().value_counts()
            tied = set(vc[vc == vc.max()].index) if len(vc) else set()
            return next((b for b in reversed(list(s)) if b in tied), None)
        part_buyer = po.groupby("part_number").who.agg(modal)
        shares: dict[str, float] = {}
        for part, owed in o["t1_owed_by_part"].items():
            if owed and part_buyer.get(part):
                shares[part_buyer[part]] = shares.get(part_buyer[part], 0.0) + owed
        tn = {n.id: n.value for n in t.numbers}
        for who, want in sorted(shares.items()):
            got = tn.get(f"duty_share:{who}")
            self.check("today", f"tariff: {who}'s share of the duty owed", float(got.usd) if got else 0.0, want, "data/purchase_orders.csv (buyer) + parts.csv + demand_forecast.csv", 2.0)
        for part, want in sorted(o["owed_by_part"].items()):
            d = attention.item_detail(self.session, f"tariff:{part}")
            if d:
                self.check("tariff", f"{part}: owed", float(next(n.value.usd for n in d.numbers if n.id == f"duty_net:{part}")), want, "data/parts.csv, purchase_orders.csv, demand_forecast.csv", 2.0)
        c = oracle.chase(self.data)
        chase = attention.item_detail(self.session, "deadline:chase")
        nums = {n.id: n.value for n in chase.numbers}
        self.check("today", "chase: lines past due with no word", float(nums["chase:count"].value), c["lines"], "data/purchase_orders.csv + data/quotes/*", 0)
        self.check("today", "chase: open value", float(nums["chase:open_total"].usd), c["usd_open"], "data/purchase_orders.csv", 1.0)
        self.check("today", "chase: largest line", float(nums["chase:largest"].usd), c["largest_usd"], f"data/purchase_orders.csv ({c['largest']})", 1.0)

    def fire_and_slips(self):
        from app.domain.attention import service as attention

        items = {i.key: i for i in attention.what_needs_attention(self.session)}
        fm = self.live[self.live.fm]
        fire = items["disruption:SUP-0001"]
        self.check("today", "fire: open value of the lines on the notice", float(fire.at_stake.usd), float((fm.open_qty * fm.usd_each).sum()), self.src(fm), 1.0)
        self.check("today", "fire: lines on the notice", fire.lines_in_scope, len(fm), self.src(fm), 0)
        self.check("today", "fire: of them past due today", fire.lines_already_late, int((fm.promised_date_d < ASOF).sum()), self.src(fm[fm.promised_date_d < ASOF]), 0)
        units = lambda product, month: float(self.fc[(self.fc["product"].str.contains(product)) & (self.fc.month == month)].units.astype(float).sum())      # noqa: E731
        for r in fire.robots_short:
            self.check("today", f"fire: {r.product.label} robots short in {r.month}", r.robots, units(r.product.label.split()[0], r.month), "data/demand_forecast.csv (no supply on the way: the whole month's plan)", 0)
        jade = items["disruption:SUP-0013"]
        moved = self.live[[(a, int(b)) in self.revised and self.revised[(a, int(b))] > p for a, b, p in zip(self.live.po_number, self.live.line, self.live.promised_date_d)]]
        moved = moved[moved.supplier_id.map(lambda s: self.domain.get(s) == self.domain.get("SUP-0013"))]
        self.check("today", "Jadepeak: open value of the lines its notice moves", float(jade.at_stake.usd), float((moved.open_qty * moved.usd_each).sum()), self.src(moved) + " + data/quotes/2026-09-18_Jadepeak_Customer_Notice_CN-2026-09.txt", 1.0)
        self.check("today", "Jadepeak: lines moved", jade.lines_in_scope, len(moved), self.src(moved), 0)
        cons = items.get("consignment:HR-30110")
        if cons:
            line = self.live[(self.live.po_number == "HPO-26-00629") & (self.live.line == "10")]
            self.check("today", "consigned PCB: open value of the late line", float(cons.at_stake.usd), float((line.open_qty * line.usd_each).sum()), self.src(line), 1.0)
            d = attention.item_detail(self.session, cons.key)
            slip = (self.revised[("HPO-26-00629", 10)] - line.promised_date_d.iloc[0]).days
            self.check("today", "consigned PCB: days late", float(next(n.value.value for n in d.numbers if n.id in ("tile:slip_days", "consigned_slip_days:HR-30110"))), slip, "data/purchase_orders.csv + data/quotes/2026-09-16_Lead_time_update…", 0)

    def supplier_risk(self):
        from app.domain.attention import service as attention

        items = {i.key: i for i in attention.what_needs_attention(self.session)}
        total_spend = self._spend_by_domain()
        for key in [k for k in items if k.startswith("risk:")]:
            ident = key.split(":")[1]
            mine = self.lines_of(self.live, ident)
            self.check("risk", f"{key}: open value with the supplier", float(items[key].at_stake.usd), float((mine.open_qty * mine.usd_each).sum()), self.src(mine), 1.0)
            allm = self.lines_of(self.po, ident)
            closed = allm[(allm.status == "CLOSED") & ~allm.promised_date_d.isna() & ~allm.received_date_d.isna()]
            from app.domain.suppliers import service as suppliers

            row = next(s for s in suppliers.list_suppliers(self.session) if s.ref.id == ident)
            if getattr(row, "delivery", None):
                days = (closed.received_date_d - closed.promised_date_d).dt.days
                self.check("risk", f"{ident}: closed lines counted", row.delivery.n, len(closed), self.src(closed), 0)
                self.check("risk", f"{ident}: closed lines on time", row.delivery.on_time, int((days <= 0).sum()), self.src(closed), 0)
                late = days[days > 0]
                self.check("risk", f"{ident}: average days late", float(row.delivery.avg_days_late or 0), round(float(late.mean()), 1) if len(late) else 0.0, self.src(closed[days > 0]), 0.05)
            share = re.search(r"([\d.]+)% of the last twelve", items[key].at_stake_note or "")
            if share:
                self.check("risk", f"{ident}: share of the last twelve months' spend", float(share.group(1)), round(100 * total_spend.get(self.domain.get(ident), 0.0), 1), "data/purchase_orders.csv: order value in dollars, orders from 2025-09-25 on", 0.1)

    def _spend_by_domain(self) -> dict[str, float]:
        recent = self.po[self.po.order_date_d >= ASOF - pd.Timedelta(days=365)]
        value = recent.qty.astype(float) * recent.unit_price.astype(float) * recent.fx * self.po.loc[recent.index, "uom"].str.upper().map(lambda u: 1 if u != "KPCS" else 1)
        value = recent.qty.astype(float) * (recent.usd_each * (recent.open_qty * 0 + 1)) * recent.uom.str.upper().map(lambda u: 1000 if u == "KPCS" else 1)
        out: dict[str, float] = {}
        for sid, v in zip(recent.supplier_id, value):
            d = self.domain.get(sid)
            out[d] = out.get(d, 0.0) + float(v)
        total = sum(out.values()) or 1.0
        return {k: v / total for k, v in out.items()}

    def email_deadlines(self):
        from app.domain.attention import service as attention

        items = {i.key: i for i in attention.what_needs_attention(self.session)}
        meiya = items.get("deadline:SUP-0042:2026-09-28")
        if meiya:
            mine = self.lines_of(self.live, "SUP-0042")
            due = mine[mine.promised_date_d <= pd.Timestamp("2026-10-08")]
            self.check("today", "Meiya: open value due by the end of its closure", float(meiya.at_stake.usd), float((due.open_qty * due.usd_each).sum()), self.src(due) + " + data/quotes/2026-09-15_Holiday_notice_National_Day_2026.txt", 1.0)
            self.check("today", "Meiya: days to its last shipment (Sep 28)", meiya.days_left, (pd.Timestamp("2026-09-28") - ASOF).days, "data/quotes/2026-09-15_Holiday_notice_National_Day_2026.txt:10", 0)

    def prose_arrivals(self) -> dict[str, list[tuple[float, pd.Timestamp, str]]]:
        """A supplier's schedule written in a sentence: 'line 20  HR-21111  57 pcs ship 10/09, 58 pcs ship 10/30' with 'Ocean transit … around 21 days'. {part: [(qty, arrival, where)]}:
        arrival is the ship date plus the transit days the same mail gives. The oracle reads only tables of PO lines; this reads the sentences it leaves."""
        out: dict[str, list] = {}
        for f in sorted((self.data / "quotes").glob("*")):
            if f.suffix not in (".eml", ".txt"):
                continue
            text = f.read_text(errors="ignore")
            body = text.split("\n> ")[0]      # the writer's own words, not the quoted mail below
            transit = re.search(r"transit[^.\n]*?(\d+)\s+days", body)
            for n, ln in enumerate(body.splitlines(), 1):
                m = re.match(r"^\s*line\s+(\d+)\s+(HR-\d{5})\s+(.*)$", ln)
                if not m:
                    continue
                for qty, mm, dd in re.findall(r"(\d+)\s*pcs\s+ship\s+(\d{2})/(\d{2})", m.group(3)):
                    ship = pd.Timestamp(year=int(f.name[:4]), month=int(mm), day=int(dd))
                    out.setdefault(m.group(2), []).append((float(qty), ship + pd.Timedelta(days=int(transit.group(1)) if transit else 0), f"data/quotes/{f.name}:{n}"))
        return out

    def readiness(self):
        from app.domain.phases import service as phases

        for product, month in (("Tern T2", "2026-10"), ("Porter P5", "2026-10"), ("Heron H1", "2026-10")):
            want = oracle.readiness(self.data, product, month)
            want = self._with_prose(want, product, month)
            got = phases.build_readiness(self.session, next(p.product.id for p in phases.builds(self.session) if p.product.label == product), month)
            for state in ("covered", "after_build", "past_due", "disrupted", "no_order", "in_house"):
                self.check("readiness", f"{product} {month}: parts {state}", got.counts.get(state, 0), want.get("counts", want).get(state, 0), "data/bom.csv + purchase_orders.csv + demand_forecast.csv", 0)

    def _with_prose(self, want: dict, product: str, month: str) -> dict:
        """Where the oracle has a part past due only because it could not read a sentence-form schedule, read the sentence: covered if enough arrives by the month's end."""
        arrivals, end = self.prose_arrivals(), pd.Timestamp(f"{month}-01") + pd.offsets.MonthEnd(0)
        pk = next(p for p, k in oracle.PRODUCTS.items() if k in product.lower())
        qpr = oracle.explode(self.bom)[pk]
        units = want["units"]
        state_of, counts = dict(want["state_of"]), dict(want["counts"])
        for part, st in want["state_of"].items():
            if st == "past_due" and part in arrivals:
                by_end = sum(q for q, a, _ in arrivals[part] if a <= end)
                new = "covered" if by_end >= units * qpr.get(part, 0) else "after_build"
                counts["past_due"] -= 1
                counts[new] = counts.get(new, 0) + 1
                state_of[part] = new
        return {**want, "state_of": state_of, "counts": counts}

    def offers(self):
        """The Inbox's extracted facts: every offer's price is on the line of the mail or PDF it cites, and its dollars follow from it."""
        import sqlite3

        from app.domain.imports import extraction

        con = sqlite3.connect(self.session.get_bind().url.database)
        rows = con.execute("select o.id, o.message_id, o.source, o.line_ref, o.price_raw, o.price, o.price_basis, o.unit_price_each, m.body from offers o join messages m on m.id = o.message_id").fetchall()
        for oid, mid, source, line_ref, price_raw, price, basis, each, body in rows:
            lines = extraction.document_lines(self.data, source, body)
            figure = str(price_raw).split()[-1]
            found = any(figure in l for l in lines)
            self.check("inbox", f"offer {oid} ({mid[:22]}): price {figure} is in the document", int(found), 1, f"data/quotes/{mid.split('_')[0]}… {source}", 0)
            if re.fullmatch(r"\d+\.\d+|\d+", figure.replace(",", "") if figure.count(",") == 1 and len(figure.split(",")[1]) == 3 else figure):      # a plain number: the unit price follows from it
                number = float(figure.replace(",", ""))
                self.check("inbox", f"offer {oid}: unit price after 'per 1,000'", float(each), number / 1000 if basis == "per_1000" else number, f"{source} {price_raw}", 1e-6)

    def _mail(self, stem: str) -> str:
        f = next((f for f in (self.data / "quotes").glob(f"{stem}*")), None)
        return " ".join(f.read_text(errors="ignore").split()) if f else ""

    def _need12(self, part: str) -> float:
        """Robots planned in the next twelve months times what each needs of the part, through every route of the bill of materials."""
        qpr = oracle.explode(self.bom)
        total = 0.0
        for pk, key in oracle.PRODUCTS.items():
            units = float(self.fc[self.fc["product"].str.lower().str.contains(key)].units.astype(float).sum())
            total += units * qpr[pk].get(part, 0.0)
        return total

    def trust_items(self):
        from app.domain.attention import service as attention

        fraud = self._mail("2026-09-23_URGENT")
        amount = re.search(r"total USD\s*([\d,]+(?:\.\d+)?)", fraud)
        d = attention.item_detail(self.session, "trust:2026-09-23_URGENT_Updated_remittance_details_following_plant_incident")
        shown = re.search(r"send USD ([\d,]+)", d.finding)
        if amount and shown:
            self.check("trust", "remittance mail: the amount it asks you to send", float(shown.group(1).replace(",", "")), float(amount.group(1).replace(",", "")), "data/quotes/2026-09-23_URGENT_Updated_remittance_details…eml: 'total USD'", 0.5)
        spot = self._mail("2026-09-12_Spot_offer")
        price = re.search(r"USD\s*([\d.]+)\s*each", spot) or re.search(r"Price:\s*USD\s*([\d.]+)", spot)
        qty = re.search(r"([\d,]+)\s*(?:pcs|pieces)", spot)
        mpn = re.search(r"NG6603-QFN48", spot)
        t = attention.item_detail(self.session, "trust:2026-09-12_Spot_offer_-_NG6603-QFN48_in_stock_ships_today")
        times = re.search(r"([\d.]+)x the usual price", t.title)
        if price and mpn and times:
            part = next((pn for pn, r in self.parts.iterrows() if str(r.get("mpn")) == "NG6603-QFN48"), None)
            last = self.po[(self.po.pn == part) & ~self.po.status.isin(["CANCELLED"])].sort_values("order_date_d")
            if len(last):
                self.check("trust", "spot offer: times the usual price", float(times.group(1)), round(float(price.group(1)) / float(last.usd_each.iloc[-1]), 1), f"data/quotes/2026-09-12_Spot_offer…eml (USD {price.group(1)}) / the part's last PO price", 0.05)
        if price and qty:
            self.check("inbox", "spot offer: quantity and price in the message summary", int(bool(re.search(rf"{qty.group(1)}.*{re.escape(price.group(1))}", next(m.summary for m in __import__('app.domain.inbox.service', fromlist=['x']).list_messages(self.session) if m.ref.id.startswith("2026-09-12_Spot"))))), 1, "data/quotes/2026-09-12_Spot_offer…eml", 0)

    def dates(self):
        """Days left on every dated row, from the dates in the mails themselves."""
        from datetime import datetime

        from app.domain.attention import service as attention

        items = {i.key: i for i in attention.what_needs_attention(self.session)}
        for i in attention.what_needs_attention(self.session):
            pass
        def days(text_date: str) -> int:
            return (pd.Timestamp(datetime.strptime(text_date, "%B %d, %Y")) - ASOF).days
        gp = self._mail("2026-09-09_Price_adjustment")
        m = re.search(r"acknowledged by ([A-Z][a-z]+ \d+, \d{4})", gp)
        if m and "deadline:SUP-0041:2026-10-15" in items:
            self.check("dates", "Great Plains price lock: days left", items["deadline:SUP-0041:2026-10-15"].days_left, days(m.group(1)), "data/quotes/2026-09-09_Price_adjustment…eml: 'acknowledged by'", 0)
        for key in ("deadline:SUP-0001:2026-10-01", "deadline:SUP-0001:2026-10-10", "deadline:SUP-0001:2026-10-13"):   # dated rows folded under the fire are not top-level: look them up by key
            if key not in items and (child := self._child(key)):
                items[key] = child
        fm = self._mail("2026-09-22_NOTICE_OF_FORCE")
        m = re.search(r"revised (?:delivery )?dates[^.]*?by (\d{1,2} [A-Z][a-z]+ \d{4})", fm)
        if m and "deadline:SUP-0001:2026-10-10" in items:
            self.check("dates", "Yunzhan revised dates: days left", items["deadline:SUP-0001:2026-10-10"].days_left, (pd.Timestamp(datetime.strptime(m.group(1), "%d %B %Y")) - ASOF).days, "data/quotes/2026-09-22_NOTICE_OF_FORCE_MAJEURE…eml", 0)
        q = self._mail("2026-08-14_RE_RFQ")
        v = re.search(r"valid (?:for )?(\d+) days", q, re.I)
        if v and "deadline:SUP-0001:2026-10-13" in items:
            self.check("dates", "Yunzhan quote: days left", items["deadline:SUP-0001:2026-10-13"].days_left, (pd.Timestamp("2026-08-14") + pd.Timedelta(days=int(v.group(1))) - ASOF).days, "data/quotes/2026-08-14_RE_RFQ…eml: validity", 0)
        c = re.search(r"Oct (\d+) to Oct (\d+)", q)
        if c and "deadline:SUP-0001:2026-10-01" in items:
            self.check("dates", "Yunzhan closure: days to its first closed day", items["deadline:SUP-0001:2026-10-01"].days_left, (pd.Timestamp(f"2026-10-{int(c.group(1)):02d}") - ASOF).days, "data/quotes/2026-08-14_RE_RFQ…eml: 'close … from Oct 1 to Oct 7'", 0)
        bcx = self._mail("2026-09-02_Baycrest")
        f = re.search(r"forward until ([A-Z][a-z]+ \d+, \d{4})", bcx)
        if f and "deadline:SUP-0016:2026-12-31" in items:
            self.check("dates", "BCX old addresses: days left", items["deadline:SUP-0016:2026-12-31"].days_left, days(f.group(1)), "data/quotes/2026-09-02_Baycrest…eml: 'forward until'", 0)

    def stakes(self):
        """The money on dated rows that does not come from open orders: the price rise at last year's spend, and what a quote covers."""
        from datetime import timedelta

        from app.domain.attention import service as attention

        items = {i.key: i for i in attention.what_needs_attention(self.session)}
        gp = items.get("deadline:SUP-0041:2026-10-15")
        notice = self._mail("2026-09-09_Price_adjustment")
        rises = re.findall(r"\+(\d+(?:\.\d+)?)%", notice)
        if gp and len(rises) >= 2:
            ext, die = float(rises[0]) / 100, float(rises[1]) / 100
            start = pd.Timestamp(re.search(r"[Ee]ffective (\w+ \d+, \d{4})", notice).group(1))      # the rise's start and the lock's delivery-by date, both from the mail
            end = pd.Timestamp(re.search(r"for delivery by (\w+ \d+, \d{4})", notice).group(1))
            qpr = oracle.explode(self.bom)
            total = 0.0
            for pn in sorted(set(self.lines_of(self.po, "SUP-0041").pn)):
                d = self.parts.loc[pn, ["description", "category"]]
                r = die if ("die cast" in d.description.lower() or "die-cast" in d.description.lower() or "hardware" in d.category.lower()) else ext
                mine = self.lines_of(self.live, "SUP-0041")
                mine = mine[(mine.pn == pn) & (mine.promised_date_d < pd.Timestamp(end.year, end.month, 1) + pd.offsets.MonthBegin(1))]      # open supply landing by the end of the window's last month (overdue counts as now)
                need_all, need_window = 0.0, 0.0
                for m in sorted(self.fc.month.unique()):
                    if pd.Timestamp(m + "-01") <= end:
                        n = sum(float(self.fc[self.fc["product"].str.lower().str.contains(key) & (self.fc.month == m)].units.astype(float).sum()) * qpr[pk].get(pn, 0.0) for pk, key in oracle.PRODUCTS.items())
                        need_all += n
                        need_window += n if f"{start:%Y-%m}" <= m else 0.0
                left = min(max(0.0, need_all - float(mine.open_qty.sum())), need_window)      # open supply used up by the earliest need first
                hist = self.lines_of(self.po, "SUP-0041")
                hist = hist[(hist.pn == pn) & (hist.status != "CANCELLED") & (hist.qty.astype(float) > 0)].assign(_line=lambda x: x.line.astype(int)).sort_values(["order_date_d", "po_number", "_line"])      # the last paid: the latest line, ties to the later row
                if left and len(hist):
                    total += left * float(hist.usd_each.iloc[-1]) * r
            self.check("today", "Great Plains price rise: the rise on the need still to be ordered inside the lock's window", float(gp.at_stake.usd), total, self.src(self.lines_of(self.po, "SUP-0041")) + " + data/quotes/2026-09-09_Price_adjustment…eml + data/demand_forecast.csv", 1.0)
        fx = pd.read_csv(self.data / "external" / "fx_rates.csv")
        latest = {c: float(g.sort_values("month").usd_per_unit.iloc[-1]) for c, g in fx.groupby("currency")}
        import sqlite3

        con = sqlite3.connect(self.session.get_bind().url.database)
        for key in ("deadline:SUP-0002:2026-10-31", "deadline:SUP-0011:2026-11-05"):
            it = items.get(key) or self._child(key)
            if not it or "planned buys" not in it.title:
                continue
            ident, validity = key.split(":")[1], key.split(":")[2]
            offers = con.execute("select part_number, unit_price_each, currency from offers where identity_id = ? and validity_date = ? and superseded_by is null and trust != 'blocked' and part_number is not null", (ident, validity)).fetchall()
            low: dict[str, float] = {}
            for part, each, cur in offers:
                v = float(each) * (1.0 if cur == "USD" else latest[cur])
                low[part] = min(low.get(part, 1e18), v)
            shown = re.search(r"quoted on \$([\d.,]+)([KM]?) of planned buys", it.title)      # the quote prices planned buys; what lapsing costs is unknown, so the figure is in the title, not the stake
            figure = float(shown.group(1).replace(",", "")) * {"": 1, "K": 1e3, "M": 1e6}[shown.group(2)] if shown else -1.0
            want = sum(v * self._need12(p) for p, v in low.items())
            self.check("today", f"{key}: planned buys the quote prices (in the title)", figure, want, "data/quotes (the quote's prices) x data/demand_forecast.csv x data/bom.csv, at data/external/fx_rates.csv's latest month", 0.006 * want + 500)      # the title rounds to three figures

    def _child(self, key: str):
        from app.domain.attention import service as attention

        c = attention.item_context(self.session, key)
        return c[0] if c else None

    def unknown_rows(self):
        from app.domain.attention import service as attention

        o = oracle.compute(self.data)
        items = {i.key: i for i in attention.what_needs_attention(self.session)}
        n = lambda k: int(re.match(r"(\d+)", items[k].title).group(1)) if k in items else None      # noqa: E731
        self.check("today", "unknown: open orders with no promised date", n("unknown:undated"), int(self.live.promised_date_d.isna().sum()), self.src(self.live[self.live.promised_date_d.isna()]), 0)
        self.check("today", "unknown: old orders probably not open", n("unknown:stale-orders"), int(self.stale.sum()), self.src(self.open_[self.stale]), 0)
        self.check("today", "unknown: parts on a listed code with no origin", n("unknown:origin"), len(o["unknown_origin_parts"]), "data/parts.csv (blank country_of_origin, tariff-listed code)", 0)
        listed = set(self.parts[self.parts.tr.map(lambda t: isinstance(t, tuple))].category)      # categories that hold a tariff-listed code: a blank code on a grommet is a data defect, not a tariff question
        blank = self.parts[(self.parts.coo == "CN") & self.parts.hts_code.isna() & (self.parts.status == "Active") & self.parts.category.isin(listed)]
        self.check("today", "unknown: China-origin parts with no tariff code, in a category that has listed codes", n("unknown:hts"), len(blank), "data/parts.csv (blank hts_code, China origin, a category with a listed code): " + ", ".join(sorted(blank.index)), 0)

    def orders_total(self):
        from app.domain.orders import service as orders

        rows = [l for l in orders.open_orders(self.session) if not l.stale and l.unit_price is not None]
        shown = sum(float(l.qty.ea if l.qty.ea is not None else l.qty.value) * float(l.unit_price.usd) for l in rows if l.unit_price.usd is not None) if rows else 0.0
        self.check("orders", "open value of the live open lines (quantity x dollar price)", shown, float((self.live.open_qty * self.live.usd_each).sum()), self.src(self.live), 5.0)
        self.check("orders", "live open lines listed", len(rows), len(self.live), self.src(self.live), 0)

    def parts_and_forecast(self):
        """The figures behind the Parts, Forecast and Shortage screens: what each part is needed for, what is on order, what was last paid, what is planned."""
        from sqlalchemy import select

        from app.domain.demand import service as demand
        from app.domain.demand.model import DemandForecast
        from app.domain.orders import service as orders
        from app.domain.orders.model import ReferencePrice

        # the forecast, as planned
        for f in self.session.scalars(select(DemandForecast)):
            name = {"HR-90020": "tern", "HR-90050": "porter", "HR-90110": "heron"}[f.product_part]
            want = float(self.fc[self.fc["product"].str.lower().str.contains(name) & (self.fc.month == f.month)].units.astype(float).sum())
            self.check("forecast", f"{f.product_part} {f.month}: robots planned", f.units, want, "data/demand_forecast.csv", 0)
        # what each bought part is needed for in the first month and over the year, through every route of the bill of materials
        qpr = oracle.explode(self.bom)
        first_month = sorted(self.fc.month.unique())[0]
        units = {pk: self.fc[self.fc["product"].str.lower().str.contains(key) & (self.fc.month == first_month)].units.astype(float).sum() for pk, key in oracle.PRODUCTS.items()}
        want_parts = {p for pk in qpr for p in qpr[pk]}
        for part in sorted(want_parts):
            reqs = demand.requirements(self.session, part)
            if not reqs:
                continue
            self.check("parts", f"{part}: needed in {first_month}", float(reqs[0].qty.value), sum(units[pk] * qpr[pk].get(part, 0.0) for pk in qpr), "data/bom.csv x data/demand_forecast.csv", 1e-6)
            self.check("parts", f"{part}: needed over twelve months", sum(float(r.qty.value) for r in reqs), self._need12(part), "data/bom.csv x data/demand_forecast.csv", 1e-6)
            supply = orders.open_supply(self.session, part)
            live = self.live[self.live.pn == part]
            self.check("parts", f"{part}: on open orders (live lines)", sum(float(l.qty.ea if l.qty.ea is not None else l.qty.value) for l in supply if not l.stale), float(live.open_qty.sum()), self.src(live), 1e-6)
        # the last price paid is the price of the PO line the app cites (the newest line that is not an outlier): recompute that line's dollars from its raw row
        for r in self.session.scalars(select(ReferencePrice)):
            pn, ln = r.po_line_id.rsplit("/", 1)
            line = self.po[(self.po.po_number == pn.replace("HPO", "HPO") if pn.startswith("HPO") else self.po.po_number == pn) & (self.po.line == ln)]
            if len(line):
                row = line.iloc[0]
                self.check("parts", f"{r.part_number}: last paid (USD each) on {r.po_line_id}", float(r.usd_each), float(row.usd_each), f"data/purchase_orders.csv row {row.csv_row}", 5e-4)

    def run(self) -> list[Row]:
        for part in (self.parts_and_forecast, self.trust_items, self.dates, self.stakes, self.unknown_rows, self.orders_total, self.counts, self.supplier_totals, self.tariff_and_chase, self.fire_and_slips, self.supplier_risk, self.email_deadlines, self.readiness, self.offers):
            part()
        return self.rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="evals.number_sweep")
    ap.add_argument("--db", type=Path, default=ROOT / "backend" / "lookout.db")
    ap.add_argument("--data", type=Path, default=ROOT / "data")
    ap.add_argument("--all", action="store_true", help="print the agreeing figures too")
    a = ap.parse_args(argv)
    sys.path.insert(0, str(ROOT / "backend"))
    rows = Sweep(a.db, a.data).run()
    bad = [r for r in rows if not r.ok]
    for r in rows if a.all else bad:
        print(f"{'ok  ' if r.ok else 'DIFF'} [{r.group}] {r.name}: shown {r.shown} / recomputed {r.recomputed}   ({r.source})")
    print(f"{len(rows)} figures, {len(bad)} mismatches")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
