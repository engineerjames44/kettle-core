"""Change what the source trail keeps of the owner's messages, one way at a time, and see whether its tests notice.

    .venv/bin/python checks/break_trail_turns.py         every break (a few seconds)

An address the owner typed in an earlier message is traced to them as long as the app
told the trail each message and has not cleared it since. Each break here makes the
trail forget too soon, or keep too long, or take other text for the owner's, in a copy
of the product.

Only tests/test_trail_turns.py is run. checks/break_checkpoint.py runs tests/test_trail.py
against other changes to the same lines.
"""

from _runner import rep, run

TESTS = ["test_trail_turns.py"]

T = "checkpoint/trail.py"

KEPT = "                self._typed.append(text[:MAX_RESULT_CHARS])\n"
TYPED = "typed = any(whole_word(value, text) for text in self._typed) if self._told else None"
FOUND = "or typed is True or any(listed for _, listed in known),"

MUTANTS = [
    ("only the newest message is kept", T, rep(KEPT, "                self._typed.clear()\n" + KEPT)),
    ("only the first message is kept", T, rep(KEPT, "                if not self._typed:\n    " + KEPT)),
    ("no message is kept", T, rep(KEPT, "                pass\n")),
    ("one message fewer is held", T, rep("MAX_TYPED = 200 ", "MAX_TYPED = 199 ")),
    ("one message more is held", T, rep("MAX_TYPED = 200 ", "MAX_TYPED = 201 ")),
    ("a clear keeps what the owner typed", T, rep("            self._typed.clear()\n", "")),
    ("a clear keeps that the owner was heard", T, rep("self._chars, self._lost, self._told = 0, 0, False", "self._chars, self._lost = 0, 0")),
    ("a clear forgets the lists too", T, rep("            self._typed.clear()\n", "            self._typed.clear()\n            self._known.clear()\n")),
    ("only the newest message is looked in", T, rep(TYPED, TYPED.replace("in self._typed)", "in list(self._typed)[-1:])"))),
    ("capital letters do not count in what the owner typed", T, rep(TYPED, TYPED.replace("whole_word(value, text)", "whole_word(value.lower(), text.lower())"))),
    ("a value inside a longer word of the owner's counts as typed", T, rep(TYPED, TYPED.replace("whole_word(value, text)", "value in text"))),
    ("what a call was asked with counts as typed", T, rep(TYPED, TYPED.replace("for text in self._typed)", "for text in list(self._typed) + [text for _, texts in self._asked for text in texts])"))),
    ("what a call returned counts as typed", T, rep(TYPED, TYPED.replace("for text in self._typed)", "for text in list(self._typed) + [text for result in self._results for text in result[3]])"))),
    ("a typed value is not found", T, rep(FOUND, "or any(listed for _, listed in known),")),
    ("a listed value is not found", T, rep(FOUND, "or typed is True,")),
    ("a value in a list counts as typed", T, rep(TYPED, TYPED.replace(" if self._told else None", " or any(value in names for names in self._known.values()) if self._told else None"))),
]

if __name__ == "__main__":
    run(MUTANTS, TESTS)
