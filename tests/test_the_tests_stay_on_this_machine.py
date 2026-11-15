"""The tests must never reach a paid API, even when the code they test is broken on purpose."""

import json
import socket

import pytest

from kettle.attacktest import __main__ as cli


@pytest.mark.parametrize("host", ["api.anthropic.com", "api.openai.com", "93.184.216.34"])
def test_a_test_cannot_reach_another_machine(host):
    with pytest.raises(AssertionError, match="the tests stay on this machine"):
        socket.create_connection((host, 443), timeout=1)
    with socket.socket() as plain, pytest.raises(AssertionError, match="the tests stay on this machine"):
        plain.connect((host, 443))


def test_a_test_can_still_reach_a_stand_in_server_on_this_machine():
    with socket.create_server(("127.0.0.1", 0)) as server:
        with socket.create_connection(("127.0.0.1", server.getsockname()[1]), timeout=5):
            pass


def test_a_real_claude_agent_made_by_the_command_cannot_call_out(monkeypatch, capsys, tmp_path):
    """What went wrong once: a break took out the --yes check, and a test then ran the real agent with a real key."""
    anthropic = pytest.importorskip("anthropic")
    real = anthropic.Anthropic.__init__
    monkeypatch.setattr(anthropic.Anthropic, "__init__", lambda self, *args, **kwargs: real(self, *args, **{**kwargs, "max_retries": 0}))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=not-a-real-key\n", encoding="utf-8")
    assert cli.main(["--claude", "--yes", "--repeats", "1", "--only", "job-meeting-time", "--setups", "none"]) == 0
    (saved,) = (tmp_path / "runs").glob("*/results.json")
    result = json.loads(saved.read_text(encoding="utf-8"))
    assert [bool(run["error"]) for run in result["runs"]] == [True]
    assert result["meta"]["usage"]["input_tokens"] == 0 and result["meta"]["usage"]["output_tokens"] == 0
