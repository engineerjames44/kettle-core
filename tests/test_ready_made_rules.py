"""The ready-made rules: what runs without asking, what asks, what is never allowed, and what each rule says about why.

tests/test_rules_set.py tries the long list of tricks against the real checkpoint.
These tests are about the rules themselves: how they are set up, how they decide,
what they say, and what each check finds and misses.
"""

import random
import re

import pytest

from kettle import FREE, NEEDS_YES, NEVER, Checkpoint, rules
from kettle.checkpoint import HELD, RAN, REFUSED
from kettle.checkpoint.rules import RulesError
from kettle.rules import MAX_REASONS, Rule, Verdict, hidden, sensitive

ME, SAM, PRIYA = "alex@example.com", "sam@example.com", "priya@example.com"
THIEF = "thief@example.net"
CATERING, LENA = "BRIGHTSIDE-CATERING-4410", "LENA-FISCHER-5526"
KEY = "sk-" + "ant-" + "a1B2c3D4e5F6g7H8i9J0" * 2


@pytest.fixture
def email():
    return rules.email(contacts=[SAM, PRIYA], me=[ME], blocked=["old-scam@example.net", "@blocked.example"])


@pytest.fixture
def pay():
    return rules.payment(payees=[CATERING, LENA], limit=200, ceiling=5000)


def note(to=SAM, **more):
    return {"to": to, "body": "See you at 3.", **more}


def reasons(rule, inputs):
    return list(rule.explain(inputs).reasons)


# ---- a rule and the checkpoint ---------------------------------------------------------


class Desk:
    def __init__(self):
        self.sent = []

    def send_email(self, to, body, cc=None):
        self.sent.append(to)
        return "sent"


@pytest.fixture
def desk():
    return Desk()


@pytest.fixture
def cp(db_path, clock, desk, email):
    checkpoint = Checkpoint(db_path, clock=clock)
    checkpoint.tool("send_email", desk.send_email, level=email, describe=email.why, watch=["to"])
    yield checkpoint
    checkpoint.close()


def test_an_email_to_a_contact_runs_and_one_to_anyone_else_waits_for_a_yes(cp, desk):
    assert cp.request("send_email", note()).status == RAN
    assert desk.sent == [SAM]
    held = cp.request("send_email", note(THIEF))
    assert held.status == HELD and desk.sent == [SAM]
    assert cp.request("send_email", note("old-scam@example.net")).status == REFUSED
    assert desk.sent == [SAM]
    cp.approve(held.request_id, held.fingerprint, "the owner")
    assert cp.run(held.request_id).status == RAN and desk.sent == [SAM, THIEF]


def test_the_approval_says_why_it_is_asking(cp):
    held = cp.request("send_email", note(THIEF))
    assert f'Summary (written by the app): "Asks because: {THIEF} is not' in held.preview
    assert "in your contacts" in held.preview


def test_a_rule_gives_the_plain_level_text_the_checkpoint_takes(email, pay):
    for answer in (email(note()), email(note(THIEF)), email(note("x@blocked.example")), pay({"to": LENA, "amount": 6000})):
        assert type(answer) is str
    assert (email(note()), email(note(THIEF)), email(note("x@blocked.example"))) == (FREE, NEEDS_YES, NEVER)


def digest_with(db_path, clock, rule):
    checkpoint = Checkpoint(db_path, clock=clock)
    try:
        checkpoint.tool("send_email", lambda to, body: "sent", level=rule)
        return checkpoint.rules_digest()
    finally:
        checkpoint.close()


def test_a_changed_setting_changes_the_rules_digest(tmp_path, clock):
    """The checkpoint writes a rule function into its digest by name only. A ready-made rule carries its settings in that name."""

    def digest(name, **settings):
        made = rules.email(**{"contacts": [SAM, PRIYA], "me": [ME], **settings})
        return digest_with(str(tmp_path / f"{name}.db"), clock, made)

    first = digest("a")
    assert digest("b") == first
    assert digest("c", contacts=[PRIYA, SAM.upper()]) == first  # the order and the capitals are not a setting
    changed = [
        digest("d", contacts=[SAM, PRIYA, THIEF]),
        digest("e", contacts=[SAM]),
        digest("f", me=[]),
        digest("g", blocked=[THIEF]),
        digest("h", own_domains=["example.com"]),
        digest("i", max_recipients=4),
        digest("j", cc="copy_to"),
    ]
    assert first not in changed and len(set(changed)) == len(changed)


def test_the_two_kinds_of_rule_never_share_a_name(pay, email):
    assert email.__qualname__.startswith("kettle.rules.email:") and pay.__qualname__.startswith("kettle.rules.payment:")
    assert re.fullmatch(r"kettle\.rules\.payment:[0-9a-f]{12}", pay.__qualname__)
    other = rules.payment(payees=[CATERING, LENA], limit=200.01, ceiling=5000)
    assert other.__qualname__ != pay.__qualname__
    assert rules.payment(payees=[LENA, CATERING], limit=200, ceiling=5000).__qualname__ == pay.__qualname__
    assert rules.payment(payees={LENA: "1"}, limit=200).__qualname__ != rules.payment(payees={LENA: "2"}, limit=200).__qualname__


def test_a_rule_cannot_be_changed_once_it_is_made(email, pay):
    for change in (
        lambda: setattr(email, "_contacts", frozenset([THIEF])),
        lambda: setattr(email, "_max", 100),
        lambda: setattr(pay, "_limit", 10**9),
        lambda: setattr(email, "__qualname__", "kettle.rules.email:000000000000"),
        lambda: setattr(email, "anything", 1),
        lambda: delattr(email, "_blocked"),
        lambda: delattr(pay, "_ceiling"),
    ):
        with pytest.raises(AttributeError, match="make a new rule to change them"):
            change()
    assert email(note(THIEF)) == NEEDS_YES and email(note("x@blocked.example")) == NEVER
    assert pay({"to": LENA, "amount": 201}) == NEEDS_YES and pay({"to": LENA, "amount": 5001}) == NEVER


def test_the_lists_are_copied_when_the_rule_is_made():
    contacts, me, blocked, payees, accounts = [SAM], [ME], [], [LENA], {LENA: "IE01"}
    email = rules.email(contacts=contacts, me=me, blocked=blocked)
    pay, supplier = rules.payment(payees=payees, limit=200), rules.payment(payees=accounts, limit=200)
    contacts.append(THIEF), me.append(THIEF), blocked.append(SAM), payees.append("THIEF-1"), accounts.update({LENA: "GB99", "THIEF-1": "GB99"})
    assert email(note(THIEF)) == NEEDS_YES and email(note()) == FREE
    assert email(note(ME, attachments=["a.pdf"])) == FREE and email(note(THIEF, attachments=["a.pdf"])) == NEEDS_YES
    assert pay({"to": "THIEF-1", "amount": 5}) == NEEDS_YES
    assert supplier({"to": LENA, "account": "GB99", "amount": 5}) == NEEDS_YES and supplier({"to": LENA, "account": "IE01", "amount": 5}) == FREE


def test_settings_gives_a_copy(email, pay):
    told = email.settings()
    assert told == {
        "contacts": [PRIYA, SAM],
        "me": [ME],
        "blocked": ["@blocked.example", "old-scam@example.net"],
        "own_domains": [],
        "max_recipients": 3,
        "fields": {"to": "to", "cc": "cc", "bcc": "bcc", "subject": "subject", "body": "body", "attachments": "attachments"},
    }
    told["contacts"].append(THIEF)
    assert email.settings()["contacts"] == [PRIYA, SAM] and email(note(THIEF)) == NEEDS_YES
    assert pay.settings() == {
        "payees": [CATERING, LENA],
        "limit": "200",
        "ceiling": "5000",
        "currencies": None,
        "fields": {"to": "to", "amount": "amount", "account": "account", "currency": "currency", "note": "note"},
    }


class Made(Rule):
    """A rule that finds whatever it is told to, to try what every rule does with what it finds."""

    kind = "made"

    def __init__(self, found):
        object.__setattr__(self, "_found", found)
        super().__init__({})

    def _look(self, inputs):
        if self._found == "crash":
            raise ValueError("no")
        return list(self._found)


def test_the_strictest_answer_wins_and_only_its_reasons_are_given():
    assert Made([]).explain({}) == Verdict(FREE, ())
    assert Made([(NEEDS_YES, "a"), (FREE, "fine")]).explain({}) == Verdict(NEEDS_YES, ("a",))
    assert Made([(NEEDS_YES, "a"), (NEVER, "b"), (NEEDS_YES, "c"), (NEVER, "d")]).explain({}) == Verdict(NEVER, ("b", "d"))
    assert Made([(NEVER, "b"), (NEEDS_YES, "a")]).explain({}) == Verdict(NEVER, ("b",))
    assert Made([(NEEDS_YES, "a"), (NEEDS_YES, "a"), (NEEDS_YES, "b"), (NEEDS_YES, "a")]).explain({}).reasons == ("a", "b")
    assert Made([(NEVER, "b"), (NEEDS_YES, "a")])({}) == NEVER and Made([(NEEDS_YES, "a")])({}) == NEEDS_YES and Made([])({}) == FREE


def test_why_is_one_line_and_counts_the_reasons_it_leaves_out():
    assert Made([]).why({}) == "Runs without asking: nothing unusual was found"
    assert Made([(NEEDS_YES, "a"), (NEEDS_YES, "b")]).why({}) == "Asks because: a; b"
    assert Made([(NEVER, "b"), (NEEDS_YES, "a")]).why({}) == "Never allowed: b"
    assert MAX_REASONS == 4
    assert Made([(NEEDS_YES, letter) for letter in "abcd"]).why({}) == "Asks because: a; b; c; d"
    assert Made([(NEEDS_YES, letter) for letter in "abcdefg"]).why({}) == "Asks because: a; b; c; d; and 3 more"


@pytest.mark.parametrize("inputs", [None, [], "to", 3, (("to", SAM),)])
def test_inputs_that_are_not_a_dict_ask(email, pay, inputs):
    for rule in (email, pay, Made([])):
        assert rule.explain(inputs) == Verdict(NEEDS_YES, ("the inputs cannot be read",))


def test_a_rule_that_crashes_is_refused_by_the_checkpoint(db_path, clock, desk):
    checkpoint = Checkpoint(db_path, clock=clock)
    try:
        checkpoint.tool("send_email", desk.send_email, level=Made("crash"))
        decision = checkpoint.request("send_email", note())
        assert decision.status == REFUSED and "ValueError" in decision.reason and desk.sent == []
    finally:
        checkpoint.close()


# ---- setting up ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "settings, words",
    [
        ({"contacts": SAM}, "contacts must be a list of addresses, given as the list itself"),
        ({"contacts": lambda: [SAM]}, "contacts must be a list of addresses, given as the list itself"),
        ({"contacts": {SAM: True}}, "contacts must be a list of addresses, given as the list itself"),
        ({"contacts": iter([SAM])}, "contacts must be a list of addresses, given as the list itself"),
        ({"contacts": [SAM, 7]}, "contacts must hold addresses as text"),
        ({"contacts": ["Sam Keane"]}, "contacts: 'Sam Keane' is not an email address"),
        ({"contacts": [f"Sam <{SAM}>"]}, "is not an email address"),
        ({"contacts": [f"{SAM}, {PRIYA}"]}, "is not an email address"),
        ({"contacts": ["@example.com"]}, "contacts: '@example.com' is not an email address"),
        ({"contacts": [SAM], "me": ME}, "me must be a list of addresses, given as the list itself"),
        ({"contacts": [SAM], "me": ["@example.com"]}, "is not an email address"),
        ({"contacts": [SAM], "blocked": "@example.net"}, "blocked must be a list of addresses, given as the list itself"),
        ({"contacts": [SAM], "blocked": ["example.net"]}, "blocked: 'example.net' is not an email address"),
        ({"contacts": [SAM], "blocked": [SAM.upper()]}, f"{SAM} is in blocked and also in contacts or me"),
        ({"contacts": [SAM], "me": [ME], "blocked": [ME]}, f"{ME} is in blocked and also in contacts or me"),
        ({"contacts": [SAM], "own_domains": "example.com"}, "own_domains must be a list of domains, given as the list itself"),
        ({"contacts": [SAM], "own_domains": ["example"]}, "own_domains: 'example' is not a domain, such as example.com"),
        ({"contacts": [SAM], "own_domains": [ME]}, "is not a domain"),
        ({"contacts": [SAM], "max_recipients": 0}, "max_recipients must be a whole number, 1 or more"),
        ({"contacts": [SAM], "max_recipients": True}, "max_recipients must be a whole number, 1 or more"),
        ({"contacts": [SAM], "max_recipients": 2.0}, "max_recipients must be a whole number, 1 or more"),
        ({"contacts": [SAM], "to": ""}, "to must be the name of an input, as text"),
        ({"contacts": [SAM], "body": None}, "body must be the name of an input, as text"),
        ({"contacts": [SAM], "cc": "to"}, "two of the input names given are the same"),
    ],
)
def test_an_email_rule_set_up_wrongly_is_refused_at_once(settings, words):
    with pytest.raises(RulesError, match=re.escape(words)):
        rules.email(**settings)


@pytest.mark.parametrize(
    "settings, words",
    [
        ({"payees": LENA, "limit": 200}, "payees must be a list, or a dict of name to account, given as the thing itself"),
        ({"payees": lambda: [LENA], "limit": 200}, "payees must be a list, or a dict of name to account"),
        ({"payees": [LENA, ""], "limit": 200}, "payees must hold names or account numbers as text"),
        ({"payees": [LENA, 5526], "limit": 200}, "payees must hold names or account numbers as text"),
        ({"payees": {LENA: 5526}, "limit": 200}, "payees as a dict must map each payee's name to its account, both as text"),
        ({"payees": {LENA: ""}, "limit": 200}, "payees as a dict must map each payee's name to its account, both as text"),
        ({"payees": [LENA], "limit": 0}, "limit must be a number above 0"),
        ({"payees": [LENA], "limit": -200}, "limit must be a number above 0"),
        ({"payees": [LENA], "limit": "200"}, "limit must be a number above 0"),
        ({"payees": [LENA], "limit": True}, "limit must be a number above 0"),
        ({"payees": [LENA], "limit": None}, "limit must be a number above 0"),
        ({"payees": [LENA], "limit": float("inf")}, "limit must be a number above 0"),
        ({"payees": [LENA], "limit": float("nan")}, "limit must be a number above 0"),
        ({"payees": [LENA], "limit": 200, "ceiling": 0}, "ceiling must be a number above 0"),
        ({"payees": [LENA], "limit": 200, "ceiling": 199.99}, "ceiling must not be below limit"),
        ({"payees": [LENA], "limit": 200, "currencies": "EUR"}, "currencies must be a list of currency codes as text"),
        ({"payees": [LENA], "limit": 200, "currencies": []}, "currencies must be a list of currency codes as text"),
        ({"payees": [LENA], "limit": 200, "currencies": ["EUR", 978]}, "currencies must be a list of currency codes as text"),
        ({"payees": [LENA], "limit": 200, "amount": "to"}, "two of the input names given are the same"),
        ({"payees": [LENA], "limit": 200, "note": 3}, "note must be the name of an input, as text"),
    ],
)
def test_a_payment_rule_set_up_wrongly_is_refused_at_once(settings, words):
    with pytest.raises(RulesError, match=re.escape(words)):
        rules.payment(**settings)


def test_a_payment_rule_needs_a_limit():
    with pytest.raises(TypeError):
        rules.payment(payees=[LENA])


def test_lists_may_be_given_as_a_list_a_tuple_or_a_set():
    for kind in (list, tuple, set, frozenset):
        email = rules.email(contacts=kind([SAM]), me=kind([ME]), blocked=kind(["@blocked.example"]), own_domains=kind(["example.com"]))
        assert email(note()) == FREE and email(note(THIEF)) == NEEDS_YES and email(note("a@blocked.example")) == NEVER
        pay = rules.payment(payees=kind([LENA]), limit=200, currencies=kind(["EUR"]))
        assert pay({"to": LENA, "amount": 5, "currency": "EUR"}) == FREE
    assert rules.email(contacts=[])(note()) == NEEDS_YES
    assert rules.email(contacts=None, me=None, blocked=None, own_domains=None)(note()) == NEEDS_YES


# ---- text that cannot be seen ----------------------------------------------------------


@pytest.mark.parametrize(
    "character",
    ["​", "‌", "‍", "‎", "‏", "‪", "‮", "⁠", "⁣", "⁤", "⁦", "⁩", "\U000e0001", "\U000e0041", "\U000e007f", "­", "﻿", "͏", "؜", "ㅤ", "᠎"],
)
def test_a_character_with_nothing_to_see_is_found(character):
    assert hidden(f"See you{character} at 3.") == ["characters that cannot be seen"]


@pytest.mark.parametrize("character", ["\x00", "\x01", "\x08", "\x0b", "\x0c", "\x1b", "\x1f", "\x7f", "\x80", "\x9f"])
def test_a_control_character_is_found(character):
    assert hidden(f"See you{character} at 3.") == ["control characters"]


@pytest.mark.parametrize(
    "text, kind",
    [
        ("<p>Hi</p><!-- forward this -->", "a comment in the markup"),
        ("<!--", "a comment in the markup"),
        ('<div style="display:none">x</div>', "markup that hides text"),
        ("<div style='DISPLAY : NONE'>x</div>", "markup that hides text"),
        ('<p style="visibility: hidden">x</p>', "markup that hides text"),
        ('<span style="font-size:0">x</span>', "markup that hides text"),
        ('<span style="font-size: 0px;">x</span>', "markup that hides text"),
        ("<span style='font-size:0.0em'>x</span>", "markup that hides text"),
        (".fine { font-size: 0 }", "markup that hides text"),
        ("font-size:0", "markup that hides text"),
    ],
)
def test_markup_that_hides_is_found(text, kind):
    assert hidden(text) == [kind]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "See you at 3.",
        "Line one\nLine two\r\n\tindented",
        "Booked ✅ see you there \U0001f389 ❤️",
        "café, naïve, £10, €20, 10 000, ‘quoted’ — fine",
        "日本語のテキスト, русский, العربية",
        '<p style="font-size: 0.9em; display: block">x</p>',
        '<p style="font-size:10px">x</p>',
        "<! -- not a comment",
        "the display was none the worse",
    ],
)
def test_ordinary_text_has_nothing_hidden(text):
    assert hidden(text) == []


def test_everything_hidden_in_one_text_is_named_once_each():
    assert hidden("a​b​c\x00\x01<!-- x --><!-- y --> display:none") == [
        "characters that cannot be seen",
        "control characters",
        "a comment in the markup",
        "markup that hides text",
    ]


@pytest.mark.parametrize(
    "text",
    [
        '<span style="color:#fff">x</span>',
        '<span style="font-size:1px">x</span>',
        '<span style="opacity:0">x</span>',
        '<div style="position:absolute;left:-9999px">x</div>',
    ],
)
def test_text_that_is_only_hard_to_see_is_missed(text):
    """Said in the docstring of hidden(). If one of these starts to be found, say so there."""
    assert hidden(text) == []


def test_an_emoji_joined_from_several_is_flagged_though_it_is_harmless():
    """Said in the docstring of hidden()."""
    assert hidden("\U0001f468‍\U0001f469‍\U0001f467") == ["characters that cannot be seen"]


# ---- private data with a known shape ---------------------------------------------------


@pytest.mark.parametrize(
    "text, kind",
    [
        ("4111 1111 1111 1111", "a card number"),
        ("4111-1111-1111-1111", "a card number"),
        ("card 4111111111111111.", "a card number"),
        ("5555555555554444", "a card number"),
        ("378282246310005", "a card number"),
        ("amex 3782 822463 10005 exp 04/29", "a card number"),
        ("4222222222222", "a card number"),
        (KEY, "a key or token"),
        ("gh" + "p_" + "a1B2c3D4e5F6g7H8i9J0a1B2c3D4e5F6g7H8", "a key or token"),
        ("github_" + "pat_" + "11ABCDEFG0abcdefghijkl_mnopqrstuv", "a key or token"),
        ("AK" + "IA" + "ABCDEFGHIJKLMNOP", "a key or token"),
        ("AI" + "za" + "SyA1B2c3D4e5F6g7H8i9J0a1B2c3D4e5F6", "a key or token"),
        ("xo" + "xb-" + "123456789012-abcdefghijkl", "a key or token"),
        ("ey" + "JhbGciOiJIUzI1NiJ9." + "ey" + "JzdWIiOiIxMjM0NTY3ODkwIn0." + "SflKxwRJSMeKKF2QT4", "a key or token"),
        ("123456789:" + "AAH" + "a1B2c3D4e5F6g7H8i9J0a1B2c3D4e5F6", "a key or token"),
        ("-----BEGIN " + "PRIVATE KEY-----", "a key or token"),
        ("-----BEGIN RSA " + "PRIVATE KEY-----", "a key or token"),
        ("-----BEGIN OPENSSH " + "PRIVATE KEY-----", "a key or token"),
        ("The wifi password is harbour-hall-2026", "a password"),
        ("password: hunter2", "a password"),
        ("Password=hunter2", "a password"),
        ("passwd : hunter2", "a password"),
        ("the passphrase is correct horse", "a password"),
        ("passcode: 9921", "a password"),
        ("pwd=abc123", "a password"),
        ("PIN is 4821", "a password"),
        ("pin: 482193", "a password"),
        ("secret: abc123", "a password"),
        ("token=abc123", "a password"),
        ("API key: abc123", "a password"),
        ("api_key=abc123", "a password"),
        ("access-key: abc123", "a password"),
        ("The door code is 4471", "a door or alarm code"),
        ("door code 4471", "a door or alarm code"),
        ("The alarm code: 99812", "a door or alarm code"),
        ("GATE CODE = 2580#", "a door or alarm code"),
        ("Security code is 301", "a door or alarm code"),
        ("Please pay to GB82 WEST 1234 5698 7654 32 by Friday thanks", "bank details"),
        ("GB82WEST12345698765432", "bank details"),
        ("iban: ie29aibk93115212345678", "bank details"),
        ("DE89 3704 0044 0532 0130 00", "bank details"),
        ("NO9386011117947", "bank details"),
        ("Sort code 12-34-56", "bank details"),
        ("account number 12345678", "bank details"),
        ("Account no. 12345678", "bank details"),
        ("acct 12345678", "bank details"),
        ("routing number: 021000021", "bank details"),
        ("routing 021000021", "bank details"),
        ("My SSN is 078-05-1120.", "an ID number"),
        ("PPS 1234567T", "an ID number"),
        ("pps: 1234567TW", "an ID number"),
    ],
)
def test_private_data_with_a_known_shape_is_found(text, kind):
    assert sensitive(text) == [kind]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "See you at 3.",
        "Call me on +353 86 123 4567 or 617-555-0142.",
        "Thursday 19 November 2026 at 18:30, order number 20261117-0042, 45 people, 1,250.00 paid.",
        "4111 1111 1111 1112",  # the last digit is wrong, so it is not a card number
        "0000 0000 0000 0000",
        "1234567890123456",
        "411111111111",  # too short
        "41111111111111111111",  # too long
        "https://harbour-hall.example/bookings?id=2291&view=full",
        "Please pass the salt, and pass it on.",
        "Did you get a password reset email? I forgot my password again.",
        "The password is on the fridge.".replace("is on", "sits on"),
        "As a token of thanks, the secret to good bread is time.",
        "Pin it to the board. The pin is in the drawer.",
        "The pin is under the mat, and the PIN is four digits long.",
        "Your order code is 55120 and the booking code is 7781.",
        "The dress code is smart, and the door code is on the fridge.",
        "The door code is the year we met, then my old flat number.",  # a known miss: it is written in words
        "The door code is 44.",  # too short to be a code
        "The area code is 617 and the post code is 02139.",
        "GB82 WEST 1234 5698 7654 33",  # the check digits do not fit
        "IE64 IRCE 9205 0112 3456 78".replace("64", "65"),
        "My account is in good standing and the sort of code we like.",
        "078-05-11200",
        "2026-11-17",
        "sk-short",
        "ghp_short",
        "AKIA",
        "task-force and risk-based checks",
    ],
)
def test_ordinary_text_is_not_taken_for_private_data(text):
    assert sensitive(text) == []


def test_every_kind_in_one_text_is_named_once_each():
    text = f"4111 1111 1111 1111 and 5555555555554444, {KEY}, password: x12, pin: 1234, GB82WEST12345698765432, sort code 12-34-56, 078-05-1120"
    assert sensitive(text) == ["a card number", "a key or token", "a password", "bank details", "an ID number"]


@pytest.mark.parametrize(
    "text",
    [
        "four one one one, one one one one, one one one one, one one one one",
        "NDExMSAxMTExIDExMTEgMTExMQ==",  # a card number in base64
        "4111 1111 / 1111 1111",
        "4 1 1 1  1 1 1 1  1 1 1 1  1 1 1 1",
        "the door code for the office: blue-heron-42",
    ],
)
def test_private_data_in_another_shape_is_missed(text):
    """Said in the docstring of sensitive(). If one of these starts to be found, say so there."""
    assert sensitive(text) == []


def test_a_reason_never_repeats_what_was_found(email, pay):
    secret = f"card 4111 1111 1111 1111, {KEY}, password: hunter2, GB82WEST12345698765432, 078-05-1120, a​b"
    for line in (email.why(note(body=secret)), pay.why({"to": LENA, "amount": 5, "note": secret})):
        assert line.startswith("Asks because: what is being sent holds what looks like a card number; ")
        for piece in ("4111", KEY, "hunter2", "GB82", "078", "​"):
            assert piece not in line


# ---- the email rule --------------------------------------------------------------------


def test_what_an_ordinary_email_says(email):
    assert email.why(note()) == "Runs without asking: every address is one of yours or in your contacts, and nothing unusual was found in what is sent"
    assert email.explain(note()) == Verdict(FREE, ())


@pytest.mark.parametrize(
    "to",
    [SAM, "SAM@EXAMPLE.COM", f"Sam Keane <{SAM}>", f"<{SAM}>", f"  {SAM}  ", f'"Keane, Sam" <{SAM}>', [SAM], [SAM, PRIYA, ME], f"{SAM},{PRIYA}", f"{SAM}; {PRIYA};", f"Sam <{SAM}>, {ME}", [f"{SAM}, {PRIYA}", ME]],
)
def test_ways_of_writing_people_you_know_that_run_without_asking(email, to):
    assert email.explain(note(to)) == Verdict(FREE, ())


@pytest.mark.parametrize(
    "inputs, reason",
    [
        (note(THIEF), f"{THIEF} is not in your contacts"),
        (note(f"Sam Keane <{THIEF.upper()}>"), f"{THIEF} is not in your contacts"),
        (note(cc=THIEF), f"{THIEF} is not in your contacts"),
        (note("sam@examp1e.com"), f"sam@examp1e.com is not in your contacts, and it looks like {SAM}, which is"),
        (note("sam@exarnple.com"), f"sam@exarnple.com is not in your contacts, and it looks like {SAM}, which is"),
        (note("sam@example.co"), f"sam@example.co is not in your contacts, and it looks like {SAM}, which is"),
        (note("sam@example.com.thief.example"), f"sam@example.com.thief.example is not in your contacts, and it looks like {SAM}, which is"),
        (note("sam@example-mail.com"), f"sam@example-mail.com is not in your contacts, and it looks like {SAM}, which is"),
        (note("sam@elsewhere.example"), f"sam@elsewhere.example is not in your contacts, and it looks like {SAM}, which is"),
        (note("sam+forward@example.com"), f"sam+forward@example.com is not in your contacts"),
        (note("s.am@example.com"), f"s.am@example.com is not in your contacts, and it looks like {SAM}, which is"),
        (note("prlya@example.com"), f"prlya@example.com is not in your contacts, and it looks like {PRIYA}, which is"),
        (note("priyaa@example.com"), f"priyaa@example.com is not in your contacts, and it looks like {PRIYA}, which is"),
        (note("alex@example.org"), f"alex@example.org is not in your contacts, and it looks like {ME}, which is"),
        (note("new.person@examp1e.com"), f"new.person@examp1e.com is not in your contacts, and its domain looks like the one in {ME}, which is"),
        (note("new.person@example.com"), "new.person@example.com is not in your contacts"),
        (note(to=None), "no address to send to was found"),
        (note(""), "no address to send to was found"),
        (note([]), "no address to send to was found"),
        (note(" , ; "), "no address to send to was found"),
        (note(bcc=PRIYA), "it has a hidden copy (BCC)"),
        (note(SAM, cc=[ME, "dana@example.com"]), "dana@example.com is not in your contacts"),
        (note(reply_to=THIEF), "the rule was not told about 1 of the inputs"),
        (note(reply_to=THIEF, headers={"X": "y"}), "the rule was not told about 2 of the inputs"),
        (note(attachments=["a.pdf"]), "it has an attachment going to someone outside your own addresses"),
        (note(attachments="a.pdf"), "it has an attachment going to someone outside your own addresses"),
        (note(attachments={"name": "a.pdf"}), "it has an attachment going to someone outside your own addresses"),
        (note(attachments=0), "it has an attachment going to someone outside your own addresses"),
        (note([ME, SAM], attachments=["a.pdf"]), "it has an attachment going to someone outside your own addresses"),
        (note(body="password: hunter2"), "what is being sent holds what looks like a password"),
        (note(subject="4111 1111 1111 1111"), "what is being sent holds what looks like a card number"),
        (note(attachments=["a​.pdf"], to=ME), "what is being sent holds characters that cannot be seen"),
        (note(body=["fine", {"more": ["<!-- x -->"]}]), "what is being sent holds a comment in the markup"),
        (note(body={"password: hunter2": "fine"}), "what is being sent holds what looks like a password"),
    ],
)
def test_one_thing_unusual_asks_and_says_what(email, inputs, reason):
    assert email.explain(inputs) == Verdict(NEEDS_YES, (reason,))


@pytest.mark.parametrize(
    "to",
    [
        f"{SAM} {THIEF}",
        f"{SAM}\n{THIEF}",
        f"{SAM}\r\nBcc: {THIEF}",
        f"{SAM}\t",
        f"{SAM}\x00",
        f"{SAM}\x7f",
        f"sam​@example.com",
        f"{SAM} ",
        f"{SAM}, thief＠example.net",
        f"{SAM}%2C{THIEF}",
        f"mailto:{SAM}",
        f"{SAM} ({THIEF})",
        f"{SAM} <{THIEF}>",
        f'"{SAM}" <{THIEF}>',
        f'"x, {THIEF}" <{SAM}>',
        f"<@thief.example:{SAM}>",
        f'"{THIEF}"@example.com',
        f"team: {THIEF};",
        f"{SAM}@thief.example",
        f"{SAM}.",
        f"Sam <{SAM}> x",
        f"Sam <{SAM}",
        f"Sam {SAM}>",
        f"<<{SAM}>>",
        f"Sam <{SAM}> <{THIEF}>",
        "sam@example",
        "sam@.com",
        "@example.com",
        "sаm@example.com",
        "sam@exаmple.com",
        "Sam Keane",
        f"{SAM},,x",
        {"address": SAM},
        [[SAM]],
        [SAM, 7],
        [SAM, None],
        42,
        True,
        0,
    ],
)
def test_an_address_input_that_cannot_be_read_for_certain_asks(email, to):
    assert email.explain(note(to)).level == NEEDS_YES
    assert 'the "to" input cannot be read for certain as a list of addresses' in reasons(email, note(to))
    assert "no address to send to was found" not in reasons(email, note(to))
    assert 'the "cc" input cannot be read for certain as a list of addresses' in reasons(email, note(cc=to))
    assert 'the "bcc" input cannot be read for certain as a list of addresses' in reasons(email, note(bcc=to))


def test_every_reason_is_given_together(email):
    inputs = note([THIEF, SAM, PRIYA, ME], bcc="x y", attachments=["a.pdf"], body="pin: 1234", reply_to="x")
    assert reasons(email, inputs) == [
        "the rule was not told about 1 of the inputs",
        'the "bcc" input cannot be read for certain as a list of addresses',
        "it goes to 4 addresses, more than 3",
        f"{THIEF} is not in your contacts",
        "it has an attachment going to someone outside your own addresses",
        "what is being sent holds what looks like a password",
    ]
    assert email.why(inputs) == (
        'Asks because: the rule was not told about 1 of the inputs; the "bcc" input cannot be read for certain as a list of addresses; '
        f"it goes to 4 addresses, more than 3; {THIEF} is not in your contacts; and 2 more"
    )


def test_how_many_it_goes_to_counts_each_address_once(email):
    assert email(note([SAM, PRIYA, ME])) == FREE
    assert email(note([SAM, PRIYA, ME], cc=[SAM.upper(), f"P <{PRIYA}>"])) == FREE
    assert reasons(email, note([SAM, PRIYA], cc=[ME, "dana@example.com"]))[0] == "it goes to 4 addresses, more than 3"
    one = rules.email(contacts=[SAM, PRIYA], me=[ME], max_recipients=1)
    assert one(note()) == FREE and reasons(one, note(cc=ME)) == ["it goes to 2 addresses, more than 1"]
    many = rules.email(contacts=[SAM, PRIYA, "dana@example.com"], me=[ME], max_recipients=4)
    assert many(note([SAM, PRIYA, ME, "dana@example.com"])) == FREE


def test_an_attachment_runs_without_asking_only_to_your_own_addresses():
    email = rules.email(contacts=[SAM, "kim@harbour.example", "kim@mail.harbour.example"], me=[ME], own_domains=["harbour.example"])
    files = {"attachments": ["q4.pdf"]}
    assert email(note(ME, **files)) == FREE
    assert email(note("kim@harbour.example", **files)) == FREE
    assert email(note([ME, "Kim <KIM@harbour.example>"], **files)) == FREE
    assert email(note(SAM, **files)) == NEEDS_YES
    assert email(note([ME, SAM], **files)) == NEEDS_YES
    assert email(note(ME, cc=SAM, **files)) == NEEDS_YES
    assert email(note("kim@mail.harbour.example", **files)) == NEEDS_YES  # a subdomain is another domain
    # Your own domain does not make a stranger at it a contact.
    assert reasons(email, note("new@harbour.example", **files)) == ["new@harbour.example is not in your contacts"]
    for nothing in (None, "", [], {}):
        assert email(note(SAM, attachments=nothing)) == FREE
    assert reasons(email, note("", **files)) == ["no address to send to was found", "it has an attachment going to someone outside your own addresses"]


@pytest.mark.parametrize(
    "to",
    [
        "old-scam@example.net",
        "OLD-SCAM@EXAMPLE.NET",
        "Sam Keane <old-scam@example.net>",
        "mailto:old-scam@example.net",
        f"{SAM} (old-scam@example.net)",
        f"{SAM}\nold-scam@example.net",
        "old-scam@example.net.",
        [SAM, "old-scam@example.net"],
        [[["old-scam@example.net"]]],
        {"address": "old-scam@example.net"},
        "anyone@blocked.example",
        "anyone@MAIL.blocked.example",
        '"x" <a@a.b.blocked.example>',
    ],
)
def test_a_blocked_address_is_never_allowed_however_it_is_written(email, to):
    for inputs in (note(to), note(cc=to), note(bcc=to), note(ME, cc=to, attachments=["a.pdf"])):
        assert email.explain(inputs) == Verdict(NEVER, ("an address is on your block list",))
        assert email.why(inputs) == "Never allowed: an address is on your block list"


@pytest.mark.parametrize("to", ["anyone@notblocked.example", "anyone@blocked.example.org", "blocked.example@example.org", "scam@example.net", "old-scam@example.org"])
def test_an_address_that_is_only_close_to_a_blocked_one_asks(email, to):
    assert email(note(to)) == NEEDS_YES


def test_the_block_list_is_about_who_it_goes_to_and_not_what_it_says(email):
    assert email(note(body="Do not reply to old-scam@example.net.", subject="a@blocked.example")) == FREE


def test_the_rule_can_be_told_what_the_tool_calls_its_inputs():
    email = rules.email(contacts=[SAM], me=[ME], blocked=[THIEF], to="recipients", cc="copy", bcc="blind", subject="title", body="text", attachments="files")
    assert email({"recipients": [SAM], "copy": ME, "title": "Hi", "text": "See you at 3."}) == FREE
    assert reasons(email, {"recipients": SAM, "blind": ME}) == ["it has a hidden copy (BCC)"]
    assert reasons(email, {"recipients": SAM, "files": ["a.pdf"]}) == ["it has an attachment going to someone outside your own addresses"]
    assert email({"copy": THIEF}) == NEVER and email({"blind": [THIEF]}) == NEVER
    # The usual names are now inputs it was not told about, and are not read as addresses.
    assert reasons(email, {"recipients": SAM, "to": THIEF}) == ["the rule was not told about 1 of the inputs"]
    assert reasons(email, note()) == ["the rule was not told about 2 of the inputs", "no address to send to was found"]
    assert reasons(email, {"recipients": SAM, "text": "pin: 1234"}) == ["what is being sent holds what looks like a password"]


def test_a_reason_does_not_carry_a_very_long_address(email):
    long = "x" * 60 + "@example.net"
    assert reasons(email, note("y" * 52 + "@example.net")) == ["y" * 52 + "@example.net is not in your contacts"]
    assert reasons(email, note(long)) == ["an address too long to show here is not in your contacts"]
    assert len(email.why(note([long, THIEF]))) < 200 and THIEF in email.why(note([long, THIEF]))


def test_a_shared_name_at_another_domain_is_not_called_a_look_alike():
    email = rules.email(contacts=["info@harbour-hall.example", "sam@example.com"])
    assert reasons(email, note("info@bakery.example")) == ["info@bakery.example is not in your contacts"]
    assert reasons(email, note("sam@bakery.example")) == ["sam@bakery.example is not in your contacts, and it looks like sam@example.com, which is"]


# ---- the payment rule ------------------------------------------------------------------


def test_what_an_ordinary_payment_says(pay):
    inputs = {"to": LENA, "amount": 180.0, "note": "March invoice 118"}
    assert pay.explain(inputs) == Verdict(FREE, ())
    assert pay.why(inputs) == "Runs without asking: the payee is one of yours, the amount is within your limit, and nothing unusual was found"


@pytest.mark.parametrize("amount", [1, 180, 200, 0.01, 199.99, 200.0, "1", "180", "200", "200.0", "200.00", "0.01", "0200", "199.99"])
def test_amounts_within_the_limit_run_without_asking(pay, amount):
    assert pay.explain({"to": CATERING, "amount": amount}) == Verdict(FREE, ())


@pytest.mark.parametrize("amount", [201, 200.01, 200.0000001, 5000, 5000.0, "200.01", "201", "5000.00", "950"])
def test_amounts_over_the_limit_ask(pay, amount):
    assert pay.explain({"to": CATERING, "amount": amount}) == Verdict(NEEDS_YES, ("the amount is over your limit of 200",))


@pytest.mark.parametrize("amount", [5001, 5000.01, 10**12, 10**400, 1e300, "5000.01", "999999999999999"])
def test_amounts_over_the_ceiling_are_never_allowed(pay, amount):
    assert pay.explain({"to": CATERING, "amount": amount}) == Verdict(NEVER, ("the amount is over your ceiling of 5000",))
    assert pay.explain({"to": "SOMEONE-NEW-1", "amount": amount, "note": "pin: 1234"}) == Verdict(NEVER, ("the amount is over your ceiling of 5000",))


@pytest.mark.parametrize(
    "amount",
    [0, -1, -180.0, 0.0, "0", "0.00", "-180", "+180", "180.999", "180.", ".5", "1e2", "1E2", "$180", "180 ", " 180", "1,80", "1 80", "1_80", "0x10", "１８０", "١٨٠", "1" * 16, "", "ten", "inf", "nan", True, False, None, [180], {"value": 180}, float("inf"), float("-inf"), float("nan")],
)
def test_an_amount_that_is_not_plainly_a_number_above_0_asks(pay, amount):
    assert pay.explain({"to": CATERING, "amount": amount}) == Verdict(NEEDS_YES, ("the amount is not plainly a number above 0",))


def test_a_payment_with_no_amount_or_no_payee_asks(pay):
    assert reasons(pay, {"to": CATERING}) == ["the amount is not plainly a number above 0"]
    assert reasons(pay, {"amount": 5}) == ["the payee cannot be read"]
    assert reasons(pay, {}) == ["the payee cannot be read", "the amount is not plainly a number above 0"]


@pytest.mark.parametrize(
    "payee, reason",
    [
        ("NORTHGATE-STORAGE-6602", "NORTHGATE-STORAGE-6602 is not one of your payees"),
        ("BRIGHTSIDE-CATERING-PAYMENTS-9034", f"BRIGHTSIDE-CATERING-PAYMENTS-9034 is not one of your payees, and it looks like {CATERING}, which is"),
        ("LENA-FISCHER-5527", f"LENA-FISCHER-5527 is not one of your payees, and it looks like {LENA}, which is"),
        (LENA.lower(), f"{LENA.lower()} is not one of your payees, and it looks like {LENA}, which is"),
        (LENA + " ", f"{LENA}  is not one of your payees, and it looks like {LENA}, which is"),
        ("LENA-FlSCHER-5526", f"LENA-FlSCHER-5526 is not one of your payees, and it looks like {LENA}, which is"),
        ("LENA FISCHER", f"LENA FISCHER is not one of your payees, and it looks like {LENA}, which is"),
        (LENA + "​", f"the payee is not one of your payees, and it looks like {LENA}, which is"),
        ("NORTHGATE\nSTORAGE", "the payee is not one of your payees"),
        ("N" * 65, "the payee is not one of your payees"),
        ("", "the payee cannot be read"),
        (None, "the payee cannot be read"),
        ([LENA], "the payee cannot be read"),
        ({"name": LENA}, "the payee cannot be read"),
        (5526, "the payee cannot be read"),
    ],
)
def test_a_payee_that_is_not_on_the_list_character_for_character_asks(pay, payee, reason):
    assert pay.explain({"to": payee, "amount": 5}) == Verdict(NEEDS_YES, (reason,))


def test_a_supplier_with_another_account_asks():
    """The invoice scam: a real supplier's bill, with the thief's account on it."""
    pay = rules.payment(payees={"Brightside Catering": "IE29AIBK93115212345678", "Lena Fischer": "DE89370400440532013000"}, limit=200)
    known = {"to": "Brightside Catering", "account": "IE29AIBK93115212345678", "amount": 180}
    assert pay.explain(known) == Verdict(FREE, ())
    for account in ("GB82WEST12345698765432", "DE89370400440532013000", "ie29aibk93115212345678", "IE29 AIBK 9311 5212 3456 78", "IE29AIBK93115212345678 ", "", None, ["IE29AIBK93115212345678"], 29):
        assert pay.explain({**known, "account": account}) == Verdict(NEEDS_YES, ("the account is not the one you gave for Brightside Catering",))
    assert reasons(pay, {"to": "Brightside Catering", "amount": 180}) == ["the account is not the one you gave for Brightside Catering"]
    assert reasons(pay, {**known, "to": "Brightside Catering Payments"}) == ["Brightside Catering Payments is not one of your payees, and it looks like Brightside Catering, which is"]
    # A list of payees was not told about accounts, so an account is an input it does not know.
    plain = rules.payment(payees=["Brightside Catering"], limit=200)
    assert reasons(plain, known) == ["the rule was not told about 1 of the inputs"]


def test_a_currency_asks_unless_the_rule_was_told_which_its_limit_is_in(pay):
    assert reasons(pay, {"to": LENA, "amount": 180, "currency": "EUR"}) == ["the rule was not told about 1 of the inputs"]
    euros = rules.payment(payees=[LENA], limit=200, currencies=["EUR", "USD"])
    assert euros({"to": LENA, "amount": 180, "currency": "EUR"}) == FREE and euros({"to": LENA, "amount": 180, "currency": "USD"}) == FREE
    for currency in ("JPY", "eur", "EUR ", "", None, ["EUR"], 978):
        assert euros.explain({"to": LENA, "amount": 180, "currency": currency}) == Verdict(NEEDS_YES, ("the currency is not one your limit is in",))
    assert reasons(euros, {"to": LENA, "amount": 180}) == ["the currency is not one your limit is in"]


def test_what_is_in_the_note_is_checked_and_the_other_inputs_are_not(pay):
    assert reasons(pay, {"to": LENA, "amount": 5, "note": "pin: 1234"}) == ["what is being sent holds what looks like a password"]
    assert reasons(pay, {"to": LENA, "amount": 5, "note": "March⁣"}) == ["what is being sent holds characters that cannot be seen"]
    assert reasons(pay, {"to": LENA, "amount": 5, "reference": "a​b"}) == ["the rule was not told about 1 of the inputs", "what is being sent holds characters that cannot be seen"]
    # An account number in the account input is what that input is for.
    supplier = rules.payment(payees={"Brightside Catering": "GB82WEST12345698765432"}, limit=200)
    assert supplier({"to": "Brightside Catering", "account": "GB82WEST12345698765432", "amount": 5}) == FREE


def test_the_payment_rule_can_be_told_what_the_tool_calls_its_inputs():
    pay = rules.payment(payees={"Lena": "DE89"}, limit=200, ceiling=900, currencies=["EUR"], to="payee", amount="value", account="iban", currency="code", note="memo")
    fine = {"payee": "Lena", "value": 180, "iban": "DE89", "code": "EUR", "memo": "March"}
    assert pay.explain(fine) == Verdict(FREE, ())
    assert reasons(pay, {**fine, "value": 201}) == ["the amount is over your limit of 200"]
    assert pay({**fine, "value": 901}) == NEVER
    assert reasons(pay, {**fine, "iban": "GB82"}) == ["the account is not the one you gave for Lena"]
    assert reasons(pay, {**fine, "code": "JPY"}) == ["the currency is not one your limit is in"]
    assert reasons(pay, {**fine, "memo": "pin: 1234"}) == ["what is being sent holds what looks like a password"]
    assert reasons(pay, {**fine, "to": "Lena"}) == ["the rule was not told about 1 of the inputs"]


def test_a_limit_with_cents_and_a_ceiling_equal_to_the_limit():
    pay = rules.payment(payees=[LENA], limit=99.99, ceiling=99.99)
    assert pay({"to": LENA, "amount": 99.99}) == FREE and pay({"to": LENA, "amount": "99.99"}) == FREE
    assert pay.explain({"to": LENA, "amount": 100}) == Verdict(NEVER, ("the amount is over your ceiling of 99.99",))
    no_ceiling = rules.payment(payees=[LENA], limit=99.99)
    assert no_ceiling.explain({"to": LENA, "amount": 10**12}) == Verdict(NEEDS_YES, ("the amount is over your limit of 99.99",))


# ---- many made-up inputs, the same ones every time -------------------------------------
#
# Whatever the rule lets run without asking is read again here the way a careless
# tool might read it: anything with an @ in it is somewhere the email could go.

_CARELESS = re.compile(r"[^\s<>()\[\]\"',;:]+@[^\s<>()\[\]\"',;:]+")
_PIECES = [
    SAM, PRIYA, ME, THIEF, "Sam@Example.com", "sam", "example.com", "example.net", "thief", "@", ".", ",", ";", " ", "  ", "<", ">", '"', "'", "(", ")", ":",
    "\n", "\r\n", "\t", "​", " ", "＠", "%2C", "%40", "mailto:", "Sam Keane", "Bcc: ", "+x", "\\", "[", "]", "/", "?cc=", "&", "=", "‮", "\x00",
    "x", "1", "-", "_", "!", "|", "old-scam@example.net", "a@blocked.example", "，", "、", ";", "؛", "﹐", "；",
]  # fmt: skip


def _careless(value):
    found = set()
    for item in value if isinstance(value, list) else [value]:
        if isinstance(item, str):
            found |= {match.group().strip(".").lower() for match in _CARELESS.finditer(item)}
            found |= {piece.lower() for piece in re.split(r"[^A-Za-z0-9._%+@-]+", item) if "@" in piece}
    return found


def test_nothing_runs_without_asking_that_a_careless_reading_would_send_to_a_stranger(email):
    made = random.Random(20261117)

    def text():
        return "".join(made.choice(_PIECES) for _ in range(made.randint(1, 6)))

    def field():
        kind = made.random()
        if kind < 0.5:
            return text()
        if kind < 0.8:
            return [text() for _ in range(made.randint(0, 3))]
        return made.choice([None, SAM, [SAM], f"Sam <{SAM}>", ME, "", []])

    ran = 0
    for _ in range(20000):
        inputs = {"to": field(), "body": "hi"}
        if made.random() < 0.4:
            inputs["cc"] = field()
        if made.random() < 0.2:
            inputs["bcc"] = field()
        if email(inputs) == FREE:
            ran += 1
            found = _careless(inputs["to"]) | _careless(inputs.get("cc")) | _careless(inputs.get("bcc"))
            assert found and found <= {SAM, PRIYA, ME}, inputs
            assert not _careless(inputs.get("bcc")), inputs
    assert ran > 500  # enough of them ran for this to have looked at something


def test_no_payment_runs_without_asking_that_a_careless_reading_would_put_over_the_limit(pay):
    made = random.Random(20261117)
    pieces = ["1", "8", "0", "9", ".", "e", "E", "-", "+", " ", "_", ",", "１", "inf", "nan", "0x", "١", "'", "\n", "1_0", "²"]
    numbers = [1e-320, 200.00000000000001, 200.0000001, True, False, None, [180], {"a": 1}, 2e2, 2.0000001e2]
    texts = ["200", "200.00", "200.01", "0200", "00.01", "0", "0.00", "199.99", "200.0", "200.001"]
    payees = [LENA, LENA + " ", LENA.lower(), "LENA-FISCHER-5527", [LENA], CATERING, "", None]
    ran = 0
    for _ in range(20000):
        kind = made.random()
        if kind < 0.5:
            amount = "".join(made.choice(pieces) for _ in range(made.randint(1, 6)))
        elif kind < 0.7:
            amount = made.choice([made.uniform(-10, 400), made.randint(-5, 400)])
        elif kind < 0.85:
            amount = made.choice(numbers)
        else:
            amount = made.choice(texts)
        to = made.choice(payees)
        if pay({"to": to, "amount": amount}) == FREE:
            ran += 1
            assert type(to) is str and to in (LENA, CATERING), (to, amount)
            assert type(amount) is not bool and 0 < float(amount) <= 200, (to, amount)
    assert ran > 500
