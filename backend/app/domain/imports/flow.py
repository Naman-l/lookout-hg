"""The Import conversation as code: questions that come from the recipe's own decisions, the person's answers, a dry run, an approval that loads.

No model is needed. Each question is a decision the bootstrap recipe already takes (link ten legacy supplier ids, infer nine blank currencies, leave five
origins unknown, drop six repeated rows, link three possible duplicate parts), grouped so one answer settles every entry it covers, with the proposed answer
on the card. Answers wait in a pending file until the person approves; approval keeps them beside the database (`decisions.yaml`, gitignored; the recipe stays as committed), with who and when) and
rebuilds the database. The Data steward will ask the same questions for files nobody has seen before; this is the part that needs no judgement.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import yaml

from app.domain.common.recipe import recipe_dir as _recipe_dir
from app.domain.imports import build
from app.domain.imports.gate import RECONCILED, run_gate
from app.domain.imports.schema import (ImportAnswerCounts, ImportApproval, ImportAnswers, ImportCheck, ImportDeck, ImportDryRun, ImportExample, ImportFileChange,
                                       ImportLoaded, ImportProposed, ImportQuestion)

ROOT = Path(__file__).resolve().parents[4]
RECIPE_DIR = _recipe_dir()
DATA_DIR = ROOT / "data"
ACCEPT_ALL = ("alias:legacy-ids", "alias:rename", "currency:blank", "origin:unknown-on-listed-codes", "duplicate-row:po", "possible-duplicate:parts", "stock:count")


class AnswersChanged(Exception):
    """The answers changed since the dry run the person approved."""


def _pending_path(db: Path) -> Path:
    return db.with_name(db.name + ".pending")


def _read_json(p: Path) -> dict:
    return json.loads(p.read_text()) if p.exists() else {}


def saved_decisions(recipe_dir: Path, db: Path | None = None) -> dict:
    """The answers already approved: the recipe's own (none are committed) and the ones kept beside the database."""
    out: dict = {}
    for p in (recipe_dir / "decisions.yaml", build.runtime_decisions_path(db) if db else None):
        if p and p.exists():
            out.update((yaml.safe_load(p.read_text()) or {}).get("decisions", {}) or {})
    return out


def effective_decisions(recipe_dir: Path, db: Path) -> dict:
    """What the recipe will use: the saved decisions, overridden by the answers still waiting for approval. An unanswered question takes its proposed answer."""
    return {**saved_decisions(recipe_dir, db), **_read_json(_pending_path(db))}


def decisions_hash(recipe_dir: Path, db: Path, data_dir: Path = DATA_DIR) -> str:
    h = hashlib.sha256()
    h.update(json.dumps({k: (v.get("action"), v.get("value")) for k, v in sorted(effective_decisions(recipe_dir, db).items())}).encode())
    h.update(build._recipe_hash(recipe_dir).encode())
    h.update(json.dumps(build._data_hashes(data_dir), sort_keys=True).encode())
    return h.hexdigest()[:16]


@lru_cache(maxsize=4)
def _baseline(recipe_dir: str, data_dir: str):
    """The recipe run with every question answered as proposed: the entries each question covers."""
    return build.run_recipe(Path(recipe_dir), Path(data_dir), {k: {"action": "accept"} for k in ACCEPT_ALL})


def _examples(rows) -> list[ImportExample]:
    return [ImportExample(from_=a, to=b, note=c) for a, b, c in rows[:3]]


def _questions(ctx) -> list[ImportQuestion]:
    t = ctx.t
    rec = t["supplier_records"].set_index("record_id")
    ident = t["supplier_identities"].set_index("id")
    legacy = rec[(rec.system == "legacy") & (rec.identity_method == "inferred")]
    po = t["po_lines"]
    cur = po[po.currency_method == "inferred"]
    parts = t["parts"]
    rules = t["tariff_rules"]
    prefixes = tuple(rules.hts_prefix)
    blank = parts[(parts.kind == "purchased") & parts.coo.isna() & parts.hts.notna() & parts.hts.fillna("").str.startswith(prefixes)]
    drops = [d for d in ctx.drops if d["raw_table"] == "raw_purchase_orders"]
    raw_po = t["raw_purchase_orders"].set_index("src_row")
    links = t["part_links"]
    open_ok = set(po[po.status.isin(["OPEN", "PARTIAL"]) & ~po["flags"].fillna("").str.contains("stale_open")].part_number)
    nostock = parts[(parts.kind == "purchased") & ~parts.part_number.isin(open_ok)]
    aliases = ctx.answers.get("supplier_aliases") or []
    sizes = rec.groupby("identity_id").size()
    most = (ident.loc[sizes.idxmax(), "name"], int(sizes.max())) if len(sizes) else ("one company", 1)
    ex_stock = nostock.part_number.iloc[0] if len(nostock) else "PART-1"
    ex_origin = blank.part_number.iloc[0] if len(blank) else "PART-1"
    qs = [
        ImportQuestion(
            id="alias:legacy-ids", kind="alias", file="suppliers.csv", covers=len(legacy), entries=list(legacy.index),
            question=f"{len(legacy)} legacy supplier ids look like suppliers you already have (same contact domain). Link them as the same company?",
            examples=_examples([(f"{r} · {rec.loc[r, 'name']}", f"{rec.loc[r, 'identity_id']} · {ident.loc[rec.loc[r, 'identity_id'], 'name']}", rec.loc[r, "identity_evidence"]) for r in legacy.index]),
            proposed=ImportProposed(answer=f"Link all {len(legacy)}", effect=f"Spend, past-due lines and exposure are counted per company ({most[0]} has {most[1]} records). Every record and every PO stays as it is; nothing is merged.")),
        ImportQuestion(
            id="alias:rename", kind="alias", file="suppliers.csv", covers=len(aliases), entries=[a["record"] for a in aliases],
            question=(f"{len(aliases)} supplier record{'s' if len(aliases) != 1 else ''} say they are a renamed company already in the master. Link "
                      f"{'them' if len(aliases) != 1 else 'it'}?"),
            examples=_examples([(f"{a['record']} · {rec.loc[a['record'], 'name']}", f"{a['identity']} · {ident.loc[a['identity'], 'name']}", a["evidence"]) for a in aliases]),
            proposed=ImportProposed(answer="Link them" if len(aliases) != 1 else "Link it", effect="Quotes under the new name and orders under the old one belong to one supplier.")),
        ImportQuestion(
            id="currency:blank", kind="currency", file="purchase_orders.csv", covers=len(cur), entries=list(cur.id),
            question=f"{len(cur)} order lines have no currency. Use the supplier's usual invoicing currency and mark it inferred?",
            examples=_examples([(r.id, r.currency, f"{rec.loc[r.record_id, 'name']} usually invoices in {r.currency}") for r in cur.itertuples()]),
            proposed=ImportProposed(answer="Use the supplier's currency, marked inferred", effect="The lines are priced and compared; each carries the label 'inferred'. None is open.")),
        ImportQuestion(
            id="origin:unknown-on-listed-codes", kind="origin", file="parts.csv", covers=len(blank), entries=list(blank.part_number),
            question=f"{len(blank)} parts are on the new tariff list but have no country of origin. Leave them unknown and ask the buyer?",
            examples=_examples([(r.part_number, "unknown", f"ask {r.buyer_id or 'the buyer'}: {r.description[:50]}") for r in blank.itertuples()]),
            proposed=ImportProposed(answer="Leave unknown, ask the buyer", effect=f"No duty is computed for them; only the figure 'if China' is shown. To answer now, change it to PART=ISO pairs, e.g. {ex_origin}=CN.")),
        ImportQuestion(
            id="duplicate-row:po", kind="duplicate_row", file="purchase_orders.csv", covers=len(drops), entries=[f"{raw_po.loc[d['src_row'], 'po_number']}/{raw_po.loc[d['src_row'], 'line']}" for d in drops],
            question=f"{len(drops)} order lines appear twice with every value identical (an export glitch). Drop the repeated copies?",
            examples=_examples([(f"{raw_po.loc[d['src_row'], 'po_number']}/{raw_po.loc[d['src_row'], 'line']}", "dropped", d["kept_as"]) for d in drops]),
            proposed=ImportProposed(answer="Drop the repeats", effect="Quantity and value of those lines are counted once. Each drop is recorded with the row it repeats.")),
        ImportQuestion(
            id="possible-duplicate:parts", kind="possible_duplicate", file="parts.csv", covers=len(links), entries=[f"{r.part_a} = {r.part_b}" for r in links.itertuples()],
            question=f"{len(links)} pairs of part numbers share a manufacturer part number. Keep both and mark them as possible duplicates?",
            examples=_examples([(r.part_a, r.part_b, r.evidence) for r in links.itertuples()]),
            proposed=ImportProposed(answer="Keep both, link them", effect="Open orders and BOMs use both numbers, so neither is removed; the link shows on the part.")),
        ImportQuestion(
            id="stock:count", kind="stock_count", file=None, covers=len(nostock), entries=list(nostock.part_number),
            question=f"The ERP export holds no stock levels, so {len(nostock)} bought parts with nothing on order are unknown rather than covered. Do you have a stock count to give?",
            examples=_examples([(r.part_number, "unknown", r.description[:50]) for r in nostock.itertuples()]),
            proposed=ImportProposed(answer="No count yet: leave them unknown",
                                    effect=f"A part with no open order stays unknown in build readiness. To give a count, change this to PART=QTY pairs, one per line, e.g. {ex_stock}=120; each part then reads as covered by stock or short.")),
    ]
    return qs


def deck(recipe_dir: Path | None = None, db: Path | None = None) -> ImportDeck:
    from app.db import DB_PATH

    recipe_dir, db = recipe_dir or RECIPE_DIR, db or DB_PATH
    base = _baseline(str(recipe_dir.resolve()), str(DATA_DIR))
    saved, pending = saved_decisions(recipe_dir, db), _read_json(_pending_path(db))
    qs = _questions(base)
    for q in qs:
        d = pending.get(q.id) or saved.get(q.id)
        if d:
            q.state = {"accept": "accepted", "change": "changed", "skip": "skipped"}[d["action"]]
            q.answer = q.proposed.answer if d["action"] == "accept" else d.get("value") if d["action"] == "change" else "Left as it is"
            q.answered_by, q.answered_at = d.get("by"), d.get("at")
    return ImportDeck(import_id=f"{recipe_dir.name}-" + build._recipe_hash(recipe_dir)[:8], questions=qs)


def answer(body: ImportAnswers, recipe_dir: Path | None = None, db: Path | None = None) -> ImportDeck:
    from app.db import DB_PATH

    recipe_dir, db = recipe_dir or RECIPE_DIR, db or DB_PATH
    known = {q.id for q in deck(recipe_dir, db).questions}
    pending = _read_json(_pending_path(db))
    for a in body.answers:
        if a.question_id not in known:
            raise KeyError(a.question_id)
        if a.action not in ("accept", "change", "skip"):
            raise ValueError(a.action)
        if a.action == "change" and not a.value:
            raise ValueError("a changed answer needs a value")
        pending[a.question_id] = {"action": a.action, "value": a.value, "by": body.answered_by, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _pending_path(db).write_text(json.dumps(pending, indent=1))
    return deck(recipe_dir, db)


def dry_run(recipe_dir: Path | None = None, db: Path | None = None) -> ImportDryRun:
    """The recipe on a copy with the current answers (nothing is written): rows in and out per file, what changed, and every load-gate check."""
    from app.db import DB_PATH

    recipe_dir, db = recipe_dir or RECIPE_DIR, db or DB_PATH
    eff = effective_decisions(recipe_dir, db)
    ctx = build.run_recipe(recipe_dir.resolve(), DATA_DIR, eff, links=build.approved_links(db))
    gate = run_gate(ctx)
    files: dict[str, ImportFileChange] = {}
    names = {"raw_suppliers": "suppliers.csv", "raw_parts": "parts.csv", "raw_bom": "bom.csv", "raw_purchase_orders": "purchase_orders.csv", "raw_demand_forecast": "demand_forecast.csv"}
    for clean, raw in RECONCILED.items():
        f = names[raw]
        files[f] = ImportFileChange(file=f, rows_in=len(ctx.t[raw]), rows_out=len(ctx.t[clean]), changes=[])
    for i in ctx.issues:
        if i["file"] in files and i["handling"] in ("fix", "infer", "link", "drop", "flag"):
            verb = {"fix": "fixed", "infer": "inferred", "link": "linked", "drop": "dropped", "flag": "flagged"}[i["handling"]]
            files[i["file"]].changes.append(f"{i['count']} {i['issue'][:70]} ({verb})")
    pend = _read_json(_pending_path(db))
    allq = {**saved_decisions(recipe_dir, db), **pend}
    return ImportDryRun(hash=decisions_hash(recipe_dir, db), files=list(files.values()), checks=[ImportCheck(name=n, passed=ok) for n, ok, _ in gate],
                        answers=ImportAnswerCounts(total=len(ACCEPT_ALL), changed=sum(1 for v in allq.values() if v["action"] == "change"), skipped=sum(1 for v in allq.values() if v["action"] == "skip")),
                        recipe_steps=len(list((recipe_dir / "steps").glob("[0-9][0-9]_*.py"))))


def approve(body: ImportApproval, recipe_dir: Path | None = None, db: Path | None = None) -> ImportLoaded:
    """Load what the dry run showed. Refused (AnswersChanged) if the answers changed since; writes the answers into the recipe and rebuilds the database."""
    from app.db import DB_PATH

    recipe_dir, db = recipe_dir or RECIPE_DIR, db or DB_PATH
    if body.hash != decisions_hash(recipe_dir, db):
        raise AnswersChanged()
    eff = effective_decisions(recipe_dir, db)
    stamped = {k: {**v, "approved_by": body.approved_by} for k, v in eff.items()}
    kept = build.runtime_decisions_path(db)      # beside the database, never inside the committed recipe
    ctx = build.run_recipe(recipe_dir.resolve(), DATA_DIR, stamped, links=build.approved_links(db))
    gate = run_gate(ctx)
    if any(not ok for _, ok, _ in gate):
        raise RuntimeError("the load gate failed: " + "; ".join(n for n, ok, _ in gate if not ok))
    build.load(ctx, gate, db, recipe_dir.resolve(), DATA_DIR)
    kept.write_text(yaml.safe_dump({"decisions": stamped}, sort_keys=True, allow_unicode=True))      # only once the load passed
    _pending_path(db).unlink(missing_ok=True)
    _baseline.cache_clear()
    try:  # a running server holds connections to the old file
        from app.db import engine

        if Path(str(engine.url.database)).resolve() == db.resolve():
            engine.dispose()
    except Exception:  # noqa: BLE001
        pass
    return ImportLoaded(loaded=True, built_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
