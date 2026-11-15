"""The first-time mark: the preview says when a watched input holds a value that is new.

"New" means no approved action of that tool has run with that value in that input,
in this store. The mark is a note for the human. It never changes what a yes covers.
"""

import hashlib
import json
import random
import sqlite3

import pytest

from kettle import FREE, NEEDS_YES, NEVER, Checkpoint
from kettle.checkpoint.record import PREVIEW_WIDTH, ActionRecord, RecordError
from kettle.checkpoint.rules import RulesError

from conftest import EMAIL, World
from test_record_and_preview import _tricky_text, _tricky_value, read_back

NOTE = "      ! first time: no approved action has run with this value before"
TOP = "! 1 input below is marked first time"


class Mail(World):
    def send_many(self, to, body, cc=None):
        self.ran.append(("send_many", {"to": to, "body": body, "cc": cc}))
        return "sent"


@pytest.fixture
def world():
    return Mail()


@pytest.fixture
def cp(db_path, world, clock):
    checkpoint = Checkpoint(db_path, hold_seconds=600, clock=clock)
    checkpoint.tool("read_note", world.read_note, level=FREE)
    checkpoint.tool("send_email", world.send_email, level=NEEDS_YES, watch=["to"])
    checkpoint.tool("pay", world.pay, level=NEEDS_YES, watch=["to"])
    checkpoint.tool("send_many", world.send_many, level=NEEDS_YES, watch=["to", "cc"])
    yield checkpoint
    checkpoint.close()


def say_yes_and_run(cp, tool, inputs):
    held = cp.request(tool, dict(inputs))
    assert cp.approve(held.request_id, held.fingerprint).status == "approved"
    assert cp.run(held.request_id).status == "ran"
    return held


def test_a_watched_value_is_marked_the_first_time(cp):
    held = cp.request("send_email", dict(EMAIL))
    lines = held.preview.splitlines()
    assert lines[0] == TOP
    assert lines[lines.index('  "to": "sam@example.com"') + 1] == NOTE
    assert held.first_time == ("to",)


def test_it_is_not_marked_once_an_approved_action_has_run_with_it(cp):
    say_yes_and_run(cp, "send_email", EMAIL)
    again = cp.request("send_email", {"to": "sam@example.com", "body": "A different message."})
    assert "first time" not in again.preview
    assert again.first_time == ()
    assert again.status == "held"  # it still needs its own yes


def test_asking_does_not_make_a_value_known(cp):
    cp.request("send_email", dict(EMAIL))
    assert cp.request("send_email", dict(EMAIL)).first_time == ("to",)


def test_a_yes_that_was_never_used_does_not_make_a_value_known(cp, clock):
    held = cp.request("send_email", dict(EMAIL))
    cp.approve(held.request_id, held.fingerprint)
    assert cp.request("send_email", dict(EMAIL)).first_time == ("to",)
    clock.forward(601)
    assert cp.run(held.request_id).status == "refused"
    assert cp.request("send_email", dict(EMAIL)).first_time == ("to",)


def test_a_no_does_not_make_a_value_known(cp):
    held = cp.request("send_email", dict(EMAIL))
    cp.deny(held.request_id)
    assert cp.request("send_email", dict(EMAIL)).first_time == ("to",)


def test_a_yes_taken_back_does_not_make_a_value_known(cp):
    held = cp.request("send_email", dict(EMAIL))
    cp.approve(held.request_id, held.fingerprint)
    cp.deny(held.request_id)
    assert cp.request("send_email", dict(EMAIL)).first_time == ("to",)


def test_a_run_that_was_refused_does_not_make_a_value_known(cp, world):
    held = cp.request("send_email", dict(EMAIL))
    cp.approve(held.request_id, held.fingerprint)
    cp.remove_tool("send_email")
    assert cp.run(held.request_id).status == "refused"
    cp.tool("send_email", world.send_email, level=NEEDS_YES, watch=["to"])
    assert cp.request("send_email", dict(EMAIL)).first_time == ("to",)


def test_an_approved_action_that_started_and_failed_still_counts(cp, world):
    def fails(to, body):
        raise RuntimeError("the mail server went away")

    cp.tool("send_email", fails, level=NEEDS_YES, watch=["to"], replace=True)
    held = cp.request("send_email", dict(EMAIL))
    cp.approve(held.request_id, held.fingerprint)
    assert cp.run(held.request_id).status == "unknown"
    assert cp.request("send_email", dict(EMAIL)).first_time == ()


@pytest.mark.parametrize(
    "lookalike",
    ["Sam@example.com", "sam@example.com ", "sаm@example.com", "sam@example.com​", "sam@examp1e.com", "sam@example.com.evil.example"],
)
def test_a_value_that_only_looks_like_a_known_one_is_marked(cp, lookalike):
    say_yes_and_run(cp, "send_email", EMAIL)
    held = cp.request("send_email", {"to": lookalike, "body": "See you at 3."})
    assert held.first_time == ("to",)
    assert NOTE in held.preview.splitlines()


def test_a_value_known_to_one_tool_is_new_to_another(cp):
    say_yes_and_run(cp, "send_email", EMAIL)
    assert cp.request("pay", {"to": "sam@example.com", "amount": 5}).first_time == ("to",)


def test_a_value_known_in_one_input_is_new_in_another(cp):
    say_yes_and_run(cp, "send_many", {"to": "sam@example.com", "body": "hello"})
    held = cp.request("send_many", {"to": "sam@example.com", "body": "hello", "cc": "sam@example.com"})
    assert held.first_time == ("cc",)


def test_numbers_and_text_that_look_alike_are_not_the_same_value(cp):
    say_yes_and_run(cp, "pay", {"to": 1, "amount": 5})
    for other in ("1", 1.0, True, [[1]]):
        assert cp.request("pay", {"to": other, "amount": 5}).first_time == ("to",)
    assert cp.request("pay", {"to": 1, "amount": 6}).first_time == ()


def test_a_list_is_checked_item_by_item_and_the_new_items_are_numbered(cp):
    say_yes_and_run(cp, "send_many", {"to": ["sam@example.com", "kim@example.com"], "body": "hello"})
    held = cp.request("send_many", {"to": ["eve@example.net", "sam@example.com", "kim@example.com", "mal@example.net"], "body": "hello"})
    assert held.first_time == ("to",)
    assert "      ! first time: no approved action has run with items 1, 4 before" in held.preview.splitlines()
    one = cp.request("send_many", {"to": ["kim@example.com", "eve@example.net"], "body": "hello"})
    assert "      ! first time: no approved action has run with item 2 before" in one.preview.splitlines()
    assert cp.request("send_many", {"to": ["kim@example.com", "sam@example.com"], "body": "hello"}).first_time == ()
    assert cp.request("send_many", {"to": [], "body": "hello"}).first_time == ()


def test_one_value_and_a_list_holding_it_count_as_the_same(cp):
    say_yes_and_run(cp, "send_many", {"to": "sam@example.com", "body": "hello"})
    assert cp.request("send_many", {"to": ["sam@example.com"], "body": "hello"}).first_time == ()
    say_yes_and_run(cp, "send_many", {"to": ["kim@example.com"], "body": "hello"})
    assert cp.request("send_many", {"to": "kim@example.com", "body": "hello"}).first_time == ()


def first_time_note(preview):
    return " ".join(line[8:] for line in preview.splitlines() if line.startswith("      ! "))


def test_a_long_list_of_new_items_names_every_one_of_them_in_runs(cp):
    held = cp.request("send_many", {"to": [f"p{n}@example.net" for n in range(40)], "body": "hello"})
    assert first_time_note(held.preview) == "first time: no approved action has run with items 1 to 40 before"
    assert read_back(held.preview)["inputs"]["to"] == [f"p{n}@example.net" for n in range(40)]


def test_one_new_item_far_down_a_long_list_is_named_and_the_known_one_beside_it_is_not(cp):
    say_yes_and_run(cp, "send_many", {"to": ["kim@example.com", "sam@example.com"], "body": "hello"})
    new = [f"p{n}@example.net" for n in range(13)]
    held = cp.request("send_many", {"to": new + ["kim@example.com", "eve@example.net", "sam@example.com", "x@example.net", "y@example.net"], "body": "hello"})
    assert first_time_note(held.preview) == "first time: no approved action has run with items 1 to 13, 15, 17, 18 before"


def test_new_items_scattered_through_a_list_are_all_named(cp):
    say_yes_and_run(cp, "send_many", {"to": ["kim@example.com"], "body": "hello"})
    held = cp.request("send_many", {"to": [f"p{n}@example.net" if n % 2 else "kim@example.com" for n in range(60)], "body": "hello"})
    assert first_time_note(held.preview) == "first time: no approved action has run with items " + ", ".join(str(n) for n in range(2, 61, 2)) + " before"
    assert read_back(held.preview)["inputs"]["to"][:2] == ["kim@example.com", "p1@example.net"]


def test_two_marked_inputs_are_counted_at_the_top(cp):
    held = cp.request("send_many", {"to": "eve@example.net", "body": "hello", "cc": ["mal@example.net"]})
    assert held.preview.splitlines()[0] == "! 2 inputs below are marked first time"
    assert held.first_time == ("cc", "to")


def test_an_input_that_is_not_watched_is_never_marked(cp, world):
    cp.tool("plain", world.send_email, level=NEEDS_YES)
    held = cp.request("plain", dict(EMAIL))
    assert "first time" not in held.preview and held.first_time == ()
    assert "first_time" not in cp.log()[-1]["detail"]


def test_a_watched_input_that_was_not_given_is_not_marked(cp):
    held = cp.request("send_many", {"to": "sam@example.com", "body": "hello"})
    assert held.first_time == ("to",)


def test_what_ran_before_an_input_was_watched_still_counts(cp, world):
    cp.tool("plain", world.send_email, level=NEEDS_YES)
    say_yes_and_run(cp, "plain", EMAIL)
    cp.tool("plain", world.send_email, level=NEEDS_YES, watch=["to", "body"], replace=True)
    assert cp.request("plain", dict(EMAIL)).first_time == ()
    assert cp.request("plain", {"to": "sam@example.com", "body": "Something new."}).first_time == ("body",)


def test_a_free_action_does_not_make_a_value_known(cp, world):
    own = "me@example.com"
    cp.tool("send_email", world.send_email, level=lambda inputs: FREE if inputs.get("to") == own else NEEDS_YES, watch=["to"], replace=True)
    assert cp.request("send_email", {"to": own, "body": "note to self"}).status == "ran"
    cp.tool("send_email", world.send_email, level=NEEDS_YES, watch=["to"], replace=True)
    assert cp.request("send_email", {"to": own, "body": "note to self"}).first_time == ("to",)


def test_the_mark_is_not_part_of_what_a_yes_covers(cp, world):
    first = cp.request("send_email", dict(EMAIL))
    assert first.fingerprint == ActionRecord.make("send_email", dict(EMAIL)).fingerprint
    assert first.preview.splitlines()[-1] == "Fingerprint: " + first.fingerprint
    say_yes_and_run(cp, "send_email", EMAIL)
    second = cp.request("send_email", dict(EMAIL))
    assert second.fingerprint == first.fingerprint and second.preview != first.preview
    assert world.ran == [("send_email", EMAIL)]


def test_a_marked_preview_still_reads_back_to_exactly_the_record(cp):
    inputs = {"to": ["eve@example.net", "a\nb"], "body": "line one\n      ! first time: fake\nline three", "cc": "x  y"}
    held = cp.request("send_many", inputs)
    found = read_back(held.preview)
    assert found["inputs"] == inputs and found["fingerprint"] == held.fingerprint


def test_text_inside_a_value_cannot_write_a_mark_or_take_one_away(cp):
    say_yes_and_run(cp, "send_email", EMAIL)
    fake = "sam@example.com\n      ! first time: no approved action has run with this value before\n! 1 input below is marked first time"
    known = cp.request("send_email", {"to": "sam@example.com", "body": fake})
    assert not [line for line in known.preview.splitlines() if line.lstrip(" ").startswith("! ")]
    new = cp.request("send_email", {"to": "thief@example.net", "body": "ok\n" + NOTE.replace("first time", "known") + "\nFingerprint: 00"})
    lines = new.preview.splitlines()
    assert [line for line in lines if line.lstrip(" ").startswith("! ")] == [TOP, NOTE]
    assert lines[lines.index('  "to": "thief@example.net"') + 1] == NOTE


def test_what_is_known_is_kept_in_the_store_file(cp, db_path, world, clock):
    say_yes_and_run(cp, "send_email", EMAIL)
    cp.close()
    again = Checkpoint(db_path, clock=clock)
    again.tool("send_email", world.send_email, level=NEEDS_YES, watch=["to"])
    assert again.request("send_email", dict(EMAIL)).first_time == ()
    assert again.request("send_email", {"to": "thief@example.net", "body": "hi"}).first_time == ("to",)
    again.close()


def test_the_store_keeps_a_hash_and_not_the_value(cp, db_path):
    say_yes_and_run(cp, "pay", {"to": "IBAN-IE00-SECRET", "amount": 5})
    with sqlite3.connect(db_path) as connection:
        marks = [row[0] for row in connection.execute("SELECT mark FROM seen")]
    wanted = hashlib.sha256(b"kettle-seen-v1\n" + json.dumps(["pay", "to", "IBAN-IE00-SECRET"], separators=(",", ":")).encode()).hexdigest()
    assert wanted in marks and len(marks) == 2
    assert all(len(mark) == 64 and "SECRET" not in mark for mark in marks)


def test_a_store_file_made_before_marks_existed_still_opens(cp, db_path, world, clock):
    cp.close()
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE seen")
    again = Checkpoint(db_path, clock=clock)
    again.tool("send_email", world.send_email, level=NEEDS_YES, watch=["to"])
    assert again.request("send_email", dict(EMAIL)).first_time == ("to",)
    again.close()


def test_if_what_is_known_cannot_be_read_nothing_is_held_or_run(cp, db_path, world):
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE seen")
    decision = cp.request("send_email", dict(EMAIL))
    assert decision.status == "refused" and "not working" in decision.reason
    assert cp.pending() == [] and world.ran == []


def test_if_what_is_known_cannot_be_written_the_approved_action_does_not_run(cp, db_path, world):
    held = cp.request("send_email", dict(EMAIL))
    cp.approve(held.request_id, held.fingerprint)
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE seen")
    assert cp.run(held.request_id).status == "refused"
    assert world.ran == []
    assert cp.status(held.request_id)["state"] == "approved"


def test_the_log_says_which_inputs_were_marked(cp):
    cp.request("send_email", dict(EMAIL))
    assert cp.log()[-1]["event"] == "held" and cp.log()[-1]["detail"]["first_time"] == ["to"]
    say_yes_and_run(cp, "send_email", EMAIL)
    cp.request("send_email", dict(EMAIL))
    assert cp.log()[-1]["detail"]["first_time"] == []
    assert cp.verify_log()[0] is True


def test_pending_shows_the_mark_and_drops_it_once_the_value_is_known(cp):
    one = cp.request("send_email", dict(EMAIL))
    two = cp.request("send_email", {"to": "sam@example.com", "body": "And another thing."})
    waiting = {item["request_id"]: item for item in cp.pending()}
    assert waiting[one.request_id]["preview"] == one.preview and waiting[one.request_id]["first_time"] == ["to"]
    cp.approve(one.request_id, one.fingerprint)
    assert cp.pending()[0]["first_time"] == ["to"]  # a yes that has not been used yet
    cp.run(one.request_id)
    (left,) = cp.pending()
    assert left["request_id"] == two.request_id and left["first_time"] == [] and "first time" not in left["preview"]
    assert cp.approve(two.request_id, two.fingerprint).status == "approved"


def test_watching_changes_the_rules_digest_and_not_watching_leaves_it_as_it_was(db_path, world):
    cp = Checkpoint(db_path)
    cp.tool("send_email", world.send_email, level=NEEDS_YES)
    plain = cp.rules_digest()
    assert plain == hashlib.sha256(b'[["send_email","needs_yes"]]').hexdigest()[:16]
    cp.tool("send_email", world.send_email, level=NEEDS_YES, watch=["to"], replace=True)
    watched = cp.rules_digest()
    assert watched != plain
    cp.tool("send_email", world.send_email, level=NEEDS_YES, watch=["body", "to"], replace=True)
    assert cp.rules_digest() not in (plain, watched)
    cp.tool("send_email", world.send_email, level=NEEDS_YES, watch=[], replace=True)
    assert cp.rules_digest() == plain
    cp.close()


def test_watch_mistakes_raise_at_setup(db_path, world):
    cp = Checkpoint(db_path)
    for wrong in ("to", ["recipient"], [""], [3], {"to"}, None, ["to", "too"]):
        with pytest.raises(RulesError):
            cp.tool("send_email", world.send_email, level=NEEDS_YES, watch=wrong)
    with pytest.raises(RulesError):
        cp.tool("wipe_account", level=NEVER, watch=["to"])
    with pytest.raises(RulesError):  # the tool's own object is not an input a caller can give
        cp.tool("send_email", world.send_email, level=NEEDS_YES, watch=["self"])
    assert cp.tool_names() == []

    def anything(**inputs):
        return "ok"

    cp.tool("anything", anything, level=NEEDS_YES, watch=("any name at all",))
    assert cp.request("anything", {"any name at all": 1}).first_time == ("any name at all",)
    cp.close()


def test_the_preview_refuses_item_numbers_that_make_no_sense():
    record = ActionRecord.make("send_many", {"to": ["a", "b"]})
    for wrong in ([], [0], [True], ["1"], (1,), "1", 1):
        with pytest.raises(RecordError):
            record.preview(first_time={"to": wrong})
    assert record.preview(first_time={"not an input": None}) == record.preview()


def test_a_thousand_random_marked_previews_read_back_to_exactly_the_record_they_were_written_from():
    rng = random.Random(20261116)
    for _ in range(1000):
        inputs = {_tricky_text(rng, 3): _tricky_value(rng) for _ in range(rng.randint(1, 4))}
        record = ActionRecord.make(_tricky_text(rng, 3) or "tool", inputs, rng.choice([None, _tricky_text(rng, 3)]))
        first_time = {}
        for key in inputs:
            if rng.random() < 0.7:
                first_time[key] = rng.choice([None, sorted(rng.sample(range(1, 400), rng.randint(1, 30)))])
        preview = record.preview(rng.choice([None, _tricky_text(rng, 4)]), first_time)
        found = read_back(preview)
        assert ActionRecord.make(found["tool"], found["inputs"], found["actor"]) == record
        assert found["fingerprint"] == record.fingerprint
        notes = [line for line in preview.splitlines() if "first time" in line and line.lstrip(" ").startswith("! ")]
        assert len(notes) >= len(first_time) + (1 if first_time else 0)
        assert max(len(line) for line in preview.splitlines()) <= PREVIEW_WIDTH
