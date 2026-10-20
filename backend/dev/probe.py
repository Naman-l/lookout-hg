"""Developer tool, not part of the app: one function that reads a built database and returns the headline numbers, for the no-model eval cases.

`python backend/dev/probe.py [db]` prints them. The eval answer sheets compare against these keys by name; the part numbers below are Halden's
because the numbers they measure are Halden's. Nothing the app runs imports this file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.domain.common import AS_OF
from app.domain.attention import service as attention
from app.domain.demand import service as demand
from app.domain.news.model import NewsItem
from app.domain.orders import service as orders
from app.domain.quotes.model import Offer
from app.domain.suppliers.model import SupplierRecord
from app.domain.tariffs import service as tariffs


def measure(db_path: str | Path) -> dict:
    eng = create_engine(f"sqlite:///{db_path}", future=True)
    with Session(eng) as s:
        raw = s.connection().exec_driver_sql("select count(*) from raw_purchase_orders").scalar()
        dropped = s.connection().exec_driver_sql("select count(*) from row_drops where raw_table='raw_purchase_orders'").scalar()
        open_lines = orders.open_supply(s)
        pd_all = orders.past_due(s, include_stale=True)
        pd_live = orders.past_due(s)
        fm = [l for l in open_lines if l.disrupted_by]
        exps = tariffs.all_exposures(s)
        t = {1: [0.0, 0.0, 0.0], 2: [0.0, 0.0, 0.0]}   # owed, gross, conditional
        unk = [0.0, 0.0]
        facts: dict[str, float] = {}
        for e in exps:
            if e.status == "china_listed":
                tr = e.tariff.rule.tranche
                t[tr][0] += float(e.net.usd)
                t[tr][1] += float(e.gross.usd)
                t[tr][2] += float(e.conditional.usd) if e.conditional else 0.0
                if tr == 1 and e.part.id in ("HR-50110", "HR-50210", "HR-40110", "HR-40210"):
                    facts[f"tariff_t1_net_usd:{e.part.id}"] = float(e.net.usd)
            elif e.status == "unknown_origin":
                unk[0] += float(e.net.usd)
                unk[1] += float(e.gross.usd)
        hr = tariffs.exposure_for_part(s, "HR-40110")
        facts.update({
            "tariff_t1_net_usd": t[1][0], "tariff_t1_gross_usd": t[1][1],
            "tariff_t2_net_usd": t[2][0], "tariff_t2_gross_usd": t[2][1],
            "tariff_t1_owed_usd": t[1][0], "tariff_t1_conditional_usd": t[1][2], "tariff_t2_owed_usd": t[2][0], "tariff_t2_conditional_usd": t[2][2],
            "unknown_origin_if_china_usd": unk[0],
            "unknown_origin_net_usd": unk[0], "unknown_origin_gross_usd": unk[1],
            "tariff_t2_pass_through_gross_usd": sum(float(e.pass_through.usd) for e in exps if e.status == "china_listed" and e.tariff.rule.tranche == 2 and e.pass_through),
            "open_po_duty_usd:HR-40110": sum(float(l.open_value.usd) for l in hr.open_lines) * hr.rate,
        })
        counts = {
            "po_rows_raw": raw,
            "po_exact_duplicate_rows_dropped": dropped,
            "po_lines_open_or_partial": len(open_lines),
            "po_lines_past_due_raw": len(pd_all),
            "po_lines_stale_unknown": sorted(l.po_line.id.replace("-", "-") for l in pd_all if l.stale),
            "po_lines_past_due": len(pd_live),
            "force_majeure_open_qty": int(sum(float(l.qty.value) for l in fm)),
            "force_majeure_hr40110_open_qty": int(sum(float(l.qty.value) for l in fm if l.part.id == "HR-40110")),
            "unknown_origin_on_listed_codes": sorted(e.part.id for e in exps if e.status == "unknown_origin"),
            "as_of": AS_OF.isoformat(),
            "force_majeure_lines_matched": len(fm),
            "force_majeure_lines_supplier": next(iter({l.supplier.id for l in fm}), None) if len({l.supplier.id for l in fm}) == 1 else sorted({l.supplier.id for l in fm}),
            "unknown_hts_china_origin_tariff_category": sorted(e.part.id for e in exps if e.status == "unknown_hts"),
            "yunzhan_supplier_records": sorted(r.record_id for r in s.scalars(select(SupplierRecord).where(SupplierRecord.identity_id == "SUP-0001"))),
        }
        news = list(s.scalars(select(NewsItem)))
        news_matches = {
            "must_match": {n.id: n.identity_id for n in news if n.match_kind == "supplier"},
            "must_not_match": sorted(n.id for n in news if n.match_kind == "other_company"),  # shares a name with a supplier, is another company
            "place_not_company": sorted(n.id for n in news if n.match_kind == "place"),
        }
        parts_with_supply = sorted({l.part.id for l in open_lines if not l.stale})
        raised = sorted(p for p in parts_with_supply if demand.shortage(s, p).first_short_month)
        shortage = {
            "raised_only_for_disrupted_parts": raised,
            "not_raised_for": sorted(set(parts_with_supply) - set(raised)),  # every part with open supply and no disruption: nothing raised
        }
        live = [o for o in s.scalars(select(Offer).where(Offer.part_number == "HR-31110", Offer.qty_break == 2500, Offer.superseded_by.is_(None)))]
        quotes = {"alderpoint_hr31110_2500yr_unit_usd": live[0].price if live else None, "alderpoint_hr31110_offers_at_2500yr": len(live)}
        bcx = [tariffs.duty_for_line(s, i) for i in ("HPO-26-00591/40", "HPO-26-00490/50")]
        tariff = {"bcx_ddp_lines_halden_duty_usd": 0 if all(d.importer == "supplier" for d in bcx) else sum(float(d.duty.usd) for d in bcx if d.duty),
                  "bcx_ddp_lines_labelled": next(iter({d.status for d in bcx}), None) if len({d.status for d in bcx}) == 1 else "mixed"}
        items = {"present": attention.all_keys(s)}
    return {"counts": counts, "facts": facts, "news_matches": news_matches, "shortage": shortage, "quotes": quotes, "tariff": tariff, "items": items}


if __name__ == "__main__":
    from app.db import DB_PATH

    print(json.dumps(measure(sys.argv[1] if len(sys.argv) > 1 else DB_PATH), indent=2, default=str))
