"""Replay a recipe: `python -m app.domain.imports.build --recipe ../recipes/<name>`.

Runs the recipe's steps in file order over the raw files, runs the load gate, and only if every check passes
writes `lookout.db` (atomically, from scratch, so a rebuild is idempotent). No model, no key, no network.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml
from sqlalchemy import create_engine, event, insert
from sqlalchemy.engine import Engine

from app import watcher
from app.domain.base import Base
from app.domain.common import AS_OF
from app.domain.imports import helpers
from app.domain.imports.context import Ctx
from app.domain.imports.gate import run_gate

# importing the models registers their tables on Base.metadata
from app.domain.bom import model as _bom  # noqa: F401
from app.domain.consignments import model as _consignments  # noqa: F401
from app.domain.demand import model as _demand  # noqa: F401
from app.domain.events import model as _events  # noqa: F401
from app.domain.imports import model as _imports  # noqa: F401
from app.domain.inbox import model as _inbox  # noqa: F401
from app.domain.news import model as _news  # noqa: F401
from app.domain.orders import model as _orders  # noqa: F401
from app.domain.parts import model as _parts  # noqa: F401
from app.domain.quotes import model as _quotes  # noqa: F401
from app.domain.stock import model as _stock  # noqa: F401
from app.domain.suppliers import model as _suppliers  # noqa: F401
from app.domain.tariffs import model as _tariffs  # noqa: F401

ROOT = Path(__file__).resolve().parents[4]


def _load_step(path: Path):
    spec = importlib.util.spec_from_file_location(f"recipe_step_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rows(ctx: Ctx) -> int:
    return sum(len(df) for name, df in ctx.t.items() if not name.startswith("raw_"))


IT_ADMIN = "IT (ERP admin)"   # the role that owns master-data questions; no person is named in the data


def _resolve_owners(ctx: Ctx) -> None:
    """Turn "@part:HR-1", "@parts:HR-1,HR-2" and "@suppliers:SUP-1" into the buyer who owns them (modal buyer)."""
    parts, po = ctx.t["parts"], ctx.t["po_lines"]
    names = {r.id: r.name for r in ctx.t["buyers"].itertuples()}

    def modal(series: pd.Series) -> str:
        s = series.dropna()
        return names[s.value_counts().idxmax()] if len(s) else IT_ADMIN

    full = {**names, **{r.name.split()[0]: r.name for r in ctx.t["buyers"].itertuples()}, "ERP admin": IT_ADMIN}
    for i in ctx.issues:
        i["owner"] = full.get(i["owner"], i["owner"])
        m = re.fullmatch(r"@(part|parts|suppliers):(.+)", i["owner"])
        if not m:
            continue
        ids = m.group(2).split(",")
        if m.group(1) in ("part", "parts"):
            i["owner"] = modal(parts[parts.part_number.isin(ids)].buyer_id)
        else:
            i["owner"] = modal(po[po.identity_id.isin(ids) | po.record_id.isin(ids)].buyer_id)


def approved_links(db: Path) -> list[dict]:
    """Links a person approved between supplier records (the approval ledger of the database about to be replaced); none if there is no database yet."""
    if not Path(db).exists():
        return []
    from app.domain.actions import ledger

    return ledger.supplier_links(db)


def runtime_decisions_path(db: Path) -> Path:
    """Where the person's approved answers from the Import screen live: `decisions.yaml` beside the database (gitignored), never inside the committed recipe."""
    return Path(db).with_name("decisions.yaml")


def run_recipe(recipe_dir: Path, data_dir: Path, decisions: dict | None = None, links: list[dict] | None = None, runtime: Path | None = None) -> Ctx:
    """Run the steps. `decisions` are the person's answers on the Import screen: they override the ones saved with the recipe (decisions.yaml, if the recipe commits any) and
    the ones a person approved earlier, kept beside the database (`runtime`).
    `links` are supplier links a person approved in the ledger: identity resolution applies them, as the person's stated answer, and never merges a record."""
    answers = yaml.safe_load((recipe_dir / "answers.yaml").read_text())
    answers["approved_links"] = list(links or [])
    saved = recipe_dir / "decisions.yaml"
    kept = lambda p: (yaml.safe_load(p.read_text()) or {}).get("decisions") or {} if p and p.exists() else {}      # noqa: E731
    answers["decisions"] = {**kept(saved), **kept(runtime), **(decisions or {})}
    ctx = Ctx(data=data_dir, answers=answers)
    helpers.configure_part_format(answers)
    step_rows = []
    steps = sorted((recipe_dir / "steps").glob("[0-9][0-9]_*.py"))
    watcher.emit("data", "build_started", f"replaying {len(steps)} steps from {recipe_dir.name}", steps=len(steps))
    for seq, path in enumerate(steps, 1):
        ctx.step = path.name
        mod = _load_step(path)
        before_rows, before_issues = _rows(ctx), len(ctx.issues)
        t0 = time.perf_counter()
        mod.run(ctx)
        secs = time.perf_counter() - t0
        title = (mod.__doc__ or path.stem).strip().splitlines()[0]
        step_rows.append(dict(seq=seq, step=path.name, title=title, rows_in=before_rows, rows_out=_rows(ctx),
                              issues=len(ctx.issues) - before_issues, seconds=round(secs, 3)))
        watcher.emit("data", "build_step", f"{path.name}: {title}", step=path.name, seconds=round(secs, 3),
                     issues=len(ctx.issues) - before_issues, rows=_rows(ctx))
    ctx.step = ""
    _resolve_owners(ctx)
    ctx.t["build_steps"] = pd.DataFrame(step_rows)
    return ctx


def _recipe_hash(recipe_dir: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(recipe_dir.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            h.update(p.relative_to(recipe_dir).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def _data_hashes(data_dir: Path) -> dict[str, str]:
    return {p.relative_to(data_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()[:16]
            for p in sorted(data_dir.rglob("*")) if p.is_file()}


def _engine(path: Path) -> Engine:
    eng = create_engine(f"sqlite:///{path}", future=True)

    @event.listens_for(eng, "connect")
    def _pragmas(conn, _):  # noqa: ANN001
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")

    return eng


def _records(df: pd.DataFrame) -> list[dict]:
    return df.astype(object).where(df.notna(), None).to_dict("records")


def _carry_over(old: Path, new: Path) -> None:
    """Keep what the recipe does not own. The records are rebuilt from the sources, but the approval ledger, the outbox, the supplier links and
    the run history are decisions people made and things that were sent: a rebuild (including an Import approval) must not erase them.
    Every table in the old file that the new file does not have is copied across, with its indexes."""
    if not old.exists():
        return
    con = sqlite3.connect(new)
    try:
        con.execute("ATTACH DATABASE ? AS old", (str(old),))
        have = {r[0] for r in con.execute("SELECT name FROM main.sqlite_master WHERE type = 'table'")}
        for name, sql in con.execute("SELECT name, sql FROM old.sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").fetchall():
            if name in have:
                continue
            con.execute(sql)
            con.execute(f'INSERT INTO main."{name}" SELECT * FROM old."{name}"')
            for (isql,) in con.execute("SELECT sql FROM old.sqlite_master WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL", (name,)).fetchall():
                con.execute(isql)
        con.commit()
        con.execute("DETACH DATABASE old")
    finally:
        con.close()


def load(ctx: Ctx, gate: list[tuple[str, bool, str]], out: Path, recipe_dir: Path, data_dir: Path) -> None:
    tmp = out.with_suffix(".db.tmp")
    for p in (tmp, Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm")):
        p.unlink(missing_ok=True)
    eng = _engine(tmp)
    Base.metadata.create_all(eng)
    ctx.t["data_issues"] = pd.DataFrame(ctx.issues).reset_index(drop=True)
    ctx.t["data_issues"].insert(0, "id", range(1, len(ctx.t["data_issues"]) + 1))
    ctx.t["row_drops"] = pd.DataFrame(ctx.drops, columns=["raw_table", "src_row", "reason", "kept_as", "step"])
    ctx.t["row_drops"].insert(0, "id", range(1, len(ctx.t["row_drops"]) + 1))
    ctx.t["load_gate"] = pd.DataFrame([dict(id=i, check=n, passed=int(ok), detail=d) for i, (n, ok, d) in enumerate(gate, 1)])
    counts = {name: len(df) for name, df in ctx.t.items() if not name.startswith("raw_")}
    ctx.t["build_meta"] = pd.DataFrame([
        dict(key="as_of", value=AS_OF.isoformat()),
        dict(key="company", value=str(ctx.answers.get("company", ""))),
        dict(key="supplier_risk", value=json.dumps(ctx.answers.get("supplier_risk") or {}, sort_keys=True)),
        dict(key="id_shapes", value=json.dumps(ctx.answers.get("id_shapes", {}))),
        dict(key="recipe", value=f"{recipe_dir.name} ({ctx.answers.get('kind', 'recipe')})"),
        dict(key="recipe_hash", value=_recipe_hash(recipe_dir)),
        dict(key="data_hashes", value=json.dumps(_data_hashes(data_dir))),
        dict(key="counts", value=json.dumps(counts)),
        dict(key="built_at", value=datetime.now(timezone.utc).isoformat(timespec="seconds")),
    ])
    with eng.begin() as conn:
        for table in Base.metadata.sorted_tables:
            df = ctx.t.get(table.name)
            if df is None:
                continue
            cols = [c.name for c in table.columns]
            extra = [c for c in df.columns if c not in cols and not c.startswith("_")]
            if extra:
                raise SystemExit(f"{table.name}: columns not in the schema: {extra}")
            records = _records(df[[c for c in cols if c in df.columns]])
            if records:
                conn.execute(insert(table), records)
        for name, df in ctx.t.items():
            if name.startswith("raw_"):
                df.to_sql(name, conn, index=False, if_exists="replace")
    eng.dispose()
    _carry_over(out, tmp)
    for suffix in ("", "-wal", "-shm"):
        Path(str(out) + suffix).unlink(missing_ok=True)
    os.replace(tmp, out)
    for suffix in ("-wal", "-shm"):
        Path(str(tmp) + suffix).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Rebuild lookout.db from the raw files by replaying a recipe.")
    ap.add_argument("--recipe", required=True, type=Path)
    ap.add_argument("--data", type=Path, default=ROOT / "data")
    ap.add_argument("--db", type=Path, default=None)
    args = ap.parse_args(argv)
    from app.db import DB_PATH

    out = args.db or DB_PATH
    ctx = run_recipe(args.recipe.resolve(), args.data.resolve(), links=approved_links(out), runtime=runtime_decisions_path(out))
    gate = run_gate(ctx)
    failed = [g for g in gate if not g[1]]
    for name, ok, detail in gate:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
        watcher.emit("data", "gate_check", f"{'pass' if ok else 'FAIL'}: {name}", severity="info" if ok else "error", detail=detail)
    if failed:
        print(f"\nload gate failed ({len(failed)} checks); no database written")
        return 1
    load(ctx, gate, out, args.recipe.resolve(), args.data.resolve())
    watcher.emit("data", "build_done", f"built {out.name}: {len(ctx.issues)} data issues", issues=len(ctx.issues))
    print(f"\nbuilt {out}  ({len(ctx.issues)} data issues, {len(ctx.drops)} rows dropped with a reason, {len(gate)} gate checks passed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
