"""Ask again when what the rule sees changed between the owner being asked and the action running.

The checkpoint keeps the rule's reasons in the log when it holds an action. At
the yes and at the run it asks the rule again: a reason that was not there when
the owner was asked cancels the request, and nothing runs.
"""

import json
import os
import sqlite3

import pytest

from kettle import FREE, NEEDS_YES, NEVER, rules
from kettle.checkpoint.checkpoint import Checkpoint
from kettle.checkpoint.rules import MAX_REASON, Refused, Rules
from kettle.holds import Hold
from kettle.rules import _shown_place

OUTSIDE = "the path is outside the folders you allow"
LINK = "a link on the way leads outside the folders you allow"


def leads(path):
    return "it really leads to " + _shown_place(os.path.realpath(path), os.path.expanduser("~"))

CHANGED = "what the rule sees changed since the owner was asked (now: "


@pytest.fixture
def place(tmp_path):
    """A project with src/ free to write, and two files outside it."""
    (tmp_path / "project" / "src").mkdir(parents=True)
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "a.txt").write_text("a")
    (tmp_path / "elsewhere" / "b.txt").write_text("b")
    (tmp_path / "elsewhere" / "guarded").write_text("g")
    return tmp_path


class World:
    def __init__(self, place, db=":memory:", level=None):
        self.place = place
        self.ran = []
        self.checkpoint = Checkpoint(db)
        self.rule = level or rules.files([str(place / "project" / "src")], does="write", protect=[str(place / "elsewhere" / "guarded")])
        self.checkpoint.tool("write_file", self.write, level=self.rule, describe=getattr(self.rule, "why", None))

    def write(self, path, content):
        self.ran.append(os.path.realpath(path))
        return "done"

    def ask(self, name="README.md"):
        path = self.place / "project" / name
        return self.checkpoint.request("write_file", {"path": str(path), "content": "new"})

    def swap(self, name, target):
        path = self.place / "project" / name
        if path.is_symlink() or path.exists():
            path.unlink()
        os.symlink(target, path)

    def log(self, event):
        return [entry for entry in self.checkpoint._store.log_entries() if entry["event"] == event]


def test_the_reasons_the_owner_was_asked_about_are_kept_in_the_log_sorted(place):
    world = World(place)
    held = world.ask()
    assert held.status == "held"
    assert world.log("held")[0]["detail"]["reasons"] == ["the path is outside the folders you allow"]
    world.swap("link.txt", str(place / "elsewhere" / "a.txt"))
    world.ask("link.txt")
    assert world.log("held")[1]["detail"]["reasons"] == [leads(place / "elsewhere" / "a.txt"), OUTSIDE]  # sorted
    world.swap("src/link.txt", str(place / "elsewhere" / "a.txt"))
    world.ask("src/link.txt")
    assert world.log("held")[2]["detail"]["reasons"] == [LINK, leads(place / "elsewhere" / "a.txt")]


def test_a_free_action_keeps_no_reasons_and_is_never_compared(place):
    world = World(place)
    done = world.ask("src/app.py")
    assert done.status == "ran" and world.log("held") == []


def test_a_free_action_does_not_ask_the_rule_for_reasons(place):
    class Free:
        def __call__(self, inputs):
            return FREE

        def reasons_in(self, inputs):
            raise RuntimeError("should not be asked")

    world = World(place, level=Free())
    assert world.ask().status == "ran"


def test_each_request_is_compared_with_its_own_reasons(place):
    said = {"reasons": ["first"]}

    class Told(rules.Rule):
        kind = "told"

        def _look(self, inputs):
            return [(NEEDS_YES, reason) for reason in said["reasons"]]

    world = World(place, level=Told({}))
    first = world.ask()
    said["reasons"] = ["second"]
    second = world.ask()
    assert world.checkpoint.approve(second.request_id, second.fingerprint).status == "approved"
    assert world.checkpoint.run(second.request_id).status == "ran"
    assert world.checkpoint.approve(first.request_id, first.fingerprint).reason.endswith("(now: second). Ask again.")


def test_with_nothing_changed_the_yes_and_the_run_go_through(place):
    world = World(place)
    held = world.ask()
    assert world.checkpoint.approve(held.request_id, held.fingerprint).status == "approved"
    assert world.checkpoint.run(held.request_id).status == "ran"
    assert world.ran == [os.path.realpath(place / "project" / "README.md")]


def test_a_file_swapped_for_a_link_after_the_yes_is_cancelled_at_the_run(place):
    world = World(place)
    (place / "project" / "README.md").write_text("old")
    held = world.ask()
    world.checkpoint.approve(held.request_id, held.fingerprint)
    world.swap("README.md", str(place / "elsewhere" / "a.txt"))
    done = world.checkpoint.run(held.request_id)
    assert done.status == "refused" and world.ran == []
    assert done.reason.startswith("Refused and cancelled: " + CHANGED)
    assert done.reason == "Refused and cancelled: " + CHANGED + leads(place / "elsewhere" / "a.txt") + "). Ask again. Nothing was run."
    assert world.checkpoint.status(held.request_id)["state"] == "cancelled"
    cancelled = world.log("cancelled")[0]["detail"]["reason"]
    assert cancelled == CHANGED + leads(place / "elsewhere" / "a.txt") + "). Ask again"


def test_a_file_swapped_for_a_link_before_the_yes_is_cancelled_at_the_yes(place):
    world = World(place)
    (place / "project" / "README.md").write_text("old")
    held = world.ask()
    world.swap("README.md", str(place / "elsewhere" / "a.txt"))
    said = world.checkpoint.approve(held.request_id, held.fingerprint)
    assert said.status == "refused" and said.reason.startswith("Refused and cancelled: " + CHANGED)
    assert said.reason.endswith("Ask again.")
    assert world.checkpoint.status(held.request_id)["state"] == "cancelled"
    assert world.checkpoint.run(held.request_id).status == "refused" and world.ran == []


def test_a_link_pointed_at_another_ordinary_file_is_cancelled_because_the_card_named_the_first(place):
    world = World(place)
    world.swap("link.txt", str(place / "elsewhere" / "a.txt"))
    held = world.ask("link.txt")
    world.checkpoint.approve(held.request_id, held.fingerprint)
    world.swap("link.txt", str(place / "elsewhere" / "b.txt"))
    done = world.checkpoint.run(held.request_id)
    assert done.status == "refused" and world.ran == []
    assert done.reason == "Refused and cancelled: " + CHANGED + leads(place / "elsewhere" / "b.txt") + "). Ask again. Nothing was run."


def test_a_link_swapped_to_a_place_that_is_never_allowed_is_refused_as_before(place):
    world = World(place)
    held = world.ask()
    world.checkpoint.approve(held.request_id, held.fingerprint)
    world.swap("README.md", str(place / "elsewhere" / "guarded"))
    done = world.checkpoint.run(held.request_id)
    assert done.status == "refused" and "not allowed with these inputs" in done.reason and world.ran == []


def test_a_reason_that_went_away_does_not_cancel(place):
    world = World(place)
    world.swap("link.txt", str(place / "elsewhere" / "a.txt"))
    held = world.ask("link.txt")
    world.checkpoint.approve(held.request_id, held.fingerprint)
    os.unlink(place / "project" / "link.txt")
    os.symlink(place / "project" / "src" / "x.txt", place / "project" / "link.txt")  # now it leads inside: nothing asks
    assert world.checkpoint.run(held.request_id).status == "ran"


def test_a_rule_that_now_fails_cancels(place):
    calls = []

    class Flaky(rules.Rule):
        kind = "flaky"

        def _look(self, inputs):
            calls.append(1)
            if len(calls) > 2:
                raise RuntimeError("broken")
            return [(NEEDS_YES, "first reason")]

    world = World(place, level=Flaky({}))
    held = world.ask()
    done = world.checkpoint.approve(held.request_id, held.fingerprint)
    assert done.status == "refused" and "failed (RuntimeError)" in done.reason


def test_a_new_reason_from_a_rule_cancels_and_is_named(place):
    said = {"reasons": ["first reason"]}

    class Told(rules.Rule):
        kind = "told"

        def _look(self, inputs):
            return [(NEEDS_YES, reason) for reason in said["reasons"]]

    world = World(place, level=Told({}))
    held = world.ask()
    said["reasons"] = ["first reason", "second reason"]
    done = world.checkpoint.approve(held.request_id, held.fingerprint)
    assert done.reason == "Refused and cancelled: " + CHANGED + "second reason). Ask again."
    held = world.ask()
    said["reasons"] = ["first reason"]
    assert world.checkpoint.approve(held.request_id, held.fingerprint).status == "approved"


def test_a_plain_level_or_a_plain_function_gives_no_reasons_and_works_as_before(place):
    for level in (NEEDS_YES, lambda inputs: NEEDS_YES):
        world = World(place, level=level)
        held = world.ask()
        assert world.log("held")[0]["detail"]["reasons"] == []
        world.checkpoint.approve(held.request_id, held.fingerprint)
        assert world.checkpoint.run(held.request_id).status == "ran"


# ---- a Hold: what was read is not the action -------------------------------------------


def test_text_read_while_the_owner_decides_does_not_cancel_a_yes(place):
    hold = Hold()
    world = World(place, level=hold.over(FREE))
    hold.on("a web page was read")
    held = world.ask("src/app.py")
    assert held.status == "held" and world.log("held")[0]["detail"]["reasons"] == []
    hold.on("an email was read")  # more outside text, read while the owner looks at the card
    world.checkpoint.approve(held.request_id, held.fingerprint)
    hold.off()
    assert world.checkpoint.run(held.request_id).status == "ran"


def test_under_a_hold_the_rule_beneath_is_still_compared(place):
    hold = Hold()
    files = rules.files([str(place / "project" / "src")], does="write")
    world = World(place, level=hold.over(files))
    hold.on("a web page was read")
    (place / "project" / "src" / "app.py").write_text("old")
    held = world.ask("src/app.py")
    world.checkpoint.approve(held.request_id, held.fingerprint)
    world.swap("src/app.py", str(place / "elsewhere" / "a.txt"))
    done = world.checkpoint.run(held.request_id)
    assert done.status == "refused" and done.reason == "Refused and cancelled: " + CHANGED + "; ".join(sorted([LINK, leads(place / "elsewhere" / "a.txt")])) + "). Ask again. Nothing was run."


def test_a_hold_gives_only_the_reasons_of_the_level_beneath(place):
    hold = Hold()
    hold.on("a web page was read")
    files = rules.files([str(place / "project" / "src")], does="write")
    outside = {"path": str(place / "project" / "README.md"), "content": "x"}
    assert hold.over(files).reasons_in(outside) == (OUTSIDE,)
    assert hold.over(files).explain(outside).reasons[-1] == "the app said to ask: a web page was read"
    for level in (FREE, NEEDS_YES, NEVER, lambda inputs: NEEDS_YES):
        assert hold.over(level).reasons_in(outside) == ()


# ---- what the log holds ----------------------------------------------------------------


def _edit_held(db, change):
    connection = sqlite3.connect(db)
    row = connection.execute("SELECT seq, detail FROM log WHERE event = 'held'").fetchone()
    change(connection, row)
    connection.commit()
    connection.close()


def test_a_request_held_by_an_older_version_is_not_compared(place):
    db = str(place / "kettle.db")
    world = World(place, db=db)
    held = world.ask()

    def drop(connection, row):
        detail = json.loads(row[1])
        del detail["reasons"]
        connection.execute("UPDATE log SET detail = ? WHERE seq = ?", (json.dumps(detail), row[0]))

    _edit_held(db, drop)
    world.checkpoint.approve(held.request_id, held.fingerprint)
    world.swap("README.md", str(place / "elsewhere" / "a.txt"))
    assert world.checkpoint.run(held.request_id).status == "ran"


@pytest.mark.parametrize(
    "change, why",
    [
        (lambda connection, row: connection.execute("UPDATE log SET detail = 'not json' WHERE seq = ?", (row[0],)), "has no readable entry"),
        (lambda connection, row: connection.execute("DELETE FROM log WHERE seq = ?", (row[0],)), "has no readable entry"),
        (lambda connection, row: connection.execute("UPDATE log SET detail = '[]' WHERE seq = ?", (row[0],)), "has no readable entry"),
        (lambda connection, row: connection.execute("UPDATE log SET detail = ? WHERE seq = ?", (json.dumps({"reasons": "x"}), row[0])), "cannot be read"),
        (lambda connection, row: connection.execute("UPDATE log SET detail = ? WHERE seq = ?", (json.dumps({"reasons": [1]}), row[0])), "cannot be read"),
    ],
)
def test_a_held_entry_that_is_missing_or_cannot_be_read_refuses(place, change, why):
    db = str(place / "kettle.db")
    world = World(place, db=db)
    held = world.ask()
    _edit_held(db, change)
    done = world.checkpoint.approve(held.request_id, held.fingerprint)
    assert done.status == "refused" and why in done.reason and world.ran == []


# ---- the reasons themselves ------------------------------------------------------------


def _tool(level):
    table = Rules()
    return table.add("t", lambda **inputs: None, level=level), table


def test_reasons_are_sorted_without_repeats():
    class Many:
        def __call__(self, inputs):
            return NEEDS_YES

        def reasons_in(self, inputs):
            return ("b", "a", "b")

    tool, table = _tool(Many())
    assert table.reasons_for(tool, {}) == ["a", "b"]


def test_a_long_reason_is_cut_with_a_mark_so_two_that_differ_at_the_end_stay_two():
    said = []

    class Long(rules.Rule):
        kind = "long"

        def _look(self, inputs):
            return [(NEEDS_YES, reason) for reason in said]

    tool, table = _tool(Long({}))
    said[:] = ["x" * 400 + "1", "x" * 400 + "2", "y" * MAX_REASON]
    kept = table.reasons_for(tool, {})
    assert len(kept) == 3 and all(len(reason) <= MAX_REASON for reason in kept)
    assert "y" * MAX_REASON in kept
    assert sum(1 for reason in kept if reason.endswith("]") and " [cut, #" in reason) == 2


def test_reasons_that_are_not_text_refuse():
    class Odd:
        def __call__(self, inputs):
            return NEEDS_YES

        def reasons_in(self, inputs):
            return ("fine", 7)

    tool, table = _tool(Odd())
    with pytest.raises(Refused, match="did not give its reasons as text"):
        table.reasons_for(tool, {})


def test_a_rule_that_fails_when_asked_for_reasons_refuses_the_request(place):
    class Breaks:
        def __call__(self, inputs):
            return NEEDS_YES

        def reasons_in(self, inputs):
            raise RuntimeError("no")

    world = World(place, level=Breaks())
    done = world.ask()
    assert done.status == "refused" and "failed (RuntimeError)" in done.reason and world.log("held") == []
