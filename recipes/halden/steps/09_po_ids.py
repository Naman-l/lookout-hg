"""Normalise PO line identity: PO number, part number, supplier record, buyer, system.

Defect: the file mixes two ERPs. The legacy one writes PO-10412 with part numbers without the hyphen (HR51110) and
buyer initials; the new one writes HPO-26-00450 with HR-51110 and full names. 20 part numbers carry stray spaces,
lower case or a letter O for zero. 121 lines are still on legacy V- supplier ids, 6 of them inside new-system POs.
Rule: part number -> HR-NNNNN (upper case, hyphen, O -> 0); id = "<po>/<line>"; the supplier record is resolved to its
identity through the alias links (the line keeps the id it was placed on); buyer -> one id. Anything that does not
resolve stops the build or is counted.
Consequence if ignored: 590 legacy lines never join the item master; spend with Yunzhan splits across three ids.
"""
import pandas as pd

from app.domain.imports.context import examples
from app.domain.imports.helpers import add_flag, norm_part_number


def run(ctx):
    po = ctx.t["po_lines"]
    parts = ctx.t["parts"].set_index("part_number")
    rec = ctx.t["supplier_records"].set_index("record_id")
    buyers = ctx.t["buyers"]
    bmap = {}
    for b in buyers.itertuples():
        bmap[b.name], bmap[b.initials] = b.id, b.id

    df = pd.DataFrame({"src_row": po.src_row})
    df["po_number"] = po.po_number.str.strip()
    df["line"] = po.line.astype(int)
    df["id"] = df.po_number + "/" + df.line.astype(str)
    n = df.groupby("id").cumcount()                       # a repeat the person chose to keep gets its own id
    df["id"] = df.id + n.map(lambda k: f"#{k + 1}" if k else "")
    df["system"] = df.po_number.map(lambda n: "new" if n.startswith("HPO") else "legacy")
    df["part_raw"] = po.part_number
    df["part_number"] = po.part_number.map(norm_part_number)
    df["record_id"] = po.supplier_id.str.strip()
    df["buyer_raw"] = po.buyer
    df["buyer_id"] = po.buyer.map(bmap)
    for c in ["qty", "uom", "unit_price", "currency", "order_date", "promised_date", "received_date"]:
        df[c + "_raw" if c != "qty" else "qty_raw"] = po[c]
    df["qty_received_raw"] = po.qty_received
    df["status"] = po.status
    assert df.buyer_id.notna().all(), df[df.buyer_id.isna()].buyer_raw.unique()
    df["identity_id"] = df.record_id.map(rec.identity_id)
    df["flags"] = ""
    add_flag(df, n > 0, "export_duplicate")
    ctx.t["po_lines"] = df

    unresolved_part = df[~df.part_number.isin(parts.index)]
    ctx.issue("po.part_unresolved", "purchase_orders.csv", "PO part number not in the item master after normalising", len(unresolved_part), "flag",
              "Kept and flagged.", "Spend that cannot be attributed to a part.", examples(unresolved_part.part_raw), "ERP admin")
    unresolved_sup = df[df.identity_id.isna()]
    ctx.issue("po.supplier_unresolved", "purchase_orders.csv", "PO supplier id not in the supplier master", len(unresolved_sup), "flag",
              "Kept and flagged.", "Spend that cannot be attributed to a supplier.", examples(unresolved_sup.record_id), "ERP admin")
    legacy_fmt = df[(df.system == "legacy")]
    ctx.issue("po.legacy_part_format", "purchase_orders.csv", "Legacy ERP lines write part numbers without the hyphen (HR51110)",
              len(legacy_fmt), "fix", "Normalise to HR-NNNNN; the raw text is kept in part_raw.",
              "Every legacy line fails to join the item master and its history is lost.", examples(legacy_fmt.part_raw), "ERP admin")
    stray = df[(df.system == "new") & (df.part_raw != df.part_number)]
    ctx.issue("po.part_number_noise", "purchase_orders.csv", "Part numbers with stray spaces, lower case or the letter O for zero (new ERP)",
              len(stray), "fix", "Upper case, strip, O -> 0 inside the digit block; raw kept.",
              "These lines silently drop out of any join on part number (20 parts in all, every one resolves).",
              examples(stray.part_raw + " -> " + stray.part_number), "ERP admin")
    legacy_id = df[df.record_id.str.startswith("V")]
    add_flag(df, df.record_id.str.startswith("V") & (df.system == "new"), "legacy_id_in_new_po")
    ctx.issue("po.legacy_supplier_ids", "purchase_orders.csv", "Lines placed on legacy V- supplier ids (some inside new-system POs)",
              len(legacy_id), "link", "Keep the id the line was placed on; resolve it to the supplier identity.",
              "A company's open lines sit on several ids; a per-id view understates its exposure.",
              examples(legacy_id.record_id + " -> " + legacy_id.identity_id), "@suppliers:" + ",".join(sorted(set(legacy_id.identity_id.dropna()))))
    new_with_legacy = legacy_id[legacy_id.system == "new"]
    ctx.issue("po.legacy_id_in_new_po", "purchase_orders.csv", "A new-system PO placed on a legacy supplier id", len(new_with_legacy), "flag",
              "Kept; the line is flagged legacy_id_in_new_po.", "The migration did not re-key everything.",
              examples(new_with_legacy.id + " on " + new_with_legacy.record_id), "@suppliers:" + ",".join(sorted(set(new_with_legacy.identity_id.dropna()))))
    ini = df[df.buyer_raw.isin(buyers.initials)]
    ctx.issue("po.buyer_initials", "purchase_orders.csv", "Buyer written as initials (TA, PN, MC, DR, SM) in the legacy ERP", len(ini), "fix",
              "Map initials and full names to one buyer id; raw kept in buyer_raw.", "Filtering by buyer returns half the lines.",
              examples(ini.buyer_raw.unique()), "ERP admin")
