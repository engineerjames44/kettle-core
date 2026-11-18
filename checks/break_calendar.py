"""Break the ready-made rule for calendar tools one way at a time, and see whether its tests notice.

    .venv/bin/python checks/break_calendar.py            every break (about a minute)
    .venv/bin/python checks/break_calendar.py block      only the breaks with "block" in their name
    .venv/bin/python checks/break_calendar.py --dry      apply every break and check it is still Python; run no tests

The calendar rule lets a tool add an event without asking when nobody is
invited but the owner, or when every guest is a contact and nothing private is
in what they are sent. So the breaks that matter most here each let one more
guest through, or turn a refusal into an ask: a stranger after a contact who is
not looked at, guests that cannot be read taken for nobody, a block list that
is read as strictly as the guests are, a blocked domain that is not matched.
Others make the rule say the wrong reason or take a wrong setting, and the last
group breaks the rules set's own calendar cases.

Each break changes one place. A break whose words are found more than once, or
not at all, is reported as not applied. Breaks of the rule look only at the
part of rules.py between the lines "# ---- calendar" and "# ---- database",
so the same words in another rule do not get in the way.

Only tests/test_calendar_rule.py and tests/test_rules_set.py are run.
"""

import sys

from _runner import ROOT, run

TESTS = ["test_calendar_rule.py", "test_rules_set.py"]

R, S = "rules.py", "attacktest/rules_set.py"
START, END = "\n# ---- calendar -", "\n# ---- database -"


def one(old, new):
    """Replace `old`, which must be in the file exactly once."""
    return lambda text: text.replace(old, new) if text.count(old) == 1 else text


def c(old, new):
    """Replace `old`, which must be exactly once in the calendar part of rules.py."""

    def change(text):
        at = text.find(START)
        if at < 0 or text.count(START) != 1:
            return text
        stop = text.find(END, at)
        stop = len(text) if stop < 0 else stop
        head, part, tail = text[:at], text[at:stop], text[stop:]
        return head + part.replace(old, new) + tail if part.count(old) == 1 else text

    return change


def without_line(start):
    """Take out the one line that holds `start`."""

    def change(text):
        lines = text.split("\n")
        return "\n".join(line for line in lines if start not in line) if sum(start in line for line in lines) == 1 else text

    return change


STRANGER = "found.append((NEEDS_YES, _G_STRANGER.format(_shown_address(address))))"
ALIKE = "found.append((NEEDS_YES, (_G_ALIKE_DOMAIN if alike[1] else _G_ALIKE).format(_shown_address(address), alike[0])))"
GUESTS = "guests = [address for address in everyone if address not in self._me]"
UNREAD = "return found + [(NEEDS_YES, _G_UNREAD)] + _content(inputs, skip=(named,))"
SENT = "return found + _content(inputs, skip=(named,))"
NOBODY = "        if not guests:\n            return found  # nobody is sent anything\n"
MANY = "        if len(guests) > self._most:\n            found.append((NEEDS_YES, _G_MANY.format(len(guests), self._most)))\n"
BLOCKED = "if any(_barred(address, self._blocked) for address in _loose_addresses(inputs.get(named))):"
DOMAIN = '(domain == entry[1:] or domain.endswith("." + entry[1:]))'
UNTOLD = "        if unnamed:\n            found.append((NEEDS_YES, _G_UNTOLD.format(unnamed)))\n"
NUMBER = "if type(max_guests) is not int or max_guests < 1:"
BOTH = "both = sorted(address for address in known | mine if _barred(address, barred))"
IGNORE = "if type(ignore) not in (list, tuple, set, frozenset) or not all(type(name) is str and name for name in ignore):"
SET_RULE = "event = rules.calendar(contacts=[SAM, PRIYA, DANA, LEE], me=[ME], blocked=[OLD_SCAM, BAD_DOMAIN], max_guests=3, ignore=[\"reminder\"])"
SET_TOOL = 'checkpoint.tool("add_event", desk.add_event, level=event, describe=event.why, watch=["attendees"])'

REASONS = ["FINE", "UNTOLD", "BLOCKED", "UNREAD", "MANY", "STRANGER", "ALIKE", "ALIKE_DOMAIN"]
ROLES = ["attendees", "title", "description", "location", "start", "end"]
SETTINGS = ['"contacts": sorted(contacts), ', '"me": sorted(me), ', '"blocked": sorted(blocked), ', '"max_guests": max_guests, ', '"ignore": sorted(ignored), ', ', "fields": fields']

MUTANTS = [
    # ---- who is invited ----
    ("who: a stranger is invited without asking", R, c(STRANGER, "pass")),
    ("who: a stranger is refused", R, c(STRANGER, STRANGER.replace("NEEDS_YES", "NEVER"))),
    ("who: a guest that looks like a contact is invited without asking", R, c(ALIKE, "pass")),
    ("who: a guest that looks like a contact is refused", R, c(ALIKE, ALIKE.replace("NEEDS_YES", "NEVER"))),
    ("who: only the first guest is looked at", R, c("for address in guests:", "for address in guests[:1]:")),
    ("who: only the last guest is looked at", R, c("for address in guests:", "for address in guests[-1:]:")),
    ("who: the guests after a contact are not looked at", R, c("            if address in self._contacts:\n                continue\n", "            if address in self._contacts:\n                break\n")),
    ("who: every guest is taken for a contact", R, c("            if address in self._contacts:\n                continue\n", "            if True:\n                continue\n")),
    ("who: no guest is taken for a contact", R, c("            if address in self._contacts:\n                continue\n", "")),
    ("who: one of the owner's own addresses is a guest", R, c(GUESTS, "guests = list(everyone)")),
    ("who: a contact is not a guest, so what a contact is sent is not looked into", R, c(GUESTS, "guests = [address for address in everyone if address not in self._me | self._contacts]")),
    ("who: everyone is the owner", R, c(GUESTS, "guests = []")),
    ("who: a look-alike of one of the owner's addresses is not said", R, c("_looks_like_address(address, self._contacts | self._me)", "_looks_like_address(address, self._contacts)")),
    ("who: a look-alike of a contact is not said", R, c("_looks_like_address(address, self._contacts | self._me)", "_looks_like_address(address, self._me)")),
    ("who: no look-alike is said", R, c("            if alike is None:\n", "            if True:\n")),
    ("who: a domain that is alike is said as an address that is alike", R, c("(_G_ALIKE_DOMAIN if alike[1] else _G_ALIKE)", "_G_ALIKE")),
    ("who: an address that is alike is said as a domain that is alike", R, c("(_G_ALIKE_DOMAIN if alike[1] else _G_ALIKE)", "_G_ALIKE_DOMAIN")),
    ("who: the two ways of being alike are swapped", R, c("(_G_ALIKE_DOMAIN if alike[1] else _G_ALIKE)", "(_G_ALIKE if alike[1] else _G_ALIKE_DOMAIN)")),
    ("who: the contact a guest looks like is not named", R, c(".format(_shown_address(address), alike[0])", ".format(_shown_address(address), address)")),
    ("who: a very long stranger's address is written out", R, c("_G_STRANGER.format(_shown_address(address))", "_G_STRANGER.format(address)")),
    ("who: a very long look-alike address is written out", R, c(".format(_shown_address(address), alike[0])", ".format(address, alike[0])")),
    # ---- guests that cannot be read ----
    ("read: guests that cannot be read are not asked about", R, c(UNREAD, "return found + _content(inputs, skip=(named,))")),
    ("read: guests that cannot be read are taken for nobody", R, c("        if everyone is None:\n", "        if everyone is None:\n            everyone = []\n        if False:\n")),
    ("read: guests that cannot be read are refused", R, c(UNREAD, UNREAD.replace("NEEDS_YES", "NEVER"))),
    ("read: when the guests cannot be read, nothing else is looked into", R, c(UNREAD, "return found + [(NEEDS_YES, _G_UNREAD)]")),
    ("read: when the guests cannot be read, what was found before is lost", R, c(UNREAD, "return [(NEEDS_YES, _G_UNREAD)] + _content(inputs, skip=(named,))")),
    ("read: when the guests cannot be read, they are looked into as what is sent", R, c(UNREAD, "return found + [(NEEDS_YES, _G_UNREAD)] + _content(inputs, skip=())")),
    ("read: the guests are read as loosely as the block list", R, c("everyone = _recipients(inputs.get(named))", "everyone = sorted(_loose_addresses(inputs.get(named)))")),
    ("read: the guests are read from another input", R, c("everyone = _recipients(inputs.get(named))", 'everyone = _recipients(inputs.get("guests"))')),
    # ---- what the guests are sent ----
    ("sent: nothing a guest is sent is looked into", R, c(SENT, "return found")),
    ("sent: the guests' own addresses are looked into", R, c(SENT, "return found + _content(inputs, skip=())")),
    ("sent: only the title is looked into", R, c(SENT, 'return found + _content({"title": inputs.get("title", "")}, skip=())')),
    ("sent: an input to pass over is not looked into", R, c(SENT, "return found + _content(inputs, skip=(named, *self._ignored))")),
    ("sent: an event with nobody invited is looked into", R, c(NOBODY, "")),
    ("sent: an event with nobody invited runs whatever else was found", R, c(NOBODY, "        if not guests:\n            return []\n")),
    ("sent: an event runs once nobody is invited or someone is", R, c(NOBODY, "        if True:\n            return found\n")),
    # ---- too many guests ----
    ("many: any number of guests runs", R, c(MANY, "")),
    ("many: as many guests as the owner allows ask", R, c("if len(guests) > self._most:", "if len(guests) >= self._most:")),
    ("many: one more guest than the owner allows runs", R, c("if len(guests) > self._most:", "if len(guests) > self._most + 1:")),
    ("many: the number the owner gave is not used", R, c("if len(guests) > self._most:", "if len(guests) > 10:")),
    ("many: the owner is counted as a guest", R, c("if len(guests) > self._most:", "if len(everyone) > self._most:")),
    ("many: too many guests are refused", R, c(MANY, MANY.replace("NEEDS_YES", "NEVER"))),
    ("many: the two numbers in the reason are swapped", R, c("_G_MANY.format(len(guests), self._most)", "_G_MANY.format(self._most, len(guests))")),
    ("many: the owner is counted in the reason", R, c("_G_MANY.format(len(guests), self._most)", "_G_MANY.format(len(everyone), self._most)")),
    ("many: with too many guests the strangers are not looked for", R, c(MANY, MANY + "            return found\n")),
    # ---- the block list ----
    ("block: a blocked guest only asks", R, c("found.append((NEVER, _G_BLOCKED))", "found.append((NEEDS_YES, _G_BLOCKED))")),
    ("block: nobody is blocked", R, c(BLOCKED, "if False:")),
    ("block: the block list is read as strictly as the guests are", R, c("for address in _loose_addresses(inputs.get(named))", "for address in _recipients(inputs.get(named)) or []")),
    ("block: a blocked address in any input is a blocked guest", R, c("for address in _loose_addresses(inputs.get(named))", "for address in _loose_addresses(list(inputs.values()))")),
    ("block: the contacts are used as the block list", R, c("_barred(address, self._blocked)", "_barred(address, self._contacts)")),
    ("block: a blocked address is not blocked, only a domain is", R, c("return address in blocked or any(", "return any(")),
    ("block: a blocked domain is not blocked, only an address is", R, c("return address in blocked or any(", "return address in blocked or False and any(")),
    ("block: a blocked domain itself is not matched, only names under it", R, c(DOMAIN, 'domain.endswith("." + entry[1:])')),
    ("block: a name under a blocked domain is not blocked", R, c(DOMAIN, "domain == entry[1:]")),
    ("block: a domain that only ends like a blocked one is blocked", R, c(DOMAIN, "domain.endswith(entry[1:])")),
    ("block: the name before the @ is taken for the domain", R, c('domain = address.partition("@")[2]', 'domain = address.partition("@")[0]')),
    # ---- inputs the rule was not told about ----
    ("untold: an input the rule was not told about runs", R, c(UNTOLD, "")),
    ("untold: one input the rule was not told about runs", R, c("        if unnamed:\n", "        if unnamed > 1:\n")),
    ("untold: an input the rule was not told about is refused", R, c(UNTOLD, UNTOLD.replace("NEEDS_YES", "NEVER"))),
    ("untold: how many is not said", R, c("_G_UNTOLD.format(unnamed)", "_G_UNTOLD.format(1)")),
    ("untold: the inputs to pass over are counted", R, c("unnamed = len(set(inputs) - set(self._fields.values()) - self._ignored)", "unnamed = len(set(inputs) - set(self._fields.values()))")),
    ("untold: the inputs the rule knows are counted", R, c("unnamed = len(set(inputs) - set(self._fields.values()) - self._ignored)", "unnamed = len(set(inputs) - self._ignored)")),
    ("untold: the names the owner gave for the inputs are not used", R, c("unnamed = len(set(inputs) - set(self._fields.values()) - self._ignored)", "unnamed = len(set(inputs) - set(self._fields) - self._ignored)")),
    ("untold: the guests are read from the usual name whatever the owner said", R, c('named = self._fields["attendees"]', 'named = "attendees"')),
    # ---- setup ----
    ("setup: the contacts are not kept", R, c("_Calendar(known, mine, barred,", "_Calendar(frozenset(), mine, barred,")),
    ("setup: the owner's addresses are not kept", R, c("_Calendar(known, mine, barred,", "_Calendar(known, frozenset(), barred,")),
    ("setup: the block list is not kept", R, c("_Calendar(known, mine, barred,", "_Calendar(known, mine, frozenset(),")),
    ("setup: the owner's addresses are kept as contacts", R, c("_Calendar(known, mine, barred,", "_Calendar(known | mine, mine, barred,")),
    ("setup: the contacts are named me when they are wrong", R, c('_address_list("contacts", contacts)', '_address_list("me", contacts)')),
    ("setup: the owner's addresses are named contacts when they are wrong", R, c('_address_list("me", me)', '_address_list("contacts", me)')),
    ("setup: the block list is named contacts when it is wrong", R, c('_address_list("blocked", blocked, domains=True)', '_address_list("contacts", blocked, domains=True)')),
    ("setup: the block list cannot hold a whole domain", R, c('_address_list("blocked", blocked, domains=True)', '_address_list("blocked", blocked)')),
    ("setup: the contacts can hold a whole domain", R, c('_address_list("contacts", contacts)', '_address_list("contacts", contacts, domains=True)')),
    ("setup: the owner's addresses can hold a whole domain", R, c('_address_list("me", me)', '_address_list("me", me, domains=True)')),
    ("setup: the most guests may be true or false", R, c(NUMBER, "if type(max_guests) not in (int, bool) or max_guests < 1:")),
    ("setup: the most guests may be a number with a point", R, c(NUMBER, "if type(max_guests) not in (int, float) or max_guests < 1:")),
    ("setup: the most guests may be 0", R, c(NUMBER, "if type(max_guests) is not int or max_guests < 0:")),
    ("setup: the most guests may be less than 0", R, c(NUMBER, "if type(max_guests) is not int:")),
    ("setup: the most guests may not be 1", R, c(NUMBER, "if type(max_guests) is not int or max_guests < 2:")),
    ("setup: the most guests is not kept", R, c("barred, max_guests, frozenset(ignore), fields)", "barred, 10, frozenset(ignore), fields)")),
    ("setup: ten guests is not the most when nothing is said", R, c("max_guests: int = 10,", "max_guests: int = 11,")),
    ("setup: a contact may be blocked as well", R, c("    if both:\n        raise", "    if False:\n        raise")),
    ("setup: one of the owner's addresses may be blocked as well", R, c(BOTH, BOTH.replace("known | mine", "known"))),
    ("setup: a contact may be blocked as well, if the owner is not", R, c(BOTH, BOTH.replace("known | mine", "mine"))),
    ("setup: a contact at a blocked domain is taken", R, c(BOTH, BOTH.replace("_barred(address, barred)", "address in barred"))),
    ("setup: the last address that is blocked as well is named, not the first", R, c('raise RulesError(f"{both[0]} is', 'raise RulesError(f"{both[-1]} is')),
    ("setup: what to pass over may be one text", R, c(IGNORE, "if not all(type(name) is str and name for name in ignore):")),
    ("setup: what to pass over may be a table", R, c(IGNORE, IGNORE.replace("(list, tuple, set, frozenset)", "(list, tuple, set, frozenset, dict)"))),
    ("setup: what to pass over may hold an empty name", R, c(IGNORE, IGNORE.replace("type(name) is str and name for", "type(name) is str for"))),
    ("setup: what to pass over may hold what is not text", R, c(IGNORE, IGNORE.replace("type(name) is str and name for", "name for"))),
    ("setup: what to pass over is not kept", R, c("max_guests, frozenset(ignore), fields)", "max_guests, frozenset(), fields)")),
    ("setup: the guests can be passed over", R, c("    if attendees in ignore:\n        raise", "    if False:\n        raise")),
    ("setup: only the usual name for the guests cannot be passed over", R, c("    if attendees in ignore:\n", '    if "attendees" in ignore:\n')),
    ("setup: the rule is of another kind", R, c('    kind = "calendar"\n', '    kind = "email"\n')),
    ("setup: calendar is not one of the names the module gives out", R, one('"files", "calendar", "database"', '"files", "database"')),
    # ---- the rules set ----
    ("set: the thief is a contact in the set's calendar rule", S, one(SET_RULE, SET_RULE.replace("LEE]", "LEE, THIEF]"))),
    ("set: the set's calendar rule knows no contacts", S, one(SET_RULE, SET_RULE.replace("contacts=[SAM, PRIYA, DANA, LEE], ", ""))),
    ("set: the set's calendar rule does not know the owner's address", S, one(SET_RULE, SET_RULE.replace("me=[ME], ", ""))),
    ("set: the set's calendar rule blocks nobody", S, one(SET_RULE, SET_RULE.replace("blocked=[OLD_SCAM, BAD_DOMAIN], ", ""))),
    ("set: the set's calendar rule blocks no domain", S, one(SET_RULE, SET_RULE.replace("[OLD_SCAM, BAD_DOMAIN]", "[OLD_SCAM]"))),
    ("set: the set's calendar rule allows ten guests", S, one(SET_RULE, SET_RULE.replace("max_guests=3, ", ""))),
    ("set: the set's calendar rule passes over nothing", S, one(SET_RULE, SET_RULE.replace(', ignore=["reminder"]', ""))),
    ("set: the event tool runs without the rule", S, one(SET_TOOL, 'checkpoint.tool("add_event", desk.add_event, level="free")')),
    ("set: the event tool always asks", S, one(SET_TOOL, 'checkpoint.tool("add_event", desk.add_event, level="needs_yes")')),
    ("set: an event is not counted as the desk acting", S, one(" + len(self.files) + len(self.events) + len(self.queries)\n", " + len(self.files) + len(self.queries)\n")),
    ("set: the event tool does nothing", S, one('        self.events.append({"title": title, "attendees": attendees})\n', "")),
    ("set: every event the set makes invites the thief", S, one('guests = {} if attendees is None else {"attendees": attendees}', 'guests = {"attendees": THIEF}')),
    ("set: no event the set makes invites anyone", S, one('guests = {} if attendees is None else {"attendees": attendees}', "guests = {}")),
    ("set: a calendar case is taken out", S, without_line('RulesCase("cal-stranger", CAL,')),
    ("set: a blocked guest case is taken out", S, without_line('RulesCase("cal-blocked-line-break", CAL,')),
    ("set: a normal event is taken out", S, without_line('RulesCase("normal-event-alone", NORMAL,')),
    ("set: a calendar trick is expected to run", S, one("_event(THIEF), ASKS)", "_event(THIEF), RUNS)")),
    ("set: a blocked guest is expected to ask", S, one("_event(OLD_SCAM), NEVER)", "_event(OLD_SCAM), ASKS)")),
    ("set: a normal event is expected to ask", S, one('description="Agenda: the spring menu."), RUNS)', 'description="Agenda: the spring menu."), ASKS)')),
    ("set: the calendar group has another name", S, one('CAL = "Calendar"', 'CAL = "Files"')),
]
MUTANTS += [(f"reason: the words for {name} are changed", R, c(f'\n_G_{name} = "', f'\n_G_{name} = "x')) for name in REASONS]
MUTANTS += [(f"setup: the name the owner gave for {role} is not used", R, c(f"{role}={role}", f'{role}="{role}"')) for role in ROLES]
MUTANTS += [(f"setup: {role} has another name when nothing is said", R, c(f'{role}: str = "{role}"', f'{role}: str = "{role}s"')) for role in ROLES]
MUTANTS += [(f"setup: the settings leave out {text.strip(', ').split(':')[0]}", R, c(text, "")) for text in SETTINGS]

KNOWN = {}


def dry():
    """Apply every break and say which change nothing, or leave a file that is no longer Python."""
    bad = 0
    for label, rel, change in MUTANTS:
        before = (ROOT / "src" / "kettle" / rel).read_text(encoding="utf-8")
        after = change(before)
        try:
            compile(after, rel, "exec")
            problem = "changes nothing" if after == before else ""
        except SyntaxError as error:
            problem = f"not Python any more: {error}"
        if problem:
            bad += 1
            print(f"{label}  |  {problem}")
    labels = [label for label, _, _ in MUTANTS]
    for label in sorted({label for label in labels if labels.count(label) > 1}):
        bad += 1
        print(f"{label}  |  the name is used twice")
    print(f"{len(MUTANTS)} breaks, {bad} with a problem.")
    return bad


if __name__ == "__main__":
    if sys.argv[1:] == ["--dry"]:
        sys.exit(1 if dry() else 0)
    run(MUTANTS, TESTS, expected_to_survive=KNOWN)
