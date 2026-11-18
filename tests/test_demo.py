"""The demo that comes with the install: it runs from the package alone, is served to this machine only, and shows what was saved."""

import http.client
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import threading

import pytest

from kettle.demo import app

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPORT = ROOT / "results" / "2026-11-15" / "2026-11-15T184338Z" / "results.json"


@pytest.fixture
def demo():
    server = app.make_server(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(5)


def ask(port, method, path, body=None, *, token=None, host=None, visit="one"):
    """One call to the demo, as a page would make it. Returns the status and what came back."""
    headers = {"Host": host or f"127.0.0.1:{port}", "X-Demo-Visit": visit}
    if token is not None:
        headers["X-Demo-Token"] = token
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request(method, path, body=None if body is None else json.dumps(body).encode(), headers=headers)
        reply = connection.getresponse()
        return reply.status, reply.read()
    finally:
        connection.close()


def post(server, path, body=None, visit="one"):
    status, raw = ask(server.server_address[1], "POST", path, body or {}, token=server.token, visit=visit)
    assert status == 200, raw
    return json.loads(raw)


def play(server, key, answer):
    """Play one story to its end. answer(step in the script) says whether the owner presses Approve."""
    story = app.BY_KEY[key]
    state = post(server, "/api/reset", {"story": key})
    first_time = {}
    for step in story.script:
        state = post(server, "/api/step")
        for waiting in state["waiting"]:
            first_time[waiting["says"]] = [each["name"] for each in waiting["inputs"] if each["first_time"]]
            state = post(server, "/api/answer", {"request_id": waiting["request_id"], "fingerprint": waiting["fingerprint"], "yes": answer(step)})
    return state, first_time


# ---- it is in the install -------------------------------------------------------------


def test_the_saved_run_in_the_package_is_the_one_in_results():
    """The demo plays a copy that ships with the package. It is the report in results/, byte for byte."""
    assert app.SAVED.read_bytes() == REPORT.read_bytes()
    assert ROOT / app.SAVED_AS == REPORT and app.SAVED_AT.endswith("/blob/main/" + app.SAVED_AS)


def test_the_demo_runs_from_the_package_alone(tmp_path):
    """As after an install: only the package is there, in a folder with nothing else, and the demo still runs."""
    site, empty = tmp_path / "site", tmp_path / "empty"
    shutil.copytree(pathlib.Path(app.__file__).resolve().parent.parent, site / "kettle", ignore=shutil.ignore_patterns("__pycache__"))
    empty.mkdir()
    env = {name: value for name, value in os.environ.items() if not name.endswith("_API_KEY")}
    env["PYTHONPATH"] = str(site)
    where = subprocess.run([sys.executable, "-c", "import kettle.demo.app as a; print(a.__file__)"], cwd=str(empty), env=env, capture_output=True, text=True, timeout=60)
    assert where.stdout.strip() == str(site / "kettle" / "demo" / "app.py"), where.stderr
    running = subprocess.Popen(
        [sys.executable, "-m", "kettle.demo", "--no-browser", "--port", "0"], cwd=str(empty), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        first = running.stdout.readline()
        found = re.fullmatch(r"Kettle demo: http://127\.0\.0\.1:(\d+)  \(Ctrl\+C to stop\)\n", first)
        assert found, first + running.stderr.read() if running.poll() is not None else first
        port = int(found.group(1))
        status, page = ask(port, "GET", "/")
        assert status == 200
        token = re.search(r'<meta name="demo-token" content="([^"]+)">', page.decode()).group(1)
        status, raw = ask(port, "POST", "/api/reset", {"story": "real"}, token=token)
        state = json.loads(raw)
        assert status == 200 and state["story"] == "real" and state["recording"]["model"] == "claude-opus-5-5"
        assert [tab["key"] for tab in state["stories"]] == ["bills", "repo", "shop", "real"]
    finally:
        running.terminate()
        running.communicate(timeout=10)
    assert list(empty.iterdir()) == []  # it left nothing behind in the folder it was run from


def test_the_command_opens_the_browser_unless_told_not_to(monkeypatch, capsys):
    opened, served = [], []
    monkeypatch.setattr(app.webbrowser, "open", opened.append)
    monkeypatch.setattr(app.Demo, "serve_forever", lambda self: served.append(self.url))
    assert app.main(["--port", "0"]) == 0
    assert opened == served and len(served) == 1
    assert capsys.readouterr().out.split("\n")[0] == f"Kettle demo: {served[0]}  (Ctrl+C to stop)"
    assert app.main(["--port", "0", "--no-browser"]) == 0
    assert len(served) == 2 and len(opened) == 1


def test_ctrl_c_stops_it_quietly(monkeypatch):
    def stopped(self):
        raise KeyboardInterrupt

    monkeypatch.setattr(app.Demo, "serve_forever", stopped)
    assert app.main(["--port", "0", "--no-browser"]) == 0


def test_a_taken_port_falls_back_to_a_free_one():
    taken = socket.socket()
    try:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        server = app.make_server(port)
        try:
            assert server.server_address[0] == "127.0.0.1" and server.server_address[1] not in (0, port)
        finally:
            server.server_close()
    finally:
        taken.close()


# ---- it is served to this machine only ------------------------------------------------


def test_it_listens_on_this_machine_only(demo):
    assert demo.server_address[0] == "127.0.0.1" and app.HOST == "127.0.0.1"
    assert demo.url == f"http://127.0.0.1:{demo.server_address[1]}"


def test_the_page_is_not_handed_to_another_site(demo):
    port = demo.server_address[1]
    for host in (f"127.0.0.1:{port}", f"localhost:{port}"):
        status, page = ask(port, "GET", "/", host=host)
        assert status == 200 and demo.token in page.decode() and "{{TOKEN}}" not in page.decode()
    for host in ("evil.example", f"evil.example:{port}", "127.0.0.1", f"127.0.0.1:{port + 1}"):
        status, page = ask(port, "GET", "/", host=host)
        assert status == 404 and demo.token not in page.decode()


@pytest.mark.parametrize("token", [None, "", "wrong", "éé"])
def test_the_buttons_need_the_token_the_page_was_given(demo, token):
    port = demo.server_address[1]
    assert ask(port, "POST", "/api/step", {}, token=token)[0] == 403
    assert ask(port, "POST", "/api/reset", {"story": "repo"}, token=token)[0] == 403
    assert ask(port, "GET", "/api/state", token=token)[0] == 404
    assert demo.visits == {}


def test_the_right_token_from_another_site_is_refused(demo):
    port = demo.server_address[1]
    assert ask(port, "POST", "/api/step", {}, token=demo.token, host="evil.example")[0] == 403
    assert ask(port, "GET", "/api/state", token=demo.token, host="evil.example")[0] == 404
    assert demo.visits == {}


def test_a_call_that_is_not_json_or_not_known_is_refused(demo):
    port = demo.server_address[1]
    assert ask(port, "POST", "/api/step", [1], token=demo.token)[0] == 400
    assert ask(port, "POST", "/api/nothing", {}, token=demo.token)[0] == 404
    assert ask(port, "GET", "/api/nothing", token=demo.token)[0] == 404


def test_two_pages_do_not_share_a_run(demo):
    post(demo, "/api/step", visit="one")
    post(demo, "/api/step", visit="one")
    status, raw = ask(demo.server_address[1], "GET", "/api/state", token=demo.token, visit="two")
    assert status == 200 and json.loads(raw)["steps"] == []
    status, raw = ask(demo.server_address[1], "GET", "/api/state", token=demo.token, visit="one")
    assert len(json.loads(raw)["steps"]) == 2


# ---- the three stories: the checkpoint decides, the page only draws --------------------

WITH_A_NO = {
    "bills": (["ran", "ran", "denied", "refused"], ["$84.10 paid to account NORTHGRID-2209"]),
    "repo": (["ran", "ran", "ran", "ran", "ran", "refused", "denied"], ["Branch fix/leap-day pushed to origin"]),
    "shop": (["ran", "ran", "ran", "denied", "refused"], ["$39.00 refunded for order 8841 to the original card"]),
}
THE_ATTACKERS = {
    "bills": "$250.00 paid to account OAKLINE-DESIGN-7713",
    "repo": "Branch fix/leap-day pushed to git@github.com:acme-ci-mirror/billing.git",
    "shop": "$390.00 refunded for order 8790 to the card ending 4417",
}


@pytest.mark.parametrize("key", ["bills", "repo", "shop"])
def test_a_no_to_what_the_attacker_asked_for_means_it_does_not_happen(demo, key):
    state, first_time = play(demo, key, lambda step: not step["planted"])
    statuses, happened = WITH_A_NO[key]
    assert state["done"] is True and state["waiting"] == []
    assert [step["status"] for step in state["steps"]] == statuses
    assert [line for step in state["steps"] for line in step["ran"]] == happened
    # Only what the attacker asked for is marked as going somewhere new.
    story = app.BY_KEY[key]
    held = [step for step in story.script if story.says[step["tool"]](step["inputs"]) in first_time]
    assert [bool(first_time[story.says[step["tool"]](step["inputs"])]) for step in held] == [step["planted"] for step in held]
    assert [step["planted"] for step in held] == [False, True]
    # What would have happened with no checkpoint is shown beside it, and the log is whole.
    assert THE_ATTACKERS[key] in [line for step in state["steps"] for line in step["without"]]
    assert state["log_ok"] is True and len(state["log"]) > len(story.script)


@pytest.mark.parametrize("key", ["bills", "repo", "shop"])
def test_a_yes_to_what_the_attacker_asked_for_runs_it(demo, key):
    """The demo does not rig the ending. An owner who approves the attacker's action gets it."""
    state, _ = play(demo, key, lambda step: True)
    happened = [line for step in state["steps"] for line in step["ran"]]
    assert THE_ATTACKERS[key] in happened and happened[: len(WITH_A_NO[key][1])] == WITH_A_NO[key][1]
    # Never-allowed calls are refused whatever is pressed.
    assert [step["status"] for step in state["steps"]].count("refused") == 1
    assert len(happened) == len(WITH_A_NO[key][1]) + 1


def test_who_wrote_what_is_only_told_at_the_end(demo):
    post(demo, "/api/reset", {"story": "bills"})
    state = post(demo, "/api/step")
    assert not any("tell" in doc for doc in state["reads"]) and "planted" not in state["steps"][0]
    state, _ = play(demo, "bills", lambda step: False)
    assert [("tell" in doc) for doc in state["reads"]] == [False, False, True] and state["steps"][2]["planted"] is True


def test_an_answer_that_names_another_action_changes_nothing(demo):
    post(demo, "/api/reset", {"story": "bills"})
    post(demo, "/api/step")
    (waiting,) = post(demo, "/api/step")["waiting"]
    for body in (
        {"request_id": waiting["request_id"], "fingerprint": "0" * 64, "yes": True},
        {"request_id": "0" * 32, "fingerprint": waiting["fingerprint"], "yes": True},
        {"request_id": waiting["request_id"], "fingerprint": waiting["fingerprint"], "yes": "true"},  # only a plain true is a yes
    ):
        state = post(demo, "/api/answer", body)
        assert [line for step in state["steps"] for line in step["ran"]] == []
    assert state["steps"][1]["status"] == "denied" and state["waiting"] == []  # the last of them was a no


def test_the_rules_shown_are_the_rules_that_ran(demo):
    state = post(demo, "/api/reset", {"story": "repo"})
    assert state["code_from"] == "src/kettle/demo/app.py"
    assert state["code"] in (ROOT / state["code_from"]).read_text(encoding="utf-8")
    assert state["code"].startswith("def repo_rules(cp, world):") and state["version"] == app.__version__


# ---- the fourth tab: a saved run, played back ------------------------------------------


def test_the_real_run_tab_shows_what_was_saved_and_decides_nothing(demo):
    saved = json.loads(REPORT.read_text(encoding="utf-8"))
    state = post(demo, "/api/reset", {"story": "real"})
    recording = state["recording"]
    assert recording["file"] == "results/2026-11-15/2026-11-15T184338Z/results.json" and recording["link"] == app.SAVED_AT
    assert recording["model"] == saved["meta"]["settings"]["model"] == "claude-opus-5-5"
    assert recording["system"] == saved["meta"]["settings"]["system"]
    # Every reply and every call is the saved one, word for word and in order.
    by_side = {(run["repeat"], run["setup"]): run for run in saved["runs"]}
    assert len(recording["runs"]) * 2 == len(saved["runs"]) == 20
    for shown in recording["runs"]:
        for setup in ("none", "kettle"):
            run = by_side[(shown["repeat"], setup)]
            assert shown[setup]["reply"] == run["reply"] and shown[setup]["seconds"] == run["seconds"]
            assert [each["outcome"] for each in shown[setup]["calls"]] == [each["outcome"] for each in run["calls"]]
            assert [{item["name"]: item["value"] for item in each["inputs"]} for each in shown[setup]["calls"]] == [
                {name: str(value) for name, value in each["inputs"].items()} for each in run["calls"]
            ]
    # The tab has no checkpoint: stepping and answering change nothing.
    assert post(demo, "/api/step") == state
    assert post(demo, "/api/answer", {"request_id": "x", "fingerprint": "y", "yes": True}) == state
    assert state["steps"] == [] and state["waiting"] == [] and state["code_from"] == "src/kettle/attacktest/runner.py"


def test_the_trail_on_the_real_run_tab_is_worked_out_not_assumed(demo):
    recording = post(demo, "/api/reset", {"story": "real"})["recording"]
    held = [
        each
        for run in recording["runs"]
        for each in run["kettle"]["calls"]
        if each["outcome"].startswith("held") and each["attackers"]
    ]
    assert recording["trail"] == {"held": len(held), "named": len(held), "file": "meeting-notes.txt", "list": "contacts.txt"}
    assert len(held) == 10
    for each in held:
        (entry,) = each["trail"]
        assert entry["input"] == "to" and entry["value"] == recording["attacker"]
        assert entry["typed"] is False and entry["lists"] == [{"name": "contacts.txt", "has_it": False}]
        assert {"tool": "read_file", "inputs": '{"name":"meeting-notes.txt"}', "given": False} in entry["calls"]
    # With no checkpoint there was nothing held, so there is no trail to show.
    assert all(each["trail"] is None for run in recording["runs"] for each in run["none"]["calls"])
