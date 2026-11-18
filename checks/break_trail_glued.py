"""Change how the source trail decides the agent "used a value before", one way at a time, and see whether its tests notice.

    .venv/bin/python checks/break_trail_glued.py         every break (a few seconds)

The trail says a call is no source for a value when the agent had already used that
value in an earlier call. "Used" means the value's exact characters appear anywhere in
what the earlier call was asked with, even glued inside longer text. Each break here
makes that looser or tighter in a copy of the product.

Only tests/test_trail_glued.py is run. checks/break_checkpoint.py runs tests/test_trail.py
against other changes to the same lines.
"""

from _runner import rep, run

TESTS = ["test_trail_glued.py"]

T = "checkpoint/trail.py"

USE = "if any(value in text for text in texts)), default=None)"
FIRST = "self._overfull or (first_use is not None and first_use < result[6])"

MUTANTS = [
    ("a use only counts where the value stands as a whole word", T, rep(USE, "if any(whole_word(value, text) for text in texts)), default=None)")),
    ("a use only counts when the value is the whole of an input", T, rep(USE, "if any(value == text for text in texts)), default=None)")),
    ("a use only counts at the start of an input", T, rep(USE, "if any(text.startswith(value) for text in texts)), default=None)")),
    ("a use only counts at the end of an input", T, rep(USE, "if any(text.endswith(value) for text in texts)), default=None)")),
    ("a use only counts once in an input", T, rep(USE, "if any(text.count(value) == 1 for text in texts)), default=None)")),
    ("an earlier use never takes a source away", T, rep(FIRST, "self._overfull")),
    ("every call counts as coming after a use", T, rep(FIRST, "True")),
    ("a use takes away only the calls before it", T, rep(FIRST, "self._overfull or (first_use is not None and first_use > result[6])")),
    ("text one character short counts as a use", T, rep(USE, "if any(value[:-1] in text for text in texts)), default=None)")),
]

if __name__ == "__main__":
    run(MUTANTS, TESTS)
