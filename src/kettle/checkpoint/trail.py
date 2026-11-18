"""The source trail: where the watched values of a held action were seen before.

The checkpoint sees every read as well as every risky action, because both go
through it. With the trail on, it keeps what each call returned and what the app
says the owner typed. When an action is held, each watched text value is looked
for in those by plain matching. No model takes part, so there is nothing in it to
talk round.

The more a line could reassure the person reading it, the stricter the match:

  - "in a list the app gave": the value must equal an entry, character for character.
  - "typed by the owner": the value must stand in the typed text as a whole word.
  - "seen in a result": the exact characters appear anywhere in what a call returned.

A trail says where characters were seen. It never says an action is all right. A
value the model rewrote (another spelling, a sum) is not matched, and the trail
then says "source not found".

A call that was handed the value in its own inputs, and gave it back, is named but
does not count as a source: anyone can make a tool repeat what they tell it.

The same goes for a call that returned the value after the agent had already put
that value into the inputs of some call. A source is a result that held the value
before the agent ever used it. So an agent cannot make a source by writing a value
somewhere with one call and reading it back with another.

What a call returned is held in memory by this one Checkpoint object. It is never
written to the store file, and another process sharing the file does not see it.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from typing import Any, Optional

MAX_RESULTS = 500  # results held; the oldest is dropped first
MAX_RESULT_CHARS = 1_000_000  # of one result; the rest of a longer one is not held
MAX_CHARS = 8_000_000  # of all results held
MAX_TYPED = 200  # pieces of owner text held; the oldest is dropped first
MAX_ASKED = 20_000  # calls whose inputs are held, to tell if the agent used a value before a result held it
MAX_ASKED_CHARS = 8_000_000  # of all those inputs
MAX_ITEMS = 20  # items of one list that are traced
MAX_SHOWN = 3  # results named for one value: the earliest, and first those not handed the value
LABEL_LIMIT = 160  # characters of a call's inputs kept to name it by

NOT_TEXT, EMPTY, TOO_MANY = "not_text", "empty", "too_many_items"

_OPENERS = "\"'(<[{,;"
_CLOSERS = "\"')>]},;"
_STOPS = ".!?:"


class TrailError(ValueError):
    """The trail was told something in a shape it cannot use."""


def whole_word(value: str, text: str) -> bool:
    """True if value stands in text as a whole word.

    Before it: the start, a space or line break, or one of " ' ( < [ { , ;
    After it: the end, a space or line break, or one of " ' ) > ] } , ; with any
    full stops, ! ? or : in between, as at the end of a sentence.

    So "smith@example.com" is not in "john.smith@example.com", and
    "sam@example.com" is not in "sam@example.com.evil.example".
    """
    if not value:
        return False
    start = text.find(value)
    while start != -1:
        before = text[start - 1] if start else ""
        end = start + len(value)
        while end < len(text) and text[end] in _STOPS:
            end += 1
        after = text[end] if end < len(text) else ""
        if (not before or before.isspace() or before in _OPENERS) and (not after or after.isspace() or after in _CLOSERS):
            return True
        start = text.find(value, start + 1)
    return False


def _texts(value: Any) -> tuple[list, bool]:
    """Every piece of text inside value, and whether all of value could be read.

    Only plain kinds are looked into: text, numbers, lists, tuples and dicts. No
    code is ever run on the value.
    """
    found, size, whole = [], 0, True
    todo = [value]
    while todo:
        item = todo.pop()
        kind = type(item)
        if kind is str:
            room = MAX_RESULT_CHARS - size
            if item[:room]:
                found.append(item[:room])
                size += len(item[:room])
            if len(item) > room:
                whole = False
                break
        elif kind in (list, tuple):
            todo.extend(reversed(item))
        elif kind is dict:
            for key, inner in reversed(list(item.items())):
                todo.append(inner)
                todo.append(key)
        elif item is None or kind in (bool, int, float):
            pass
        else:
            whole = False
    return found, whole


def call_label(inputs: dict) -> str:
    """The inputs of a call as one short line, to name the call by."""
    text = json.dumps(inputs, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return text if len(text) <= LABEL_LIMIT else text[:LABEL_LIMIT] + "..."


class Trail:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._results: deque = deque()  # (at, tool, inputs label, text returned, size, text in the inputs, order)
        self._chars = 0
        self._order = 0  # counts calls asked for and results kept, so which came first never rests on the clock
        self._asked: list = []  # (order, text in the inputs) of every call the agent asked for, whatever came of it
        self._asked_chars = 0
        self._overfull = False  # some inputs are not held, so "used before" can no longer be told
        self._lost = 0  # results that are not held, or not held in full
        self._typed: deque = deque(maxlen=MAX_TYPED)
        self._told = False  # has the app ever said what the owner typed?
        self._known: dict[str, frozenset] = {}

    def asked(self, inputs: Any) -> None:
        """Keep the text in the inputs of a call the agent asked for: run, held or refused. Never raises."""
        try:
            texts, whole = _texts(inputs)
            size = sum(len(text) for text in texts)
        except Exception:
            texts, whole, size = [], False, 0
        with self._lock:
            self._order += 1
            if not whole or len(self._asked) >= MAX_ASKED or self._asked_chars + size > MAX_ASKED_CHARS:
                self._overfull = True  # from here on no result is counted as a source, until clear()
                return
            if texts:
                self._asked.append((self._order, tuple(texts)))
                self._asked_chars += size

    def saw_result(self, tool: str, inputs: dict, result: Any, at: float) -> None:
        """Keep what a call returned. Never raises: the call has already happened."""
        try:
            texts, whole = _texts(result)
            given, _ = _texts(inputs)
            label, size = call_label(inputs), sum(len(text) for text in texts + given)
            at = float(at)
        except Exception:
            self.missed_one()
            return
        with self._lock:
            if not whole:
                self._lost += 1
            self._order += 1
            if texts:
                self._results.append((at, tool, label, tuple(texts), size, tuple(given), self._order))
                self._chars += size
            while len(self._results) > MAX_RESULTS or self._chars > MAX_CHARS:
                self._chars -= self._results.popleft()[4]
                self._lost += 1

    def missed_one(self) -> None:
        """A result could not be kept. A later miss then says so."""
        with self._lock:
            self._lost += 1

    def owner_said(self, text: str) -> None:
        if type(text) is not str:
            raise TrailError("what the owner typed must be text")
        with self._lock:
            self._told = True
            if text:
                self._typed.append(text[:MAX_RESULT_CHARS])

    def known(self, name: str, values: Any) -> None:
        if type(name) is not str or not name or len(name) > 60:
            raise TrailError("a list needs a name: text, 60 characters at most")
        if type(values) not in (list, tuple, set, frozenset) or any(type(value) is not str for value in values):
            raise TrailError(f"{name}: the values must be a list of text")
        with self._lock:
            self._known[name] = frozenset(values)

    def clear(self) -> None:
        """Forget the results, the calls asked for and the owner's text. The lists stay."""
        with self._lock:
            self._results.clear()
            self._typed.clear()
            self._asked.clear()
            self._chars, self._lost, self._told = 0, 0, False
            self._asked_chars, self._overfull = 0, False

    def trace(self, watch: tuple, inputs: dict, now: float) -> list:
        """One entry for each watched value of these inputs. A list is traced item by item."""
        entries = []
        with self._lock:
            for key in watch:
                if key not in inputs:
                    continue
                value = inputs[key]
                if type(value) is not list:
                    entries.append(self._one(key, None, value, now))
                    continue
                for number, item in enumerate(value[:MAX_ITEMS], 1):
                    entries.append(self._one(key, number, item, now))
                if len(value) > MAX_ITEMS:
                    entries.append({"input": key, "item": None, "not_traced": TOO_MANY})
        return entries

    def _one(self, key: str, item: Optional[int], value: Any, now: float) -> dict:
        if type(value) is not str:
            return {"input": key, "item": item, "not_traced": NOT_TEXT}
        if not value:
            return {"input": key, "item": item, "not_traced": EMPTY}
        first_use = min((order for order, texts in self._asked if any(value in text for text in texts)), default=None)
        seen = [
            (result, any(value in text for text in result[5]), self._overfull or (first_use is not None and first_use < result[6]))
            for result in self._results
            if any(value in text for text in result[3])
        ]
        seen.sort(key=lambda found: found[1] or found[2])  # the calls that count as a source first; the order is otherwise kept
        typed = any(whole_word(value, text) for text in self._typed) if self._told else None
        known = [[name, value in self._known[name]] for name in sorted(self._known)]
        return {
            "input": key,
            "item": item,
            "seen_in": [
                {"tool": result[1], "inputs": result[2], "seconds_before": round(max(0.0, now - result[0]), 3), "given": given, "used_before": used}
                for result, given, used in seen[:MAX_SHOWN]
            ],
            "seen_in_more": max(0, len(seen) - MAX_SHOWN),
            "typed": typed,
            "known": known,
            "lost": self._lost,
            "unsure": self._overfull,
            "found": any(not given and not used for _, given, used in seen) or typed is True or any(listed for _, listed in known),
        }
