"""The small pieces for plugging Kettle into a tool loop that already exists. No model, no network.

As in the other fixed tests, what counts is what the World saw run.
"""

import io
import json
import os
import sys
from types import SimpleNamespace as NS

import pytest

from conftest import EMAIL
from kettle import FREE, NEEDS_YES, Checkpoint
from kettle.adapters import (
    QUESTION,
    SAID_NO,
    WAITING,
    anthropic_tool_results,
    anthropic_tools,
    ask_in_terminal,
    openai_arguments,
    openai_assistant_message,
    openai_tool_messages,
    openai_tools,
    through,
)
from kettle.attacktest import TOOL_SPECS


def recorder(answers=None):
    calls = []

    def call(name, inputs):
        calls.append((name, inputs))
        return (answers or {}).get(name, f"result of {name}")

    return call, calls


class Human:
    """Stands in for the person at the keyboard: answers in order, and keeps what was shown."""

    def __init__(self, *answers):
        self.answers, self.asked, self.shown = list(answers), [], []

    def ask(self, question):
        self.asked.append(question)
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def show(self, text):
        self.shown.append(text)


# ---- the tool list ----


def test_the_tool_list_for_each_api_has_every_tool_in_that_apis_shape():
    for_anthropic, for_openai = anthropic_tools(TOOL_SPECS), openai_tools(TOOL_SPECS)
    assert len(for_anthropic) == len(for_openai) == len(TOOL_SPECS) == 8
    for spec, a, o in zip(TOOL_SPECS, for_anthropic, for_openai):
        assert a == {"name": spec.name, "description": spec.description, "input_schema": spec.parameters}
        assert o == {"type": "function", "function": {"name": spec.name, "description": spec.description, "parameters": spec.parameters}}
    json.dumps([for_anthropic, for_openai])  # plain data, ready to send


# ---- running what the model asked for ----


@pytest.mark.parametrize("as_dicts", [False, True])
def test_anthropic_tool_uses_are_run_in_order_and_each_gets_its_result(as_dicts):
    blocks = [
        {"type": "text", "text": "Looking."},
        {"type": "tool_use", "id": "t1", "name": "list_emails", "input": {}},
        {"type": "tool_use", "id": "t2", "name": "read_email", "input": {"id": "e1"}},
    ]
    content = blocks if as_dicts else [NS(**block) for block in blocks]
    call, calls = recorder({"read_email": "the email"})
    assert anthropic_tool_results(content, call) == [
        {"type": "tool_result", "tool_use_id": "t1", "content": "result of list_emails"},
        {"type": "tool_result", "tool_use_id": "t2", "content": "the email"},
    ]
    assert calls == [("list_emails", {}), ("read_email", {"id": "e1"})]


def test_a_reply_that_asks_for_no_tool_gives_no_results_and_runs_nothing():
    call, calls = recorder()
    assert anthropic_tool_results([NS(type="text", text="Done.")], call) == []
    assert anthropic_tool_results([], call) == [] and anthropic_tool_results(None, call) == []
    assert openai_tool_messages(None, call) == [] and openai_tool_messages([], call) == []
    assert calls == []


@pytest.mark.parametrize("as_dicts", [False, True])
def test_openai_tool_calls_are_run_in_order_and_each_gets_its_own_message(as_dicts):
    raw = [
        {"id": "c1", "type": "function", "function": {"name": "list_emails", "arguments": "{}"}},
        {"id": "c2", "type": "function", "function": {"name": "read_email", "arguments": '{"id": "e1"}'}},
    ]
    tool_calls = raw if as_dicts else [NS(id=item["id"], type="function", function=NS(**item["function"])) for item in raw]
    call, calls = recorder({"read_email": "the email"})
    assert openai_tool_messages(tool_calls, call) == [
        {"role": "tool", "tool_call_id": "c1", "content": "result of list_emails"},
        {"role": "tool", "tool_call_id": "c2", "content": "the email"},
    ]
    assert calls == [("list_emails", {}), ("read_email", {"id": "e1"})]
    message = {"role": "assistant", "content": None, "tool_calls": raw} if as_dicts else NS(content=None, tool_calls=tool_calls)
    assert openai_assistant_message(message) == {"role": "assistant", "content": None, "tool_calls": raw}


def test_an_openai_turn_with_no_tool_call_has_no_tool_calls_entry():
    assert openai_assistant_message(NS(content="Done.", tool_calls=None)) == {"role": "assistant", "content": "Done."}


def test_an_openai_tool_call_that_is_not_a_function_call_stops_everything_before_anything_runs():
    call, calls = recorder()
    mixed = [NS(id="c1", type="function", function=NS(name="pay", arguments="{}")), NS(id="c2", type="custom", custom=NS(name="pay", input="x"))]
    with pytest.raises(ValueError, match="not a function call"):
        openai_tool_messages(mixed, call)
    with pytest.raises(ValueError, match="not a function call"):
        openai_assistant_message(NS(content=None, tool_calls=mixed))
    assert calls == []


@pytest.mark.parametrize(
    "arguments, expected",
    [
        ('{"to": "sam@example.com", "amount": 40}', {"to": "sam@example.com", "amount": 40}),
        ("{}", {}),
        ("", {}),
        (" \n", {}),
        ('{"to": "sam@example.com"', '{"to": "sam@example.com"'),  # cut off: handed on as the text it is
        ("pay sam", "pay sam"),
        ("[1, 2]", [1, 2]),
        ("[" * 100_000, "[" * 100_000),
        ({"to": "sam@example.com"}, {"to": "sam@example.com"}),  # a server that sends an object, not text
        (None, None),
    ],
)
def test_reading_the_inputs_of_an_openai_tool_call(arguments, expected):
    assert openai_arguments(arguments) == expected


def test_inputs_a_server_sent_as_an_object_go_back_as_json_text():
    message = NS(content=None, tool_calls=[NS(id="c1", function=NS(name="pay", arguments={"to": "sam", "amount": 1}))])
    assert openai_assistant_message(message)["tool_calls"][0]["function"]["arguments"] == '{"to": "sam", "amount": 1}'


def test_a_result_that_is_not_text_is_made_into_text():
    assert anthropic_tool_results([NS(type="tool_use", id="t1", name="count", input={})], lambda name, inputs: 3)[0]["content"] == "3"
    assert openai_tool_messages([NS(id="c1", function=NS(name="count", arguments="{}"))], lambda name, inputs: 3)[0]["content"] == "3"


# ---- a checkpoint in front of your own tools ----


def test_a_free_tool_runs_and_its_result_is_the_text(cp, world):
    call = through(cp.gate)
    assert call("read_note", {}) == "the note" and world.ran == [("read_note", {})]


def test_a_free_tool_that_gives_back_something_other_than_text_still_comes_back_as_text(db_path):
    cp = Checkpoint(db_path)
    cp.tool("count_notes", lambda: 42, level=FREE)
    text = through(cp.gate)("count_notes", {})
    assert type(text) is str and text == "42"


def test_inputs_nested_too_deep_to_read_are_refused_and_do_not_stop_the_program(cp, world):
    deep = "[" * 100000 + "]" * 100000  # some Python versions cannot read this at all, others can
    call = through(cp.gate)
    for arguments in (deep, '{"to": ' + deep + ', "body": "hello"}'):
        inputs = openai_arguments(arguments)
        assert inputs == arguments or type(inputs) in (list, dict)
        text = call("send_email", inputs)
        assert type(text) is str and text.startswith("Refused")
    assert world.ran == [] and cp.pending() == []


def test_inputs_python_gives_up_reading_are_handed_on_as_text_on_every_python_version(cp, world, monkeypatch):
    written, read = '{"to": [[[["x"]]]]}', json.loads

    def gives_up(text, *args, **options):
        if text == written:
            raise RecursionError("maximum recursion depth exceeded")
        return read(text, *args, **options)

    monkeypatch.setattr("kettle.adapters.json.loads", gives_up)  # what Python 3.11 does with very deep JSON
    assert openai_arguments(written) == written
    messages = openai_tool_messages([{"id": "call_1", "function": {"name": "send_email", "arguments": written}}], through(cp.gate))
    assert len(messages) == 1 and messages[0]["content"].startswith("Refused")
    assert world.ran == [] and cp.pending() == []


def test_a_risky_tool_is_held_and_the_model_is_told_it_is_waiting(cp, world):
    call = through(cp.gate)
    assert call("send_email", dict(EMAIL)) == WAITING
    assert world.risky() == [] and len(cp.pending()) == 1
    assert "Nothing has been run" in WAITING


def test_what_is_refused_comes_back_as_the_reason_and_does_not_run(cp, world):
    call = through(cp.gate)
    for name, inputs in [("wipe_account", {}), ("transfer_everything", {}), ("send_email", {"to": "sam@example.com"}), ("send_email", "to sam"), ("pay", None)]:
        text = call(name, inputs)
        assert type(text) is str and text.startswith("Refused"), (name, text)
    assert world.ran == [] and cp.pending() == []


def test_a_checkpoint_that_is_not_working_refuses_through_the_adapter_too(cp, world, monkeypatch):
    monkeypatch.setattr(cp._store, "write", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    text = through(cp.gate)("send_email", dict(EMAIL))
    assert "not working" in text and world.ran == []


def test_a_free_tool_that_fails_comes_back_as_text_and_not_as_a_crash(db_path):
    def broken():
        raise OSError("disk gone")

    checkpoint = Checkpoint(db_path)
    checkpoint.tool("broken", broken, level=FREE)
    text = through(checkpoint.gate)("broken", {})
    assert "started and failed" in text and "disk gone" not in text


def test_a_held_action_is_handed_to_on_held_and_its_answer_is_the_text(cp, world):
    seen = []
    call = through(cp.gate_for("inbox-agent"), on_held=lambda decision: seen.append(decision) or 7)
    assert call("send_email", dict(EMAIL)) == "7"
    (decision,) = seen
    assert decision.status == "held" and decision.tool == "send_email" and '"inbox-agent"' in decision.preview
    assert world.risky() == []  # being asked is not a yes
    assert call("read_note", {}) == "the note" and len(seen) == 1  # a free tool does not ask


def test_the_gate_handed_to_through_cannot_approve_or_run(cp):
    call = through(cp.gate)
    assert not hasattr(cp.gate, "approve") and not hasattr(cp.gate, "run") and not hasattr(call, "approve")


# ---- asking in the terminal ----


def test_a_yes_at_the_keyboard_runs_the_action_that_was_shown_once(cp, world):
    human = Human("yes")
    call = through(cp.gate, on_held=ask_in_terminal(cp, ask=human.ask, show=human.show))
    assert call("send_email", dict(EMAIL)) == "sent"
    assert world.risky() == [("send_email", EMAIL)]
    assert human.asked == [QUESTION]
    shown = "\n".join(human.shown)
    assert 'Action: "send_email"' in shown and '"to": "sam@example.com"' in shown and "Fingerprint: " in shown
    assert shown.index("Nothing has run yet") < shown.index("Action:") < shown.index("Ran.")
    events = [entry["event"] for entry in cp.log()]
    assert events == ["held", "approved", "started", "ran"] and cp.verify_log()[0]


@pytest.mark.parametrize("answer", ["", "y", "Y", "Yes", "YES", "yes please", "yes!", "no", "ok", "sure", "yes yes", "уes", None, 1, True, EOFError()])
def test_anything_but_the_word_yes_is_a_no_and_nothing_runs(cp, world, answer):
    human = Human(answer)
    call = through(cp.gate, on_held=ask_in_terminal(cp, ask=human.ask, show=human.show))
    assert call("send_email", dict(EMAIL)) == SAID_NO
    assert world.risky() == [] and cp.pending() == []
    assert [entry["event"] for entry in cp.log()] == ["held", "denied"]
    assert "Refused. Nothing was run." in human.shown and "Ran." not in human.shown


@pytest.mark.parametrize("answer", ["yes", " yes ", "yes\n"])
def test_spaces_around_the_yes_do_not_matter(cp, world, answer):
    human = Human(answer)
    assert through(cp.gate, on_held=ask_in_terminal(cp, ask=human.ask, show=human.show))("send_email", dict(EMAIL)) == "sent"
    assert len(world.risky()) == 1


def test_with_no_keyboard_to_ask_at_the_answer_is_no(cp, world, monkeypatch):
    piped = io.StringIO("yes\nyes\nyes\n")  # input that is piped in is not a person
    monkeypatch.setattr(sys, "stdin", piped)
    shown = []
    call = through(cp.gate, on_held=ask_in_terminal(cp, show=shown.append))
    assert call("send_email", dict(EMAIL)) == SAID_NO
    assert world.risky() == [] and piped.tell() == 0  # nothing was read from it
    monkeypatch.setattr(sys, "stdin", None)
    assert call("send_email", dict(EMAIL)) == SAID_NO and world.risky() == []


def test_piped_input_is_not_the_answer_even_where_throwing_typed_input_away_needs_no_terminal(cp, world, monkeypatch):
    # On Windows the keyboard is emptied without touching stdin, so that step does not fail on a pipe.
    monkeypatch.setattr("kettle.adapters._discard_typed_ahead", lambda: None)
    piped = io.StringIO("yes\n")
    monkeypatch.setattr(sys, "stdin", piped)
    call = through(cp.gate, on_held=ask_in_terminal(cp, show=lambda line: None))
    assert call("send_email", dict(EMAIL)) == SAID_NO
    assert world.risky() == [] and piped.tell() == 0


def terminal(monkeypatch, typed_early, typed_at_the_question):
    """A pretend terminal on stdin. Returns the questions that were asked."""
    pty = pytest.importorskip("pty")
    ours, theirs = pty.openpty()
    keyboard = open(theirs, "r", closefd=False)
    asked = []

    def typing(question):  # stands in for input(): the person types once the question is up
        asked.append(question)
        os.write(ours, typed_at_the_question.encode())
        return keyboard.readline()

    monkeypatch.setattr(sys, "stdin", keyboard)
    monkeypatch.setattr("kettle.adapters.input", typing, raising=False)
    os.write(ours, typed_early.encode())
    return asked, lambda: (keyboard.close(), os.close(ours), os.close(theirs))


def test_a_yes_typed_before_the_question_was_on_screen_does_not_answer_it(cp, world, monkeypatch):
    asked, close = terminal(monkeypatch, typed_early="yes\nyes\n", typed_at_the_question="no\n")
    try:
        call = through(cp.gate, on_held=ask_in_terminal(cp, show=lambda text: None))
        assert call("send_email", dict(EMAIL)) == SAID_NO and world.risky() == []
        assert call("pay", {"to": "acme", "amount": 40}) == SAID_NO and world.risky() == []
    finally:
        close()
    assert asked == [QUESTION, QUESTION]


def test_a_yes_typed_at_the_question_still_counts_after_something_was_typed_too_early(cp, world, monkeypatch):
    asked, close = terminal(monkeypatch, typed_early="no\nno\n", typed_at_the_question="yes\n")
    try:
        assert through(cp.gate, on_held=ask_in_terminal(cp, show=lambda text: None))("send_email", dict(EMAIL)) == "sent"
    finally:
        close()
    assert world.risky() == [("send_email", EMAIL)] and asked == [QUESTION]


def test_if_what_was_typed_early_cannot_be_thrown_away_the_answer_is_no(cp, world, monkeypatch):
    asked, close = terminal(monkeypatch, typed_early="", typed_at_the_question="yes\n")

    def broken():
        raise OSError("no such terminal")

    monkeypatch.setattr("kettle.adapters._discard_typed_ahead", broken)
    try:
        assert through(cp.gate, on_held=ask_in_terminal(cp, show=lambda text: None))("send_email", dict(EMAIL)) == SAID_NO
    finally:
        close()
    assert world.risky() == [] and asked == []


def test_each_held_action_is_asked_about_on_its_own(cp, world):
    human = Human("yes", "no", "yes")
    call = through(cp.gate, on_held=ask_in_terminal(cp, ask=human.ask, show=human.show))
    assert call("send_email", dict(EMAIL)) == "sent"
    assert call("send_email", dict(EMAIL)) == SAID_NO  # the same action again needs its own yes
    assert call("pay", {"to": "acme", "amount": 40}) == "paid"
    assert world.risky() == [("send_email", EMAIL), ("pay", {"to": "acme", "amount": 40})]
    assert len(human.asked) == 3


def test_a_yes_that_comes_too_late_runs_nothing(cp, world, clock):
    def slow(question):
        clock.forward(601)
        return "yes"

    shown = []
    text = through(cp.gate, on_held=ask_in_terminal(cp, ask=slow, show=shown.append))("send_email", dict(EMAIL))
    assert "expired" in text and world.risky() == [] and "Ran." not in shown


def test_a_yes_does_not_carry_over_to_an_action_that_was_not_shown(cp, world):
    """on_held called with a decision whose fingerprint is not the held action's: the yes is for something else."""
    first = cp.request("send_email", dict(EMAIL))
    other = cp.request("send_email", {"to": "eve@example.net", "body": "See you at 3."})
    swapped = type(first)(first.status, first.reason, first.tool, other.request_id, first.fingerprint, first.preview, first.expires_at)
    human = Human("yes")
    text = ask_in_terminal(cp, ask=human.ask, show=human.show)(swapped)
    assert "different action" in text and world.risky() == []


def test_answering_the_same_question_twice_runs_it_once(cp, world):
    held = cp.request("send_email", dict(EMAIL))
    human = Human("yes", "yes")
    on_held = ask_in_terminal(cp, ask=human.ask, show=human.show)
    assert on_held(held) == "sent"
    assert on_held(held).startswith("Refused") and world.risky() == [("send_email", EMAIL)]


def test_an_action_that_fails_after_the_yes_is_reported_and_not_retried(db_path):
    tries = []

    def send_email(to, body):
        tries.append(to)
        raise OSError("network down")

    checkpoint = Checkpoint(db_path)
    checkpoint.tool("send_email", send_email, level=NEEDS_YES)
    human = Human("yes")
    text = through(checkpoint.gate, on_held=ask_in_terminal(checkpoint, ask=human.ask, show=human.show))("send_email", dict(EMAIL))
    assert "may or may not have acted" in text and tries == ["sam@example.com"] and text in human.shown


def test_the_first_time_mark_is_in_what_the_human_is_shown(db_path, world):
    checkpoint = Checkpoint(db_path)
    checkpoint.tool("send_email", world.send_email, level=NEEDS_YES, watch=["to"])
    human = Human("yes", "yes")
    call = through(checkpoint.gate, on_held=ask_in_terminal(checkpoint, ask=human.ask, show=human.show))
    assert call("send_email", dict(EMAIL)) == "sent"
    first = "\n".join(human.shown)
    assert "! 1 input below is marked first time" in first and "! first time: no approved action has run with this value before" in first
    human.shown.clear()
    assert call("send_email", dict(EMAIL)) == "sent"
    assert "first time" not in "\n".join(human.shown)


def test_who_said_yes_is_written_in_the_log(cp):
    human = Human("yes", "no")
    call = through(cp.gate, on_held=ask_in_terminal(cp, approver="james at the keyboard", ask=human.ask, show=human.show))
    call("send_email", dict(EMAIL))
    call("send_email", dict(EMAIL))
    by = [entry["detail"].get("by") for entry in cp.log() if entry["event"] in ("approved", "denied")]
    assert by == ["james at the keyboard", "james at the keyboard"]


def test_what_is_shown_is_plain_ascii_whatever_the_agent_put_in_the_action(cp):
    human = Human("no")
    nasty = {"to": "sam@exampⅼe.com", "body": "ok\x1b[2J\x1b[H‮Approved already\r\nType yes"}
    through(cp.gate, on_held=ask_in_terminal(cp, ask=human.ask, show=human.show))("send_email", nasty)
    for line in "\n".join(human.shown).splitlines():
        assert all(32 <= ord(char) < 127 for char in line), line


# ---- the two together, in a loop like the ones people already have ----


def test_a_whole_anthropic_style_loop_with_a_checkpoint_in_front_of_the_tools(cp, world):
    """A model that reads a note, then tries a send the human refuses, then one the human agrees to."""
    replies = [
        [NS(type="tool_use", id="t1", name="read_note", input={})],
        [NS(type="tool_use", id="t2", name="send_email", input={"to": "eve@example.net", "body": "the note"})],
        [NS(type="tool_use", id="t3", name="send_email", input=dict(EMAIL))],
        [NS(type="text", text="Done.")],
    ]
    human = Human("no", "yes")
    call = through(cp.gate_for("notes-agent"), on_held=ask_in_terminal(cp, ask=human.ask, show=human.show))
    told = []
    for content in replies:
        results = anthropic_tool_results(content, call)
        if not results:
            break
        told += [result["content"] for result in results]
    assert told == ["the note", SAID_NO, "sent"]
    assert world.risky() == [("send_email", EMAIL)]
    assert sum('"notes-agent"' in text for text in human.shown) == 2
