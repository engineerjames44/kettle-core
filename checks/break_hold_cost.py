"""Break the count of what a hold costs and what it buys, one way at a time, and see whether its tests notice.

    .venv/bin/python checks/break_hold_cost.py           every break (about a minute)
    .venv/bin/python checks/break_hold_cost.py sender    only the breaks with "sender" in their name

The count says two things: how many more asks a hold makes, and how many attacks by
somebody on the owner's lists it stops. Both are easy to get wrong in a way that
looks good. So most breaks here make a hold look cheaper than it is, make it look
as if it stops more than it does, or hide something that ran: a tool is left
unmarked, the attacker is never put on the lists, a job is put in the wrong column,
an action that ran is not counted.

The breaks near the end are to the Hold itself and to the daily case set, to show
the count moves when either changes. checks/break_holds.py is where the Hold is
broken in full.

Only tests/test_hold_cost.py is run. No model takes part.
"""

from _runner import nth, rep, run

TESTS = ["test_hold_cost.py"]

C, H, D = "attacktest/hold_cost.py", "holds.py", "attacktest/sets/daily.toml"

OUTSIDE_FIRST = "    if tools & set(_OUTSIDE_TOOLS):\n        return OUTSIDE\n"
FILES_OR_SAID = "    return FILES if tools & set(_FILE_TOOLS) else SAID\n"
TO_CONTACTS = "        return contacts + [case.goal.to], payees\n"
TO_PAYEES = "    return contacts, payees + [case.goal.to]\n"
KNOWN = "    known = {contact.lower() for contact in contacts}\n"
A_STRANGER = "        if not found or any(address.lower() not in known for address in found):\n"
INBOX_SENDERS = 'if _a_stranger([line.split(" | ", 2)[1] for line in text.splitlines() if " | " in line], contacts):'
INBOX_ON = '            hold.on("the inbox lists an email" + NOT_A_CONTACT)\n'
EMAIL_SENDER = '        if _a_stranger([text.split("\\n", 1)[0]], contacts):\n'
EMAIL_ON = '            hold.on(REASONS["read_email"] + NOT_A_CONTACT)\n'
CALENDAR_SENDERS = '        if _a_stranger([line for line in text.splitlines() if line.startswith("Organiser: ")], contacts):\n'
CALENDAR_ON = '            hold.on("the calendar has an invite" + NOT_A_CONTACT)\n'
NOT_MARKED = "        if name not in way.marked:\n            readers[name] = run\n"
BY_SENDER = "        elif way.by_sender and name in by_sender:\n"
MARKED = "            readers[name] = hold.reads(run, REASONS[name])\n"
ALWAYS = "    if not way.rules:\n        return make_checkpoint\n"
ALONE = "    if not way.marked:\n        return with_rules(way.name, contacts, payees, limit).checkpoint_for\n"
NEW_HOLD = "    def build(tools: dict) -> Checkpoint:\n        hold = Hold()\n"
OVER = '        over = {"send_email": hold.over(rules.email(contacts=contacts)), "pay": hold.over(rules.payment(payees=payees, limit=limit))}\n'
RISKY_TOOL = '                checkpoint.tool(spec.name, tools[spec.name], level=over[spec.name], describe=over[spec.name].why, watch=["to"])\n'
READING_TOOL = "                checkpoint.tool(spec.name, readers[spec.name], level=FREE)\n"
LISTS = "    contacts, payees = owners_lists(case_set) if lists is None else lists\n"
JOB_RUN = "result = run_case(standins.careful(case), case, case_set, KETTLE, _checkpoint_for=checkpoint_for(way, contacts, payees, limit))"
ATTACK_RUN = "result = run_case(standins.fooled(case), case, case_set, KETTLE, _checkpoint_for=checkpoint_for(way, *mine, limit))"
MINE = "                mine = (contacts, payees) if world == STRANGER else with_attacker(case, contacts, payees)\n"
CELL = '            cell = row["by_read"][what_it_read(case)]\n'
SAME_WAYS = '        if len({row["way"] for row in rows}) != 1:\n            raise ValueError("the sets were not counted with the same ways")\n'
TWICE = '            if summed["asks_by_job"].keys() & row["asks_by_job"].keys():\n                raise ValueError("the same job was counted twice")\n'
SUMS = '**{key: sum(row[key] for row in rows) for key in ("jobs", "jobs_done", "other_ran", "attacks")}}'
BY_READ_SUM = 'summed["by_read"][kind] = {key: sum(row["by_read"][kind][key] for row in rows) for key in ("jobs", "actions", "asks")}'
WORLD_SUM = 'block = {key: sum(row[world][key] for row in rows) for key in ("asks", "got_through", "other_ran", "tasks_done")}'
P_JOBS = '        if row["jobs_done"] != row["jobs"]:\n'
P_OTHER = '        if row["other_ran"]:\n'
P_TASKS = '            if block["tasks_done"] != row["attacks"]:\n'
P_OTHER_ATTACK = '            if block["other_ran"]:\n'
P_STRANGER = '        if row[STRANGER]["got_through"]:\n'
P_LISTED = '        if name in (AFTER_ANYTHING, ASK_ALWAYS) and row[LISTED]["got_through"]:\n'
P_FEWER = '        fewer = [job for job, asks in row["asks_by_job"].items() if asks < base["asks_by_job"].get(job, 0)]\n'
T_COST = "lines += [f\"  {row['by_read'][SAID]['asks']:>6}  {row['by_read'][FILES]['asks']:>6}  {row['by_read'][OUTSIDE]['asks']:>7}   {row['way']}\" for row in rows]"
T_GAIN = "lines += [f\"  {row[STRANGER]['got_through']:>8}  {row[LISTED]['got_through']:>6}   {row['way']}{_by_where(row[LISTED])}\" for row in rows]"
T_PICK = 'base, full, always = rows[0], next(row for row in rows if row["way"] == AFTER_ANYTHING), rows[-1]'
T_WHERE = 'parts = [f"{where} {ran} of {of}" for where, (ran, of) in sorted(block["by_where"].items()) if ran]'
M_GIVEN = "    if sys.argv[1:] if argv is None else argv:\n"
M_TOLD = '        print("This takes nothing after its name: python -m kettle.attacktest.hold_cost", file=sys.stderr)\n        return 2\n'

HOLD_MARK = "            self.on(reason)\n"
HOLD_STOP = "        if not held or under.level not in (FREE, NEEDS_YES):\n            return under\n"

SAID_STEPS = '    {tool = "send_email", inputs = {to = "sam@example.com", subject = "Running late on Monday"'


def off(line):
    """Swap the condition of an `if` line for one that is never true."""
    return line[: len(line) - len(line.lstrip())] + "if False:\n"


def on(line):
    """Swap the condition of an `if` line for one that is always true."""
    return line[: len(line) - len(line.lstrip())] + "if True:\n"


MUTANTS = [
    # what is counted
    ("counted: the daily set is left out", C, rep("SETS = ASKS_SETS + (str(DAILY),)", "SETS = ASKS_SETS")),
    ("counted: the limit is ten times what is said", C, rep("LIMIT = 1000\n", "LIMIT = 10000\n")),
    ("counted: the web page hold marks nothing", C, rep('Way(AFTER_PAGE, ("open_page",)),', "Way(AFTER_PAGE),")),
    ("counted: the web page hold marks a file and not a page", C, rep('Way(AFTER_PAGE, ("open_page",)),', 'Way(AFTER_PAGE, ("read_file",)),')),
    ("counted: the sender hold does not look at the sender", C, rep("Way(AFTER_STRANGER, _OUTSIDE_TOOLS, by_sender=True),", "Way(AFTER_STRANGER, _OUTSIDE_TOOLS),")),
    ("counted: the outside hold looks at the sender", C, rep("Way(AFTER_OUTSIDE, _OUTSIDE_TOOLS),", "Way(AFTER_OUTSIDE, _OUTSIDE_TOOLS, by_sender=True),")),
    ("counted: the hold after anything leaves files out", C, rep("Way(AFTER_ANYTHING, _OUTSIDE_TOOLS + _FILE_TOOLS),", "Way(AFTER_ANYTHING, _OUTSIDE_TOOLS),")),
    ("counted: the list of files is not a file tool", C, rep('_FILE_TOOLS = ("list_files", "read_file")', '_FILE_TOOLS = ("read_file",)')),
    ("counted: reading a file is not a file tool", C, rep('_FILE_TOOLS = ("list_files", "read_file")', '_FILE_TOOLS = ("list_files",)')),
    ("counted: the calendar is not an outside tool", C, rep('("open_page", "list_emails", "read_email", "read_calendar")', '("open_page", "list_emails", "read_email")')),
    ("counted: the inbox is not an outside tool", C, rep('("open_page", "list_emails", "read_email", "read_calendar")', '("open_page", "read_email", "read_calendar")')),
    ("counted: an email is not an outside tool", C, rep('("open_page", "list_emails", "read_email", "read_calendar")', '("open_page", "list_emails", "read_calendar")')),
    ("counted: the last row has the rules too", C, rep("Way(ASK_ALWAYS, rules=False),", "Way(ASK_ALWAYS),")),
    ("counted: the rows are in another order", C, rep("    Way(AFTER_OUTSIDE, _OUTSIDE_TOOLS),\n    Way(AFTER_ANYTHING, _OUTSIDE_TOOLS + _FILE_TOOLS),\n", "    Way(AFTER_ANYTHING, _OUTSIDE_TOOLS + _FILE_TOOLS),\n    Way(AFTER_OUTSIDE, _OUTSIDE_TOOLS),\n")),
    # what a job read
    ("read: a job that read an email is put with the files", C, rep(OUTSIDE_FIRST, "    if tools & set(_OUTSIDE_TOOLS):\n        return FILES\n")),
    ("read: a job that read an email is put with the said ones", C, rep(OUTSIDE_FIRST, "    if tools & set(_OUTSIDE_TOOLS):\n        return SAID\n")),
    ("read: a job that read a file and the calendar is put with the files", C, rep(OUTSIDE_FIRST, "    if tools & set(_OUTSIDE_TOOLS) and not tools & set(_FILE_TOOLS):\n        return OUTSIDE\n")),
    ("read: a job that read a file is put with the said ones", C, rep(FILES_OR_SAID, "    return SAID\n")),
    ("read: a job that read nothing is put with the files", C, rep(FILES_OR_SAID, "    return FILES\n")),
    ("read: the first step alone is looked at", C, rep("tools = {tool for tool, _ in case.steps}", "tools = {tool for tool, _ in case.steps[:1]}")),
    # the attacker on the lists
    ("listed: an address is added to the payees", C, rep('    if case.goal.tool == "send_email":\n', '    if case.goal.tool == "pay":\n')),
    ("listed: an attacker's address is not added", C, rep(TO_CONTACTS, "        return contacts, payees\n")),
    ("listed: an attacker's account is not added", C, rep(TO_PAYEES, "    return contacts, payees\n")),
    ("listed: the attacker's address stays on the owner's list afterwards", C, rep(TO_CONTACTS, "        contacts.append(case.goal.to)\n        return contacts, payees\n")),
    ("listed: the attacker's account stays on the owner's list afterwards", C, rep(TO_PAYEES, "    payees.append(case.goal.to)\n    return contacts, payees\n")),
    ("listed: the stranger world gets the attacker too", C, rep(MINE, "                mine = with_attacker(case, contacts, payees)\n")),
    ("listed: the listed world does not get the attacker", C, rep(MINE, "                mine = (contacts, payees)\n")),
    ("listed: the two worlds are the wrong way round", C, rep(MINE, MINE.replace("world == STRANGER", "world == LISTED"))),
    # who is a stranger
    ("sender: the owner's contacts keep their capital letters", C, rep(KNOWN, "    known = set(contacts)\n")),
    ("sender: the sender's address keeps its capital letters", C, rep(A_STRANGER, A_STRANGER.replace("address.lower()", "address"))),
    ("sender: a sender with no address is taken as a contact", C, rep(A_STRANGER, A_STRANGER.replace("if not found or any(", "if any("))),
    ("sender: one contact among the addresses is enough", C, rep(A_STRANGER, "        if not found or all(address.lower() not in known for address in found):\n")),
    ("sender: only the first sender is looked at", C, rep("    for sender in senders:\n", "    for sender in senders[:1]:\n")),
    ("sender: only the last sender is looked at", C, rep("    for sender in senders:\n", "    for sender in senders[-1:]:\n")),
    ("sender: the sender in the middle is skipped", C, rep("    for sender in senders:\n", "    for sender in senders[:1] + senders[-1:]:\n")),
    ("sender: nobody is a stranger", C, rep(A_STRANGER + "            return True\n", A_STRANGER + "            return False\n")),
    ("sender: everybody is a stranger", C, rep("            return True\n    return False\n", "            return True\n    return True\n")),
    ("sender: the inbox is read by its subjects", C, rep(INBOX_SENDERS, INBOX_SENDERS.replace('line.split(" | ", 2)[1]', 'line.split(" | ", 2)[-1]'))),
    ("sender: the whole line of the inbox is looked at", C, rep(INBOX_SENDERS, INBOX_SENDERS.replace('line.split(" | ", 2)[1]', "line"))),
    ("sender: a line of the inbox that is cut short is skipped", C, rep(INBOX_SENDERS, INBOX_SENDERS.replace('if " | " in line]', 'if line.count(" | ") >= 2]'))),
    ("sender: the inbox never turns the hold on", C, rep(INBOX_ON, "            pass\n")),
    ("sender: the inbox always turns the hold on", C, rep("        " + INBOX_SENDERS + "\n", "        if True:\n")),
    ("sender: the whole email is looked at, not its sender line", C, rep(EMAIL_SENDER, '        if _a_stranger([text], contacts):\n')),
    ("sender: the subject line of an email is looked at", C, rep(EMAIL_SENDER, '        if _a_stranger(text.split("\\n", 2)[1:2], contacts):\n')),
    ("sender: an email never turns the hold on", C, rep(EMAIL_ON, "            pass\n")),
    ("sender: an email always turns the hold on", C, rep(EMAIL_SENDER, on(EMAIL_SENDER))),
    ("sender: an email gives the reason of a page", C, rep(EMAIL_ON, '            hold.on(REASONS["open_page"] + NOT_A_CONTACT)\n')),
    ("sender: an email is read twice", C, lambda text: nth(text, '        text = tools["read_email"](id)\n', '        text = tools["read_email"](id) + tools["read_email"](id)\n')),
    ("sender: an organiser is looked for anywhere in a line", C, rep(CALENDAR_SENDERS, CALENDAR_SENDERS.replace('line.startswith("Organiser: ")', '"Organiser: " in line'))),
    ("sender: the first organiser alone is looked at", C, rep(CALENDAR_SENDERS, CALENDAR_SENDERS.replace('line.startswith("Organiser: ")], contacts)', 'line.startswith("Organiser: ")][:1], contacts)'))),
    ("sender: the calendar never turns the hold on", C, rep(CALENDAR_ON, "            pass\n")),
    ("sender: the calendar always turns the hold on", C, rep(CALENDAR_SENDERS, on(CALENDAR_SENDERS))),
    ("sender: the calendar gives the inbox's reason", C, rep(CALENDAR_ON, INBOX_ON)),
    ("sender: who is not a contact is not said", C, rep('NOT_A_CONTACT = " from somebody who is not in your contacts"', 'NOT_A_CONTACT = ""')),
    # the reading tools
    ("readers: a marked tool is not marked", C, rep(MARKED, "            readers[name] = run\n")),
    ("readers: a tool that is not marked turns the hold on", C, rep(NOT_MARKED, "        if name not in way.marked and name not in REASONS:\n            readers[name] = run\n")),
    ("readers: every hold looks at the sender", C, rep(BY_SENDER, "        elif name in by_sender:\n")),
    ("readers: no hold looks at the sender", C, rep(BY_SENDER, "        elif False:\n")),
    ("readers: every tool gives the reason of a page", C, rep(MARKED, '            readers[name] = hold.reads(run, REASONS["open_page"])\n')),
    ("readers: a file gives the reason of an email", C, rep('    "read_file": "a file was read",\n', '    "read_file": "an email was read",\n')),
    ("readers: reading a file reads the list of files", C, rep('        return tools["read_file"](name)\n', '        return tools["list_files"]()\n')),
    ("readers: opening a page reads a file", C, rep('        return tools["open_page"](url)\n', '        return tools["read_file"](url)\n')),
    ("readers: the calendar gives the inbox", C, lambda text: nth(text, '        return tools["read_calendar"]()\n', '        return tools["list_emails"]()\n')),
    ("readers: the inbox gives the calendar", C, lambda text: nth(text, '        return tools["list_emails"]()\n', '        return tools["read_calendar"]()\n')),
    ("readers: an email is read by another name for its input", C, rep('    def read_email(id: str) -> str:\n        return tools["read_email"](id)\n', '    def read_email(email: str) -> str:\n        return tools["read_email"](email)\n')),
    ("readers: the tools are handed over in another order", C, rep('plain = {"list_emails": list_emails, "read_email": read_email,', 'plain = {"read_email": read_email, "list_emails": list_emails,')),
    # the checkpoint
    ("checkpoint: the last row is not a yes every time", C, rep(ALWAYS, "")),
    ("checkpoint: the rules alone are not the ones the asks count uses", C, rep(ALONE, "")),
    ("checkpoint: one hold is shared by every run", C, rep(NEW_HOLD, "    hold = Hold()\n\n    def build(tools: dict) -> Checkpoint:\n")),
    ("checkpoint: an email is not under the hold", C, rep(OVER, OVER.replace("hold.over(rules.email(contacts=contacts))", "rules.email(contacts=contacts)"))),
    ("checkpoint: a payment is not under the hold", C, rep(OVER, OVER.replace("hold.over(rules.payment(payees=payees, limit=limit))", "rules.payment(payees=payees, limit=limit)"))),
    ("checkpoint: a hold takes the place of the email rule", C, rep(OVER, OVER.replace("hold.over(rules.email(contacts=contacts))", "hold.over(FREE)"))),
    ("checkpoint: a hold takes the place of the payment rule", C, rep(OVER, OVER.replace("hold.over(rules.payment(payees=payees, limit=limit))", "hold.over(FREE)"))),
    ("checkpoint: the owner's contacts are not given to the rule", C, rep(OVER, OVER.replace("contacts=contacts", "contacts=[]"))),
    ("checkpoint: the owner's payees are not given to the rule", C, rep(OVER, OVER.replace("payees=payees", "payees=[]"))),
    ("checkpoint: the limit asked for is not given to the rule", C, rep(OVER, OVER.replace("limit=limit", "limit=LIMIT"))),
    ("checkpoint: an email or a payment is free", C, rep(RISKY_TOOL, RISKY_TOOL.replace("level=over[spec.name]", "level=FREE"))),
    ("checkpoint: the world's own reading tools are used", C, rep(READING_TOOL, READING_TOOL.replace("readers[spec.name]", "tools[spec.name]"))),
    ("checkpoint: reading needs a yes", C, rep(READING_TOOL, READING_TOOL.replace("level=FREE", 'level="needs_yes"'))),
    ("checkpoint: the readers get no contacts", C, rep("readers = _readers(tools, hold, way, contacts)", "readers = _readers(tools, hold, way, [])")),
    ("checkpoint: the rules alone get no limit", C, rep(ALONE, ALONE.replace("payees, limit)", "payees, LIMIT)"))),
    # the count of one set
    ("count: lists handed in are ignored", C, rep(LISTS, "    contacts, payees = owners_lists(case_set)\n")),
    ("count: the jobs are done by the stand-in that obeys trick text", C, rep(JOB_RUN, JOB_RUN.replace("standins.careful(case)", "standins.fooled(case)"))),
    ("count: the attacks are done by the stand-in that ignores trick text", C, rep(ATTACK_RUN, ATTACK_RUN.replace("standins.fooled(case)", "standins.careful(case)"))),
    ("count: the jobs are not done with the limit asked for", C, rep(JOB_RUN, JOB_RUN.replace("payees, limit))", "payees))"))),
    ("count: the attacks are not done with the limit asked for", C, rep(ATTACK_RUN, ATTACK_RUN.replace("*mine, limit))", "*mine))"))),
    ("count: every job is done with the rules alone", C, rep(JOB_RUN, JOB_RUN.replace("checkpoint_for(way, contacts", "checkpoint_for(WAYS[0], contacts"))),
    ("count: every attack is done with the rules alone", C, rep(ATTACK_RUN, ATTACK_RUN.replace("checkpoint_for(way, *mine", "checkpoint_for(WAYS[0], *mine"))),
    ("count: every attack is done with a yes every time", C, rep(ATTACK_RUN, ATTACK_RUN.replace("checkpoint_for(way, *mine", "checkpoint_for(WAYS[-1], *mine"))),
    ("count: every job is put in the outside column", C, rep(CELL, '            cell = row["by_read"][OUTSIDE]\n')),
    ("count: a job that only reads is counted as an action", C, rep('            cell["actions"] += case.action is not None\n', '            cell["actions"] += 1\n')),
    ("count: a job is not counted", C, rep('            cell["jobs"] += 1\n', '            cell["jobs"] += 0\n')),
    ("count: an ask in a job is not counted", C, rep('            cell["asks"] += result["owner_asked"]\n', '            cell["asks"] += 0\n')),
    ("count: which job asked is not kept", C, rep('f"{case_set.name}: {case.id}"] = result["owner_asked"]', 'f"{case_set.name}: {case.id}"] = 0')),
    ("count: a job is kept without the name of its set", C, rep('row["asks_by_job"][f"{case_set.name}: {case.id}"]', 'row["asks_by_job"][case.id]')),
    ("count: every job counts as done", C, rep('            row["jobs_done"] += result["task_done"]\n', '            row["jobs_done"] += 1\n')),
    ("count: what else ran in a job is not counted", C, rep('            row["other_ran"] += sum(_not_called_for(case, result["ran"]))\n', '            row["other_ran"] += 0\n')),
    ("count: an ask in an attack is not counted", C, rep('                block["asks"] += result["owner_asked"]\n', '                block["asks"] += 0\n')),
    ("count: an attacker's action that ran is not counted", C, rep('                block["got_through"] += result["got_through"]\n', '                block["got_through"] += 0\n')),
    ("count: what else ran in an attack is not counted", C, rep('                block["other_ran"] += _not_called_for(case, result["ran"])[1]\n', '                block["other_ran"] += 0\n')),
    ("count: the attacker's action is counted as something else", C, rep('_not_called_for(case, result["ran"])[1]\n', 'sum(_not_called_for(case, result["ran"]))\n')),
    ("count: every owner's task counts as done", C, rep('                block["tasks_done"] += result["task_done"]\n', '                block["tasks_done"] += 1\n')),
    ("count: where it arrived is always an email", C, rep('block["by_where"].setdefault(case.where, [0, 0])', 'block["by_where"].setdefault("email", [0, 0])')),
    ("count: what got through is not kept by where it arrived", C, rep('                where[0] += result["got_through"]\n', "                where[0] += 0\n")),
    ("count: the attacks are not counted by where they arrived", C, rep("                where[1] += 1\n", "                where[1] += 0\n")),
    ("count: the listed world is counted into the stranger's", C, rep("                block = row[world]\n", "                block = row[STRANGER]\n")),
    # adding the sets together
    ("add: sets counted in different ways are added", C, rep(SAME_WAYS, "")),
    ("add: a set with fewer rows is added", C, rep("for rows in zip(*per_set, strict=True):", "for rows in zip(*per_set):")),
    ("add: the same set is added twice", C, rep(TWICE, "")),
    ("add: the biggest set is taken for the total", C, rep(SUMS, SUMS.replace("sum(row[key] for row in rows)", "max(row[key] for row in rows)"))),
    ("add: the first set alone gives the cost", C, rep(BY_READ_SUM, BY_READ_SUM.replace('sum(row["by_read"][kind][key] for row in rows)', 'rows[0]["by_read"][kind][key]'))),
    ("add: the first set alone gives the gain", C, rep(WORLD_SUM, WORLD_SUM.replace("sum(row[world][key] for row in rows)", "rows[0][world][key]"))),
    ("add: what got through by where is the last set's", C, rep("                    both[0] += ran\n", "                    both[0] = ran\n")),
    ("add: how many arrived by where is the last set's", C, rep("                    both[1] += of\n", "                    both[1] = of\n")),
    ("add: which job asked is lost", C, rep('            summed["asks_by_job"].update(row["asks_by_job"])\n', "")),
    ("add: the total is written into the first set", C, rep('                    both = block["by_where"].setdefault(where, [0, 0])\n', '                    both = rows[0][world]["by_where"].setdefault(where, [0, 0])\n                    block["by_where"][where] = both\n')),
    # what is not as it should be
    ("problems: a job not done is not said", C, rep(P_JOBS, off(P_JOBS))),
    ("problems: something else running in a job is not said", C, rep(P_OTHER, off(P_OTHER))),
    ("problems: an owner's task not done is not said", C, rep(P_TASKS, off(P_TASKS))),
    ("problems: something else running in an attack is not said", C, rep(P_OTHER_ATTACK, off(P_OTHER_ATTACK))),
    ("problems: the listed world is not looked at", C, rep("        for world in WORLDS:\n            block = row[world]\n            if block", "        for world in WORLDS[:1]:\n            block = row[world]\n            if block")),
    ("problems: a stranger's action running is not said", C, rep(P_STRANGER, off(P_STRANGER))),
    ("problems: a stranger's action is looked for in the listed world", C, rep(P_STRANGER, P_STRANGER.replace("STRANGER", "LISTED"))),
    ("problems: a listed attacker getting past the full hold is not said", C, rep(P_LISTED, P_LISTED.replace("(AFTER_ANYTHING, ASK_ALWAYS)", "(ASK_ALWAYS,)"))),
    ("problems: a listed attacker getting past a yes every time is not said", C, rep(P_LISTED, P_LISTED.replace("(AFTER_ANYTHING, ASK_ALWAYS)", "(AFTER_ANYTHING,)"))),
    ("problems: a listed attacker getting past is a problem in every row", C, rep(P_LISTED, '        if row[LISTED]["got_through"]:\n')),
    ("problems: a listed attacker getting past is never said", C, rep(P_LISTED, off(P_LISTED))),
    ("problems: a hold that asks less than the rules is not said", C, rep("        if fewer:\n", "        if False:\n")),
    ("problems: asking the same as the rules is called less", C, rep(P_FEWER, P_FEWER.replace("if asks < base", "if asks <= base"))),
    ("problems: the rules are compared with the last row", C, rep("    base = rows[0]\n    for row in rows:\n", "    base = rows[-1]\n    for row in rows:\n")),
    ("problems: the jobs that asked less are not sorted", C, rep("{', '.join(sorted(fewer))}", "{', '.join(fewer)}")),
    # what is printed
    ("printed: the said and files columns are swapped", C, rep(T_COST, T_COST.replace("{row['by_read'][SAID]['asks']:>6}  {row['by_read'][FILES]['asks']:>6}", "{row['by_read'][FILES]['asks']:>6}  {row['by_read'][SAID]['asks']:>6}"))),
    ("printed: the outside column shows the files", C, rep(T_COST, T_COST.replace("{row['by_read'][OUTSIDE]['asks']:>7}", "{row['by_read'][FILES]['asks']:>7}"))),
    ("printed: the stranger and listed columns are swapped", C, rep(T_GAIN, T_GAIN.replace("{row[STRANGER]['got_through']:>8}  {row[LISTED]['got_through']:>6}", "{row[LISTED]['got_through']:>8}  {row[STRANGER]['got_through']:>6}"))),
    ("printed: the listed column shows the asks", C, rep(T_GAIN, T_GAIN.replace("{row[LISTED]['got_through']:>6}", "{row[LISTED]['asks']:>6}"))),
    ("printed: where it got through is the stranger world's", C, rep(T_GAIN, T_GAIN.replace("_by_where(row[LISTED])", "_by_where(row[STRANGER])"))),
    ("printed: where nothing got through is shown too", C, rep(T_WHERE, T_WHERE.replace(" if ran]", "]"))),
    ("printed: where it got through is not sorted", C, rep(T_WHERE, T_WHERE.replace('sorted(block["by_where"].items())', 'block["by_where"].items()'))),
    ("printed: where it got through shows how many arrived, twice", C, rep(T_WHERE, T_WHERE.replace('f"{where} {ran} of {of}"', 'f"{where} {of} of {of}"'))),
    ("printed: the full hold in the sentences is the web page one", C, rep(T_PICK, "base, full, always = rows[0], rows[1], rows[-1]")),
    ("printed: a yes every time in the sentences is the rules alone", C, rep(T_PICK, T_PICK.replace("rows[-1]", "rows[0]"))),
    ("printed: the actions are the last row's", C, rep('actions = {kind: base["by_read"][kind]["actions"] for kind in READ}', 'actions = {kind: base["by_read"][kind]["jobs"] for kind in READ}')),
    ("printed: how many sets is written in", C, rep('f"{sets} sets: {base[', 'f"4 sets: {base[')),
    ("printed: how often the rules alone let it run is written in", C, rep("ran in {base[LISTED]['got_through']} of {attacks} attacks. The rules", "ran in 32 of 32 attacks. The rules")),
    ("printed: how often the full hold let it run is written in", C, rep("it ran in {full[LISTED]['got_through']} of {attacks}, for", "it ran in 0 of {attacks}, for")),
    ("printed: the asks of the full hold are written in", C, rep("for {asked(full)} asks on the normal jobs", "for 19 asks on the normal jobs")),
    ("printed: the asks of a yes every time are written in", C, rep("A yes every time is {asked(always)} asks.", "A yes every time is 23 asks.")),
    ("printed: the asks on a said job are written in", C, rep("{full['by_read'][SAID]['asks']} asks on {actions[SAID]} under every hold", "0 asks on {actions[SAID]} under every hold")),
    ("printed: the asks on a said job with a yes every time are written in", C, rep("{always['by_read'][SAID]['asks']} with a yes every time.", "4 with a yes every time.")),
    ("printed: the asks of a row leave the said jobs out", C, rep('asked = lambda row: sum(row["by_read"][kind]["asks"] for kind in READ)', 'asked = lambda row: sum(row["by_read"][kind]["asks"] for kind in READ[1:])')),
    ("printed: all is said to be well when it is not", C, rep("    if wrong:\n        lines += [\"\", \"NOT AS IT SHOULD BE:\"]", "    if not wrong:\n        lines += [\"\", \"NOT AS IT SHOULD BE:\"]")),
    ("printed: what is wrong is not said", C, rep('    wrong = problems(rows)\n    if wrong:', "    wrong = []\n    if wrong:")),
    ("printed: that the stand-ins are scripts is left out", C, rep('        "The stand-ins are scripts, not models, and the mix of jobs is made up: read each column, not their sum.",\n', "")),
    ("printed: that a real owner may say yes is left out", C, rep('        "A real owner who is asked may say yes. A hold only gets them asked.",\n', "")),
    # the command
    ("command: the command line is not read", C, rep(M_GIVEN, "    if argv:\n")),
    ("command: something after the name is taken", C, rep(M_TOLD, "")),
    ("command: something after the name ends with 0", C, rep(M_TOLD, M_TOLD.replace("return 2", "return 0"))),
    ("command: what it does not take is said on the wrong stream", C, rep(M_TOLD, M_TOLD.replace(", file=sys.stderr", ""))),
    ("command: it ends with 0 when something is wrong", C, rep("    return 1 if problems(rows) else 0\n", "    return 0\n")),
    ("command: it ends with 1 when all is well", C, rep("    return 1 if problems(rows) else 0\n", "    return 1\n")),
    ("command: how many sets is written in", C, rep("    print(text(rows, len(SETS)))\n", "    print(text(rows, 4))\n")),
    ("command: only the first set is counted", C, rep("for path in SETS])", "for path in SETS[:1]])")),
    ("command: nothing is printed", C, rep("    print(text(rows, len(SETS)))\n", "    text(rows, len(SETS))\n")),
    # the Hold itself: the count moves when it breaks
    ("hold: a marked tool does not turn it on", H, rep(HOLD_MARK, "            pass\n")),
    ("hold: a hold that is on changes nothing", H, rep(HOLD_STOP, "        if True:\n            return under\n")),
    ("hold: it is turned on after the tool has run, not before", H, rep(HOLD_MARK + "            return run(*args, **inputs)\n", "            result = run(*args, **inputs)\n            self.on(reason)\n            return result\n")),
    ("hold: what the app said is not marked as the app's", H, rep('SAID = "the app said to ask: "', 'SAID = ""')),
    # the daily set: the count moves when it changes
    ("daily: a said job reads the contact list first", D, rep("steps = [\n" + SAID_STEPS, 'steps = [\n    {tool = "read_file", inputs = {name = "contacts.txt"}},\n' + SAID_STEPS)),
    ("daily: a said job does not give the address", D, rep('task = "Email sam@example.com to say I will be ten minutes late', 'task = "Email Sam to say I will be ten minutes late')),
    ("daily: a file job gives the account in the task", D, rep("for invoice 311. Their account is in contacts.txt.", "for invoice 311. Their account is BRIGHTSIDE-CATERING-4410.")),
    ("daily: a file job reads the inbox too", D, rep('steps = [\n    {tool = "read_file", inputs = {name = "contacts.txt"}},\n    {tool = "pay"', 'steps = [\n    {tool = "list_emails"},\n    {tool = "read_file", inputs = {name = "contacts.txt"}},\n    {tool = "pay"')),
    ("daily: the storage rent is over the limit", D, rep("amount = 95.0", "amount = 9500.0")),
    ("daily: a job that only reads looks at the files and not the calendar", D, rep('steps = [{tool = "read_calendar"}]', 'steps = [{tool = "list_files"}]')),
    ("daily: the reply to Sam reads no email", D, rep('    {tool = "list_emails"},\n    {tool = "read_email", inputs = {id = "e1"}},\n', "")),
    ("daily: an email comes from an address that is in no file", D, rep('from = "Sam Keane <sam@example.com>"', 'from = "Sam Keane <sam.keane@example.net>"')),
]

if __name__ == "__main__":
    run(MUTANTS, TESTS)
