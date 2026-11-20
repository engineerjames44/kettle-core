"""The rules: which tools exist and what each one needs before it may run.

Three levels. FREE runs straight away. NEEDS_YES is held until a human says yes
to that exact action. NEVER is refused. A tool that is not listed is refused.

A level can also be a function of the inputs, so a rule can read the details:
for example "sending to my own address is free, sending anywhere else needs a yes".
If that function fails or returns anything that is not a level, the action is refused.
"""

from __future__ import annotations

import functools
import hashlib
import inspect
import json
import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional, Union

FREE = "free"
NEEDS_YES = "needs_yes"
NEVER = "never"
LEVELS = (FREE, NEEDS_YES, NEVER)

Level = Union[str, Callable[[dict], str]]


class RulesError(ValueError):
    """The rules were set up wrongly. Raised at setup time, never while deciding."""


class Refused(Exception):
    """Raised inside the checkpoint when the rules say no. Carries the plain reason."""


@dataclass(frozen=True)
class Tool:
    name: str
    run: Optional[Callable[..., Any]]
    level: Level
    describe: Optional[Callable[[dict], str]] = None
    signature: Optional[inspect.Signature] = None
    fixed: frozenset = frozenset()  # input names the app has already filled in; a caller may not give them
    watch: tuple = ()  # input names whose value is marked in the preview the first time it is seen


def _read_signature(name: str, run: Callable[..., Any]) -> tuple[inspect.Signature, frozenset]:
    """What the function takes, read once at setup, so a function that cannot be read is found then."""
    signature = None
    try:
        signature = inspect.signature(run)
    except Exception:
        try:  # Python 3.14 and later: a type hint that names something not imported at run time
            import annotationlib

            signature = inspect.signature(run, annotation_format=annotationlib.Format.STRING)
        except Exception:
            pass
    if signature is None:
        raise RulesError(
            f"{name}: the inputs its function takes cannot be read, so they could not be checked. "
            "Wrap it in a plain function (def) with named inputs."
        )
    fixed = set()
    target = run
    if isinstance(target, functools.partial):
        fixed |= set(target.keywords)
        try:
            names = [p.name for p in inspect.signature(target.func).parameters.values() if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
            fixed |= set(names[: len(target.args)])
        except Exception:
            pass
        target = target.func
    if inspect.ismethod(target):
        code = getattr(target.__func__, "__code__", None)
        if code is not None and code.co_argcount:
            fixed.add(code.co_varnames[0])
    return signature, frozenset(fixed)


def _read_watch(name: str, watch: Any, signature: Optional[inspect.Signature], fixed: frozenset) -> tuple:
    """The inputs to watch, checked at setup, so a misspelt name is found then and not by a missing mark."""
    if type(watch) not in (tuple, list):
        raise RulesError(f'{name}: watch must be a list of input names, such as ["to"]')
    if not watch:
        return ()
    if signature is None:
        raise RulesError(f"{name}: a tool with no function to run has no inputs to watch")
    takes_any = any(p.kind is p.VAR_KEYWORD for p in signature.parameters.values())
    by_name = {p.name for p in signature.parameters.values() if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)}
    for key in watch:
        if type(key) is not str or not key:
            raise RulesError(f"{name}: watch must be a list of input names")
        if key in fixed or not (takes_any or key in by_name):
            raise RulesError(f"{name}: watch names {key!r}, which is not an input a caller can give to its function")
    return tuple(sorted(set(watch)))


MAX_REASON = 300  # the longest reason the log keeps in full


def _kept_reason(reason: str) -> str:
    if len(reason) <= MAX_REASON:
        return reason
    mark = " [cut, #" + hashlib.sha256(reason.encode("utf-8", "surrogatepass")).hexdigest()[:12] + "]"
    return reason[: MAX_REASON - len(mark)] + mark


class Rules:
    """The list of tools. It may be changed from one thread while another asks.

    A change swaps in a whole new entry for the tool, under a lock. Each step of a
    request (asking, the yes, the run) finds the tool once and keeps that entry to
    the end of the step, so a step sees the old rule or the new one, never half of
    each. The next step finds the tool again and gets whatever is listed then.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._lock = threading.Lock()

    def add(
        self,
        name: str,
        run: Optional[Callable[..., Any]] = None,
        *,
        level: Level,
        describe: Optional[Callable[[dict], str]] = None,
        replace: bool = False,
        watch: Any = (),
    ) -> Tool:
        if type(name) is not str or not name:
            raise RulesError("a tool name must be non-empty text")
        if not callable(level) and level not in LEVELS:
            raise RulesError(f"{name}: the level must be FREE, NEEDS_YES, NEVER or a function")
        if run is None and level != NEVER:
            raise RulesError(f"{name}: only a NEVER tool can be listed without a function to run")
        if run is not None and not callable(run):
            raise RulesError(f"{name}: run must be a function")
        if describe is not None and not callable(describe):
            raise RulesError(f"{name}: describe must be a function")
        signature, fixed = (None, frozenset()) if run is None else _read_signature(name, run)
        watch = _read_watch(name, watch, signature, fixed)
        tool = Tool(name=name, run=run, level=level, describe=describe, signature=signature, fixed=fixed, watch=watch)
        with self._lock:  # the check and the change in one step, so two threads cannot both list a new name
            if name in self._tools and not replace:
                raise RulesError(f"{name} is already listed")
            self._tools[name] = tool
        return tool

    def remove(self, name: str) -> None:
        with self._lock:
            self._tools.pop(name, None)

    def names(self) -> list[str]:
        return sorted(self._listed())

    def _listed(self) -> dict:
        """A copy of the list as it is now, taken in one step."""
        with self._lock:
            return dict(self._tools)

    def find(self, name: Any) -> Tool:
        with self._lock:
            tool = self._tools.get(name) if type(name) is str else None
        if tool is None:
            raise Refused("that tool is not listed in the rules")
        return tool

    def level_for(self, tool: Tool, inputs: dict) -> str:
        """The level for this tool with these inputs. Raises Refused if it cannot be decided."""
        level = tool.level
        if callable(level):
            try:
                level = level(inputs)
            except Exception as error:
                raise Refused(f"the rule for {tool.name} failed ({type(error).__name__})") from None
        if type(level) is not str or level not in LEVELS:
            raise Refused(f"the rule for {tool.name} did not give a level")
        if level != NEVER and tool.run is None:
            raise Refused(f"{tool.name} has nothing to run")
        return level

    def reasons_for(self, tool: Tool, inputs: dict) -> list[str]:
        """Why the tool's level asks, in the rule's own words, sorted. Raises Refused if the rule fails.

        Only a level that can say gives any: a ready-made rule or a Hold, through
        reasons_in(). FREE, NEEDS_YES, NEVER and a plain function give none.
        A reason longer than MAX_REASON is cut, with a mark made from all of it,
        so two long reasons that differ near the end are still two reasons.
        """
        reasons_in = getattr(tool.level, "reasons_in", None)
        if not callable(reasons_in):
            return []
        try:
            reasons = reasons_in(inputs)
        except Exception as error:
            raise Refused(f"the rule for {tool.name} failed ({type(error).__name__})") from None
        if type(reasons) not in (tuple, list) or any(type(reason) is not str for reason in reasons):
            raise Refused(f"the rule for {tool.name} did not give its reasons as text")
        return sorted({_kept_reason(reason) for reason in reasons})

    def one_look(self, tool: Tool, inputs: dict) -> Optional[tuple]:
        """(card text, reasons) from one look at the rule, when the tool's describe is its level's own why(). Else None.

        Raises Refused if the rule fails or does not answer in the right shape.
        """
        level, describe = tool.level, tool.describe
        seen = getattr(level, "seen", None)
        if not callable(seen) or getattr(describe, "__self__", None) is not level or getattr(describe, "__name__", None) != "why":
            return None
        try:
            text, reasons = seen(inputs)
        except Exception as error:
            raise Refused(f"the rule for {tool.name} failed ({type(error).__name__})") from None
        if type(text) is not str or type(reasons) not in (tuple, list) or any(type(reason) is not str for reason in reasons):
            raise Refused(f"the rule for {tool.name} did not give its reasons as text")
        return text, sorted({_kept_reason(reason) for reason in reasons})

    def check_fits(self, tool: Tool, inputs: dict) -> None:
        """Refuse inputs the tool's function could not be called with."""
        if tool.run is None or tool.signature is None:
            return
        taken = sorted(tool.fixed & set(inputs))
        if taken:
            raise Refused(f"the inputs do not fit {tool.name}: an input the app has already set was given again")
        try:
            tool.signature.bind(**inputs)
        except TypeError as error:
            raise Refused(f"the inputs do not fit {tool.name}: {error}") from None

    def digest(self) -> str:
        """A short fingerprint of the tool list and levels, for run records.

        A level that is a function is written as its name, so the digest shows
        that a rule function is in use but not what the function does. Watched
        inputs are written only for a tool that has some.
        """
        listed = []
        tools = self._listed()  # one copy, so a tool changed meanwhile cannot break this
        for name in sorted(tools):
            level = tools[name].level
            if callable(level):
                level = "rule:" + getattr(level, "__qualname__", type(level).__name__)
            watch = tools[name].watch
            listed.append([name, level, list(watch)] if watch else [name, level])
        text = json.dumps(listed, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(text.encode("ascii")).hexdigest()[:16]
