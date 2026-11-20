"""A tool changed on one thread while another thread asks.

An app may call tool(..., replace=True) from another thread, for example when the
owner presses "Approve and trust" and the app makes its email rule again with a
longer list. Each step of a request keeps the one entry it found, so it sees the
old rule or the new one, never half of each.
"""

import threading

import pytest

from kettle import FREE, NEEDS_YES, rules
from kettle.checkpoint.checkpoint import Checkpoint
from kettle.checkpoint.rules import RulesError


def send(to, body):
    return "sent"


class Says(rules.Rule):
    kind = "says"

    def __init__(self, reason):
        super().__init__({"reason": reason})
        object.__setattr__(self, "_reason", reason)

    def _look(self, inputs):
        return [(NEEDS_YES, self._reason)]


def test_two_threads_listing_the_same_new_name_cannot_both_succeed():
    checkpoint = Checkpoint(":memory:")
    met = threading.Barrier(2, timeout=0.5)

    class Slow(dict):
        def __contains__(self, name):
            listed = dict.__contains__(self, name)  # looked at first, then wait for the other thread
            try:
                met.wait()  # both threads meet here only if nothing keeps the second out while the first checks
            except threading.BrokenBarrierError:
                pass
            return listed

    checkpoint._rules._tools = Slow()
    outcomes = []

    def add():
        try:
            checkpoint.tool("send_email", send, level=NEEDS_YES)
            outcomes.append("listed")
        except RulesError as error:
            outcomes.append(str(error))

    threads = [threading.Thread(target=add) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["listed", "send_email is already listed"]


def test_a_tool_removed_while_the_rules_are_fingerprinted_does_not_break_a_request():
    checkpoint = Checkpoint(":memory:")

    class Removes:
        """A level that removes another tool when its name is read for the fingerprint."""

        def __call__(self, inputs):
            return FREE

        def __getattr__(self, name):
            if name != "__qualname__":
                raise AttributeError(name)
            checkpoint.remove_tool("b_other")
            return "removes"

    checkpoint.tool("a_send", send, level=Removes())
    checkpoint.tool("b_other", send, level=FREE)
    done = checkpoint.request("a_send", {"to": "sam@example.com", "body": "hi"})
    assert done.status == "ran", done.reason
    assert checkpoint.tool_names() == ["a_send"]


def test_a_rule_swapped_again_and_again_while_requests_are_made_is_seen_whole():
    checkpoint = Checkpoint(":memory:")
    old, new = Says("the old rule asks"), Says("the new rule asks")
    checkpoint.tool("send_email", send, level=old, describe=old.why)
    stop = threading.Event()

    def swap():
        flip = False
        while not stop.is_set():
            level = new if flip else old
            checkpoint.tool("send_email", send, level=level, describe=level.why, replace=True)
            flip = not flip

    swapper = threading.Thread(target=swap)
    swapper.start()
    try:
        decisions = [checkpoint.request("send_email", {"to": "sam@example.com", "body": f"note {n}"}) for n in range(300)]
    finally:
        stop.set()
        swapper.join()
    held = {entry["request_id"]: entry["detail"]["reasons"] for entry in checkpoint._store.log_entries() if entry["event"] == "held"}
    assert all(decision.status in ("held", "refused") for decision in decisions)
    for decision in decisions:
        if decision.status == "refused":  # the rule changed while that request was being made: asked again
            assert decision.reason == "Refused: what the rule sees changed while the owner was being asked. Ask again. Nothing was run."
            continue
        kept = held[decision.request_id]
        assert kept in (["the old rule asks"], ["the new rule asks"])
        assert "Asks because: " + kept[0] in decision.preview.replace("\\u{0020}\n", " ")


def test_approve_and_trust_a_held_email_runs_under_the_rule_made_again_with_the_address_listed():
    checkpoint = Checkpoint(":memory:")
    ran = []

    def send_email(to, body):
        ran.append(to)
        return "sent"

    before = rules.email(contacts=["lee@example.com"])
    checkpoint.tool("send_email", send_email, level=before, describe=before.why, watch=["to"])
    held = checkpoint.request("send_email", {"to": "sam@example.com", "body": "hi"})
    assert held.status == "held"
    assert checkpoint.approve(held.request_id, held.fingerprint).status == "approved"
    after = rules.email(contacts=["lee@example.com", checkpoint.inputs(held.request_id)["to"]])
    checkpoint.tool("send_email", send_email, level=after, describe=after.why, watch=["to"], replace=True)
    assert checkpoint.run(held.request_id).status == "ran" and ran == ["sam@example.com"]
    assert checkpoint.request("send_email", {"to": "sam@example.com", "body": "again"}).status == "ran"


def test_a_rule_swapped_in_with_a_new_reason_cancels_a_yes_given_under_the_old_one():
    checkpoint = Checkpoint(":memory:")
    old, new = Says("the old rule asks"), Says("the new rule asks")
    checkpoint.tool("send_email", send, level=old, describe=old.why)
    held = checkpoint.request("send_email", {"to": "sam@example.com", "body": "hi"})
    checkpoint.approve(held.request_id, held.fingerprint)
    checkpoint.tool("send_email", send, level=new, describe=new.why, replace=True)
    done = checkpoint.run(held.request_id)
    assert done.status == "refused" and "(now: the new rule asks)" in done.reason


@pytest.mark.parametrize("replace", [False, True])
def test_listing_a_name_again_needs_replace(replace):
    checkpoint = Checkpoint(":memory:")
    checkpoint.tool("send_email", send, level=NEEDS_YES)
    if replace:
        checkpoint.tool("send_email", send, level=FREE, replace=True)
        assert checkpoint.request("send_email", {"to": "a@example.com", "body": "x"}).status == "ran"
    else:
        with pytest.raises(RulesError, match="send_email is already listed"):
            checkpoint.tool("send_email", send, level=FREE)
