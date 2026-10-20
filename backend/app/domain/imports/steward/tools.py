"""The Data steward's tools. All code over DOMAIN's profiler and sandbox; the steward (a model) judges and writes one script.

  drift_report   what the incoming file looks like against the known export (columns, formats, likely renames)
  column_facts   counts for one column: blanks, distinct values, value shapes, so a finding's count comes from code
  try_step       run a normaliser script in the sandbox on the incoming file and check the result like the load gate
  add_finding    a defect in plain words with a count (from a tool), the consequence and an example
  add_question   one flashcard: a question only a person can answer, with the proposed answer

Nothing here loads data. The steward's output is a proposed step, findings and questions for a person to approve."""

from __future__ import annotations

import re
import shutil
from decimal import Decimal
import tempfile
from pathlib import Path

import pandas as pd
from claude_agent_sdk import tool

from ....organism.context import RunContext
from ....organism.toolkit import READ, STAGE, plain_number, refuse, reply
from ...values import unknown
from ..context import Ctx
from ..profile import shape
from ..sandbox import run_step
from . import checks, drift

MAX_ATTEMPTS = 4  # tries the steward gets at one file; the gate caps `try_step` at this (organism/workflows/import_file.py)


def start(ctx: RunContext, path: Path) -> dict:
    """The steward's workspace for one run: the incoming file (copied to its own directory), the known export it resembles, and what has been tried."""
    work = Path(tempfile.mkdtemp(prefix="lookout-steward-"))
    incoming = work / "incoming"
    incoming.mkdir()
    shutil.copy(path, incoming / path.name)
    report = drift.drift_report(incoming / path.name)
    ctx.steward = {
        "dir": work, "incoming": incoming, "file": path.name, "source": pd.read_csv(incoming / path.name, dtype=str, keep_default_na=False), "report": report,
        "expected": drift.known_export(report["looks_like"]) if report["looks_like"] else pd.DataFrame(), "attempts": 0, "best": None, "last": None, "findings": [], "questions": [],
    }
    return ctx.steward


def make_tools(ctx: RunContext, svc=None):
    S = lambda: ctx.steward  # noqa: E731

    @tool("drift_report", "How the incoming file differs from the known export it resembles: expected, missing and new columns, samples and value shapes per column, likely renames (a hint from value shapes and names, not a decision) and columns whose format changed. It compares with the closest known export by column mapping; if you read the file as a different export, pass its name as `table` (purchase_orders, parts, bom, suppliers, demand_forecast) and the comparison is redone against that one.", {"type": "object", "properties": {"table": {"type": "string", "enum": sorted(drift.KNOWN)}}}, annotations=READ)
    async def drift_report(args):
        if args.get("table"):
            if args["table"] not in drift.KNOWN:
                return refuse(f"no known export {args['table']!r}; the known exports are {sorted(drift.KNOWN)}")
            S()["report"] = drift.drift_report(S()["incoming"] / S()["file"], table=args["table"])
            S()["expected"] = drift.known_export(args["table"])
        r, src = S()["report"], S()["source"]
        cols = [{"column": c, "samples": [v for v in src[c].head(40).tolist() if v][:3], "shapes": sorted(drift.shapes(src[c]))[:3], "blank": int((src[c] == "").sum())} for c in src.columns]
        f = S()["file"]
        numbers = [plain_number(f"import:{f}:rows", f"Rows in {f}", r["rows"], "rows"), plain_number(f"import:{f}:columns_found", "Columns found", len(r["found_columns"]), "columns"),
                   plain_number(f"import:{f}:columns_expected", f"Columns the known export has ({r['known_export']})", len(r["expected_columns"]), "columns"),
                   plain_number(f"import:{f}:columns_missing", "Expected columns not found under their name", len(r["missing"]), "columns"),
                   plain_number(f"import:{f}:columns_new", "Columns found that the known export does not have", len(r["new"]), "columns")]
        exp = S()["expected"]
        expected_cols = [{"column": c, "samples": [v for v in exp[c].head(40).tolist() if v][:3], "shapes": sorted(drift.shapes(exp[c]))[:3]} for c in exp.columns]
        data = {"file": f, "looks_like": r["looks_like"], "known_export": r["known_export"], "match": r["match"], "expected_columns": expected_cols, "found": cols,
                "missing": r["missing"], "new": r["new"], "likely_renames": r["likely_renames"], "same_name_new_format": r["same_name_new_format"]}
        return reply(ctx, f"{f} looks like the {r['looks_like'].replace('_', ' ')} export with {len(r['missing'])} columns renamed or missing and {len(r['new'])} new", data, numbers)

    @tool("column_facts", "Counts for one column of the incoming file: blank values, distinct values, and how many values have each shape. Use it to get the number behind a finding.", {"column": str}, annotations=READ)
    async def column_facts(args):
        src, c = S()["source"], args["column"]
        if c not in src.columns:
            return refuse(f"no column {c!r}; the columns are {list(src.columns)}")
        shp = src[c][src[c] != ""].map(shape).value_counts()
        f = S()["file"]
        numbers = [plain_number(f"import:{f}:{c}:blank", f"Blank values in {c}", int((src[c] == "").sum()), "rows"), plain_number(f"import:{f}:{c}:distinct", f"Distinct values in {c}", src[c].nunique(), "values")]
        numbers += [plain_number(f"import:{f}:{c}:shape:{i}", f"Values in {c} shaped {sh}", int(n), "rows") for i, (sh, n) in enumerate(shp.head(4).items())]
        return reply(ctx, f"{c}: {int((src[c] == '').sum())} blank, {src[c].nunique()} distinct, {len(shp)} shapes", {"column": c, "shapes": shp.head(6).to_dict()}, numbers)

    @tool(
        "try_step",
        "Write and try ONE normaliser step on the incoming file. `code` is a Python script defining `run(ctx)`: read the file with ctx.read_csv('<the file name>') "
        "(every value comes back as text), rename and reformat columns so they match the known export exactly (same column names in the same order, values written the "
        "way the known export writes them), drop the new columns you cannot place, and store the result as `ctx.t['normalised']`. Allowed: pandas, numpy, re, datetime, "
        "decimal, math, json, collections, itertools, string, and app.domain.imports.helpers. No file access except ctx.read_csv. It runs in a sandbox on a copy; the result is "
        f"checked in code (columns, row count, values kept, formats). You have {MAX_ATTEMPTS} attempts.",
        {"name": str, "code": str},
        annotations=STAGE,
    )
    async def try_step(args):
        st = S()
        st["attempts"] += 1
        name = re.sub(r"[^a-z0-9_]", "_", args["name"].lower())[:40] or "normalise"
        script = st["dir"] / f"{st['attempts']:02d}_{name}.py"
        script.write_text(args["code"], encoding="utf-8")
        sctx = Ctx(data=st["incoming"], answers={}, t={})
        outcome = run_step(sctx, script)
        f = st["file"]
        st["last"] = {"script": script.name, "ok": False}
        if not outcome.ok:
            msg = (outcome.error or "failed")[:600]
            return reply(ctx, f"Attempt {st['attempts']} failed in the sandbox: {msg[:120]}", {"attempt": st["attempts"], "ok": False, "error": msg, "violations": outcome.violations, "isolation": outcome.isolation})
        out = sctx.t.get("normalised")
        if out is None:
            return reply(ctx, f"Attempt {st['attempts']} ran but stored no `ctx.t['normalised']`", {"attempt": st["attempts"], "ok": False, "error": "store the result as ctx.t['normalised']"})
        result = checks.gate(st["source"], out.astype(str), st["expected"])
        passed = all(c["passed"] for c in result)
        numbers = [plain_number(f"import:{f}:rows_in", "Rows in", len(st["source"]), "rows"), plain_number(f"import:{f}:rows_out", "Rows out", len(out), "rows"),
                   plain_number(f"import:{f}:checks_passed", "Checks passed", sum(c["passed"] for c in result), "checks"), plain_number(f"import:{f}:checks_total", "Checks run", len(result), "checks")]
        st["last"] = {"script": script.name, "ok": passed, "checks": result, "rows_out": len(out)}
        if passed:
            st["best"] = {"script": script.name, "code": args["code"], "rows_in": len(st["source"]), "rows_out": len(out), "checks": result, "seconds": outcome.seconds, "isolation": outcome.isolation}
        data = {"attempt": st["attempts"], "ok": passed, "checks": result, "isolation": outcome.isolation, "seconds": outcome.seconds,
                "before": st["source"].head(2).to_dict(orient="records"), "after": out.head(2).astype(str).to_dict(orient="records")}
        return reply(ctx, f"Attempt {st['attempts']}: {sum(c['passed'] for c in result)} of {len(result)} checks passed, {len(out)} rows out", data, numbers)

    @tool(
        "add_finding",
        "Record one defect or difference in the incoming file in plain words: what it is, how many rows it affects (a count a tool returned), what it would cost if nobody dealt with it, and an example.",
        {"issue": str, "count": int, "consequence": str, "example": str, "handling": {"type": "string", "enum": ["fix", "infer", "flag", "leave", "drop"]}},
        annotations=STAGE,
    )
    async def add_finding(args):
        if Decimal(args["count"]) not in ctx.seen_numerals and args["count"] != 0:
            return refuse(f"{args['count']} is not a count any tool returned; get it from column_facts or drift_report")
        S()["findings"].append({k: args[k] for k in ("issue", "count", "consequence", "example")} | {"handling": args.get("handling", "fix")})
        return reply(ctx, f"Finding recorded: {args['issue']} ({args['count']})", {"findings": len(S()["findings"])})

    @tool(
        "add_question",
        "Ask the person ONE question that only they can answer (what a new column means, which of two columns is the order quantity, what to do with values you cannot place), with your proposed answer. "
        "Group everything that has the same answer into one card. Give how many rows it covers (a tool count).",
        {"question": str, "why_it_blocks": str, "proposed_answer": str, "covers": int},
        annotations=STAGE,
    )
    async def add_question(args):
        card = unknown(args["question"], args["why_it_blocks"], "unassigned", f"{args['question']} Proposed: {args['proposed_answer']}")
        S()["questions"].append(card)
        ctx.unknowns.append(card)
        return reply(ctx, f"Question for the person: {args['question']}", {"cards": len(S()["questions"])})

    return [drift_report, column_facts, try_step, add_finding, add_question]

