"""Setting up Kettle for Claude Code, in a pretend home folder. No real settings, Keychain, launchd or network."""

import json
import os
import plistlib
import stat
import subprocess
import sys

import pytest

from kettle import claude_code as cc
from kettle import claude_code_setup as cs

PYTHON = "/opt/my python/bin/python3"


class Launchd:
    """Stands in for launchctl. The daemon 'runs' once it is bootstrapped."""

    def __init__(self, home, starts=True):
        self.home, self.starts, self.calls, self.up, self.settings_at_start = home, starts, [], False, None

    def __call__(self, args, **kwargs):
        self.calls.append(args[:2])
        if args[1] == "bootstrap":
            settings = self.home / ".claude" / "settings.json"
            self.settings_at_start = settings.read_text() if settings.exists() else None
            self.up = self.starts
        if args[1] == "bootout":
            self.up = False
        return subprocess.CompletedProcess(args, 0, "", "")


def made(tmp_path, answers=("yes", "yes"), token="t0ken", chat=4242, platform="darwin", starts=True, root=None, project=None):
    launchd = Launchd(tmp_path, starts)
    said, asked, chats = [], [], []
    replies = list(answers)

    def ask(question):
        asked.append(question)
        if not replies:
            raise EOFError
        return replies.pop(0)

    def find_chat(the_token, say):
        chats.append(the_token)
        if isinstance(chat, Exception):
            raise chat
        return chat

    setup = cs.Setup(tmp_path, PYTHON, root, lambda: token, find_chat, ask=ask, say=said.append, run=launchd, running=lambda: launchd.up, platform=platform, uid=501, project=project)
    setup._pause = lambda seconds: None
    return setup, launchd, said, asked, chats


def settings_of(tmp_path):
    return json.loads((tmp_path / ".claude" / "settings.json").read_text())


def test_with_no_token_nothing_is_changed(tmp_path):
    setup, launchd, said, asked, _ = made(tmp_path, token="")
    assert setup.setup() == 2
    assert any(cs.KEYCHAIN_HINT in line for line in said) and asked == [] and launchd.calls == []
    assert not (tmp_path / ".kettle").exists() and not (tmp_path / ".claude").exists()


def test_a_full_setup_starts_the_daemon_before_adding_the_hook(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps({"model": "opus", "hooks": {"Stop": [{"hooks": []}]}}))
    setup, launchd, said, asked, chats = made(tmp_path)
    assert setup.setup() == 0
    assert chats == ["t0ken"] and launchd.calls == [["launchctl", "bootout"], ["launchctl", "bootstrap"]]
    assert "kettle.claude_code" not in launchd.settings_at_start  # the hook came after the daemon was up
    config = tmp_path / ".kettle" / "claude-code.toml"
    assert stat.S_IMODE(config.stat().st_mode) == 0o600 and stat.S_IMODE((tmp_path / ".kettle").stat().st_mode) == 0o700
    assert cc.read_config(str(config))["chat_id"] == 4242 and "t0ken" not in config.read_text()
    agent = plistlib.loads((tmp_path / "Library" / "LaunchAgents" / f"{cs.LABEL}.plist").read_bytes())
    assert agent["ProgramArguments"] == [PYTHON, "-m", "kettle.claude_code", "serve"] and agent["RunAtLoad"] and "EnvironmentVariables" not in agent
    after = settings_of(tmp_path)
    assert after["model"] == "opus" and after["hooks"]["Stop"] == [{"hooks": []}]
    handler = after["hooks"]["PreToolUse"][0]["hooks"][0]
    assert handler == {"type": "command", "command": f"'{PYTHON}' -m kettle.claude_code hook", "timeout": 360, "onFailure": "block"}
    assert after["hooks"]["PreToolUse"][0]["matcher"] == "*"
    assert json.loads((tmp_path / ".claude" / "settings.json.before-kettle").read_text())["model"] == "opus"
    assert len(asked) == 2


def test_no_to_the_daemon_adds_no_hook(tmp_path):
    setup, launchd, said, _, _ = made(tmp_path, answers=("no",))
    assert setup.setup() == 1
    assert launchd.calls == [] and not (tmp_path / ".claude" / "settings.json").exists()
    assert (tmp_path / ".kettle" / "claude-code.toml").exists()


def test_no_to_the_hook_leaves_the_settings_alone(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text('{"model": "opus"}')
    setup, _, _, _, _ = made(tmp_path, answers=("yes", "nope"))
    assert setup.setup() == 1
    assert (tmp_path / ".claude" / "settings.json").read_text() == '{"model": "opus"}'


def test_a_question_with_no_one_to_answer_is_a_no(tmp_path):
    setup, launchd, _, _, _ = made(tmp_path, answers=())
    assert setup.setup() == 1 and launchd.calls == []


def test_a_daemon_that_never_answers_gets_no_hook(tmp_path):
    setup, _, said, _, _ = made(tmp_path, starts=False)
    assert setup.setup() == 1
    assert not (tmp_path / ".claude" / "settings.json").exists() and any("did not answer" in line for line in said)


def test_settings_already_there_are_kept_and_a_hook_is_not_added_twice(tmp_path):
    (tmp_path / ".kettle").mkdir()
    (tmp_path / ".kettle" / "claude-code.toml").write_text("chat_id = 7\n")
    setup, _, _, _, chats = made(tmp_path)
    assert setup.setup() == 0 and chats == []
    assert (tmp_path / ".kettle" / "claude-code.toml").read_text() == "chat_id = 7\n"
    again, launchd, said, asked, _ = made(tmp_path)
    launchd.up = True
    assert again.setup() == 0 and asked == []
    assert len(settings_of(tmp_path)["hooks"]["PreToolUse"]) == 1


def test_no_chat_id_means_nothing_more_happens(tmp_path):
    setup, launchd, said, _, _ = made(tmp_path, chat=RuntimeError("no message with the code came in time"))
    assert setup.setup() == 1 and launchd.calls == [] and not (tmp_path / ".kettle" / "claude-code.toml").exists()
    assert any("no message with the code" in line for line in said)
    setup, _, _, _, chats = made(tmp_path / "b")
    assert setup.setup(chat_id=99) == 0 and chats == []


def test_a_settings_file_it_cannot_read_is_left_alone(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{ not json")
    setup, _, said, _, _ = made(tmp_path)
    assert setup.setup() == 1
    assert (tmp_path / ".claude" / "settings.json").read_text() == "{ not json"
    assert any('"onFailure": "block"' in line for line in said)


def test_not_on_a_mac_there_is_no_login_item(tmp_path):
    setup, launchd, said, _, _ = made(tmp_path, answers=("yes",), platform="linux")
    assert setup.setup() == 0 and launchd.calls == []
    assert any("serve" in line for line in said) and settings_of(tmp_path)["hooks"]["PreToolUse"]


def test_from_source_the_daemon_and_the_hook_get_the_source_folder(tmp_path):
    setup, _, _, _, _ = made(tmp_path, root="/src/kettle core/src")
    assert setup.setup() == 0
    agent = plistlib.loads((tmp_path / "Library" / "LaunchAgents" / f"{cs.LABEL}.plist").read_bytes())
    assert agent["EnvironmentVariables"] == {"PYTHONPATH": "/src/kettle core/src"}
    assert settings_of(tmp_path)["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == f"PYTHONPATH='/src/kettle core/src' '{PYTHON}' -m kettle.claude_code hook"


def test_uninstall_takes_the_hook_out_first_and_keeps_the_log(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "mine.sh"}]}]}}))
    setup, launchd, _, _, _ = made(tmp_path)
    assert setup.setup() == 0
    seen = {}
    removing, launchd, _, _, _ = made(tmp_path)

    def bootout(args, **kwargs):
        seen["settings"] = settings_of(tmp_path)
        return subprocess.CompletedProcess(args, 0, "", "")

    removing.run = bootout
    assert removing.uninstall() == 0
    assert not cs.has_hook(seen["settings"])  # the hook was gone before the daemon stopped
    assert settings_of(tmp_path) == {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "mine.sh"}]}]}}
    assert not (tmp_path / "Library" / "LaunchAgents" / f"{cs.LABEL}.plist").exists() and (tmp_path / ".kettle" / "claude-code.toml").exists()


def test_uninstall_asks_and_a_no_stops_it(tmp_path):
    setup, _, _, _, _ = made(tmp_path)
    assert setup.setup() == 0
    removing, launchd, _, _, _ = made(tmp_path, answers=("no",))
    assert removing.uninstall() == 1 and cs.has_hook(settings_of(tmp_path)) and launchd.calls == []


def test_add_and_remove_leave_everything_else_as_it_was():
    before = {"model": "x", "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "a.sh"}]}], "Stop": []}}
    entry = cs.hook_entry(cs.hook_command(PYTHON, None), 300)
    added = cs.add_hook(before, entry)
    assert cs.has_hook(added) and not cs.has_hook(before) and len(added["hooks"]["PreToolUse"]) == 2
    assert cs.remove_hook(added) == before
    assert cs.remove_hook(cs.add_hook({}, entry)) == {}
    with pytest.raises(ValueError):
        cs.add_hook({"hooks": []}, entry)


def test_the_hook_command_runs_through_a_shell_and_fails_closed(tmp_path):
    """The command setup writes, run the way Claude Code runs it, with no daemon in a pretend home."""
    command = cs.hook_command(sys.executable, str(cs.source_root() or ""))
    call = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": str(tmp_path)})
    env = {key: value for key, value in os.environ.items() if not key.endswith("_API_KEY")} | {"HOME": str(tmp_path)}
    done = subprocess.run(["/bin/sh", "-c", command], input=call, capture_output=True, text=True, env=env, timeout=60)
    assert done.returncode == 0
    assert json.loads(done.stdout)["hookSpecificOutput"]["permissionDecisionReason"] == cc.NOT_RUNNING


def test_a_kettle_folder_with_loose_rights_is_closed_up(tmp_path):
    (tmp_path / ".kettle").mkdir()
    os.chmod(tmp_path / ".kettle", 0o755)
    setup, _, _, _, _ = made(tmp_path)
    assert setup.setup() == 0 and stat.S_IMODE((tmp_path / ".kettle").stat().st_mode) == 0o700


def test_one_project_only_goes_in_its_personal_settings(tmp_path):
    project = tmp_path / "work" / "app"
    project.mkdir(parents=True)
    setup, _, said, _, _ = made(tmp_path, project=project)
    assert setup.setup() == 0
    local = json.loads((project / ".claude" / "settings.local.json").read_text())
    assert cs.has_hook(local) and not (tmp_path / ".claude" / "settings.json").exists()
    removing, _, _, _, _ = made(tmp_path, project=project)
    assert removing.uninstall() == 0 and json.loads((project / ".claude" / "settings.local.json").read_text()) == {}
