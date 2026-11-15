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

RECORD_VERSION = 1
MAX_RECORD_BYTES = 1_000_000
MAX_DEPTH = 32
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

    def preview(self, summary: Optional[str] = None) -> str:
        """What a human is shown before saying yes. Written here, from the record.

        It is plain ASCII, no line is longer than PREVIEW_WIDTH, and it can be read
        back to exactly the record: see the notes above _pieces and _fold.
        """
        lines = []
        if summary:
            lines += _text_lines("Summary (written by the app): ", [], summary, "  ")
        lines += _text_lines("Action: ", [], self.tool, "  ")
        if self.actor is not None:
            lines += _text_lines("Asked through (set by the app): ", [], self.actor, "  ")
        inputs = self.inputs()
        if not inputs:
            lines.append("Inputs: none")
        for key in sorted(inputs):
            label = ['"'] + _pieces(key, quoted=True) + ['"', ":"]
            value = inputs[key]
            if type(value) is str:
                lines += _text_lines("  ", label, value, "      ", noted=key)
            else:
                lines += _json_lines("  ", label, value, "      ", noted=key)
        lines.append(f"Fingerprint: {self.fingerprint}")
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
#   - Text from inside a value only ever appears after a quote, a "|" or a "+".

PREVIEW_WIDTH = 78
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


def _fold(head: str, pieces: list[str], more: str, json_from: Optional[int] = None) -> list[str]:
    """Write the pieces after head, in lines of at most PREVIEW_WIDTH characters.

    A line that had to be cut carries on in the next one after `more`. No line ends
    with a bare space and no carried-on line starts with one: a space that would
    land there is written out instead. Pieces from json_from on are JSON, where the
    way to write a space out is \\u0020.

    A space from inside a value is always a piece on its own. A longer piece that
    starts with a space is the gap between a label and its value, which is not part
    of either, so it is left out when the value starts on a carried-on line.
    """
    room = PREVIEW_WIDTH - len(_SPACE)
    lines, line, count, last, last_space = [], head, 0, "", _SPACE
    for index, piece in enumerate(pieces):
        space = _SPACE if json_from is None or index < json_from else _JSON_SPACE
        if count and len(line) + len(piece) > room:
            if last == " ":
                line = line[:-1] + last_space
            lines.append(line)
            line, count = more, 0
        if count == 0 and lines and piece[:1] == " ":
            piece = space if piece == " " else piece[1:]
        line += piece
        last, last_space = piece, space
        count += 1
    lines.append(line)
    return lines


def _note_lines(text: str, indent: str) -> list[str]:
    """Name the first few characters that are not plain ASCII, since some look exactly like ones that are."""
    odd = {char: None for char in text if ord(char) > 127}
    if not odd:
        return []
    named = [f"U+{ord(char):04X} {unicodedata.name(char, 'unnamed')}" for char in list(odd)[:4]]
    more = f", and {len(odd) - 4} more" if len(odd) > 4 else ""
    mark = indent + "! "
    return textwrap.wrap("not plain ASCII: " + ", ".join(named) + more, width=PREVIEW_WIDTH, initial_indent=mark, subsequent_indent=mark)


def _text_lines(head: str, label: list[str], text: str, indent: str, noted: str = "") -> list[str]:
    """One-line text in quotes; text with line breaks as a block, one "|" line for each line of it."""
    more = indent + "+ "
    gap = " " if label else ""
    if "\n" not in text:
        lines = _fold(head, label + [gap + '"'] + _pieces(text, quoted=True) + ['"'], more)
    else:
        parts = text.split("\n")
        lines = _fold(head, label + [f"{gap}[{len(parts)} lines]"], more)
        for part in parts:
            lines += _fold(indent + "| ", _pieces(part, quoted=False), more) if part else [indent + "|"]
    return lines + _note_lines(noted + text, indent)


def _json_lines(head: str, label: list[str], value: Any, indent: str, noted: str = "") -> list[str]:
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
    lines = _fold(head, label + pieces, indent + "+ ", json_from=len(label))
    return lines + _note_lines(noted + json.dumps(value, ensure_ascii=False), indent)
