"""A Hold: a switch the app owns that makes the next actions ask, once the agent has read text from outside.

Found in real use: a tool that is fine to run when the owner asks for it should
need a yes once the agent has read a page or an email somebody else wrote. A level
sees only the inputs of one action, so the app has to say so. These tests pin that
a Hold only ever adds an ask, that it comes on before a marked tool runs, and what
a real checkpoint does with it. No model takes part.
"""

import functools
import inspect
import threading

import pytest

from kettle import FREE, HELD, NEEDS_YES, NEVER, RAN, REFUSED, Checkpoint, rules
from kettle.checkpoint.rules import RulesError
from kettle.holds import MAX_KEPT, MAX_REASON, NO_REASON, SAID, Hold

SAM = "sam@example.com"
STRANGER = "x@evil.example"
BLOCKED = "no@blocked.example"
PAGE = "a web page was read"
MAIL = "an email was read"
STRICT = {FREE: 0, NEEDS_YES: 1, NEVER: 2}
OWN_ASK = "this tool's own level says to ask"
OWN_NEVER = "this tool's own level never allows it"
NOT_A_REASON = [None, "", "   ", "\t", 5, b"a page", ["a page"], "x" * (MAX_REASON + 1), "one\ntwo", "bell\x07", "hidden​join"]
REASON_ERROR = r"^the reason must be text on one line, from 1 to 120 characters$"
READS_ERROR = r"^reads\(\) takes a plain function \(def\)\. For anything else, call on\(\) inside the tool$"
OVER_ERROR = r"^over\(\) takes FREE, NEEDS_YES, NEVER, a rule or a function$"


@pytest.fixture
def hold():
    return Hold()


def mail(to=SAM):
    return {"to": to, "body": "See you Saturday."}


def email_rule():
    return rules.email(contacts=[SAM], blocked=[BLOCKED])


# ---- the switch ------------------------------------------------------------------


def test_a_new_hold_is_off(hold):
    assert (hold.is_on(), hold.reasons()) == (False, ())


def test_on_turns_it_on_with_the_reason(hold):
    hold.on(PAGE)
    assert (hold.is_on(), hold.reasons()) == (True, (PAGE,))


def test_off_turns_it_off_and_forgets_the_reasons(hold):
    hold.on(PAGE)
    hold.on(MAIL)
    hold.off()
    assert (hold.is_on(), hold.reasons()) == (False, ())


def test_off_on_a_hold_that_is_off_is_fine(hold):
    hold.off()
    assert hold.is_on() is False


def test_it_can_be_turned_on_again_after_off(hold):
    hold.on(PAGE)
    hold.off()
    hold.on(MAIL)
    assert hold.reasons() == (MAIL,)


def test_reasons_are_kept_oldest_first(hold):
    hold.on(MAIL)
    hold.on(PAGE)
    assert hold.reasons() == (MAIL, PAGE)


def test_the_same_reason_is_kept_once_and_keeps_its_place(hold):
    hold.on(MAIL)
    hold.on(PAGE)
    hold.on(MAIL)
    assert hold.reasons() == (MAIL, PAGE)


def test_spaces_around_a_reason_are_dropped(hold):
    hold.on(f"  {PAGE} ")
    hold.on(PAGE)
    assert hold.reasons() == (PAGE,)


def test_the_longest_reason_is_kept_whole(hold):
    hold.on("x" * MAX_REASON)
    assert hold.reasons() == ("x" * MAX_REASON,)


def test_the_limits_are_what_the_words_say():
    assert (MAX_REASON, MAX_KEPT) == (120, 8)


@pytest.mark.parametrize("reason", NOT_A_REASON, ids=repr)
def test_a_reason_that_cannot_be_shown_still_turns_it_on_with_a_plain_one(hold, reason):
    hold.on(reason)
    assert (hold.is_on(), hold.reasons()) == (True, (NO_REASON,))


def test_the_plain_reason_is_one_that_can_be_shown():
    assert NO_REASON == "outside text was read (the app gave no reason that can be shown)"
    assert NO_REASON.isprintable() and len(NO_REASON) <= MAX_REASON


def test_no_more_than_eight_reasons_are_kept_and_it_stays_on(hold):
    for number in range(MAX_KEPT + 3):
        hold.on(f"reason {number}")
    assert hold.reasons() == tuple(f"reason {number}" for number in range(MAX_KEPT))
    assert hold.is_on()


def test_exactly_eight_reasons_are_all_kept(hold):
    for number in range(MAX_KEPT):
        hold.on(f"reason {number}")
    assert len(hold.reasons()) == MAX_KEPT


def test_a_kept_reason_given_again_when_full_changes_nothing(hold):
    for number in range(MAX_KEPT):
        hold.on(f"reason {number}")
    hold.on("reason 0")
    assert hold.reasons() == tuple(f"reason {number}" for number in range(MAX_KEPT))


def test_reasons_given_back_cannot_change_the_hold(hold):
    hold.on(PAGE)
    given = hold.reasons()
    assert type(given) is tuple
    hold.off()
    assert given == (PAGE,) and hold.reasons() == ()


def test_two_holds_do_not_share_a_switch():
    one, other = Hold(), Hold()
    one.on(PAGE)
    assert (one.is_on(), other.is_on()) == (True, False)


def test_a_hold_turned_on_in_another_thread_is_on_in_this_one(hold):
    thread = threading.Thread(target=hold.on, args=(PAGE,))
    thread.start()
    thread.join()
    assert hold.reasons() == (PAGE,)


def test_many_threads_turning_it_on_at_once_lose_nothing(hold):
    threads = [threading.Thread(target=hold.on, args=(f"reason {number % MAX_KEPT}",)) for number in range(64)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(hold.reasons()) == [f"reason {number}" for number in range(MAX_KEPT)]


# ---- a level under the hold ----------------------------------------------------


def test_a_free_level_is_free_while_the_hold_is_off(hold):
    level = hold.over(FREE)
    assert level({}) == FREE
    assert level.explain({}) == rules.Verdict(FREE, ())


def test_a_free_level_asks_while_the_hold_is_on(hold):
    level = hold.over(FREE)
    hold.on(PAGE)
    assert level({}) == NEEDS_YES
    assert level.explain({}) == rules.Verdict(NEEDS_YES, (SAID + PAGE,))


def test_a_free_level_is_free_again_after_off(hold):
    level = hold.over(FREE)
    hold.on(PAGE)
    hold.off()
    assert level({}) == FREE


def test_a_level_that_asks_keeps_asking_and_says_why_while_off(hold):
    assert hold.over(NEEDS_YES).explain({}) == rules.Verdict(NEEDS_YES, (OWN_ASK,))


def test_a_level_that_asks_gets_one_more_reason_while_on_and_its_own_comes_first(hold):
    hold.on(PAGE)
    assert hold.over(NEEDS_YES).explain({}) == rules.Verdict(NEEDS_YES, (OWN_ASK, SAID + PAGE))


@pytest.mark.parametrize("on", [False, True])
def test_never_stays_never_with_its_own_reason_only(hold, on):
    if on:
        hold.on(PAGE)
    level = hold.over(NEVER)
    assert level({}) == NEVER
    assert level.explain({}) == rules.Verdict(NEVER, (OWN_NEVER,))


def test_every_reason_the_hold_has_is_given_in_order(hold):
    hold.on(MAIL)
    hold.on(PAGE)
    assert hold.over(FREE).explain({}).reasons == (SAID + MAIL, SAID + PAGE)


def test_the_words_before_a_reason():
    assert SAID == "the app said to ask: "


def test_a_rule_under_the_hold_runs_free_for_a_contact_while_off(hold):
    email = hold.over(email_rule())
    assert email(mail()) == FREE
    assert email.explain(mail()) == email_rule().explain(mail())


def test_a_rule_under_the_hold_asks_for_a_contact_while_on(hold):
    email = hold.over(email_rule())
    hold.on(PAGE)
    assert email.explain(mail()) == rules.Verdict(NEEDS_YES, (SAID + PAGE,))


def test_a_rule_that_asks_keeps_its_reasons_first_and_adds_the_holds(hold):
    email = hold.over(email_rule())
    own = email_rule().explain(mail(STRANGER))
    hold.on(PAGE)
    assert own.level == NEEDS_YES and own.reasons
    assert email.explain(mail(STRANGER)) == rules.Verdict(NEEDS_YES, own.reasons + (SAID + PAGE,))


@pytest.mark.parametrize("on", [False, True])
def test_a_rule_that_says_never_is_not_changed(hold, on):
    if on:
        hold.on(PAGE)
    own = email_rule().explain(mail(BLOCKED))
    assert own.level == NEVER
    assert hold.over(email_rule()).explain(mail(BLOCKED)) == own


def test_inputs_a_rule_cannot_read_still_ask_and_the_hold_adds_its_reason(hold):
    email = hold.over(email_rule())
    assert email.explain("not inputs") == rules.Verdict(NEEDS_YES, ("the inputs cannot be read",))
    hold.on(PAGE)
    assert email.explain("not inputs") == rules.Verdict(NEEDS_YES, ("the inputs cannot be read", SAID + PAGE))


@pytest.mark.parametrize("own, off, on", [(FREE, FREE, NEEDS_YES), (NEEDS_YES, NEEDS_YES, NEEDS_YES), (NEVER, NEVER, NEVER)])
def test_a_function_under_the_hold_is_asked_each_time(hold, own, off, on):
    seen = []

    def by_hand(inputs):
        seen.append(inputs)
        return own

    level = hold.over(by_hand)
    assert level({"a": 1}) == off
    hold.on(PAGE)
    assert level({"a": 2}) == on
    assert seen == [{"a": 1}, {"a": 2}]


def test_a_function_that_asks_gets_a_reason_of_its_own(hold):
    hold.on(PAGE)
    assert hold.over(lambda inputs: NEEDS_YES).explain({}).reasons == (OWN_ASK, SAID + PAGE)
    assert hold.over(lambda inputs: NEVER).explain({}).reasons == (OWN_NEVER,)


@pytest.mark.parametrize("on", [False, True])
@pytest.mark.parametrize("answer", [None, "", "free-ish", "FREE", 0, 1, True, ["free"]], ids=repr)
def test_an_answer_that_is_not_a_level_is_passed_on_as_it_is(hold, on, answer):
    """So the checkpoint refuses it, with the hold on or off. The hold must not turn it into a level."""
    if on:
        hold.on(PAGE)
    level = hold.over(lambda inputs: answer)
    assert level({}) is answer
    assert level.explain({}).reasons == ()


@pytest.mark.parametrize("on", [False, True])
def test_a_function_that_fails_fails_through_the_hold(hold, on):
    if on:
        hold.on(PAGE)

    def broken(inputs):
        raise KeyError("to")

    with pytest.raises(KeyError):
        hold.over(broken)({})


@pytest.mark.parametrize("on", [False, True])
@pytest.mark.parametrize("own", [FREE, NEEDS_YES, NEVER])
@pytest.mark.parametrize("shape", ["level", "function", "over twice"])
def test_a_hold_never_makes_a_level_lower(hold, on, own, shape):
    if on:
        hold.on(PAGE)
    inner = {"level": own, "function": lambda inputs: own, "over twice": Hold().over(own)}[shape]
    assert STRICT[hold.over(inner)({})] >= STRICT[own]


@pytest.mark.parametrize("to", [SAM, STRANGER, BLOCKED])
@pytest.mark.parametrize("on", [False, True])
def test_a_hold_never_makes_a_rule_lower(hold, on, to):
    if on:
        hold.on(PAGE)
    assert STRICT[hold.over(email_rule())(mail(to))] >= STRICT[email_rule()(mail(to))]


def test_a_level_over_a_level_of_the_same_hold_says_the_reason_once(hold):
    hold.on(PAGE)
    assert hold.over(hold.over(FREE)).explain({}) == rules.Verdict(NEEDS_YES, (SAID + PAGE,))


def test_a_level_over_two_holds_asks_when_either_is_on():
    inner, outer = Hold(), Hold()
    level = outer.over(inner.over(FREE))
    assert level({}) == FREE
    inner.on(MAIL)
    assert level.explain({}) == rules.Verdict(NEEDS_YES, (SAID + MAIL,))
    outer.on(PAGE)
    assert level.explain({}) == rules.Verdict(NEEDS_YES, (SAID + MAIL, SAID + PAGE))
    inner.off()
    assert level.explain({}) == rules.Verdict(NEEDS_YES, (SAID + PAGE,))


def test_every_level_made_from_one_hold_follows_the_same_switch(hold):
    one, other = hold.over(FREE), hold.over(email_rule())
    hold.on(PAGE)
    assert (one({}), other(mail())) == (NEEDS_YES, NEEDS_YES)
    hold.off()
    assert (one({}), other(mail())) == (FREE, FREE)


@pytest.mark.parametrize("not_a_level", [None, 5, "", "free-ish", "FREE", b"free", ["free"], (FREE,)], ids=repr)
def test_over_takes_only_a_level_a_rule_or_a_function(hold, not_a_level):
    with pytest.raises(RulesError, match=OVER_ERROR):
        hold.over(not_a_level)


def test_over_does_not_take_text_that_only_equals_a_level(hold):
    class Text(str):
        pass

    with pytest.raises(RulesError, match=OVER_ERROR):
        hold.over(Text(FREE))


# ---- what the approval says ------------------------------------------------------


def test_why_says_it_runs_without_asking_while_off(hold):
    assert hold.over(FREE).why({}) == "Runs without asking: nothing unusual was found"


def test_why_gives_the_rules_own_words_while_off(hold):
    assert hold.over(email_rule()).why(mail()) == email_rule().why(mail())
    assert hold.over(email_rule()).why(mail(STRANGER)) == email_rule().why(mail(STRANGER))


def test_why_says_the_app_said_to_ask_while_on(hold):
    hold.on(PAGE)
    assert hold.over(FREE).why({}) == "Asks because: the app said to ask: a web page was read"
    assert hold.over(email_rule()).why(mail()) == "Asks because: the app said to ask: a web page was read"


def test_why_gives_the_rules_reason_first_and_then_the_holds(hold):
    hold.on(PAGE)
    assert hold.over(email_rule()).why(mail(STRANGER)) == email_rule().why(mail(STRANGER)) + "; the app said to ask: a web page was read"


def test_why_for_a_level_that_always_asks(hold):
    assert hold.over(NEEDS_YES).why({}) == "Asks because: this tool's own level says to ask"
    assert hold.over(NEVER).why({}) == "Never allowed: this tool's own level never allows it"


def test_why_writes_out_four_reasons_and_counts_the_rest(hold):
    for number in range(6):
        hold.on(f"reason {number}")
    assert hold.over(FREE).why({}) == (
        "Asks because: the app said to ask: reason 0; the app said to ask: reason 1; "
        "the app said to ask: reason 2; the app said to ask: reason 3; and 2 more"
    )


# ---- what the checkpoint's digest sees --------------------------------------------


def test_a_level_under_a_hold_has_a_name_that_says_so(hold):
    assert hold.over(FREE).__qualname__.startswith("kettle.rules.hold:")
    assert hold.over(FREE).kind == "hold"


def test_the_name_changes_with_what_is_under_the_hold(hold):
    names = {hold.over(inner).__qualname__ for inner in (FREE, NEEDS_YES, NEVER, email_rule(), rules.email(contacts=[STRANGER]), len)}
    assert len(names) == 6


def test_the_name_does_not_change_with_the_switch_or_the_hold(hold):
    before = hold.over(email_rule()).__qualname__
    hold.on(PAGE)
    assert hold.over(email_rule()).__qualname__ == before == Hold().over(email_rule()).__qualname__


def test_settings_say_what_is_under_the_hold(hold):
    assert hold.over(NEEDS_YES).settings() == {"over": NEEDS_YES}
    assert hold.over(email_rule()).settings() == {"over": "rule:" + email_rule().__qualname__}
    assert hold.over(len).settings() == {"over": "rule:len"}


def test_a_function_with_no_name_is_named_by_its_kind(hold):
    assert hold.over(functools.partial(lambda level, inputs: level, FREE)).settings() == {"over": "rule:partial"}


def test_a_level_under_a_hold_cannot_be_changed_after_it_is_made(hold):
    level = hold.over(FREE)
    with pytest.raises(AttributeError):
        level._hold = Hold()
    with pytest.raises(AttributeError):
        del level._inner


# ---- a tool that brings outside text in --------------------------------------------


def test_running_a_marked_function_turns_the_hold_on(hold):
    fetch = hold.reads(lambda url: f"text of {url}", PAGE)
    assert hold.is_on() is False
    assert fetch(url="https://example.com") == "text of https://example.com"
    assert hold.reasons() == (PAGE,)


def test_marking_a_function_does_not_turn_the_hold_on(hold):
    hold.reads(lambda url: url, PAGE)
    assert hold.is_on() is False


def test_a_marked_function_is_given_what_it_was_called_with(hold):
    def join(first, second="b", *more, **named):
        return first, second, more, named

    assert hold.reads(join, PAGE)("a", "c", "d", key="e") == ("a", "c", ("d",), {"key": "e"})


def test_the_hold_is_on_before_the_function_is_called(hold):
    seen = []
    hold.reads(lambda: seen.append(hold.reasons()), PAGE)()
    assert seen == [(PAGE,)]


def test_the_hold_is_on_even_when_the_function_fails(hold):
    def broken(url):
        raise OSError("the site is down")

    with pytest.raises(OSError):
        hold.reads(broken, PAGE)(url="https://example.com")
    assert hold.reasons() == (PAGE,)


def test_each_run_after_off_turns_it_on_again(hold):
    fetch = hold.reads(lambda: "text", PAGE)
    fetch()
    hold.off()
    assert hold.is_on() is False
    fetch()
    assert hold.reasons() == (PAGE,)


def test_two_marked_functions_give_two_reasons(hold):
    hold.reads(lambda: "mail", MAIL)()
    hold.reads(lambda: "page", PAGE)()
    assert hold.reasons() == (MAIL, PAGE)


def test_a_marked_function_keeps_its_name_and_its_inputs(hold):
    def fetch(url, timeout=10):
        """Read a page."""

    marked = hold.reads(fetch, PAGE)
    assert (marked.__name__, marked.__doc__) == ("fetch", "Read a page.")
    assert inspect.signature(marked) == inspect.signature(fetch)


def test_a_marked_function_that_is_async_turns_the_hold_on_when_called(hold):
    async def fetch(url):
        return url

    waiting = hold.reads(fetch, PAGE)(url="https://example.com")
    assert inspect.iscoroutine(waiting)
    waiting.close()
    assert hold.reasons() == (PAGE,)


class _Site:
    def fetch(self, url):
        return url

    def __call__(self, url):
        return url


@pytest.mark.parametrize(
    "not_plain",
    [None, "fetch", len, _Site, _Site(), _Site().fetch, functools.partial(lambda url, key: url, key="k")],
    ids=["nothing", "text", "built in", "class", "object", "method", "partial"],
)
def test_reads_takes_only_a_plain_function(hold, not_plain):
    """A method or a partial has inputs the app already set. A wrapper would hide that from the checkpoint."""
    with pytest.raises(RulesError, match=READS_ERROR):
        hold.reads(not_plain, PAGE)
    assert hold.is_on() is False


@pytest.mark.parametrize("reason", NOT_A_REASON, ids=repr)
def test_reads_refuses_a_reason_that_cannot_be_shown(hold, reason):
    with pytest.raises(RulesError, match=REASON_ERROR):
        hold.reads(lambda: None, reason)


def test_reads_takes_the_longest_reason(hold):
    hold.reads(lambda: None, "x" * MAX_REASON)()
    assert hold.reasons() == ("x" * MAX_REASON,)


# ---- with a real checkpoint -------------------------------------------------------


class Desk:
    """A checkpoint with one tool that reads outside text and tools that act."""

    def __init__(self, path, clock):
        self.hold = Hold()
        self.sent, self.notes, self.fetched = [], [], []
        self.email = self.hold.over(email_rule())
        self.cp = Checkpoint(path, hold_seconds=600, clock=clock)
        self.cp.tool("send_email", self.send, level=self.email, describe=self.email.why, watch=["to"])
        self.cp.tool("add_note", self.note, level=self.hold.over(FREE))
        self.cp.tool("wipe", self.note, level=self.hold.over(NEVER))
        self.cp.tool("fetch", self.hold.reads(self._fetch_function(), PAGE), level=FREE, watch=["url"])
        self.cp.tool("open_mail", self.hold.reads(self._fetch_function(), MAIL), level=NEEDS_YES)

    def send(self, to, body):
        self.sent.append(to)
        return "sent"

    def note(self, text):
        self.notes.append(text)
        return "noted"

    def _fetch_function(self):
        def fetch(url):
            self.fetched.append(url)
            return f"text of {url}"

        return fetch


@pytest.fixture
def desk(db_path, clock):
    desk = Desk(db_path, clock)
    yield desk
    desk.cp.close()


def test_before_anything_is_read_an_email_to_a_contact_runs(desk):
    assert desk.cp.request("send_email", mail()).status == RAN
    assert desk.sent == [SAM]


def test_after_a_page_is_read_the_same_email_is_held_and_not_sent(desk):
    assert desk.cp.request("fetch", {"url": "https://example.com"}).status == RAN
    held = desk.cp.request("send_email", mail())
    assert held.status == HELD
    assert desk.sent == []
    assert "the app said to ask" in held.preview


def test_after_a_page_is_read_a_free_tool_under_the_hold_is_held(desk):
    desk.cp.request("fetch", {"url": "https://example.com"})
    assert desk.cp.request("add_note", {"text": "buy milk"}).status == HELD
    assert desk.notes == []


def test_a_tool_that_is_not_under_the_hold_still_runs(desk):
    desk.cp.request("fetch", {"url": "https://example.com"})
    assert desk.cp.request("fetch", {"url": "https://example.org"}).status == RAN
    assert desk.fetched == ["https://example.com", "https://example.org"]


def test_the_owners_yes_runs_the_held_email_once(desk):
    desk.cp.request("fetch", {"url": "https://example.com"})
    held = desk.cp.request("send_email", mail())
    desk.cp.approve(held.request_id, held.fingerprint)
    assert desk.cp.run(held.request_id).status == RAN
    assert desk.sent == [SAM]
    assert desk.hold.is_on(), "a yes for one action must not turn the hold off for the next"
    assert desk.cp.request("send_email", mail()).status == HELD


def test_after_off_the_email_runs_again(desk):
    desk.cp.request("fetch", {"url": "https://example.com"})
    desk.hold.off()
    assert desk.cp.request("send_email", mail()).status == RAN
    assert desk.sent == [SAM]


def test_an_email_held_while_on_still_needs_its_yes_after_off(desk):
    desk.cp.request("fetch", {"url": "https://example.com"})
    held = desk.cp.request("send_email", mail())
    desk.hold.off()
    assert desk.sent == []
    assert desk.cp.run(held.request_id).status != RAN
    assert desk.sent == []


def test_a_never_tool_is_refused_with_the_hold_on_or_off(desk):
    assert desk.cp.request("wipe", {"text": "all"}).status == REFUSED
    desk.cp.request("fetch", {"url": "https://example.com"})
    assert desk.cp.request("wipe", {"text": "all"}).status == REFUSED
    assert desk.notes == []


def test_a_blocked_address_is_refused_with_the_hold_on(desk):
    desk.cp.request("fetch", {"url": "https://example.com"})
    assert desk.cp.request("send_email", mail(BLOCKED)).status == REFUSED
    assert desk.sent == []


def test_a_read_that_is_refused_does_not_turn_the_hold_on(desk):
    assert desk.cp.request("fetch", {"address": "https://example.com"}).status == REFUSED
    assert desk.cp.request("fetch", {"url": "https://example.com", "extra": 1}).status == REFUSED
    assert (desk.hold.is_on(), desk.fetched) == (False, [])


def test_a_read_that_is_held_turns_the_hold_on_only_when_it_runs(desk):
    held = desk.cp.request("open_mail", {"url": "inbox/1"})
    assert (held.status, desk.hold.is_on()) == (HELD, False)
    desk.cp.approve(held.request_id, held.fingerprint)
    assert desk.hold.is_on() is False
    assert desk.cp.run(held.request_id).status == RAN
    assert desk.hold.reasons() == (MAIL,)
    assert desk.cp.request("send_email", mail()).status == HELD


def test_the_checkpoint_still_reads_a_marked_tools_inputs(db_path, clock):
    """watch names are checked against the function's inputs when a tool is listed."""
    hold = Hold()
    cp = Checkpoint(db_path, hold_seconds=600, clock=clock)
    cp.tool("fetch", hold.reads(lambda url: url, PAGE), level=NEEDS_YES, watch=["url"])
    with pytest.raises(RulesError):
        cp.tool("other", hold.reads(lambda url: url, PAGE), level=NEEDS_YES, watch=["address"])
    assert cp.request("fetch", {"url": "https://example.com"}).first_time == ("url",)
    cp.close()


def test_the_rules_digest_says_a_hold_is_in_use(db_path, clock):
    digests = []
    for level in (FREE, Hold().over(FREE), Hold().over(FREE), Hold().over(NEEDS_YES)):
        cp = Checkpoint(db_path, hold_seconds=600, clock=clock)
        cp.tool("add_note", lambda text: text, level=level)
        digests.append(cp.rules_digest())
        cp.close()
    assert digests[0] != digests[1] == digests[2] != digests[3]


def test_an_answer_that_is_not_a_level_is_refused_by_the_checkpoint_with_the_hold_on(db_path, clock):
    hold = Hold()
    ran = []
    cp = Checkpoint(db_path, hold_seconds=600, clock=clock)
    cp.tool("add_note", ran.append, level=hold.over(lambda inputs: "free-ish"))
    cp.tool("other", ran.append, level=hold.over(lambda inputs: inputs["missing"]))
    hold.on(PAGE)
    assert cp.request("add_note", {"object": "x"}).status == REFUSED
    assert cp.request("other", {"object": "x"}).status == REFUSED
    assert ran == []
    cp.close()
