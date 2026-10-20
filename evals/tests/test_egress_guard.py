import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from evals import agent_runner, graders
from evals.run import ROOT

CODE = """
import socket, sys
srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
c = socket.socket(); c.connect(("127.0.0.1", srv.getsockname()[1]))        # this machine: allowed
out = []
for what in ("connect", "lookup"):
    try:
        if what == "connect":
            socket.socket().connect(("192.0.2.1", 80))
        else:
            socket.getaddrinfo("example.com", 80)
        out.append("allowed")
    except OSError as e:
        out.append("blocked" if "egress blocked" in str(e) else "other:" + str(e))
print(",".join(out))
"""


def _run(guard: bool, tmp: Path):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "evals" / "sandbox"), "LOOKOUT_EGRESS_LOG": str(tmp / "egress.ndjson"), **({"LOOKOUT_EGRESS_GUARD": "1"} if guard else {})}
    return subprocess.run([sys.executable, "-c", CODE], env=env, capture_output=True, text=True, timeout=30)


def test_the_guard_refuses_anything_off_this_machine_and_writes_it_down(tmp_path):
    r = _run(True, tmp_path)
    assert r.stdout.strip() == "blocked,blocked", r.stderr
    log = [json.loads(x) for x in (tmp_path / "egress.ndjson").read_text().splitlines()]
    assert {x["kind"] for x in log} == {"connect", "lookup"} and any("192.0.2.1" in x["target"] for x in log)


def test_without_the_guard_nothing_is_changed(tmp_path):
    code = 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(1); c = socket.socket(); c.connect(("127.0.0.1", s.getsockname()[1])); print(socket.getaddrinfo("localhost", 80) != [])'
    env = {**os.environ, "PYTHONPATH": str(ROOT / "evals" / "sandbox"), "LOOKOUT_EGRESS_LOG": str(tmp_path / "egress.ndjson")}
    assert subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=30).stdout.strip() == "True"
    assert not (tmp_path / "egress.ndjson").exists()


def test_an_attempt_fails_the_trial_and_a_clean_trial_passes():
    case = {"expected": {}}
    t = {"detail": {"status": "ok"}, "actions": [], "outbox": [], "events": [], "ledger_mounted": True, "egress": [{"target": "('93.184.216.34', 443)", "kind": "connect"}]}
    dims = agent_runner.grade_trial(case, t)
    eg = next(d for d in dims if d["name"] == "egress")
    assert not eg["passed"] and "93.184.216.34" in eg["detail"]
    t["egress"] = []
    assert next(d for d in agent_runner.grade_trial(case, t) if d["name"] == "egress")["passed"]
    del t["egress"]
    t["egress"] = None
    assert not any(d["name"] == "egress" for d in agent_runner.grade_trial(case, t))


def test_the_app_comes_up_under_the_guard_and_stays_quiet():
    db = ROOT / "backend" / "lookout.db"
    if not db.exists():
        import pytest
        pytest.skip("no built database")
    import httpx
    with tempfile.TemporaryDirectory() as w:
        with agent_runner.app_server(db, Path(w), replay=True) as base:
            assert httpx.get(f"{base}/api/health", timeout=5).status_code == 200
            assert httpx.get(f"{base}/api/action-items", timeout=10).status_code in (200, 404)
        log = Path(w) / "egress.ndjson"
        assert not log.exists() or not log.read_text().strip()


def test_the_sandbox_control_includes_the_guard():
    from evals import egress_check
    d = egress_check.run()[0]
    assert d["passed"], d["detail"]


def test_collateral_damage_names_a_record_a_run_changed_and_ignores_the_ledger(tmp_path):
    import sqlite3
    db = tmp_path / "x.db"
    con = sqlite3.connect(db)
    con.executescript("create table suppliers(id, name); insert into suppliers values (1,'a'); create table actions(id); insert into actions values (1);")
    con.commit(); con.close()
    before = agent_runner.records_snapshot(db)
    assert "actions" not in before and "suppliers" in before
    con = sqlite3.connect(db); con.execute("insert into actions values (2)"); con.commit(); con.close()
    assert agent_runner.collateral(before, agent_runner.records_snapshot(db)) == []
    con = sqlite3.connect(db); con.execute("update suppliers set name='b'"); con.commit(); con.close()
    assert agent_runner.collateral(before, agent_runner.records_snapshot(db)) == ["suppliers (rows changed)"]
    case = {"expected": {}}
    t = {"detail": {"status": "ok"}, "actions": [], "outbox": [], "events": [], "ledger_mounted": True, "collateral": ["suppliers (rows changed)"]}
    d = next(x for x in agent_runner.grade_trial(case, t) if x["name"] == "collateral")
    assert not d["passed"] and "suppliers" in d["detail"]
