"""The ready-made rule for a tool that adds an event to a calendar: rules.calendar.

The rule is called as the checkpoint calls it, with the inputs of one action.
Nothing here reaches a calendar.
"""

import pytest

from kettle import rules
from kettle.checkpoint import HELD, RAN, REFUSED, Checkpoint
from kettle.checkpoint.rules import FREE, NEEDS_YES, NEVER, RulesError

FINE = "nobody is invited who is not you or in your contacts, and nothing unusual was found in what a guest would be sent"
UNTOLD = "the rule was not told about {} of the inputs of this event"
BLOCKED = "a guest is on your block list"
UNREAD = "the guests cannot be read for certain as a list of addresses"
MANY = "it invites {} guests, more than {}"
STRANGER = "{} is invited and is not in your contacts"
ALIKE = "{} is invited and is not in your contacts, and it looks like {}, which is"
ALIKE_DOMAIN = "{} is invited and is not in your contacts, and its domain looks like the one in {}, which is"
CARD_FOUND = "what is being sent holds what looks like a card number"
CODE_FOUND = "what is being sent holds what looks like a door or alarm code"
UNSEEN_FOUND = "what is being sent holds characters that cannot be seen"

ME, WORK = "alex@example.com", "alex@work.example"
SAM, PRIYA, DANA, LEE = "sam@example.com", "priya@example.com", "dana@harbour-hall.example", "lee@example.com"
THIEF = "thief@example.net"
OLD_SCAM, BAD_DOMAIN = "old-scam@example.net", "@blocked.example"
CARD = "4111 1111 1111 1111"


def make(**settings):
    settings = {"contacts": [SAM, PRIYA, DANA, LEE], "me": [ME, WORK], "blocked": [OLD_SCAM, BAD_DOMAIN], **settings}
    return rules.calendar(**settings)


def said(reasons):
    """The reasons as why() writes them: the first four, then how many more."""
    return "; ".join(reasons[:4]) + (f"; and {len(reasons) - 4} more" if len(reasons) > 4 else "")


def runs(inputs, rule=None):
    rule = make() if rule is None else rule
    verdict = rule.explain(inputs)
    assert (verdict.level, list(verdict.reasons)) == (FREE, [])
    assert rule(inputs) == FREE
    assert rule.why(inputs) == "Runs without asking: " + FINE


def asks(inputs, reasons, rule=None):
    rule = make() if rule is None else rule
    verdict = rule.explain(inputs)
    assert (verdict.level, list(verdict.reasons)) == (NEEDS_YES, reasons)
    assert rule(inputs) == NEEDS_YES
    assert rule.why(inputs) == "Asks because: " + said(reasons)


def never(inputs, reasons, rule=None):
    rule = make() if rule is None else rule
    verdict = rule.explain(inputs)
    assert (verdict.level, list(verdict.reasons)) == (NEVER, reasons)
    assert rule(inputs) == NEVER
    assert rule.why(inputs) == "Never allowed: " + said(reasons)


def event(attendees=None, **more):
    inputs = {"title": "Planning", "start": "2026-12-03T15:00", "end": "2026-12-03T16:00", **more}
    if attendees is not None:
        inputs["attendees"] = attendees
    return inputs


# ---- nobody is sent anything ----


@pytest.mark.parametrize("attendees", [None, "", [], ME, [ME], [ME, WORK], f"Alex <{ME}>", "ALEX@Example.com", f"{ME}, {WORK}"])
def test_an_event_with_nobody_on_it_but_the_owner_runs(attendees):
    runs(event(attendees))
    runs({} if attendees is None else {"attendees": attendees})


def test_an_event_with_no_guests_is_not_looked_into():
    runs(event(description=f"Card {CARD}", location="Door code 4821", title="a​b"))
    runs(event(ME, description=f"Card {CARD}"))


def test_an_event_with_no_guests_still_asks_about_an_input_the_rule_was_not_told_about():
    asks(event(event_id="evt_7"), [UNTOLD.format(1)])
    asks(event(ME, event_id="evt_7", calendar="work"), [UNTOLD.format(2)])


# ---- contacts ----


@pytest.mark.parametrize(
    "attendees",
    [SAM, [SAM], [SAM, PRIYA], [SAM, PRIYA, DANA], f"{SAM}, {PRIYA}", f"Sam Keane <{SAM}>", "SAM@Example.com", [SAM, ME], f"{SAM}; {DANA}", [f"Priya Nair <{PRIYA}>", LEE, DANA, SAM, ME, WORK]],
)
def test_an_event_with_contacts_invited_runs(attendees):
    runs(event(attendees))
    runs(event(attendees, description="Agenda: the spring menu. Call 617 555 0143 if you are late.", location="Room 4, 12 Harbour Street"))


def test_a_contact_whose_address_looks_like_private_data_can_be_invited():
    odd = "4111111111111111@example.com"
    runs(event(odd), make(contacts=[odd]))
    asks(event(SAM, title="4111111111111111"), [CARD_FOUND])


# ---- strangers ----


@pytest.mark.parametrize("attendees", [THIEF, [THIEF], f"Sam Keane <{THIEF}>", "THIEF@example.net"])
def test_a_guest_who_is_not_a_contact_asks(attendees):
    asks(event(attendees), [STRANGER.format(THIEF)])


def test_a_stranger_anywhere_among_the_guests_asks():
    asks(event([THIEF, SAM, PRIYA]), [STRANGER.format(THIEF)])
    asks(event([SAM, THIEF, PRIYA]), [STRANGER.format(THIEF)])
    asks(event([SAM, PRIYA, THIEF]), [STRANGER.format(THIEF)])
    asks(event(f"{SAM}, {PRIYA}, {THIEF}"), [STRANGER.format(THIEF)])
    asks(event([ME, THIEF]), [STRANGER.format(THIEF)])


def test_each_stranger_is_named_in_the_order_given():
    asks(event(["zed@example.org", SAM, THIEF]), [STRANGER.format("zed@example.org"), STRANGER.format(THIEF)])


def test_one_of_your_own_addresses_is_not_a_contact_of_someone_elses_rule():
    asks(event("lena@work.example"), [STRANGER.format("lena@work.example")], make(me=[ME]))
    runs(event("lena@work.example"), make(me=[ME, "lena@work.example"]))
    asks(event(SAM), [STRANGER.format(SAM)], make(contacts=[PRIYA]))
    asks(event(SAM), [STRANGER.format(SAM)], rules.calendar())


def test_a_guest_that_looks_like_a_contact_is_said_to():
    asks(event("sam@examp1e.com"), [ALIKE.format("sam@examp1e.com", SAM)])
    asks(event("dana@harbour-hal.example"), [ALIKE.format("dana@harbour-hal.example", DANA)])
    asks(event(["prlya@example.com", SAM]), [ALIKE.format("prlya@example.com", PRIYA)])


def test_a_guest_that_looks_like_one_of_your_own_addresses_is_said_to():
    asks(event("a1ex@work.example"), [ALIKE.format("a1ex@work.example", WORK)])


def test_a_guest_at_a_domain_that_looks_like_a_contacts_is_said_to():
    asks(event("kim@harbour-hal.example"), [ALIKE_DOMAIN.format("kim@harbour-hal.example", DANA)])
    asks(event("kim@harbourhall.example"), [ALIKE_DOMAIN.format("kim@harbourhall.example", DANA)])


def test_a_very_long_address_is_not_written_out_in_the_reason():
    long = "a" * 60 + "@example.net"
    asks(event(long), [STRANGER.format("an address too long to show here")])
    fine = "a" * 52 + "@example.net"
    asks(event(fine), [STRANGER.format(fine)])
    alike = "a" * 60 + "@harbour-hal.example"
    asks(event(alike), [ALIKE_DOMAIN.format("an address too long to show here", DANA)])


# ---- guests that cannot be read ----


@pytest.mark.parametrize(
    "attendees",
    [
        f"{SAM}\n{THIEF}",
        f"{SAM}\t{THIEF}",
        f"{SAM}​",
        f"{SAM} {THIEF}",
        "not an address",
        f"<{SAM}> <{THIEF}>",
        5,
        True,
        {"email": SAM},
        [{"email": SAM}],
        [SAM, 5],
        [SAM, None],
        [[SAM]],
        (SAM,),
        (),
        b"sam@example.com",
    ],
)
def test_guests_that_cannot_be_read_for_certain_ask(attendees):
    asks(event(attendees), [UNREAD])


def test_guests_that_cannot_be_read_do_not_stop_the_other_checks():
    asks(event("not an address", description=f"Card {CARD}", event_id="evt_7"), [UNTOLD.format(1), UNREAD, CARD_FOUND])
    asks(event(f"{SAM}​", title="a​b"), [UNREAD, UNSEEN_FOUND])


# ---- too many guests ----


def test_more_guests_than_the_owner_allows_asks():
    everyone = [SAM, PRIYA, DANA, LEE]
    runs(event(everyone))
    runs(event(everyone[:3]), make(max_guests=3))
    asks(event(everyone), [MANY.format(4, 3)], make(max_guests=3))
    asks(event(everyone[:2]), [MANY.format(2, 1)], make(max_guests=1))
    runs(event(everyone[:1]), make(max_guests=1))


def test_the_owner_is_not_counted_as_a_guest():
    runs(event([SAM, PRIYA, DANA, ME, WORK]), make(max_guests=3))
    asks(event([SAM, PRIYA, DANA, LEE, ME]), [MANY.format(4, 3)], make(max_guests=3))


def test_ten_guests_run_and_eleven_ask_when_nothing_is_said():
    people = [f"guest{n}@example.org" for n in range(11)]
    rule = rules.calendar(contacts=people)
    runs(event(people[:10]), rule)
    asks(event(people), [MANY.format(11, 10)], rule)
    runs(event(people), rules.calendar(contacts=people, max_guests=11))


def test_strangers_are_counted_too():
    asks(event([SAM, PRIYA, THIEF]), [MANY.format(3, 2), STRANGER.format(THIEF)], make(max_guests=2))


# ---- the block list ----


@pytest.mark.parametrize(
    "attendees",
    [
        OLD_SCAM,
        [SAM, OLD_SCAM],
        f"Old Friend <{OLD_SCAM}>",
        "OLD-SCAM@Example.net",
        "anyone@blocked.example",
        "anyone@BLOCKED.example",
        "anyone@mail.blocked.example",
        f"{SAM}\n{OLD_SCAM}",
        f"{SAM} {OLD_SCAM}",
        [SAM, f"see {OLD_SCAM} too"],
        f"{ME}, anyone@blocked.example",
    ],
)
def test_a_blocked_guest_is_never_invited(attendees):
    never(event(attendees), [BLOCKED])


def test_a_blocked_guest_is_refused_whatever_else_is_found():
    never(event([OLD_SCAM, THIEF], description=f"Card {CARD}", event_id="evt_7"), [BLOCKED])


def test_a_domain_that_only_ends_like_a_blocked_one_is_not_blocked():
    asks(event("anyone@unblocked.example"), [STRANGER.format("anyone@unblocked.example")])
    asks(event("anyone@blocked.example.org"), [STRANGER.format("anyone@blocked.example.org")])
    asks(event("old-scam@example.org"), [STRANGER.format("old-scam@example.org")])
    asks(event("scam@example.net"), [STRANGER.format("scam@example.net")])


def test_with_no_block_list_nobody_is_refused():
    asks(event(OLD_SCAM), [STRANGER.format(OLD_SCAM)], make(blocked=[]))
    asks(event("anyone@blocked.example"), [STRANGER.format("anyone@blocked.example")], make(blocked=[OLD_SCAM]))
    never(event(OLD_SCAM), [BLOCKED], make(blocked=[OLD_SCAM]))
    never(event("anyone@blocked.example"), [BLOCKED], make(blocked=[BAD_DOMAIN]))
    asks(event(OLD_SCAM), [STRANGER.format(OLD_SCAM)], make(blocked=[BAD_DOMAIN]))


def test_a_blocked_address_in_another_input_is_not_a_guest():
    runs(event(SAM, description=f"Do not invite {OLD_SCAM}."))


# ---- what the guests are sent ----


@pytest.mark.parametrize("name", ["title", "description", "location", "start", "end"])
def test_private_data_in_any_input_asks_when_someone_is_invited(name):
    asks(event(SAM, **{name: f"Card {CARD}"}), [CARD_FOUND])
    asks(event(SAM, **{name: "a​b"}), [UNSEEN_FOUND])
    asks(event([SAM, PRIYA], **{name: [f"Card {CARD}"]}), [CARD_FOUND])


def test_a_door_code_asks_when_someone_is_invited():
    asks(event(SAM, description="Door code 4821, then the second floor."), [CODE_FOUND])
    runs(event(description="Door code 4821, then the second floor."))


def test_an_input_the_rule_passes_over_is_still_looked_into():
    rule = make(ignore=["reminder"])
    runs(event(SAM, reminder=30), rule)
    asks(event(SAM, reminder=f"Card {CARD}"), [CARD_FOUND], rule)
    runs(event(reminder=f"Card {CARD}"), rule)


def test_everything_found_is_said_together():
    asks(
        event([THIEF, "sam@examp1e.com"], title=f"Card {CARD}", description="a​b", event_id="evt_7"),
        [UNTOLD.format(1), STRANGER.format(THIEF), ALIKE.format("sam@examp1e.com", SAM), UNSEEN_FOUND, CARD_FOUND],  # by the name of the input
    )


# ---- inputs the rule was not told about ----


def test_an_input_the_rule_was_not_told_about_asks():
    asks(event(SAM, optional_attendees=THIEF), [UNTOLD.format(1)])
    asks(event(SAM, event_id="evt_7", calendar="work", notify=True), [UNTOLD.format(3)])
    asks(event(SAM, reminder=30), [UNTOLD.format(1)])


def test_an_input_the_owner_says_to_pass_over_does_not_ask():
    rule = make(ignore=["reminder", "colour"])
    runs(event(SAM, reminder=30, colour="green"), rule)
    asks(event(SAM, reminder=30, colour="green", event_id="evt_7"), [UNTOLD.format(1)], rule)
    runs(event(SAM, reminder=30), make(ignore=("reminder",)))
    runs(event(SAM, reminder=30), make(ignore={"reminder"}))
    runs(event(SAM, reminder=30), make(ignore=frozenset({"reminder"})))


def test_the_inputs_can_have_other_names():
    rule = make(attendees="guests", title="summary", description="notes", location="where", start="begins", end="ends")
    runs({"guests": [SAM], "summary": "Planning", "notes": "Agenda", "where": "Room 4", "begins": "15:00", "ends": "16:00"}, rule)
    asks({"guests": [THIEF]}, [STRANGER.format(THIEF)], rule)
    never({"guests": [OLD_SCAM]}, [BLOCKED], rule)
    asks({"guests": [SAM], "summary": f"Card {CARD}"}, [CARD_FOUND], rule)
    for old in ("attendees", "title", "description", "location", "start", "end"):
        asks({"guests": [SAM], old: "x"}, [UNTOLD.format(1)], rule)
    # Under the old name the guests are not guests: the rule asks because it was not told about the input.
    asks({"attendees": [OLD_SCAM]}, [UNTOLD.format(1)], rule)


@pytest.mark.parametrize("role", ["title", "description", "location", "start", "end"])
def test_each_input_name_is_used(role):
    rule = make(**{role: "other"})
    runs({"attendees": SAM, "other": "x"}, rule)
    asks({"attendees": SAM, role: "x"}, [UNTOLD.format(1)], rule)
    asks({"attendees": SAM, "other": f"Card {CARD}"}, [CARD_FOUND], rule)


# ---- setup ----


@pytest.mark.parametrize("name", ["contacts", "me", "blocked"])
def test_the_lists_must_be_lists_of_addresses(name):
    with pytest.raises(RulesError, match=f"{name} must be a list of addresses, given as the list itself"):
        rules.calendar(**{name: SAM})
    with pytest.raises(RulesError, match=f"{name} must hold addresses as text"):
        rules.calendar(**{name: [5]})
    with pytest.raises(RulesError, match=f"{name}: 'not an address' is not an email address"):
        rules.calendar(**{name: ["not an address"]})


def test_only_the_block_list_takes_a_whole_domain():
    rules.calendar(blocked=["@blocked.example"])
    with pytest.raises(RulesError, match="contacts: '@example.com' is not an email address"):
        rules.calendar(contacts=["@example.com"])
    with pytest.raises(RulesError, match="me: '@example.com' is not an email address"):
        rules.calendar(me=["@example.com"])


@pytest.mark.parametrize("value", [0, -1, True, False, 2.0, "3", None, [3]])
def test_the_most_guests_must_be_a_whole_number_of_one_or_more(value):
    with pytest.raises(RulesError, match="max_guests must be a whole number, 1 or more"):
        rules.calendar(max_guests=value)


def test_an_address_cannot_be_trusted_and_blocked():
    with pytest.raises(RulesError, match="sam@example.com is a contact or one of your own addresses, and is blocked as well"):
        rules.calendar(contacts=[SAM, PRIYA], blocked=[SAM])
    with pytest.raises(RulesError, match="alex@example.com is a contact or one of your own addresses, and is blocked as well"):
        rules.calendar(contacts=[SAM], me=[ME], blocked=[ME])
    with pytest.raises(RulesError, match="priya@example.com is a contact or one of your own addresses, and is blocked as well"):
        rules.calendar(contacts=[SAM, PRIYA], blocked=["@example.com"])
    with pytest.raises(RulesError, match="alex@work.example is a contact or one of your own addresses, and is blocked as well"):
        rules.calendar(me=[WORK], blocked=["@work.example"])
    with pytest.raises(RulesError, match="kim@mail.blocked.example is a contact or one of your own addresses, and is blocked as well"):
        rules.calendar(contacts=["kim@mail.blocked.example"], blocked=["@blocked.example"])
    rules.calendar(contacts=[SAM], me=[ME], blocked=["@ample.com", OLD_SCAM])


@pytest.mark.parametrize("value", ["reminder", None, 5, {"reminder": True}, [5], [""], ["reminder", None]])
def test_what_to_pass_over_must_be_a_list_of_names(value):
    with pytest.raises(RulesError, match="ignore must be a list of the names of inputs, each as text"):
        rules.calendar(ignore=value)


def test_the_guests_cannot_be_passed_over():
    with pytest.raises(RulesError, match="the input that holds the guests cannot be ignored"):
        rules.calendar(ignore=["attendees"])
    with pytest.raises(RulesError, match="the input that holds the guests cannot be ignored"):
        rules.calendar(attendees="guests", ignore=["reminder", "guests"])
    rules.calendar(attendees="guests", ignore=["attendees"])


@pytest.mark.parametrize("role", ["attendees", "title", "description", "location", "start", "end"])
def test_each_input_name_must_be_text(role):
    for value in ("", None, 5, ["x"]):
        with pytest.raises(RulesError, match=f"{role} must be the name of an input, as text"):
            rules.calendar(**{role: value})


def test_two_inputs_cannot_have_the_same_name():
    with pytest.raises(RulesError, match="two of the input names given are the same"):
        rules.calendar(title="attendees")
    with pytest.raises(RulesError, match="two of the input names given are the same"):
        rules.calendar(start="when", end="when")


def test_the_lists_are_copied_at_setup():
    contacts, mine, blocked, passed = [SAM], [ME], [OLD_SCAM], ["reminder"]
    rule = rules.calendar(contacts=contacts, me=mine, blocked=blocked, ignore=passed)
    contacts.append(THIEF)
    mine.append(THIEF)
    blocked.clear()
    passed.append("event_id")
    asks(event(THIEF), [STRANGER.format(THIEF)], rule)
    never(event(OLD_SCAM), [BLOCKED], rule)
    asks(event(SAM, event_id="evt_7"), [UNTOLD.format(1)], rule)


# ---- what the rule says about itself ----


def test_the_settings_are_kept_and_named():
    rule = rules.calendar(contacts=[SAM, "Priya@Example.com"], me=[WORK, ME], blocked=[OLD_SCAM, "@Blocked.example"], max_guests=4, ignore=["reminder", "colour"], attendees="guests")
    assert rule.kind == "calendar"
    assert rule.settings() == {
        "contacts": ["priya@example.com", "sam@example.com"],
        "me": ["alex@example.com", "alex@work.example"],
        "blocked": ["@blocked.example", "old-scam@example.net"],
        "max_guests": 4,
        "ignore": ["colour", "reminder"],
        "fields": {"attendees": "guests", "title": "title", "description": "description", "location": "location", "start": "start", "end": "end"},
    }
    assert rules.calendar().settings() == {
        "contacts": [],
        "me": [],
        "blocked": [],
        "max_guests": 10,
        "ignore": [],
        "fields": {"attendees": "attendees", "title": "title", "description": "description", "location": "location", "start": "start", "end": "end"},
    }


def test_the_name_of_the_rule_changes_with_any_setting():
    def name(**settings):
        return make(**settings).__qualname__

    assert name().startswith("kettle.rules.calendar:")
    assert name() == name()
    assert name() == name(contacts=[LEE, DANA, PRIYA, SAM])
    changed = [
        name(contacts=[SAM]),
        name(me=[ME]),
        name(blocked=[OLD_SCAM]),
        name(max_guests=9),
        name(ignore=["reminder"]),
        name(attendees="guests"),
        name(title="summary"),
        name(description="notes"),
        name(location="where"),
        name(start="begins"),
        name(end="ends"),
    ]
    assert len(set(changed + [name()])) == 12


def test_the_rule_cannot_be_changed_after_setup():
    rule = make()
    for name, value in (("_contacts", frozenset({THIEF})), ("_blocked", frozenset()), ("_most", 99), ("kind", "x")):
        with pytest.raises(Exception):
            setattr(rule, name, value)
    asks(event(THIEF), [STRANGER.format(THIEF)], rule)


def test_calendar_is_one_of_the_rules_the_package_names():
    assert "calendar" in rules.__all__
    assert rules.__all__.index("calendar") == rules.__all__.index("files") + 1


# ---- with the real checkpoint ----


def test_with_the_checkpoint_a_contact_runs_a_stranger_is_held_and_a_blocked_guest_is_refused(tmp_path):
    added = []

    def add_event(title, start, attendees=None, description=""):
        added.append((title, attendees))
        return "added"

    rule = make()
    checkpoint = Checkpoint(str(tmp_path / "kettle.db"))
    try:
        checkpoint.tool("add_event", add_event, level=rule, describe=rule.why, watch=["attendees"])
        assert checkpoint.gate.request("add_event", {"title": "Dentist", "start": "15:00"}).status == RAN
        assert checkpoint.gate.request("add_event", {"title": "Planning", "start": "15:00", "attendees": [SAM]}).status == RAN
        assert added == [("Dentist", None), ("Planning", [SAM])]
        assert checkpoint.gate.request("add_event", {"title": "Planning", "start": "15:00", "attendees": [SAM, THIEF]}).status == HELD
        assert checkpoint.gate.request("add_event", {"title": "Planning", "start": "15:00", "attendees": [SAM], "description": f"Card {CARD}"}).status == HELD
        assert checkpoint.gate.request("add_event", {"title": "Planning", "start": "15:00", "attendees": OLD_SCAM}).status == REFUSED
        assert len(added) == 2
    finally:
        checkpoint.close()
