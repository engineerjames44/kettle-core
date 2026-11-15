"""The files in examples/ are what a new reader runs first, so they are run here as a reader would run them."""

import os
import pathlib
import select
import subprocess
import sys
import time

import pytest

from kettle.adapters import QUESTION

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [os.environ.get("PYTHONPATH"), str(ROOT / "src")]))}


def run(*args, **options):
    return subprocess.run([sys.executable, *args], cwd=str(ROOT), env=ENV, capture_output=True, text=True, timeout=60, **options)


def test_the_quickstart_runs_and_sends_once():
    done = run("examples/quickstart.py", stdin=subprocess.DEVNULL)
    assert done.returncode == 0, done.stderr
    assert "first run:  ran | sent: [('sam@example.com', 'See you at 3.')]" in done.stdout
    assert "second run: refused | sent: [('sam@example.com', 'See you at 3.')]" in done.stdout
    assert "chain intact" in done.stdout


def test_the_loop_example_sends_nothing_when_there_is_nobody_to_ask():
    done = run("examples/with_checkpoint.py", stdin=subprocess.DEVNULL)
    assert done.returncode == 0, done.stderr
    assert "! first time: no approved action has run with this value before" in done.stdout
    assert "Refused. Nothing was run." in done.stdout and "Emails sent: []" in done.stdout
    assert "chain intact" in done.stdout


def at_a_terminal(script, typed, typed_early=""):
    """Run a script with a pretend terminal on stdin. typed is typed once the question is on screen."""
    pty = pytest.importorskip("pty")
    ours, theirs = pty.openpty()
    try:
        running = subprocess.Popen([sys.executable, script], cwd=str(ROOT), env=ENV, stdin=theirs, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            os.write(ours, typed_early.encode())
            seen, deadline = b"", time.time() + 60
            while QUESTION.encode() not in seen:
                ready, _, _ = select.select([running.stdout], [], [], max(0.0, deadline - time.time()))
                more = os.read(running.stdout.fileno(), 4096) if ready else b""
                assert more, "the question never came: " + seen.decode(errors="replace")
                seen += more
            os.write(ours, typed.encode())
            rest, errors = running.communicate(timeout=60)
        finally:
            running.kill()
    finally:
        os.close(ours)
        os.close(theirs)
    assert running.returncode == 0, errors.decode(errors="replace")
    return (seen + rest).decode()


@pytest.mark.parametrize("typed, sent", [("yes", "[('sam@example.com', 'The meeting is at 3pm.')]"), ("no", "[]"), ("y", "[]"), ("", "[]")])
def test_the_loop_example_sends_only_after_yes_is_typed_at_a_real_terminal(typed, sent):
    out = at_a_terminal("examples/with_checkpoint.py", typed + "\n")
    assert f"Emails sent: {sent}" in out and "chain intact" in out


def test_a_yes_typed_before_the_loop_example_asks_is_not_taken_as_the_answer():
    out = at_a_terminal("examples/with_checkpoint.py", "no\n", typed_early="yes\nyes\n")
    assert "Refused. Nothing was run." in out and "Emails sent: []" in out and "chain intact" in out


def test_the_agent_example_can_be_run_by_the_attack_test(tmp_path):
    done = run("-m", "kettle.attacktest", "--agent", "examples.my_agent:agent", "--repeats", "1", "--only", "job-meeting-time", "--out", str(tmp_path), stdin=subprocess.DEVNULL)
    assert done.returncode == 0, done.stderr
    (folder,) = tmp_path.iterdir()
    assert (folder / "report.md").exists() and (folder / "results.json").exists()
