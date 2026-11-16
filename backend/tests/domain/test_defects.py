"""One test per defect planted in the dummy data: each is found, counted once, and handled as its step says.

Where a count can be recomputed from the raw rows without the recipe's code, it is, so the test does not just read the step's own number back.
"""

import email
import re
from email import policy

import yaml

from tests.domain.conftest import DATA, RECIPE

ANSWERS = yaml.safe_load((RECIPE / "answers.yaml").read_text())


def _cells(con, table):
    cols = [r[1] for r in con.execute(f"pragma table_info({table})") if r[1].startswith("c")]
    return [str(v) for row in con.execute(f"select {', '.join(cols)} from {table}") for v in row if v is not None]


# 1. the same project under different names
def test_project_name_variants_are_linked_and_names_nobody_can_place_are_left(issues, con):
    by = dict(con.execute("select method, count(*) from project_aliases group by method").fetchall())
    assert issues["projects.name_variants"]["count"] == by["answer"] == 22 and issues["projects.name_variants"]["handling"] == "link"
    assert con.execute("select project_ids from project_aliases where alias = 'KD-01 & KD-02'").fetchone()[0] == "kd-01,kd-02"      # one column, two projects
    assert issues["projects.unresolved_names"]["count"] == by["unresolved"] == 6 and issues["projects.unresolved_names"]["handling"] == "leave"
    assert con.execute("select count(*) from project_aliases where method = 'unresolved' and project_ids is not null and project_ids != ''").fetchone()[0] == 0


# 2. rupees, lakh and crore in one sheet
def test_fund_and_projection_amounts_written_in_lakh_or_crore_are_read_in_rupees(issues, con):
    got = {r["amount_raw"]: (r["amount"], r["unit_raw"]) for r in con.execute("select amount_raw, amount, unit_raw from fund_lines where flags like '%unit%'")}
    assert got == {"45 L": (4_500_000, "lakh"), "23,50,000": (2_350_000, "rupee"), "1.5 L": (150_000, "lakh")} and issues["fund.mixed_units"]["count"] == 3
    proj = {r[0]: r[1] for r in con.execute("select rtgs_raw, rtgs from payment_projection where rtgs_raw like '% Cr' or rtgs_raw like '% L'")}
    assert proj == {"2.64 Cr": 26_400_000, "45 L": 4_500_000} and issues["projection.mixed_units"]["count"] == 2


# 3. cement in bags and tonnes
def test_cement_bought_by_the_bag_is_counted_in_tonnes(issues, con):
    per = ANSWERS["cement"]["bags_per_mt"]
    bags = con.execute("select qty, qty_base, net_price, price_unit, rate_base from po_lines where uom = 'BAG'").fetchall()
    assert bags and all(abs(r["qty_base"] - r["qty"] / per) < 1e-6 and abs(r["rate_base"] - r["net_price"] / r["price_unit"] * per) < 1e-6 for r in bags)
    pr_bags = con.execute("select count(*) from pr_lines where uom = 'BAG'").fetchone()[0]
    assert issues["po.cement_bags_and_tonnes"]["count"] == len(bags) + pr_bags == 59


# 4. one company under two vendor codes
def test_a_renamed_vendor_keeps_both_codes_under_one_company(issues, con):
    recs = con.execute("select record_id, identity_id, identity_method from supplier_records where identity_id in "
                       "(select identity_id from supplier_records group by identity_id having count(*) > 1)").fetchall()
    assert len(recs) == 2 and len({r["identity_id"] for r in recs}) == 1 and issues["vendors.two_codes"]["count"] == 1
    assert {r["identity_method"] for r in recs} == {"stated", "answer"}      # the second code is joined by a person's answer, not by a guess on the name


# 5. PRs that name no project
def test_head_office_prs_with_no_tracking_number_stay_without_a_project(issues, con):
    rows = con.execute("select plant, tracking_no from pr_lines where project_id is null or project_id = ''").fetchall()
    assert len(rows) == issues["prs.no_project"]["count"] == 14 and {r["plant"] for r in rows} == {ANSWERS["ho_plant"]["plant"]}
    assert all(not (r["tracking_no"] or "").strip() for r in rows) and issues["prs.no_project"]["handling"] == "leave"


# 6. POs with no PR
def test_orders_placed_without_a_requisition_are_flagged(issues, one):
    raw = one("select count(*) from raw_me2n where trim(\"Purchase Requisition\") = ''")
    assert raw == issues["po.no_pr"]["count"] == one("select count(*) from po_lines where flags like '%no_pr%'") == 25


# 7. PRs keyed in on the day of the order
def test_requisitions_created_the_day_their_order_was_placed_are_flagged(issues, one):
    same = one("select count(*) from pr_lines p join po_lines o on o.id = p.po_line_id where p.created = o.doc_date")
    assert same == issues["prs.same_day_po"]["count"] == one("select count(*) from pr_lines where flags like '%same_day_po%'") == 39


# 8. a turnaround of zero that means "none closed"
def test_a_zero_turnaround_with_nothing_closed_is_no_turnaround(issues, con):
    rows = con.execute("select closed, avg_tat, avg_tat_raw from tat_report where avg_tat is null").fetchall()
    assert len(rows) == issues["tat.zero_means_none"]["count"] == 6 and all(r["closed"] == 0 and r["avg_tat_raw"].strip() == "0" for r in rows)


# 9. the MB51 export appended twice
def test_exact_repeat_rows_in_the_receipts_export_are_dropped_with_a_reason(issues, con):
    cols = [r[1] for r in con.execute("pragma table_info(raw_mb51)") if r[1] != "src_row"]
    quoted = ", ".join(f'"{c}"' for c in cols)
    repeats = con.execute(f"select coalesce(sum(n - 1), 0) from (select count(*) n from raw_mb51 group by {quoted})").fetchone()[0]
    drops = con.execute("select count(*) from row_drops where raw_table = 'raw_mb51'").fetchone()[0]
    assert repeats == drops == issues["mb51.duplicate_rows"]["count"] == 18 and issues["mb51.duplicate_rows"]["handling"] == "drop"


# 10. reversals and returns
def test_reversals_and_returns_net_off_what_was_received(issues, con):
    raw = con.execute("select count(*) from raw_mb51 where \"Movement Type\" in ('102', '122')").fetchone()[0]
    assert raw == issues["mb51.reversals"]["count"] == 88
    assert con.execute("select count(*) from (select po_line_id, sum(qty_base) s from receipts group by po_line_id) where s < -1e-6").fetchone()[0] == 0
    off = con.execute("select count(*) from po_lines o where abs(coalesce(o.received_base, 0) - coalesce((select sum(qty_base) from receipts r where r.po_line_id = o.id), 0)) > 1e-6")
    assert off.fetchone()[0] == 0      # what a PO line says was received is the net of its receipts


# 11. AAC blocks priced per thousand
def test_a_price_per_thousand_is_read_per_piece(issues, con):
    rows = con.execute("select qty, net_price, price_unit, rate_base, value from po_lines where price_unit_raw not in ('1', '')").fetchall()
    assert len(rows) == issues["po.price_per_1000"]["count"] == 16
    assert all(r["price_unit"] == 1000 and abs(r["rate_base"] - r["net_price"] / 1000) < 1e-9 and abs(r["value"] - r["qty"] * r["rate_base"]) < 0.01 for r in rows)


# 12. the fund sheet and the requirement sheet disagree
def test_fund_and_requirement_disagreements_are_the_planted_ones(issues, con):
    got = {(r[0], r[1]) for r in con.execute("select month, column_as_printed from fund_checks where disagrees = 1")}
    assert got == {("2026-10", "Pune-Shirur"), ("2026-10", "Tirupati"), ("2026-11", "Ahmedabad"), ("2026-11", "Arurangabad"), ("2026-11", "Gaya"),
                   ("2026-11", "JH-13"), ("2026-11", "Pune-Shirur"), ("2026-12", "Pune-Shirur")}
    assert issues["fund.disagrees_with_requirement"]["count"] == len(got)
    rule = ANSWERS["fund_check"]
    for r in con.execute("select requirement, fund, difference from fund_checks where disagrees = 1 and requirement is not null"):
        assert abs(r["difference"]) >= rule["min_difference_inr"] and abs(r["difference"]) >= rule["min_share"] * r["requirement"]


# 13. sources older than a week
def test_sources_older_than_the_stale_limit_are_raised(issues, con):
    stale = {(r["key"], r["stamped_at"][:10]) for r in con.execute("select key, stamped_at from sources where stale = 1")}
    assert stale == {("fund", "2026-09-18"), ("vendor_library", "2026-10-03"), ("tat_report", "2026-10-03")} and issues["sources.stale"]["count"] == 3
    assert con.execute("select count(*) from sources where judged = 1 and age_days > ? and stale = 0", (ANSWERS["stale_after_days"],)).fetchone()[0] == 0
    assert con.execute("select count(*) from sources where judged = 0 and stale = 1").fetchone()[0] == 0      # a reference table (the purchasing groups) is not judged by age


# 14. projects won after the last plant was created in SAP
def test_projects_with_no_sap_plant_are_kept_with_no_sap_records(issues, con):
    blank = [r[0] for r in con.execute("select Project from raw_project_directory where trim(Plant) = ''")]
    assert sorted(blank) == ["BESS Chorniya", "Jamshedpur 400 kV", "Pune-Shirur", "UPPTCL Mirzapur-Chunar"]
    assert issues["projects.no_sap_plant"]["count"] == len(blank) and issues["projects.no_sap_plant"]["handling"] == "leave"
    ids = [r[0] for r in con.execute("select id from projects where id not in (select project_id from project_plants where project_id is not null)")]
    assert len(ids) == len(blank)
    for table in ("pr_lines", "po_lines", "receipts"):
        assert con.execute(f"select count(*) from {table} where project_id in ({','.join('?' * len(ids))})", ids).fetchone()[0] == 0
    # every receipt's plant name is the one its project's plant carries
    assert con.execute("select count(*) from receipts r join project_plants p on p.plant = r.plant where r.plant_name != p.name").fetchone()[0] == 0


# and what the sheets and mails bring with them
def test_spreadsheet_errors_in_the_requirement_sheets_are_counted_and_left_blank(issues, con):
    errors = sum(1 for t in ("raw_roads_req", "raw_railway_req") for v in _cells(con, t) if v.strip().startswith("#"))
    assert errors == issues["requirements.sheet_errors"]["count"] == 21
    assert con.execute("select count(*) from requirement_lines where qty_raw like '#%' and qty is not null").fetchone()[0] == 0


def test_rfqs_sent_before_their_pr_existed_are_flagged(issues, one):
    early = one("select count(distinct q.pr_line_id) from quotes q join pr_lines p on p.id = q.pr_line_id where q.rfq_sent < p.created")
    assert early == issues["cs.rfq_before_pr"]["count"] == 20


def test_library_vendors_with_no_sap_code_and_orders_placed_outside_the_library(issues, one):
    assert issues["library.not_in_sap"]["count"] == one("select count(*) from vendor_library where record_id is null or record_id = ''")
    assert issues["library.ordered_outside"]["count"] == one("select count(*) from po_lines where flags like '%not_in_library%'") == 10


def test_requirement_lines_with_no_budget_rate_are_left_unknown(issues):
    assert issues["budget.missing_rates"]["count"] == 7 and issues["budget.missing_rates"]["handling"] == "leave"


def test_a_tracked_po_missing_from_the_export_keeps_its_milestones(issues, one):
    assert issues["expediting.po_not_in_export"]["count"] == one("select count(*) from milestones where po_line_id is null or po_line_id = ''") == 1


def test_trust_is_computed_in_code_before_anyone_reads(issues, con):
    held = {r["sender_class"]: set(r["trust_flags"].split(",")) for r in con.execute("select sender_class, trust_flags from messages where trust = 'blocked'")}
    assert set(held) == {"lookalike_vendor", "lookalike_internal", "unknown"} and issues["inbox.held"]["count"] == 3
    assert {"sender_domain_lookalike", "reply_to_freemail", "bank_detail_change"} <= held["lookalike_vendor"]
    assert {"sender_domain_lookalike", "bank_detail_change"} <= held["lookalike_internal"] and "instruction_in_message" in held["unknown"]
    assert issues["inbox.unknown_senders"]["count"] == con.execute("select count(*) from messages where sender_class = 'unknown'").fetchone()[0] == 1


def test_quotes_only_in_mail_cite_the_line_they_were_read_from(issues, con):
    offers = [(doc["message"], o) for p in sorted((RECIPE / "extractions").glob("*.yaml")) for doc in [yaml.safe_load(p.read_text())] for o in doc["offers"]]
    assert len(offers) == issues["quotes.only_in_mail"]["count"] == con.execute("select count(*) from quotes where source = 'mail'").fetchone()[0] == 5
    for mid, o in offers:
        msg = email.message_from_bytes((DATA / "inbox" / f"{mid}.eml").read_bytes(), policy=policy.default)
        lines = msg.get_body(preferencelist=("plain",)).get_content().splitlines()
        assert o["raw"] in lines[int(o["line"][1:]) - 1], (mid, o["line"], o["raw"])
        row = con.execute("select rate, line_ref from quotes where message_id = ? and material = ? and rate = ?", (mid, o["material"], o["rate"])).fetchone()
        assert row is not None and row["line_ref"] == o["line"]


def test_facts_in_mail_prose_are_kept_with_the_line_they_came_from(issues, con):
    assert issues["inbox.facts_in_prose"]["count"] == con.execute("select count(*) from message_events").fetchone()[0] == 73
    for r in con.execute("select message_id, line_ref from message_events"):
        assert re.fullmatch(r"L\d+", r["line_ref"]), r["message_id"]
