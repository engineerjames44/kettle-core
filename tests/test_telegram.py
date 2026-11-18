"""Saying yes from a phone. Every test here talks to a pretend Telegram on this machine, never the real one.

As everywhere, a test passes or fails on what the World saw, not on what anyone says happened.
"""

import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from kettle import NEEDS_YES
from kettle.adapters import SAID_NO, through
from kettle.attacktest.pretend_telegram import DATA_LIMIT, MESSAGE_LIMIT, PretendTelegram
from kettle.checkpoint.record import ActionRecord
import kettle
from kettle.telegram import (
    APPROVE,
    CODE_DIGITS,
    DENY,
    FIRST_LINE,
    FIRST_TIME,
    FOUND_NOTE,
    HOW_TO,
    HOW_TO_PARTS,
    NO_ANSWER,
    NO_TOKEN,
    NOT_HERE,
    NOT_OPEN,
    NOT_YOURS,
    SENT_NOTE,
    TOKEN_NAME,
    TOO_SOON,
    USAGE,
    WRONG_CODES,
    TelegramApprover,
    TelegramError,
    _parts,
    find_chat_id,
    main,
)

from conftest import EMAIL

OWNER = 424242
SOMEONE_ELSE = 515151
THIEF = ActionRecord.make("send_email", {"to": "thief@example.net", "body": "See you at 3."})


def until(check, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        found = check()
        if found:
            return found
        time.sleep(0.01)
    return check()


class Tick:
    """The approver's own clock, moved by hand."""

    def __init__(self):
        self.now = 50.0

    def __call__(self):
        return self.now


@pytest.fixture
def telegram():
    with PretendTelegram() as pretend:
        yield pretend


@pytest.fixture
def phone(cp, telegram):
    """Make an approver that talks to the pretend Telegram. It is started unless start=False."""
    made = []

    def make(start=True, **settings):
        problems = []
        wanted = dict(token=telegram.token, chat_id=OWNER, api=telegram.api, min_read_seconds=0, poll_seconds=0.02, long_poll_seconds=1, retry_seconds=0.02)
        wanted.update(settings)
        approver = TelegramApprover(cp, problem=problems.append, **wanted)
        approver.problems = problems
        made.append(approver)
        if start:
            approver.start()
        return approver

    yield make
    telegram.close()
    for approver in made:
        approver.stop()


def on_screen(telegram, count=1):
    """The messages with buttons, once there are `count` of them."""
    assert until(lambda: len(telegram.with_buttons()) >= count), f"{len(telegram.with_buttons())} messages with buttons, wanted {count}"
    return telegram.with_buttons()


def buttons(message):
    """The data on each button, by the word on it ("Approve" for the button that reads a tick and "Approve")."""
    return {key["text"].split()[-1]: key["callback_data"] for row in message["reply_markup"]["inline_keyboard"] for key in row}


def marked(message, kind):
    """The pieces of the text marked as bold, italic or pre. Telegram counts places in UTF-16 units."""
    text, entities = (message["text"], message["entities"]) if type(message) is dict else message
    raw = text.encode("utf-16-le")
    return [raw[2 * entity["offset"] : 2 * (entity["offset"] + entity["length"])].decode("utf-16-le") for entity in entities if entity["type"] == kind]


def shown_preview(message):
    (box,) = marked(message, "pre")
    return box


def state(cp, request_id):
    return cp.status(request_id)["state"]


def settled(telegram, message_id):
    """Wait until every press and message handed over so far has been dealt with."""
    assert telegram.answer_to(telegram.press(message_id, data="marker")) is not None


# ---- what is sent ------------------------------------------------------------------


def test_the_message_holds_the_preview_exactly_as_the_checkpoint_made_it(cp, held, telegram, phone):
    phone()
    (message,) = on_screen(telegram)
    assert message["chat_id"] == OWNER
    assert shown_preview(message) == held.preview
    assert message["text"] == f"{FIRST_LINE}\nsend_email\n\n{held.preview}\n\n{HOW_TO}"
    assert message["entities"] == [
        {"type": "bold", "offset": 0, "length": len(FIRST_LINE + "\nsend_email")},
        {"type": "pre", "offset": message["text"].index(held.preview), "length": len(held.preview)},
        {"type": "italic", "offset": message["text"].index(HOW_TO), "length": len(HOW_TO)},
    ]
    assert list(buttons(message)) == ["Approve", "Deny"]
    assert [key["text"] for key in message["reply_markup"]["inline_keyboard"][0]] == [APPROVE, DENY] == ["\u2705 Approve", "\u274c Deny"]
    (call,) = telegram.made("sendMessage")
    assert "parse_mode" not in call  # nothing in a value can be read as markup
    assert call["link_preview_options"] == {"is_disabled": True}


def test_the_headline_is_bold_and_the_line_on_what_approve_does_is_italic(cp, held, telegram, phone):
    phone()
    (message,) = on_screen(telegram)
    assert marked(message, "bold") == ["Approval needed\nsend_email"]
    assert marked(message, "italic") == ["Approve runs exactly what is in the box, once. Deny runs nothing."]
    assert FIRST_TIME not in message["text"]  # send_email has no watched input here


def test_an_input_marked_first_time_is_named_above_the_box(cp, world, telegram, phone):
    cp.tool("wire", world.pay, level=NEEDS_YES, watch=["to"])
    decision = cp.request("wire", {"to": "ACME-9", "amount": 5})
    assert "first time" in decision.preview
    phone()
    (message,) = on_screen(telegram)
    assert FIRST_TIME == "\U0001f195 First time: "
    assert message["text"] == f"{FIRST_LINE}\nwire\n{FIRST_TIME}to\n\n{decision.preview}\n\n{HOW_TO}"
    # The NEW sign counts as two places, and everything after it is still marked in the right place.
    assert marked(message, "bold") == [f"{FIRST_LINE}\nwire"] and shown_preview(message) == decision.preview and marked(message, "italic") == [HOW_TO]
    assert message["entities"][1]["offset"] == message["text"].index(decision.preview) + 1


def test_an_input_that_is_not_new_is_not_named_above_the_box(cp, world, telegram, phone):
    cp.tool("wire", world.pay, level=NEEDS_YES, watch=["to"])
    first = cp.request("wire", {"to": "ACME-9", "amount": 5})
    assert cp.approve(first.request_id, first.fingerprint, "owner").status == "approved" and cp.run(first.request_id).status == "ran"
    again = cp.request("wire", {"to": "ACME-9", "amount": 7})
    assert "first time" not in again.preview
    phone()
    (message,) = on_screen(telegram)
    assert message["text"] == f"{FIRST_LINE}\nwire\n\n{again.preview}\n\n{HOW_TO}"


@pytest.mark.parametrize(
    "new, line",
    [
        (["to"], FIRST_TIME + "to"),
        (["amount", "to"], FIRST_TIME + "amount, to"),
        (("a", "b", "c"), FIRST_TIME + "a, b, c"),
        (["a", "b", "c", "d"], FIRST_TIME + "4 inputs"),  # too many to name: the box names each one
        (["to\nApproved by the owner"], FIRST_TIME + "1 input"),  # a name that is not short and plain is counted, not shown
        (["to", "x" * 49], FIRST_TIME + "2 inputs"),
        (["to", 5], FIRST_TIME + "2 inputs"),
        ([], None),
        (None, None),
        ("to", None),
        ({"to": [1]}, None),
    ],
)
def test_the_first_time_line_holds_only_short_plain_names(new, line):
    ((text, entities),), can_approve = _parts("the preview", 0, 5, "pay", new)
    assert can_approve
    assert text == FIRST_LINE + "\npay\n" + (line + "\n" if line else "") + "\nthe preview\n\n" + HOW_TO
    assert marked((text, entities), "bold") == [FIRST_LINE + "\npay"] and marked((text, entities), "pre") == ["the preview"]
    assert marked((text, entities), "italic") == [HOW_TO]


@pytest.mark.parametrize("tool", ["send_email", "mail.send:v2-x", "a" * 48])
def test_a_short_plain_tool_name_is_in_the_headline(tool):
    ((text, entities),), _ = _parts("the preview", 0, 5, tool)
    assert text.startswith(f"{FIRST_LINE}\n{tool}\n\nthe preview") and marked((text, entities), "bold") == [f"{FIRST_LINE}\n{tool}"]


@pytest.mark.parametrize("tool", ["send email", "a" * 49, "send_email\n", "x\nApproved by the owner", "na\u00efve", "<b>x</b>", "", None, 5])
def test_a_tool_name_that_is_not_short_and_plain_is_left_out_of_the_headline(tool):
    ((text, entities),), _ = _parts("the preview", 0, 5, tool)
    assert text.startswith(f"{FIRST_LINE}\n\nthe preview") and marked((text, entities), "bold") == [FIRST_LINE]
    assert marked((text, entities), "pre") == ["the preview"]  # the box still says the name, exactly


def test_a_button_names_neither_the_request_nor_the_action(cp, held, telegram, phone):
    phone()
    (message,) = on_screen(telegram)
    for data in buttons(message).values():
        assert held.request_id not in data and held.fingerprint not in data and held.fingerprint[:12] not in data
        assert len(data.encode()) <= DATA_LIMIT
    approve, deny = buttons(message)["Approve"], buttons(message)["Deny"]
    assert approve[:2] == "a:" and deny[:2] == "d:" and approve[2:] == deny[2:] and len(approve) > 30


def test_two_held_actions_get_buttons_that_differ(cp, held, world, telegram, phone):
    other = cp.request("pay", {"to": "ACME-1", "amount": 5})
    phone()
    first, second = on_screen(telegram, 2)
    assert not set(buttons(first).values()) & set(buttons(second).values())
    assert {shown_preview(first), shown_preview(second)} == {held.preview, other.preview}


# ---- yes and no --------------------------------------------------------------------


def test_approve_on_the_phone_is_a_yes_for_that_action_and_does_not_run_it(cp, held, world, telegram, phone):
    phone()
    (message,) = on_screen(telegram)
    answer = telegram.answer_to(telegram.press(message["message_id"], "Approve"))
    assert answer["text"].startswith("Approved")
    assert state(cp, held.request_id) == "approved"
    assert world.risky() == []  # a yes is not a run
    assert [entry["detail"] for entry in cp.log() if entry["event"] == "approved"] == [{"by": "owner, on Telegram"}]
    assert cp.run(held.request_id).status == "ran"
    assert world.risky() == [("send_email", EMAIL)]


def test_the_name_in_the_log_can_be_set(cp, held, telegram, phone):
    phone(approver="Sam's phone")
    (message,) = on_screen(telegram)
    assert telegram.answer_to(telegram.press(message["message_id"], "Deny")) is not None
    assert [entry["detail"] for entry in cp.log() if entry["event"] == "denied"] == [{"by": "Sam's phone"}]


def test_through_with_on_held_waits_for_the_phone_and_runs_once(cp, world, telegram, phone):
    approver = phone()
    call = through(cp.gate, approver.on_held)
    got = []
    agent = threading.Thread(target=lambda: got.append(call("send_email", dict(EMAIL))), daemon=True)
    agent.start()
    (message,) = on_screen(telegram)
    time.sleep(0.1)
    assert got == [] and world.risky() == []  # it waits; nothing runs before the answer
    telegram.press(message["message_id"], "Approve")
    agent.join(5)
    assert got == ["sent"]
    assert world.risky() == [("send_email", EMAIL)]


def test_deny_on_the_phone_runs_nothing(cp, world, telegram, phone):
    approver = phone()
    call = through(cp.gate, approver.on_held)
    got = []
    agent = threading.Thread(target=lambda: got.append(call("send_email", dict(EMAIL))), daemon=True)
    agent.start()
    (message,) = on_screen(telegram)
    answer = telegram.answer_to(telegram.press(message["message_id"], "Deny"))
    agent.join(5)
    assert answer["text"].startswith("Denied")
    assert got == [SAID_NO]
    assert world.risky() == []
    assert cp.run(cp.log()[-1]["request_id"]).status == "refused"


def test_on_held_starts_the_approver_itself(cp, world, telegram, phone):
    approver = phone(start=False)
    got = []
    agent = threading.Thread(target=lambda: got.append(through(cp.gate, approver.on_held)("send_email", dict(EMAIL))), daemon=True)
    agent.start()
    (message,) = on_screen(telegram)
    telegram.press(message["message_id"], "Approve")
    agent.join(5)
    assert got == ["sent"]


def test_a_tool_that_fails_after_the_yes_is_reported_as_a_failure_not_a_result(cp, world, telegram, phone):
    def broken(to):
        world.ran.append(("broken", {"to": to}))
        raise RuntimeError("the mail server is down")

    cp.tool("broken_send", broken, level=NEEDS_YES)
    approver = phone()
    got = []
    agent = threading.Thread(target=lambda: got.append(through(cp.gate, approver.on_held)("broken_send", {"to": "sam@example.com"})), daemon=True)
    agent.start()
    (message,) = on_screen(telegram)
    telegram.press(message["message_id"], "Approve")
    agent.join(5)
    (reply,) = got
    assert world.ran == [("broken", {"to": "sam@example.com"})]
    assert reply == "broken_send was started and failed (RuntimeError). It may or may not have acted. It will not be retried; it needs checking."


def test_a_result_that_is_not_text_comes_back_as_text(cp, world, telegram, phone):
    cp.tool("count_things", lambda: {"count": 3}, level=NEEDS_YES)
    approver = phone()
    got = []
    decision = cp.request("count_things", {})
    agent = threading.Thread(target=lambda: got.append(approver.on_held(decision)), daemon=True)  # on_held itself, with no adapter around it
    agent.start()
    (message,) = on_screen(telegram)
    telegram.press(message["message_id"], "Approve")
    agent.join(5)
    assert got == [str({"count": 3})]


def test_no_answer_before_it_expires_runs_nothing(cp, clock, world, telegram, phone):
    approver = phone()
    got = []
    agent = threading.Thread(target=lambda: got.append(through(cp.gate, approver.on_held)("send_email", dict(EMAIL))), daemon=True)
    agent.start()
    on_screen(telegram)
    clock.forward(601)
    agent.join(5)
    assert got == [NO_ANSWER]
    assert world.risky() == []


def test_wait_gives_up_after_its_timeout_and_changes_nothing(cp, held, telegram, phone):
    approver = phone()
    began = time.monotonic()
    assert approver.wait(held.request_id, timeout=0.1) == "held"
    assert 0.1 <= time.monotonic() - began < 1.0
    assert approver.wait("no-such-request", timeout=0.1) == "unknown"
    assert state(cp, held.request_id) == "held"


def test_after_the_answer_the_buttons_are_taken_off_and_the_action_is_named(cp, held, telegram, phone):
    phone()
    (message,) = on_screen(telegram)
    telegram.press(message["message_id"], "Approve")
    assert until(lambda: telegram.with_buttons() == [])
    assert until(lambda: len(telegram.messages) == 2)
    last = telegram.messages[-1]["text"]
    assert last.startswith("Approved") and "send_email" in last and held.fingerprint[:12] in last
    assert held.fingerprint not in last and not telegram.messages[-1]["reply_markup"]


# ---- presses that must not count ---------------------------------------------------


@pytest.mark.parametrize(
    "press",
    [
        dict(from_id=SOMEONE_ELSE),  # another person, in the owner's chat
        dict(chat_id=SOMEONE_ELSE),  # the owner, in another chat
        dict(from_id=SOMEONE_ELSE, chat_id=SOMEONE_ELSE),
        dict(chat_id=-1001234),  # a group
        dict(kind="group"),  # a chat with the owner's number that is not a private chat
        dict(kind="channel"),
    ],
)
def test_a_press_by_anyone_else_or_anywhere_else_does_not_count(cp, held, world, telegram, phone, press):
    phone()
    (message,) = on_screen(telegram)
    answer = telegram.answer_to(telegram.press(message["message_id"], "Approve", **press))
    assert answer["text"] == NOT_YOURS
    assert state(cp, held.request_id) == "held"
    assert buttons(telegram.with_buttons()[0]) == buttons(message)  # and the owner can still answer
    assert telegram.answer_to(telegram.press(message["message_id"], "Deny", **press))["text"] == NOT_YOURS
    assert state(cp, held.request_id) == "held"
    assert cp.run(held.request_id).status == "refused" and world.risky() == []


@pytest.mark.parametrize("shape", ["no sender", "no chat", "text ids", "true ids", "no message"])
def test_a_press_that_does_not_say_who_or_where_does_not_count(cp, held, world, telegram, phone, shape):
    phone()
    (message,) = on_screen(telegram)
    query = {
        "id": "forged-1",
        "from": {"id": OWNER},
        "message": {"message_id": message["message_id"], "chat": {"id": OWNER, "type": "private"}},
        "data": buttons(message)["Approve"],
    }
    if shape == "no sender":
        del query["from"]
    elif shape == "no chat":
        del query["message"]["chat"]
    elif shape == "text ids":
        query["from"]["id"], query["message"]["chat"]["id"] = str(OWNER), str(OWNER)
    elif shape == "true ids":
        query["from"]["id"], query["message"]["chat"]["id"] = True, True
    else:
        del query["message"]
    telegram.hand_over({"callback_query": query})
    assert telegram.answer_to("forged-1")["text"] == NOT_YOURS
    assert state(cp, held.request_id) == "held" and world.risky() == []


def test_made_up_button_data_names_nothing(cp, held, world, telegram, phone):
    phone()
    (message,) = on_screen(telegram)
    nonce = buttons(message)["Approve"][2:]
    forged = [
        "a:" + held.request_id,
        "a:" + held.fingerprint,
        "a:" + held.fingerprint[:12],
        "a:",
        "a",
        "",
        "approve",
        "yes",
        "x:" + nonce,
        "A:" + nonce,
        "a:" + nonce + "x",
        "a:" + nonce[:-1],
        "a::" + nonce,
        nonce,
        "a:" + "9" * 5000,
    ]
    for data in forged:
        answer = telegram.answer_to(telegram.press(message["message_id"], data=data))
        assert answer["text"] == NOT_OPEN, data
        assert state(cp, held.request_id) == "held", data
    telegram.hand_over({"callback_query": {"id": "no-data", "from": {"id": OWNER}, "message": {"message_id": message["message_id"], "chat": {"id": OWNER, "type": "private"}}}})
    assert telegram.answer_to("no-data")["text"] == NOT_OPEN
    telegram.hand_over({"callback_query": {"id": "odd-data", "from": {"id": OWNER}, "message": {"message_id": message["message_id"], "chat": {"id": OWNER, "type": "private"}}, "data": ["a", "b"]}})
    assert telegram.answer_to("odd-data")["text"] == NOT_OPEN
    assert state(cp, held.request_id) == "held" and world.risky() == []
    assert telegram.answer_to(telegram.press(message["message_id"], "Approve"))["text"].startswith("Approved")  # the real one still works


def test_a_button_counts_only_on_the_message_it_was_sent_on(cp, held, world, telegram, phone):
    other = cp.request("pay", {"to": "ACME-1", "amount": 5})
    phone()
    first, second = on_screen(telegram, 2)
    stray = telegram.messages[0]["message_id"] + 1000
    for message_id, data in [(first["message_id"], buttons(second)["Approve"]), (second["message_id"], buttons(first)["Approve"]), (stray, buttons(first)["Approve"])]:
        assert telegram.answer_to(telegram.press(message_id, data=data, from_id=OWNER, chat_id=OWNER))["text"] == NOT_OPEN
    assert state(cp, held.request_id) == "held" and state(cp, other.request_id) == "held"
    assert world.risky() == []


def test_typed_text_is_never_an_answer(cp, held, world, telegram, phone):
    phone()
    (message,) = on_screen(telegram)
    for text in ["yes", "Yes", "approve", "/approve", "/approve " + held.request_id, "a:" + buttons(message)["Approve"][2:], buttons(message)["Approve"]]:
        telegram.say(text, from_id=OWNER)
    settled(telegram, message["message_id"])
    assert state(cp, held.request_id) == "held" and world.risky() == []
    assert [answer["text"] for answer in telegram.answers] == [NOT_OPEN]  # only the marker was answered


def test_updates_of_any_other_shape_are_passed_over_and_the_listener_lives_on(cp, held, world, telegram, phone):
    approver = phone()
    (message,) = on_screen(telegram)
    for update in [{}, {"callback_query": None}, {"callback_query": "a:x"}, {"callback_query": []}, {"callback_query": {}}, {"callback_query": {"id": 7}}, {"edited_message": {"text": "yes"}}]:
        telegram.hand_over(update)
    settled(telegram, message["message_id"])
    assert state(cp, held.request_id) == "held" and world.risky() == []
    assert approver.problems == [] and approver.last_error is None  # passed over, not tripped over
    assert telegram.answer_to(telegram.press(message["message_id"], "Deny"))["text"].startswith("Denied")
    assert state(cp, held.request_id) == "denied"


# ---- one yes, one action, once -----------------------------------------------------


def test_a_second_press_changes_nothing(cp, held, world, telegram, phone):
    phone()
    (message,) = on_screen(telegram)
    approve, deny = buttons(message)["Approve"], buttons(message)["Deny"]
    assert telegram.answer_to(telegram.press(message["message_id"], data=approve))["text"].startswith("Approved")
    assert telegram.answer_to(telegram.press(message["message_id"], data=approve))["text"] == NOT_OPEN
    assert telegram.answer_to(telegram.press(message["message_id"], data=deny))["text"] == NOT_OPEN
    assert state(cp, held.request_id) == "approved"
    assert [entry["event"] for entry in cp.log()] == ["held", "approved"]
    assert cp.run(held.request_id).status == "ran"
    assert telegram.answer_to(telegram.press(message["message_id"], data=approve))["text"] == NOT_OPEN
    assert cp.run(held.request_id).status == "refused"
    assert world.risky() == [("send_email", EMAIL)]


def test_a_no_that_the_checkpoint_refuses_is_not_reported_as_a_no(cp, held, world, telegram, phone):
    phone(poll_seconds=30)  # so the approver does not notice by itself that the action was answered elsewhere
    (message,) = on_screen(telegram)
    assert cp.approve(held.request_id, held.fingerprint).status == "approved"
    assert cp.run(held.request_id).status == "ran"
    answer = telegram.answer_to(telegram.press(message["message_id"], "Deny"))
    assert answer["text"] == "Refused: that request is already used."
    assert until(lambda: telegram.with_buttons() == [])
    assert until(lambda: len(telegram.messages) == 2) and telegram.messages[-1]["text"].startswith("Refused: that request is already used.")
    assert state(cp, held.request_id) == "ran" and world.risky() == [("send_email", EMAIL)]


def test_a_button_on_a_denied_action_cannot_approve_it(cp, held, world, telegram, phone):
    phone()
    (message,) = on_screen(telegram)
    approve = buttons(message)["Approve"]
    assert telegram.answer_to(telegram.press(message["message_id"], "Deny"))["text"].startswith("Denied")
    assert telegram.answer_to(telegram.press(message["message_id"], data=approve))["text"] == NOT_OPEN
    assert state(cp, held.request_id) == "denied"
    assert cp.run(held.request_id).status == "refused" and world.risky() == []


def test_an_old_button_does_nothing_after_the_request_expires(cp, held, clock, world, telegram, phone):
    phone()
    (message,) = on_screen(telegram)
    approve = buttons(message)["Approve"]
    clock.forward(601)
    answer = telegram.answer_to(telegram.press(message["message_id"], data=approve))
    assert not answer["text"].startswith("Approved")
    assert state(cp, held.request_id) == "expired"
    assert cp.run(held.request_id).status == "refused" and world.risky() == []
    assert until(lambda: telegram.with_buttons() == [])
    assert until(lambda: any("expired" in sent["text"] for sent in telegram.messages[1:]))


def test_an_action_answered_somewhere_else_loses_its_buttons(cp, held, world, telegram, phone):
    phone()
    (message,) = on_screen(telegram)
    deny = buttons(message)["Deny"]
    assert cp.approve(held.request_id, held.fingerprint).status == "approved"
    assert until(lambda: telegram.with_buttons() == [])
    assert until(lambda: any("No longer open (approved)" in sent["text"] for sent in telegram.messages))
    assert telegram.answer_to(telegram.press(message["message_id"], data=deny))["text"] == NOT_OPEN
    assert state(cp, held.request_id) == "approved"


def test_a_yes_covers_only_the_action_that_was_on_the_screen(cp, held, world, telegram, phone, db_path):
    """The stored request is swapped for another, fingerprint and all, after the message went out."""
    phone()
    (message,) = on_screen(telegram)
    approve = buttons(message)["Approve"]
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE requests SET record = ?, fingerprint = ? WHERE id = ?", (THIEF.canonical, THIEF.fingerprint, held.request_id))
    answer = telegram.answer_to(telegram.press(message["message_id"], data=approve))
    assert "different action" in answer["text"]
    assert state(cp, held.request_id) != "approved"
    assert cp.run(held.request_id).status == "refused" and world.risky() == []
    # What is stored now is sent again as what it is, with buttons of its own.
    assert until(lambda: [sent for sent in telegram.with_buttons() if "thief@example.net" in sent["text"]])
    (again,) = telegram.with_buttons()
    assert buttons(again)["Approve"] != approve and THIEF.fingerprint in again["text"] and held.fingerprint not in again["text"]
    assert telegram.answer_to(telegram.press(message["message_id"], data=approve))["text"] == NOT_OPEN  # the old button is dead
    assert state(cp, held.request_id) == "held"


def test_a_stored_request_that_no_longer_matches_itself_cannot_be_approved(cp, held, world, telegram, phone, db_path):
    phone()
    (message,) = on_screen(telegram)
    approve = buttons(message)["Approve"]
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE requests SET record = ? WHERE id = ?", (THIEF.canonical, held.request_id))
    answer = telegram.answer_to(telegram.press(message["message_id"], data=approve))
    assert not answer["text"].startswith("Approved")
    assert state(cp, held.request_id) != "approved"
    assert cp.run(held.request_id).status == "refused" and world.risky() == []


# ---- a tap is not a yes until there was time to read -------------------------------


def test_approve_too_soon_does_not_count_and_later_does(cp, held, world, telegram, phone):
    tick = Tick()
    phone(min_read_seconds=2, clock=tick)
    (message,) = on_screen(telegram)
    answer = telegram.answer_to(telegram.press(message["message_id"], "Approve"))
    assert answer["text"] == TOO_SOON and answer["show_alert"] is True
    assert state(cp, held.request_id) == "held"
    tick.now = 51.9
    assert telegram.answer_to(telegram.press(message["message_id"], "Approve"))["text"] == TOO_SOON
    assert state(cp, held.request_id) == "held" and world.risky() == []
    tick.now = 52.0
    assert telegram.answer_to(telegram.press(message["message_id"], "Approve"))["text"].startswith("Approved")
    assert state(cp, held.request_id) == "approved"


def test_deny_is_never_too_soon(cp, held, telegram, phone):
    phone(min_read_seconds=60, clock=Tick())
    (message,) = on_screen(telegram)
    assert telegram.answer_to(telegram.press(message["message_id"], "Deny"))["text"].startswith("Denied")
    assert state(cp, held.request_id) == "denied"


def test_the_default_is_two_seconds_to_read(cp, held, telegram):
    approver = TelegramApprover(cp, token=telegram.token, chat_id=OWNER, api=telegram.api)
    assert approver._min_read == 2.0 and approver._at_once == 3


# ---- many at once ------------------------------------------------------------------


def test_only_a_few_are_on_the_phone_at_a_time(cp, world, telegram, phone):
    made = [cp.request("pay", {"to": f"ACME-{number}", "amount": number}) for number in range(1, 11)]
    phone()
    on_screen(telegram, 3)
    time.sleep(0.2)
    first, second, third = telegram.with_buttons()
    assert len(telegram.messages) == 3
    assert [shown_preview(message) for message in (first, second, third)] == [decision.preview for decision in made[:3]]  # oldest first
    assert "9 more are waiting after this one." in first["text"]
    assert "7 more are waiting after this one." in third["text"]
    telegram.press(second["message_id"], "Deny")
    assert until(lambda: len(telegram.with_buttons()) == 3 and telegram.with_buttons()[-1]["message_id"] != third["message_id"])
    time.sleep(0.2)
    assert len(telegram.with_buttons()) == 3
    assert shown_preview(telegram.with_buttons()[-1]) == made[3].preview
    assert "6 more are waiting" in telegram.with_buttons()[-1]["text"]
    assert [state(cp, decision.request_id) for decision in made] == ["held", "denied"] + ["held"] * 8


def test_one_at_a_time_when_asked(cp, world, telegram, phone):
    first, second = cp.request("pay", {"to": "ACME-1", "amount": 1}), cp.request("pay", {"to": "ACME-2", "amount": 2})
    phone(at_once=1)
    (message,) = on_screen(telegram)
    time.sleep(0.2)
    assert len(telegram.with_buttons()) == 1 and "1 more is waiting after this one." in message["text"]
    assert shown_preview(message) == first.preview
    telegram.press(message["message_id"], "Approve")
    assert until(lambda: [sent for sent in telegram.with_buttons() if shown_preview(sent) == second.preview])
    assert "waiting after" not in telegram.with_buttons()[0]["text"]


# ---- long actions ------------------------------------------------------------------

LONG = {"to": "sam@example.com", "body": " ".join(f"line {number} of the long report" for number in range(400))}


def parts_needed(decision):
    return len(_parts(decision.preview, 0, 99)[0])


def test_a_long_preview_carries_on_in_the_next_message_and_all_of_it_is_there(cp, world, telegram, phone):
    decision = cp.request("send_email", dict(LONG))
    assert len(decision.preview) > 2 * MESSAGE_LIMIT
    phone()
    (last,) = on_screen(telegram)
    parts = [message for message in telegram.messages]
    assert len(parts) >= 3 and parts[-1] is last
    assert all(len(message["text"]) <= MESSAGE_LIMIT for message in parts)
    assert all(not message["reply_markup"] for message in parts[:-1])  # the buttons are under the last part only
    assert "\n".join(shown_preview(message) for message in parts) == decision.preview
    for number, message in enumerate(parts, 1):
        assert f"Part {number} of {len(parts)}." in message["text"]
    assert parts[0]["text"].startswith(FIRST_LINE) and FIRST_LINE not in parts[1]["text"]
    assert HOW_TO_PARTS in last["text"] and HOW_TO_PARTS not in parts[0]["text"] and not any(HOW_TO in message["text"] for message in parts)
    assert [marked(message, "bold") for message in parts] == [[FIRST_LINE + "\nsend_email"]] + [[]] * (len(parts) - 1)  # the headline is on the first part only
    assert [marked(message, "italic") for message in parts] == [[]] * (len(parts) - 1) + [[HOW_TO_PARTS]]
    assert HOW_TO_PARTS == "Approve runs exactly what is in the boxes of all the parts, once. Deny runs nothing."
    where = "The buttons are under the last part."
    assert all(where in message["text"] for message in parts[:-1]) and where not in last["text"]
    # A press on an earlier part does not count, even with the right data.
    assert telegram.answer_to(telegram.press(parts[0]["message_id"], data=buttons(last)["Approve"]))["text"] == NOT_OPEN
    assert state(cp, decision.request_id) == "held"
    assert telegram.answer_to(telegram.press(last["message_id"], "Approve"))["text"].startswith("Approved")


def test_an_action_too_long_to_read_on_a_phone_cannot_be_approved_there(cp, world, telegram, phone):
    decision = cp.request("send_email", dict(LONG))
    phone(max_parts=parts_needed(decision) - 1)
    (message,) = on_screen(telegram)
    assert len(telegram.messages) == 1 and len(message["text"]) <= MESSAGE_LIMIT
    assert list(buttons(message)) == ["Deny"]
    assert NOT_HERE in message["text"] and f"{len(decision.preview.splitlines())} lines long" in message["text"]
    assert marked(message, "bold") == [FIRST_LINE + "\nsend_email"] and marked(message, "italic") == [] and HOW_TO not in message["text"]
    assert decision.preview.startswith(shown_preview(message))
    forged = "a:" + buttons(message)["Deny"][2:]
    answer = telegram.answer_to(telegram.press(message["message_id"], data=forged))
    assert answer["text"] == NOT_HERE
    assert state(cp, decision.request_id) == "held" and world.risky() == []
    assert telegram.answer_to(telegram.press(message["message_id"], "Deny"))["text"].startswith("Denied")
    assert state(cp, decision.request_id) == "denied"


def test_an_action_of_exactly_the_most_parts_can_still_be_approved(cp, world, telegram, phone):
    decision = cp.request("send_email", dict(LONG))
    assert parts_needed(decision) >= 3
    phone(max_parts=parts_needed(decision))
    (last,) = on_screen(telegram)
    assert len(telegram.messages) == parts_needed(decision) and list(buttons(last)) == ["Approve", "Deny"]
    assert "\n".join(shown_preview(message) for message in telegram.messages) == decision.preview


def test_look_alike_letters_reach_the_phone_as_codes_with_the_warning(cp, world, telegram, phone):
    decision = cp.request("send_email", {"to": "sаm@example.com", "body": "hello"})  # a Cyrillic a
    phone()
    (message,) = on_screen(telegram)
    assert shown_preview(message) == decision.preview
    assert "а" not in message["text"] and "\\u{0430}" in message["text"]
    assert all(32 <= ord(letter) < 127 or letter == "\n" for letter in message["text"])


# ---- saying that Telegram has it ---------------------------------------------------


def test_the_owner_side_is_told_once_when_telegram_has_the_question(cp, held, world, telegram, phone):
    lines = []
    phone(sent=lines.append)
    on_screen(telegram)
    assert until(lambda: lines)
    time.sleep(0.2)
    assert lines == [f"kettle.telegram: send_email is with Telegram, on its way to your phone (fingerprint {held.fingerprint[:12]}...). Waiting for your answer."]
    assert lines == [SENT_NOTE.format(tool="send_email", start=held.fingerprint[:12])]
    assert held.fingerprint[:13] not in lines[0] and EMAIL["to"] not in lines[0] and EMAIL["body"] not in lines[0] and telegram.token not in lines[0]
    assert state(cp, held.request_id) == "held" and world.risky() == []  # being told is not an answer


def test_nothing_is_said_while_telegram_has_not_taken_the_question(cp, held, telegram, phone):
    lines = []
    telegram.fail(4, "sendMessage")
    phone(sent=lines.append)
    assert until(lambda: len(telegram.made("sendMessage")) >= 3)
    assert lines == [] and telegram.with_buttons() == []
    on_screen(telegram)
    assert until(lambda: len(lines) == 1)


def test_a_long_action_is_said_to_be_sent_only_when_its_last_part_is(cp, telegram, phone):
    decision = cp.request("send_email", dict(LONG))
    parts = parts_needed(decision)
    assert parts >= 3
    lines = []
    telegram.fail(3, "sendMessage", after=parts - 1)
    phone(sent=lines.append)
    assert until(lambda: len(telegram.made("sendMessage")) >= parts + 1)  # every part but the last is out, and the last was refused
    assert len(telegram.messages) == parts - 1 and lines == []
    on_screen(telegram)
    assert until(lambda: lines)
    time.sleep(0.2)
    assert lines == [SENT_NOTE.format(tool="send_email", start=decision.fingerprint[:12])]


def test_each_held_action_is_said_to_be_sent(cp, held, telegram, phone):
    other = cp.request("send_email", {"to": "kim@example.com", "body": "And you."})
    lines = []
    phone(sent=lines.append)
    on_screen(telegram, 2)
    assert until(lambda: len(lines) == 2)
    assert sorted(lines) == sorted(SENT_NOTE.format(tool="send_email", start=found.fingerprint[:12]) for found in (held, other))


def test_a_tool_name_that_is_not_short_and_plain_is_not_in_the_line_that_says_sent(cp, world, telegram, phone):
    cp.tool("wire \x1b[2J now", world.pay, level=NEEDS_YES)
    decision = cp.request("wire \x1b[2J now", {"to": "IE00 1234", "amount": 5})
    assert decision.status == "held"
    lines = []
    phone(sent=lines.append)
    on_screen(telegram)
    assert until(lambda: lines)
    assert lines == [SENT_NOTE.format(tool="an action", start=decision.fingerprint[:12])] and "\x1b" not in lines[0]


def test_a_sent_report_that_itself_fails_does_not_stop_the_approver(cp, held, world, telegram, phone):
    def broken(line):
        raise RuntimeError("the reporter is broken")

    approver = phone(sent=broken)
    (message,) = on_screen(telegram)
    settled(telegram, message["message_id"])
    time.sleep(0.1)
    assert approver.problems == [] and approver.last_error is None
    assert telegram.answer_to(telegram.press(message["message_id"], "Deny"))["text"].startswith("Denied")
    assert state(cp, held.request_id) == "denied" and world.risky() == []


def test_with_no_sent_given_nothing_is_printed(cp, held, telegram, phone, capsys):
    phone()
    (message,) = on_screen(telegram)
    settled(telegram, message["message_id"])
    time.sleep(0.1)
    printed = capsys.readouterr()
    assert printed.out == "" and printed.err == ""


# ---- when Telegram cannot be reached -----------------------------------------------


def test_a_failed_send_approves_nothing_and_is_sent_once_when_it_works_again(cp, held, world, telegram, phone):
    telegram.fail(4, "sendMessage")
    approver = phone()
    assert until(lambda: len(telegram.made("sendMessage")) >= 5)
    (message,) = on_screen(telegram)
    time.sleep(0.2)
    assert len(telegram.messages) == 1 and shown_preview(message) == held.preview
    assert state(cp, held.request_id) == "held" and world.risky() == []
    assert approver.problems and "500" in approver.problems[0] and "Nothing is approved" in approver.problems[0]
    assert len(approver.problems) == 1  # the same fault is reported once, not on every try


def test_a_send_that_fails_part_way_carries_on_from_where_it_stopped(cp, world, telegram, phone):
    decision = cp.request("send_email", dict(LONG))
    telegram.fail(3, "sendMessage", after=1)
    phone()
    (last,) = on_screen(telegram)
    time.sleep(0.2)
    assert "\n".join(shown_preview(message) for message in telegram.messages) == decision.preview  # no part twice, none missing
    assert all(not message["reply_markup"] for message in telegram.messages[:-1])
    assert state(cp, decision.request_id) == "held"


def test_a_failed_listen_approves_nothing_and_presses_count_once_it_works_again(cp, held, world, telegram, phone):
    telegram.fail(5, "getUpdates", code=502)
    approver = phone()
    (message,) = on_screen(telegram)
    query = telegram.press(message["message_id"], "Approve")
    assert telegram.answer_to(query)["text"].startswith("Approved")
    assert any("502" in line for line in approver.problems)
    assert state(cp, held.request_id) == "approved" and world.risky() == []


def test_when_the_answer_to_a_press_cannot_be_sent_the_yes_still_stands_and_the_buttons_come_off(cp, held, world, telegram, phone):
    approver = phone()
    (message,) = on_screen(telegram)
    telegram.fail(1, "answerCallbackQuery")
    telegram.press(message["message_id"], "Approve")
    assert until(lambda: state(cp, held.request_id) == "approved")
    assert until(lambda: telegram.with_buttons() == [])
    assert until(lambda: len(telegram.messages) == 2) and telegram.messages[-1]["text"].startswith("Approved")
    assert telegram.answers == [] and len(approver.problems) == 1 and "answerCallbackQuery" in approver.problems[0]


def test_an_answer_that_says_it_is_not_ok_is_a_fault(cp, held):
    server = _Recorder(200, body=b'{"ok": false, "result": {"message_id": 1}}')
    problems = []
    approver = TelegramApprover(cp, token="12345:a-token-for-the-not-ok-test", chat_id=OWNER, api=server.address, poll_seconds=0.02, long_poll_seconds=0, retry_seconds=0.02, problem=problems.append)
    approver.start()
    try:
        assert until(lambda: len(problems) >= 2)
        assert all("could not be read" in line for line in problems)
        assert state(cp, held.request_id) == "held"
    finally:
        approver.stop()
        server.close()


def test_an_answer_that_names_no_message_is_a_failed_send(cp, held, world, telegram, phone):
    telegram.fail(3, "sendMessage", code=200, said="not a message")  # it says ok, and gives no message
    approver = phone()
    assert until(lambda: approver.problems)
    assert "did not say which message" in approver.problems[0]
    (message,) = on_screen(telegram)
    assert len(telegram.messages) == 1 and state(cp, held.request_id) == "held"


def test_the_token_is_never_in_an_error_a_report_or_repr(cp, held, telegram, phone):
    token = telegram.token
    telegram.fail(2, "sendMessage", code=400, said=f"Bad Request: wrong path /bot{token}/sendMessage")
    telegram.fail(2, "getUpdates", code=500, said=f"https://api.telegram.org/bot{token}/getUpdates failed")
    approver = phone()
    on_screen(telegram)
    assert until(lambda: len(approver.problems) >= 2)
    telegram.close()
    assert until(lambda: any("could not be reached" in line for line in approver.problems))
    said = " ".join(approver.problems) + repr(approver) + str(approver) + str(approver.last_error)
    assert token not in said and token.split(":")[1] not in said
    assert "[token removed]" in said
    assert any("400" in line for line in approver.problems) and any("500" in line for line in approver.problems)


def test_a_wrong_token_approves_nothing_and_is_not_shown(cp, held, world, telegram, phone):
    wrong = "99999:not-the-token-the-pretend-telegram-knows"
    approver = phone(token=wrong)
    assert until(lambda: telegram.wrong_token >= 2)
    assert until(lambda: approver.last_error) and "401" in approver.last_error
    assert wrong not in " ".join(approver.problems) + approver.last_error
    assert telegram.messages == [] and state(cp, held.request_id) == "held"


def test_a_problem_report_that_itself_fails_does_not_stop_the_approver(cp, held, telegram):
    def broken(line):
        raise RuntimeError("the reporter is broken")

    telegram.fail(2, "sendMessage")
    approver = TelegramApprover(cp, token=telegram.token, chat_id=OWNER, api=telegram.api, min_read_seconds=0, poll_seconds=0.02, long_poll_seconds=1, retry_seconds=0.02, problem=broken)
    approver.start()
    try:
        (message,) = on_screen(telegram)
        assert telegram.answer_to(telegram.press(message["message_id"], "Deny"))["text"].startswith("Denied")
    finally:
        telegram.close()
        approver.stop()


class _Recorder:
    """A server on this machine that writes down what it is asked and answers with one fixed reply."""

    def __init__(self, code, headers=(), body=b""):
        self.asked = []
        recorder = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _any(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                recorder.asked.append((self.command, self.path))
                self.send_response(code)
                for name, value in headers:
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = _any

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.address = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.mark.parametrize("code", [301, 302, 303, 307])
def test_the_token_does_not_follow_a_redirect(cp, held, code):
    elsewhere = _Recorder(200)
    first = _Recorder(code, [("Location", elsewhere.address + "/somewhere-else")])
    problems = []
    approver = TelegramApprover(cp, token="12345:a-token-for-the-redirect-test", chat_id=OWNER, api=first.address, poll_seconds=0.02, long_poll_seconds=0, retry_seconds=0.02, problem=problems.append)
    approver.start()
    try:
        assert until(lambda: len(first.asked) >= 4)
        assert elsewhere.asked == []
        assert str(code) in approver.last_error and "a-token-for" not in " ".join(problems)
        assert state(cp, held.request_id) == "held"
    finally:
        approver.stop()
        first.close()
        elsewhere.close()


# ---- stopping ----------------------------------------------------------------------


def test_after_stop_nothing_is_sent_and_no_press_counts(cp, held, world, telegram, phone):
    approver = phone()
    (message,) = on_screen(telegram)
    approver.stop()
    assert "stopped" in repr(approver)
    telegram.press(message["message_id"], "Approve")
    other = cp.request("pay", {"to": "ACME-1", "amount": 5})
    time.sleep(0.3)
    assert len(telegram.messages) == 1 and telegram.answers == []
    assert state(cp, held.request_id) == "held" and state(cp, other.request_id) == "held"
    assert world.risky() == []


def test_start_twice_makes_one_approver_not_two(cp, held, telegram, phone):
    approver = phone()
    approver.start()
    approver.start()
    on_screen(telegram)
    time.sleep(0.2)
    assert len(telegram.messages) == 1
    assert "running" in repr(approver)


def test_starting_again_does_not_bring_old_buttons_back_to_life(cp, held, world, telegram, phone):
    approver = phone()
    (old,) = on_screen(telegram)
    old_buttons = buttons(old)
    approver.stop()
    pressed = telegram.press(old["message_id"], "Approve")  # pressed while nothing was listening
    approver.start()
    assert telegram.answer_to(pressed)["text"] == NOT_OPEN
    assert state(cp, held.request_id) == "held"
    new = until(lambda: [message for message in telegram.with_buttons() if message["message_id"] != old["message_id"]])
    assert new and not set(buttons(new[0]).values()) & set(old_buttons.values())
    assert telegram.answer_to(telegram.press(new[0]["message_id"], "Approve"))["text"].startswith("Approved")
    assert state(cp, held.request_id) == "approved" and world.risky() == []


def test_only_button_presses_are_asked_for(cp, held, telegram, phone):
    phone()
    on_screen(telegram)
    assert until(lambda: telegram.made("getUpdates"))
    assert all(call["allowed_updates"] == ["callback_query"] for call in telegram.made("getUpdates"))


def test_a_proxy_set_for_this_shell_is_not_used_for_the_pretend_telegram(cp, held, telegram, phone, monkeypatch):
    for name in ("http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")  # nothing listens there
    for name in ("no_proxy", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)
    approver = phone()
    on_screen(telegram)
    assert approver.problems == []


# ---- setting it up -----------------------------------------------------------------


@pytest.mark.parametrize("token", ["", "abc", "12345", "12345:", ":abc", "12345:ab/cd", "12345:ab cd", "12345:abc\n", "12345:abc?x=1", "12345:../../x", "x12345:abc", None, 12345, b"12345:abc"])
def test_a_token_of_the_wrong_shape_is_refused_and_not_repeated(cp, token):
    with pytest.raises(TelegramError) as caught:
        TelegramApprover(cp, token=token, chat_id=OWNER)
    assert "not the shape of a bot token" in str(caught.value)
    if token:
        assert str(token) not in str(caught.value)


@pytest.mark.parametrize("chat_id", [0, -1, -1001234567890, True, "424242", 4242.0, None])
def test_only_a_private_chat_can_be_the_owners_chat(cp, telegram, chat_id):
    with pytest.raises(TelegramError, match="private chat"):
        TelegramApprover(cp, token=telegram.token, chat_id=chat_id)


@pytest.mark.parametrize(
    "api",
    [
        "http://api.telegram.org",
        "http://example.com",
        "http://127.0.0.1.example.com",
        "http://localhost.example.com:8080",
        "ftp://127.0.0.1",
        "api.telegram.org",
        "",
        None,
        "https://",
        "https://user:secret@api.telegram.org",
        "https://api.telegram.org@example.com",
        "https://api.telegram.org/somewhere",
        "https://api.telegram.org?x=1",
        "https://api.telegram.org#x",
        "https://api.telegram.org:port",
        "file:///etc/passwd",
    ],
)
def test_the_api_address_must_be_https_or_this_machine(cp, telegram, api):
    with pytest.raises(TelegramError, match="api must"):
        TelegramApprover(cp, token=telegram.token, chat_id=OWNER, api=api)


@pytest.mark.parametrize("api", ["https://api.telegram.org", "https://api.telegram.org/", "https://my-own-bot-api.example.com:8443", "http://127.0.0.1:8081", "http://localhost:8081", "http://[::1]:8081"])
def test_api_addresses_that_are_taken(cp, telegram, api):
    approver = TelegramApprover(cp, token=telegram.token, chat_id=OWNER, api=api)
    assert approver._api == api.rstrip("/")


@pytest.mark.parametrize("setting", [dict(at_once=0), dict(at_once=True), dict(at_once=1.5), dict(min_read_seconds=-1), dict(min_read_seconds="2"), dict(max_parts=0), dict(approver=""), dict(approver=None)])
def test_settings_that_make_no_sense_are_refused(cp, telegram, setting):
    with pytest.raises(TelegramError):
        TelegramApprover(cp, token=telegram.token, chat_id=OWNER, api=telegram.api, **setting)


# ---- the pretend Telegram keeps to the real one's limits ---------------------------


def test_the_pretend_telegram_refuses_what_the_real_one_documents_as_too_long(telegram):
    assert telegram._sendMessage({"chat_id": OWNER, "text": "x" * MESSAGE_LIMIT})[0] == 200
    assert telegram._sendMessage({"chat_id": OWNER, "text": "x" * (MESSAGE_LIMIT + 1)})[0] == 400
    assert telegram._sendMessage({"chat_id": OWNER, "text": ""})[0] == 400
    assert telegram._sendMessage({"chat_id": OWNER, "text": "x", "parse_mode": "HTML"})[0] == 400
    assert telegram._sendMessage({"chat_id": OWNER, "text": "x", "entities": [{"type": "pre", "offset": 0, "length": 2}]})[0] == 400
    new_sign = "\U0001f195x"  # three places as Telegram counts them: the sign is two
    assert telegram._sendMessage({"chat_id": OWNER, "text": new_sign, "entities": [{"type": "bold", "offset": 2, "length": 1}]})[0] == 200
    assert telegram._sendMessage({"chat_id": OWNER, "text": new_sign, "entities": [{"type": "bold", "offset": 2, "length": 2}]})[0] == 400
    assert telegram._sendMessage({"chat_id": OWNER, "text": "\U0001f195" * (MESSAGE_LIMIT // 2)})[0] == 200
    assert telegram._sendMessage({"chat_id": OWNER, "text": "\U0001f195" * (MESSAGE_LIMIT // 2) + "x"})[0] == 400

    def keyboard(data):
        return {"inline_keyboard": [[{"text": "Approve", "callback_data": data}]]}

    assert telegram._sendMessage({"chat_id": OWNER, "text": "x", "reply_markup": keyboard("a" * DATA_LIMIT)})[0] == 200
    assert telegram._sendMessage({"chat_id": OWNER, "text": "x", "reply_markup": keyboard("a" * (DATA_LIMIT + 1))})[0] == 400
    assert telegram._sendMessage({"chat_id": OWNER, "text": "x", "reply_markup": keyboard("")})[0] == 400


# ---- finding your chat id: python -m kettle.telegram --------------------------------


class Screen:
    """What the command shows, and the person reading it: when the code comes up, `then` is called with it."""

    def __init__(self, then=None):
        self.lines, self.then, self.code = [], then, None

    def __call__(self, line=""):
        self.lines.append(line)
        found = re.search(r"send it this code: (.+)$", line)
        if found:
            self.code = found.group(1)
            if self.then:
                self.then(self.code)

    @property
    def text(self):
        return "\n".join(self.lines)


class Steps:
    """A clock that moves on one second each time it is read, so a wait ends without any real waiting."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 1.0
        return self.now


def other_code(code, step=1):
    return f"{(int(code) + step) % 10**CODE_DIGITS:0{CODE_DIGITS}d}"


def find(telegram, screen, **settings):
    wanted = dict(api=telegram.api, say=screen, wait_seconds=30, long_poll_seconds=0, clock=Steps())
    wanted.update(settings)
    return find_chat_id(telegram.token, **wanted)


def test_the_code_sent_in_your_own_chat_finds_it(telegram):
    screen = Screen(lambda code: telegram.say(code, from_id=OWNER))
    assert find(telegram, screen) == OWNER
    assert re.fullmatch(r"[0-9]{6}", screen.code)
    assert screen.lines[0] == "This token belongs to the bot @kettle_pretend_bot."
    assert screen.lines[1] == f"Open your chat with @kettle_pretend_bot in Telegram and send it this code: {screen.code}"
    assert telegram.token not in screen.text


def test_each_search_shows_a_new_code(telegram):
    codes = set()
    for _ in range(6):
        screen = Screen(lambda code: telegram.say(code, from_id=OWNER))
        find(telegram, screen)
        codes.add(screen.code)
    assert len(codes) > 1


def test_the_first_chat_to_write_is_not_taken_as_yours(telegram):
    def then(code):
        telegram.say("/start", from_id=SOMEONE_ELSE)
        for _ in range(WRONG_CODES + 1):  # ordinary messages are not wrong codes, however many there are
            telegram.say("hello, is this my bot?", from_id=SOMEONE_ELSE)
        telegram.say(code, from_id=OWNER)

    assert find(telegram, Screen(then)) == OWNER


def test_a_chat_that_never_sends_the_code_is_never_found(telegram):
    def then(code):
        telegram.say("/start", from_id=SOMEONE_ELSE)
        telegram.say(f"the code is {code}", from_id=SOMEONE_ELSE)
        telegram.say(code[:-1], from_id=SOMEONE_ELSE)
        telegram.say(code + "0", from_id=SOMEONE_ELSE)

    with pytest.raises(TelegramError, match="no message with the code came in time"):
        find(telegram, Screen(then))
    assert telegram.messages == []


def test_spaces_around_the_code_do_not_matter(telegram):
    assert find(telegram, Screen(lambda code: telegram.say(f"  {code} \n", from_id=OWNER))) == OWNER


def test_what_was_sent_before_the_code_was_shown_is_passed_over(telegram):
    for step in range(WRONG_CODES + 3):
        telegram.say(f"{step:0{CODE_DIGITS}d}", from_id=SOMEONE_ELSE)
    waiting_before = len(telegram._updates)

    def then(code):
        for step in range(1, WRONG_CODES):  # one short of too many: not one of the old messages may be counted
            telegram.say(other_code(code, step), from_id=SOMEONE_ELSE)
        telegram.say(code, from_id=OWNER)

    assert find(telegram, Screen(then)) == OWNER
    assert waiting_before == WRONG_CODES + 3 and telegram._updates == []


def test_a_few_wrong_codes_from_someone_else_do_not_stop_you(telegram):
    def then(code):
        for step in range(1, WRONG_CODES):
            telegram.say(other_code(code, step), from_id=SOMEONE_ELSE)
        telegram.say(code, from_id=OWNER)

    assert find(telegram, Screen(then)) == OWNER


def test_too_many_wrong_codes_stop_the_search(telegram):
    """Nobody gets to keep guessing: after five wrong codes even the right one is not taken."""

    def then(code):
        for step in range(1, WRONG_CODES + 1):
            telegram.say(other_code(code, step), from_id=SOMEONE_ELSE)
        telegram.say(code, from_id=SOMEONE_ELSE)

    with pytest.raises(TelegramError, match="5 wrong codes were sent"):
        find(telegram, Screen(then))
    assert telegram.messages == []


def test_a_code_sent_in_a_group_is_no_longer_good(telegram):
    def then(code):
        telegram.say(code, from_id=OWNER, chat_id=-1001234567890)
        telegram.say(code, from_id=OWNER)

    with pytest.raises(TelegramError, match="sent in a group"):
        find(telegram, Screen(then))
    assert telegram.messages == []


@pytest.mark.parametrize(
    "sender, chat",
    [
        ({"id": SOMEONE_ELSE}, {"id": OWNER, "type": "private"}),
        ({"id": OWNER}, {"id": OWNER, "type": "group"}),
        ({"id": OWNER}, {"id": OWNER, "type": "supergroup"}),
        ({"id": OWNER}, {"id": OWNER}),
        ({"id": -5}, {"id": -5, "type": "private"}),
        ({"id": 0}, {"id": 0, "type": "private"}),
        ({"id": str(OWNER)}, {"id": str(OWNER), "type": "private"}),
        ({"id": True}, {"id": True, "type": "private"}),
        ({"id": float(OWNER)}, {"id": float(OWNER), "type": "private"}),
        (None, {"id": OWNER, "type": "private"}),
        ({"id": OWNER}, None),
        ("someone", "somewhere"),
    ],
)
def test_the_right_code_from_anywhere_but_a_private_chat_of_its_sender_finds_nothing(telegram, sender, chat):
    def then(code):
        message = {"message_id": 1, "date": 0, "text": code}
        message.update({key: value for key, value in (("from", sender), ("chat", chat)) if value is not None})
        telegram.hand_over({"message": message})

    with pytest.raises(TelegramError, match="sent in a group"):
        find(telegram, Screen(then))
    assert telegram.messages == []


def test_updates_of_any_other_shape_are_passed_over(telegram):
    def then(code):
        telegram.hand_over({"message": "not a message"})
        telegram.hand_over({"message": {"text": int(code)}})
        telegram.hand_over({"message": {"text": None, "from": {"id": OWNER}, "chat": {"id": OWNER, "type": "private"}}})
        telegram.hand_over({"edited_message": {"text": code, "from": {"id": SOMEONE_ELSE}, "chat": {"id": SOMEONE_ELSE, "type": "private"}}})
        telegram.hand_over({"callback_query": {"id": "1", "from": {"id": SOMEONE_ELSE}, "data": code}})
        telegram.hand_over({})
        telegram.say(code, from_id=OWNER)

    assert find(telegram, Screen(then)) == OWNER


def test_only_typed_messages_are_asked_for_and_the_code_is_not_left_waiting(telegram):
    """The approver asks Telegram for button presses only. This asks for messages only, every time, and says so each time."""
    screen = Screen(lambda code: telegram.say(code, from_id=OWNER))
    assert find(telegram, screen) == OWNER
    asked = telegram.made("getUpdates")
    assert len(asked) >= 3 and all(body["allowed_updates"] == ["message"] for body in asked)
    assert asked[-1]["offset"] == telegram._ids["update"] + 1 and asked[-1]["timeout"] == 0
    assert telegram._updates == []


def test_the_chat_is_told_it_was_found(telegram):
    assert find(telegram, Screen(lambda code: telegram.say(code, from_id=OWNER))) == OWNER
    (message,) = telegram.messages
    assert (message["chat_id"], message["text"], message["reply_markup"]) == (OWNER, FOUND_NOTE, None)


def test_a_fault_after_the_chat_is_found_changes_nothing(telegram):
    def then(code):
        telegram.say(code, from_id=OWNER)
        telegram.fail(times=5, method="getUpdates", after=1)  # the call that reads the code goes through; the one after it does not
        telegram.fail(times=5, method="sendMessage")

    assert find(telegram, Screen(then)) == OWNER
    assert telegram.messages == []


def test_nothing_is_shown_for_a_token_telegram_does_not_know(telegram):
    screen = Screen()
    other = "1234567890:another-token-of-the-right-shape"
    with pytest.raises(TelegramError, match=r"Telegram refused getMe \(401: Unauthorized\)") as caught:
        find_chat_id(other, api=telegram.api, say=screen)
    assert screen.lines == [] and other not in str(caught.value) and telegram.calls == []


@pytest.mark.parametrize("token", ["", "not a token", "1234567890", None, 1234567890])
def test_a_token_of_the_wrong_shape_is_not_sent_and_not_repeated(telegram, token):
    screen = Screen()
    with pytest.raises(TelegramError, match="not the shape of a bot token") as caught:
        find_chat_id(token, api=telegram.api, say=screen)
    assert screen.lines == [] and telegram.calls == [] and telegram.wrong_token == 0
    assert not token or str(token) not in str(caught.value)


@pytest.mark.parametrize("username", [None, "", "two words", "line\nbreak", "x" * 65, 12345])
def test_a_bot_name_that_is_not_a_bot_name_is_not_shown(telegram, username):
    telegram.username = username
    screen = Screen()
    with pytest.raises(TelegramError, match="did not say which bot"):
        find(telegram, screen)
    assert screen.lines == []


def test_a_fault_while_waiting_ends_the_search_with_telegrams_reason(telegram):
    said = "Conflict: terminated by other getUpdates request; make sure that only one bot instance is running"
    screen = Screen(lambda code: telegram.fail(method="getUpdates", code=409, said=said))
    with pytest.raises(TelegramError, match="409: Conflict") as caught:
        find(telegram, screen)
    assert telegram.token not in str(caught.value)


def test_the_search_ends_at_the_time_limit(telegram):
    clock = Steps()
    screen = Screen()
    with pytest.raises(TelegramError, match="no message with the code came in time"):
        find(telegram, screen, wait_seconds=4, clock=clock)
    assert clock.now == 5.0  # read once to set the limit, then once a round until the 4 seconds are gone
    assert screen.lines[2] == "Waiting up to 4 seconds. Only that code, sent in a private chat, counts."
    telegram.say(screen.code, from_id=OWNER)  # too late: nothing is listening any more
    assert telegram.messages == []


def test_a_wait_on_telegram_does_not_run_far_past_the_time_limit(telegram):
    started = time.monotonic()
    with pytest.raises(TelegramError, match="in time"):
        find_chat_id(telegram.token, api=telegram.api, say=Screen(), wait_seconds=1.5, long_poll_seconds=8)
    assert 1.4 < time.monotonic() - started < 5
    assert [body["timeout"] for body in telegram.made("getUpdates")] == [0, 1, 1]


@pytest.mark.parametrize("wait_seconds", [0, -1, True, "120", None])
def test_a_time_limit_that_makes_no_sense_is_refused(telegram, wait_seconds):
    with pytest.raises(TelegramError, match="wait_seconds"):
        find_chat_id(telegram.token, api=telegram.api, say=Screen(), wait_seconds=wait_seconds)
    assert telegram.calls == []


def test_the_search_goes_only_where_the_approver_would(telegram):
    with pytest.raises(TelegramError, match="api must"):
        find_chat_id(telegram.token, api="http://example.com", say=Screen())


def test_the_command_prints_the_chat_id_and_the_next_step(telegram):
    screen = Screen(lambda code: telegram.say(code, from_id=OWNER))
    assert main([], environ={TOKEN_NAME: f"  {telegram.token}\n"}, api=telegram.api, say=screen, wait_seconds=30) == 0
    assert screen.lines[3:] == [
        "",
        "Your chat id is 424242",
        "",
        "Next step: give that number to the approver in your agent's code.",
        "",
        '    approver = TelegramApprover(cp, token=os.environ["KETTLE_TELEGRAM_TOKEN"], chat_id=424242)',
        "",
        "Only a button pressed in that chat will count as an answer.",
    ]
    assert telegram.token not in screen.text


def test_the_printed_next_step_makes_an_approver_for_that_chat(cp, telegram):
    screen = Screen(lambda code: telegram.say(code, from_id=OWNER))
    environ = {TOKEN_NAME: telegram.token}
    assert main([], environ=environ, api=telegram.api, say=screen, wait_seconds=30) == 0
    (line,) = [line for line in screen.lines if "TelegramApprover(" in line]
    names = {"TelegramApprover": TelegramApprover, "cp": cp, "os": type("os", (), {"environ": environ})}
    exec(line.strip(), names)
    assert names["approver"]._chat_id == OWNER and names["approver"]._token == telegram.token


@pytest.mark.parametrize("environ", [{}, {TOKEN_NAME: ""}, {TOKEN_NAME: "   "}, {"TELEGRAM_TOKEN": "1234567890:in-some-other-name"}])
def test_with_no_token_the_command_says_how_to_give_one_and_calls_nothing(telegram, environ):
    screen = Screen()
    assert main([], environ=environ, api=telegram.api, say=screen) == 2
    assert screen.lines == [NO_TOKEN] and "read -s KETTLE_TELEGRAM_TOKEN && export KETTLE_TELEGRAM_TOKEN" in NO_TOKEN
    assert telegram.calls == [] and telegram.wrong_token == 0


@pytest.mark.parametrize("argv", [["--token", "1234567890:given-on-the-command-line"], ["1234567890:given-on-the-command-line"], ["--help"], [""]])
def test_the_command_takes_no_arguments_so_a_token_cannot_be_typed_where_the_shell_keeps_it(telegram, argv):
    screen = Screen()
    assert main(argv, environ={TOKEN_NAME: telegram.token}, api=telegram.api, say=screen, wait_seconds=1) == 2
    assert screen.lines == [USAGE]
    assert telegram.calls == [] and telegram.wrong_token == 0


def test_the_command_says_why_no_chat_was_found_without_the_token(telegram):
    wrong_shape, unknown = "my-bot-token", "1234567890:another-token-of-the-right-shape"
    screen = Screen()
    assert main([], environ={TOKEN_NAME: wrong_shape}, api=telegram.api, say=screen) == 1
    assert screen.lines == ["No chat id: that is not the shape of a bot token (the value given is not shown)."]
    screen = Screen()
    assert main([], environ={TOKEN_NAME: unknown}, api=telegram.api, say=screen) == 1
    assert screen.lines == ["No chat id: Telegram refused getMe (401: Unauthorized)."]
    screen = Screen()
    assert main([], environ={TOKEN_NAME: telegram.token}, api=telegram.api, say=screen, wait_seconds=1) == 1
    assert screen.lines[3:] == ["No chat id: no message with the code came in time."] and telegram.token not in screen.text


def run_the_command(*arguments):
    """Run python -m kettle.telegram for real, with no token anywhere near it, so it can only stop before any call."""
    environ = {"PYTHONPATH": os.path.dirname(os.path.dirname(kettle.__file__))}
    return subprocess.run([sys.executable, "-m", "kettle.telegram", *arguments], env=environ, capture_output=True, text=True, timeout=60)


def test_the_command_runs_as_python_m_kettle_telegram():
    done = run_the_command()
    assert (done.returncode, done.stdout, done.stderr) == (2, NO_TOKEN + "\n", "")
    done = run_the_command("--token", "1234567890:given-on-the-command-line")
    assert (done.returncode, done.stdout, done.stderr) == (2, USAGE + "\n", "")
