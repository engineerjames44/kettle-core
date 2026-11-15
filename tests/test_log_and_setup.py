"""The log of what happened, setup mistakes, and the limits we know about.

The tests named test_known_limit_* pass when the limit is still there. They are
here so the README cannot quietly claim more than the code does.
"""

import sqlite3

import pytest

from kettle import FREE, NEEDS_YES, NEVER, Checkpoint, CheckpointError
from kettle.checkpoint.rules import RulesError

from conftest import EMAIL, World, add_tools


def _events(cp):
    return [(entry["event"], entry["tool"]) for entry in cp.log()]


def _sql(db_path, statement, args=()):
    connection = sqlite3.connect(db_path)
    connection.execute(statement, args)
    connection.commit()
    connection.close()


# ---- the log ----


def test_the_log_says_what_happened_in_order(cp, world, clock):
    cp.request("read_note", {})
    held = cp.request("send_email", dict(EMAIL))
    cp.run(held.request_id)
    cp.approve(held.request_id, held.fingerprint)
    cp.run(held.request_id)
    cp.run(held.request_id)
    cp.request("wipe_account", {})
    cp.request("not_listed", {})
    denied = cp.request("pay", {"to": "acme", "amount": 5})
    cp.deny(denied.request_id)
    late = cp.request("pay", {"to": "acme", "amount": 6})
    clock.forward(601)
    cp.approve(late.request_id, late.fingerprint)
    assert _events(cp) == [
        ("started", "read_note"),
        ("ran", "read_note"),
        ("held", "send_email"),
        ("refused", "send_email"),
        ("approved", "send_email"),
        ("started", "send_email"),
        ("ran", "send_email"),
        ("refused", "send_email"),
        ("refused", "wipe_account"),
        ("refused", "not_listed"),
        ("held", "pay"),
        ("denied", "pay"),
        ("held", "pay"),
        ("expired", "pay"),
    ]
    assert cp.verify_log() == (True, "14 entries, chain intact")


def test_asking_to_run_what_has_no_yes_or_a_used_yes_is_written_down(cp, world):
    held = cp.request("send_email", dict(EMAIL))
    cp.run(held.request_id)
    cp.approve(held.request_id, held.fingerprint)
    cp.run(held.request_id)
    cp.run(held.request_id)
    refused = [entry for entry in cp.log() if entry["event"] == "refused"]
    assert [entry["detail"] for entry in refused] == [
        {"reason": "asked to run before anyone said yes"},
        {"reason": "asked to run a request that is already used"},
    ]
    assert all((entry["request_id"], entry["fingerprint"]) == (held.request_id, held.fingerprint) for entry in refused)
    assert world.ran == [("send_email", EMAIL)] and cp.verify_log()[0]


def test_every_real_run_has_a_started_entry_written_before_it(cp, world):
    seen = []

    def send(to, body):
        seen.append(_events(cp)[-1])
        return "sent"

    def read():
        seen.append(_events(cp)[-1])

    cp.tool("send_email", send, level=NEEDS_YES, replace=True)
    cp.tool("read_note", read, level=FREE, replace=True)
    cp.request("read_note", {})
    held = cp.request("send_email", dict(EMAIL))
    cp.approve(held.request_id, held.fingerprint)
    cp.run(held.request_id)
    assert seen == [("started", "read_note"), ("started", "send_email")]


def test_the_log_shows_the_number_of_real_runs(cp, world, approved):
    for _ in range(5):
        cp.run(approved.request_id)
    ran = [entry for entry in cp.log() if entry["event"] == "ran" and entry["tool"] == "send_email"]
    assert len(ran) == len(world.ran) == 1


def _filled(cp):
    cp.request("read_note", {})
    held = cp.request("send_email", dict(EMAIL))
    cp.approve(held.request_id, held.fingerprint)
    cp.run(held.request_id)
    assert cp.verify_log()[0]


def test_an_edited_log_entry_is_found(cp, db_path):
    _filled(cp)
    _sql(db_path, "UPDATE log SET tool = 'read_note' WHERE seq = 5")
    assert cp.verify_log() == (False, "entry 5 was changed")


def test_an_edited_log_detail_is_found(cp, db_path):
    _filled(cp)
    _sql(db_path, "UPDATE log SET detail = '{}' WHERE seq = 3")
    assert cp.verify_log() == (False, "entry 3 was changed")


def test_a_log_entry_removed_from_the_middle_is_found(cp, db_path):
    _filled(cp)
    _sql(db_path, "DELETE FROM log WHERE seq = 4")
    assert cp.verify_log() == (False, "entry 4 is missing")


def test_log_entries_swapped_around_are_found(cp, db_path):
    _filled(cp)
    _sql(db_path, "UPDATE log SET seq = 99 WHERE seq = 2")
    _sql(db_path, "UPDATE log SET seq = 2 WHERE seq = 3")
    _sql(db_path, "UPDATE log SET seq = 3 WHERE seq = 99")
    assert cp.verify_log()[0] is False


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE log SET detail = x'00ff' WHERE seq = 3",
        "UPDATE log SET at = 9e999 WHERE seq = 3",
        "UPDATE log SET at = 'yesterday' WHERE seq = 3",
        "UPDATE log SET tool = x'00ff' WHERE seq = 3",
        "UPDATE log SET hash = x'00' WHERE seq = 3",
    ],
)
def test_a_log_entry_changed_into_something_the_checkpoint_never_writes_is_found_not_crashed_on(cp, db_path, statement):
    _filled(cp)
    _sql(db_path, statement)
    assert cp.verify_log() == (False, "entry 3 was changed")
    assert len(cp.log()) == 6  # reading the log still works


def test_known_limit_the_last_log_entry_can_be_rewritten_by_whoever_can_write_the_file(cp, db_path):
    from kettle.checkpoint.store import _entry_hash

    _filled(cp)
    row = cp._store.read("SELECT * FROM log WHERE seq = 6")[0]
    before = cp._store.read("SELECT hash FROM log WHERE seq = 5")[0]["hash"]
    forged = _entry_hash(before, 6, row["at"], "refused", row["request_id"], row["tool"], row["fingerprint"], row["detail"])
    _sql(db_path, "UPDATE log SET event = 'refused', hash = ? WHERE seq = 6", (forged,))
    assert cp.verify_log()[0] is True


def test_known_limit_entries_cut_from_the_end_of_the_log_are_not_found(cp, db_path):
    _filled(cp)
    _sql(db_path, "DELETE FROM log WHERE seq >= 5")
    assert cp.verify_log() == (True, "4 entries, chain intact")


def test_known_limit_whoever_can_write_the_store_file_can_forge_a_yes(cp, world, held, db_path):
    # The store file is trusted. This is why it must sit where the agent cannot write.
    _sql(
        db_path,
        "UPDATE requests SET state = 'approved', approved_fingerprint = fingerprint WHERE id = ?",
        (held.request_id,),
    )
    assert cp.run(held.request_id).status == "ran"
    assert len(world.ran) == 1


def test_known_limit_a_tool_function_called_directly_is_not_seen(cp, world):
    # The checkpoint only governs calls that go through it.
    world.send_email("thief@example.net", "direct")
    assert len(world.ran) == 1
    assert cp.log() == []


# ---- setup mistakes are loud, at setup time ----


def test_setup_mistakes_raise(db_path):
    world = World()
    cp = Checkpoint(db_path)
    add_tools(cp, world)
    with pytest.raises(RulesError):
        cp.tool("send_email", world.send_email, level=FREE)  # already listed
    with pytest.raises(RulesError):
        cp.tool("new_tool", world.pay, level="sometimes")
    with pytest.raises(RulesError):
        cp.tool("new_tool", level=NEEDS_YES)  # nothing to run
    with pytest.raises(RulesError):
        cp.tool("new_tool", "not a function", level=FREE)
    with pytest.raises(RulesError):
        cp.tool("", world.pay, level=FREE)
    with pytest.raises(RulesError):
        cp.tool(None, world.pay, level=FREE)
    with pytest.raises(TypeError):
        cp.tool("new_tool", world.pay)  # a level must always be given
    assert cp.tool_names() == ["pay", "read_note", "send_email", "wipe_account"]
    cp.close()


@pytest.mark.parametrize("hold", [0, -1, float("inf"), float("nan"), "600", None, True])
def test_a_hold_time_that_makes_no_sense_is_refused_at_setup(db_path, hold):
    with pytest.raises(CheckpointError):
        Checkpoint(db_path, hold_seconds=hold)


def test_a_store_made_by_another_version_is_refused_at_setup(db_path):
    Checkpoint(db_path).close()
    _sql(db_path, "UPDATE meta SET value = '999' WHERE key = 'schema'")
    with pytest.raises(CheckpointError):
        Checkpoint(db_path)


def test_a_file_that_is_not_a_store_is_refused_at_setup(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("this is not a database " * 100)
    with pytest.raises(CheckpointError):
        Checkpoint(str(path))


def test_the_rules_digest_changes_when_the_rules_do(cp, world):
    before = cp.rules_digest()
    cp.tool("send_email", world.send_email, level=FREE, replace=True)
    assert cp.rules_digest() != before
    cp.tool("send_email", world.send_email, level=NEEDS_YES, replace=True)
    assert cp.rules_digest() == before
    cp.tool("extra", level=NEVER)
    assert cp.rules_digest() != before


def test_the_store_moves_a_request_only_out_of_the_state_it_was_expected_to_be_in(tmp_path):
    from kettle.checkpoint.store import Store

    store = Store(str(tmp_path / "k.db"))
    with store.write() as tx:
        tx.insert_request("one", "f", "{}", 0.0, 10.0)
        assert tx.move("one", ("approved",), "running") is False and tx.get("one")["state"] == "held"
        assert tx.move("one", ("held",), "approved") is True and tx.get("one")["state"] == "approved"
        assert tx.move("one", ("held",), "denied") is False and tx.get("one")["state"] == "approved"
        assert tx.move("missing", ("held", "approved"), "denied") is False
