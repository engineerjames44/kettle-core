"""Break "ask again if the rule's reasons changed", the agent files, /proc and "where it really leads", and see whether the tests notice.

    .venv/bin/python checks/break_ask_again.py           every break (about a minute)
    .venv/bin/python checks/break_ask_again.py proc      only the breaks with "proc" in their name

The breaks that matter most are the ones that would let a yes run something the
owner was not shown: the reasons not kept, not compared, compared the wrong way,
compared at the yes but not at the run, a Hold's own reasons counted so that a
yes is cancelled for nothing, or an older request refused for no reason.
"""

from _runner import rep, run

TESTS = ["test_ask_again.py", "test_tool_swap.py", "test_stored_inputs.py", "test_agent_files_rules.py", "test_agent_tricks.py", "test_files_rule.py"]

CP = "checkpoint/checkpoint.py"
CR = "checkpoint/rules.py"
ST = "checkpoint/store.py"
H = "holds.py"
R = "rules.py"

KEEP = '            summary, reasons = self._asked_about(found, record) if level != FREE else (None, [])\n'
DETAIL = '"rules": self._rules.digest(), "reasons": reasons}'
AT_YES = "                    self._same_reasons(tx, request_id, self._recheck(record), record)\n"
AT_RUN = "                    found = self._recheck(record)\n                    self._same_reasons(tx, request_id, found, record)\n"
NO_ENTRY = '        if type(held) is not dict:\n            raise Refused("the log has no readable entry for when the owner was asked")\n'
OLDER = '        if "reasons" not in held:\n            return\n'
UNREADABLE = '        if type(kept) is not list or any(type(reason) is not str for reason in kept):\n'
NEW = "        new = [reason for reason in self._rules.reasons_for(found, record.inputs()) if reason not in kept]\n"
SAYS = '            raise Refused(_clip("what the rule sees changed since the owner was asked (now: " + "; ".join(new) + "). Ask again", 500))\n'

FOR_LOOK = '        reasons_in = getattr(tool.level, "reasons_in", None)\n'
FOR_NONE = "        if not callable(reasons_in):\n            return []\n"
FOR_FAIL = '            raise Refused(f"the rule for {tool.name} failed ({type(error).__name__})") from None\n        if type(reasons)'
FOR_TEXT = "        if type(reasons) not in (tuple, list) or any(type(reason) is not str for reason in reasons):\n"
FOR_SORT = "        return sorted({_kept_reason(reason) for reason in reasons})\n"
CUT_SHORT = "    if len(reason) <= MAX_REASON:\n        return reason\n"
CUT = "    return reason[: MAX_REASON - len(mark)] + mark\n"

HELD_SQL = "\"SELECT detail FROM log WHERE request_id = ? AND event = 'held' ORDER BY seq LIMIT 1\", (request_id,)\n        ).fetchone()"

HOLD_IN = "        return self._both(inputs)[1]\n\n    def _both(self, inputs: dict) -> tuple:\n        \"\"\"The verdict with the Hold's"

RULE_IN = "        verdict = self.explain(inputs)\n        return verdict, verdict.reasons\n"
PROC_FILES = '    if pieces[:1] == ["proc"] and pieces[-1] in _PROC_SECRETS:\n        return True\n'
PROC_SHELL = '    if "proc" in on_the_way and on_the_way[-1] in _PROC_SECRETS:\n        return True\n'
LEADS = "        if real != tidy and found and not _system_alias(real, tidy):\n            # Said first, so the card shows it: the owner is asked about where the write lands, not the name it was given.\n            found.insert(0, (NEEDS_YES, _F_LEADS.format(_shown_place(real, self._home))))\n"
ALIAS = '    return top is not None and real == _real(top) + tidy[len(top):]\n'
ALIAS_TOP = '    top = next((alias for alias in _SYSTEM_ALIASES if _same(tidy) == alias or _same(tidy).startswith(alias + "/")), None)\n'
SHOWN_HOME = '    shown = "~" + path[len(home):] if _under(path, [home], exact=True) else path\n'
SHOWN_PRINT = '    shown = "".join(letter if letter.isprintable() else "?" for letter in shown)\n'
SHOWN_CUT = "    return shown[: MAX_PLACE - len(mark)] + mark\n"


INPUTS_RETURN = "        return copy.deepcopy(record.inputs())\n\n    def needs_checking"
INPUTS_CHECKED = "            record = self._stored_record(rows[0])\n        except (Refused, RecordError):\n            return None\n"
GATE_NAMES = "    def tool_names(self) -> list[str]:\n        return self._names()\n\n\ndef _mark"


ONE_LOOK_CHECK = '        if not callable(seen) or getattr(describe, "__self__", None) is not level or getattr(describe, "__name__", None) != "why":\n'
ASKED = "        once = self._rules.one_look(found, inputs)\n"
AFTER = "        if self._rules.reasons_for(found, inputs) != reasons:\n"
SEEN = "        verdict, reasons = self._both(inputs)\n        return self._said(verdict), reasons\n"
OVER_BOTH = "            under, reasons = inner._both(inputs)\n"
CUT_SUMMARY = '    return text if len(text) <= 500 else text[:500] + " [summary cut at 500 characters]"\n\n\ndef _clip'


ADD_LOCKED = "        with self._lock:  # the check and the change in one step, so two threads cannot both list a new name\n            if name in self._tools and not replace:\n                raise RulesError(f\"{name} is already listed\")\n            self._tools[name] = tool\n"
DIGEST_COPY = "        tools = self._listed()  # one copy, so a tool changed meanwhile cannot break this\n        for name in sorted(tools):\n"


def gone(old):
    return rep(old, "")


MUTANTS = [
    # ---- the checkpoint keeps the reasons and compares them
    ("keep: no reasons are kept at the hold", CP, rep("        return summary, reasons\n\n    def _summary", "        return summary, []\n\n    def _summary")),
    ("keep: reasons are worked out for a free action too", CP, rep(KEEP, KEEP.replace(" if level != FREE else (None, [])", ""))),
    ("keep: the reasons are not put in the log", CP, rep(DETAIL, '"rules": self._rules.digest()}')),
    ("keep: the reasons are put in the log unsorted", CP, rep(DETAIL, '"rules": self._rules.digest(), "reasons": reasons[::-1]}')),
    ("compare: not at the yes", CP, rep(AT_YES, "                    self._recheck(record)\n")),
    ("compare: not at the run", CP, rep(AT_RUN, "                    found = self._recheck(record)\n")),
    ("compare: a log with no entry for the hold is let through", CP, gone(NO_ENTRY)),
    ("compare: a log with no entry for the hold is taken as an older version", CP, rep(NO_ENTRY, '        if type(held) is not dict:\n            return\n')),
    ("compare: an older request is refused", CP, rep(OLDER, '        if "reasons" not in held:\n            raise Refused("old")\n')),
    ("compare: an older request is compared with nothing", CP, rep(OLDER, '        if "reasons" not in held:\n            held = {"reasons": []}\n')),
    ("compare: reasons that are not a list are let through", CP, rep(UNREADABLE, "        if type(kept) is not list:\n")),
    ("compare: reasons that are not text are let through", CP, rep(UNREADABLE, "        if any(type(reason) is not str for reason in kept):\n")),
    ("compare: the new reasons are worked out from the kept ones", CP, rep(NEW, "        new = [reason for reason in kept if reason not in self._rules.reasons_for(found, record.inputs())]\n")),
    ("compare: any change at all cancels, a reason that went away too", CP, rep(NEW, "        new = sorted(set(self._rules.reasons_for(found, record.inputs())) ^ set(kept))\n")),
    ("compare: nothing is ever new", CP, rep(NEW, "        new = []\n")),
    ("compare: only the first new reason counts", CP, rep(NEW, "        new = [reason for reason in self._rules.reasons_for(found, record.inputs())[:1] if reason not in kept]\n")),
    ("compare: what changed is not said", CP, rep(SAYS, '            raise Refused("what the rule sees changed since the owner was asked. Ask again")\n')),
    ("compare: the cancel does not say to ask again", CP, rep(SAYS, SAYS.replace('"). Ask again"', '")"'))),
    # ---- inputs(): the stored values, for the owner's side only
    ("inputs: one shared dict is handed out", CP, rep(INPUTS_RETURN, '        return self.__dict__.setdefault("_kept_" + request_id, record.inputs())\n\n    def needs_checking')),
    ("inputs: offered on the gate", CP, rep(GATE_NAMES, "    def tool_names(self) -> list[str]:\n        return self._names()\n\n    def inputs(self, request_id: str) -> None:\n        return None\n\n\ndef _mark")),
    ("inputs: a record changed after it was made is given anyway", CP, rep(INPUTS_CHECKED, "            record = ActionRecord.from_canonical(rows[0][\"record\"])\n        except (Refused, RecordError):\n            return None\n")),
    ("inputs: no such request gives an empty dict", CP, rep("        if not rows:\n            return None\n        try:\n            record = self._stored_record(rows[0])", "        if not rows:\n            return {}\n        try:\n            record = self._stored_record(rows[0])")),
    ("inputs: a request id that is not text is looked up anyway", CP, rep('"SELECT * FROM requests WHERE id = ?", (request_id,)) if type(request_id) is str else []\n        if not rows:\n            return None\n        try:', '"SELECT * FROM requests WHERE id = ?", (str(request_id),))\n        if not rows:\n            return None\n        try:')),
    ("inputs: only the first input is given", CP, rep(INPUTS_RETURN, "        return dict(list(copy.deepcopy(record.inputs()).items())[:1])\n\n    def needs_checking")),
    ("inputs: no deep copy", CP, rep(INPUTS_RETURN, "        return record.inputs()\n\n    def needs_checking")),
    # ---- one look for the card and the kept reasons, and a check after
    ("one look: never used", CP, rep(ASKED, "        once = None\n")),
    ("one look: any describe of the level's counts", CR, rep(ONE_LOOK_CHECK, '        if not callable(seen) or getattr(describe, "__self__", None) is not level:\n')),
    ("one look: another rule's why counts", CR, rep(ONE_LOOK_CHECK, '        if not callable(seen) or getattr(describe, "__name__", None) != "why":\n')),
    ("one look: the text is not checked", CR, rep("        if type(text) is not str or type(reasons) not in (tuple, list)", "        if type(reasons) not in (tuple, list)")),
    ("one look: a rule that fails is let through", CR, rep('            text, reasons = seen(inputs)\n        except Exception as error:\n            raise Refused(f"the rule for {tool.name} failed ({type(error).__name__})") from None\n', '            text, reasons = seen(inputs)\n        except Exception as error:\n            return None\n')),
    ("check after: gone", CP, rep(AFTER, "        if False:\n")),
    ("check after: only a new reason counts", CP, rep(AFTER, "        if not set(self._rules.reasons_for(found, inputs)) <= set(reasons):\n")),
    ("seen: text and reasons from two looks", R, rep(SEEN, "        return self.why(inputs), self.reasons_in(inputs)\n")),
    ("hold: the rule beneath is looked at twice", H, rep(OVER_BOTH, "            under, reasons = inner.explain(inputs), inner.reasons_in(inputs)\n")),
    ("card: a long card is not cut", CP, rep(CUT_SUMMARY, "    return text\n\n\ndef _clip")),
    # ---- the tool list changed from another thread
    ("tools: the check and the change are two steps", CR, rep(ADD_LOCKED, "        if name in self._tools and not replace:\n            raise RulesError(f\"{name} is already listed\")\n        with self._lock:\n            self._tools[name] = tool\n")),
    ("tools: no lock when a tool is listed", CR, rep(ADD_LOCKED, "        if name in self._tools and not replace:\n            raise RulesError(f\"{name} is already listed\")\n        self._tools[name] = tool\n")),
    ("tools: a tool can be listed twice", CR, rep(ADD_LOCKED, "        with self._lock:\n            self._tools[name] = tool\n")),
    ("tools: the fingerprint reads the live list", CR, rep(DIGEST_COPY, "        tools = self._tools\n        for name in self.names():\n")),
    ("tools: no lock when a tool is found", CR, rep("        with self._lock:\n            tool = self._tools.get(name) if type(name) is str else None", "        if True:\n            tool = self._tools.get(name) if type(name) is str else None")),
    ("tools: no lock when a tool is removed", CR, rep("        with self._lock:\n            self._tools.pop(name, None)", "        if True:\n            self._tools.pop(name, None)")),
    ("tools: no lock when the list is copied", CR, rep("        with self._lock:\n            return dict(self._tools)", "        if True:\n            return dict(self._tools)")),
    # ---- the reasons themselves
    ("reasons: never asked for", CR, rep(FOR_LOOK, '        reasons_in = None\n')),
    ("reasons: explain() is used, so a Hold's own reasons count", CR, rep(FOR_LOOK, '        reasons_in = (lambda inputs: tool.level.explain(inputs).reasons) if hasattr(tool.level, "explain") else None\n')),
    ("reasons: a level that cannot say gives an empty reason", CR, rep(FOR_NONE, '        if not callable(reasons_in):\n            return [""]\n')),
    ("reasons: a rule that fails gives none", CR, rep(FOR_FAIL, "            return []\n        if type(reasons)")),
    ("reasons: reasons that are not text are kept", CR, rep(FOR_TEXT, "        if type(reasons) not in (tuple, list):\n")),
    ("reasons: given in the rule's order", CR, rep(FOR_SORT, "        return list(dict.fromkeys(_kept_reason(reason) for reason in reasons))\n")),
    ("reasons: repeats kept", CR, rep(FOR_SORT, "        return sorted(_kept_reason(reason) for reason in reasons)\n")),
    ("reasons: a long one is kept whole", CR, rep(CUT_SHORT, "    if True:\n        return reason\n")),
    ("reasons: a long one is cut with no mark", CR, rep(CUT, "    return reason[:MAX_REASON]\n")),
    ("reasons: a long one is cut one letter too long", CR, rep(CUT, "    return reason[: MAX_REASON - len(mark) + 1] + mark\n")),
    ("reasons: the limit is 100", CR, rep("MAX_REASON = 300 ", "MAX_REASON = 100 ")),
    ("store: the first entry for any request is read", ST, rep(HELD_SQL, "\"SELECT detail FROM log WHERE event = 'held' ORDER BY seq LIMIT 1\"\n        ).fetchone()")),
    ("store: the last held entry is read", ST, rep(HELD_SQL, HELD_SQL.replace("ORDER BY seq LIMIT 1", "ORDER BY seq DESC LIMIT 1"))),
    ("store: an entry that is not JSON stops the checkpoint", ST, rep("        except (ValueError, TypeError):\n            return None\n\n    def seen", "        except TypeError:\n            return None\n\n    def seen")),
    # ---- a Hold gives only what is beneath it
    ("hold: its own reasons are given too", H, rep(HOLD_IN, HOLD_IN.replace("return self._both(inputs)[1]", "return self.explain(inputs).reasons"))),
    ("hold: the rule beneath gives nothing", H, rep(OVER_BOTH, "            under, reasons = inner._both(inputs)[0], ()\n")),
    ("hold: a plain level beneath gives a reason", H, rep("            under, reasons = self._under(inputs), ()\n", "            under, reasons = self._under(inputs), ('the level',)\n")),
    ("rule: a ready-made rule gives no reasons to keep", R, rep(RULE_IN, "        verdict = self.explain(inputs)\n        return verdict, ()\n")),
    # ---- agent files and /proc
    ("agent files: .mcp.json is not one", R, rep(" .mcp.json agents.md", " agents.md")),
    ("agent files: AGENTS.md is not one", R, rep(" .mcp.json agents.md claude.md", " .mcp.json claude.md")),
    ("agent files: CLAUDE.md is not one", R, rep(" agents.md claude.md claude.local.md", " agents.md claude.local.md")),
    ("agent files: CLAUDE.local.md is not one", R, rep(" claude.md claude.local.md gemini.md", " claude.md gemini.md")),
    ("agent files: GEMINI.md is not one", R, rep(" claude.local.md gemini.md .cursorrules", " claude.local.md .cursorrules")),
    ("agent files: .cursorrules is not one", R, rep(" gemini.md .cursorrules .windsurfrules", " gemini.md .windsurfrules")),
    ("agent files: .windsurfrules is not one", R, rep(' .cursorrules .windsurfrules".split()', ' .cursorrules".split()')),
    ("agent folders: .gemini is not one", R, rep('" .gemini .codex', '" .codex')),
    ("agent folders: .codex is not one", R, rep(" .gemini .codex .windsurf", " .gemini .windsurf")),
    ("agent folders: .windsurf is not one", R, rep(" .codex .windsurf .amazonq", " .codex .amazonq")),
    ("agent folders: .amazonq is not one", R, rep(" .windsurf .amazonq .continue", " .windsurf .continue")),
    ("agent folders: .continue is not one", R, rep(" .amazonq .continue .clinerules", " .amazonq .clinerules")),
    ("agent folders: .clinerules is not one", R, rep(' .continue .clinerules".split()', ' .continue".split()')),
    ("proc: environ is not a secret place", R, rep('_PROC_SECRETS = ("environ", "cmdline")', '_PROC_SECRETS = ("cmdline",)')),
    ("proc: cmdline is not a secret place", R, rep('_PROC_SECRETS = ("environ", "cmdline")', '_PROC_SECRETS = ("environ",)')),
    ("proc: the files rule does not know it", R, gone(PROC_FILES)),
    ("proc: the files rule looks only at /proc/<n>/environ", R, rep(PROC_FILES, '    if pieces[:1] == ["proc"] and len(pieces) == 3 and pieces[-1] in _PROC_SECRETS:\n        return True\n')),
    ("proc: the files rule takes any environ for one", R, rep(PROC_FILES, '    if pieces and pieces[-1] in _PROC_SECRETS:\n        return True\n')),
    ("proc: the shell rule does not know it", R, gone(PROC_SHELL)),
    ("proc: the shell rule takes any environ for one", R, rep(PROC_SHELL, '    if on_the_way and on_the_way[-1] in _PROC_SECRETS:\n        return True\n')),
    ("proc: the shell rule looks only at the first piece", R, rep(PROC_SHELL, '    if on_the_way[:1] == ["proc"] and on_the_way[-1] in _PROC_SECRETS:\n        return True\n')),
    # ---- where a link really leads
    ("leads: never said", R, gone(LEADS)),
    ("leads: said even when nothing else asks", R, rep(LEADS, LEADS.replace(" and found and ", " and "))),
    ("leads: said last", R, rep(LEADS, LEADS.replace("found.insert(0, ", "found.append("))),
    ("leads: the system's own top links are said too", R, rep(LEADS, LEADS.replace(" and not _system_alias(real, tidy)", ""))),
    ("leads: the place as it was given, not where it leads", R, rep(LEADS, LEADS.replace("_shown_place(real, self._home)", "_shown_place(tidy, self._home)"))),
    ("alias: any top folder counts", R, rep(ALIAS, "    return True\n")),
    ("alias: capitals in the top folder are not passed over", R, rep(ALIAS_TOP, ALIAS_TOP.replace("_same(tidy)", "tidy"))),
    ("alias: /tmp is not one", R, rep('_SYSTEM_ALIASES = ("/tmp", "/var", "/etc")', '_SYSTEM_ALIASES = ("/var", "/etc")')),
    ("alias: /etc is not one", R, rep('_SYSTEM_ALIASES = ("/tmp", "/var", "/etc")', '_SYSTEM_ALIASES = ("/tmp", "/var")')),
    ("alias: /var is not one", R, rep('_SYSTEM_ALIASES = ("/tmp", "/var", "/etc")', '_SYSTEM_ALIASES = ("/tmp", "/etc")')),
    ("alias: a name that only starts like one counts", R, rep(ALIAS_TOP, ALIAS_TOP.replace('startswith(alias + "/")', "startswith(alias)"))),
    ("shown: the home folder is not written as ~", R, rep(SHOWN_HOME, "    shown = path\n")),
    ("shown: a folder that only starts like the home folder is written as ~", R, rep(SHOWN_HOME, '    shown = "~" + path[len(home):] if path.startswith(home) else path\n')),
    ("shown: letters that cannot be shown are kept", R, gone(SHOWN_PRINT)),
    ("shown: a long place is cut with no mark", R, rep(SHOWN_CUT, "    return shown[:MAX_PLACE]\n")),
    ("shown: a long place is kept whole", R, rep("    if len(shown) <= MAX_PLACE:\n        return shown\n", "    if True:\n        return shown\n")),
    ("shown: a long place is cut one letter too long", R, rep(SHOWN_CUT, "    return shown[: MAX_PLACE - len(mark) + 1] + mark\n")),
]

KNOWN = {
    "tools: no lock when a tool is found": "with Python's global lock one dict read is one step anyway; the lock is there for builds without it",
    "tools: no lock when a tool is removed": "with Python's global lock one dict change is one step anyway; the lock is there for builds without it",
    "tools: no lock when the list is copied": "with Python's global lock copying a dict is one step anyway; the lock is there for builds without it",
    "inputs: no deep copy": "a record reads its inputs afresh from its stored text each time, so each call is a new copy anyway",
    "store: the last held entry is read": "a request is held once, so its first and its last held entry are the same entry",
    "alias: a name that only starts like one counts": "a name such as /tmpfoo then fails the check that the place is the alias's own place plus the rest",
}

run(MUTANTS, TESTS, expected_to_survive=KNOWN)
