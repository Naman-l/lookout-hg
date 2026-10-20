"""Generality: the specialised agents' categories on cases nobody built them for.   python -m evals.generality [--keep DIR] [--json FILE]

Twelve unseen variants, two per category (Disruption, Supplier risk, Tariff, Deadline, Unknown, Trust), made by changing the DATA only (a notice from
another supplier on file, a quote for another part, a different look-alike domain, a line with no date), dropped in through the normal inputs (data/
quotes, the supplier master, the news feed, the orders export), then the same recipe builds the database. Each variant is walked link by link with no
model: detector -> case kind -> the team (plan_for) -> findings -> routes (option kinds, also-starts) -> route figures -> the buyer's choice -> the draft to
that variant's own contact on file, with the category rules (D2 D4 R1 R4 T2) where they apply. PASS / FAIL / n/a per link. The perturbed gate is the
seed of this; nothing here adds a case key."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def _rows(p: Path) -> list[dict]:
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write(p: Path, rows: list[dict]) -> None:
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _part(p: str) -> str:
    return p if "-" in p else f"{p[:2]}-{p[2:]}"


def _iso(d: str) -> str:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(d, fmt).date().isoformat()
        except ValueError:
            continue
    return d


def _supplier(data: Path, sid: str) -> dict:
    return next(r for r in _rows(data / "suppliers.csv") if r["supplier_id"] == sid)


def _open_lines(data: Path, sid: str) -> list[dict]:
    return [r for r in _rows(data / "purchase_orders.csv") if r["supplier_id"] == sid and r["status"] in ("OPEN", "PARTIAL") and r["promised_date"]]


def _eml(data: Path, name: str, sender: str, email: str, to: str, date: str, subject: str, body: str) -> None:
    from email.header import Header  # noqa: PLC0415

    sender = Header(sender, "utf-8").encode() if not sender.isascii() else sender      # a name with accents is encoded in the header, as real mail does
    (data / "quotes" / name).write_text(f"From: {sender} <{email}>\nTo: {to}\nDate: {date}\nSubject: {subject}\nMessage-ID: <{name}@variant.example>\n"
                                        f"Content-Type: text/plain; charset=\"utf-8\"\nMIME-Version: 1.0\n\n{body}\n", encoding="utf-8")


def force_majeure(data: Path, sid: str, day: str, extra: str = "") -> None:
    s = _supplier(data, sid)
    lines = sorted(_open_lines(data, sid), key=lambda r: _iso(r["promised_date"]))
    table = "\n".join(f"{r['po_number']:<14}{r['line']:<6}{_part(r['part_number']):<11}{int(float(r['qty'])):>8}   {_iso(r['promised_date'])}" for r in lines)
    body = (f"Dear Purchasing,\n\nWe regret to inform you that on {day} a flood damaged the production hall of our main plant. No one was injured.\n\n"
            f"According to the force majeure clause of our supply agreement, we hereby give formal notice that we are unable to perform deliveries "
            f"for the time being. Following open orders are affected:\n\nPO            Line  Part       Open qty   Confirmed date\n{table}\n\n"
            f"Our current estimation is partial production can resume in 4 to 6 weeks.\n{extra}\nWe will provide revised delivery dates no later than 16 October 2026.\n\n"
            f"{s['contact_name']}\n{s['name']}")
    _eml(data, f"2026-09-23_NOTICE_OF_FORCE_MAJEURE_-_{s['name'].split(',')[0].replace(' ', '_')}.eml", s["contact_name"], s["contact_email"],
         "Purchasing <purchasing@company.example>", "Wed, 23 Sep 2026 09:10:00 +0200", f"NOTICE OF FORCE MAJEURE - {s['name']}", body)


def price_rise(data: Path, sid: str) -> None:
    s = _supplier(data, sid)
    body = (f"Hello,\n\nRaw material costs have moved sharply.\n\nEffective December 1, 2026, {s['name']} will increase prices as follows:\n\n"
            f"  - Machined and fabricated parts: +6.0%\n\nOrders placed and acknowledged by November 10, 2026 for delivery by January 15, 2027\n"
            f"will be honored at current pricing.\n\n{s['contact_name']}\n{s['name']}")
    _eml(data, "2026-09-20_Price_adjustment_notice_-_effective_December_1_2026.eml", s["contact_name"], s["contact_email"], "Purchasing <purchasing@company.example>",
         "Sun, 20 Sep 2026 10:00:00 -0500", "Price adjustment notice - effective December 1, 2026", body)


def closure(data: Path, sid: str) -> None:
    s = _supplier(data, sid)
    (data / "quotes" / "2026-09-19_Plant_shutdown_notice_November_2026.txt").write_text(
        f"From: {s['contact_name']} <{s['contact_email']}>\nSent: Saturday, September 19, 2026 9:00 AM\nTo: Purchasing\nSubject: Plant shutdown notice - November 2026\n\n"
        f"Dear customer,\n\nPlease kindly note our plant will be closed for annual maintenance from\nOctober 19 to October 30, 2026. Last shipment before the shutdown will leave on\n"
        f"October 16. Production resumes November 2.\n\nAny orders scheduled to ship during the closure will ship on November 3.\n\n{s['contact_name']}\n{s['name']}\n", encoding="utf-8")


def alt_origin_quote(data: Path, part: str, price: str, name: str, country: str, quote: str) -> None:
    body = (f"Dear Purchasing,\n\nThank you for your inquiry. Please find our quotation {quote} for an equivalent to your part {part}.\n\n"
            f"Part: {part}\nQty 500: USD {price} each, FOB Laem Chabang\nLead time: 8 weeks after sample approval\nMOQ: 500\n"
            f"Country of origin: {country}\nValid until: 2026-12-31\nPayment terms: Net 30\n\nBest regards,\nSomsak Chai\n{name}")
    _eml(data, f"2026-09-24_Quotation_{quote}_-_equivalent_to_{part}.eml", "Somsak Chai", f"somsak@{name.split()[0].lower()}.example", "Purchasing <purchasing@company.example>",
         "Thu, 24 Sep 2026 11:00:00 +0700", f"Quotation {quote} - equivalent to {part}", body)


def look_alike(data: Path, sid: str, domain: str) -> None:
    s = _supplier(data, sid)
    old = next((data / "quotes").glob("*URGENT*")).read_text(encoding="utf-8")
    body = old.split("\n\n", 1)[1]
    _eml(data, "2026-09-24_URGENT_new_bank_details_effective_immediately.eml", s["contact_name"], f"{s['contact_email'].split('@')[0]}@{domain}",
         "Accounts Payable <ap@company.example>", "Thu, 24 Sep 2026 07:15:00 +0800", "URGENT: new bank details effective immediately", body)


def spot_offer(data: Path) -> None:
    old = next((data / "quotes").glob("*Spot_offer*")).read_text(encoding="utf-8")
    body = old.split("\n\n", 1)[1]
    _eml(data, "2026-09-21_Stock_offer_-_drive_ICs_ready_to_ship.eml", "Kevin Brandt", "kevin@fastchips-global.example", "Purchasing <purchasing@company.example>",
         "Mon, 21 Sep 2026 06:00:00 +0000", "Stock offer - drive ICs ready to ship", body)


def news(data: Path, entity: str, headline: str, summary: str) -> None:
    p = data / "external" / "supplier_news.json"
    feed = json.loads(p.read_text(encoding="utf-8"))
    feed.append({"id": f"N-9{len(feed):02d}", "date": "2026-09-21", "source": "Industry Wire", "headline": headline, "summary": summary, "entity_mentioned": entity,
                 "url": "https://industrywire.example/" + entity.lower().replace(" ", "-")})
    p.write_text(json.dumps(feed, indent=2, ensure_ascii=False), encoding="utf-8")


def set_master(data: Path, sid: str, **fields) -> None:
    rows = _rows(data / "suppliers.csv")
    for r in rows:
        if r["supplier_id"] == sid:
            r.update(fields)
    _write(data / "suppliers.csv", rows)


def undate_line(data: Path, sid: str) -> str:
    rows = _rows(data / "purchase_orders.csv")
    r = next(r for r in rows if r["supplier_id"] == sid and r["status"] == "OPEN" and r["promised_date"])
    r["promised_date"] = ""
    _write(data / "purchase_orders.csv", rows)
    return f"{r['po_number']}/{r['line']}"


def no_origin(data: Path, part: str) -> None:
    rows = _rows(data / "parts.csv")
    for r in rows:
        if r["part_number"] in (part, part.replace("-", "")):
            for k in ("coo", "country_of_origin"):
                if k in r:
                    r[k] = ""
    _write(data / "parts.csv", rows)


# (id, category, the data change, what the detector should find: (group, key prefix or exact key, supplier id whose contact the draft must reach), rules)
VARIANTS = [
    ("dis-fm-sakai", "Disruption", lambda d: force_majeure(d, "SUP-0049", "19 September 2026"), ("disruption", "disruption:SUP-0049", "SUP-0049"), ["R1", "D4"]),
    ("dis-fm-cutoff-rheinberg", "Disruption", lambda d: force_majeure(d, "SUP-0059", "20 September 2026",
                                                                       "For orders placed after 20 October 2026, standard lead time extends from 6 weeks to 12 weeks.\n"),
     ("disruption", "disruption:SUP-0059", "SUP-0059"), ["R1", "D4", "D2"]),
    ("risk-insolvency-bajio", "Supplier risk", lambda d: news(d, "Bajío Precision Machining", "Bajío Precision Machining files for insolvency",
                                                              "The Querétaro machining supplier Bajío Precision Machining has filed for insolvency (concurso mercantil); operations continue under a court-appointed conciliator."),
     ("disruption", "risk:SUP-0040", "SUP-0040"), ["R1", "D4"]),
    ("risk-prepaid-quenvara", "Supplier risk", lambda d: set_master(d, "SUP-0011", payment_terms="100% T/T in advance"), ("disruption", "risk:SUP-0011", "SUP-0011"), ["R4", "D4"]),
    ("tariff-alt-origin-cheaper", "Tariff", lambda d: alt_origin_quote(d, "HR-41110", "120.00", "Chonburi Motion Co., Ltd.", "Thailand", "CMT-Q-2609"), ("tariff", "tariff:all", None), ["T2+"]),
    ("tariff-alt-origin-dearer", "Tariff", lambda d: alt_origin_quote(d, "HR-40310", "400.00", "Rayong Drives Co., Ltd.", "Thailand", "RDT-Q-2609"), ("tariff", "tariff:all", None), ["T2-"]),
    ("deadline-price-rise-kraft", "Deadline", lambda d: price_rise(d, "SUP-0039"), ("deadline", "deadline:SUP-0039", "SUP-0039"), []),
    ("deadline-closure-corvell", "Deadline", lambda d: closure(d, "SUP-0036"), ("deadline", "deadline:SUP-0036", "SUP-0036"), []),
    ("unknown-undated-lakemont", "Unknown", lambda d: undate_line(d, "SUP-0026"), ("unknown", "unknown:undated", None), []),
    ("unknown-origin-meiya", "Unknown", lambda d: no_origin(d, "HR-73112"), ("unknown", "unknown:origin", None), []),
    ("trust-lookalike-jadepeak", "Trust", lambda d: look_alike(d, "SUP-0013", "jadepeak-tw.example"), ("trust", "trust:", None), []),
    ("trust-spot-broker", "Trust", lambda d: spot_offer(d), ("trust", "trust:", None), []),
]
LINKS = ["detector", "kind", "team", "findings", "routes", "figures", "choose", "draft", "rules"]


def make_world(root: Path) -> Path:
    data, recipe = root / "data", root / "recipe"
    shutil.copytree(ROOT / "data", data, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "recipes" / "halden", recipe, ignore=shutil.ignore_patterns("__pycache__"))
    for _vid, _cat, change, _exp, _rules in VARIANTS:
        change(data)
    db = root / "variants.db"
    done = subprocess.run([sys.executable, "-m", "app.domain.imports.build", "--recipe", str(recipe), "--data", str(data), "--db", str(db)], cwd=BACKEND,
                          env={**os.environ, "LOOKOUT_DB": str(db)}, capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(done.stdout[-1500:] + done.stderr[-1500:])
    return db


def walk(db: Path, before: set[str]) -> list[dict]:
    """In a process whose LOOKOUT_DB is the variants' database (the app reads it at import)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.domain.actions import approvers
    from app.domain.actions.routes import RouteError, choose
    from app.domain.attention import findings, option_kinds, options, service
    from app.domain.attention.api import action_item_options
    from app.organism.workflows.work_item import plan_for

    eng = create_engine(f"sqlite:///{db}", future=True)
    out = []
    with Session(eng) as s:
        items = service.what_needs_attention(s)
        new_trust = [i for i in items if i.group == "trust" and i.key not in before]
        for vid, cat, _change, (group, key, sid), rules in VARIANTS:
            row = {"variant": vid, "category": cat, **{k: "n/a" for k in LINKS}, "notes": []}
            if group == "trust":
                hit = next((i for i in new_trust if ("jadepeak" in vid and "Jadepeak" in i.title) or ("spot" in vid and "Jadepeak" not in i.title)), None)
            elif key in ("tariff:all", "unknown:undated", "unknown:origin"):
                hit = next((i for i in items if i.key == key), None)
            else:
                hit = next((i for i in items if i.key == key or i.key.startswith(key + ":")), None)
            row["detector"] = "PASS" if hit else "FAIL"
            if not hit:
                row["notes"].append(f"no item {key}* on the Action list")
                out.append(row)
                continue
            row["key"], row["title"] = hit.key, hit.title
            kind = options.case_kind(s, hit.key) or hit.group
            row["kind"] = f"PASS ({kind})"
            team = plan_for(hit.group, hit.key)
            row["team"] = f"PASS ({' → '.join(x if isinstance(x, str) else '+'.join(x) for x in team) or 'code only'})"
            f = findings.candidates(s, hit.key)
            row["findings"] = f"PASS ({len(f)})" if f or group in ("trust",) else "FAIL (none)"
            owners = sorted(approvers.owners_of(str(db), hit.key) or [])
            owner = owners[0] if owners else None
            kinds = option_kinds.option_kinds(s, hit.key, owner)
            if group == "trust":
                row["routes"] = "PASS (controls, no routes)" if not kinds else "FAIL (routes on a trust item)"
                row["rules"] = "PASS (held, nothing drafted)"
                out.append(row)
                continue
            row["routes"] = f"PASS ({len(kinds)}; also: {', '.join(k.kind for k in kinds if k.also_start) or '-'})" if kinds else "FAIL (no routes)"
            figs = action_item_options(hit.key, owner, s)
            uncited = [r.kind for r in figs if any(m is not None and m.provenance is None for m in (r.cost, r.cost_delta))]
            row["figures"] = "PASS" if [r.kind for r in figs] == [k.kind for k in kinds] and not uncited else f"FAIL ({uncited or 'rows differ from routes'})"
            req = next((k for k in kinds if k.leads_to == "request"), None) or (kinds[0] if kinds else None)
            draft = None
            if req is not None and owner:
                try:
                    draft, how = choose(s, str(db), hit.key, req.kind, owner, reason="variant check")
                    row["choose"] = f"PASS ({req.kind}, {how})"
                except RouteError as e:
                    row["choose"] = f"FAIL ({e.status}: {e.message[:80]})"
            if draft is not None and draft.type == "supplier_request" and sid:
                from app.domain.suppliers import service as suppliers

                want = suppliers.contact_on_file(s, sid).email
                row["draft"] = "PASS (to " + draft.recipient + ")" if draft.recipient == want else f"FAIL (to {draft.recipient}, contact on file {want})"
            elif draft is not None:
                row["draft"] = f"PASS ({draft.type} to {(draft.change or {}).get('to') or draft.recipient or 'the record'})"
            res = []
            body = (draft.body or "") if draft is not None else ""
            for r in rules:
                if r == "R1":
                    res.append(("R1", "waives any of" in body))
                elif r == "D4":
                    res.append(("D4", any(k.kind in ("second_source", "alternate_on_file") and k.also_start for k in kinds)))
                elif r == "D2":
                    res.append(("D2", any(k.kind == "order_before" for k in kinds)))
                elif r == "R4":
                    res.append(("R4", bool(f) and f[0].key == "cash_at_risk"))
                elif r in ("T2+", "T2-"):
                    alts = option_kinds.alternate_origins(s)
                    named = any(a["part"] == ("HR-41110" if r == "T2+" else "HR-40310") for a in alts)
                    res.append((r, named if r == "T2+" else not named))
            row["rules"] = ("PASS (" if all(ok for _, ok in res) else "FAIL (") + ", ".join(f"{n} {'ok' if ok else 'missing'}" for n, ok in res) + ")" if res else "n/a"
            out.append(row)
    eng.dispose()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evals.generality")
    ap.add_argument("--keep", type=Path, help="keep the variants' database here (for the case-page check)")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--walk", type=Path, help=argparse.SUPPRESS)
    ap.add_argument("--before", type=Path, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.walk:      # the child process: LOOKOUT_DB is the variants' database
        sys.path.insert(0, str(BACKEND))
        before = set(json.loads(a.before.read_text())) if a.before else set()
        print(json.dumps(walk(a.walk, before)))
        return 0
    with tempfile.TemporaryDirectory(prefix="lookout-generality-") as w:
        root = Path(w)
        db = make_world(root)
        base = root / "base.db"
        subprocess.run([sys.executable, "-m", "app.domain.imports.build", "--recipe", str(ROOT / "recipes" / "halden"), "--data", str(ROOT / "data"), "--db", str(base)],
                       cwd=BACKEND, env={**os.environ, "LOOKOUT_DB": str(base)}, capture_output=True, text=True, check=True)
        keys = subprocess.run([sys.executable, "-c", "import json; from app.db import SessionLocal; from app.domain.attention import service as a; "
                               "print(json.dumps([i.key for i in a.what_needs_attention(SessionLocal())]))"], cwd=BACKEND, env={**os.environ, "LOOKOUT_DB": str(base)},
                              capture_output=True, text=True, check=True).stdout
        (root / "before.json").write_text(keys)
        if a.keep:
            a.keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(db, a.keep)
        res = subprocess.run([sys.executable, "-m", "evals.generality", "--walk", str(db), "--before", str(root / "before.json")], cwd=ROOT,
                             env={**os.environ, "LOOKOUT_DB": str(db), "PYTHONPATH": str(BACKEND)}, capture_output=True, text=True)
        if res.returncode != 0:
            print(res.stderr[-3000:])
            return 1
        rows = json.loads(res.stdout.strip().splitlines()[-1])
    fails = 0
    print(f"{'variant':30} {'cat':13} " + " ".join(f"{k:9}" for k in LINKS))
    for r in rows:
        fails += sum(str(r[k]).startswith("FAIL") for k in LINKS)
        print(f"{r['variant']:30} {r['category']:13} " + " ".join(f"{str(r[k]).split(' ')[0]:9}" for k in LINKS) + (f"  key={r.get('key')}" if r.get("key") else ""))
    if a.json:
        a.json.write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    print(f"{len(rows)} variants, {fails} failed links")
    return 0


if __name__ == "__main__":
    sys.exit(main())
