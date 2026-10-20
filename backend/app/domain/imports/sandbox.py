"""Run a model-written recipe step safely: AST allowlist, a separate process, no network, writes only to a scratch directory, CPU and time limits.

The Data steward writes steps; this decides whether and how they run. A step has the recipe shape (`run(ctx)`). It sees copies of the tables, never the
originals; what it changes comes back as data and is applied to the real context only when the step succeeds, so a failing or hostile step leaves the
tables as they were. The raw files are read-only (the OS sandbox denies every write outside the scratch directory).

Isolation, in order of strength (reported in every outcome, never silent):
  sandbox-exec (macOS)  the operating system denies the network, every write outside the scratch directory, and every read under the user's home and the
                        temporary directories except scratch, the backend (its virtual environment) and the raw data directory
  unshare -n (Linux)    a new network namespace, when the kernel allows it; reads are NOT fenced here, only the AST check limits them
  none                  the AST check and a scrubbed environment only
The AST allowlist is the first fence and is deliberately strict (no getattr, no `os`/`io`/`sys` attribute chains, no file readers or writers); the operating
system is the fence that does not depend on the allowlist having missed nothing.
"""

from __future__ import annotations

import ast
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from app.domain.common import AS_OF
from app.domain.imports.context import Ctx

BACKEND = Path(__file__).resolve().parents[3]
ALLOWED_IMPORTS = {"pandas", "numpy", "re", "datetime", "decimal", "math", "json", "csv", "collections", "itertools", "functools", "string", "unicodedata",
                   "statistics", "typing", "dataclasses", "app.domain.imports.helpers", "app.domain.imports.context", "app.domain.common"}
DENIED_NAMES = {"open", "eval", "exec", "compile", "__import__", "globals", "locals", "vars", "input", "breakpoint", "exit", "quit", "memoryview",
                "getattr", "setattr", "delattr", "type", "super", "__builtins__", "__loader__", "__spec__"}  # getattr spells a denied attribute at run time
DENIED_ATTRS = {"read_csv", "read_pickle", "read_json", "read_excel", "read_parquet", "read_sql", "read_html", "read_feather", "read_table", "read_fwf", "read_xml",
                "to_csv", "to_pickle", "to_json", "to_excel", "to_parquet", "to_sql", "to_feather", "to_html", "to_xml", "to_hdf", "to_clipboard", "read_clipboard",
                "write_text", "write_bytes", "open", "unlink", "rmdir", "mkdir", "touch", "chmod", "eval",
                # numpy readers and writers, and the modules a library re-exports (pd.io.common.os.popen): an attribute chain is not an import
                "fromfile", "tofile", "loadtxt", "genfromtxt", "load", "save", "savez", "savez_compressed", "savetxt", "memmap", "ctypeslib", "fromregex",
                "os", "io", "sys", "subprocess", "builtins", "importlib", "shutil", "pathlib", "socket", "ctypes", "pickle", "marshal", "tempfile", "glob", "fnmatch",
                "mmap", "signal", "resource", "platform", "inspect", "gc", "code", "runpy", "pty", "fcntl", "popen", "listdir", "scandir", "walk", "urlopen", "urllib"}


@dataclass
class Outcome:
    ok: bool
    error: str | None = None
    stdout: str = ""
    seconds: float = 0.0
    isolation: str = "none"
    violations: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)  # tables the step replaced
    issues: int = 0
    drops: int = 0


def check_script(source: str) -> list[str]:
    """Reasons a script may not run. Empty means it passed the allowlist. This is the first fence; the operating system is the second."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [f"syntax error: {e.msg} (line {e.lineno})"]
    bad: list[str] = []
    has_run = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            has_run = True
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name not in ALLOWED_IMPORTS and a.name.split(".")[0] not in ALLOWED_IMPORTS:
                    bad.append(f"import {a.name} is not allowed (line {node.lineno})")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level or (mod not in ALLOWED_IMPORTS and mod.split(".")[0] not in ALLOWED_IMPORTS):
                bad.append(f"from {'.' * node.level}{mod} import ... is not allowed (line {node.lineno})")
        elif isinstance(node, ast.Name) and node.id in DENIED_NAMES:
            bad.append(f"{node.id} is not allowed (line {node.lineno})")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and any(n in node.value for n in ("__class__", "__globals__", "__builtins__", "__subclasses__")):
            bad.append(f"a string naming a dunder attribute is not allowed (line {node.lineno})")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                bad.append(f"dunder attribute {node.attr} is not allowed (line {node.lineno})")
            elif node.attr in DENIED_ATTRS and not (node.attr == "read_csv" and isinstance(node.value, ast.Name) and node.value.id == "ctx"):
                bad.append(f".{node.attr} is not allowed (line {node.lineno})")
    if not has_run:
        bad.append("the script must define run(ctx)")
    return bad


def write_step_script(directory: Path, name: str, code: str) -> Path:
    """Save a step the steward wrote, but only if it passes the allowlist. Returns the path; raises ValueError listing the violations."""
    problems = check_script(code)
    if problems:
        raise ValueError("; ".join(problems))
    path = Path(directory) / name
    path.write_text(code, encoding="utf-8")
    return path


def _isolation() -> str:
    if platform.system() == "Darwin" and shutil.which("sandbox-exec"):
        return "sandbox-exec"
    if platform.system() == "Linux" and shutil.which("unshare"):
        ok = subprocess.run(["unshare", "-rn", "true"], capture_output=True).returncode == 0
        return "unshare" if ok else "none"
    return "none"


# Where a step can never read, whatever the allowlist missed: the user's home and every temporary directory (the scratch directory is allowed back below).
READ_DENIED = ("/Users", "/Volumes", "/home", "/private/var/folders", "/private/tmp", "/private/var/tmp", "/tmp", "/var/tmp")


def _profile(scratch: Path, read_allow: list[Path] = ()) -> str:
    """sandbox-exec profile: no network; writes only to scratch; reads denied under home and the temp directories except scratch and the listed paths.
    The last matching rule wins, so the allows follow the denies. File metadata (stat) stays readable so Python can resolve its own paths."""
    allow = "".join(f'(allow file-read-data (subpath "{Path(p).resolve()}"))' for p in [scratch, *read_allow])   # same operation as the deny: a wildcard allow does not override it
    deny = "".join(f'(deny file-read-data (subpath "{d}"))' for d in READ_DENIED)
    return ('(version 1)(allow default)(deny network*)' + deny + allow +
            f'(deny file-write* (require-all (require-not (subpath "{scratch.resolve()}")) (require-not (literal "/dev/null")) (require-not (literal "/dev/dtracehelper"))))')


def _limits(cpu_seconds: int):
    def apply():
        import resource

        os.setsid()
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        resource.setrlimit(resource.RLIMIT_FSIZE, (200 * 2**20, 200 * 2**20))
        try:
            resource.setrlimit(resource.RLIMIT_AS, (4 * 2**30, 4 * 2**30))
        except (ValueError, OSError):  # not enforced on every platform
            pass
    return apply


def dump_table(df: pd.DataFrame) -> str:
    return json.dumps({"columns": list(df.columns), "dtypes": {c: str(t) for c, t in df.dtypes.items()},
                       "data": json.loads(df.to_json(orient="values", date_format="iso", default_handler=str))})


def load_table(text: str) -> pd.DataFrame:
    p = json.loads(text)
    df = pd.DataFrame(p["data"], columns=p["columns"])
    for c, t in p["dtypes"].items():
        if t == "object":
            df[c] = df[c].astype(object).where(df[c].notna(), None)
        else:
            df[c] = df[c].astype(t)
    return df


def run_python(code: str, scratch: Path, *, timeout: float = 30, cpu_seconds: int = 20, isolation: str | None = None, read_allow: list[Path] = ()) -> subprocess.CompletedProcess:
    read_allow = [*read_allow, Path(sys.prefix), BACKEND]   # the interpreter's own environment must be readable
    """Run raw Python in the OS sandbox (used by the step runner, and by the tests of the sandbox itself)."""
    iso = isolation or _isolation()
    cmd = [sys.executable, "-I", "-c", code]
    if iso == "sandbox-exec":
        cmd = ["sandbox-exec", "-p", _profile(scratch, read_allow)] + cmd
    elif iso == "unshare":
        cmd = ["unshare", "-rn"] + cmd
    env = {"PATH": "/usr/bin:/bin", "HOME": str(scratch), "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8",   # no keys, no proxies
           "LOOKOUT_AS_OF": AS_OF.isoformat()}   # the data date, handed down: the child may not read the recipe to find it
    proc = subprocess.Popen(cmd, cwd=scratch, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, preexec_fn=_limits(cpu_seconds))
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


_CHILD = r"""
import json, sys, traceback, importlib.util, io, contextlib
sys.dont_write_bytecode = True
req = json.load(open('request.json'))
sys.path.insert(0, req['backend'])
import pandas as pd
from app.domain.imports.sandbox import load_table, dump_table
from app.domain.imports.context import Ctx
from pathlib import Path
res = {'ok': False, 'error': None}
buf = io.StringIO()
try:
    tables = {name: load_table(Path('in', name + '.json').read_text()) for name in req['tables']}
    before = {name: dump_table(df) for name, df in tables.items()}
    ctx = Ctx(data=Path(req['data']), answers=req['answers'], t=tables)
    ctx.step = req['step']
    spec = importlib.util.spec_from_file_location('sandboxed_step', 'step.py')
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    with contextlib.redirect_stdout(buf):
        mod.run(ctx)
    changed = []
    Path('out').mkdir(exist_ok=True)
    for name, df in ctx.t.items():
        if not isinstance(df, pd.DataFrame) or not all(isinstance(c, str) for c in df.columns):
            raise ValueError('table ' + repr(name) + ' must be a DataFrame with text column names')
        text = dump_table(df)
        if name not in before or text != before[name]:
            Path('out', name + '.json').write_text(text); changed.append(name)
    Path('out', 'issues.json').write_text(json.dumps(ctx.issues, default=str))
    Path('out', 'drops.json').write_text(json.dumps(ctx.drops, default=str))
    res.update(ok=True, changed=changed)
except BaseException as e:
    res.update(error=''.join(traceback.format_exception_only(type(e), e)).strip())
res['stdout'] = buf.getvalue()[-4000:]
Path('result.json').write_text(json.dumps(res))
"""


def run_step(ctx: Ctx, script: Path, *, timeout: float = 60, cpu_seconds: int = 30, isolation: str | None = None) -> Outcome:
    """Run one step in the sandbox. On success its changes are applied to `ctx`; on any failure `ctx` is untouched."""
    script = Path(script)
    problems = check_script(script.read_text(encoding="utf-8"))
    iso = isolation or _isolation()
    if problems:
        return Outcome(ok=False, error="refused: " + "; ".join(problems), violations=problems, isolation=iso)
    scratch = Path(tempfile.mkdtemp(prefix="lookout-sandbox-"))
    t0 = time.perf_counter()
    try:
        (scratch / "in").mkdir()
        for name, df in ctx.t.items():
            (scratch / "in" / f"{name}.json").write_text(dump_table(df))
        (scratch / "step.py").write_text(script.read_text(encoding="utf-8"))   # the child reads its own copy: nothing outside scratch is needed for the script
        (scratch / "request.json").write_text(json.dumps({"backend": str(BACKEND), "data": str(ctx.data), "answers": ctx.answers, "step": script.name, "tables": list(ctx.t)}, default=str))
        try:
            proc = run_python(_CHILD, scratch, timeout=timeout, cpu_seconds=cpu_seconds, isolation=iso, read_allow=[BACKEND, Path(ctx.data)])
        except subprocess.TimeoutExpired:
            return Outcome(ok=False, error=f"timeout after {timeout:g} s", seconds=round(time.perf_counter() - t0, 3), isolation=iso)
        secs = round(time.perf_counter() - t0, 3)
        result_path = scratch / "result.json"
        if not result_path.exists():
            return Outcome(ok=False, error=(proc.stderr or f"exit {proc.returncode}").strip()[-1500:], seconds=secs, isolation=iso)
        res = json.loads(result_path.read_text())
        if not res["ok"]:
            return Outcome(ok=False, error=res["error"], stdout=res.get("stdout", ""), seconds=secs, isolation=iso)
        try:  # whatever comes back is data from an untrusted process: a malformed result is a failed step, not a crash
            incoming = {name: load_table((scratch / "out" / f"{name}.json").read_text()) for name in res["changed"]}
            issues = json.loads((scratch / "out" / "issues.json").read_text())
            drops = json.loads((scratch / "out" / "drops.json").read_text())
            if not all(isinstance(c, str) for df in incoming.values() for c in df.columns):
                raise ValueError("a table came back with non-text column names")
        except Exception as e:  # noqa: BLE001
            return Outcome(ok=False, error=f"the step's result could not be applied: {type(e).__name__}: {str(e)[:200]}", stdout=res.get("stdout", ""), seconds=secs, isolation=iso)
        ctx.t.update(incoming)
        have = {i["key"] for i in ctx.issues}
        new_issues = [i for i in issues if i["key"] not in have]
        ctx.issues.extend(new_issues)
        new_drops = drops  # the child starts with empty lists: everything in them is this step's
        ctx.drops.extend(new_drops)
        return Outcome(ok=True, stdout=res.get("stdout", ""), seconds=secs, isolation=iso, changed=res["changed"], issues=len(new_issues), drops=len(new_drops))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
