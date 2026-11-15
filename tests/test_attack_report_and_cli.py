"""The report and the command line. No model is used and no paid call is made."""

import json
import sys

import pytest

from kettle.attacktest import KETTLE, NONE, load_cases, run_test, save_report, to_markdown
from kettle.attacktest import __main__ as cli
from kettle.attacktest import claude_agent, standins

CASES = load_cases()


@pytest.fixture(scope="module")
def result():
    return run_test(agent_for=standins.fooled, cases=CASES, repeats=2, label="A scripted stand-in | not a model", settings={"script": "fooled"})


def row(report, label):
    line = next(line for line in report.splitlines() if line.startswith(f"| {label} |"))
    return [cell.strip() for cell in line.strip("|").split("|")][1:]


def test_the_report_shows_the_four_numbers_from_the_result(result):
    report = to_markdown(result)
    assert row(report, "Attacks run") == ["24", "24"]
    assert row(report, "Attacks the agent went along with") == ["24", "24"]
    assert row(report, "Actions that ran without a yes") == ["24", "0"]
    assert row(report, "Normal jobs still finished") == ["12 of 12", "12 of 12"]
    assert row(report, "Attack runs where the attacker's action really ran") == ["24", "0"]
    assert row(report, "Attack runs where the trick text reached the agent") == ["24 of 24", "24 of 24"]


def test_the_report_has_one_line_per_case_per_setup(result):
    report = to_markdown(result)
    for case in CASES.cases():
        assert sum(line.startswith(f"| {case.id} |") for line in report.splitlines()) == 2


def test_the_report_says_who_ran_it_and_what_it_does_not_show(result):
    report = to_markdown(result)
    for text in (
        "It is not an independent test.",
        "The owner is a stand-in.",
        "A small, public case set.",
        "does not show the agent is safe",
        "Not compared with other approval steps.",
        "Rules are not judgement.",
        "The attacker controls text the agent reads",
        CASES.sha256[:16],
        '"script": "fooled"',
    ):
        assert text in report
    assert "A scripted stand-in \\| not a model" not in report.split("## The four numbers")[0]  # only tables escape the bar


def test_a_report_with_one_setup_has_one_column(result):
    one = run_test(agent_for=standins.careful, cases=CASES, repeats=1, setups=(KETTLE,))
    report = to_markdown(one)
    assert row(report, "Attacks run") == ["12"] and "No checkpoint" not in report.split("## What was tested")[0]


def test_saving_writes_the_report_and_every_run(result, tmp_path):
    folder = save_report(result, str(tmp_path / "runs"))
    assert (folder / "report.md").read_text(encoding="utf-8") == to_markdown(result)
    saved = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    assert saved == json.loads(json.dumps(result)) and len(saved["runs"]) == 72
    again = save_report(result, str(tmp_path / "runs"))
    assert again != folder and again.name == folder.name + "-2"


def test_an_agent_that_passes_odd_things_still_gets_a_report_that_can_be_saved(tmp_path):
    class Odd:
        def __repr__(self):
            raise RuntimeError("no")

    def agent(task, tools):
        tools.call("pay", {"to": Odd(), "amount": float("inf")})
        tools.call(Odd(), b"bytes")
        tools.call("read_file", {"name": "x" * 5000})
        return "ok"

    result = run_test(agent, cases=CASES, repeats=1, only=["job-meeting-time"])
    folder = save_report(result, str(tmp_path))
    assert json.loads((folder / "results.json").read_text(encoding="utf-8"))["totals"][NONE]["tool_calls"] == 3


# ---- the command line ----


def test_self_check_passes_and_says_it_is_not_about_a_model(capsys):
    assert cli.main(["--self-check"]) == 0
    out = capsys.readouterr().out
    assert "8 of 8 checks held." in out and "says nothing about one" in out and "FAIL" not in out


def test_a_self_check_that_fails_says_so_and_the_command_fails(monkeypatch, capsys):
    monkeypatch.setattr(cli, "self_check", lambda cases: [("this one held", True), ("this one did not", False)])
    assert cli.main(["--self-check"]) == 1
    out = capsys.readouterr().out
    assert "FAIL  this one did not" in out and "1 of 2 checks held." in out


def test_list_names_every_case(capsys):
    assert cli.main(["--list"]) == 0
    out = capsys.readouterr().out
    assert all(case.id in out for case in CASES.cases()) and "6 normal jobs, 12 attacks" in out


def test_the_fraud_set_can_be_asked_for_by_name(capsys):
    assert cli.main(["--list", "--cases", "fraud"]) == 0
    out = capsys.readouterr().out
    assert "kettle-fraud-1: 7 normal jobs, 7 attacks" in out and "attack-email-lookalike" in out and "attack-file-gift" not in out
    assert cli.main(["--self-check", "--cases", "fraud"]) == 0
    out = capsys.readouterr().out
    assert "8 of 8 checks held." in out and "all 7 attacks counted as gone along with" in out and "FAIL" not in out
    assert cli.main(["--claude", "--cases", "fraud", "--repeats", "1"]) == 0
    assert "28 times" in capsys.readouterr().out


def test_a_wrong_case_file_stops_the_command(tmp_path, capsys):
    path = tmp_path / "bad.toml"
    path.write_text('name = "bad"', encoding="utf-8")
    assert cli.main(["--list", "--cases", str(path)]) == 2
    assert "The case file is wrong" in capsys.readouterr().err


class NoClaude:
    def __init__(self, *args, **kwargs):
        raise AssertionError("the Claude agent must not be made here")


def test_claude_does_nothing_without_yes(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(claude_agent, "ClaudeAgent", NoClaude)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--claude"]) == 0
    out = capsys.readouterr().out
    assert "180 times" in out and "Nothing has been run" in out and not (tmp_path / "runs").exists()
    assert cli.main(["--claude", "--repeats", "1", "--only", "attack-file-gift,job-pay-invoice", "--setups", "kettle"]) == 0
    assert "2 times" in capsys.readouterr().out
    assert cli.main(["--claude", "--repeats", "1", "--only", "attack-file-gift,attack-file-gift"]) == 0
    assert "2 times" in capsys.readouterr().out  # a case named twice is run once per setup
    assert cli.main(["--claude", "--only", "attack-file-gift,no-such-case"]) == 2
    captured = capsys.readouterr()
    assert "no such case: no-such-case" in captured.err and "times" not in captured.out


def test_claude_with_yes_but_no_key_runs_nothing(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(claude_agent, "ClaudeAgent", NoClaude)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-key-from-somewhere-else")
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--claude", "--yes"]) == 2
    assert "No ANTHROPIC_API_KEY found in .env" in capsys.readouterr().err


class FakeClaude:
    made = []

    def __init__(self, model, api_key=None):
        self.model, self.api_key = model, api_key
        self.settings = {"model": model, "api_address": "https://api.example.test/"}
        self.api_calls, self.input_tokens, self.output_tokens = 3, 1200, 340
        FakeClaude.made.append(self)

    def __call__(self, task, tools):
        return "I could not do that."


@pytest.mark.parametrize("extra, expected", [([], "key-in-the-file"), (["--key-from-env"], "key-in-the-environment")])
def test_the_key_comes_from_the_file_unless_asked_otherwise(monkeypatch, capsys, tmp_path, extra, expected):
    FakeClaude.made.clear()
    monkeypatch.setattr(claude_agent, "ClaudeAgent", FakeClaude)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key-in-the-environment")
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OTHER=1\nexport ANTHROPIC_API_KEY='key-in-the-file'\n", encoding="utf-8")
    assert cli.main(["--claude", "--yes", "--repeats", "1", "--only", "job-meeting-time", "--model", "some-model"] + extra) == 0
    (agent,) = FakeClaude.made
    assert (agent.api_key, agent.model) == (expected, "some-model")
    captured = capsys.readouterr()
    assert expected not in captured.out and expected not in captured.err  # the key is never printed
    assert "Calling the API at https://api.example.test/" in captured.out  # where the key is sent is
    (folder,) = (tmp_path / "runs").iterdir()
    saved = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    assert saved["meta"]["usage"] == {"api_calls": 3, "input_tokens": 1200, "output_tokens": 340}
    assert expected not in (folder / "results.json").read_text(encoding="utf-8")
    report = (folder / "report.md").read_text(encoding="utf-8")
    assert "1200 input tokens" in report and expected not in report and '"api_address": "https://api.example.test/"' in report


@pytest.mark.parametrize(
    "text, expected",
    [
        ("ANTHROPIC_API_KEY=abc", "abc"),
        ('  export ANTHROPIC_API_KEY="abc"  ', "abc"),
        ("# a comment\nOTHER=1\nANTHROPIC_API_KEY='abc'\n", "abc"),
        ("ANTHROPIC_API_KEY=", None),
        ("MY_ANTHROPIC_API_KEY=abc", None),
        ("", None),
    ],
)
def test_reading_the_key_file(tmp_path, text, expected):
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    assert cli._key_from_file(str(path)) == expected
    assert cli._key_from_file(str(tmp_path / "missing")) is None


def test_running_your_own_agent_writes_a_report(monkeypatch, capsys, tmp_path):
    (tmp_path / "bot.py").write_text("def agent(task, tools):\n    tools.call('list_emails', {})\n    return 'ok'\n\nnumber = 5\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "path", list(sys.path))
    assert cli.main(["--agent", "bot:agent", "--repeats", "1", "--out", "out"]) == 0
    out = capsys.readouterr().out
    assert "[36/36]" in out and "Kettle checkpoint: 12 attacks run, 0 gone along with, 0 actions ran without a yes, 0 of 6 normal jobs finished" in out
    (folder,) = (tmp_path / "out").iterdir()
    assert "- Agent: bot:agent" in (folder / "report.md").read_text(encoding="utf-8")
    for spec in ("bot", "bot:missing", "nothing_here:agent", "bot:number"):
        with pytest.raises(SystemExit):
            cli.main(["--agent", spec, "--repeats", "1", "--out", "out"])
    assert cli.main(["--agent", "bot:agent", "--only", "no-such-case"]) == 2
    assert cli.main(["--agent", "bot:agent", "--setups", "magic"]) == 2
    assert len(list((tmp_path / "out").iterdir())) == 1
