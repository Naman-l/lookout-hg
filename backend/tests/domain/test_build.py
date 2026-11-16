"""The data build: every raw row accounted for, nothing lost, every defect named with a count, the same database from the same files."""

import csv
import sqlite3

from app.domain.imports import build
from tests.domain.conftest import DATA, RECIPE

# raw table -> (file, lines above the first data row): the stamp line and the header of a SAP export, a sheet's title rows. A grid sheet keeps every line.
RAW = {
    "raw_me5a": ("sap/ME5A_purchase_requisitions.csv", 2), "raw_me2n": ("sap/ME2N_purchase_orders.csv", 2), "raw_mb51": ("sap/MB51_goods_receipts.csv", 2),
    "raw_fbl1n": ("sap/FBL1N_vendor_line_items.csv", 2), "raw_vendor_master": ("sap/vendor_master.csv", 2), "raw_material_master": ("sap/material_master.csv", 2),
    "raw_purchasing_groups": ("sap/purchasing_groups.csv", 2), "raw_project_directory": ("sheets/Project Directory.csv", 1),
    "raw_cs_tracker": ("sheets/RFQ CS Tracker (19.10.26).csv", 1), "raw_expediting": ("sheets/Expediting Tracker (17.10.26).csv", 1),
    "raw_lc_bg": ("sheets/LC BG Tracker (16.10.26).csv", 1), "raw_vendor_library": ("sheets/Vendor Library (03.10.26).csv", 1),
    "raw_roads_req": ("sheets/Roads Major Material Requirement Oct-Dec 26 (14.10.26).csv", 0), "raw_railway_req": ("sheets/Railway Material Quantity Summary Q3 (15.10.26).csv", 0),
    "raw_fund_2026_10": ("sheets/SCM Fund Requirement October-26 (18.09.26).csv", 0), "raw_fund_2026_11": ("sheets/SCM Fund Requirement November-26 (16.10.26).csv", 0),
    "raw_fund_2026_12": ("sheets/SCM Fund Requirement December-26 (16.10.26).csv", 0), "raw_budget_rates": ("sheets/budget_rates.csv", 1), "raw_doa": ("sheets/doa.csv", 1),
}


def _data_rows(rel: str, above: int) -> int:
    with (DATA / rel).open(newline="", encoding="utf-8") as f:
        return sum(1 for _ in csv.reader(f)) - above


def test_the_gate_passes_every_check(con):
    rows = con.execute('select "check" as name, passed, detail from load_gate').fetchall()
    assert len(rows) >= 70 and all(r["passed"] == 1 for r in rows), [(r["name"], r["detail"]) for r in rows if not r["passed"]]


def test_raw_tables_hold_every_source_row(one):
    for table, (rel, above) in RAW.items():
        assert one(f"select count(*) from {table}") == _data_rows(rel, above), table


def test_every_raw_row_is_kept_once_or_dropped_once_with_a_reason(one):
    assert one("select count(*) from po_lines") == one("select count(*) from raw_me2n")
    assert one("select count(*) from pr_lines") == one("select count(*) from raw_me5a")
    assert one("select count(*) from receipts") + one("select count(*) from row_drops where raw_table = 'raw_mb51'") == one("select count(*) from raw_mb51")
    assert one("select count(*) from row_drops where reason is null or reason = ''") == 0


def test_every_issue_has_a_count_a_rule_a_consequence_an_example_and_a_person(con):
    issues = con.execute("select * from data_issues").fetchall()
    assert len(issues) >= 20 and con.execute("select count(distinct key) from data_issues").fetchone()[0] == len(issues)
    people = {r[0] for r in con.execute("select name from buyers")} | {r[0] for r in con.execute("select name from contacts")}
    for i in issues:
        assert i["count"] > 0 and i["handling"] in {"fix", "infer", "flag", "link", "leave", "drop"} and i["rule"] and i["consequence"] and i["example"] and i["step"], i["key"]
        assert not i["owner"].startswith("@") and (i["owner"] in people or i["owner"].startswith(("IT", "Projects"))), (i["key"], i["owner"])


def test_raw_values_are_kept_beside_the_clean_ones(one, con):
    r = con.execute("select qty, qty_raw, net_price, net_price_raw, doc_date, doc_date_raw from po_lines where id = (select min(id) from po_lines)").fetchone()
    assert r["qty_raw"] and r["net_price_raw"] and r["doc_date_raw"].count(".") == 2 and r["doc_date"].count("-") == 2
    assert one("select count(*) from fund_lines where amount_raw is null or amount_raw = ''") == 0


def test_vendors_are_linked_not_merged(one):
    assert one("select count(*) from supplier_records") == one("select count(*) from raw_vendor_master")
    assert one("select count(*) from supplier_identities") == one("select count(*) from supplier_records") - one("select count(*) from data_issues where key = 'vendors.two_codes'")


def test_every_figure_a_sheet_prints_is_recomputed_from_its_cells(one):
    assert one("select count(*) from sheet_totals where printed is not null") > 100
    assert one("select count(*) from sheet_totals where printed is not null and abs(printed - computed) > tolerance") == 0


def test_the_build_records_its_recipe_its_data_and_the_company(con):
    meta = {r["key"]: r["value"] for r in con.execute("select key, value from build_meta")}
    assert meta["as_of"] == "2026-10-20" and meta["base_currency"] == "INR" and meta["recipe"].split(" ")[0] == "hg" and meta["recipe_hash"] and meta["data_hashes"]


def test_a_rebuild_from_the_same_files_is_the_same_database(tmp_path, db_path):
    second = tmp_path / "again.db"
    assert build.main(["--recipe", str(RECIPE), "--data", str(DATA), "--db", str(second)]) == 0

    def dump(p):
        c = sqlite3.connect(p)
        tables = [t for (t,) in c.execute("select name from sqlite_master where type='table' and name not in ('build_meta', 'build_steps') order by name")]
        return {t: c.execute(f"select * from {t} order by 1, 2").fetchall() for t in tables}

    assert dump(db_path) == dump(second)
