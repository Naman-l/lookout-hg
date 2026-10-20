"""The run's event recorder: every step becomes a RunEvent, stored, pushed to subscribers and emitted to the
Watcher. One recorder per run; child runs share the writer and carry their own run_id."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from ... import watcher
from ..purposes import why as _why
from ..schemas import EntityRef, EventType, RunEvent
from ..specialists.registry import SPECIALISTS
from . import store

# watcher.emit's own parameters: a payload key with one of these names would collide, so it is prefixed in the Watcher copy
_WATCHER_RESERVED = {"source", "kind", "summary", "severity", "run_id", "request_id", "item_id", "agent", "seq"}

LABELS = {"lookout": "Lookout", **{name: s.label for name, s in SPECIALISTS.items()}, "verifier": "Verifier", "reviewer": "Reviewer"}  # every specialist from the registry, never a raw name


class Recorder:
    def __init__(self, run_id: str, db_path, *, parent_run_id: str | None = None, t0: float | None = None):
        self.run_id = run_id
        self.parent_run_id = parent_run_id
        self.db_path = db_path
        self.t0 = t0 if t0 is not None else time.perf_counter()
        self.seq = 0
        self.first_step_ms: int | None = None  # first thing the buyer sees happen (the system reading the item counts)
        self.first_token_ms: int | None = None  # first model output, reported separately
        self.tool_calls = 0
        self.denied_calls = 0
        self.subscribers: list[asyncio.Queue] = []
        self.events: list[RunEvent] = []

    def child(self, run_id: str) -> "Recorder":
        """A recorder for a child run: own run_id and seq, shared clock, store and subscribers."""
        c = Recorder(run_id, self.db_path, parent_run_id=self.run_id, t0=self.t0)
        c.subscribers = self.subscribers
        return c

    def t_ms(self) -> int:
        return round((time.perf_counter() - self.t0) * 1000)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self.subscribers.append(q)
        return q

    def _push(self, item: tuple[int | None, RunEvent]) -> None:
        for q in self.subscribers:
            q.put_nowait(item)

    def emit(
        self,
        type: EventType,
        summary: str,
        *,
        agent: str = "lookout",
        tool_use_id: str | None = None,
        refs: list[EntityRef] | None = None,
        run_id: str | None = None,
        parent_run_id: str | None = None,
        _t_ms: int | None = None,  # a replay keeps the original run's clock
        **payload,
    ) -> RunEvent:
        if type in ("step.text", "step.delta", "child.started", "tool.called") and self.first_step_ms is None:
            self.first_step_ms = self.t_ms()
        if type in ("step.text", "step.delta") and self.first_token_ms is None:
            self.first_token_ms = self.t_ms()
        if type == "tool.called":
            if "why" not in payload and payload.get("gate") in ("allowed", "staged"):  # the reason a buyer reads beside the step, written by code
                payload["why"] = _why(payload.get("tool") or payload.get("name") or "", payload.get("args"), self.db_path)
            self.tool_calls += 1
            self.denied_calls += payload.get("gate") == "denied"
        if type != "step.delta":
            self.seq += 1
        event = RunEvent(
            run_id=run_id or self.run_id,
            parent_run_id=parent_run_id if parent_run_id is not None else self.parent_run_id,
            seq=self.seq,
            ts=datetime.now(timezone.utc).isoformat(),
            t_ms=self.t_ms() if _t_ms is None else _t_ms,
            type=type,
            agent=agent,
            agent_label=LABELS.get(agent, agent),
            tool_use_id=tool_use_id,
            summary=summary,
            refs=refs or [],
            payload=payload,
        )
        row_id = None
        if type != "step.delta":  # deltas are SSE-only: no id, never stored
            row_id = store.append_event(self.db_path, event)
            self.events.append(event)
            safe = {(f"payload_{k}" if k in _WATCHER_RESERVED else k): v for k, v in payload.items()}
            # parent_run_id is what ties a specialist's own steps to the run that asked it; t_ms is the run's own clock (a replay's wall time is not)
            watcher.emit("agent", type, summary, run_id=event.run_id, agent=agent, seq=event.seq, parent_run_id=event.parent_run_id, t_ms=event.t_ms, **safe)
        self._push((row_id, event))
        return event


def mark_superseded(events: list[RunEvent]) -> list[RunEvent]:
    """Tag, for display, the remarks Lookout made after it was nudged that the final answer replaces.

    The runner nudges Lookout when its turn ends before every teammate has handed off. What Lookout says after that, once it has asked
    the teammate again and before its last read of the handoffs, is a first attempt at the answer or a status that is already out of
    date. It stays in the log, tagged `payload.superseded`, for the page to fold; nothing is removed and no model input changes."""
    marker = next((i for i, e in enumerate(events) if e.type == "step.text" and e.payload.get("system") and e.summary.startswith("Still waiting for")), None)
    if marker is None:
        return events
    last_read = max((i for i, e in enumerate(events) if e.type == "tool.called" and e.agent == "lookout" and e.payload.get("tool") == "get_handoffs"), default=-1)
    asked_again = next((i for i, e in enumerate(events) if i > marker and e.type == "child.started"), None)
    if asked_again is None:
        return events
    return [e.model_copy(update={"payload": {**e.payload, "superseded": True}}) if (asked_again < i < last_read and e.type == "step.text" and e.agent == "lookout" and not e.payload.get("system")) else e
            for i, e in enumerate(events)]
