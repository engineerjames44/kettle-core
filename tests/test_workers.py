"""Two workers, one approval: threads, separate checkpoints and separate processes.

However many try at once, the action runs once. Also: a process that dies in the
middle of an action leaves it marked for checking, and it is never run again.
"""

import os
import subprocess
import sys
import threading

from kettle import NEEDS_YES, Checkpoint

from conftest import EMAIL, World, add_tools

WORKER = os.path.join(os.path.dirname(__file__), "_worker.py")


def _race(count, attempt):
    """Start count threads that all call attempt() at the same moment; return what each got."""
    barrier = threading.Barrier(count)
    results = [None] * count

    def go(index):
        barrier.wait()
        results[index] = attempt(index)

    threads = [threading.Thread(target=go, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert all(result is not None for result in results)
    return results


def test_many_threads_one_yes_runs_once(cp, world, approved):
    statuses = [decision.status for decision in _race(24, lambda index: cp.run(approved.request_id))]
    assert statuses.count("ran") == 1
    assert statuses.count("refused") == 23
    assert world.ran == [("send_email", EMAIL)]


def test_many_checkpoints_on_one_store_one_yes_runs_once(cp, world, approved, db_path):
    others = []
    for _ in range(8):
        other = Checkpoint(db_path, clock=cp._clock)
        add_tools(other, world)
        others.append(other)
    statuses = [decision.status for decision in _race(8, lambda index: others[index].run(approved.request_id))]
    for other in others:
        other.close()
    assert statuses.count("ran") == 1
    assert statuses.count("refused") == 7
    assert world.ran == [("send_email", EMAIL)]


def test_a_yes_and_a_no_arriving_together_never_both_win(cp, world, held):
    for _ in range(20):
        request = cp.request("send_email", dict(EMAIL))

        def attempt(index, request=request):
            if index % 2:
                return cp.deny(request.request_id).status
            cp.approve(request.request_id, request.fingerprint)
            return cp.run(request.request_id).status

        statuses = _race(2, attempt)
        state = cp.status(request.request_id)["state"]
        sent = len(world.ran)
        world.ran.clear()
        if state == "denied":
            assert sent == 0 and "ran" not in statuses
        else:
            assert state == "ran" and sent == 1 and statuses.count("ran") == 1


def _start(db_path, request_id, out_file, go_file, mode):
    return subprocess.Popen(
        [sys.executable, WORKER, db_path, request_id, out_file, go_file, mode],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _lines(path):
    if not os.path.exists(path):
        return []
    with open(path) as handle:
        return handle.read().splitlines()


def test_many_processes_one_yes_runs_once(tmp_path):
    db_path = str(tmp_path / "kettle.db")
    out_file, go_file = str(tmp_path / "sent.txt"), str(tmp_path / "go")
    parent = Checkpoint(db_path)
    parent.tool("send_email", lambda to, body: None, level=NEEDS_YES)
    held = parent.request("send_email", dict(EMAIL))
    assert parent.approve(held.request_id, held.fingerprint).status == "approved"

    workers = [_start(db_path, held.request_id, out_file, go_file, "run") for _ in range(8)]
    open(go_file, "w").close()
    outputs = [worker.communicate(timeout=120) for worker in workers]
    statuses = [out.strip() for out, _ in outputs]

    assert all(worker.returncode == 0 for worker in workers), [err for _, err in outputs]
    assert statuses.count("ran") == 1, statuses
    assert statuses.count("refused") == 7, statuses
    assert len(_lines(out_file)) == 1
    assert parent.status(held.request_id)["state"] == "ran"
    assert parent.verify_log()[0]
    parent.close()


def test_a_process_that_dies_mid_action_is_marked_for_checking_and_never_rerun(tmp_path):
    db_path = str(tmp_path / "kettle.db")
    out_file, go_file = str(tmp_path / "sent.txt"), str(tmp_path / "go")
    open(go_file, "w").close()
    world = World()
    parent = Checkpoint(db_path)
    add_tools(parent, world)
    held = parent.request("send_email", dict(EMAIL))
    parent.approve(held.request_id, held.fingerprint)

    crashed = _start(db_path, held.request_id, out_file, go_file, "crash")
    crashed.communicate(timeout=120)
    assert crashed.returncode == 17
    assert len(_lines(out_file)) == 1  # it did send, then died before it could say so

    assert parent.status(held.request_id)["state"] == "running"
    assert parent.run(held.request_id).status == "refused"
    assert parent.approve(held.request_id, held.fingerprint).status == "refused"

    retry = _start(db_path, held.request_id, out_file, go_file, "run")
    out, _ = retry.communicate(timeout=120)
    assert out.strip() == "refused"

    assert len(_lines(out_file)) == 1
    assert world.ran == []
    assert [item["request_id"] for item in parent.needs_checking(older_than=0)] == [held.request_id]
    parent.close()


def test_workers_sharing_a_store_wait_for_each_other_and_none_is_turned_away(cp, world, db_path):
    others = [Checkpoint(db_path) for _ in range(3)]
    for other in others:
        add_tools(other, World())
    checkpoints = [cp] + others

    def attempt(index):
        return [checkpoints[index % 4].request("read_note", {}).status for _ in range(25)]

    results = _race(8, attempt)
    assert [status for statuses in results for status in statuses] == ["ran"] * 200
    ok, detail = cp.verify_log()
    assert ok and detail.startswith("400 entries")
