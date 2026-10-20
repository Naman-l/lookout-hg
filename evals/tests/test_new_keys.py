"""Re-derive the PO-based keys of the limb answer sheets from the raw files (no app code)."""
from pathlib import Path

import pandas as pd
import pytest

from evals import run
from evals.oracle import COO, load

DATA = Path(run.ROOT) / "data"
CASES = run.load_cases()


@pytest.fixture(scope="module")
def po():
    return load(DATA)[0]


def fact(case, name, **match):
    return next(f for f in CASES[case]["expected"]["facts"]
                if f["name"] == name and all(f.get(k) == v for k, v in match.items()))


def line(po, number, ln):
    return po[(po.po_number == number) & (po.line == str(ln))].iloc[0]


def test_hr40110_open_lines_value_and_duty(po):
    rows = po[(po.pn == "HR-40110") & po.status.isin(["OPEN", "PARTIAL"]) & po.po_number.str.startswith("HPO")]
    value = (rows.open_qty * rows.usd_each).sum()
    assert rows.open_qty.sum() == 1140
    assert value == pytest.approx(fact("tariff-hr40110", "open_po_value_usd")["value"], rel=.001)
    assert value * .25 == pytest.approx(fact("tariff-hr40110", "open_po_duty_usd")["value"], rel=.001)


def test_hr50110_open_value_gross_and_exposed_duty(po):
    rows = po[(po.pn == "HR-50110") & (po.status == "OPEN")]
    value = (rows.open_qty * rows.usd_each).sum()
    assert value == pytest.approx(fact("tariff-hr50110", "open_po_value_usd")["value"], rel=.001)
    assert value * .25 == pytest.approx(fact("tariff-hr50110", "open_po_duty_usd_gross")["value"], rel=.001)
    late = rows[rows.promised_date_d >= pd.Timestamp("2026-11-01")]
    assert list(late.po_number) == ["HPO-26-00609"]
    assert (late.open_qty * late.usd_each).sum() * .25 == pytest.approx(fact("tariff-hr50110", "open_po_duty_usd_exposed")["value"], rel=.001)


def test_quenvara_landed_options():
    assert 1155.21 * 1.25 == pytest.approx(fact("tariff-hr50110", "landed_usd_each", option="huizhou")["value"], abs=.01)
    assert 1224.52 * 1.25 == pytest.approx(fact("tariff-hr50110", "landed_usd_each", option="penang_if_chinese_origin")["value"], abs=.01)
    assert pd.Timestamp("2026-09-21") + pd.Timedelta(days=45) == pd.Timestamp("2026-11-05")


def test_vinh_phuc_vs_yunzhan_landed():
    lp = CASES["tariff-hr40110"]["expected"]["alternative_origin"]["landed_vs_yunzhan_at_500"]
    assert 154.55 * 1.25 == pytest.approx(lp["yunzhan_with_duty"], abs=.01)
    assert 165.54 * 1.25 == pytest.approx(lp["vinh_phuc_if_china"], abs=.01)
    assert lp["vinh_phuc_if_vietnam"] < lp["yunzhan_with_duty"] < lp["vinh_phuc_if_china"]


def test_hallerbeck_arithmetic_and_exposure(po):
    net100, net250 = 100 * 389.50 * 1.035, 250 * 376.10 * 1.035
    assert net100 == pytest.approx(fact("quote-hallerbeck", "net_total_eur", qty=100)["value"], abs=.01)
    assert net250 == pytest.approx(fact("quote-hallerbeck", "net_total_eur", qty=250)["value"], abs=.01)
    assert net100 * .3 == pytest.approx(fact("quote-hallerbeck", "prepayment_eur")["value"], abs=.01)
    assert net100 * .3 * 1.18399 == pytest.approx(fact("quote-hallerbeck", "prepayment_usd")["value"], rel=.001)
    assert 389.50 / 315.53 - 1 == pytest.approx(.234, abs=.001)
    open_eur = sum(line(po, n, l).open_qty * float(line(po, n, l).unit_price) for n, l in [("HPO-26-00404", 10), ("HPO-26-00652", 10)])
    assert open_eur == pytest.approx(fact("quote-hallerbeck", "open_exposure_eur")["value"], rel=.001)


def test_bcx_unit_conversion_and_duty():
    e = CASES["quote-bcx"]["expected"]
    each = {f["part"]: f["value"] for f in e["facts"] if f["name"] == "unit_price_usd_each"}
    assert 240.58 / 1000 == pytest.approx(each["HR-20103"], rel=.001)
    assert 1536.93 / 1000 == pytest.approx(each["HR-20140"], rel=.001)
    duty = sum(p * q * .15 for p, q in [(0.24058, 12000), (0.28543, 8000), (0.11474, 12000), (0.13992, 16000), (9.10, 4200), (13.24, 900)])
    assert duty == pytest.approx(next(f for f in e["facts"] if f["name"] == "duty_2027_usd" and "part" not in f)["value"], rel=.001)
    assert "HR-20140" not in e["duty_scope"]["dutiable_china_lines"]


def test_jadepeak_delays_and_duty(po):
    revised = {("HPO-26-00486", 10): "2026-11-09", ("HPO-26-00517", 20): "2026-11-04", ("HPO-26-00517", 10): "2026-11-11",
               ("HPO-26-00672", 10): "2027-01-08", ("HPO-26-00646", 10): "2027-01-04"}
    for (n, l), new in revised.items():
        days = (pd.Timestamp(new) - line(po, n, l).promised_date_d).days
        assert days == fact("disruption-jadepeak", "revised_delay_days", po_line=f"{n}/{l}")["value"]
    for ln, key in [(10, "HPO-26-00517/10"), (20, "HPO-26-00517/20")]:
        r = line(po, "HPO-26-00517", ln)
        assert r.open_qty * r.usd_each * .25 == pytest.approx(fact("disruption-jadepeak", "duty_usd", po_line=key)["value"], rel=.001)


def _senders():
    import email
    import glob
    import re
    from email import policy
    sup = pd.read_csv(DATA / "suppliers.csv", dtype=str)
    by_addr = {r.contact_email.lower(): r.supplier_id for r in sup.itertuples()}
    by_dom = {}
    for r in sup.itertuples():
        by_dom.setdefault(r.contact_email.split("@")[-1].lower(), r.supplier_id)
    out = {}
    for p in sorted(glob.glob(str(DATA / "quotes" / "*.*"))):
        if p.endswith(".eml"):
            m = email.message_from_file(open(p), policy=policy.default)
            addr = re.search(r"<([^>]+)>", str(m["From"])).group(1).lower()
        else:
            hit = re.search(r"([\w.\-]+@[\w.\-]+)", open(p).read().split("\n\n")[0])
            addr = hit.group(1).lower() if hit else None
        if addr is None:
            out[Path(p).name] = (None, "unverifiable_pasted_text")
        elif addr in by_addr:
            out[Path(p).name] = (by_addr[addr], "trusted")
        elif addr.split("@")[-1] in by_dom:
            out[Path(p).name] = (by_dom[addr.split("@")[-1]], "known_domain")
        else:
            out[Path(p).name] = (None, "unknown")
    return out


def test_triage_trust_is_derivable_from_the_raw_senders():
    got = _senders()
    checks = run.load_cases("triage-inbox")["triage-inbox"]["checks"]
    assert len(got) == 15 and len([c for c in checks if "pick" in c]) == 15
    for c in checks:
        if "pick" not in c:
            continue
        stem = c["pick"]["ref.id"]
        file = next(n for n in got if n.rsplit(".", 1)[0] == stem)
        sender, trust = got[file]
        want = c["expect"]
        if want["trust"] in ("suspicious", "new_sender"):
            if not want.get("supplier.id"):
                assert trust == "unknown", (stem, trust)        # the fraud email and the Vietnamese maker: no domain on file
            else:
                assert sender == want["supplier.id"] and trust == "known_domain", (stem, sender, trust)   # Saltmarsh: right domain, wrong address
        elif sender is not None:
            linked = {"SUP-0061": "SUP-0016"}                         # the rename: BCX's own record is linked to Baycrest by the alias decision
            assert linked.get(sender, sender) == want["supplier.id"], (stem, sender, want["supplier.id"])
            if trust == "known_domain":                           # right domain, address not on file: the flag must be required
                assert "sender_not_contact_on_file" in want["trust_flags"]["contains"], stem
        else:
            assert stem.startswith("2026-09-18_Jadepeak")        # a pasted notice with no sender address at all


def test_quote_validity_dates_are_the_arithmetic_of_the_message_dates():
    d = lambda s, n: str((pd.Timestamp(s) + pd.Timedelta(days=n)).date())  # noqa: E731
    assert d("2026-08-14", 60) == "2026-10-13" and d("2026-09-17", 60) == "2026-11-16" and d("2026-09-21", 45) == "2026-11-05"
    assert fact("deadline-greatplains", "days_left")["value"] == (pd.Timestamp("2026-10-15") - pd.Timestamp("2026-09-25")).days


def test_import_sheets_match_the_raw_files(po):
    sup = pd.read_csv(DATA / "suppliers.csv", dtype=str).set_index("supplier_id")
    raw = pd.read_csv(DATA / "purchase_orders.csv", dtype=str)
    blank = raw[raw.currency.isna()]
    want = {x["po_line"]: x["inferred"] for x in CASES["import-currencies"]["expected"]["blank_currency_lines"]}
    got = {f"{r.po_number}/{r.line}": sup.currency[r.supplier_id] for r in blank.itertuples()}
    assert got == want and set(blank.status) <= {"CLOSED", "CANCELLED"}
    assert int((raw.currency == "RMB").sum()) == CASES["import-currencies"]["expected"]["normalised"]["lines"]
    legacy = [i for i in sup.index if i.startswith("V")]
    asked = {r for a in CASES["import-aliases"]["expected"]["asked_not_assumed"] for r in a["records"] if r.startswith("V")}
    assert asked == set(legacy) and len(sup) == CASES["import-aliases"]["expected"]["supplier_records"]
    assert sup.contact_name["SUP-0016"] == sup.contact_name["V10045"]
    assert sup.status["V10560"] == "Inactive" and (raw.supplier_id == "V10560").sum() == 14
    assert "SUP-0053" in sup.index


def test_unknown_origin_owners_follow_the_category_buyer():
    parts = pd.read_csv(DATA / "parts.csv", dtype=str).set_index("part_number")
    e = CASES["import-origins-unknown"]["expected"]
    for x in e["unknown_origin_on_listed_codes"]:
        assert pd.isna(parts.country_of_origin[x["part"]]) and not pd.isna(parts.hts_code[x["part"]])
    for x in e["unknown_hts_china_origin"]:
        assert pd.isna(parts.hts_code[x["part"]]) and COO[parts.country_of_origin[x["part"]].strip().upper()] == "CN"  # raw spellings vary ("China (PRC)")


def test_jadepeak_slip_shortages_follow_from_the_notice_and_the_forecast(po):
    """Cumulative balance with unknown stock taken as zero: a slip causes the shortage that the original promise did not."""
    from evals.oracle import explode, PRODUCTS
    bom = pd.read_csv(DATA / "bom.csv", dtype=str)
    fc = pd.read_csv(DATA / "demand_forecast.csv", dtype=str)
    qpr = explode(bom)
    key = {"tern": "HR-90020", "porter": "HR-90050", "heron": "HR-90110"}
    fc["pk"] = fc["product"].str.lower().map(lambda n: next(v for k, v in key.items() if k in n))
    units = fc.assign(u=fc.units.astype(float)).groupby(["pk", "month"]).u.sum().unstack(0).fillna(0)
    months = list(units.index)
    slip = {("HPO-26-00486", "10"): "2026-11-09", ("HPO-26-00517", "20"): "2026-11-04", ("HPO-26-00517", "10"): "2026-11-11",
            ("HPO-26-00672", "10"): "2027-01-08", ("HPO-26-00646", "10"): "2027-01-04"}

    def short(part, use_slip):
        lines = po[(po.pn == part) & po.status.isin(["OPEN", "PARTIAL"]) & po.po_number.str.startswith("HPO")]
        arrive = {}
        for r in lines.itertuples():
            d = pd.Timestamp(slip[(r.po_number, r.line)]) if use_slip and (r.po_number, r.line) in slip else r.promised_date_d
            m = max(f"{d:%Y-%m}", "2026-09")  # a line already late arrives, at the earliest, in the current month
            arrive[m] = arrive.get(m, 0) + r.open_qty
        cum, out = arrive.get("2026-09", 0), {}
        for m in months[:4]:
            cum += arrive.get(m, 0) - sum(units[p].loc[m] * qpr[p].get(part, 0) for p in PRODUCTS)
            out[m] = round(max(0, -cum))
        return out

    for part, month, want in [("HR-51110", "2026-10", 222), ("HR-51120", "2026-10", 222), ("HR-51130", "2026-10", 222), ("HR-51310", "2026-11", 46)]:
        f = fact("disruption-jadepeak", "shortage_caused_by_slip", part=part)
        assert f["value"] == want and f["id"] == f"shortage:{part}:{month}:short"
        assert short(part, True)[month] == want and short(part, False)[month] < want


def test_import_deck_lists_are_derivable_from_the_raw_files():
    parts = pd.read_csv(DATA / "parts.csv", dtype=str)
    have = parts[parts.mpn.notna() & parts.manufacturer.notna()]
    groups = have.groupby([have.manufacturer.str.strip().str.lower(), have.mpn.str.strip().str.lower()]).part_number.apply(sorted)
    pairs = sorted(" = ".join(g) for g in groups if len(g) == 2)
    raw = pd.read_csv(DATA / "purchase_orders.csv", dtype=str)
    repeats = [f"{r.po_number}/{r.line}" for r in raw[raw.duplicated(keep="first")].itertuples()]
    checks = {c["id"]: c["expect"] for c in CASES["import-deck"]["checks"]}
    assert sorted(checks["three-possible-duplicate-parts"]["entries"]) == pairs
    assert sorted(checks["six-repeated-rows"]["entries"]) == sorted(repeats)
    sup = pd.read_csv(DATA / "suppliers.csv", dtype=str)
    assert sorted(checks["deck-has-six-cards"]["entries"]) == sorted(i for i in sup.supplier_id if i.startswith("V"))
    bom = pd.read_csv(DATA / "bom.csv", dtype=str)
    assert len(bom) == 359 and len(raw) == 2622 and len(sup) == 71 and len(parts) == 502


def test_apicheck_all_true_form():
    from evals import apicheck
    ok = {"checks": [{"name": "a", "passed": True}, {"name": "b", "passed": True}]}
    assert apicheck.evaluate({"id": "g", "expect": {"checks": {"all_true": "passed"}}}, ok)["passed"]
    ok["checks"][1]["passed"] = False
    assert not apicheck.evaluate({"id": "g", "expect": {"checks": {"all_true": "passed"}}}, ok)["passed"]


def test_tern_october_readiness_keys_come_from_the_raw_files():
    from pathlib import Path

    from evals import oracle
    r = oracle.readiness(Path(__file__).resolve().parents[2] / "data", "Tern T2", "2026-10")
    assert r["units"] == 182 and r["bought_parts"] == 134
    assert r["counts"] == {"in_house": 7, "no_order": 80, "covered": 35, "after_build": 13, "disrupted": 3, "past_due": 3}
    assert sum(v for k, v in r["counts"].items() if k != "in_house") == 134 and r["covered_but_short_on_quantity"] == []


def test_the_stock_card_covers_the_bought_parts_with_nothing_on_order():
    from pathlib import Path

    import pandas as pd

    from evals import oracle
    d = Path(__file__).resolve().parents[2] / "data"
    po, parts, *_ = oracle.load(d)
    open_ = po[po.status.isin(["OPEN", "PARTIAL"])]
    stale = open_.po_number.str.startswith("PO-") & (open_.promised_date_d < pd.Timestamp("2026-01-01"))
    supply = open_[~stale & (open_.open_qty > 0)]
    bought = parts[~parts.category.isin(["Finished Good", "Sub-assembly"])]
    assert len(bought) == 481 and len(set(bought.index) - set(supply.pn)) == 335


def test_the_chase_list_is_derived_from_the_raw_files():
    from pathlib import Path

    from evals import oracle
    r = oracle.chase(Path(__file__).resolve().parents[2] / "data")
    assert r["lines"] == 16 and round(r["usd_open"]) == 496044      # 19 and 503,522 before the supplier that announced a closure (Meiya, three lines) was taken out
    assert r["largest"] == "HPO-26-00505/10" and round(r["largest_usd"]) == 367729
    assert r["buyers"] == ["Dana Reyes", "Marcus Chen", "Priya Nair", "Tom Albrecht"]
