"""The data build: every raw row accounted for, nothing lost, every defect named with a count."""
import json
from pathlib import Path

from app.domain.imports import build

BACKEND = Path(__file__).resolve().parents[2]
RECIPE = BACKEND.parent / "recipes" / "halden"

FACTS = {  # FINDINGS.md section B and research/05, reproduced from the raw files
    "raw_suppliers": 71, "raw_parts": 502, "raw_bom": 359, "raw_purchase_orders": 2622, "raw_demand_forecast": 36,
}


def test_gate_all_pass(con):
    rows = con.execute('select "check" as name, passed from load_gate').fetchall()
    assert len(rows) >= 30 and all(r["passed"] == 1 for r in rows), [r["name"] for r in rows if not r["passed"]]


def test_raw_tables_hold_every_source_row(con):
    for table, n in FACTS.items():
        assert con.execute(f"select count(*) c from {table}").fetchone()["c"] == n


def test_counts_after_cleaning(con):
    c = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
    assert c("select count(*) from supplier_records") == 71
    assert c("select count(*) from supplier_identities") == 60
    assert c("select count(*) from parts") == 502
    assert c("select count(*) from po_lines") == 2616          # 6 exact duplicates dropped, each in row_drops
    assert c("select count(*) from bom_lines") == 358          # 1 exact duplicate (HR-15109) dropped
    assert c("select count(*) from row_drops") == 7
    assert c("select count(*) from po_lines where status in ('OPEN','PARTIAL')") == 185
    assert c("select count(*) from message_events where kind='force_majeure' and ref_type='po_line'") == 10


def test_identities_link_not_merge(con):
    rows = con.execute("select record_id from supplier_records where identity_id='SUP-0001'").fetchall()
    assert {r[0] for r in rows} == {"SUP-0001", "V10233", "V10871"}      # Yunzhan: three records, one company
    assert con.execute("select identity_id from supplier_records where record_id='SUP-0061'").fetchone()[0] == "SUP-0016"  # BCX = Baycrest
    ids = {r[0] for r in con.execute("select identity_id from supplier_records where record_id in ('SUP-0036','SUP-0037')")}
    assert ids == {"SUP-0036", "SUP-0037"}                                # Corvell US and TW stay two companies


def test_raw_beside_clean(con):
    r = con.execute("select coo, coo_raw, hts, hts_raw, hts_method from parts where part_number='HR-51120'").fetchone()
    assert (r["coo"], r["hts"], r["hts_raw"], r["hts_method"]) == ("CN", "8504409580", "85O4.40.9580", "flagged")
    r = con.execute("select currency, currency_raw, currency_method from po_lines where currency_method='inferred' limit 1").fetchone()
    assert r["currency_raw"] == "" and r["currency"]
    assert con.execute("select count(*) from po_lines where currency_method='inferred'").fetchone()[0] == 9


def test_unknowns_stay_unknown(con):
    assert con.execute("select count(*) from parts where coo is null and kind='purchased'").fetchone()[0] == 22
    assert con.execute("select count(*) from parts where kind='purchased' and hts is null").fetchone()[0] == 23


def test_every_issue_has_count_handling_consequence_owner(con):
    issues = con.execute("select * from data_issues").fetchall()
    assert len(issues) >= 40
    for i in issues:
        assert i["count"] > 0 and i["handling"] and i["consequence"] and i["example"] and i["owner"] and i["step"]
        assert not i["owner"].startswith("@"), i["key"]
    assert con.execute("select count(distinct key) from data_issues").fetchone()[0] == len(issues)


def test_known_defects_found(con):
    d = {r["key"]: r["count"] for r in con.execute("select key, count from data_issues")}
    assert d["po.exact_duplicate_rows"] == 6
    assert d["po.returns"] == 3
    assert d["po.short_closed"] == 78
    assert d["po.currency_blank"] == 9
    assert d["po.no_promise_date"] == 5
    assert d["po.stale_open"] == 3
    assert d["po.legacy_id_in_new_po"] == 6
    assert d["parts.duplicate_parts"] == 3
    assert d["parts.hts_letter_o"] == 1
    assert d["parts.coo_blank"] == 22
    assert d["bom.orphan_child"] == 1 and d["bom.unit_mismatch"] == 1 and d["bom.exact_duplicate_rows"] == 1
    assert d["bom.obsolete_child"] == 2 and d["bom.second_placement"] == 2
    assert d["suppliers.duplicate_records"] == 11
    assert d["suppliers.lookalike_names"] == 1


def test_rebuild_is_idempotent(tmp_path, db_path):
    import sqlite3

    from app.domain.imports.build import main
    from tests.domain.conftest import ROOT

    second = tmp_path / "again.db"
    assert main(["--recipe", str(ROOT / "recipes" / "halden"), "--data", str(ROOT / "data"), "--db", str(second)]) == 0

    owned = {t for (t,) in sqlite3.connect(second).execute("select name from sqlite_master where type='table'")}      # what the recipe builds; the ledger and the runs are not its

    def dump(p):
        c = sqlite3.connect(p)
        out = {}
        for (t,) in c.execute("select name from sqlite_master where type='table' and name not in ('build_meta','build_steps')"):
            if t not in owned:
                continue
            out[t] = c.execute(f"select * from {t} order by 1,2").fetchall()
        return out

    assert dump(db_path) == dump(second)


def test_trust_is_computed_before_any_model(con):
    t = {r["id"][:10] + r["id"][10:30]: (r["trust"], r["trust_flags"]) for r in con.execute("select id, trust, trust_flags from messages")}
    fraud = next(v for k, v in t.items() if "URGENT" in k)
    assert fraud[0] == "blocked" and {"sender_domain_lookalike", "reply_to_freemail", "bank_detail_change"} <= set(fraud[1].split(","))
    spot = next(v for k, v in t.items() if "Spot_offer" in k)
    assert spot[0] == "blocked" and "instruction_in_message" in spot[1] and "supplier_on_hold" in spot[1]
    vinh = next(v for k, v in t.items() if "VPM" in k or "Quotation_VPM" in k)
    assert vinh[0] == "review" and "sender_not_in_master" in vinh[1]
    assert sum(1 for v in t.values() if v[0] == "blocked") == 2


def test_a_rebuild_keeps_the_ledger_and_the_links_people_made(tmp_path):
    """The records come from the sources; approvals, the outbox, supplier links and runs are decisions and sends. A rebuild must not erase them."""
    import sqlite3
    import subprocess
    import sys

    from app.domain.actions import ledger

    db = tmp_path / "lookout.db"
    cmd = [sys.executable, "-m", "app.domain.imports.build", "--recipe", str(RECIPE), "--db", str(db)]
    for _ in range(2):
        done = subprocess.run(cmd, cwd=BACKEND, capture_output=True, text=True)
        assert done.returncode == 0, done.stdout[-400:] + done.stderr[-400:]
        if _ == 0:
            con = ledger.connect(db)
            con.execute("INSERT INTO supplier_links (supplier_a, supplier_b, action_id, linked_by, linked_at, evidence) VALUES ('SUP-A', 'SUP-B', 'A-test', 'a buyer', '2026-10-11', 'x')")
            con.close()
    con = sqlite3.connect(db)
    assert con.execute("select count(*) from supplier_links").fetchone()[0] == 1
    assert con.execute("select count(*) from po_lines").fetchone()[0] > 2000     # and the records are the fresh build


def test_a_link_a_person_approved_folds_two_identities_and_merges_no_record(tmp_path):
    import sqlite3
    import subprocess
    import sys

    from app.domain.actions import ledger

    db = tmp_path / "lookout.db"
    cmd = [sys.executable, "-m", "app.domain.imports.build", "--recipe", str(RECIPE), "--db", str(db)]
    assert subprocess.run(cmd, cwd=BACKEND, capture_output=True, text=True).returncode == 0
    con = sqlite3.connect(db)
    a, b = [r[0] for r in con.execute("select id from supplier_identities where id like 'SUP-%' order by id limit 2")]
    n_ident, n_rec = (con.execute(f"select count(*) from {t}").fetchone()[0] for t in ("supplier_identities", "supplier_records"))
    con.close()
    led = ledger.connect(db)
    led.execute("INSERT INTO supplier_links (supplier_a, supplier_b, action_id, linked_by, linked_at, evidence) VALUES (?, ?, 'A-test', 'a buyer', '2026-10-11', 'one company')", (a, b))
    led.close()
    done = subprocess.run(cmd, cwd=BACKEND, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout[-400:] + done.stderr[-400:]
    con = sqlite3.connect(db)
    assert con.execute("select count(*) from supplier_identities").fetchone()[0] == n_ident - 1
    assert con.execute("select count(*) from supplier_records").fetchone()[0] == n_rec                        # linked, never merged
    assert con.execute("select identity_id, identity_method, identity_evidence from supplier_records where record_id = ?", (b,)).fetchone() == (
        a, "stated", "approved by a buyer (action A-test): one company")
    assert con.execute("select count(*) from po_lines where identity_id = ?", (b,)).fetchone()[0] == 0        # its orders now count under the one company
