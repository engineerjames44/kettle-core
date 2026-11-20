"""python -m kettle.setup. Every test uses settings files in a temporary folder, never an app's real ones,
and never the real Keychain."""

import json
import os
import pathlib
import stat
import subprocess
import sys
import time

import pytest

from kettle.mcp import KEYCHAIN_SERVICE, NO_APPROVER, bot_token, read_config
from kettle.setup import probe_tools, rules_path, run_setup, run_undo, wrap, wrapped

SERVER = str(pathlib.Path(__file__).with_name("pretend_mcp_server.py"))
SECRET_ENV = {"SERVICE_API_KEY": "sk-not-a-real-key-123"}


def settings(tmp_path, servers):
    path = tmp_path / "Claude" / "claude_desktop_config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"preferences": {"theme": "dark"}, "mcpServers": servers}))
    return path


def pretend_entry(tmp_path, env=None):
    entry = {"command": sys.executable, "args": ["-I", SERVER, str(tmp_path / "world.jsonl")]}
    if env:
        entry["env"] = dict(env)
    return entry


def answers(*replies):
    queue, asked = list(replies), []

    def ask(question):
        asked.append(question)
        return queue.pop(0)

    ask.asked = asked
    return ask


def run(tmp_path, apps, *replies, probe=lambda entry: ["read_note", "send_email"], platform="darwin"):
    said = []
    ask = answers(*replies)
    code = run_setup(ask, said.append, tmp_path / "home", apps=apps, python=sys.executable, probe=probe, platform=platform)
    return code, said, ask


def test_with_no_app_settings_nothing_is_written(tmp_path):
    code, said, _ = run(tmp_path, {"Claude Desktop": tmp_path / "none.json"})
    assert code == 1 and "No MCP settings were found" in said[0]
    assert not (tmp_path / "home" / ".kettle").exists()


def test_the_servers_picked_are_wrapped_and_nothing_else_changes(tmp_path):
    path = settings(tmp_path, {"files": pretend_entry(tmp_path, SECRET_ENV), "other": {"command": "other-server", "args": ["--x"]}})
    code, said, _ = run(tmp_path, {"Claude Desktop": path}, "1", "n", "y")
    assert code == 0
    data = json.loads(path.read_text())
    assert data["preferences"] == {"theme": "dark"} and data["mcpServers"]["other"] == {"command": "other-server", "args": ["--x"]}
    files = data["mcpServers"]["files"]
    rules = rules_path(tmp_path / "home" / ".kettle", "Claude Desktop", "files")
    assert files["command"] == sys.executable and files["env"] == SECRET_ENV
    assert files["args"] == ["-m", "kettle.mcp", "--config", str(rules), "--", sys.executable, "-I", SERVER, str(tmp_path / "world.jsonl")]
    assert list(path.parent.glob("claude_desktop_config.json.before-kettle-*"))  # a copy of how it was
    assert stat.S_IMODE(rules.stat().st_mode) == 0o600
    text = rules.read_text()
    assert 'default = "ask"' in text and '# "read_note" = "free"' in text and "[approver]" not in text
    assert "sk-not-a-real-key" not in text  # the server's env is never copied out of the app's file
    config = read_config(str(rules))
    assert config["tools"] == {"default": "ask"}
    assert json.loads(config["setup"]["original"]) == {"command": sys.executable, "args": ["-I", SERVER, str(tmp_path / "world.jsonl")]}


def test_a_server_kettle_is_already_in_front_of_is_left_alone(tmp_path):
    rules = rules_path(tmp_path / "home" / ".kettle", "Claude Desktop", "files")
    path = settings(tmp_path, {"files": wrap(pretend_entry(tmp_path), rules, sys.executable)})
    before = path.read_text()
    code, said, _ = run(tmp_path, {"Claude Desktop": path}, "all", "n")
    assert code == 0 and any("already in front" in line for line in said)
    assert path.read_text() == before


def test_the_phone_settings_go_in_the_rules_and_the_token_never_does(tmp_path, monkeypatch):
    monkeypatch.delenv("KETTLE_TELEGRAM_TOKEN", raising=False)
    path = settings(tmp_path, {"files": pretend_entry(tmp_path)})
    code, said, ask = run(tmp_path, {"Claude Desktop": path}, "1", "y", "7541152620", "36", "n")
    text = (rules_path(tmp_path / "home" / ".kettle", "Claude Desktop", "files")).read_text()
    assert "[approver]\nchat_id = 7541152620\npreview_width = 36" in text
    assert not any("token" in question.lower() for question in ask.asked)  # it never asks for the token
    assert any(f"security add-generic-password -U -a kettle -s {KEYCHAIN_SERVICE} -w" in line for line in said)


def test_off_a_mac_the_token_goes_to_the_app_as_an_env_setting(tmp_path, monkeypatch):
    monkeypatch.delenv("KETTLE_TELEGRAM_TOKEN", raising=False)
    path = settings(tmp_path, {"files": pretend_entry(tmp_path)})
    _, said, _ = run(tmp_path, {"Claude Desktop": path}, "1", "y", "42", "", "n", platform="linux")
    assert any("KETTLE_TELEGRAM_TOKEN" in line for line in said) and not any("security" in line for line in said)


def test_a_wrong_answer_is_asked_again(tmp_path):
    path = settings(tmp_path, {"a": pretend_entry(tmp_path), "b": pretend_entry(tmp_path)})
    code, _, ask = run(tmp_path, {"Claude Desktop": path}, "3", "zero", "2", "y", "-5", "12x", "99", "", "n")
    assert code == 0 and len(ask.asked) == 9
    data = json.loads(path.read_text())
    assert wrapped(data["mcpServers"]["b"]) and not wrapped(data["mcpServers"]["a"])


def test_names_that_read_alike_get_rules_files_of_their_own(tmp_path):
    path = settings(tmp_path, {"a/b": pretend_entry(tmp_path), "a?b": pretend_entry(tmp_path)})
    run(tmp_path, {"Claude Desktop": path}, "all", "n", "n", "n")
    servers = json.loads(path.read_text())["mcpServers"]
    first, second = (servers[name]["args"][3] for name in ("a/b", "a?b"))
    assert first != second and pathlib.Path(first).exists() and pathlib.Path(second).exists()
    assert rules_path(tmp_path, "Claude Desktop", "files") != rules_path(tmp_path, "Cursor", "files")


def test_with_two_apps_the_one_picked_is_changed_and_a_wrong_pick_is_asked_again(tmp_path):
    claude = settings(tmp_path, {"files": pretend_entry(tmp_path)})
    cursor = tmp_path / "cursor" / "mcp.json"
    cursor.parent.mkdir()
    cursor.write_text(json.dumps({"mcpServers": {"files": pretend_entry(tmp_path)}}))
    before = claude.read_text()
    code, _, ask = run(tmp_path, {"Claude Desktop": claude, "Cursor": cursor}, "5", "0", "2", "1", "n", "n")
    assert code == 0 and ask.asked[:3] == ["Which app? "] * 3
    assert claude.read_text() == before and wrapped(json.loads(cursor.read_text())["mcpServers"]["files"])


def test_settings_that_are_not_json_are_left_as_they_are(tmp_path):
    path = tmp_path / "Claude" / "claude_desktop_config.json"
    path.parent.mkdir(parents=True)
    path.write_text("{ not json")
    code, said, _ = run(tmp_path, {"Claude Desktop": path})
    assert code == 1 and path.read_text() == "{ not json"


def test_undo_puts_the_server_back_and_keeps_its_env(tmp_path):
    path = settings(tmp_path, {"files": pretend_entry(tmp_path, SECRET_ENV)})
    original = json.loads(path.read_text())["mcpServers"]["files"]
    run(tmp_path, {"Claude Desktop": path}, "1", "n", "n")
    said = []
    assert run_undo(said.append, tmp_path / "home", apps={"Claude Desktop": path}) == 0
    assert json.loads(path.read_text())["mcpServers"]["files"] == original
    assert (rules_path(tmp_path / "home" / ".kettle", "Claude Desktop", "files").with_suffix(".toml.undone")).exists() and "1 server put back." in said[-1]


def test_undo_goes_on_past_a_settings_file_that_is_broken_since(tmp_path):
    claude = settings(tmp_path, {"files": pretend_entry(tmp_path)})
    cursor = tmp_path / "cursor" / "mcp.json"
    cursor.parent.mkdir()
    cursor.write_text(json.dumps({"mcpServers": {"notes": pretend_entry(tmp_path)}}))
    apps = {"Claude Desktop": claude, "Cursor": cursor}
    original = json.loads(cursor.read_text())["mcpServers"]["notes"]
    run(tmp_path, apps, "1", "1", "n", "n")
    run(tmp_path, apps, "2", "1", "n", "n")
    claude.write_text("{ broken since")
    said = []
    assert run_undo(said.append, tmp_path / "home", apps=apps) == 0
    assert json.loads(cursor.read_text())["mcpServers"]["notes"] == original and claude.read_text() == "{ broken since"
    assert any("could not be read as JSON" in line for line in said) and "1 server put back." in said[-1]


def test_undo_leaves_alone_a_server_changed_by_hand_since(tmp_path):
    path = settings(tmp_path, {"files": pretend_entry(tmp_path)})
    run(tmp_path, {"Claude Desktop": path}, "1", "n", "n")
    data = json.loads(path.read_text())
    data["mcpServers"]["files"] = {"command": "something-else"}
    path.write_text(json.dumps(data))
    said = []
    run_undo(said.append, tmp_path / "home", apps={"Claude Desktop": path})
    assert json.loads(path.read_text())["mcpServers"]["files"] == {"command": "something-else"} and "0 servers put back." in said[-1]


def test_the_tools_a_server_offers_are_read_by_starting_it_once(tmp_path):
    assert probe_tools(pretend_entry(tmp_path)) == ["read_note", "send_email", "delete_all", "fails"]
    assert probe_tools({"command": str(tmp_path / "no-such-server")}) == []
    assert not (tmp_path / "world.jsonl").exists()  # asking for the list runs no tool


def test_a_server_that_never_answers_is_stopped_when_the_time_is_up(tmp_path):
    started = time.monotonic()
    assert probe_tools({"command": sys.executable, "args": ["-c", "import time; time.sleep(60)"]}, timeout=1) == []
    assert time.monotonic() - started < 10


def test_the_wrapped_entry_really_puts_kettle_in_front_of_the_server(tmp_path):
    path = settings(tmp_path, {"files": pretend_entry(tmp_path)})
    run(tmp_path, {"Claude Desktop": path}, "1", "n", "n")
    entry = json.loads(path.read_text())["mcpServers"]["files"]

    def talk(*calls):
        """As an app does: each request waits for its answer before the next is sent."""
        app = subprocess.Popen([entry["command"]] + entry["args"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        lines = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
        lines += [{"jsonrpc": "2.0", "id": 3 + n, "method": "tools/call", "params": {"name": name, "arguments": {}}} for n, name in enumerate(calls)]
        replies = {}
        for line in lines:
            app.stdin.write(json.dumps(line) + "\n")
            app.stdin.flush()
            while line["id"] not in replies:
                message = json.loads(app.stdout.readline())
                if "id" in message:
                    replies[message["id"]] = message
        app.stdin.close()
        app.wait(30)
        return replies

    replies = talk("read_note")
    assert replies[3]["result"]["content"][0]["text"] == NO_APPROVER  # every tool asks, and no phone is set up
    assert not (tmp_path / "world.jsonl").exists()
    rules = rules_path(tmp_path / "home" / ".kettle", "Claude Desktop", "files")
    rules.write_text(rules.read_text().replace('default = "ask"', 'default = "ask"\nread_note = "free"'))
    replies = talk("read_note")
    assert replies[3]["result"]["content"][0]["text"].startswith("Sam's new address")
    assert len((tmp_path / "world.jsonl").read_text().splitlines()) == 1


# ---- the bot token --------------------------------------------------------------------


class Keychain:
    def __init__(self, code=0, out="123:secret-from-keychain\n"):
        self.calls, self.code, self.out = [], code, out

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        return subprocess.CompletedProcess(args, self.code, stdout=self.out, stderr="")


def test_the_token_comes_from_the_environment_first():
    keychain = Keychain()
    assert bot_token({"KETTLE_TELEGRAM_TOKEN": " 1:abc \n"}, keychain, "darwin") == "1:abc" and keychain.calls == []


def test_on_a_mac_the_token_is_read_from_the_keychain():
    keychain = Keychain()
    assert bot_token({}, keychain, "darwin") == "123:secret-from-keychain"
    assert keychain.calls == [["security", "find-generic-password", "-a", "kettle", "-s", KEYCHAIN_SERVICE, "-w"]]


def test_no_keychain_off_a_mac_and_nothing_when_it_has_none():
    keychain = Keychain()
    assert bot_token({}, keychain, "linux") == "" and keychain.calls == []
    assert bot_token({}, Keychain(code=44, out="security: The specified item could not be found in the keychain.\n"), "darwin") == ""

    def broken(args, **kwargs):
        raise OSError("no security command")

    assert bot_token({}, broken, "darwin") == ""
