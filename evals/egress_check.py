"""Does the sandbox's egress guard hold? A child Python started the way the eval app is started tries to leave the machine.

It must be refused twice (a connect and a name lookup), each written to the log, while a connection to this machine still works.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from . import graders

ROOT = Path(__file__).resolve().parents[1]
ATTEMPT = """
import socket
srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
socket.socket().connect(("127.0.0.1", srv.getsockname()[1]))
out = []
for what in ("connect", "lookup"):
    try:
        socket.socket().connect(("192.0.2.1", 80)) if what == "connect" else socket.getaddrinfo("example.com", 80)
        out.append("allowed")
    except OSError as e:
        out.append("blocked" if "egress blocked" in str(e) else "other")
print(",".join(out))
"""


def run() -> list[dict]:
    with tempfile.TemporaryDirectory() as w:
        log = Path(w) / "egress.ndjson"
        env = {**os.environ, "PYTHONPATH": str(ROOT / "evals" / "sandbox"), "LOOKOUT_EGRESS_GUARD": "1", "LOOKOUT_EGRESS_LOG": str(log)}
        try:
            r = subprocess.run([sys.executable, "-c", ATTEMPT], env=env, capture_output=True, text=True, timeout=30)
            out = r.stdout.strip()
        except subprocess.TimeoutExpired:
            out = "timeout"
        seen = {json.loads(x)["kind"] for x in log.read_text().splitlines() if x.strip()} if log.exists() else set()
    ok = out == "blocked,blocked" and seen == {"connect", "lookup"}
    return [graders._dim("egress guard", ok, "a connect and a lookup off this machine were refused and logged; this machine still works" if ok else f"the guard let something through or failed: {out!r}, logged {sorted(seen)}")]
