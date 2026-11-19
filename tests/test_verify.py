"""Receipts (python -m kettle.verify): who said yes, when, and to exactly what, read from the file without changing it."""

import os
import pathlib
import sqlite3
import subprocess
import sys
import time

import pytest

from kettle import NEEDS_YES, NEVER, Checkpoint
from kettle import verify
from kettle.checkpoint.record import ActionRecord
from kettle.checkpoint.store import StoreError, _entry_hash, GENESIS

from conftest import EMAIL, add_tools

ROOT = pathlib.Path(__file__).resolve().parent.parent
AT = "1970-01-12 13:46:40 UTC"  # the test clock starts at 1,000,000 seconds


@pytest.fixture(autouse=True)
def far_from_utc(monkeypatch):
    """The times printed are UTC wherever it is run."""
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def yes_and_run(cp, tool, inputs, by="owner"):
    held = cp.request(tool, dict(inputs))
    assert cp.approve(held.request_id, held.fingerprint, by).status == "approved"
    cp.run(held.request_id)
    return held


def rewrite(db_path, *statements, drop=()):
    """Change the file by hand, then write new hashes for the whole log, as someone who can write the file could."""
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    for statement in statements:
        connection.execute(statement)
    rows = [dict(row) for row in connection.execute("SELECT * FROM log ORDER BY seq") if row["seq"] not in drop]
    connection.execute("DELETE FROM log")
    prev = GENESIS
    for seq, row in enumerate(rows, 1):
        made = _entry_hash(prev, seq, row["at"], row["event"], row["request_id"], row["tool"], row["fingerprint"], row["detail"])
        connection.execute(
            "INSERT INTO log (seq, at, event, request_id, tool, fingerprint, detail, prev_hash, hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (seq, row["at"], row["event"], row["request_id"], row["tool"], row["fingerprint"], row["detail"], prev, made),
        )
        prev = made
    connection.commit()
    connection.close()


def seq_of(cp, event, request_id):
    return next(entry["seq"] for entry in cp.log() if entry["event"] == event and entry["request_id"] == request_id)


def told(db_path, capsys):
    code = verify.main([db_path])
    return code, capsys.readouterr().out.split("\n")


# ---- what a receipt says ---------------------------------------------------------------


def test_a_receipt_says_who_said_yes_when_and_to_exactly_what(cp, world, clock, db_path, capsys):
    cp.request("read_note", {})
    clock.forward(60)
    held = cp.request("send_email", dict(EMAIL))
    clock.forward(60)
    cp.approve(held.request_id, held.fingerprint, "telegram:55")
    clock.forward(60)
    cp.run(held.request_id)
    code, lines = told(db_path, capsys)
    assert code == 0
    assert lines == [
        f"Kettle receipts for {db_path}",
        "",
        "The log: 6 entries, chain intact.",
        "In it: held for a yes 1, denied 0, expired 0, cancelled 0, free actions started 1 (their inputs are not stored).",
        "",
        "Receipt 1: send_email",
        "  Yes: by telegram:55, 1970-01-12 13:48:40 UTC",
        "  Started: 1970-01-12 13:49:40 UTC",
        "  Outcome: ran, 1970-01-12 13:49:40 UTC",
        '  Action: "send_email"',
        '    "body": "See you at 3."',
        '    "to": "sam@example.com"',
        f"  Fingerprint: {held.fingerprint}",
        "",
        "1 receipt. Each action is the one its yes was for, and the log is whole.",
        "This cannot show entries cut from the end of the log, or a file rewritten by someone who can write it.",
        "",
    ]
    # What is printed is what the outside world saw happen.
    assert world.ran == [("read_note", {}), ("send_email", EMAIL)]


def test_only_actions_that_were_started_get_a_receipt(cp, world, clock, db_path, capsys):
    yes_and_run(cp, "send_email", EMAIL)
    denied = cp.request("pay", {"to": "sam@example.com", "amount": 5})
    cp.deny(denied.request_id)
    approved = cp.request("pay", {"to": "sam@example.com", "amount": 6})
    cp.approve(approved.request_id, approved.fingerprint)  # a yes that is never used
    cp.request("pay", {"to": "sam@example.com", "amount": 7})  # never answered
    cp.request("wipe_account", {})
    clock.forward(601)
    assert cp.run(approved.request_id).reason == "Refused: that yes has expired. Nothing was run."  # where the checkpoint writes that it expired
    yes_and_run(cp, "pay", {"to": "ana@example.com", "amount": 8}, by="ana")
    gone = cp.request("pay", {"to": "sam@example.com", "amount": 9})
    cp.tool("pay", world.pay, level=NEVER, replace=True)  # the rules change while it waits
    assert cp.approve(gone.request_id, gone.fingerprint).reason == "Refused and cancelled: pay is never allowed."
    report = verify.receipts(db_path)
    assert [(each["number"], each["tool"], each["yes_by"], each["outcome"]) for each in report["receipts"]] == [
        (1, "send_email", "owner", "ran"),
        (2, "pay", "ana", "ran"),
    ]
    assert report["also"] == {"held": 6, "denied": 1, "expired": 1, "cancelled": 1, "free": 0}
    assert report["wrong"] == [] and report["log_ok"] is True
    code, lines = told(db_path, capsys)
    assert code == 0 and "2 receipts. Each action is the one its yes was for, and the log is whole." in lines
    assert world.ran == [("send_email", EMAIL), ("pay", {"to": "ana@example.com", "amount": 8})]


def test_a_file_with_nothing_started_says_so(cp, db_path, capsys):
    cp.request("send_email", dict(EMAIL))
    code, lines = told(db_path, capsys)
    assert code == 0
    assert lines[4:] == [
        "",
        "No action that needs a yes has been started.",
        "",
        "0 receipts. Each action is the one its yes was for, and the log is whole.",
        "This cannot show entries cut from the end of the log, or a file rewritten by someone who can write it.",
        "",
    ]


def test_an_action_that_failed_part_way_is_not_said_to_have_run(db_path, clock, capsys):
    def breaks(to, amount):
        raise RuntimeError("the bank did not answer")

    cp = Checkpoint(db_path, clock=clock)
    cp.tool("pay", breaks, level=NEEDS_YES)
    assert yes_and_run(cp, "pay", {"to": "sam@example.com", "amount": 5}).status == "held"
    cp.close()
    code, lines = told(db_path, capsys)
    assert code == 0
    assert f"  Outcome: NOT KNOWN. It failed part way, {AT}, and may or may not have acted" in lines
    assert not any(line.startswith("  Outcome: ran") for line in lines)


def test_an_action_still_running_has_no_end_yet(db_path, clock, capsys):
    """Asked from inside the tool: the action has been started and nothing says how it ended."""
    during = []

    def pay(to, amount):
        during.append((verify.receipts(db_path), verify.to_text(verify.receipts(db_path)).split("\n")))

    cp = Checkpoint(db_path, clock=clock)
    cp.tool("pay", pay, level=NEEDS_YES)
    yes_and_run(cp, "pay", {"to": "sam@example.com", "amount": 5})
    cp.close()
    ((report, lines),) = during
    (receipt,) = report["receipts"]
    assert receipt["outcome"] is None and receipt["ended_at"] is None and report["wrong"] == []
    assert "  Outcome: NOT KNOWN. No end was recorded, and it may or may not have acted" in lines
    assert verify.receipts(db_path)["receipts"][0]["outcome"] == "ran"  # and once it has ended, it says so


def test_it_says_which_inputs_were_marked_first_time(db_path, world, clock, capsys):
    cp = Checkpoint(db_path, clock=clock)
    cp.tool("send_email", world.send_email, level=NEEDS_YES, watch=["to"])
    yes_and_run(cp, "send_email", EMAIL)
    yes_and_run(cp, "send_email", EMAIL)
    cp.close()
    first, second = verify.receipts(db_path)["receipts"]
    assert first["first_time"] == ["to"] and second["first_time"] == []
    code, lines = told(db_path, capsys)
    assert lines.count("  Marked first time when it was asked for: to") == 1 and lines.index("  Marked first time when it was asked for: to") < lines.index("Receipt 2: send_email")


def test_the_action_printed_reads_back_to_exactly_the_stored_one(cp, db_path):
    inputs = {"to": "sam@example.com‮", "body": "line one\nline two  \n" + "long " * 40}
    held = yes_and_run(cp, "send_email", inputs)
    (receipt,) = verify.receipts(db_path)["receipts"]
    assert receipt["action"] == ActionRecord.make("send_email", inputs).preview()
    assert receipt["fingerprint"] == held.fingerprint and receipt["request_id"] == held.request_id
    assert "‮" not in receipt["action"]  # the same safe drawing as the preview a human is shown


def test_a_receipt_shows_the_action_at_the_usual_width_whatever_width_the_checkpoint_showed_it_at(db_path, world, clock):
    narrow = Checkpoint(db_path, hold_seconds=600, clock=clock, preview_width=38)
    add_tools(narrow, world)
    inputs = {"to": "sam@example.com", "body": "long " * 40}
    try:
        held = yes_and_run(narrow, "send_email", inputs)
        assert max(len(line) for line in held.preview.split("\n")) == 38
        report = verify.receipts(db_path)
    finally:
        narrow.close()
    (receipt,) = report["receipts"]
    assert report["wrong"] == [] and report["log_ok"] is True
    assert receipt["action"] == ActionRecord.make("send_email", inputs).preview() != held.preview
    assert receipt["fingerprint"] == held.fingerprint  # the width was never part of the action


# ---- the file is only read ---------------------------------------------------------------


def test_the_file_is_not_changed_and_nothing_is_left_beside_it(cp, db_path, tmp_path, capsys):
    yes_and_run(cp, "send_email", EMAIL)
    cp.close()
    before, beside = pathlib.Path(db_path).read_bytes(), sorted(os.listdir(tmp_path))
    stamp = os.stat(db_path).st_mtime_ns
    assert verify.main([db_path]) == 0
    assert pathlib.Path(db_path).read_bytes() == before and os.stat(db_path).st_mtime_ns == stamp
    assert sorted(os.listdir(tmp_path)) == beside


def test_the_file_is_opened_so_that_it_cannot_be_written(cp, db_path):
    yes_and_run(cp, "send_email", EMAIL)
    opened = verify._ReadOnly(db_path)
    try:
        with pytest.raises(StoreError):
            with opened.write() as tx:
                tx.log(1.0, "made up")
        with pytest.raises(StoreError):
            opened.read("DELETE FROM log")
    finally:
        opened.close()
    assert cp.verify_log() == (True, "4 entries, chain intact")


def test_a_file_that_is_not_there_is_not_made(tmp_path, capsys):
    missing = str(tmp_path / "no-such.db")
    assert verify.main([missing]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == f"{missing} cannot be read: there is no such file.\n"
    assert os.listdir(tmp_path) == []


def test_a_file_that_is_not_a_checkpoints_is_refused(tmp_path, capsys):
    text, empty, other = tmp_path / "notes.txt", tmp_path / "empty.db", tmp_path / "other.db"
    text.write_text("not a database at all, " * 200, encoding="utf-8")
    sqlite3.connect(empty).close()
    connection = sqlite3.connect(other)
    connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute("INSERT INTO meta VALUES ('schema', '1')")
    connection.commit()
    connection.close()
    for path, why in ((text, "it is not a file a Kettle checkpoint keeps"), (empty, "it is not a file a Kettle checkpoint keeps"), (other, "it is not a file a Kettle checkpoint keeps"), (tmp_path, "there is no such file")):
        assert verify.main([str(path)]) == 2
        captured = capsys.readouterr()
        assert captured.out == "" and captured.err == f"{path} cannot be read: {why}.\n"
    assert sorted(os.listdir(tmp_path)) == ["empty.db", "notes.txt", "other.db"]


def test_a_file_from_another_version_is_refused(cp, db_path, capsys):
    yes_and_run(cp, "send_email", EMAIL)
    cp.close()
    rewrite(db_path, "UPDATE meta SET value = '99' WHERE key = 'schema'")
    assert verify.main([db_path]) == 2
    assert capsys.readouterr().err == f"{db_path} cannot be read: it was made by a different version of the checkpoint.\n"


def test_it_can_be_run_while_the_checkpoint_has_the_file_open(cp, db_path, capsys):
    yes_and_run(cp, "send_email", EMAIL)
    assert verify.main([db_path]) == 0
    assert yes_and_run(cp, "pay", {"to": "sam@example.com", "amount": 5}).status == "held"
    assert len(verify.receipts(db_path)["receipts"]) == 2


def test_a_write_in_the_middle_of_the_read_cannot_make_the_parts_disagree(cp, db_path, monkeypatch):
    yes_and_run(cp, "send_email", EMAIL)
    cp.close()
    read_the_log, tried = verify._ReadOnly.log_entries, []

    def and_then_a_write(self):
        entries = read_the_log(self)
        other = sqlite3.connect(db_path, timeout=0)
        try:
            other.execute("UPDATE requests SET state = 'denied'")
            other.commit()
            tried.append("written")
        except sqlite3.OperationalError:
            tried.append("had to wait")
        finally:
            other.close()
        return entries

    monkeypatch.setattr(verify._ReadOnly, "log_entries", and_then_a_write)
    report = verify.receipts(db_path)
    assert tried == ["had to wait"] and report["wrong"] == [] and len(report["receipts"]) == 1


def test_the_command_as_a_reader_would_run_it(cp, db_path):
    held = yes_and_run(cp, "send_email", EMAIL)
    cp.close()
    env = {name: value for name, value in os.environ.items() if not name.endswith("_API_KEY")}
    env["PYTHONPATH"] = str(pathlib.Path(verify.__file__).resolve().parent.parent)
    out = subprocess.run([sys.executable, "-m", "kettle.verify", db_path], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and out.stderr == ""
    assert f"  Fingerprint: {held.fingerprint}" in out.stdout.split("\n")
    missing = subprocess.run([sys.executable, "-m", "kettle.verify"], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60)
    assert missing.returncode == 2 and "python -m kettle.verify" in missing.stderr


# ---- what does not add up is said, and ends with 1 ---------------------------------------


def test_an_edited_log_is_reported(cp, db_path, capsys):
    yes_and_run(cp, "send_email", EMAIL, by="owner")
    cp.close()
    connection = sqlite3.connect(db_path)
    connection.execute("""UPDATE log SET detail = '{"by":"the boss"}' WHERE event = 'approved'""")
    connection.commit()
    connection.close()
    code, lines = told(db_path, capsys)
    assert code == 1
    assert lines[2] == "THE LOG HAS BEEN CHANGED: entry 2 was changed."
    assert lines[-5:] == [
        "",
        "1 thing did not add up:",
        "  The log has been changed: entry 2 was changed.",
        "This cannot show entries cut from the end of the log, or a file rewritten by someone who can write it.",
        "",
    ]
    assert not any("the log is whole" in line for line in lines)


def test_a_stored_action_swapped_for_another_is_reported_and_not_printed(cp, db_path, capsys):
    held = yes_and_run(cp, "send_email", EMAIL)
    cp.close()
    other = ActionRecord.make("send_email", {"to": "thief@example.net", "body": "See you at 3."})
    for changes in (
        [f"UPDATE requests SET record = '{other.canonical}'"],  # the action alone
        [f"UPDATE requests SET record = '{other.canonical}', fingerprint = '{other.fingerprint}', approved_fingerprint = '{other.fingerprint}'"],
    ):
        rewrite(db_path, *changes)
        code, lines = told(db_path, capsys)
        assert code == 1
        assert "  DOES NOT ADD UP: the stored action is not the one the log says was started" in lines
        assert "  Receipt 1: the stored action is not the one the log says was started." in lines
        assert not any("thief@example.net" in line or "sam@example.com" in line for line in lines)
        assert f"  Fingerprint: {held.fingerprint}" in lines  # the one the log holds


def test_a_log_that_names_another_tool_is_reported(cp, db_path, capsys):
    yes_and_run(cp, "send_email", EMAIL)
    cp.close()
    rewrite(db_path, "UPDATE log SET tool = 'read_note' WHERE event = 'started'")
    code, lines = told(db_path, capsys)
    assert code == 1 and "  Receipt 1: the stored action is not the one the log says was started." in lines
    assert not any("sam@example.com" in line for line in lines)


def test_a_stored_action_that_cannot_be_read_is_reported(cp, db_path, capsys):
    yes_and_run(cp, "send_email", EMAIL)
    cp.close()
    rewrite(db_path, "UPDATE requests SET record = '{not json'")
    code, lines = told(db_path, capsys)
    assert code == 1 and "  Receipt 1: the stored action cannot be read." in lines


def test_a_stored_action_that_is_gone_is_reported(cp, db_path, capsys):
    yes_and_run(cp, "send_email", EMAIL)
    cp.close()
    rewrite(db_path, "DELETE FROM requests")
    code, lines = told(db_path, capsys)
    assert code == 1 and "  Receipt 1: the file has no stored action for it." in lines


def test_a_started_action_with_no_yes_in_the_log_is_reported(cp, db_path, capsys):
    held = yes_and_run(cp, "send_email", EMAIL)
    approved = seq_of(cp, "approved", held.request_id)
    cp.close()
    rewrite(db_path, drop=(approved,))  # the yes taken out, and the chain made whole again
    code, lines = told(db_path, capsys)
    assert code == 1 and lines[2] == "The log: 3 entries, chain intact."
    assert "  Yes: NOT IN THE LOG" in lines and "  Receipt 1: the log has no yes for it." in lines


def test_a_yes_for_another_request_is_not_a_yes_for_this_one(cp, db_path, capsys):
    """The same action asked for twice has the same fingerprint. Each start still needs its own yes."""
    first = yes_and_run(cp, "send_email", EMAIL)
    second = yes_and_run(cp, "send_email", EMAIL)
    assert first.fingerprint == second.fingerprint and first.request_id != second.request_id
    approved = seq_of(cp, "approved", second.request_id)
    cp.close()
    rewrite(db_path, drop=(approved,))
    code, lines = told(db_path, capsys)
    assert code == 1 and lines[-4:-2] == ["1 thing did not add up:", "  Receipt 2: the log has no yes for it."]


def test_a_yes_for_a_different_action_is_reported(cp, db_path, capsys):
    yes_and_run(cp, "send_email", EMAIL)
    cp.close()
    rewrite(db_path, f"UPDATE log SET fingerprint = '{'0' * 64}' WHERE event = 'approved'")
    code, lines = told(db_path, capsys)
    assert code == 1 and "  Receipt 1: the yes in the log is for a different action." in lines


def test_a_yes_that_came_after_the_start_is_not_a_yes_for_it(cp, db_path, capsys):
    held = yes_and_run(cp, "send_email", EMAIL)
    approved, started = seq_of(cp, "approved", held.request_id), seq_of(cp, "started", held.request_id)
    cp.close()
    rewrite(db_path, f"UPDATE log SET seq = -1 WHERE seq = {approved}", f"UPDATE log SET seq = {approved} WHERE seq = {started}", f"UPDATE log SET seq = {started} WHERE seq = -1")
    code, lines = told(db_path, capsys)
    assert code == 1 and lines[2] == "The log: 4 entries, chain intact." and "  Receipt 1: the log has no yes for it." in lines


def test_an_action_the_log_says_started_twice_is_reported(cp, db_path, capsys):
    held = yes_and_run(cp, "send_email", EMAIL)
    cp.close()
    rewrite(db_path, "INSERT INTO log SELECT seq + 100, at, event, request_id, tool, fingerprint, detail, prev_hash, hash FROM log WHERE event = 'started'")
    code, lines = told(db_path, capsys)
    assert code == 1
    assert lines.count("  DOES NOT ADD UP: the log says it was started more than once") == 2
    assert [line for line in lines if line.startswith("Receipt ")] == ["Receipt 1: send_email", "Receipt 2: send_email"]
    assert held.request_id not in "\n".join(lines)


def test_a_request_the_file_calls_denied_and_the_log_calls_started_is_reported(cp, db_path, capsys):
    yes_and_run(cp, "send_email", EMAIL)
    cp.close()
    rewrite(db_path, "UPDATE requests SET state = 'denied'")
    code, lines = told(db_path, capsys)
    assert code == 1 and "  Receipt 1: the file says the request is denied, and the log says it was started." in lines


def test_a_log_cut_at_the_end_is_noticed_when_the_file_still_says_it_ran(cp, db_path, capsys):
    """The chain check alone cannot see entries cut from the end. The stored request still says it was started."""
    yes_and_run(cp, "pay", {"to": "sam@example.com", "amount": 5})
    held = yes_and_run(cp, "send_email", EMAIL)
    started = seq_of(cp, "started", held.request_id)
    cp.close()
    rewrite(db_path, drop=(started, started + 1))
    code, lines = told(db_path, capsys)
    assert code == 1 and lines[2] == "The log: 6 entries, chain intact."
    assert [line for line in lines if line.startswith("Receipt ")] == ["Receipt 1: pay"]
    assert lines[-5:] == [
        "",
        "1 thing did not add up:",
        f"  The file says a request ({held.request_id[:8]}) was started, and the log has no entry for it.",
        "This cannot show entries cut from the end of the log, or a file rewritten by someone who can write it.",
        "",
    ]


def test_the_end_of_one_action_is_not_given_to_another(cp, db_path, capsys):
    first = yes_and_run(cp, "pay", {"to": "sam@example.com", "amount": 5})
    yes_and_run(cp, "send_email", EMAIL)
    ran = seq_of(cp, "ran", first.request_id)
    cp.close()
    rewrite(db_path, drop=(ran,))  # the end of the first cut out, and the chain made whole again
    one, two = verify.receipts(db_path)["receipts"]
    assert (one["outcome"], one["ended_at"], two["outcome"]) == (None, None, "ran")
    code, lines = told(db_path, capsys)
    assert code == 1 and lines.count("  Outcome: NOT KNOWN. No end was recorded, and it may or may not have acted") == 1
    assert lines[-4:-2] == ["1 thing did not add up:", "  Receipt 1: the file says it ended, and the log has no end for it."]


def test_a_time_that_cannot_be_read_does_not_stop_the_rest(cp, db_path, capsys):
    yes_and_run(cp, "send_email", EMAIL)
    cp.close()
    rewrite(db_path, "UPDATE log SET at = 1e30 WHERE event = 'approved'")
    code, lines = told(db_path, capsys)
    assert code == 0
    assert "  Yes: by owner, at a time that cannot be read" in lines and f"  Started: {AT}" in lines


def test_a_log_entry_edited_into_something_else_does_not_stop_the_rest(cp, db_path, capsys):
    yes_and_run(cp, "send_email", EMAIL)
    cp.close()
    connection = sqlite3.connect(db_path)
    connection.execute("UPDATE log SET detail = 'not json' WHERE event IN ('approved', 'held')")
    connection.commit()
    connection.close()
    code, lines = told(db_path, capsys)
    assert code == 1 and lines[2] == "THE LOG HAS BEEN CHANGED: entry 1 was changed."
    assert "  Yes: by None, " + AT in lines and "Receipt 1: send_email" in lines
