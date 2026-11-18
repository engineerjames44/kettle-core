"""The fixed tests: known ways around a checkpoint, tried with no model.

Each test tries one trick and passes only if the World shows nothing risky ran
(or, where a yes was fairly given, that it ran exactly once and exactly as approved).
"""

import functools
import sqlite3
import sys

import pytest

from kettle import FREE, NEEDS_YES, NEVER, Checkpoint, CheckpointError
from kettle.checkpoint.record import ActionRecord
from kettle.checkpoint.rules import RulesError
from kettle.checkpoint.store import Transaction

from conftest import EMAIL, Clock, World, add_tools


# ---- the normal path, so the tricks below are measured against something that works ----


def test_free_tool_runs_straight_away(cp, world):
    decision = cp.request("read_note", {})
    assert decision.status == "ran" and decision.result == "the note"
    assert world.ran == [("read_note", {})]


def test_risky_tool_is_held_and_does_not_run(cp, world):
    decision = cp.request("send_email", dict(EMAIL))
    assert decision.status == "held"
    assert world.ran == []


def test_yes_then_run_carries_out_exactly_what_was_approved_once(cp, world, approved):
    decision = cp.run(approved.request_id)
    assert decision.status == "ran" and decision.result == "sent"
    assert world.ran == [("send_email", EMAIL)]


# ---- trick: run without a yes ----


def test_run_without_a_yes_is_refused(cp, world, held):
    assert cp.run(held.request_id).status == "refused"
    assert world.ran == []


@pytest.mark.parametrize("request_id", ["", "0" * 32, "not-a-request", None, 7, ["x"], b"abc"])
def test_run_with_a_made_up_request_is_refused(cp, world, held, request_id):
    assert cp.run(request_id).status == "refused"
    assert world.ran == []


def test_run_after_a_no_is_refused(cp, world, held):
    assert cp.deny(held.request_id).status == "denied"
    assert cp.run(held.request_id).status == "refused"
    assert cp.approve(held.request_id, held.fingerprint).status == "refused"
    assert cp.run(held.request_id).status == "refused"
    assert world.ran == []


def test_a_yes_can_be_withdrawn_before_it_is_used(cp, world, approved):
    assert cp.deny(approved.request_id).status == "denied"
    assert cp.run(approved.request_id).status == "refused"
    assert world.ran == []


def test_the_gate_given_to_an_agent_offers_asking_and_nothing_else(cp):
    gate = cp.gate
    public = [name for name in dir(gate) if not name.startswith("_")]
    assert sorted(public) == ["request", "tool_names"]


def test_the_caller_of_a_gate_cannot_say_who_is_asking(cp, world):
    with pytest.raises(TypeError):
        cp.gate.request("send_email", dict(EMAIL), "the owner")
    with pytest.raises(TypeError):
        cp.gate.request("send_email", dict(EMAIL), actor="the owner")
    assert cp.pending() == []
    # Who is asking is fixed by the app when it makes the gate.
    held = cp.gate_for("research agent").request("send_email", dict(EMAIL))
    assert ActionRecord.from_canonical(cp._store.read("SELECT record FROM requests")[0]["record"]).actor == "research agent"
    assert 'Asked through (set by the app): "research agent"' in held.preview.splitlines()
    assert "Asked through" not in cp.gate.request("send_email", dict(EMAIL)).preview
    for bad in ("", None, 7):
        with pytest.raises(CheckpointError):
            cp.gate_for(bad)
    assert world.ran == []


# ---- trick: reuse a yes ----


def test_a_yes_cannot_be_used_twice(cp, world, approved):
    assert cp.run(approved.request_id).status == "ran"
    again = cp.run(approved.request_id)
    assert again.status == "refused"
    assert len(world.ran) == 1


def test_a_used_request_cannot_be_approved_again(cp, world, approved):
    assert cp.run(approved.request_id).status == "ran"
    assert cp.approve(approved.request_id, approved.fingerprint).status == "refused"
    assert cp.run(approved.request_id).status == "refused"
    assert len(world.ran) == 1


def test_a_yes_for_one_request_does_not_cover_an_identical_second_request(cp, world, approved):
    second = cp.request("send_email", dict(EMAIL))
    assert second.status == "held"
    assert second.fingerprint == approved.fingerprint
    assert second.request_id != approved.request_id
    assert cp.run(second.request_id).status == "refused"
    assert world.ran == []
    assert cp.run(approved.request_id).status == "ran"
    assert cp.run(second.request_id).status == "refused"
    assert len(world.ran) == 1


# ---- trick: change the action after the yes ----


def test_changing_the_callers_inputs_after_asking_changes_nothing(cp, world):
    inputs = {"to": "sam@example.com", "body": "See you at 3.", "extra": None}
    cp.tool("send_email", lambda to, body, extra: world.send_email(to, body), level=NEEDS_YES, replace=True)
    held = cp.request("send_email", inputs)
    inputs["to"] = "thief@example.net"
    inputs["body"] = "changed"
    cp.approve(held.request_id, held.fingerprint)
    assert cp.run(held.request_id).status == "ran"
    assert world.ran == [("send_email", EMAIL)]


def test_a_changed_request_is_a_new_request_and_the_old_yes_does_not_cover_it(cp, world, approved):
    changed = cp.request("send_email", {"to": "thief@example.net", "body": EMAIL["body"]})
    assert changed.status == "held"
    assert changed.fingerprint != approved.fingerprint
    assert cp.approve(changed.request_id, approved.fingerprint).status == "refused"
    assert cp.run(changed.request_id).status == "refused"
    assert world.ran == []


def _rewrite(db_path, request_id, **columns):
    connection = sqlite3.connect(db_path)
    for column, value in columns.items():
        connection.execute(f"UPDATE requests SET {column} = ? WHERE id = ?", (value, request_id))
    connection.commit()
    connection.close()


THIEF = ActionRecord.make("send_email", {"to": "thief@example.net", "body": "See you at 3."})


def test_swapping_the_stored_record_after_the_yes_cancels_it(cp, world, approved, db_path):
    _rewrite(db_path, approved.request_id, record=THIEF.canonical)
    assert cp.run(approved.request_id).status == "refused"
    assert cp.status(approved.request_id)["state"] == "cancelled"
    assert world.ran == []


def test_swapping_only_the_stored_record_before_the_yes_cancels_the_request(cp, world, held, db_path):
    _rewrite(db_path, held.request_id, record=THIEF.canonical)
    # Even a yes that names the swapped-in action is refused: the request no longer matches itself.
    assert cp.approve(held.request_id, THIEF.fingerprint).status == "refused"
    assert cp.status(held.request_id)["state"] == "cancelled"
    assert cp.run(held.request_id).status == "refused"
    assert world.ran == []


def test_swapping_the_stored_record_and_its_fingerprint_after_the_yes_cancels_it(cp, world, approved, db_path):
    _rewrite(db_path, approved.request_id, record=THIEF.canonical, fingerprint=THIEF.fingerprint)
    assert cp.run(approved.request_id).status == "refused"
    assert cp.status(approved.request_id)["state"] == "cancelled"
    assert world.ran == []


def test_swapping_the_stored_record_before_the_yes_means_the_yes_does_not_land(cp, world, held, db_path):
    _rewrite(db_path, held.request_id, record=THIEF.canonical, fingerprint=THIEF.fingerprint)
    # The human was shown the original, so the yes names the original fingerprint.
    assert cp.approve(held.request_id, held.fingerprint).status == "refused"
    assert cp.run(held.request_id).status == "refused"
    assert world.ran == []


def test_a_stored_record_that_is_not_in_exact_form_is_cancelled(cp, world, approved, db_path):
    _rewrite(db_path, approved.request_id, record=approved_text_with_a_second_to(EMAIL))
    assert cp.run(approved.request_id).status == "refused"
    assert world.ran == []


def approved_text_with_a_second_to(email):
    """The same record text with a duplicate "to" key added, which a loose reader would accept."""
    text = ActionRecord.make("send_email", dict(email)).canonical
    return text.replace('"inputs":{', '"inputs":{"to":"thief@example.net",', 1)


@pytest.mark.parametrize("wrong", ["", "0" * 64, None, 5, "é" * 64])
def test_a_yes_that_names_the_wrong_fingerprint_is_refused(cp, world, held, wrong):
    assert cp.approve(held.request_id, wrong).status == "refused"
    assert cp.run(held.request_id).status == "refused"
    assert world.ran == []


def test_a_yes_that_names_another_requests_fingerprint_is_refused(cp, world, held):
    other = cp.request("pay", {"to": "acme", "amount": 5})
    assert cp.approve(held.request_id, other.fingerprint).status == "refused"
    assert cp.approve(other.request_id, held.fingerprint).status == "refused"
    assert world.ran == []


# ---- trick: use a yes that has expired ----


def test_a_request_nobody_answered_in_time_cannot_be_approved(cp, world, clock, held):
    clock.forward(601)
    assert cp.approve(held.request_id, held.fingerprint).status == "refused"
    assert cp.run(held.request_id).status == "refused"
    assert cp.status(held.request_id)["state"] == "expired"
    assert world.ran == []


def test_a_yes_given_in_time_but_used_too_late_is_refused(cp, world, clock, approved):
    clock.forward(601)
    assert cp.run(approved.request_id).status == "refused"
    assert world.ran == []


def test_the_exact_moment_of_expiry_counts_as_expired(cp, world, clock, approved):
    clock.forward(600)
    assert cp.run(approved.request_id).status == "refused"
    assert world.ran == []


def test_one_second_before_expiry_still_works(cp, world, clock, approved):
    clock.forward(599)
    assert cp.run(approved.request_id).status == "ran"
    assert len(world.ran) == 1


def test_turning_the_clock_back_does_not_revive_an_expired_yes(cp, world, clock, approved):
    clock.forward(601)
    assert cp.run(approved.request_id).status == "refused"
    clock.forward(-601)
    assert cp.run(approved.request_id).status == "refused"
    assert cp.approve(approved.request_id, approved.fingerprint).status == "refused"
    assert world.ran == []


# ---- trick: ask for a tool that is not listed, or is never allowed ----


@pytest.mark.parametrize(
    "name",
    ["delete_everything", "send_email ", " send_email", "Send_Email", "send_email\x00", "send-email", "", None, 3, ["send_email"], ("send_email",)],
)
def test_an_unlisted_tool_is_refused(cp, world, name):
    decision = cp.request(name, dict(EMAIL))
    assert decision.status == "refused"
    assert world.ran == []


def test_a_never_tool_is_refused_and_leaves_nothing_to_approve(cp, world):
    decision = cp.request("wipe_account", {})
    assert decision.status == "refused" and decision.request_id is None
    assert cp.pending() == []
    assert world.ran == []


def test_a_tool_taken_off_the_list_after_the_yes_does_not_run(cp, world, approved):
    cp.remove_tool("send_email")
    assert cp.run(approved.request_id).status == "refused"
    assert world.ran == []


def test_a_tool_made_never_after_the_yes_does_not_run(cp, world, approved):
    cp.tool("send_email", world.send_email, level=NEVER, replace=True)
    assert cp.run(approved.request_id).status == "refused"
    assert world.ran == []


def _not_to_example_com(inputs):
    return NEVER if inputs["to"].endswith("@example.com") else NEEDS_YES


def test_a_refusal_says_never_only_when_no_inputs_are_allowed(cp, world):
    """A tool whose level depends on its inputs is allowed with other inputs, so its refusal does not call it never allowed."""
    never = cp.request("wipe_account", {})
    assert never.reason == "Refused: wipe_account is never allowed. Nothing was run."
    cp.tool("send_email", world.send_email, level=_not_to_example_com, replace=True)
    these = cp.request("send_email", dict(EMAIL))
    assert these.status == "refused" and these.request_id is None
    assert these.reason == "Refused: send_email is not allowed with these inputs. Nothing was run."
    assert cp.request("send_email", {"to": "sam@example.org", "body": "See you at 3."}).status == "held"
    assert [entry["detail"]["reason"] for entry in cp.log() if entry["event"] == "refused"] == [
        "wipe_account is never allowed",
        "send_email is not allowed with these inputs",
    ]
    assert world.ran == []


def test_a_refusal_after_the_yes_says_the_same(cp, world, approved):
    cp.tool("send_email", world.send_email, level=_not_to_example_com, replace=True)
    late = cp.run(approved.request_id)
    assert late.status == "refused"
    assert late.reason == "Refused and cancelled: send_email is not allowed with these inputs. Nothing was run."
    assert world.ran == []


def test_a_tool_made_never_after_the_yes_is_called_never_allowed(cp, world, approved):
    cp.tool("send_email", world.send_email, level=NEVER, replace=True)
    assert cp.run(approved.request_id).reason == "Refused and cancelled: send_email is never allowed. Nothing was run."
    assert world.ran == []


# ---- trick: inputs that cannot be pinned down ----


class Sneaky(dict):
    """A dict that shows different contents each time it is read."""

    def items(self):
        return [("to", "thief@example.net"), ("body", "x")]


BAD_INPUTS = [
    None,
    "to=sam@example.com",
    ["sam@example.com", "hi"],
    {"to": "sam@example.com", "body": float("nan")},
    {"to": "sam@example.com", "body": float("inf")},
    {"to": "sam@example.com", "body": b"bytes"},
    {"to": "sam@example.com", "body": {"a", "set"}},
    {"to": "sam@example.com", "body": ("a", "tuple")},
    {"to": "sam@example.com", "body": object()},
    {"to": "sam@example.com", 1: "body"},
    {"to": "sam@example.com", "body": "\ud800"},
    {"to": "sam@example.com", "body": "x" * 1_100_000},
    {"to": "sam@example.com"},
    {"to": "sam@example.com", "body": "hi", "bcc": "thief@example.net"},
    Sneaky(to="sam@example.com", body="hi"),
]


@pytest.mark.parametrize("inputs", BAD_INPUTS, ids=lambda value: type(value).__name__)
def test_inputs_that_cannot_be_made_into_an_exact_record_are_refused(cp, world, inputs):
    decision = cp.request("send_email", inputs)
    assert decision.status == "refused"
    assert cp.pending() == []
    assert world.ran == []


def test_inputs_nested_too_deep_or_in_a_loop_are_refused(cp, world):
    deep = "x"
    for _ in range(40):
        deep = [deep]
    loop = {"to": "sam@example.com"}
    loop["body"] = loop
    for inputs in ({"to": "sam@example.com", "body": deep}, loop):
        assert cp.request("send_email", inputs).status == "refused"
    assert world.ran == []


# ---- trick: the checkpoint is down ----


def test_a_checkpoint_that_cannot_open_its_store_says_so_at_setup(tmp_path):
    with pytest.raises(CheckpointError):
        Checkpoint(str(tmp_path / "no" / "such" / "folder" / "kettle.db"))


def test_with_the_store_gone_nothing_runs_not_even_free_tools(cp, world, approved):
    cp._store._connection.close()
    assert cp.request("read_note", {}).status == "refused"
    assert cp.request("send_email", dict(EMAIL)).status == "refused"
    assert cp.run(approved.request_id).status == "refused"
    assert cp.approve(approved.request_id, approved.fingerprint).status == "refused"
    assert world.ran == []


def test_if_the_log_cannot_be_written_nothing_runs(cp, world, approved, monkeypatch):
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("disk is full")

    monkeypatch.setattr(Transaction, "log", broken)
    assert cp.request("read_note", {}).status == "refused"
    assert cp.request("send_email", dict(EMAIL)).status == "refused"
    assert cp.run(approved.request_id).status == "refused"
    assert world.ran == []
    monkeypatch.undo()
    # The failed attempts left nothing half-done: no new request, and the yes is still unused.
    assert cp.pending() == []
    assert cp.status(approved.request_id)["state"] == "approved"


def test_a_store_that_has_become_read_only_runs_nothing(cp, world, approved, db_path):
    import os

    if os.geteuid() == 0:
        pytest.skip("root can write a read-only file")
    os.chmod(db_path, 0o444)
    os.chmod(os.path.dirname(db_path), 0o555)
    try:
        other_world = World()
        try:
            second = Checkpoint(db_path, clock=cp._clock)
        except CheckpointError:
            return
        add_tools(second, other_world)
        assert second.request("read_note", {}).status == "refused"
        assert second.run(approved.request_id).status == "refused"
        assert other_world.ran == []
        second.close()
    finally:
        os.chmod(os.path.dirname(db_path), 0o755)
        os.chmod(db_path, 0o644)


def test_a_broken_clock_runs_nothing(db_path, world):
    def broken():
        raise OSError("no clock")

    checkpoint = Checkpoint(db_path, clock=broken)
    add_tools(checkpoint, world)
    assert checkpoint.request("read_note", {}).status == "refused"
    assert checkpoint.request("send_email", dict(EMAIL)).status == "refused"
    assert world.ran == []


def test_a_rule_that_fails_or_answers_nonsense_runs_nothing(cp, world):
    def fails(inputs):
        raise RuntimeError("rule broke")

    for rule in (fails, lambda inputs: "yes", lambda inputs: None, lambda inputs: True, lambda inputs: ["free"]):
        cp.tool("send_email", world.send_email, level=rule, replace=True)
        assert cp.request("send_email", dict(EMAIL)).status == "refused"
    assert world.ran == []


# ---- a tool that fails part-way must not be sent twice ----


def test_a_tool_that_fails_is_marked_unknown_and_its_yes_is_spent(cp, world):
    def flaky(to, body):
        world.ran.append(("send_email", {"to": to, "body": body}))
        raise ConnectionError("the line dropped after sending")

    cp.tool("send_email", flaky, level=NEEDS_YES, replace=True)
    held = cp.request("send_email", dict(EMAIL))
    cp.approve(held.request_id, held.fingerprint)
    assert cp.run(held.request_id).status == "unknown"
    assert cp.run(held.request_id).status == "refused"
    assert cp.approve(held.request_id, held.fingerprint).status == "refused"
    assert len(world.ran) == 1
    assert [item["request_id"] for item in cp.needs_checking()] == [held.request_id]


def test_if_the_result_cannot_be_recorded_the_action_still_never_runs_twice(cp, world, approved, monkeypatch):
    real_log = Transaction.log

    def fails_on_ran(self, at, event, *args, **kwargs):
        if event == "ran":
            raise sqlite3.OperationalError("disk is full")
        return real_log(self, at, event, *args, **kwargs)

    monkeypatch.setattr(Transaction, "log", fails_on_ran)
    decision = cp.run(approved.request_id)
    assert decision.status == "ran" and "could not record" in decision.reason
    monkeypatch.undo()
    assert cp.run(approved.request_id).status == "refused"
    assert len(world.ran) == 1
    assert [item["request_id"] for item in cp.needs_checking(older_than=0)] == [approved.request_id]


def test_an_interrupt_during_a_tool_is_passed_on_and_the_yes_is_spent(cp, world):
    def interrupted(to, body):
        raise KeyboardInterrupt

    cp.tool("send_email", interrupted, level=NEEDS_YES, replace=True)
    held = cp.request("send_email", dict(EMAIL))
    cp.approve(held.request_id, held.fingerprint)
    with pytest.raises(KeyboardInterrupt):
        cp.run(held.request_id)
    assert cp.status(held.request_id)["state"] == "unknown"
    assert cp.run(held.request_id).status == "refused"


# ---- rules that read the details ----


def test_a_rule_can_depend_on_the_inputs(cp, world):
    def rule(inputs):
        if inputs["to"] == "me@example.com":
            return FREE
        if inputs["to"].endswith("@blocked.example"):
            return NEVER
        return NEEDS_YES

    cp.tool("send_email", world.send_email, level=rule, replace=True)
    assert cp.request("send_email", {"to": "me@example.com", "body": "note to self"}).status == "ran"
    assert cp.request("send_email", {"to": "x@blocked.example", "body": "hi"}).status == "refused"
    assert cp.request("send_email", {"to": "sam@example.com", "body": "hi"}).status == "held"
    assert world.ran == [("send_email", {"to": "me@example.com", "body": "note to self"})]


def test_a_rule_cannot_change_the_inputs_it_is_shown(cp, world):
    def meddling(inputs):
        inputs["to"] = "thief@example.net"
        return NEEDS_YES

    cp.tool("send_email", world.send_email, level=meddling, replace=True)
    held = cp.request("send_email", dict(EMAIL))
    cp.approve(held.request_id, held.fingerprint)
    cp.run(held.request_id)
    assert world.ran == [("send_email", EMAIL)]


# ---- what was held survives a restart ----


def test_a_held_request_and_its_yes_survive_a_restart(db_path, world, clock):
    first = Checkpoint(db_path, clock=clock)
    add_tools(first, World())
    held = first.request("send_email", dict(EMAIL))
    first.approve(held.request_id, held.fingerprint)
    first.close()

    second = Checkpoint(db_path, clock=clock)
    add_tools(second, world)
    assert second.run(held.request_id).status == "ran"
    assert second.run(held.request_id).status == "refused"
    assert world.ran == [("send_email", EMAIL)]


# ---- found by an independent review of the checkpoint, each one fixed and pinned here ----


def test_a_yes_that_runs_out_while_the_checkpoint_waits_for_its_store_is_not_used(cp, world, clock, approved, monkeypatch):
    real_write = cp._store.write

    def slow_write():
        clock.forward(601)  # the wait for the store outlasts the yes
        return real_write()

    monkeypatch.setattr(cp._store, "write", slow_write)
    decision = cp.run(approved.request_id)
    assert decision.status == "refused" and "expired" in decision.reason
    assert world.ran == []


def test_a_request_that_runs_out_while_the_checkpoint_waits_for_its_store_cannot_be_approved(cp, world, clock, held, monkeypatch):
    real_write = cp._store.write

    def slow_write():
        clock.forward(601)
        return real_write()

    monkeypatch.setattr(cp._store, "write", slow_write)
    assert cp.approve(held.request_id, held.fingerprint).status == "refused"
    monkeypatch.undo()
    assert cp.run(held.request_id).status == "refused"
    assert world.ran == []


def test_the_time_a_request_is_held_for_starts_when_it_is_written_down(cp, clock, monkeypatch):
    real_write = cp._store.write

    def slow_write():
        clock.forward(5)
        return real_write()

    monkeypatch.setattr(cp._store, "write", slow_write)
    held = cp.request("send_email", dict(EMAIL))
    assert held.expires_at == clock.now + 600


class _Unprintable(Exception):
    def __str__(self):
        raise RuntimeError("this error cannot even describe itself")


@pytest.mark.parametrize("error", [_Unprintable(), ValueError("half a character: \ud83d"), ValueError("x" * 5000)], ids=["unprintable", "not-valid-text", "very-long"])
def test_a_tool_whose_error_cannot_be_written_down_is_still_marked_unknown(cp, world, error):
    def flaky(to, body):
        world.ran.append(("send_email", {"to": to, "body": body}))
        raise error

    cp.tool("send_email", flaky, level=NEEDS_YES, replace=True)
    held = cp.request("send_email", dict(EMAIL))
    cp.approve(held.request_id, held.fingerprint)
    assert cp.run(held.request_id).status == "unknown"
    assert cp.status(held.request_id)["state"] == "unknown"
    assert cp.log()[-1]["event"] == "unknown"
    assert len(cp.log()[-1]["detail"]["note"]) <= 503
    assert cp.run(held.request_id).status == "refused"
    assert len(world.ran) == 1
    assert cp.verify_log()[0]


def test_a_free_tool_whose_error_cannot_be_written_down_does_not_break_the_caller(cp, world):
    def flaky():
        raise _Unprintable()

    cp.tool("read_note", flaky, level=FREE, replace=True)
    assert cp.request("read_note", {}).status == "unknown"
    assert [entry["event"] for entry in cp.log()] == ["started", "unknown"]


def test_a_free_tool_that_fails_is_in_the_log_but_not_in_the_list_of_requests_to_check(cp, world):
    def flaky():
        raise ConnectionError("dropped")

    cp.tool("read_note", flaky, level=FREE, replace=True)
    assert cp.request("read_note", {}).status == "unknown"
    assert cp.log()[-1]["event"] == "unknown" and cp.log()[-1]["tool"] == "read_note"
    assert cp.needs_checking(older_than=0) == []  # it lists held requests only; see its docstring


def test_a_refusal_is_logged_even_when_the_tool_name_is_not_valid_text(cp, world):
    assert cp.request("send_email\ud83d", dict(EMAIL)).status == "refused"
    assert cp.request("x" * 5000, {}).status == "refused"
    entries = cp.log()
    assert [entry["event"] for entry in entries] == ["refused", "refused"]
    assert entries[0]["tool"] == "send_email\\ud83d"
    assert len(entries[1]["tool"]) == 203
    assert cp.verify_log()[0]


def test_refusing_a_request_never_runs_code_on_what_was_asked(cp, world):
    class Loud:
        called = False

        def __repr__(self):
            Loud.called = True
            raise RuntimeError("repr ran")

        __str__ = __repr__

    assert cp.request(Loud(), {}).status == "refused"
    assert cp.request("send_email", Loud()).status == "refused"
    assert cp.request("send_email", {"to": Loud(), "body": "x"}).status == "refused"
    assert cp.approve(Loud(), Loud(), approver=Loud()).status == "refused"
    held = cp.request("send_email", dict(EMAIL))
    assert cp.approve(held.request_id, held.fingerprint, approver=Loud()).status == "approved"
    assert cp.log()[-1]["detail"] == {"by": "<Loud>"}
    assert Loud.called is False
    assert world.ran == []


def test_when_the_checkpoint_itself_fails_on_a_request_that_is_logged(cp, world, monkeypatch):
    def broken(*args, **kwargs):
        raise NameError("something inside the checkpoint went wrong")

    monkeypatch.setattr(cp._rules, "check_fits", broken)
    decision = cp.request("send_email", dict(EMAIL))
    assert decision.status == "refused" and "not working" in decision.reason
    assert [(entry["event"], entry["tool"]) for entry in cp.log()] == [("refused", "send_email")]
    assert "NameError" in cp.log()[0]["detail"]["reason"]
    assert world.ran == []


@pytest.mark.parametrize("function", [max, int, dict], ids=["max", "int", "dict"])
def test_a_function_whose_inputs_cannot_be_read_is_refused_at_setup(cp, function):
    # Otherwise it would be held, approved, and only then found not to fit.
    with pytest.raises(RulesError, match="cannot be read"):
        cp.tool("odd", function, level=NEEDS_YES)
    assert "odd" not in cp.tool_names()


def test_inputs_that_do_not_fit_a_built_in_function_are_refused_before_any_yes(cp):
    cp.tool("length", len, level=NEEDS_YES)
    assert cp.request("length", {"obj": "abc"}).status == "refused"  # len takes no named inputs
    assert cp.pending() == []


@pytest.mark.skipif(sys.version_info < (3, 14), reason="type hints are only read late from Python 3.14")
def test_a_type_hint_that_names_something_not_imported_does_not_stop_the_checkpoint(cp, world):
    namespace = {"world": world}
    exec("def send(to: NotImportedAtRunTime, body: str):\n    return world.send_email(to, body)\n", namespace)
    cp.tool("send_email", namespace["send"], level=NEEDS_YES, replace=True)
    held = cp.request("send_email", dict(EMAIL))
    assert held.status == "held"
    assert cp.request("send_email", {"to": "a"}).status == "refused"  # the inputs are still checked
    cp.approve(held.request_id, held.fingerprint)
    assert cp.run(held.request_id).status == "ran"
    assert world.ran == [("send_email", EMAIL)]


def test_an_input_the_app_has_already_fixed_cannot_be_given_again(cp, world):
    cp.tool("email_the_boss", functools.partial(world.send_email, to="boss@example.com"), level=FREE)
    assert cp.request("email_the_boss", {"to": "thief@example.net", "body": "hi"}).status == "refused"
    assert world.ran == []
    assert cp.request("email_the_boss", {"body": "hi"}).status == "ran"
    assert world.ran == [("send_email", {"to": "boss@example.com", "body": "hi"})]


def test_an_input_fixed_by_position_cannot_be_given_again_by_name(cp, world):
    def send(to, body, **extra):
        return world.send_email(to, body)

    cp.tool("email_the_boss", functools.partial(send, "boss@example.com"), level=NEEDS_YES)
    assert cp.request("email_the_boss", {"to": "thief@example.net", "body": "hi"}).status == "refused"
    assert cp.request("email_the_boss", {"body": "hi"}).status == "held"
    assert world.ran == []


def test_an_input_named_like_the_tools_own_object_is_refused_before_any_yes(cp, world):
    class Mailer:
        def send(self, **fields):
            return world.send_email(**fields)

    cp.tool("send_email", Mailer().send, level=NEEDS_YES, replace=True)
    assert cp.request("send_email", {"self": "x", "to": "a", "body": "b"}).status == "refused"
    assert cp.request("send_email", dict(EMAIL)).status == "held"
    assert cp.request("read_note", {"self": "x"}).status == "refused"
    assert world.ran == []


def test_known_limit_the_gate_is_not_a_wall_inside_one_process(cp):
    # Python code that holds the gate can walk back to the checkpoint. The gate keeps
    # approve and run out of an agent loop by accident. It does not stop code that goes looking.
    assert cp.gate._request.__self__ is cp


def test_a_refusal_that_quotes_a_huge_input_name_is_logged_in_short(cp, world):
    assert cp.request("send_email", {"to": "a", "body": "b", "x" * 100_000: 1}).status == "refused"
    entry = cp.log()[-1]
    assert entry["event"] == "refused" and len(entry["detail"]["reason"]) <= 503
