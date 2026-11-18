"""Break the hold switch, one way at a time, and see whether its tests notice.

    .venv/bin/python checks/break_holds.py         every break (a few seconds)
    .venv/bin/python checks/break_holds.py never   only the breaks with "never" in their name

A Hold makes the next actions ask once the agent has read text from outside. Each
break here makes it stay off when it should be on, come on too late, lower a
level, lose a reason, or take something it should refuse, in a copy of the product.

Only tests/test_holds.py is run. No model takes part.
"""

from _runner import rep, run

TESTS = ["test_holds.py"]

H = "holds.py"

SHOWABLE = "return type(reason) is str and bool(reason.strip()) and len(reason) <= MAX_REASON and reason.isprintable()"
TEXT = "        text = reason.strip() if _showable(reason) else NO_REASON\n"
ROOM = "            if len(self._reasons) < MAX_KEPT:  # past that it is on already, and a card has no room for more\n"
KEEP = "                self._reasons.setdefault(text, None)\n"
CLEAR = "            self._reasons.clear()\n"
IS_ON = "            return bool(self._reasons)\n"
GIVEN = "            return tuple(self._reasons)\n"
PLAIN = "        if not inspect.isfunction(run):\n"
CHECKED = "        if not _showable(reason):\n"
WRAPS = "        @functools.wraps(run)\n"
MARK = "            self.on(reason)\n"
CALL = "            return run(*args, **inputs)\n"
TAKES = "        if not callable(level) and (type(level) is not str or level not in LEVELS):\n"
NAME = 'name = inner if type(inner) is str else "rule:" + getattr(inner, "__qualname__", type(inner).__name__)'
STOP = "        if not held or under.level not in (FREE, NEEDS_YES):\n            return under\n"
ADDED = "        added = tuple(SAID + reason for reason in held)\n"
RAISED = "            return Verdict(NEEDS_YES, added)\n"
BOTH = "        return Verdict(NEEDS_YES, tuple(dict.fromkeys(under.reasons + added)))\n"
RULE = "        if isinstance(inner, Rule):\n            return inner.explain(inputs)\n"
LEVEL = "        level = inner if type(inner) is str else inner(inputs)\n"
OWN_ASK = '            return Verdict(NEEDS_YES, ("this tool\'s own level says to ask",))\n'
OWN_NEVER = '            return Verdict(NEVER, ("this tool\'s own level never allows it",))\n'
LAST = "        return Verdict(level, ())\n"
FINE = '        object.__setattr__(self, "_fine", getattr(inner, "_fine", Rule._fine))\n'

MUTANTS = [
    # ---- the switch
    ("on does not turn it on", H, rep(KEEP, "                pass\n")),
    ("on turns it on only for a reason that can be shown", H, rep(TEXT, "        if not _showable(reason):\n            return\n        text = reason.strip()\n")),
    ("on fails for a reason that cannot be shown", H, rep(TEXT, "        if not _showable(reason):\n            raise ValueError(reason)\n        text = reason.strip()\n")),
    ("on keeps the spaces around a reason", H, rep(TEXT, "        text = reason if _showable(reason) else NO_REASON\n")),
    ("on keeps a reason that cannot be shown as it is", H, rep(TEXT, "        text = reason.strip() if type(reason) is str and reason.strip() else NO_REASON\n")),
    ("a reason that is not text is taken", H, rep(SHOWABLE, SHOWABLE.replace("type(reason) is str and ", "hasattr(reason, 'strip') and "))),
    ("an empty reason is taken", H, rep(SHOWABLE, SHOWABLE.replace("bool(reason.strip()) and ", ""))),
    ("a reason of spaces is taken", H, rep(SHOWABLE, SHOWABLE.replace("bool(reason.strip())", "bool(reason)"))),
    ("a reason of any length is taken", H, rep(SHOWABLE, SHOWABLE.replace("len(reason) <= MAX_REASON and ", ""))),
    ("the longest reason is one character shorter", H, rep(SHOWABLE, SHOWABLE.replace("<= MAX_REASON", "< MAX_REASON"))),
    ("a reason with a line break or an unseen character is taken", H, rep(SHOWABLE, SHOWABLE.replace(" and reason.isprintable()", ""))),
    ("the longest reason is 119", H, rep("MAX_REASON = 120 ", "MAX_REASON = 119 ")),
    ("the longest reason is 121", H, rep("MAX_REASON = 120 ", "MAX_REASON = 121 ")),
    ("seven reasons are kept", H, rep("MAX_KEPT = 8 ", "MAX_KEPT = 7 ")),
    ("nine reasons are kept", H, rep("MAX_KEPT = 8 ", "MAX_KEPT = 9 ")),
    ("one reason more than the limit is kept", H, rep(ROOM, ROOM.replace("< MAX_KEPT", "<= MAX_KEPT"))),
    ("every reason is kept", H, rep(ROOM, "            if True:\n")),
    ("only the first reason is kept", H, rep(ROOM, "            if not self._reasons:\n")),
    ("only the newest reason is kept", H, rep(KEEP, "                self._reasons.clear()\n" + KEEP)),
    ("a reason given again moves to the end", H, rep(KEEP, "                self._reasons.pop(text, None)\n" + KEEP)),
    ("the plain reason says something else", H, rep('NO_REASON = "outside text was read (the app gave no reason that can be shown)"', 'NO_REASON = "outside text was read"')),
    ("off does nothing", H, rep(CLEAR, "            pass\n")),
    ("off forgets only the newest reason", H, rep(CLEAR, "            if self._reasons:\n                self._reasons.popitem()\n")),
    ("is_on always says off", H, rep(IS_ON, "            return False\n")),
    ("is_on always says on", H, rep(IS_ON, "            return True\n")),
    ("reasons are given newest first", H, rep(GIVEN, "            return tuple(reversed(self._reasons))\n")),
    ("reasons are given as a list", H, rep(GIVEN, "            return list(self._reasons)\n")),
    ("reasons gives only the first", H, rep(GIVEN, "            return tuple(self._reasons)[:1]\n")),
    ("two holds share one switch", H, rep("        self._reasons: dict = {}\n", "        self._reasons = _SHARED\n", "class Hold:", "_SHARED: dict = {}\n\n\nclass Hold:")),
    # ---- a tool that brings outside text in
    ("a marked tool never turns the hold on", H, rep(MARK, "")),
    ("a marked tool turns the hold on after it has run", H, rep(MARK + CALL, "            result = run(*args, **inputs)\n" + MARK + "            return result\n")),
    ("marking a tool turns the hold on", H, rep(WRAPS, MARK.replace("            ", "        ") + WRAPS)),
    ("a marked tool turns the hold on with no reason", H, rep(MARK, "            self.on(None)\n")),
    ("a marked tool's result is lost", H, rep(CALL, "            run(*args, **inputs)\n")),
    ("a marked tool is not run", H, rep(CALL, "            return None\n")),
    ("a marked tool loses its named inputs", H, rep(CALL, "            return run(*args)\n")),
    ("a marked tool loses its inputs given by place", H, rep(CALL, "            return run(**inputs)\n")),
    ("a marked tool loses its name and its inputs", H, rep(WRAPS, "")),
    ("reads takes anything that can be called", H, rep(PLAIN, "        if not callable(run):\n")),
    ("reads takes anything at all", H, rep(PLAIN, "        if False:\n")),
    ("reads takes a method", H, rep(PLAIN, "        if not (inspect.isfunction(run) or inspect.ismethod(run)):\n")),
    ("reads takes a partial", H, rep(PLAIN, "        if not (inspect.isfunction(run) or isinstance(run, functools.partial)):\n")),
    ("reads takes any reason", H, rep(CHECKED, "        if False:\n")),
    ("reads takes any text as a reason", H, rep(CHECKED, "        if type(reason) is not str:\n")),
    ("reads says something else about the function", H, rep("reads() takes a plain function (def). For anything else, call on() inside the tool", "reads() takes a plain function")),
    ("reads says something else about the reason", H, rep("the reason must be text on one line, from 1 to {MAX_REASON} characters", "the reason must be text, from 1 to {MAX_REASON} characters")),
    # ---- a level under the hold
    ("over takes any text", H, rep(TAKES, "        if not callable(level) and type(level) is not str:\n")),
    ("over takes anything", H, rep(TAKES, "        if False:\n")),
    ("over takes text that only equals a level", H, rep(TAKES, "        if not callable(level) and level not in LEVELS:\n")),
    ("over takes only rules and functions", H, rep(TAKES, "        if not callable(level):\n")),
    ("over says something else", H, rep("over() takes FREE, NEEDS_YES, NEVER, a rule or a function", "over() takes a level")),
    ("a hold that is on lowers never to an ask", H, rep(STOP, "        if not held or under.level not in (FREE, NEEDS_YES, NEVER):\n            return under\n")),
    ("a hold that is on turns anything into an ask", H, rep(STOP, "        if not held:\n            return under\n")),
    ("a hold that is on does not raise a free level", H, rep(STOP, "        if not held or under.level != NEEDS_YES:\n            return under\n")),
    ("a hold that is on adds nothing to a level that asks", H, rep(STOP, "        if not held or under.level != FREE:\n            return under\n")),
    ("a hold that is off still raises a free level", H, rep(STOP, "        if under.level not in (FREE, NEEDS_YES):\n            return under\n")),
    ("a hold is never looked at", H, rep("        held = self._hold.reasons()\n", "        held = ()\n")),
    ("only the first reason of the hold is given", H, rep(ADDED, "        added = tuple(SAID + reason for reason in held[:1])\n")),
    ("the reasons of the hold are given newest first", H, rep(ADDED, "        added = tuple(SAID + reason for reason in reversed(held))\n")),
    ("the reason is given without saying the app said it", H, rep(ADDED, "        added = tuple(held)\n")),
    ("the words before a reason are different", H, rep('SAID = "the app said to ask: "', 'SAID = "the app asked: "')),
    ("a free level raised by the hold gives no reason", H, rep(RAISED, "            return Verdict(NEEDS_YES, ())\n")),
    ("a free level under a hold that is on stays free", H, rep(RAISED, "            return Verdict(FREE, added)\n")),
    ("a free level under a hold that is on becomes never", H, rep(RAISED, "            return Verdict(NEVER, added)\n")),
    ("the hold's reason comes before the rule's own", H, rep(BOTH, "        return Verdict(NEEDS_YES, tuple(dict.fromkeys(added + under.reasons)))\n")),
    ("the rule's own reasons are dropped when the hold is on", H, rep(BOTH, "        return Verdict(NEEDS_YES, added)\n")),
    ("the hold's reason is dropped from a level that asks", H, rep(BOTH, "        return Verdict(NEEDS_YES, under.reasons)\n")),
    ("the same reason can be given twice", H, rep(BOTH, "        return Verdict(NEEDS_YES, under.reasons + added)\n")),
    ("a rule under the hold loses its reasons", H, rep(RULE, "")),
    ("a rule under the hold is not asked", H, rep(RULE, "        if isinstance(inner, Rule):\n            return Verdict(FREE, ())\n")),
    ("a function under the hold is not asked", H, rep(LEVEL, "        level = inner if type(inner) is str else FREE\n")),
    ("a function under the hold is asked with nothing", H, rep(LEVEL, "        level = inner if type(inner) is str else inner({})\n")),
    ("a function that fails counts as an ask", H, rep(LEVEL, "        try:\n            level = inner if type(inner) is str else inner(inputs)\n        except Exception:\n            level = NEEDS_YES\n")),
    ("a function that fails counts as free", H, rep(LEVEL, "        try:\n            level = inner if type(inner) is str else inner(inputs)\n        except Exception:\n            level = FREE\n")),
    ("a level that asks gives no reason of its own", H, rep(OWN_ASK, "            return Verdict(NEEDS_YES, ())\n")),
    ("a level that asks says something else", H, rep(OWN_ASK, OWN_ASK.replace("says to ask", "asks"))),
    ("a level that never allows gives no reason of its own", H, rep(OWN_NEVER, "            return Verdict(NEVER, ())\n")),
    ("a level that never allows says something else", H, rep(OWN_NEVER, OWN_NEVER.replace("never allows it", "refuses it"))),
    ("a level that never allows is given as an ask", H, rep(OWN_NEVER, OWN_NEVER.replace("Verdict(NEVER,", "Verdict(NEEDS_YES,"))),
    ("an answer that is not a level becomes an ask", H, rep(LAST, "        return Verdict(level if level == FREE else NEEDS_YES, ())\n")),
    ("an answer that is not a level becomes free", H, rep(LAST, "        return Verdict(FREE, ())\n")),
    ("an answer that is not a level is given a reason", H, rep(LAST, '        return Verdict(level, () if level == FREE else ("not a level",))\n')),
    # ---- what the checkpoint's digest sees
    ("the name does not say a hold is in use", H, rep('    kind = "hold"\n', '    kind = "rule"\n')),
    ("the name is the same whatever is under the hold", H, rep('super().__init__({"over": name})', 'super().__init__({"over": "x"})')),
    ("the settings use another word", H, rep('super().__init__({"over": name})', 'super().__init__({"under": name})')),
    ("a rule under the hold is named without saying it is a rule", H, rep(NAME, NAME.replace('"rule:" + ', ""))),
    ("a rule under the hold is named by its kind only", H, rep(NAME, NAME.replace('getattr(inner, "__qualname__", type(inner).__name__)', "type(inner).__name__"))),
    ("a function with no name cannot be put under a hold", H, rep(NAME, NAME.replace('getattr(inner, "__qualname__", type(inner).__name__)', "inner.__qualname__"))),
    ("the rule's own words for a free action are lost", H, rep(FINE, "")),
    ("a level under a hold can be given another hold later", H, rep('        object.__setattr__(self, "_hold", hold)\n', '        object.__setattr__(self, "_hold", hold)\n\n    def __setattr__(self, name, value):\n        object.__setattr__(self, name, value)\n')),
]

if __name__ == "__main__":
    run(MUTANTS, TESTS)
