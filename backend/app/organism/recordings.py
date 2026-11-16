"""Whether a model is connected. On this machine none is: runs are drafted by code or replayed from the recordings in `recordings/hg/` (mocked)."""

from __future__ import annotations


def live_available() -> bool:
    return False
