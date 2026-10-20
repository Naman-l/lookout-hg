import asyncio

from evals import model


def _reset(monkeypatch, key, probe):
    import os
    for name in [n for n in os.environ if n.startswith(("ANTHROPIC_", "CLAUDE_CODE_", "CLAUDE_AGENT_"))]:
        monkeypatch.delenv(name)
    model._cache.clear()
    monkeypatch.setattr(model, "_probe", probe)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    if key:
        monkeypatch.setenv("ANTHROPIC_API_KEY", key)


def test_a_key_the_api_refuses_is_named_and_not_counted_as_the_agent_failing(monkeypatch):
    async def refused():
        return False, "the SDK returned an error: Invalid API key"
    _reset(monkeypatch, "sk-ant-wrong", refused)
    ok, why = model.reachable()
    assert not ok and "did not accept it" in why and "Invalid API key" in why and ".env" in why


def test_a_good_key_and_no_key_at_all_are_told_apart(monkeypatch):
    async def fine():
        return True, "reachable through the Claude CLI login"
    _reset(monkeypatch, "sk-ant-good", fine)
    assert model.reachable() == (True, "ANTHROPIC_API_KEY is set and accepted")

    async def down():
        raise OSError("offline")
    _reset(monkeypatch, None, down)
    ok, why = model.reachable()
    assert not ok and "no ANTHROPIC_API_KEY" in why


def test_the_sdk_error_for_a_bad_key_is_shortened_to_what_the_reader_needs(monkeypatch):
    async def boom():
        raise RuntimeError("Claude Code returned an error result: Invalid API key · Fix external API key (exit code: 1)")
    _reset(monkeypatch, "sk-ant-wrong", boom)
    ok, why = model.reachable()
    assert not ok and why.startswith("ANTHROPIC_API_KEY was refused: Invalid API key") and "ResultError" not in why
