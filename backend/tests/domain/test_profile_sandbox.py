"""The Data steward's instruments: the profiler reads, the sandbox runs what the steward writes."""
import sys
from pathlib import Path

import pytest

from app.domain.imports import profile, sandbox
from app.domain.imports.context import Ctx

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"
STEPS = ROOT / "recipes" / "halden" / "steps"


# --- profiler ---
def test_profile_finds_the_known_mess():
    po = profile.profile_file(DATA / "purchase_orders.csv", DATA)
    cols = {c.name: c for c in po.columns}
    assert po.rows == 2622 and po.duplicate_rows == 6
    assert cols["uom"].distinct == 10 and cols["currency"].missing == 9 and cols["promised_date"].missing == 52
    assert set(cols["order_date"].date_formats) == {"YYYY-MM-DD", "MM/DD/YYYY"}          # two ERPs in one column
    assert {p for p, _ in cols["part_number"].patterns} >= {"AA-9{5}", "AA9{5}"}          # with and without the hyphen
    assert cols["unit_price"].outliers > 0
    parts = {c.name: c for c in profile.profile_file(DATA / "parts.csv", DATA).columns}
    assert parts["part_number"].is_candidate_key and parts["country_of_origin"].distinct == 32 and parts["country_of_origin"].missing == 22
    assert parts["hts_code"].missing == 44


def test_profile_handles_other_kinds():
    kinds = {f.file: f for f in profile.profile_all(DATA).files}
    assert kinds["quotes/pdf/BCX-Q-2609_BCX_Interconnect_quotation.pdf"].kind == "pdf"
    assert kinds["external/supplier_news.json"].rows == 23 and kinds["external/supplier_news.json"].columns[0].is_candidate_key
    assert kinds["quotes/2026-09-15_Holiday_notice_National_Day_2026.txt"].kind == "text"
    assert sum(1 for f in kinds.values() if f.kind == "email") == 13


def test_profile_joins_show_the_formatting_gap():
    j = {(x.left, x.right): x for x in profile.profile_all(DATA).joins}
    gap = j[("parts.csv.part_number", "purchase_orders.csv.part_number")]
    assert gap.overlap_pct < 95 and gap.normalised_overlap_pct == 100                       # a formatting gap, not missing records
    assert j[("purchase_orders.csv.supplier_id", "suppliers.csv.supplier_id")].overlap_pct == 100


def test_shape():
    assert profile.shape("HR-51110") == "AA-99999".replace("99999", "9{5}") and profile.shape("12/04/2024") == "99/99/9999"


# --- sandbox: the allowlist ---
@pytest.mark.parametrize("code,reason", [
    ("import socket\ndef run(ctx): pass", "import socket"),
    ("import os\ndef run(ctx): os.system('x')", "import os"),
    ("def run(ctx): open('/tmp/x', 'w')", "open"),
    ("def run(ctx): __import__('os')", "__import__"),
    ("import pandas as pd\ndef run(ctx): pd.read_csv('/etc/passwd')", ".read_csv"),
    ("def run(ctx): ctx.t['x'].to_csv('/tmp/y')", ".to_csv"),
    ("def run(ctx): ().__class__.__bases__", "dunder"),
    ("from app.organism import x\ndef run(ctx): pass", "is not allowed"),
    ("def run(ctx): eval('1')", "eval"),
    ("def not_run(ctx): pass", "must define run"),
])
def test_allowlist_refuses(code, reason):
    problems = sandbox.check_script(code)
    assert problems and any(reason in p for p in problems), problems


def test_allowlist_accepts_the_recipe_steps():
    for step in sorted(STEPS.glob("*.py")):
        src = step.read_text()
        problems = sandbox.check_script(src)
        # the bootstrap steps read files and parse PDFs/emails themselves (open/email/pypdf): only the table steps are written to the steward's contract
        if step.name[:2] in ("02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12", "13", "14", "15", "16", "17", "18"):
            assert not problems, (step.name, problems)


def test_write_step_script_validates(tmp_path):
    p = sandbox.write_step_script(tmp_path, "ok.py", "def run(ctx):\n    pass\n")
    assert p.exists()
    with pytest.raises(ValueError):
        sandbox.write_step_script(tmp_path, "bad.py", "import socket\ndef run(ctx): pass\n")
    assert not (tmp_path / "bad.py").exists()


# --- sandbox: running ---
def _ctx_after(n: int) -> Ctx:
    import importlib.util

    ctx = Ctx(data=DATA, answers=__import__("yaml").safe_load((ROOT / "recipes" / "halden" / "answers.yaml").read_text()))
    for step in sorted(STEPS.glob("[0-9][0-9]_*.py"))[:n]:
        spec = importlib.util.spec_from_file_location(step.stem, step)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        ctx.step = step.name
        mod.run(ctx)
    return ctx


def test_sandboxed_step_equals_in_process():
    import importlib.util

    a, b = _ctx_after(7), _ctx_after(7)                                                      # raw tables, suppliers, parts, bom, forecast, fx
    step = STEPS / "08_po_exact_duplicates.py"
    out = sandbox.run_step(a, step)
    assert out.ok, out.error
    spec = importlib.util.spec_from_file_location("s08", step)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    b.step = step.name
    mod.run(b)
    assert out.changed == ["po_lines"] and out.issues == 1 and out.drops == 6
    assert a.t["po_lines"].equals(b.t["po_lines"]) and a.issues == b.issues and a.drops == b.drops
    if sys.platform == "darwin":
        assert out.isolation == "sandbox-exec"


def test_failing_step_leaves_the_tables_alone(tmp_path):
    ctx = _ctx_after(1)
    before = {k: v.copy() for k, v in ctx.t.items()}
    p = sandbox.write_step_script(tmp_path, "boom.py", "def run(ctx):\n    ctx.t['raw_parts'] = ctx.t['raw_parts'].head(1)\n    raise RuntimeError('half done')\n")
    out = sandbox.run_step(ctx, p)
    assert not out.ok and "half done" in out.error
    assert all(ctx.t[k].equals(before[k]) for k in before)


def test_runaway_step_is_killed(tmp_path):
    p = sandbox.write_step_script(tmp_path, "loop.py", "def run(ctx):\n    while True:\n        pass\n")
    out = sandbox.run_step(_ctx_after(1), p, timeout=2, cpu_seconds=2)
    assert not out.ok and ("timeout" in out.error or out.error)


def test_refused_script_never_runs(tmp_path):
    p = tmp_path / "net.py"
    p.write_text("import socket\ndef run(ctx): pass\n")
    out = sandbox.run_step(_ctx_after(1), p)
    assert not out.ok and out.error.startswith("refused") and out.violations


@pytest.mark.skipif(sandbox._isolation() == "none", reason="no operating-system sandbox on this machine")
def test_operating_system_denies_network_and_writes_outside_scratch(tmp_path):
    code = ("import socket, sys\n"
            "try:\n    socket.create_connection(('1.1.1.1', 80), timeout=2); print('NET')\nexcept Exception: print('no-net')\n"
            "try:\n    open('/tmp/lookout-escape', 'w').write('x'); print('WROTE')\nexcept Exception: print('no-write')\n"
            "open('inside.txt', 'w').write('ok'); print('scratch-ok')\n")
    r = sandbox.run_python(code, tmp_path)
    assert "no-net" in r.stdout and "no-write" in r.stdout and "scratch-ok" in r.stdout and "NET" not in r.stdout.replace("no-net", "")
    assert not Path("/tmp/lookout-escape").exists()


def test_environment_is_scrubbed(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-secret")
    r = sandbox.run_python("import os; print(sorted(k for k in os.environ if 'KEY' in k or 'TOKEN' in k))", tmp_path)
    assert r.stdout.strip() == "[]"


# --- found by an independent attack suite (evals/sandbox_attack.py) ---
@pytest.mark.parametrize("code,why", [
    ("import pandas as pd\ndef run(ctx):\n    getattr(pd, 'read_' + 'csv')('/etc/hosts')", "getattr spells a denied attribute at run time"),
    ("import numpy as np\ndef run(ctx):\n    np.fromfile('/etc/hosts', dtype=np.uint8)", "a numpy reader"),
    ("import numpy as np\ndef run(ctx):\n    np.loadtxt('/etc/hosts', dtype=str)", "a numpy text loader"),
    ("import pandas as pd\ndef run(ctx):\n    pd.io.common.os.popen('cat /etc/hosts').read()", "a library re-exports os"),
    ("import pandas as pd\ndef run(ctx):\n    pd.io.common.os.listdir('/')", "a directory listing"),
    ("import numpy as np\ndef run(ctx):\n    np.save('/tmp/x', np.zeros(1))", "a numpy writer"),
    ("def run(ctx):\n    x = 'a'\n    y = x.__class__", "a dunder attribute"),
    ("def run(ctx):\n    print(type(ctx))", "type()"),
    ("def run(ctx):\n    s = '__subclasses__'", "a string naming a dunder attribute"),
])
def test_allowlist_closes_the_bypasses_found_by_the_attack_suite(code, why):
    assert sandbox.check_script(code), why


@pytest.mark.skipif(sandbox._isolation() != "sandbox-exec", reason="the read fence is the macOS operating-system sandbox")
def test_operating_system_fences_reads_even_if_the_allowlist_missed(tmp_path):
    import tempfile

    secret_dir = Path(tempfile.mkdtemp(prefix="lookout-secret-"))               # a sibling of the scratch directory, outside it
    canary = secret_dir / "canary.txt"
    canary.write_text("CANARY-123")
    home = Path.home()
    code = (f"import os\n"
            f"def attempt(label, fn):\n"
            f"    try:\n        fn(); print(label, 'READ')\n    except Exception as e:\n        print(label, 'denied')\n"
            f"attempt('canary', lambda: open({str(canary)!r}).read())\n"
            f"attempt('home', lambda: os.listdir({str(home)!r}))\n"
            f"attempt('ssh', lambda: open({str(home / '.ssh' / 'id_rsa')!r}).read())\n"
            f"attempt('scratch', lambda: open('here.txt', 'w').write('ok'))\n"
            f"attempt('data', lambda: os.listdir({str(DATA)!r}))\n")
    r = sandbox.run_python(code, tmp_path, read_allow=[DATA])
    out = dict(line.split() for line in r.stdout.strip().splitlines())
    assert out == {"canary": "denied", "home": "denied", "ssh": "denied", "scratch": "READ", "data": "READ"}, (out, r.stderr[-300:])
    assert not (Path("/tmp") / "lookout-escape").exists()


def test_a_malformed_result_is_a_failed_step_not_a_crash(tmp_path, monkeypatch):
    ctx = _ctx_after(1)
    p = sandbox.write_step_script(tmp_path, "ints.py", "import pandas as pd\ndef run(ctx):\n    ctx.t['raw_parts'] = pd.DataFrame([[1, 2], [3, 4]])\n")
    out = sandbox.run_step(ctx, p)                                         # integer column names: refused by the child's own check
    assert not out.ok and "text column names" in out.error
    ok = sandbox.write_step_script(tmp_path, "fine.py", "def run(ctx):\n    ctx.t['raw_parts'] = ctx.t['raw_parts'].head(2)\n")
    monkeypatch.setattr(sandbox, "load_table", lambda text: (_ for _ in ()).throw(KeyError("0")))     # whatever the child sends back, the parent does not raise
    before = len(ctx.t["raw_parts"])
    out = sandbox.run_step(ctx, ok)
    assert not out.ok and "could not be applied" in out.error and len(ctx.t["raw_parts"]) == before
