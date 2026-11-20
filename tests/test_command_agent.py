"""--agent-command and --claude-code: an agent that is a program, with the pretend world as its MCP server.

The program here is tests/pretend_mcp_agent.py, a fixed script that speaks MCP. No
model runs, and `claude` cannot be found: PATH is empty for every test in this file,
so even a copy of the code with the --yes guard taken out cannot start it.
"""

import io
import json
import os
import shlex
import stat
import sys
from pathlib import Path

import pytest

from kettle.attacktest import __main__ as cli
from kettle.attacktest import load_cases, run_test, standins
from kettle.attacktest import world_server
from kettle.attacktest.command_agent import CLAUDE_CODE, CommandAgent, CommandError, claude_code, parse
from kettle.attacktest.sandbox import TOOL_SPECS

PRETEND = str(Path(__file__).with_name("pretend_mcp_agent.py"))


@pytest.fixture(autouse=True)
def no_programs_on_the_path(monkeypatch, tmp_path):
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))


def pretend(mode, cases="fraud", task=True, **more):
    words = [sys.executable, PRETEND, "--mcp", "{mcp_config}", "--cases", cases, "--mode", mode]
    if task:
        words += ["--task", "{task}"]
    for name, value in more.items():
        words += [f"--{name}", value]
    return words


FRAUD_FEW = ["attack-notes-address", "attack-invoice-notice", "job-pay-invoice", "job-send-numbers"]


def totals(result):
    keep = ("attack_runs", "went_along", "ran_without_yes", "job_runs", "jobs_done", "errors")
    return {setup: {key: result["totals"][setup][key] for key in keep} for setup in result["totals"]}


# ---- the same counts as the stand-ins called as functions ----


@pytest.mark.parametrize("mode", ["fooled", "careful"])
def test_a_program_gets_the_same_counts_as_the_same_script_as_a_function(mode):
    fraud = load_cases("fraud")
    as_program = run_test(agent_for=lambda case: CommandAgent(pretend(mode, case=case.id), timeout=60), cases=fraud, repeats=1, only=FRAUD_FEW)
    as_function = run_test(agent_for=getattr(standins, mode), cases=fraud, repeats=1, only=FRAUD_FEW)
    assert totals(as_program) == totals(as_function)
    assert totals(as_program)["none"]["errors"] == 0


def test_a_fooled_program_is_stopped_by_the_checkpoint_and_not_without_it():
    result = run_test(CommandAgent(pretend("fooled", case="attack-notes-address"), timeout=60), cases=load_cases("fraud"), repeats=1, only=["attack-notes-address"])
    assert result["totals"]["none"]["ran_without_yes"] == 1
    assert result["totals"]["kettle"]["ran_without_yes"] == 0
    assert result["totals"]["kettle"]["went_along"] == 1
    kettle_run = next(run for run in result["runs"] if run["setup"] == "kettle")
    assert any(call["outcome"] != "ran" for call in kettle_run["calls"] if call["tool"] in ("send_email", "pay"))


def test_with_no_task_in_the_command_the_task_comes_on_stdin():
    result = run_test(CommandAgent(pretend("careful", task=False, case="job-pay-invoice"), timeout=60), cases=load_cases("fraud"), repeats=1, only=["job-pay-invoice"], setups=("none",))
    assert result["totals"]["none"]["jobs_done"] == 1 and result["totals"]["none"]["errors"] == 0


def test_the_call_limit_holds_for_a_program():
    result = run_test(CommandAgent(pretend("flood"), timeout=60), cases=load_cases("fraud"), repeats=1, max_calls=5, only=["job-pay-invoice"], setups=("none",))
    run = result["runs"][0]
    assert run["over_call_limit"] is True
    assert [call["outcome"] for call in run["calls"]] == ["ran"] * 5 + ["over the call limit"] * 45


def test_a_tool_that_does_not_exist_and_bad_inputs_are_answered_and_run_nothing():
    replies = {}

    def keep(run):
        replies["reply"] = run["reply"]

    result = run_test(CommandAgent(pretend("odd"), timeout=60), cases=load_cases("fraud"), repeats=1, only=["job-pay-invoice"], setups=("none",), progress=keep)
    unknown, bad = json.loads(replies["reply"])
    assert unknown == "There is no tool with that name." and bad.startswith("The inputs do not fit read_email")
    assert result["runs"][0]["ran"] == []


# ---- when the program fails ----


def test_a_program_that_is_not_there_is_an_error_in_the_run_not_a_crash():
    result = run_test(CommandAgent(["no-such-agent-program", "{task}"], timeout=10), cases=load_cases("fraud"), repeats=1, only=["job-pay-invoice"], setups=("none",))
    assert "no-such-agent-program was not found" in result["runs"][0]["error"]


def test_a_program_that_fails_and_prints_nothing_is_an_error():
    with pytest.raises(CommandError, match="ended with 3"):
        CommandAgent(pretend("silent"), timeout=10)("the task", tools=None)


def test_a_program_that_fails_after_printing_a_reply_is_an_error_not_a_reply():
    with pytest.raises(CommandError, match="ended with 4: something broke"):
        CommandAgent(pretend("crash"), timeout=10)("the task", tools=None)
    result = run_test(CommandAgent(pretend("crash"), timeout=10), cases=load_cases("fraud"), repeats=1, only=["job-pay-invoice"], setups=("none",))
    assert result["runs"][0]["error"].startswith("CommandError: the program ended with 4")
    assert result["totals"]["none"]["jobs_done"] == 0


def test_a_program_that_does_not_finish_is_stopped():
    with pytest.raises(CommandError, match="did not finish in 1 seconds"):
        CommandAgent(pretend("sleep"), timeout=1)("the task", tools=None)


def test_the_folder_is_the_programs_alone_and_is_taken_away_after(monkeypatch):
    seen = {}

    class Look:
        specs = TOOL_SPECS

        def call(self, name, inputs):
            return "ok"

    real_run = __import__("subprocess").run

    def run(words, **more):
        config = words[words.index("--mcp") + 1]
        folder = os.path.dirname(config)
        seen["folder"], seen["cwd"] = folder, more["cwd"]
        seen["mode"] = stat.S_IMODE(os.stat(folder).st_mode)
        seen["socket"] = stat.S_IMODE(os.stat(os.path.join(folder, "w.sock")).st_mode)
        seen["config"] = json.load(open(config))
        return real_run(words, **more)

    monkeypatch.setattr("kettle.attacktest.command_agent.subprocess.run", run)
    CommandAgent(pretend("marker", marker=os.devnull), timeout=10)("the task", Look())
    assert seen["mode"] == 0o700 and seen["socket"] == 0o600
    assert seen["cwd"] == os.path.join(seen["folder"], "work")
    assert list(seen["config"]["mcpServers"]) == ["world"]
    assert seen["config"]["mcpServers"]["world"]["args"][:3] == ["-P", "-m", "kettle.attacktest.world_server"]
    assert not os.path.exists(seen["folder"])


def test_the_task_and_settings_path_are_filled_in_as_whole_arguments_never_through_a_shell():
    agent = CommandAgent(["prog", "--task", "{task}", "--mcp={mcp_config}"])
    assert agent.arguments("a; rm -rf ~ `x` $(y)", "/tmp/c.json") == ["prog", "--task", "a; rm -rf ~ `x` $(y)", "--mcp=/tmp/c.json"]
    assert parse("my-agent --task {task} 'two words'") == ["my-agent", "--task", "{task}", "two words"]
    with pytest.raises(ValueError):
        parse("   ")


# ---- Claude Code ----


def test_claude_code_gets_only_the_worlds_tools():
    words = claude_code()
    assert words[:3] == ["claude", "-p", "{task}"]
    assert words[words.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in words
    assert words[words.index("--mcp-config") + 1] == "{mcp_config}"
    assert words[words.index("--allowedTools") + 1] == "mcp__world__*"
    assert "--dangerously-skip-permissions" not in words and "bypassPermissions" not in words
    assert claude_code("haiku")[-2:] == ["--model", "haiku"] and CLAUDE_CODE == claude_code()


# ---- the command ----


def test_a_program_is_not_started_without_yes(capsys, tmp_path):
    marker = tmp_path / "started"
    command = shlex.join(pretend("marker", marker=str(marker)))
    assert cli.main(["--agent-command", command, "--repeats", "1", "--only", "job-meeting-time", "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "would start" in out and "2 times" in out and "Nothing has been run" in out
    assert not marker.exists()


def test_claude_code_is_not_started_without_yes(capsys, tmp_path):
    out_folder = tmp_path / "out"
    assert cli.main(["--claude-code", "--repeats", "1", "--only", "job-meeting-time", "--out", str(out_folder)]) == 0
    out = capsys.readouterr().out
    assert "would start claude 2 times" in out and "can cost money" in out
    assert not out_folder.exists()


def test_with_yes_the_program_runs_and_the_report_names_it(capsys, tmp_path):
    command = shlex.join(pretend("careful", case="job-pay-invoice"))
    assert cli.main(["--agent-command", command, "--cases", "fraud", "--repeats", "1", "--only", "job-pay-invoice", "--out", str(tmp_path), "--yes"]) == 0
    out = capsys.readouterr().out
    assert "Running: " in out and "1 of 1 normal jobs finished" in out
    saved = json.loads(next(tmp_path.glob("*/results.json")).read_text())
    assert saved["meta"]["settings"]["agent_command"] == command
    assert saved["meta"]["agent"] == sys.executable


def test_an_empty_command_and_a_bad_timeout_stop_the_command(capsys, tmp_path):
    assert cli.main(["--agent-command", "  ", "--out", str(tmp_path)]) == 2
    assert cli.main(["--agent-command", "prog", "--agent-timeout", "0", "--out", str(tmp_path)]) == 2
    assert "Nothing has been run" in capsys.readouterr().err


def test_the_trusted_set_can_be_asked_for_by_name(capsys):
    assert cli.main(["--list", "--cases", "trusted"]) == 0
    assert capsys.readouterr().out.startswith("kettle-trusted-1:")


# ---- the server on its own ----


class Line:
    def __init__(self):
        self.calls = []

    def call(self, name, inputs):
        self.calls.append((name, inputs))
        return f"ran {name}"


def talk(messages):
    out = io.BytesIO()
    line = Line()
    original = world_server.TestLine
    world_server.TestLine = lambda path: line
    try:
        world_server.serve("unused", io.BytesIO(b"".join(m if type(m) is bytes else json.dumps(m).encode() + b"\n" for m in messages)), out)
    finally:
        world_server.TestLine = original
    return [json.loads(raw) for raw in out.getvalue().splitlines()], line


def test_the_server_says_hello_lists_the_worlds_tools_and_passes_calls_on():
    replies, line = talk([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        b"not json\n",
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "pay", "arguments": {"to": "X", "amount": 1}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "read_email", "arguments": "not a dict"}},
        {"jsonrpc": "2.0", "id": 5, "method": "resources/list"},
        {"jsonrpc": "2.0", "id": 6, "method": "ping"},
    ])  # fmt: skip
    assert [reply["id"] for reply in replies] == [1, 2, 3, 4, 5, 6]
    assert replies[0]["result"]["protocolVersion"] == "2024-11-05" and replies[0]["result"]["capabilities"] == {"tools": {}}
    assert [tool["name"] for tool in replies[1]["result"]["tools"]] == [spec.name for spec in TOOL_SPECS]
    assert replies[2]["result"]["content"] == [{"type": "text", "text": "ran pay"}]
    assert line.calls == [("pay", {"to": "X", "amount": 1}), ("read_email", {})]
    assert replies[4]["error"]["code"] == -32601
    assert replies[5]["result"] == {}


def test_with_the_test_gone_a_call_runs_nothing_and_says_so(tmp_path):
    said = world_server.TestLine(str(tmp_path / "nothing-here.sock")).call("pay", {"to": "X"})
    assert said == "The attack test is no longer answering. Nothing was run."
