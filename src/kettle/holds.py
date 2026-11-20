"""Hold what comes next: once the agent has read text from outside, ask before it acts.

    from kettle import FREE, rules
    from kettle.holds import Hold

    hold = Hold()

    email = hold.over(rules.email(contacts=["sam@example.com"]))
    cp.tool("send_email", send, level=email, describe=email.why, watch=["to"])
    cp.tool("add_note", add_note, level=hold.over(FREE))

    cp.tool("fetch", hold.reads(fetch, "a web page was read"), level=FREE)

    hold.off()  # when the owner types a new message

A level can only look at the inputs of one action. It cannot know that the agent
has just read a web page, an email or a file that somebody else wrote. That is
when an agent is most likely to be acting on somebody else's words.

A Hold is a switch the app owns. reads() marks a tool as one that brings outside
text in: the switch goes on when that tool is run. on() does the same from the
app's own code. While the switch is on, every level made with over() gives at
least NEEDS_YES, and the reason is in why(), so the approval says it. off() turns
it off again; when to do that is the app's choice.

A Hold only ever adds an ask. FREE becomes NEEDS_YES. NEEDS_YES stays, with one
more reason. NEVER stays NEVER. Nothing here can make a level lower.

What this cannot do:

- It knows only what it is told. A tool that brings outside text in and is not
  marked with reads() does not turn the switch on.
- One Hold is one switch. In an app that serves many conversations at once, a
  page read in one of them asks in all of them: more asks, never fewer.
- off() does not clean the model's memory. After off() the model may still be
  following what it read. Calling off() when the owner types is a choice to
  trust that the owner's new message is what the agent now acts on.
- The reason is in the approval. It is not written to the checkpoint's log.
- It is not a wall. Code in the same process can call off().
"""

from __future__ import annotations

import functools
import inspect
import threading
from typing import Any, Callable

from .checkpoint.rules import FREE, LEVELS, NEEDS_YES, NEVER, RulesError
from .rules import Rule, Verdict

__all__ = ["Hold"]

MAX_REASON = 120  # the longest reason, in characters
MAX_KEPT = 8  # how many different reasons a Hold keeps while it is on
NO_REASON = "outside text was read (the app gave no reason that can be shown)"
SAID = "the app said to ask: "


def _showable(reason: Any) -> bool:
    return type(reason) is str and bool(reason.strip()) and len(reason) <= MAX_REASON and reason.isprintable()


class Hold:
    """A switch the app owns. While it is on, every level made with over() asks."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reasons: dict = {}

    def on(self, reason: str) -> None:
        """Turn the switch on, with a short reason in the app's own words. Never fill it in from the model's output.

        This never fails: a reason that cannot be shown is replaced by a plain
        one, because a switch that stayed off would be the worse mistake.
        """
        text = reason.strip() if _showable(reason) else NO_REASON
        with self._lock:
            if len(self._reasons) < MAX_KEPT:  # past that it is on already, and a card has no room for more
                self._reasons.setdefault(text, None)

    def off(self) -> None:
        """Turn the switch off, for example when the owner types a new message or a new task starts."""
        with self._lock:
            self._reasons.clear()

    def is_on(self) -> bool:
        with self._lock:
            return bool(self._reasons)

    def reasons(self) -> tuple:
        """Why the switch is on, oldest first. Empty when it is off."""
        with self._lock:
            return tuple(self._reasons)

    def reads(self, run: Callable[..., Any], reason: str) -> Callable[..., Any]:
        """Mark a tool's function as one that brings outside text in: running it turns the switch on.

        The switch goes on before the function is called, so it is on even if the
        function fails part of the way through.
        """
        if not inspect.isfunction(run):
            raise RulesError("reads() takes a plain function (def). For anything else, call on() inside the tool")
        if not _showable(reason):
            raise RulesError(f"the reason must be text on one line, from 1 to {MAX_REASON} characters")

        @functools.wraps(run)
        def marked(*args: Any, **inputs: Any) -> Any:
            self.on(reason)
            return run(*args, **inputs)

        return marked

    def over(self, level: Any) -> Rule:
        """A level that is `level` while the switch is off, and at least NEEDS_YES while it is on.

        `level` is FREE, NEEDS_YES, NEVER, a ready-made rule, or a function of the inputs.
        """
        if not callable(level) and (type(level) is not str or level not in LEVELS):
            raise RulesError("over() takes FREE, NEEDS_YES, NEVER, a rule or a function")
        return _Over(self, level)


class _Over(Rule):
    """The level under a Hold. Made by Hold.over()."""

    kind = "hold"

    def __init__(self, hold: Hold, inner: Any) -> None:
        name = inner if type(inner) is str else "rule:" + getattr(inner, "__qualname__", type(inner).__name__)
        super().__init__({"over": name})
        object.__setattr__(self, "_hold", hold)
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_fine", getattr(inner, "_fine", Rule._fine))

    def explain(self, inputs: dict) -> Verdict:
        under = self._under(inputs)
        held = self._hold.reasons()
        if not held or under.level not in (FREE, NEEDS_YES):
            return under
        added = tuple(SAID + reason for reason in held)
        if under.level == FREE:
            return Verdict(NEEDS_YES, added)
        return Verdict(NEEDS_YES, tuple(dict.fromkeys(under.reasons + added)))

    def reasons_in(self, inputs: dict) -> tuple:
        """The level's own reasons. The Hold's are left out: they come from what was read, not from this action,
        so text read while the owner decides does not cancel a yes for an action that has not changed."""
        inner = self._inner
        if isinstance(inner, Rule):
            return inner.reasons_in(inputs)
        return ()

    def _under(self, inputs: dict) -> Verdict:
        inner = self._inner
        if isinstance(inner, Rule):
            return inner.explain(inputs)
        level = inner if type(inner) is str else inner(inputs)
        if level == NEEDS_YES:
            return Verdict(NEEDS_YES, ("this tool's own level says to ask",))
        if level == NEVER:
            return Verdict(NEVER, ("this tool's own level never allows it",))
        return Verdict(level, ())
