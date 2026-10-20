"""Is the model reachable? The precondition for agent cases.

Two ways, and only these: an ANTHROPIC_API_KEY in the environment (a reviewer's case), or the Agent SDK
authenticating through the machine's logged-in Claude CLI (ours). The second is proven by one tiny query.
Nothing here sets, reads out or stores a credential.
"""
from __future__ import annotations

import asyncio
import os

_cache: dict[str, tuple[bool, str]] = {}


async def _probe() -> tuple[bool, str]:
    import claude_agent_sdk as sdk
    opts = sdk.ClaudeAgentOptions(max_turns=1, allowed_tools=[], system_prompt="Answer with the single word: ok")
    out = (False, "the SDK returned no result")
    async for msg in sdk.query(prompt="ok?", options=opts):  # drained to the end, so the stream closes cleanly
        if isinstance(msg, sdk.ResultMessage):
            out = (not msg.is_error, "reachable through the Claude CLI login" if not msg.is_error else f"the SDK returned an error: {msg.result}")
    return out


def reachable(timeout_s: float = 60) -> tuple[bool, str]:
    """(ok, how-or-why-not). Cached for the process: the probe costs a query."""
    if "r" in _cache:
        return _cache["r"]
    keyed = bool(os.environ.get("ANTHROPIC_API_KEY"))
    try:
        ok, why = asyncio.run(asyncio.wait_for(_probe(), timeout_s))   # one tiny query, so a wrong key is named here and not counted as the agent failing every case
        if keyed:
            _cache["r"] = (ok, "ANTHROPIC_API_KEY is set and accepted" if ok else f"ANTHROPIC_API_KEY is set but the API did not accept it ({why}). Check the key in .env; the evals are not run.")
        else:
            _cache["r"] = (ok, why)
    except Exception as e:  # noqa: BLE001  (no SDK, not logged in, offline: all mean "not reachable")
        detail = str(e).split("error result:")[-1].strip()[:140]   # "Invalid API key · Fix external API key (exit code: 1)"
        _cache["r"] = (False, f"ANTHROPIC_API_KEY was refused: {detail}. Check the key in .env." if keyed else f"no ANTHROPIC_API_KEY and no Claude CLI login ({detail})")
    return _cache["r"]
