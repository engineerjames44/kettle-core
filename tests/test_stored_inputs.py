"""Checkpoint.inputs(): the inputs of a request as stored, for the owner's side only."""

import sqlite3

import pytest

from kettle import NEEDS_YES
from kettle.checkpoint.checkpoint import Checkpoint, Gate

SENT = {"to": "sam@example.com", "cc": ["lee@example.com", {"name": "Ann"}], "body": "hi"}


def send(to, cc, body):
    return "sent"


@pytest.fixture
def checkpoint():
    made = Checkpoint(":memory:")
    made.tool("send_email", send, level=NEEDS_YES)
    return made


def test_the_inputs_are_given_as_stored_in_every_state(checkpoint):
    held = checkpoint.request("send_email", SENT)
    assert checkpoint.inputs(held.request_id) == SENT
    checkpoint.approve(held.request_id, held.fingerprint)
    assert checkpoint.inputs(held.request_id) == SENT
    checkpoint.run(held.request_id)
    assert checkpoint.inputs(held.request_id) == SENT


def test_each_call_gives_a_copy_that_cannot_change_what_is_stored(checkpoint):
    held = checkpoint.request("send_email", SENT)
    first = checkpoint.inputs(held.request_id)
    first["to"] = "thief@example.net"
    first["cc"][0] = "thief@example.net"
    first["cc"][1]["name"] = "Thief"
    second = checkpoint.inputs(held.request_id)
    assert second == SENT and second is not first and second["cc"] is not first["cc"]
    checkpoint.approve(held.request_id, held.fingerprint)
    assert checkpoint.run(held.request_id).status == "ran"


@pytest.mark.parametrize("request_id", ["no-such-request", "", None, 7, ["x"]])
def test_no_such_request_gives_none(checkpoint, request_id):
    assert checkpoint.inputs(request_id) is None


def test_a_stored_record_changed_after_it_was_made_gives_none(tmp_path):
    made = Checkpoint(str(tmp_path / "kettle.db"))
    made.tool("send_email", send, level=NEEDS_YES)
    held = made.request("send_email", SENT)
    connection = sqlite3.connect(str(tmp_path / "kettle.db"))
    record = connection.execute("SELECT record FROM requests WHERE id = ?", (held.request_id,)).fetchone()[0]
    connection.execute("UPDATE requests SET record = ? WHERE id = ?", (record.replace("sam@example.com", "thief@example.net"), held.request_id))
    connection.commit()
    connection.close()
    assert made.inputs(held.request_id) is None


def test_the_gate_the_model_is_given_has_no_way_to_read_inputs(checkpoint):
    for gate in (checkpoint.gate, checkpoint.gate_for("agent")):
        assert not hasattr(gate, "inputs") and not hasattr(Gate, "inputs")
        assert [name for name in dir(gate) if not name.startswith("_")] == ["request", "tool_names"]


def test_only_a_request_id_given_as_text_is_looked_up(checkpoint):
    held = checkpoint.request("send_email", SENT)

    class LooksLikeIt:
        def __str__(self):
            return held.request_id

    assert checkpoint.inputs(LooksLikeIt()) is None and checkpoint.inputs(held.request_id) == SENT
