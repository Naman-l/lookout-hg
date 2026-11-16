"""The Import conversation as code: questions that come from the recipe's own decisions, the person's answers, a dry run, an approval that loads.

No model is needed. Each question is a decision the bootstrap recipe already takes (which names are the same project, which vendor codes are one
company, what to do with what the data cannot say), grouped so one answer settles every entry it covers, with the proposed answer on the card. The
questions are the recipe's (`recipes/<customer>/questions.py`, a `questions(ctx)` function over the recipe run as proposed), never written here.
Answers wait in a pending file until the person approves; approval keeps them beside the database (`decisions.yaml`, gitignored; the recipe stays
as committed), with who and when, and rebuilds the database. The Data steward asks the same kind of question for files nobody has seen before.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import yaml

from app.domain.common.recipe import recipe_dir as _recipe_dir
from app.domain.imports import build
from app.domain.imports.gate import reconciled, run_gate
from app.domain.imports.schema import (ImportAnswerCounts, ImportApproval, ImportAnswers, ImportCheck, ImportDeck, ImportDryRun, ImportExample, ImportFileChange,
                                       ImportLoaded, ImportProposed, ImportQuestion)

ROOT = Path(__file__).resolve().parents[4]
RECIPE_DIR = _recipe_dir()
DATA_DIR = ROOT / "data"


def _recipe_questions(recipe_dir: Path):
    """The recipe's questions module, or None when the recipe asks nothing."""
    path = recipe_dir / "questions.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"recipe_questions_{recipe_dir.name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def accept_all(recipe_dir: Path) -> tuple[str, ...]:
    mod = _recipe_questions(recipe_dir)
    return tuple(getattr(mod, "ACCEPT_ALL", ())) if mod else ()


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
    return build.run_recipe(Path(recipe_dir), Path(data_dir), {k: {"action": "accept"} for k in accept_all(Path(recipe_dir))})


def _examples(rows) -> list[ImportExample]:
    return [ImportExample(from_=a, to=b, note=c) for a, b, c in rows[:3]]


def _questions(ctx, recipe_dir: Path) -> list[ImportQuestion]:
    mod = _recipe_questions(recipe_dir)
    return list(mod.questions(ctx, ImportQuestion, ImportProposed, _examples)) if mod else []


def deck(recipe_dir: Path | None = None, db: Path | None = None) -> ImportDeck:
    from app.db import DB_PATH

    recipe_dir, db = recipe_dir or RECIPE_DIR, db or DB_PATH
    base = _baseline(str(recipe_dir.resolve()), str(DATA_DIR))
    saved, pending = saved_decisions(recipe_dir, db), _read_json(_pending_path(db))
    qs = _questions(base, recipe_dir)
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
    names = dict(zip(ctx.t["_files"].raw_table, ctx.t["_files"].file)) if "_files" in ctx.t else {}
    for clean, spec in reconciled(ctx).items():
        raw = spec["raw"]
        if raw not in ctx.t or clean not in ctx.t:
            continue
        f = names.get(raw, raw)
        out = ctx.t[clean].query(spec["where"]) if spec.get("where") else ctx.t[clean]
        files[f] = ImportFileChange(file=f, rows_in=len(ctx.t[raw]), rows_out=len(out), changes=[])
    for i in ctx.issues:
        hit = next((f for f in files if f.startswith(i["file"]) or i["file"] in f), None)
        if hit and i["handling"] in ("fix", "infer", "link", "drop", "flag"):
            verb = {"fix": "fixed", "infer": "inferred", "link": "linked", "drop": "dropped", "flag": "flagged"}[i["handling"]]
            files[hit].changes.append(f"{i['count']} {i['issue'][:70]} ({verb})")
    pend = _read_json(_pending_path(db))
    allq = {**saved_decisions(recipe_dir, db), **pend}
    return ImportDryRun(hash=decisions_hash(recipe_dir, db), files=list(files.values()), checks=[ImportCheck(name=n, passed=ok) for n, ok, _ in gate],
                        answers=ImportAnswerCounts(total=len(accept_all(recipe_dir)), changed=sum(1 for v in allq.values() if v["action"] == "change"), skipped=sum(1 for v in allq.values() if v["action"] == "skip")),
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
