"""The action record: the one exact thing a yes can cover.

A record is the tool name, the inputs and (optionally) who the app says is asking,
written out as one fixed line of text. The fingerprint is a SHA-256 of that text.
Two records have the same fingerprint only if every byte of that text is the same,
so a yes given for one record cannot be moved to another.

The text is the truth. When an action runs, its inputs are read back out of the
text, never taken from an object the caller still holds and could have changed.
"""

from __future__ import annotations

import hashlib
import json
import math
import textwrap
import unicodedata
from dataclasses import dataclass
from typing import Any, Optional

from .trail import EMPTY, MAX_ITEMS, NOT_TEXT, TOO_MANY

RECORD_VERSION = 1
MAX_RECORD_BYTES = 1_000_000
MAX_DEPTH = 32
PREVIEW_WIDTH = 78  # no line of a preview is longer than this: see "writing the preview" below
MIN_PREVIEW_WIDTH = 32  # the narrowest a preview can be asked for: the longest fixed words and marks still fit on a line
_PREFIX = b"kettle-action-v1\n"


class RecordError(ValueError):
    """The tool name or inputs cannot be made into an exact record."""


def _plain(value: Any, depth: int, where: str) -> Any:
    """Copy value into plain JSON types, or raise RecordError.

    Exact types only (no subclasses), so what gets checked is what gets written.
    """
    if depth > MAX_DEPTH:
        raise RecordError(f"{where} is nested more than {MAX_DEPTH} levels deep")
    kind = type(value)
    if value is None or kind is bool or kind is int:
        return value
    if kind is str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise RecordError(f"{where} holds text that is not valid Unicode") from None
        return value
    if kind is float:
        if not math.isfinite(value):
            raise RecordError(f"{where} is not a finite number")
        return value
    if kind is list:
        return [_plain(item, depth + 1, f"{where}[{index}]") for index, item in enumerate(value)]
    if kind is dict:
        copy = {}
        for key, item in value.items():
            if type(key) is not str:
                raise RecordError(f"{where} has a key that is not text (a {type(key).__name__})")
            copy[_plain(key, depth + 1, where)] = _plain(item, depth + 1, f"{where}.{key}")
        return copy
    raise RecordError(f"{where} is a {kind.__name__}, which a record cannot hold")


def _canonical(body: dict) -> str:
    try:
        text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (ValueError, TypeError, RecursionError) as error:
        raise RecordError(f"the record cannot be written out: {error}") from None
    if len(text) > MAX_RECORD_BYTES:
        raise RecordError(f"the record is larger than {MAX_RECORD_BYTES} bytes")
    return text


def _fingerprint(canonical: str) -> str:
    return hashlib.sha256(_PREFIX + canonical.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class ActionRecord:
    """One exact action. Build it with make() or from_canonical(), not directly."""

    tool: str
    canonical: str
    fingerprint: str

    @classmethod
    def make(cls, tool: str, inputs: dict, actor: Optional[str] = None) -> "ActionRecord":
        if type(tool) is not str or not tool:
            raise RecordError("the tool name must be non-empty text")
        if type(inputs) is not dict:
            raise RecordError("the inputs must be a dict")
        if actor is not None and type(actor) is not str:
            raise RecordError("the actor must be text")
        body = {
            "actor": None if actor is None else _plain(actor, 0, "actor"),
            "inputs": _plain(inputs, 0, "inputs"),
            "tool": _plain(tool, 0, "tool"),
            "v": RECORD_VERSION,
        }
        canonical = _canonical(body)
        return cls(tool=tool, canonical=canonical, fingerprint=_fingerprint(canonical))

    @classmethod
    def from_canonical(cls, canonical: str) -> "ActionRecord":
        """Rebuild a record from stored text, refusing text that is not exactly canonical."""
        if type(canonical) is not str:
            raise RecordError("the stored record is not text")
        if len(canonical) > MAX_RECORD_BYTES:
            raise RecordError(f"the stored record is larger than {MAX_RECORD_BYTES} bytes")
        try:
            body = json.loads(canonical)
        except (ValueError, RecursionError):
            raise RecordError("the stored record is not readable") from None
        if type(body) is not dict or set(body) != {"actor", "inputs", "tool", "v"}:
            raise RecordError("the stored record has the wrong shape")
        if body["v"] != RECORD_VERSION or type(body["v"]) is not int:
            raise RecordError("the stored record has an unknown version")
        record = cls.make(body["tool"], body["inputs"], body["actor"])
        if record.canonical != canonical:
            raise RecordError("the stored record is not in its exact written form")
        return record

    def _body(self) -> dict:
        return json.loads(self.canonical)

    def inputs(self) -> dict:
        """A fresh copy of the inputs, read from the record text."""
        return self._body()["inputs"]

    @property
    def actor(self) -> Optional[str]:
        return self._body()["actor"]

    def preview(
        self, summary: Optional[str] = None, first_time: Optional[dict] = None, trail: Optional[list] = None, width: int = PREVIEW_WIDTH
    ) -> str:
        """What a human is shown before saying yes. Written here, from the record.

        It is plain ASCII, no line is longer than width, and it can be read back to
        exactly the record: see the notes above _pieces and _fold.

        width is for a screen that shows fewer than PREVIEW_WIDTH characters on a
        line, such as a phone: from MIN_PREVIEW_WIDTH to PREVIEW_WIDTH. A narrower
        preview has more lines. It says the same and reads back to the same record.

        first_time names the inputs to mark as new: each name maps to None for the
        whole value, or to the numbers (from 1) of the new items in a list. The
        marks are "!" notes. They are not part of the record or its fingerprint.

        trail is what Trail.trace() gave for the watched inputs: where each value
        was seen before. It is written as "!" notes too, under the input.
        """
        if type(width) is not int or not MIN_PREVIEW_WIDTH <= width <= PREVIEW_WIDTH:
            raise RecordError(f"the width of a preview must be a whole number from {MIN_PREVIEW_WIDTH} to {PREVIEW_WIDTH}")
        inputs = self.inputs()
        traced, missing = _trail_lines(trail, inputs, "      ", width) if trail else ({}, 0)
        marked = {key: _first_time_lines(items, "      ", width) for key, items in (first_time or {}).items() if key in inputs}
        lines = []
        if marked:
            lines += _top_note(f"{len(marked)} input{' below is' if len(marked) == 1 else 's below are'} marked first time", width)
        if missing:
            lines += _top_note(f"source not found for {missing} value{'' if missing == 1 else 's'} below", width)
        if summary:
            lines += _text_lines("", ["Summary (written by the app):"], summary, "  ", words=True, width=width)
        lines += _text_lines("", ["Action:"], self.tool, "  ", width=width)
        if self.actor is not None:
            lines += _text_lines("", ["Asked through (set by the app):"], self.actor, "  ", width=width)
        if not inputs:
            lines.append("Inputs: none")
        for key in sorted(inputs):
            label = ['"'] + _pieces(key, quoted=True) + ['"', ":"]
            value = inputs[key]
            if type(value) is str:
                lines += _text_lines("  ", label, value, "      ", noted=key, width=width)
            else:
                lines += _json_lines("  ", label, value, "      ", noted=key, width=width)
            lines += marked.get(key, [])
            lines += traced.get(key, [])
        lines += _fingerprint_lines(self.fingerprint, width)
        return "\n".join(lines)


# ---- writing the preview ----
#
# The reader has to be able to tell two different records apart by looking. So:
#   - Only printable ASCII is written as itself. Every other character, seen or
#     unseen, is written as \u{...} in the place where it is.
#   - A space at the start or end of a line of text, or next to another space, is
#     written as \u{0020}, because nobody can count those by eye.
#   - No line is longer than PREVIEW_WIDTH. A longer one is cut here, and carries on
#     in the next line after a "+" mark, so a screen that wraps or clips long lines
#     cannot be used to push part of a value out of sight or to the start of a line.
#     A screen that shows fewer characters than that on a line wraps them all the
#     same, so the preview can be asked for at the width the screen has.
#   - The app's summary is the one thing a person reads as a sentence, so it is cut
#     between words where it can be. At the usual width the space at the cut is
#     written out like any other space at the end of a line. On a narrower preview
#     it is not written at all: a summary line that carries on after "+ " carries on
#     after a space, and one that carries on after "+" with nothing after it was cut
#     inside a word. Either way the summary reads back exactly.
#   - Text from inside a value only ever appears after a quote, a "|" or a "+".

WORD_LIMIT = 24  # a word longer than this is cut where the line ends, not carried down whole
_SPACE = "\\u{0020}"
_JSON_SPACE = "\\u0020"


def _pieces(text: str, quoted: bool) -> list[str]:
    """One piece of plain ASCII for each character of text."""
    out = []
    last = len(text) - 1
    for index, char in enumerate(text):
        if char == "\\":
            out.append("\\\\")
        elif char == '"' and quoted:
            out.append('\\"')
        elif char == " ":
            alone = 0 < index < last and text[index - 1] != " " and text[index + 1] != " "
            out.append(" " if alone else _SPACE)
        elif "!" <= char <= "~":
            out.append(char)
        else:
            out.append(f"\\u{{{ord(char):04X}}}")
    return out


def _fold(
    head: str, pieces: list[str], more: str, json_from: Optional[int] = None, words: bool = False, width: int = PREVIEW_WIDTH
) -> list[str]:
    """Write the pieces after head, in lines of at most width characters.

    A line that had to be cut carries on in the next one after `more`. No line ends
    with a bare space and no carried-on line starts with one: a space that would
    land there is written out instead. Pieces from json_from on are JSON, where the
    way to write a space out is \\u0020.

    A space from inside a value is always a piece on its own. A longer piece that
    starts with a space is the gap between a label and its value, which is not part
    of either, so it is left out when the value starts on a carried-on line.

    With words, a line is cut after its last single space, and the word that was
    being written is carried down whole, if that word is WORD_LIMIT characters or
    fewer so far and fits on the next line with the piece that comes after it. A
    line with no such space, or a longer word, is cut where it ends.

    At the usual width a line is cut len(_SPACE) characters early, which is the room
    a space needs when it is written out at the cut. Every release so far has cut
    there, so it stays. A narrower preview has no characters to spare, so there a
    line is filled. A space that then has no room to be written out where the line
    ends is written out at the start of the next line. With words, a space is only
    put on a line that has the room, so a line cut between words ends with it. The
    room is not needed once all that is left fits on the line.

    With words on a narrower preview, the space at a cut is not written at all. The
    next line starts with `more` when the cut was at a space, and with `more` less
    its last space ("+" alone before the text) when the cut was inside a word.
    """
    fill = width < PREVIEW_WIDTH
    implied = fill and words  # the space at a cut is told by the mark on the next line, not written
    glued = more.rstrip(" ")
    room = width if fill else width - len(_SPACE)
    left = sum(map(len, pieces))  # how long the pieces not yet written are
    lines, line, count, last, last_space = [], head, 0, "", _SPACE
    word_at, word_space = 0, _SPACE  # with words: where in the line the word being written starts (0: none to carry)
    for index, piece in enumerate(pieces):
        space = _SPACE if json_from is None or index < json_from else _JSON_SPACE
        size = len(piece)
        left -= len(piece)
        if count and len(line) + size > room:
            carried, lead = "", ""
            fits = len(more) + len(line) - word_at + size <= room  # the carried word and this piece, on the next line
            if words and word_at and last != " " and len(line) - word_at <= WORD_LIMIT and fits and not (implied and piece == " "):
                carried, line, last, last_space = line[word_at:], line[:word_at], " ", word_space
            if implied:
                at_space = last == " " or piece == " "
                lines.append(line[:-1] if last == " " else line)
                line, count, word_at = (more if at_space else glued) + carried, 1 if carried else 0, 0
                if piece == " ":  # the cut falls on this space (no word is carried down then), and the mark on the new line stands for it
                    continue
            else:
                if last == " " and len(line) - 1 + len(last_space) <= width:
                    line = line[:-1] + last_space
                elif last == " ":
                    line, lead = line[:-1], last_space
                lines.append(line)
                line, count = more + lead + carried, 1 if carried else 0
                word_at = 0
        if count == 0 and lines and piece[:1] == " ":
            piece = space if piece == " " else piece[1:]
        line += piece
        if piece == " ":
            word_at, word_space = len(line), space
        last, last_space = piece, space
        count += 1
    lines.append(line)
    return lines


def _top_note(text: str, width: int) -> list[str]:
    """A note at the top of the preview, about the inputs below. The words are fixed."""
    return textwrap.wrap(text, width=width, initial_indent="! ", subsequent_indent="! + ")


def _fingerprint_lines(fingerprint: str, width: int) -> list[str]:
    """The last line. On a narrow preview the fingerprint is cut into rows of the same length, so it can be compared row by row."""
    whole = f"Fingerprint: {fingerprint}"
    if len(whole) <= width:
        return [whole]
    more = "  + "
    rows = -(-len(fingerprint) // (width - len(more)))
    while len(fingerprint) % rows:
        rows += 1
    size = len(fingerprint) // rows
    return ["Fingerprint:"] + [more + fingerprint[at : at + size] for at in range(0, len(fingerprint), size)]


def _note_lines(text: str, indent: str, width: int = PREVIEW_WIDTH) -> list[str]:
    """Name the first few characters that are not plain ASCII, since some look exactly like ones that are."""
    odd = {char: None for char in text if ord(char) > 127}
    if not odd:
        return []
    named = [f"U+{ord(char):04X} {unicodedata.name(char, 'unnamed')}" for char in list(odd)[:4]]
    more = f", and {len(odd) - 4} more" if len(odd) > 4 else ""
    mark = indent + "! "
    return textwrap.wrap("not plain ASCII: " + ", ".join(named) + more, width=width, initial_indent=mark, subsequent_indent=mark)


def _in_runs(items: list) -> str:
    """Numbers with each unbroken run written once: 1, 2, 3, 4, 7 becomes "1 to 4, 7". Every number is still named."""
    runs: list = []
    for item in items:
        if runs and item == runs[-1][1] + 1:
            runs[-1][1] = item
        else:
            runs.append([item, item])
    return ", ".join(str(first) if first == last else f"{first}, {last}" if last == first + 1 else f"{first} to {last}" for first, last in runs)


def _first_time_lines(items: Optional[list], indent: str, width: int = PREVIEW_WIDTH) -> list[str]:
    """The note under an input whose value, or some items of it, no approved action has run with before."""
    if items is None:
        what = "this value"
    else:
        if type(items) is not list or not items or any(type(item) is not int or item < 1 for item in items):
            raise RecordError("the items to mark as first time must be a list of numbers from 1")
        what = ("item " if len(items) == 1 else "items ") + _in_runs(items)
    mark = indent + "! "
    text = f"first time: no approved action has run with {what} before"
    return textwrap.wrap(text, width=width, initial_indent=mark, subsequent_indent=mark)


def _age(seconds: float) -> str:
    whole = int(seconds)
    for size, name in ((86400, "day"), (3600, "hour"), (60, "minute"), (1, "second")):
        if whole >= size:
            return f"{whole // size} {name}{'' if whole // size == 1 else 's'}"
    return "under a second"


_NOT_TRACED = {
    NOT_TEXT: "not traced, because it is not text",
    EMPTY: "not traced, because it is empty",
    TOO_MANY: f"only items 1 to {MAX_ITEMS} of this list were traced",
}


def _trail_lines(trail: Any, inputs: dict, indent: str, width: int = PREVIEW_WIDTH) -> tuple[dict, int]:
    """The notes under each watched input that say where its value was seen before.

    Returns the lines for each input, and how many values no source was found for.

    The words are fixed. The two things that are not, the earlier call (its inputs
    were chosen by the model) and the name of a list, are written out the way a
    value is. Any note that does not fit on one line carries on after "! +". So
    nothing in them can pass for a note of its own.

    A call that was handed the value in its own inputs is named, and is not counted
    as a source. Nor is a call that returned the value after the agent had already
    used it in the inputs of some call.

    A trail says where the characters were seen. It never says the action is fine.
    """
    mark, more = indent + "! ", indent + "! + "
    out: dict = {}
    missing = 0
    if type(trail) not in (list, tuple):
        raise RecordError("the trail must be a list")
    for entry in trail:
        try:
            key, item = entry["input"], entry["item"]
            if type(key) is not str or not (item is None or (type(item) is int and item >= 1)):
                raise TypeError
            if key not in inputs:
                continue
            lines = out.setdefault(key, [])
            who = "source: " if item is None else f"source, item {item}: "

            def say(text: str) -> None:
                lines.extend(textwrap.wrap(who + text, width=width, initial_indent=mark, subsequent_indent=more))

            if "not_traced" in entry:
                say(_NOT_TRACED[entry["not_traced"]])
                continue
            seen, extra, typed, known, lost = entry["seen_in"], entry["seen_in_more"], entry["typed"], entry["known"], entry["lost"]
            if type(seen) not in (list, tuple) or type(known) not in (list, tuple) or not (typed is None or type(typed) is bool):
                raise TypeError
            if type(extra) is not int or extra < 0 or type(lost) is not int or lost < 0:
                raise TypeError
            unsure = entry.get("unsure", False)  # a trail worked out before these were added has neither
            if type(unsure) is not bool:
                raise TypeError
            calls = []
            for call in seen:
                tool, label, age, given, used = call["tool"], call["inputs"], call["seconds_before"], call["given"], call.get("used_before", False)
                if type(tool) is not str or not tool or type(label) is not str or type(given) is not bool or type(used) is not bool:
                    raise TypeError
                if not (age is None or (type(age) in (int, float) and math.isfinite(age) and age >= 0)):
                    raise TypeError
                calls.append((tool, label, age, given, used))
            lists = []
            for name, listed in known:
                if type(name) is not str or type(listed) is not bool:
                    raise TypeError
                lists.append((name, listed))
        except (KeyError, TypeError, ValueError):
            raise RecordError("the trail is not in the shape Trail.trace() gives") from None

        # Calls that count as a source come first, so if no call named here does, none of the rest does.
        if all(given or used for _, _, _, given, used in calls) and typed is not True and not any(listed for _, listed in lists):
            missing += 1
            not_found = "source not found for " + ("this value" if item is None else f"item {item}")
            lines.extend(textwrap.wrap(not_found, width=width, initial_indent=mark, subsequent_indent=more))
        for name, listed in lists:
            head = mark + who + ("in" if listed else "not in") + " the app's list "
            written = ['"'] + _pieces(name, quoted=True) + ['"']
            if width < PREVIEW_WIDTH and len(head) + sum(map(len, written)) > width:
                # On a narrow preview, a name that does not fit beside these words carries on below them.
                say(("in" if listed else "not in") + " the app's list")
                head = more
            lines += _fold(head, written, more, width=width)
        if typed is not None:
            say("the owner typed it" if typed else "the owner did not type it")
        for tool, label, age, given, used in calls:
            say("returned by this earlier call" + ("" if age is None else f", {_age(age)} before") + ":")
            lines += _fold(mark + "call: ", _pieces(tool, quoted=False) + ([" "] if label else []) + _pieces(label, quoted=False), more, width=width)
            if given:
                say("that call was handed it in its own inputs, so it is no source")
            elif used and not unsure:
                say("the agent used it before that call, so it is no source")
        if unsure and calls:
            say("too many calls to know if the agent used it first: no source")
        if extra:
            say(f"and returned by {extra} more earlier call{'' if extra == 1 else 's'}")
        if not calls:
            say("not returned by any earlier call")
            if lost:
                say(f"{lost} earlier result{'' if lost == 1 else 's'} not kept in full, so a match there is missed")
    return out, missing


def _text_lines(head: str, label: list[str], text: str, indent: str, noted: str = "", words: bool = False, width: int = PREVIEW_WIDTH) -> list[str]:
    """One-line text in quotes; text with line breaks as a block, one "|" line for each line of it."""
    more = indent + "+ "
    gap = " " if label else ""
    if "\n" not in text:
        value = ['"'] + _pieces(text, quoted=True) + ['"']
        if head == "" and width < PREVIEW_WIDTH and len(head) + sum(map(len, label)) + len(gap) + sum(map(len, value)) > width:
            # On a narrow preview, a value that does not fit beside its heading (the summary, the action, who asked)
            # starts on a line of its own.
            lines = [head + "".join(label)] + _fold(more, value, more, words=words, width=width)
        else:
            lines = _fold(head, label + [gap + value[0]] + value[1:], more, words=words, width=width)
    else:
        parts = text.split("\n")
        lines = _fold(head, label + [f"{gap}[{len(parts)} lines]"], more, width=width)
        for part in parts:
            lines += _fold(indent + "| ", _pieces(part, quoted=False), more, words=words, width=width) if part else [indent + "|"]
    return lines + _note_lines(noted + text, indent, width)


def _json_lines(head: str, label: list[str], value: Any, indent: str, noted: str = "", width: int = PREVIEW_WIDTH) -> list[str]:
    """A value that is not text, written as JSON on one (folded) line.

    With no spaces between its parts, every space in the JSON is inside a string,
    where \\u0020 is JSON's own way to write one. json.dumps has already written
    every character that is not printable ASCII as \\uXXXX.
    """
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    pieces, index = [], 0
    while index < len(text):
        char = text[index]
        if char == "\\":  # a code such as \u202e or \n stays in one piece, so it is never cut in two
            size = 6 if text[index + 1] == "u" else 2
            pieces.append(text[index : index + size])
            index += size
            continue
        if char == " ":
            pieces.append(" " if text[index - 1] != " " and text[index + 1] != " " else _JSON_SPACE)
        else:
            pieces.append(char)
        index += 1
    pieces[0] = " " + pieces[0]
    lines = _fold(head, label + pieces, indent + "+ ", json_from=len(label), width=width)
    return lines + _note_lines(noted + json.dumps(value, ensure_ascii=False), indent, width)
