import json
import subprocess

from watcher import correlate


def _write(tmp_path, events):
    (tmp_path / "2026-10-12.ndjson").write_text("\n".join(json.dumps(e) for e in events) + "\n")


def _ev(kind, run, seq, **body):
    parent = body.pop("parent_run_id", None)
    return {"ts": f"2026-10-12T10:00:{seq:02d}+00:00", "source": "agent", "kind": kind, "severity": "info",
            "summary": body.pop("summary", kind), "run_id": run, "request_id": body.pop("request_id", "req-1"),
            "body": {"seq": seq, "parent_run_id": parent, **body}}


def test_story_spans_request_run_child_gate_and_finish(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOOKOUT_EVENTS_DIR", str(tmp_path))
    _write(tmp_path, [
        _ev("run.started", "run-1", 1, agent_label="Lookout", t_ms=0),
        _ev("child.started", "run-2", 2, parent_run_id="run-1", agent_label="Supply planner", t_ms=900),
        _ev("tool.called", "run-2", 3, parent_run_id="run-1", agent_label="Supply planner", gate="allowed",
            summary="open_supply HR-40110", t_ms=1200),
        _ev("tool.called", "run-2", 4, parent_run_id="run-1", agent_label="Supply planner", gate="denied",
            summary="Bash", t_ms=1500),
        _ev("run.finished", "run-1", 5, status="ok", tool_calls=2, first_step_ms=1350, wall_ms=16800, cost_usd=0.045),
    ])
    assert correlate.main(["req-1"]) == 0
    out = capsys.readouterr().out
    assert "[DENIED]" in out and "Supply planner" in out and "finished ok" in out and "first step 1350 ms" in out


def test_unknown_id_exits_nonzero(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOOKOUT_EVENTS_DIR", str(tmp_path))
    assert correlate.main(["nope"]) == 1


def test_run_without_finish_is_called_out(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOOKOUT_EVENTS_DIR", str(tmp_path))
    _write(tmp_path, [_ev("run.started", "run-1", 1, t_ms=0)])
    correlate.main(["run-1"])
    assert "did not end cleanly" in capsys.readouterr().out


def test_correlator_reads_what_the_apps_emit_writes(tmp_path, monkeypatch, capsys):
    import importlib.util
    monkeypatch.setenv("LOOKOUT_EVENTS_DIR", str(tmp_path))
    spec = importlib.util.spec_from_file_location("app_watcher", "backend/app/watcher.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.emit("agent", "run.started", "Lookout began work on the Yunzhan item", run_id="run-9", request_id="req-9", t_ms=0, agent_label="Lookout")
    mod.emit("agent", "tool.called", "open_supply HR-40110", run_id="run-9", request_id="req-9", t_ms=800, gate="staged", agent_label="Buyer's clerk")
    mod.emit("agent", "run.finished", "done", run_id="run-9", request_id="req-9", status="ok", tool_calls=1, first_step_ms=900, wall_ms=5000, cost_usd=0.02)
    assert correlate.main(["run-9"]) == 0
    out = capsys.readouterr().out
    assert "[STAGED]" in out and "Buyer's clerk" in out and "finished ok" in out
