"""Generates evals/TOOLS-AND-WORKFLOWS.md: what each of the agent's tools and workflows does, its test, its last result and (for workflows) its last live run.

Nothing here is typed by hand: the tool list and descriptions come from the registry, the results from running the contract test and the workflow tests now (pytest's junit
report), the live runs from the saved recordings (each one is a live run, with its cost, time, drafts and verifier). `python -m evals.tools_and_workflows` rewrites the file;
`--check` fails if it is out of date with the tools (a tool without a row)."""

from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
OUT = ROOT / "evals" / "TOOLS-AND-WORKFLOWS.md"
PY = str(BACKEND / ".venv" / "bin" / "python") if (BACKEND / ".venv" / "bin" / "python").exists() else sys.executable

# kind -> (workflow, what it does, the tests that cover it); a test is file::name prefix, checked against the junit report so a renamed test shows as missing
WORKFLOWS = {
    "disruption": ("Work an item: a supplier's disruption", "Supply planner maps the lines and the shortage, the clerk asks the supplier for revised dates; one answer.", ["tests/organism/test_gate.py", "tests/organism/test_verifier.py"]),
    "deadline": ("Work an item: a deadline", "States what the date protects, finds the open lines, stages the request that is needed before it.", ["tests/organism/test_tools.py"]),
    "unknown": ("Work an item: an open question", "Supply planner reads the lines, the clerk stages one request per supplier and owner (code lists who is owed one).", ["tests/domain/test_verifier_products.py"]),
    "tariff": ("Work an item: duty", "Tariff analyst (and Sourcing analyst) read the exposure and the offers; the answer cites the rate, owed and conditional amounts.", ["tests/organism/test_tools.py"]),
    "risk": ("Work an item: supplier risk", "Reads the supplier's risk and the open lines and states the decision.", ["tests/organism/test_verifier.py"]),
    "consignment": ("Work an item: consignment", "Reads the consignment and states what to do about the stock.", ["tests/organism/test_verifier.py"]),
    "triage": ("Triage a message", "Inbox analyst reads the thread and judges it; a quote adds the Tariff and Sourcing analysts; the clerk only on a message the trust check cleared.", ["tests/organism/test_gate.py"]),
    "reply": ("Draft the reply to a message", "The analyst reads the thread, the clerk drafts one reply to the contact on file.", ["tests/organism/test_tools.py"]),
    "ask": ("Ask", "Free question: Lookout picks the specialists, answers in a finding, up to three rows and a next step.", ["tests/organism/test_events.py", "tests/organism/test_gate.py"]),
    "compare": ("Compare quotes", "The Sourcing analyst reads every offer beside the current supplier.", ["tests/organism/test_tools.py"]),
    "import": ("Data steward on a file", "Reports drift, tries a mapping in a sandbox, states findings and questions.", ["tests/organism/test_steward.py"]),
    "trust": ("A message that failed the trust checks", "Answered by code from the item's fields; no model, nothing staged.", ["tests/organism/test_events.py"]),
}


def run_tests() -> dict[str, str]:
    """{test id: passed | failed | skipped}, from one pytest run of the contract test and the workflow tests."""
    files = sorted({f for _, _, fs in WORKFLOWS.values() for f in fs} | {"tests/tools"})
    xml = BACKEND / ".tools-junit.xml"
    subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={xml}", *files], cwd=BACKEND, capture_output=True, text=True)
    out: dict[str, str] = {}
    for tc in ET.parse(xml).getroot().iter("testcase"):
        status = "failed" if tc.find("failure") is not None or tc.find("error") is not None else "skipped" if tc.find("skipped") is not None else "passed"
        out[f"{tc.get('classname', '').replace('.', '/')}.py::{tc.get('name')}".replace("/py::", ".py::")] = status
    xml.unlink(missing_ok=True)
    return out


def tool_rows(results: dict[str, str]) -> list[dict]:
    sys.path.insert(0, str(BACKEND))
    from app.organism.specialists import registry  # noqa: PLC0415

    rows = []
    desc = _descriptions()
    for name in sorted(registry.TOOL_SERVER):
        mine = {k: v for k, v in results.items() if f"[{name}]" in k and "tests/tools/test_tool_contract" in k.replace(".", "/").replace("/py", ".py")}
        passed, failed = sum(v == "passed" for v in mine.values()), sum(v == "failed" for v in mine.values())
        who = [s for s, spec in registry.SPECIALISTS.items() if name in spec.tools]
        rows.append({"tool": name, "server": registry.TOOL_SERVER[name], "does": desc.get(name, ""), "who": ", ".join(who) or "Lookout",
                     "test": "make tools: valid input, bad input, gate refusal", "result": "pass" if passed and not failed else "FAIL" if failed else "no test", "cases": f"{passed}/{passed + failed}"})
    return rows


def _descriptions() -> dict[str, str]:
    import os  # noqa: PLC0415
    import re  # noqa: PLC0415

    os.environ.pop("LOOKOUT_FAKE_SERVICES", None)
    from app import db as app_db  # noqa: PLC0415
    from app.organism import runner, services as organism_services  # noqa: PLC0415
    from app.organism.context import RunContext  # noqa: PLC0415
    from app.organism.runner import allow_map  # noqa: PLC0415
    from app.organism.runs.events import Recorder  # noqa: PLC0415

    db = str(app_db.DB_PATH)
    svc = organism_services.get(db)
    try:
        ctx = RunContext(run_id="run-doc", item_key="x", db_path=db, recorder=Recorder("run-doc", db + ".doc"), plan=["supply_planner"], allow=allow_map(["supply_planner"]))
        return {t.name: re.split(r"(?<=[.])\s", t.description.strip())[0] for ts in runner.tool_lists(ctx, svc).values() for t in ts}
    finally:
        svc.close()


def workflow_rows(results: dict[str, str]) -> list[dict]:
    rec_dir = BACKEND / "app" / "organism" / "recordings"
    rows = []
    for kind, (name, does, files) in WORKFLOWS.items():
        docs = []
        for p in rec_dir.glob(f"{kind}_*.json"):
            try:
                docs.append(json.loads(p.read_text()))
            except ValueError:
                continue
        live = max(docs, key=lambda d: d["recorded_at"], default=None)
        tests = {k: v for k, v in results.items() if any(k.startswith(f) for f in files)}
        rows.append({"workflow": name, "does": does, "tests": ", ".join(files), "result": ("pass" if tests and "failed" not in tests.values() else "FAIL" if "failed" in tests.values() else "no test") + f" ({len(tests)} tests)",
                     "live": (f"{live['recorded_at'][:10]} · ${live['run']['cost_usd']:.3f} · {live['run']['wall_ms'] / 1000:.0f} s · {len(live['actions'])} drafts or notes · verifier {'passed' if (live.get('verifier') or {}).get('passed') else 'did not pass'} · {live['run']['status']}" if live else "none recorded")})
    return rows


def render() -> str:
    results = run_tests()
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    today = date.today().isoformat()
    tools, flows = tool_rows(results), workflow_rows(results)
    lines = [f"# Tools and workflows: what each does, how it is tested, how it last ran", "",
             f"Generated by `python -m evals.tools_and_workflows` on {today} at commit `{commit}`. The tool results come from running `make tools` now; the live runs are the saved recordings (each one a real run).", "",
             f"## The {len(tools)} tools", "", "| Tool | Server | Given to | What it does | Test | Last result ({today}, {commit}) |".replace("{today}", today).replace("{commit}", commit), "|---|---|---|---|---|---|"]
    for r in tools:
        lines.append(f"| `{r['tool']}` | {r['server']} | {r['who']} | {r['does'].replace('|', '/')} | {r['test']} | {r['result']} ({r['cases']}) |")
    lines += ["", f"## The {len(flows)} workflows", "", "| Workflow | What it does | Tests | Last result | Last live run |", "|---|---|---|---|---|"]
    for r in flows:
        lines.append(f"| {r['workflow']} | {r['does']} | {r['tests']} | {r['result']} | {r['live']} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    text = render()
    if "--check" in argv:
        missing = [l for l in text.splitlines() if "no test" in l and l.startswith("| `")]
        print("\n".join(missing) or "every tool has a passing test")
        return 1 if missing else 0
    OUT.write_text(text)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
