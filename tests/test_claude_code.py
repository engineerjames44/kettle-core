"""Kettle in front of Claude Code: the decider, the daemon and the hook, with a pretend phone. No network."""

import io
import json
import os
import shutil
import socket
import stat
import tempfile
import threading
import time

import pytest

from kettle import Checkpoint
from kettle import claude_code as cc

HOME = os.path.realpath(os.path.expanduser("~"))


class Owner:
    """Stands in for the owner's phone. answer is "approve", "deny" or None (never answers)."""

    def __init__(self, cp, answer):
        self.cp, self.answer, self.asked, self.previews, self.tools, self.started = cp, answer, [], [], [], 0

    def start(self):
        self.started += 1

    def stop(self):
        pass

    def wait(self, request_id, timeout=None):
        found = self.cp.status(request_id)
        if found["state"] == "held" and request_id not in self.asked:
            self.asked.append(request_id)
            self.previews += [item["preview"] for item in self.cp.pending() if item["request_id"] == request_id]
            self.tools += [item["tool"] for item in self.cp.pending() if item["request_id"] == request_id]
            if self.answer == "approve":
                self.cp.approve(request_id, found["fingerprint"], "test owner")
            elif self.answer == "deny":
                self.cp.deny(request_id, "test owner")
        time.sleep(min(timeout or 0.02, 0.02))
        return self.cp.status(request_id)["state"]


def settings(**more):
    base = {"chat_id": None, "wait_seconds": 1.0, "allow": ["pytest"], "folders": [], "read_only": [], "sites": ["docs.python.org"], "store": ":memory:", "socket": ""}
    base.update(more)
    return base


@pytest.fixture
def project():
    folder = os.path.realpath(tempfile.mkdtemp(prefix="kc-project-"))
    yield folder
    shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture
def decider_for():
    made = []

    def make(answer="approve", **more):
        cp = Checkpoint(":memory:", hold_seconds=60)
        owner = Owner(cp, answer) if answer != "no phone" else None
        decider = cc.Decider(cp, settings(**more), owner)
        made.append(cp)
        return decider, owner, cp

    yield make
    for cp in made:
        cp.close()


def call(tool, inputs, cwd):
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": inputs, "cwd": cwd, "session_id": "s1"}


def decision(answer):
    return answer["hookSpecificOutput"]["permissionDecision"] if answer else None


def reason(answer):
    return answer["hookSpecificOutput"]["permissionDecisionReason"]


# ---- the decider ------------------------------------------------------------------------


def test_a_free_call_gets_no_decision_and_never_reaches_the_phone(decider_for, project):
    decider, owner, _ = decider_for()
    assert decider.decide(call("Bash", {"command": "ls -la", "description": "list"}, project)) == {}
    assert decider.decide(call("Bash", {"command": "pytest -q"}, project)) == {}
    assert owner.asked == [] and owner.started == 0


def test_a_risky_call_waits_for_the_phone(decider_for, project):
    decider, owner, cp = decider_for("approve")
    answer = decider.decide(call("Bash", {"command": "git push"}, project))
    assert decision(answer) == "allow" and reason(answer) == cc.APPROVED_TEXT
    assert len(owner.asked) == 1 and cp.status(owner.asked[0])["state"] == "ran"
    assert "git push" in owner.previews[0]


def test_deny_and_no_answer_both_deny(decider_for, project):
    decider, _, _ = decider_for("deny")
    assert reason(decider.decide(call("Bash", {"command": "git push"}, project))) == cc.DENIED_TEXT
    decider, owner, cp = decider_for(None)
    answer = decider.decide(call("Bash", {"command": "git push"}, project))
    assert decision(answer) == "deny" and reason(answer) == cc.NO_ANSWER
    assert cp.status(owner.asked[0])["state"] == "held"  # never run, whatever the owner presses later


def test_never_is_denied_with_the_rules_reason_and_no_phone(decider_for, project):
    decider, owner, _ = decider_for()
    answer = decider.decide(call("Bash", {"command": "rm -rf /"}, project))
    assert decision(answer) == "deny" and "Never allowed" in reason(answer) and owner.asked == []


def test_with_no_phone_every_ask_is_denied(decider_for, project):
    decider, _, _ = decider_for("no phone")
    assert reason(decider.decide(call("Bash", {"command": "git push"}, project))) == cc.NO_PHONE
    assert decider.decide(call("Bash", {"command": "ls"}, project)) == {}


def test_tools_kettle_does_not_know_get_no_decision(decider_for, project):
    decider, owner, _ = decider_for()
    for tool in ("mcp__mail__send", "WebSearch", "Agent", "AskUserQuestion"):
        assert decider.decide(call(tool, {"anything": "at all"}, project)) == {}
    assert owner.asked == []


def test_writing_in_the_project_is_free_and_elsewhere_asks(decider_for, project):
    decider, owner, _ = decider_for("deny")
    assert decider.decide(call("Write", {"file_path": f"{project}/a.py", "content": "x = 1\n"}, project)) == {}
    assert decider.decide(call("Edit", {"file_path": f"{project}/a.py", "old_string": "1", "new_string": "2", "replace_all": False}, project)) == {}
    assert decider.decide(call("Write", {"file_path": "a.py", "content": "x"}, project)) == {}  # relative to the session's folder
    assert decision(decider.decide(call("Write", {"file_path": f"{HOME}/.zshrc", "content": "x"}, project))) == "deny"
    assert decision(decider.decide(call("Write", {"file_path": f"{project}/.claude/settings.json", "content": "{}"}, project))) == "deny"
    assert len(owner.asked) == 2


def test_kettles_own_folder_is_protected(decider_for, project):
    decider, owner, _ = decider_for("approve")
    answer = decider.decide(call("Write", {"file_path": f"{HOME}/.kettle/claude-code.toml", "content": "chat_id = 1"}, project))
    assert decision(answer) == "deny" and "Never allowed" in reason(answer) and owner.asked == []
    assert decision(decider.decide(call("Read", {"file_path": f"{HOME}/.kettle/claude-code.db"}, project))) == "allow"
    assert len(owner.asked) == 1  # reading it asked first


def test_an_input_kettle_was_not_told_about_asks(decider_for, project):
    decider, owner, _ = decider_for("deny")
    assert decision(decider.decide(call("Bash", {"command": "ls", "dangerouslyDisableSandbox": True}, project))) == "deny"
    assert decision(decider.decide(call("Edit", {"file_path": f"{project}/a.py", "old_string": "a", "new_string": "b", "surprise": 1}, project))) == "deny"
    assert len(owner.asked) == 2


def test_reading_searching_and_fetching(decider_for, project):
    decider, owner, _ = decider_for("deny")
    assert decider.decide(call("Read", {"file_path": f"{project}/README.md", "offset": 1, "limit": 20}, project)) == {}
    assert decider.decide(call("Grep", {"pattern": "TODO", "output_mode": "content", "-n": True}, project)) == {}
    assert decider.decide(call("Glob", {"pattern": "**/*.py"}, project)) == {}
    assert decision(decider.decide(call("Grep", {"pattern": "KEY", "path": f"{HOME}/.ssh"}, project))) == "deny"
    assert decider.decide(call("WebFetch", {"url": "https://docs.python.org/3/library/json.html", "prompt": "summarise"}, project)) == {}
    assert decision(decider.decide(call("WebFetch", {"url": "https://unknown.example/x", "prompt": "p"}, project))) == "deny"
    localhost = decider.decide(call("WebFetch", {"url": "http://127.0.0.1:8080/", "prompt": "p"}, project))
    assert "Never allowed" in reason(localhost)
    assert len(owner.asked) == 2


def test_a_session_in_the_home_folder_gets_no_folder_free(decider_for):
    decider, owner, _ = decider_for("deny")
    for cwd in (HOME, "/", os.path.dirname(HOME)):
        assert decision(decider.decide(call("Write", {"file_path": f"{HOME}/notes.txt", "content": "x"}, cwd))) == "deny"
    assert decision(decider.decide(call("Bash", {"command": "ls"}, HOME))) == "deny"  # it lists the home folder: a read outside, as for Read
    assert len(owner.asked) == 4


def test_extra_folders_from_the_settings_are_free(decider_for, project):
    other = os.path.realpath(tempfile.mkdtemp(prefix="kc-other-"))
    try:
        decider, owner, _ = decider_for("deny", folders=[other])
        assert decider.decide(call("Write", {"file_path": f"{other}/x.txt", "content": "x"}, project)) == {}
        assert decider.decide(call("Write", {"file_path": f"{other}/x.txt", "content": "x"}, HOME)) == {}
    finally:
        shutil.rmtree(other, ignore_errors=True)


def test_each_folder_gets_its_own_tool_and_the_card_names_it(decider_for, project):
    other = os.path.realpath(tempfile.mkdtemp(prefix="kc-other-"))
    try:
        decider, owner, cp = decider_for("deny")
        decider.decide(call("Write", {"file_path": f"{other}/x.txt", "content": "x"}, project))  # outside this session's folder: asks
        assert decider.decide(call("Write", {"file_path": f"{other}/x.txt", "content": "x"}, other)) == {}  # inside that one's: free
        assert owner.tools == [f"Write in {project}"]
    finally:
        shutil.rmtree(other, ignore_errors=True)


def test_calls_it_cannot_read_are_denied(decider_for, project):
    decider, owner, _ = decider_for()
    for bad in (None, [], "x", {"tool_name": "Bash"}, {**call("Bash", {"command": "ls"}, project), "hook_event_name": "PostToolUse"}, call(3, {}, project), call("Bash", "ls", project)):
        assert reason(decider.decide(bad)) == cc.BAD_CALL
    for cwd in (None, "relative/path", "", f"{project}\x00x"):
        assert reason(decider.decide(call("Bash", {"command": "ls"}, cwd))) == cc.NO_FOLDER
    assert owner.asked == []


def test_a_failure_inside_is_a_deny(decider_for, project, monkeypatch):
    decider, _, _ = decider_for()

    class Broken:
        def request(self, *args, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(decider, "_gate", Broken())
    assert reason(decider.decide(call("Bash", {"command": "ls"}, project))) == cc.BROKE


def test_a_hook_that_gives_up_gets_nothing_run(decider_for, project):
    decider, owner, cp = decider_for(None, wait_seconds=30)
    stop = threading.Event()
    threading.Timer(0.2, stop.set).start()
    started = time.time()
    answer = decider.decide(call("Bash", {"command": "git push"}, project), stop)
    assert reason(answer) == cc.GAVE_UP and time.time() - started < 5
    assert cp.status(owner.asked[0])["state"] == "held"


def test_a_yes_that_no_longer_fits_is_refused_at_the_last_look(decider_for, project, monkeypatch):
    decider, owner, cp = decider_for("approve")
    real_run = cp.run

    def run_refused(request_id):
        made = real_run.__self__  # the same checkpoint
        made.deny(request_id, "changed underneath")
        return real_run(request_id)

    monkeypatch.setattr(cp, "run", run_refused)
    answer = decider.decide(call("Bash", {"command": "git push"}, project))
    assert decision(answer) == "deny"


# ---- the answers --------------------------------------------------------------------------


def test_only_well_formed_answers_pass():
    assert cc._answer_ok({}) and cc._answer_ok(cc.allow("x")) and cc._answer_ok(cc.deny("x"))
    for bad in (None, [], {"x": 1}, {"hookSpecificOutput": {**cc.allow("x")["hookSpecificOutput"], "permissionDecision": "ask"}}, {"hookSpecificOutput": {**cc.allow("x")["hookSpecificOutput"], "updatedInput": {}}}, {**cc.allow("x"), "continue": False}, {"hookSpecificOutput": {**cc.allow("x")["hookSpecificOutput"], "permissionDecisionReason": 3}}, {"hookSpecificOutput": {**cc.allow("x")["hookSpecificOutput"], "hookEventName": "PostToolUse"}}):
        assert not cc._answer_ok(bad)


# ---- the daemon and the hook --------------------------------------------------------------


@pytest.fixture
def daemon():
    """Start a real daemon on a socket of its own; the phone is pretend."""
    folder = tempfile.mkdtemp(prefix="kc", dir="/tmp")
    started = []

    def start(answer="approve", **more):
        config = settings(socket=os.path.join(folder, "k", "s.sock"), **more)
        ready, box, owners = threading.Event(), [], []

        def approver_for(cp):
            owners.append(Owner(cp, answer))
            return owners[0]

        thread = threading.Thread(target=cc.serve, args=(config,), kwargs={"approver_for": approver_for, "ready": ready, "server_box": box}, daemon=True)
        thread.start()
        assert ready.wait(5)
        started.append((box[0], thread))
        return config["socket"], owners[0], box[0]

    yield start
    for server, thread in started:
        server.shutdown()
        thread.join(5)
    shutil.rmtree(folder, ignore_errors=True)


def run_hook(path, the_call):
    out = io.StringIO()
    raw = the_call if type(the_call) is bytes else json.dumps(the_call).encode()
    assert cc.hook(stdin=io.BytesIO(raw), stdout=out, socket_path=path) == 0
    text = out.getvalue()
    return json.loads(text) if text else {}


def test_the_hook_and_the_daemon_together(daemon, project):
    path, owner, _ = daemon("approve")
    assert run_hook(path, call("Bash", {"command": "ls"}, project)) == {}
    assert decision(run_hook(path, call("Bash", {"command": "git push"}, project))) == "allow"
    assert "Never allowed" in reason(run_hook(path, call("Bash", {"command": "rm -rf ~"}, project)))
    assert len(owner.asked) == 1


def test_the_socket_and_its_folder_are_the_owners_alone(daemon):
    path, _, _ = daemon()
    assert stat.S_IMODE(os.stat(path).st_mode) & 0o077 == 0
    assert stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode) == 0o700
    assert cc.status(path)


def test_with_no_daemon_the_hook_denies(project):
    folder = tempfile.mkdtemp(prefix="kc", dir="/tmp")
    try:
        answer = run_hook(os.path.join(folder, "none.sock"), call("Bash", {"command": "ls"}, project))
        assert decision(answer) == "deny" and reason(answer) == cc.NOT_RUNNING
        assert not cc.status(os.path.join(folder, "none.sock"))
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_the_hook_denies_what_it_cannot_read(daemon, project):
    path, _, _ = daemon()
    assert reason(run_hook(path, b"not json")) == cc.BAD_CALL
    assert reason(run_hook(path, b'{"hook_event_name": "PreToolUse"}')) == cc.BAD_CALL


def test_the_hook_denies_an_answer_it_does_not_expect(project, monkeypatch):
    folder = tempfile.mkdtemp(prefix="kc", dir="/tmp")
    path = os.path.join(folder, "fake.sock")
    replies = [b'{"hookSpecificOutput": {"permissionDecision": "allow"}}\n', b"nonsense\n", b'{"hookSpecificOutput"', b"[" + b" " * cc.MAX_REPLY + b"]\n"]
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as fake:
        fake.bind(path)
        fake.listen(4)

        def answer_each():
            for reply in replies:
                connection, _ = fake.accept()
                with connection:
                    connection.recv(65536)
                    connection.sendall(reply)

        thread = threading.Thread(target=answer_each, daemon=True)
        thread.start()
        got = [run_hook(path, call("Bash", {"command": "ls"}, project)) for _ in replies]
        thread.join(5)
    shutil.rmtree(folder, ignore_errors=True)
    assert [reason(answer) for answer in got] == [cc.BROKE, cc.NOT_RUNNING, cc.NOT_RUNNING, cc.NOT_RUNNING]


def test_a_big_call_is_refused_and_a_long_write_still_goes_through(daemon, project, monkeypatch):
    path, _, _ = daemon()
    assert run_hook(path, call("Write", {"file_path": f"{project}/big.txt", "content": "x" * 2_000_000}, project)) == {}
    monkeypatch.setattr(cc, "MAX_CALL", 1000)
    assert reason(run_hook(path, call("Write", {"file_path": f"{project}/big.txt", "content": "x" * 2000}, project))) == cc.TOO_BIG


def test_a_hook_that_hangs_up_gets_nothing_run(daemon, project):
    path, owner, server = daemon(None, wait_seconds=30)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as line:
        line.connect(path)
        line.sendall(json.dumps(call("Bash", {"command": "git push"}, project)).encode() + b"\n")
        for _ in range(100):
            if owner.asked:
                break
            time.sleep(0.02)
    time.sleep(1.0)
    assert owner.asked and owner.cp.status(owner.asked[0])["state"] == "held"


def test_a_second_daemon_will_not_start_and_a_stale_socket_is_cleared(daemon):
    path, _, _ = daemon()
    with pytest.raises(cc.ConfigError, match="already running"):
        cc.Server(path, None)
    folder = tempfile.mkdtemp(prefix="kc", dir="/tmp")
    stale = os.path.join(folder, "s.sock")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as old:
            old.bind(stale)  # left behind by a daemon that died
        server = cc.Server(stale, None)
        server.server_close()
    finally:
        shutil.rmtree(folder, ignore_errors=True)


# ---- the settings and the command ----------------------------------------------------------


def test_the_settings(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text('chat_id = 5\nwait_seconds = 120\nallow = ["pytest"]\nfolders = ["~/x"]\n')
    config = cc.read_config(str(path))
    assert config["chat_id"] == 5 and config["wait_seconds"] == 120.0 and config["folders"] == [os.path.realpath(os.path.expanduser("~/x"))]
    for text, words in (("colour = 1\n", "not a setting"), ('chat_id = "5"\n', "wrong kind"), ("chat_id = true\n", "wrong kind"), ("wait_seconds = 1\n", "between"), ("allow = [1]\n", "list of text"), ('allow = [""]\n', "list of text"), ("= x", "could not be read")):
        path.write_text(text)
        with pytest.raises(cc.ConfigError, match=words):
            cc.read_config(str(path))
    with pytest.raises(cc.ConfigError, match="no settings file"):
        cc.read_config(str(tmp_path / "none.toml"))


def test_the_command(project, capsys):
    folder = tempfile.mkdtemp(prefix="kc", dir="/tmp")
    try:
        assert cc.main(["status", "--socket", os.path.join(folder, "x.sock")]) == 1
        assert "not running" in capsys.readouterr().out
        assert cc.main(["nonsense"]) == 2
        assert cc.main(["serve", "--config", os.path.join(folder, "none.toml")]) == 2
        assert "no settings file" in capsys.readouterr().err
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_a_long_write_is_kept_as_its_length_and_hash(decider_for, project):
    decider, owner, cp = decider_for("deny")
    text = "y" * (cc.BIG_TEXT + 1)
    answer = decider.decide(call("Write", {"file_path": f"{HOME}/big.txt", "content": text}, project))
    assert decision(answer) == "deny" and f"({len(text)} characters, sha256 " in owner.previews[0]
    other = "z" * (cc.BIG_TEXT + 1)
    decider.decide(call("Write", {"file_path": f"{HOME}/big.txt", "content": other}, project))
    assert len(owner.asked) == 2 and cp.status(owner.asked[0])["fingerprint"] != cp.status(owner.asked[1])["fingerprint"]
    assert decider.decide(call("Write", {"file_path": f"{project}/small.txt", "content": "short"}, project)) == {}


def test_a_folder_with_loose_rights_is_closed_up(project):
    folder = tempfile.mkdtemp(prefix="kc", dir="/tmp")
    try:
        inner = os.path.join(folder, "k")
        os.mkdir(inner, 0o755)
        os.chmod(inner, 0o755)
        server = cc.Server(os.path.join(inner, "s.sock"), None)
        server.server_close()
        assert stat.S_IMODE(os.stat(inner).st_mode) == 0o700
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_when_the_hook_hangs_up_the_daemon_stops_waiting(daemon, project):
    path, owner, _ = daemon(None, wait_seconds=30)
    waits = []
    real_wait = owner.wait

    def counted(request_id, timeout=None):
        waits.append(time.time())
        return real_wait(request_id, timeout)

    owner.wait = counted
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as line:
        line.connect(path)
        line.sendall(json.dumps(call("Bash", {"command": "git push"}, project)).encode() + b"\n")
        for _ in range(200):
            if owner.asked:
                break
            time.sleep(0.02)
    time.sleep(1.0)  # it has hung up: the daemon notices within half a second
    before = len(waits)
    time.sleep(0.5)
    assert len(waits) == before and owner.cp.status(owner.asked[0])["state"] == "held"


def test_the_daemon_refuses_a_big_call_itself(daemon, project, monkeypatch):
    path, owner, _ = daemon()
    monkeypatch.setattr(cc, "MAX_CALL", 1000)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as line:
        line.connect(path)
        line.sendall(json.dumps(call("Bash", {"command": "git push " + "x" * 2000}, project)).encode() + b"\n")
        reply = json.loads(line.recv(65536))
    assert reason(reply) == cc.TOO_BIG and owner.asked == []


def test_the_shell_cannot_read_round_the_folder_limits(decider_for, project):
    decider, owner, _ = decider_for("deny")
    for free in ("ls -la", "cat README.md", "git status", "grep -rn TODO .", "cd src && ls"):
        assert decider.decide(call("Bash", {"command": free}, project)) == {}, free
    for escape in ("cat ~/.kettle/claude-code.toml", f"cat {HOME}/.kettle/claude-code.db", "cd ~ && cat .kettle/claude-code.toml", "grep -r chat ~/.kettle", "cd .. && ls", "cat ~/Documents/notes.txt"):
        answer = decider.decide(call("Bash", {"command": escape}, project))
        assert decision(answer) == "deny" and reason(answer) == cc.DENIED_TEXT, escape
    assert len(owner.asked) == 6


def test_a_home_session_shell_reads_ask_from_where_it_runs(decider_for, project):
    decider, owner, _ = decider_for("deny", read_only=[project])
    assert decider.decide(call("Bash", {"command": f"cat {project}/x"}, HOME)) == {}  # a read-only folder from the settings
    assert decision(decider.decide(call("Bash", {"command": "ls"}, HOME))) == "deny"  # lists the home folder
    assert decision(decider.decide(call("Bash", {"command": "cat x"}, "/"))) == "deny"
    assert len(owner.asked) == 2 and owner.tools == ["Bash in ~", "Bash in /"]
