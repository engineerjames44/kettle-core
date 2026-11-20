"""Ready-made rules: ask only when something about the action is unusual.

    from kettle import rules

    email = rules.email(contacts=["sam@example.com"], me=["alex@example.com"])
    cp.tool("send_email", send, level=email, describe=email.why, watch=["to"])

    pay = rules.payment(payees=["BRIGHTSIDE-CATERING-4410"], limit=200)
    cp.tool("pay", pay_now, level=pay, describe=pay.why, watch=["to"])

    web = rules.web(read=["docs.python.org"], send=["api.example.com"])
    cp.tool("fetch", fetch, level=web, describe=web.why, watch=["url"])

    shell = rules.shell(allow=["pytest", "git add", "git commit"])
    cp.tool("run", run, level=shell, describe=shell.why, watch=["command"])

    write = rules.files(["~/Projects/my-app"], does="write")
    cp.tool("write_file", write_file, level=write, describe=write.why, watch=["path"])

    event = rules.calendar(contacts=["sam@example.com"], me=["alex@example.com"])
    cp.tool("add_event", add_event, level=event, describe=event.why, watch=["attendees"])

    query = rules.database(protect=["payroll"], live=True)
    cp.tool("run_sql", run_sql, level=query, describe=query.why, watch=["sql"])

A rule is called with the inputs of one action and gives FREE, NEEDS_YES or NEVER.
It is plain code. There is no model in it.

How every rule here decides:

- The strictest answer wins. One reason to ask is enough, whatever else is fine.
- Anything the rule cannot read, or was not told about, asks.
- The lists (contacts, payees) are copied when the rule is made. Nothing that
  happens later changes them: to change a list, make the rule again. Give lists
  that came from the owner, never from anything the agent could have written.

What a rule here cannot see: anything but the inputs of the one action (the files
rule also looks at where a path really leads on this machine). It does not
know what ran before, so it cannot add up payments over a day or count emails in an
hour. It lowers how often the owner is asked. It is the checkpoint, not the rule,
that holds an action until the owner says yes.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional
from urllib.parse import unquote

from .checkpoint.rules import FREE, NEEDS_YES, NEVER, RulesError

__all__ = ["Rule", "Verdict", "email", "payment", "web", "shell", "files", "calendar", "database", "hidden", "sensitive"]

_STRICTNESS = {FREE: 0, NEEDS_YES: 1, NEVER: 2}
MAX_REASONS = 4  # how many reasons why() writes out before it says "and N more"


@dataclass(frozen=True)
class Verdict:
    """What a rule says about one action: the level, and every reason found for it."""

    level: str
    reasons: tuple


class Rule:
    """A ready-made rule. Call it with a tool's inputs to get the level.

    explain() gives the level with its reasons. why() gives the reasons as one
    line of text, which fits `describe=` so the approval says why it is asking.
    """

    kind = "rule"

    def __init__(self, settings: dict) -> None:
        text = json.dumps(settings, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        mark = hashlib.sha256(text.encode("ascii")).hexdigest()[:12]
        object.__setattr__(self, "_settings", text)
        # The checkpoint writes a rule function into its rules digest by this name.
        # With the settings in the name, a changed limit or list changes the digest.
        object.__setattr__(self, "__qualname__", f"kettle.rules.{self.kind}:{mark}")

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("a rule's settings are fixed when it is made: make a new rule to change them")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("a rule's settings are fixed when it is made: make a new rule to change them")

    def __call__(self, inputs: dict) -> str:
        return self.explain(inputs).level

    def settings(self) -> dict:
        """What this rule was made with, as a fresh copy."""
        return json.loads(self._settings)

    def explain(self, inputs: dict) -> Verdict:
        if type(inputs) is not dict:
            return Verdict(NEEDS_YES, ("the inputs cannot be read",))
        found = self._look(inputs)
        level = max((level for level, _ in found), key=_STRICTNESS.__getitem__, default=FREE)
        reasons = tuple(dict.fromkeys(reason for found_level, reason in found if found_level == level))
        return Verdict(level, reasons)

    def reasons_in(self, inputs: dict) -> tuple:
        """The reasons to ask that come from the inputs and where they lead.

        The checkpoint keeps these when it holds an action, and asks again for them
        at the yes and at the run: a reason that was not there when the owner was
        asked cancels the yes. For a ready-made rule they are the reasons explain()
        gives.
        """
        return self._both(inputs)[1]

    def seen(self, inputs: dict) -> tuple:
        """why() and reasons_in() from one look at the inputs, as (text, reasons).

        The checkpoint uses this when a tool's describe is the rule's own why(), so
        the card the owner reads and the reasons it keeps come from the same look:
        a link that changes between two looks cannot make them differ.
        """
        verdict, reasons = self._both(inputs)
        return self._said(verdict), reasons

    def _both(self, inputs: dict) -> tuple:
        verdict = self.explain(inputs)
        return verdict, verdict.reasons

    def why(self, inputs: dict) -> str:
        return self._said(self.explain(inputs))

    def _said(self, verdict: Verdict) -> str:
        if verdict.level == FREE:
            return "Runs without asking: " + self._fine
        reasons = list(verdict.reasons[:MAX_REASONS])
        if len(verdict.reasons) > MAX_REASONS:
            reasons.append(f"and {len(verdict.reasons) - MAX_REASONS} more")
        return ("Never allowed: " if verdict.level == NEVER else "Asks because: ") + "; ".join(reasons)

    _fine = "nothing unusual was found"

    def _look(self, inputs: dict) -> list:
        raise NotImplementedError


# ---- what is being sent --------------------------------------------------------------
#
# These look at text that is going out. Each returns the kinds of thing found, in
# plain words, and never the text itself, so a reason cannot carry a secret onwards.

_HIDDEN_RANGES = (
    (0x200B, 0x200F),  # zero-width space and joiners, left-to-right and right-to-left marks
    (0x202A, 0x202E),  # direction overrides: text that reads one way and is stored another
    (0x2060, 0x2064),  # word joiner and the invisible operators
    (0x2066, 0x2069),  # direction isolates
    (0xE0000, 0xE007F),  # tag characters: a whole unseen alphabet
)
_HIDDEN_SINGLE = {0x00AD, 0x034F, 0x061C, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x180E, 0x3164, 0xFEFF, 0xFFA0}
_MARKUP = (
    ("a comment in the markup", re.compile(r"<!--")),
    ("markup that hides text", re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?:\.0+)?(?:px|pt|em|rem|%)?\s*(?:[;\"'}]|$)", re.I)),
)


def hidden(text: str) -> list:
    """The kinds of unseen text in `text`: characters with no width, control characters, markup that hides.

    What it misses: text that is only hard to see (pale, tiny but not zero, off the
    side of the page), and anything inside a picture or an attached file.
    What it flags that is harmless: an emoji built from several joined with a
    zero-width joiner.
    """
    found = []
    if any(_is_hidden(ord(character)) for character in text):
        found.append("characters that cannot be seen")
    if any(_is_control(ord(character)) for character in text):
        found.append("control characters")
    found += [name for name, pattern in _MARKUP if pattern.search(text)]
    return found


def _is_hidden(code: int) -> bool:
    return code in _HIDDEN_SINGLE or any(low <= code <= high for low, high in _HIDDEN_RANGES)


def _is_control(code: int) -> bool:
    return (code < 0x20 and code not in (0x09, 0x0A, 0x0D)) or 0x7F <= code <= 0x9F


_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_IBAN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{2}\d{2}(?: ?[A-Za-z0-9]){11,30}(?![A-Za-z0-9])")
_KEYS = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\bsk-[A-Za-z0-9_-]{16,}"
    r"|\bgh[pousr]_[A-Za-z0-9]{20,}"
    r"|\bgithub_pat_[A-Za-z0-9_]{20,}"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\bAIza[0-9A-Za-z_-]{30,}"
    r"|\bxox[abprs]-[A-Za-z0-9-]{10,}"
    r"|\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}"
    r"|(?<!\d)\d{8,10}:[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])"
)
_PASSWORD = re.compile(
    r"\b(?:pass(?:word|wd|phrase|code)|pwd)\b\s*(?:is\b|[:=])\s*\S{3,}"
    r"|\bpin\b\s*(?:is\b|[:=])\s*\d{3,}"
    r"|\b(?:secret|token|api[ _-]?key|access[ _-]?key|private[ _-]?key)\b\s*[:=]\s*\S{3,}",
    re.I,
)
_ENTRY_CODE = re.compile(r"\b(?:door|alarm|gate|security)\s*code\b\s*(?:is\b|[:=])?\s*\d{3,}", re.I)
_BANK = re.compile(r"\b(?:sort\s*code|routing(?:\s*(?:number|no\.?))?|account\s*(?:number|no\.?)|acct\.?(?:\s*(?:number|no\.?))?)\s*(?:is\b|[:=#])?\s*\d[\d -]{4,}", re.I)
_ID_NUMBER = re.compile(r"(?<![\d-])\d{3}-\d{2}-\d{4}(?![\d-])|(?<![A-Za-z0-9])\d{7}[A-Wa-w][A-IWa-iw]?(?![A-Za-z0-9])")


def sensitive(text: str) -> list:
    """The kinds of private data in `text` that have a known shape: card numbers, keys, passwords, door and alarm codes, bank details, ID numbers.

    What it misses: the same data written out in words, encoded, split into pieces,
    or in a shape that is not on this list.
    """
    found = []
    if any(_luhn(re.sub(r"\D", "", match.group())) for match in _CARD.finditer(text)):
        found.append("a card number")
    if _KEYS.search(text):
        found.append("a key or token")
    if _PASSWORD.search(text):
        found.append("a password")
    if _ENTRY_CODE.search(text):
        found.append("a door or alarm code")
    if _BANK.search(text) or any(_iban(match.group()) for match in _IBAN.finditer(text)):
        found.append("bank details")
    if _ID_NUMBER.search(text):
        found.append("an ID number")
    return found


def _luhn(digits: str) -> bool:
    if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:
        return False
    total = 0
    for place, digit in enumerate(reversed(digits)):
        number = int(digit)
        if place % 2:
            number = number * 2 - 9 if number > 4 else number * 2
        total += number
    return total % 10 == 0


def _iban(text: str) -> bool:
    """True if `text`, or a start of it, is an account number in the international form, by its check digits.

    The pattern that found `text` may have run on into the words after the number,
    so each length a real one can have is tried.
    """
    plain = text.replace(" ", "").upper()
    for length in range(15, min(34, len(plain)) + 1):
        moved = plain[4:length] + plain[:4]
        if int("".join(str(int(character, 36)) for character in moved)) % 97 == 1:
            return True
    return False


def _texts(value: Any) -> Iterable[str]:
    """Every piece of text inside a value, the names of inputs inside it too."""
    if type(value) is str:
        yield value
    elif type(value) is list:
        for item in value:
            yield from _texts(item)
    elif type(value) is dict:
        for key, item in value.items():
            yield key
            yield from _texts(item)


def _content(inputs: dict, skip: Iterable[str]) -> list:
    """What the content checks find in everything but the inputs named in `skip`."""
    found = []
    for key in sorted(set(inputs) - set(skip)):
        for text in _texts(inputs[key]):
            found += [(NEEDS_YES, f"what is being sent holds what looks like {kind}") for kind in sensitive(text)]
            found += [(NEEDS_YES, f"what is being sent holds {kind}") for kind in hidden(text)]
    return found


# ---- addresses -----------------------------------------------------------------------

_ADDRESS = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"
_WHOLE_ADDRESS = re.compile(_ADDRESS)
_ANY_ADDRESS = re.compile(r"[^\s<>()\[\]\"',;:]+@[^\s<>()\[\]\"',;:]+")
_NAMED = re.compile(r"([^<>@]*)<([^<>]*)>")


def _address(text: str) -> Optional[str]:
    """One address, lower-cased, if `text` is an address and nothing else. `Name <address>` counts."""
    text = text.strip(" ")
    named = _NAMED.fullmatch(text)
    if named is not None:
        text = named.group(2).strip(" ")
    return text.lower() if _WHOLE_ADDRESS.fullmatch(text) else None


def _split(text: str) -> list:
    """The pieces of `text` between commas and semicolons, leaving alone the ones inside quotes or <>."""
    pieces, piece, quoted, inside = [], [], False, False
    for character in text:
        if character == '"':
            quoted = not quoted
        elif character == "<" and not quoted:
            inside = True
        elif character == ">" and not quoted:
            inside = False
        if character in ",;" and not quoted and not inside:
            pieces.append("".join(piece))
            piece = []
        else:
            piece.append(character)
    pieces.append("".join(piece))
    return [piece for piece in pieces if piece.strip(" ")]


def _recipients(value: Any) -> Optional[list]:
    """The addresses a recipients input names, or None if any part of it cannot be read for certain.

    A tool may read its own input more loosely than this does. So this is strict:
    a line break, an unseen character, an "@" that is not part of an address that
    was read, or anything else left over, and the whole input counts as unreadable.
    """
    if value is None:
        return []
    items = value if type(value) is list else [value]
    found = []
    for item in items:
        if type(item) is not str:
            return None
        if any(ord(character) < 0x20 or ord(character) == 0x7F for character in item) or hidden(item):
            return None
        pieces = _split(item)
        addresses = [_address(piece) for piece in pieces]
        if None in addresses or item.count("@") != len(addresses):
            return None
        found += addresses
    return list(dict.fromkeys(found))


def _loose_addresses(value: Any) -> set:
    """Everything in a value that could be an address, read as loosely as a careless tool might. For the block list."""
    return {match.group().strip(".").lower() for text in _texts(value) for match in _ANY_ADDRESS.finditer(text)}


def _address_list(name: str, values: Any, domains: bool = False) -> frozenset:
    """A list given at setup, checked and copied."""
    if values is None:
        return frozenset()
    if type(values) not in (list, tuple, set, frozenset):
        raise RulesError(f"{name} must be a list of addresses, given as the list itself")
    kept = set()
    for value in values:
        if type(value) is not str:
            raise RulesError(f"{name} must hold addresses as text")
        if domains and value.startswith("@") and _WHOLE_ADDRESS.fullmatch("x" + value.strip(" ")):
            kept.add(value.strip(" ").lower())
            continue
        address = _address(value) if "<" not in value else None
        if address is None:
            raise RulesError(f"{name}: {value!r} is not an email address")
        kept.add(address)
    return frozenset(kept)


def _domain_list(name: str, values: Any) -> frozenset:
    if values is None:
        return frozenset()
    if type(values) not in (list, tuple, set, frozenset):
        raise RulesError(f"{name} must be a list of domains, given as the list itself")
    kept = set()
    for value in values:
        if type(value) is not str or not _WHOLE_ADDRESS.fullmatch("x@" + value.strip(" ").lstrip("@")):
            raise RulesError(f"{name}: {value!r} is not a domain, such as example.com")
        kept.add(value.strip(" ").lstrip("@").lower())
    return frozenset(kept)


# ---- look-alikes ---------------------------------------------------------------------
#
# A look-alike only ever adds a warning to an ask. An address that is not on a list
# asks whether or not it looks like one that is.


def _near(one: str, other: str, most: int) -> bool:
    """True if `one` can be turned into `other` with at most `most` single-character changes."""
    if abs(len(one) - len(other)) > most:
        return False
    row = list(range(len(other) + 1))
    for index, character in enumerate(one, 1):
        last, row[0] = row[0], index
        for place, target in enumerate(other, 1):
            last, row[place] = row[place], min(row[place] + 1, row[place - 1] + 1, last + (character != target))
        if min(row) > most:
            return False
    return row[-1] <= most


def _shape(text: str) -> str:
    """Text with the characters people misread for each other made the same, and the joining marks taken out."""
    text = text.replace("I", "l").lower()
    for seen, read in (("rn", "m"), ("vv", "w"), ("0", "o"), ("1", "l"), ("5", "s")):
        text = text.replace(seen, read)
    return re.sub(r"[._+-]", "", text)


_SHARED_NAMES = frozenset(
    "accounts admin billing contact enquiries finance hello help info mail no-reply noreply office orders sales support team".split()
)


def _mistaken(domain: str, known: str) -> bool:
    """True if `domain` could be misread as `known`, or is `known` with more on the end."""
    return _shape(domain) == _shape(known) or _near(domain, known, 1 if len(known) < 8 else 2) or domain.startswith(known + ".")


def _related(domain: str, known: str) -> bool:
    return _mistaken(domain, known) or known in domain or domain.rsplit(".", 1)[0] == known.rsplit(".", 1)[0]


def _looks_like_address(address: str, listed: frozenset) -> Optional[tuple]:
    """The listed address that `address` could be taken for, if there is one, and whether only its domain is alike."""
    name, _, domain = address.partition("@")
    by_domain = None
    for known in sorted(listed):
        known_name, _, known_domain = known.partition("@")
        same_name = _shape(name) == _shape(known_name) or (min(len(name), len(known_name)) >= 4 and _near(name, known_name, 1))
        if domain == known_domain:
            if same_name:
                return known, False
        elif (name == known_name and name not in _SHARED_NAMES) or (same_name and _related(domain, known_domain)):
            return known, False
        elif by_domain is None and _mistaken(domain, known_domain):
            by_domain = known
    return None if by_domain is None else (by_domain, True)


def _shown_address(address: str) -> str:
    """An address as it may be written in a reason. A very long one is not written, so it cannot crowd the others out."""
    return address if len(address) <= 64 else "an address too long to show here"


def _words(text: str) -> set:
    return {word for word in re.findall(r"[a-z]{3,}", text.lower())}


def _looks_like_payee(payee: str, listed: Iterable[str]) -> Optional[str]:
    words = _words(payee)
    for known in sorted(listed):
        known_words = _words(known)
        if _shape(payee) == _shape(known) or _near(payee.lower(), known.lower(), 2):
            return known
        if known_words and len(words & known_words) * 2 >= len(known_words) and len(words & known_words) >= min(2, len(known_words)):
            return known
    return None


# ---- email ---------------------------------------------------------------------------


class _Email(Rule):
    kind = "email"
    _fine = "every address is one of yours or in your contacts, and nothing unusual was found in what is sent"

    def __init__(self, contacts, me, blocked, own_domains, max_recipients, fields) -> None:
        object.__setattr__(self, "_contacts", contacts)
        object.__setattr__(self, "_me", me)
        object.__setattr__(self, "_blocked", blocked)
        object.__setattr__(self, "_own_domains", own_domains)
        object.__setattr__(self, "_max", max_recipients)
        object.__setattr__(self, "_fields", fields)
        super().__init__(
            {
                "contacts": sorted(contacts),
                "me": sorted(me),
                "blocked": sorted(blocked),
                "own_domains": sorted(own_domains),
                "max_recipients": max_recipients,
                "fields": fields,
            }
        )

    def _look(self, inputs: dict) -> list:
        fields = self._fields
        found = []
        unknown = sorted(set(inputs) - set(fields.values()))
        if unknown:
            found.append((NEEDS_YES, f"the rule was not told about {len(unknown)} of the inputs"))

        # The block list is read loosely, so an address written in an odd way is still caught.
        loose = _loose_addresses({key: inputs[key] for key in inputs if key in (fields["to"], fields["cc"], fields["bcc"])})
        if any(self._is_blocked(address) for address in loose):
            found.append((NEVER, "an address is on your block list"))

        everyone, unread = [], False
        for kind in ("to", "cc", "bcc"):
            addresses = _recipients(inputs.get(fields[kind]))
            if addresses is None:
                found.append((NEEDS_YES, f'the "{kind}" input cannot be read for certain as a list of addresses'))
                unread = True
                continue
            if kind == "bcc" and addresses:
                found.append((NEEDS_YES, "it has a hidden copy (BCC)"))
            everyone += addresses
        everyone = list(dict.fromkeys(everyone))
        if not everyone and not unread:
            found.append((NEEDS_YES, "no address to send to was found"))
        if len(everyone) > self._max:
            found.append((NEEDS_YES, f"it goes to {len(everyone)} addresses, more than {self._max}"))

        trusted = self._contacts | self._me
        for address in everyone:
            if address in trusted:
                continue
            alike = _looks_like_address(address, trusted)
            if alike is None:
                found.append((NEEDS_YES, f"{_shown_address(address)} is not in your contacts"))
            elif alike[1]:
                found.append((NEEDS_YES, f"{_shown_address(address)} is not in your contacts, and its domain looks like the one in {alike[0]}, which is"))
            else:
                found.append((NEEDS_YES, f"{_shown_address(address)} is not in your contacts, and it looks like {alike[0]}, which is"))

        if _has_any(inputs.get(fields["attachments"])):
            if not everyone or any(address not in self._me and address.partition("@")[2] not in self._own_domains for address in everyone):
                found.append((NEEDS_YES, "it has an attachment going to someone outside your own addresses"))

        return found + _content(inputs, skip=(fields["to"], fields["cc"], fields["bcc"]))

    def _is_blocked(self, address: str) -> bool:
        domain = address.partition("@")[2]
        return address in self._blocked or any(entry.startswith("@") and (domain == entry[1:] or domain.endswith("." + entry[1:])) for entry in self._blocked)


def _has_any(value: Any) -> bool:
    """True unless the value is plainly nothing: missing, empty text, an empty list."""
    return value is not None and value != "" and value != [] and value != {}


def email(
    contacts: Any,
    *,
    me: Any = (),
    blocked: Any = (),
    own_domains: Any = (),
    max_recipients: int = 3,
    to: str = "to",
    cc: str = "cc",
    bcc: str = "bcc",
    subject: str = "subject",
    body: str = "body",
    attachments: str = "attachments",
) -> Rule:
    """A rule for a tool that sends email.

    Runs without asking only when all of this is true:
    every address (to, cc) is in `contacts` or `me`; there is no BCC; there are no
    more than `max_recipients` addresses; any attachment goes only to `me` or to
    `own_domains`; and nothing in the rest of the inputs looks like private data
    or holds text that cannot be seen.

    Never: an address in `blocked`. An entry such as "@example.net" blocks a whole domain.
    Everything else asks. So does an input the rule was not told the name of:
    the last six settings say what your tool calls its inputs.

    An address is compared without regard to capitals. Nothing else is treated as
    the same: sam+x@example.com is not sam@example.com.

    `contacts` must come from the owner. If the agent can add to wherever your
    app gets it from, an attacker can ask the agent to add them first.
    """
    contacts = _address_list("contacts", contacts)
    me = _address_list("me", me)
    blocked = _address_list("blocked", blocked, domains=True)
    own_domains = _domain_list("own_domains", own_domains)
    if type(max_recipients) is not int or max_recipients < 1:
        raise RulesError("max_recipients must be a whole number, 1 or more")
    listed_twice = sorted((contacts | me) & blocked)
    if listed_twice:
        raise RulesError(f"{listed_twice[0]} is in blocked and also in contacts or me")
    fields = _fields(to=to, cc=cc, bcc=bcc, subject=subject, body=body, attachments=attachments)
    return _Email(contacts, me, blocked, own_domains, max_recipients, fields)


def _fields(**names: Any) -> dict:
    for role, name in names.items():
        if type(name) is not str or not name:
            raise RulesError(f"{role} must be the name of an input, as text")
    if len(set(names.values())) != len(names):
        raise RulesError("two of the input names given are the same")
    return dict(names)


# ---- payments ------------------------------------------------------------------------

_PLAIN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._&'/-]{0,63}")
_AMOUNT_TEXT = re.compile(r"[0-9]{1,15}(?:\.[0-9]{1,2})?")


def _amount(value: Any) -> Optional[Decimal]:
    """The amount as an exact number, or None if it is not plainly one."""
    if type(value) is int:
        return Decimal(value)
    if type(value) is float and math.isfinite(value):
        return Decimal(repr(value))
    if type(value) is str and _AMOUNT_TEXT.fullmatch(value):
        return Decimal(value)
    return None


def _number(name: str, value: Any) -> Decimal:
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise RulesError(f"{name} must be a number above 0")
    try:
        return Decimal(repr(value))
    except InvalidOperation:
        raise RulesError(f"{name} must be a number above 0") from None


def _shown(name: str) -> str:
    """A payee's name as it may be written in a reason, or a plain stand-in if it holds anything odd."""
    return name if _PLAIN_NAME.fullmatch(name) else "the payee"


class _Payment(Rule):
    kind = "payment"
    _fine = "the payee is one of yours, the amount is within your limit, and nothing unusual was found"

    def __init__(self, payees, accounts, limit, ceiling, currencies, fields) -> None:
        object.__setattr__(self, "_payees", payees)
        object.__setattr__(self, "_accounts", accounts)
        object.__setattr__(self, "_limit", limit)
        object.__setattr__(self, "_ceiling", ceiling)
        object.__setattr__(self, "_currencies", currencies)
        object.__setattr__(self, "_fields", fields)
        super().__init__(
            {
                "payees": sorted(payees) if accounts is None else sorted(accounts.items()),
                "limit": str(limit),
                "ceiling": None if ceiling is None else str(ceiling),
                "currencies": None if currencies is None else sorted(currencies),
                "fields": fields,
            }
        )

    def _look(self, inputs: dict) -> list:
        fields = self._fields
        found = []
        known = {fields["to"], fields["amount"], fields["note"]}
        if self._accounts is not None:
            known.add(fields["account"])
        if self._currencies is not None:
            known.add(fields["currency"])
        unknown = sorted(set(inputs) - known)
        if unknown:
            found.append((NEEDS_YES, f"the rule was not told about {len(unknown)} of the inputs"))

        payee = inputs.get(fields["to"])
        if type(payee) is not str or not payee:
            found.append((NEEDS_YES, "the payee cannot be read"))
        elif payee not in self._payees:
            alike = _looks_like_payee(payee, self._payees)
            if alike is not None:
                found.append((NEEDS_YES, f"{_shown(payee)} is not one of your payees, and it looks like {_shown(alike)}, which is"))
            else:
                found.append((NEEDS_YES, f"{_shown(payee)} is not one of your payees"))
        elif self._accounts is not None and inputs.get(fields["account"]) != self._accounts[payee]:
            found.append((NEEDS_YES, f"the account is not the one you gave for {_shown(payee)}"))

        amount = _amount(inputs.get(fields["amount"]))
        if amount is None or amount <= 0:
            found.append((NEEDS_YES, "the amount is not plainly a number above 0"))
        else:
            if amount > self._limit:
                found.append((NEEDS_YES, f"the amount is over your limit of {self._limit}"))
            if self._ceiling is not None and amount > self._ceiling:
                found.append((NEVER, f"the amount is over your ceiling of {self._ceiling}"))

        if self._currencies is not None:
            currency = inputs.get(fields["currency"])
            if type(currency) is not str or currency not in self._currencies:
                found.append((NEEDS_YES, "the currency is not one your limit is in"))

        return found + _content(inputs, skip=(fields["to"], fields["amount"], fields["account"], fields["currency"]))


def payment(
    payees: Any,
    *,
    limit: Any,
    ceiling: Any = None,
    currencies: Any = None,
    to: str = "to",
    amount: str = "amount",
    account: str = "account",
    currency: str = "currency",
    note: str = "note",
) -> Rule:
    """A rule for a tool that pays.

    Runs without asking only when all of this is true:
    the payee is in `payees`, character for character; the amount is plainly a
    number above 0 and no more than `limit`; and nothing in the note looks like
    private data or holds text that cannot be seen.

    `payees` is a list of the names or account numbers your tool pays to. If your
    tool takes a name and an account as two inputs, give a dict of name to
    account: a payee you know with any other account then asks. That is the
    invoice scam, where a real supplier's bill carries the thief's account.

    Never: an amount over `ceiling`, if you set one. Everything else asks.

    If your tool takes a currency, say which ones `limit` is in, such as
    currencies=["EUR"]. Any other currency asks. If you do not, a call that gives
    a currency asks, because the rule was not told about that input.

    What it cannot do: add up payments. Ten payments under the limit to a payee
    you know all run without asking. The money can only go to payees on your list.
    """
    accounts = None
    if type(payees) is dict:
        if not all(type(name) is str and name and type(number) is str and number for name, number in payees.items()):
            raise RulesError("payees as a dict must map each payee's name to its account, both as text")
        accounts = dict(payees)
        names = frozenset(accounts)
    elif type(payees) in (list, tuple, set, frozenset):
        if not all(type(name) is str and name for name in payees):
            raise RulesError("payees must hold names or account numbers as text")
        names = frozenset(payees)
    else:
        raise RulesError("payees must be a list, or a dict of name to account, given as the thing itself")
    limit = _number("limit", limit)
    if ceiling is not None:
        ceiling = _number("ceiling", ceiling)
        if ceiling < limit:
            raise RulesError("ceiling must not be below limit")
    if currencies is not None:
        if type(currencies) not in (list, tuple, set, frozenset) or not currencies or not all(type(code) is str and code for code in currencies):
            raise RulesError('currencies must be a list of currency codes as text, such as ["EUR"]')
        currencies = frozenset(currencies)
    fields = _fields(to=to, amount=amount, account=account, currency=currency, note=note)
    return _Payment(names, accounts, limit, ceiling, currencies, fields)


# ---- web requests --------------------------------------------------------------------
#
# The rule reads the address itself, and strictly. The tricks here are the ones
# where two programs read one address as two different sites, so an address that
# is not written the one plain way asks, and one that may point home is refused.

_SITE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*")
_WEB_ADDRESS = re.compile(r"([Hh][Tt][Tt][Pp][Ss]?)://(\[[^\[\]/?#@]*\]|[^\[\]/?#@:]*)(:[^/?#@]*)?(/.*)?")
_PORT = re.compile(r":[1-9][0-9]{0,4}")
_NUMBER_LABEL = re.compile(r"[0-9]+|0x[0-9a-f]*")
_LOCAL_ENDINGS = (".localhost", ".local", ".localdomain", ".internal", ".intranet", ".lan", ".home", ".home.arpa", ".corp", ".private")
_PROGRAMS = frozenset("apk app appimage bat bin cmd deb dmg exe jar msi pkg ps1 rpm run scr sh vbs".split())
_READS, _SENDS, _REMOVES = ("GET", "HEAD"), ("POST", "PUT", "PATCH"), ("DELETE",)
_UNSURE = "the address cannot be read for certain"
_HOME = "the address is on this machine or your own network"
_MAYBE_HOME = "the address cannot be read for certain, and may point at this machine or your own network"


@dataclass(frozen=True)
class _Place:
    """A web address the rule could read for certain."""

    site: str  # the name of the site, in small letters
    secure: bool  # https
    usual_port: bool
    rest: str  # everything after the site and the port


def _part(text: str) -> Optional[int]:
    """One piece of a numbered address, read the way programs do: 0x is base 16 and a leading 0 is base 8."""
    if len(text) > 20:
        return None
    if text.startswith("0x"):
        return int(text[2:] or "0", 16) if re.fullmatch(r"[0-9a-f]*", text[2:]) else None
    if len(text) > 1 and text.startswith("0"):
        return int(text, 8) if re.fullmatch(r"[0-7]+", text) else None
    return int(text) if re.fullmatch(r"[0-9]+", text) else None


def _four(name: str) -> Optional[ipaddress.IPv4Address]:
    """A numbered address in any of the forms programs take: 127.0.0.1, 127.1, 0x7f.0.0.1, 2130706433."""
    numbers = [_part(piece) for piece in name.split(".")]
    if len(numbers) > 4 or None in numbers:
        return None
    if any(number > 255 for number in numbers[:-1]) or numbers[-1] >= 256 ** (5 - len(numbers)):
        return None
    return ipaddress.IPv4Address(sum(number << (8 * (3 - place)) for place, number in enumerate(numbers[:-1])) + numbers[-1])


def _six(text: str) -> Optional[Any]:
    try:
        address = ipaddress.IPv6Address(text.partition("%")[0])
    except ValueError:
        return None
    inside = address.ipv4_mapped or address.sixtofour
    if inside is None and int(address) >> 32 in (0, 0x64FF9B << 64):
        inside = ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)  # ::127.0.0.1, and 64:ff9b::127.0.0.1
    return inside or address


def _public(address: Any) -> bool:
    """True for a numbered address out on the internet: not this machine, a private network, or a group of machines."""
    return address.is_global and not address.is_multicast


def _is_number(host: str) -> bool:
    """True if programs would take `host` for a numbered address and not a name."""
    return host.startswith("[") or bool(_NUMBER_LABEL.fullmatch(host.rstrip(".").rsplit(".", 1)[-1]))


def _local(host: str) -> bool:
    """True if `host` is this machine or a private network, or a numbered address that is not plainly a public one."""
    if host.startswith("["):
        address = _six(host[1:-1]) if host.endswith("]") else None
        return address is None or not _public(address)
    name = host[:-1] if host.endswith(".") else host
    if not name:
        return False
    if _is_number(name):
        address = _four(name)
        return address is None or not _public(address)
    return "." not in name or name == "localhost" or name.endswith(_LOCAL_ENDINGS)


def _plain(address: str) -> str:
    """A hard-to-read address the way a forgiving program might take it."""
    text = unicodedata.normalize("NFKC", address).replace("。", ".")
    text = "".join(character for character in text if 0x20 < ord(character) < 0x7F)
    return unquote(text.replace("\\", "/"), errors="replace").lower()


def _loose_hosts(plain: str) -> list:
    """Every host a forgiving program might find in an address."""
    after = re.sub(r"^(?:[a-z][a-z0-9+.-]*:/+|/+)", "", plain)
    hosts = []
    for piece in re.split(r"[/?#]", after, maxsplit=1)[0].split("@"):
        hosts += [piece, piece.rsplit(":", 1)[0]]
    return hosts


def _place(address: Any) -> Any:
    """The address as a _Place, or the (level, reason) that says why it could not be taken as one."""
    if type(address) is not str or not address:
        return NEEDS_YES, "the address cannot be read"
    plain = _plain(address)
    if plain.startswith("file:"):
        return NEVER, "the address is a file on this machine"
    unsure = (NEVER, _MAYBE_HOME) if any(_local(host) for host in _loose_hosts(plain)) else (NEEDS_YES, _UNSURE)
    found = _WEB_ADDRESS.fullmatch(address)
    if found is None or any(not 0x20 < ord(character) < 0x7F or character == "\\" for character in address):
        return unsure
    host = found.group(2).lower()
    if _local(host) or _local(unquote(host, errors="replace")):
        return NEVER, _HOME
    if _is_number(host):
        return NEEDS_YES, "the address is a number, not the name of a site"
    if not _SITE.fullmatch(host) or len(host) > 253:
        return unsure
    secure = found.group(1).lower() == "https"
    port = found.group(3)
    if port is not None and (not _PORT.fullmatch(port) or int(port[1:]) > 65535):
        return unsure
    return _Place(host, secure, port is None or int(port[1:]) == (443 if secure else 80), found.group(4) or "")


def _carried(rest: str, most: int, measure: bool) -> list:
    """What is unusual in the part of an address after the site: data being carried out, or a program coming in."""
    found = []
    before, _, fragment = rest.partition("#")
    path, _, query = before.partition("?")
    if measure and (len(rest) > 4 * most or len(query) > most or len(fragment) > most or any(len(piece) > most for piece in path.split("/"))):
        found.append((NEEDS_YES, "the address carries a long string of data"))
    decoded = unquote(rest, errors="replace")
    for text in (rest, decoded):
        found += [(NEEDS_YES, f"the address holds what looks like {kind}") for kind in sensitive(text)]
    if any(ord(character) < 0x20 for character in decoded) or hidden(decoded):
        found.append((NEEDS_YES, "the address holds text that cannot be seen once it is decoded"))
    name = unquote(path, errors="replace").rsplit("/", 1)[-1].rstrip(". ").lower()
    if "." in name and name.rsplit(".", 1)[1] in _PROGRAMS:
        found.append((NEEDS_YES, "the address ends like a program to download"))
    return found


class _Web(Rule):
    kind = "web"
    _fine = "the site is one you allow for this, and nothing unusual was found"

    def __init__(self, read, send, most, fields) -> None:
        object.__setattr__(self, "_read", read | send)
        object.__setattr__(self, "_send", send)
        object.__setattr__(self, "_most", most)
        object.__setattr__(self, "_fields", fields)
        super().__init__({"read": sorted(read), "send": sorted(send), "max_data": most, "fields": fields})

    def _look(self, inputs: dict) -> list:
        fields = self._fields
        found = []
        untold = len(set(inputs) - set(fields.values()))
        if untold:
            found.append((NEEDS_YES, f"the rule was not told about {untold} of the inputs"))

        method = inputs.get(fields["method"])
        method = "GET" if method is None else method.upper() if type(method) is str and method.isascii() else None
        sending = False
        if method not in _READS + _SENDS + _REMOVES:
            found.append((NEEDS_YES, "the method is not GET, HEAD, POST, PUT, PATCH or DELETE"))
        elif method in _REMOVES:
            found.append((NEEDS_YES, "a DELETE request removes something"))
        else:
            sending = method in _SENDS or _has_any(inputs.get(fields["body"])) or _has_any(inputs.get(fields["headers"]))

        place = _place(inputs.get(fields["url"]))
        if type(place) is tuple:
            found.append(place)
        else:
            allowed = self._send if sending else self._read
            if place.site not in allowed:
                found.append((NEEDS_YES, self._stranger(place.site, sending, allowed)))
            if not place.secure:
                found.append((NEEDS_YES, "the address is http, not https"))
            if not place.usual_port:
                found.append((NEEDS_YES, "the address names an unusual port"))
            found += _carried(place.rest, self._most, measure=place.site not in self._send)
        return found + _content(inputs, skip=(fields["url"], fields["method"]))

    def _stranger(self, site: str, sending: bool, allowed: frozenset) -> str:
        if sending and site in self._read:
            return f"you allow reading {site}, but not sending to it"
        reason = f"{_shown_address(site)} is not one of the sites you allow {'sending to' if sending else 'reading'}"
        alike = next((known for known in sorted(allowed) if _mistaken(site, known) or known in site), None)
        return reason if alike is None else f"{reason}, and it looks like {alike}, which is"


def _site_list(name: str, values: Any) -> frozenset:
    """A list of sites given at setup, checked and copied."""
    if values is None:
        return frozenset()
    if type(values) not in (list, tuple, set, frozenset):
        raise RulesError(f"{name} must be a list of site names, given as the list itself")
    kept = set()
    for value in values:
        site = value.strip(" ").lower() if type(value) is str else ""
        if not _SITE.fullmatch(site) or len(site) > 253 or "." not in site or _is_number(site):
            raise RulesError(f"{name}: {value!r} is not the name of a site, such as example.com")
        if _local(site):
            raise RulesError(f"{name}: {value!r} is on this machine or your own network, which a web rule never allows")
        kept.add(site)
    return frozenset(kept)


def web(
    read: Any = None,
    *,
    send: Any = None,
    max_data: int = 80,
    url: str = "url",
    method: str = "method",
    body: str = "body",
    headers: str = "headers",
) -> Rule:
    """A rule for a tool that makes web requests.

    Runs without asking only when all of this is true:
    the address is plain https to a site on your list, by its whole name; the
    request only reads (GET or HEAD, with no body and no headers) and the site is
    in `read` or `send`, or it sends (POST, PUT, PATCH, or anything with a body or
    headers) and the site is in `send`; the address does not carry a long string
    of data or end like a program; and nothing in the address or in what is sent
    looks like private data or holds text that cannot be seen.

    Never: an address on this machine or your own network, in any way of writing
    it the rule knows (localhost, 127.0.0.1, 127.1, 0x7f.0.0.1, [::1],
    192.168.1.1, 169.254.169.254 where cloud machines keep their keys, a name with
    no dot in it, a name ending .local or .internal), and a file: address.
    Everything else asks: a site not on a list, http, an unusual port, DELETE, a
    numbered address, and any address not written the one plain way
    (https://site/path), such as one with an @ before the path.

    Sites are whole names. "example.com" does not cover "www.example.com". List
    each name. `max_data` is the longest piece of a path, and the longest query,
    that a read may have before it asks; four times that for the whole of what
    follows the site.

    What it cannot do. It reads the name and not where the name points: your
    fetch tool should refuse private addresses after it looks a name up, and
    should not follow a redirect to another site without asking the checkpoint
    again. It cannot tell a short secret in an address from a search word, and it
    does not add up what many small reads carry out. So list for reading only
    sites where it does not matter who sees the addresses asked for: a site where
    anyone can host a page can be used to carry data out.
    """
    read, send = _site_list("read", read), _site_list("send", send)
    if type(max_data) is not int or not 8 <= max_data <= 2000:
        raise RulesError("max_data must be a whole number from 8 to 2000")
    fields = _fields(url=url, method=method, body=body, headers=headers)
    return _Web(read, send, max_data, fields)


# ---- shell commands ------------------------------------------------------------------
#
# The line is read once, the strict way: quotes are followed, and anything the shell
# would work out for itself (a variable, a command inside the command, a file written
# with >) is a reason to ask. The reading carries on past such a thing, so that a wipe
# written behind it is still seen and refused.

_UNSEEN = "the command holds a line break or a character that cannot be seen"
_WORKED_OUT = "the command holds a variable, or a command inside the command"
_BRACKETS = "the command uses brackets or braces, which the shell reads in its own way"
_BACKSLASH = "the command uses a backslash"
_TO_FILE = "the command sends its output to a file, or takes its input from one"
_NO_WAIT = "the command starts something and does not wait for it"
_COMMENT = "the command holds a comment"
_OPEN_QUOTE = "a quote in the command is never closed"
_EMPTY_PART = "the command has a part with nothing in it"
_NO_COMMAND = "the command cannot be read"
_WIPE = "it would delete a top folder of this machine, or your whole home folder"
_LOCK = "it would change who can use every file in a top folder of this machine, or in your whole home folder"
_DISK = "it would wipe a disk, or write straight onto one"
_BOMB = "it would start copies of itself without end"
_SECRET_PLACE = "it reads from what looks like a place where keys or passwords are kept"
_HIDDEN_FILES = "it uses a pattern that reaches hidden files"
_WIDE_SEARCH = "it searches through everything in a top folder of this machine, or in your whole home folder"
_PATTERN_OPTION = "a pattern in the command could turn into an option once the shell fills it in"

_BLANK = " \t\r\n"
_JOINS = ("&&", "||", "|", ";")
_QUIET = re.compile(r"(?:&[12]| */dev/null)(?=[ ;|&]|$)")
_TARGET = re.compile(r"[>&|]? *([^ ;|&<>()]*)")  # after a < or a >: the file it names
_QUIET_DEVICES = frozenset(("/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"))
_HOME_WORD = re.compile(r"\$HOME(?![A-Za-z0-9_])|\$\{HOME\}")
_BRACED = re.compile(r"\$\{[A-Za-z0-9_]*\}")
_FORK_BOMB = re.compile(r"(:|\b\w{1,40})\(\)\{\1\|\1&\};?\1")

_PLAIN_READS = frozenset(
    "basename cat cd cksum cmp column comm cut df diff dirname du echo egrep false fgrep fold grep head id ls md5 md5sum nl "
    "paste printf pwd realpath rev seq sha1sum sha256sum shasum stat tac tail tr true type uname wc which whoami".split()
)
_VERSIONS = frozenset("cargo clang docker gcc git go java make node npm pip pip3 pnpm python python3 ruby rustc uv yarn".split())
_GIT_READS = frozenset("blame cat-file describe diff log ls-files ls-tree merge-base name-rev rev-list rev-parse shortlog show status".split())
_BRANCH_LOOKS = frozenset("-a -r -v -vv --all --remotes --verbose --list --show-current".split())
_FIND_LOOKS = frozenset(
    "-a -and -atime -cmin -cnewer -ctime -d -depth -empty -E -false -follow -group -H -iname -ipath -iregex -L -links -maxdepth "
    "-mindepth -mmin -mtime -name -newer -nogroup -not -nouser -o -or -P -path -perm -print -print0 -prune -readable -regex -s "
    "-size -true -type -user -x -xdev".split()
)
_FIND_ACTS = frozenset("-delete -exec -execdir -ok -okdir -fprint -fprint0 -fprintf -fls".split())
_FIND_COUNT = re.compile(r"-[0-9]+[A-Za-z]?")
_TREE_LOOKS = frozenset("--charset --device --dirsfirst --du --filelimit --gitignore --inodes --noreport --prune".split())
_FILE_LOOKS = frozenset("-b -h -i -I -k -L --brief --mime --mime-encoding --mime-type".split())
_SED_PRINT = re.compile(r"[0-9]{1,9}(?:,[0-9]{1,9})?p")
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\+?=")
_PLAIN_COMMAND = re.compile(r"[A-Za-z0-9._+-]{1,24}")

_DELETES = frozenset("rm rmdir shred srm trash unlink".split())
_ADMIN = frozenset("doas su sudo".split())
_SHELLS = frozenset("bash csh dash fish ksh sh tcsh zsh".split())
_INTERPRETERS = frozenset("awk bun deno lua node osascript perl php python python3 ruby".split())
_WRAPPERS = frozenset(". builtin command env eval exec nice nohup source time timeout watch xargs".split())
_LAUNCHERS = _ADMIN | _SHELLS | _INTERPRETERS | _WRAPPERS
_CARRIERS = _ADMIN | _WRAPPERS | {"ssh"}  # what follows one of these may be the command that really runs
_JOINED = frozenset(("eval", "ssh", "su", "watch"))  # these join their words into one line and hand it to a shell
_INSIDE = _SHELLS | _JOINED  # these may be handed a command as one piece of text
_FETCHERS = frozenset(("curl", "wget"))
_NETWORK = _FETCHERS | frozenset("ftp nc ncat netcat rsync scp sftp ssh telnet".split())
_RUNNERS = frozenset("bunx npx pipx uvx".split())
_INSTALLERS = frozenset("apt apt-get brew bun cargo conda dnf gem go npm pacman pip pip3 pnpm port uv yarn yum".split())
_INSTALL_WORDS = frozenset("add ci get i install update upgrade".split())
_ERASES = re.compile(r"(?:erase|secureerase|zerodisk|randomdisk|reformat|partitiondisk|delete|resetfusion)")

_TOP_FOLDERS = frozenset(
    "applications bin boot dev etc home lib lib32 lib64 library media mnt opt private proc root run sbin srv sys system users usr var volumes".split()
)
_HOME_PARENTS = ("users", "home")
_SECRET_NAMES = (
    ".ssh", ".aws", ".gnupg", ".netrc", ".npmrc", ".pypirc", ".kube", ".docker/config",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "/etc/shadow", "/etc/sudoers", "keychain",
    "_history", ".config/gh/hosts", ".config/gcloud",
)  # fmt: skip
_SECRET_ENDINGS = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".kdbx", ".ppk")
_SECRET_WORDS = ("secret", "password", "passwd", "credential")


@dataclass(frozen=True)
class _Word:
    text: str
    pattern: bool = False  # holds * ? or [ outside quotes: the shell swaps the word for the file names that fit
    inner: bool = False  # holds a command inside double quotes


def _read_line(line: str) -> tuple:
    """A command line as its parts, each the join before it and its words, and what was found on the way."""
    parts: list = [["", []]]
    found: list = []
    word: Optional[list] = None  # the word being read: its pieces, then the two marks a _Word carries

    def grow(text: str = "", pattern: bool = False, inner: bool = False) -> None:
        nonlocal word
        if word is None:
            word = [[], False, False]
        word[0].append(text)
        word[1], word[2] = word[1] or pattern, word[2] or inner

    def close() -> None:
        nonlocal word
        if word is not None:
            parts[-1][1].append(_Word("".join(word[0]), word[1], word[2]))
            word = None

    def part(join: str) -> None:
        close()
        if join in _JOINS and not parts[-1][1]:
            found.append((NEEDS_YES, _EMPTY_PART))
        parts.append([join, []])

    def worked_out(at: int, quoted: bool) -> int:
        """A $ or a backtick at `at`. Gives back where the reading goes on."""
        found.append((NEEDS_YES, _WORKED_OUT))
        home = _HOME_WORD.match(line, at)
        if home:
            grow("~" if word is None or not any(word[0]) else home.group())
            return home.end()
        braced = _BRACED.match(line, at)
        if braced:
            grow(braced.group())
            return braced.end()
        if quoted:
            grow(line[at], inner=line[at] == "`" or line[at + 1 : at + 2] == "(")
        elif line[at] == "`":
            part("(")
        else:
            grow("$")
        return at + 1

    def redirect(at: int) -> int:
        """A < or a > at `at`. Gives back where the reading goes on."""
        nonlocal word
        if word is not None and "".join(word[0]) in ("1", "2"):
            word = None  # the number says which output or input is meant: it is not a word of the command
        close()
        quiet = _QUIET.match(line, at + 1) if line[at] == ">" else None
        if quiet:
            return quiet.end()
        found.append((NEEDS_YES, _TO_FILE))
        target = _TARGET.match(line, at + 1)
        name = target.group(1).replace("'", "").replace('"', "").lower()
        if line[at] == ">" and name.startswith("/dev/") and name not in _QUIET_DEVICES:
            found.append((NEVER, _DISK))
        return target.start(1) if "'" in target.group(1) or '"' in target.group(1) else target.end()

    at, end = 0, len(line)
    while at < end:
        character = line[at]
        at += 1
        if character in " \t":
            close()
        elif character in "\r\n":
            part("\n")
        elif character == "'":
            stop = line.find("'", at)
            if stop < 0:
                found.append((NEEDS_YES, _OPEN_QUOTE))
                stop = end
            grow(line[at:stop])
            at = stop + 1
        elif character == '"':
            grow()
            while at < end and line[at] != '"':
                character = line[at]
                at += 1
                if character == "\\" and at < end:
                    grow(line[at] if line[at] in '$`"\\' else "\\" + line[at])  # every shell reads this the same way
                    at += 1
                elif character in "$`":
                    at = worked_out(at - 1, quoted=True)
                else:
                    grow(character)
            if at >= end:
                found.append((NEEDS_YES, _OPEN_QUOTE))
            at += 1
        elif character == "\\":
            found.append((NEEDS_YES, _BACKSLASH))
            if at < end:
                grow(line[at])
                at += 1
        elif character in "$`":
            at = worked_out(at - 1, quoted=False)
        elif character in "(){}":
            found.append((NEEDS_YES, _BRACKETS))
            part("(")
        elif character in "<>":
            at = redirect(at - 1)
        elif character == "|":
            two = line[at : at + 1] == "|"
            at += two
            part("||" if two else "|")
        elif character == "&":
            two = line[at : at + 1] == "&"
            at += two
            if not two:
                found.append((NEEDS_YES, _NO_WAIT))
            part("&&" if two else "&")
        elif character == ";":
            part(";")
        elif character == "#" and word is None:
            found.append((NEEDS_YES, _COMMENT))
            grow(character)
        else:
            grow(character, pattern=character in "*?[")
    close()
    if parts[-1][0] in ("&&", "||", "|") and not parts[-1][1]:
        found.append((NEEDS_YES, _EMPTY_PART))
    return [(join, words) for join, words in parts if words], found


def _steps(parts: list) -> Iterable[tuple]:
    """Each part with the folder it runs in, where a cd earlier in the line says which that is."""
    where = None
    for join, words in parts:
        yield join, words, where
        if words[0].text == "cd":
            if len(words) == 1:
                where = (True, ())
            elif len(words) == 2 and not words[1].pattern and words[1].text != "-":
                where = _resolve(words[1].text, where)
            else:
                where = None


def _resolve(text: str, where: Optional[tuple]) -> Optional[tuple]:
    """Where a path points: (is it in the home folder, the folders below). None when that hangs on where the command is run."""
    text = _HOME_WORD.sub("~", text, count=1) if text.startswith("$") else text
    if text.startswith("~"):
        home, pieces, text = True, [], text.partition("/")[2]
    elif text.startswith("/"):
        home, pieces = False, []
    elif where is None:
        return None
    else:
        home, pieces = where[0], list(where[1])
    for piece in text.split("/"):
        if piece == "..":
            pieces[-1:] = []
        elif piece not in ("", "."):
            pieces.append(piece.lower())  # a Mac reads /users and /Users as one folder
    return home, tuple(pieces)


def _is_home(place: tuple) -> bool:
    home, pieces = place
    return not pieces if home else len(pieces) == 2 and pieces[0] in _HOME_PARENTS


def _is_top(place: tuple) -> bool:
    home, pieces = place
    if home or not pieces:
        return not pieces
    if len(pieces) == 1:
        return pieces[0] in _TOP_FOLDERS
    return len(pieces) == 2 and (pieces[0] in _HOME_PARENTS + ("usr",) or pieces in (("private", "etc"), ("private", "var")))


def _top(word: _Word, where: Optional[tuple]) -> bool:
    """True when a word names a top folder of the machine or the home folder, or everything in one."""
    text = word.text
    if text.startswith("-"):
        return False
    everything = None
    if word.pattern:
        pieces = text.split("/")
        first = next((at for at, piece in enumerate(pieces) if any(mark in piece for mark in "*?[")), len(pieces) - 1)
        everything = not pieces[first].strip("*?.")
        text = "/".join(pieces[:first]) or ("/" if text.startswith("/") else ".")
    place = _resolve(text, where)
    if place is None or not _is_top(place):
        return False
    # In a home folder a pattern is a wipe only when it fits everything: rm -rf ~/old-* is an ordinary thing to ask for.
    return everything is None or everything or not _is_home(place)


def _wipes(words: list, where: Optional[tuple], depth: int = 0) -> list:
    """The reasons to refuse one part of a command outright."""
    found = []
    names = [word.text.rsplit("/", 1)[-1].lower() for word in words]  # a Mac runs RM as rm
    for at in range(len(words) if names[0] in _CARRIERS else 1):
        name, rest = names[at], words[at + 1 :]
        texts = [word.text for word in rest]
        if name in ("rm", "chmod", "chown", "chgrp"):
            deep = any(
                text == "--recursive" or (name == "rm" and text.startswith("--r")) or (text[:1] == "-" and text[:2] != "--" and ("R" in text or (name == "rm" and "r" in text)))
                for text in texts
            )
            if (name == "rm" and any(text.startswith("--no-p") for text in texts)) or (deep and any(_top(word, where) for word in rest)):
                found.append((NEVER, _WIPE if name == "rm" else _LOCK))
        elif name == "find":
            if ("-delete" in texts or "rm" in names[at:]) and any(_top(word, where) for word in rest):
                found.append((NEVER, _WIPE))
        elif name.startswith(("mkfs", "newfs")) or name in ("mke2fs", "wipefs"):
            found.append((NEVER, _DISK))
        elif name == "diskutil":
            if any(_ERASES.match(text.lower()) for text in texts):
                found.append((NEVER, _DISK))
        elif name == "dd":
            if any(text.lower().startswith("of=/dev/") and text.lower()[3:] not in _QUIET_DEVICES for text in texts):
                found.append((NEVER, _DISK))
        elif name in _INSIDE and depth < 3:
            for text in texts:
                found += _wipes_inside(text, depth + 1)
    for word in words:
        if word.inner and depth < 3:
            found += _wipes_inside(word.text, depth + 1)
    return found


def _wipes_inside(text: str, depth: int) -> list:
    """The reasons to refuse a command that is handed to a shell as one piece of text."""
    parts, read = _read_line(text.strip(_BLANK))
    found = [(level, reason) for level, reason in read if level == NEVER]
    for _, words, where in _steps(parts):
        found += _wipes(words, where, depth)
    return found


def _cluster(text: str, letters: str) -> bool:
    """True for a word of one-letter options, such as -rn, that holds one of `letters`."""
    return text[:1] == "-" and text[:2] != "--" and any(letter in text for letter in letters)


def _sort(texts: list) -> str:
    told = any(text.startswith(("--o", "--c")) or _cluster(text, "o") for text in texts)
    return "sort is told to write a file, or to run another program" if told else ""


def _uniq(texts: list) -> str:
    files = [text for at, text in enumerate(texts) if text[:1] != "-" and (at == 0 or texts[at - 1] not in ("-f", "-s", "-w"))]
    return "" if len(files) <= 1 and "--" not in texts else "uniq is given a second file, which it would write to"


def _find(texts: list) -> str:
    for text in texts:
        if text[:1] == "-" and text not in _FIND_LOOKS and not _FIND_COUNT.fullmatch(text):
            return "find is told to delete what it finds, or to run or write something" if text in _FIND_ACTS else "find is given an option this rule does not know"
    return ""


def _rg(texts: list) -> str:
    return "rg is told to run another program" if any(text.startswith(("--pre", "--hostname-bin")) for text in texts) else ""


def _tree(texts: list) -> str:
    told = any((text[:2] == "--" and text.partition("=")[0] not in _TREE_LOOKS) or _cluster(text, "oR") for text in texts)
    return "tree is told to write a file, or is given an option this rule does not know" if told else ""


def _file(texts: list) -> str:
    return "file is given an option this rule does not know" if any(text[:1] == "-" and text not in _FILE_LOOKS for text in texts) else ""


def _date(texts: list) -> str:
    return "" if all(text == "-u" or text.startswith("+") for text in texts) else "date is told to do more than show the time"


def _hostname(texts: list) -> str:
    return "" if texts in ([], ["-s"], ["-f"]) else "hostname is told to do more than show the name of this machine"


def _sed(texts: list) -> str:
    prints = len(texts) >= 2 and texts[0] == "-n" and _SED_PRINT.fullmatch(texts[1]) and not any(text.startswith("-") for text in texts[2:])
    return "" if prints else "sed is used for more than printing chosen lines"


def _git(texts: list) -> str:
    while texts[:1] == ["--no-pager"] or (texts[:1] == ["-C"] and len(texts) > 1):
        texts = texts[1 if texts[0] == "--no-pager" else 2 :]
    command, rest = (texts[0], texts[1:]) if texts else ("", [])
    if command in _GIT_READS:
        return "git is told to write a file, or to run another program" if any(text.startswith(("--ou", "--ext")) for text in rest) else ""
    if (
        (command == "branch" and all(text in _BRANCH_LOOKS for text in rest))
        or (command == "tag" and all(text in ("-l", "--list") for text in rest))
        or (command == "remote" and all(text in ("-v", "--verbose") for text in rest))
        or (command == "stash" and rest == ["list"])
    ):
        return ""
    if command == "push":
        forced = any(text.startswith(("--force", "+")) or _cluster(text, "f") for text in rest)
        return "a forced git push can throw away work on the other side" if forced else "git push sends your work out"
    if command == "reset" and "--hard" in rest:
        return "git reset --hard throws away changes"
    if command == "clean":
        return "git clean deletes files"
    return "it is a git command that does more than read"


_CAREFUL_READS = {"sort": _sort, "uniq": _uniq, "find": _find, "rg": _rg, "tree": _tree, "file": _file, "date": _date, "hostname": _hostname, "sed": _sed, "git": _git}


def _reader(name: str, texts: list) -> Optional[str]:
    """For a command this rule knows as a reader: "" when this use of it only reads, or why it does not. None for any other command."""
    if name in _PLAIN_READS or (name in _VERSIONS and texts == ["--version"]):
        return ""
    check = _CAREFUL_READS.get(name)
    return None if check is None else check(texts)


def _other_command(name: str, texts: list, piped: bool) -> str:
    """Why a command that is not a known reader asks."""
    base = name.rsplit("/", 1)[-1]
    if _ASSIGNMENT.match(name):
        return "it sets a variable before the command"
    if piped and (base in _SHELLS | _INTERPRETERS or (base in _ADMIN and any(text in _SHELLS for text in texts))):
        return "a download is piped straight into a shell"
    if base in _DELETES:
        return "it deletes files"
    if base in _ADMIN:
        return "it runs as the administrator"
    if base in _INSTALLERS and any(text in _INSTALL_WORDS for text in texts):
        return "it installs software"
    if base in _SHELLS | _INTERPRETERS:
        return "it runs a script, or program text this rule does not read"
    if base in _RUNNERS:
        return "it downloads a program and runs it"
    if base in _NETWORK:
        return "it reaches out over the network"
    if "/" in name:
        return "it runs a program by its path, which may be a script"
    shown = name if _PLAIN_COMMAND.fullmatch(name) else "the command"
    return f"{shown} is not a command this rule knows to only read, and it is not on your list"


def _secret_place(word: _Word) -> bool:
    text = word.text.lower()
    on_the_way = [piece for piece in text.split("/") if piece]
    if "proc" in on_the_way and on_the_way[-1] in _PROC_SECRETS:
        return True
    pieces = re.split(r"[/=:,]", text)
    if any(piece == ".env" or piece == ".envrc" or piece.startswith(".env.") for piece in pieces):
        return True
    if any(name in text for name in _SECRET_NAMES) or text.endswith(_SECRET_ENDINGS):
        return True
    return ("/" in text or "." in text) and any(name in text for name in _SECRET_WORDS)


def _hidden_pattern(word: _Word) -> bool:
    return word.pattern and any(piece.startswith(".") and any(mark in piece for mark in "*?[") for piece in word.text.split("/"))


class _Shell(Rule):
    kind = "shell"
    _fine = "every part of the command only reads, or is a command you allow"

    def __init__(self, allowed, ignored, fields) -> None:
        object.__setattr__(self, "_allowed", allowed)
        object.__setattr__(self, "_ignored", ignored)
        object.__setattr__(self, "_fields", fields)
        super().__init__({"allow": sorted(list(entry) for entry in allowed), "ignore": sorted(ignored), "fields": fields})

    def _look(self, inputs: dict) -> list:
        found = []
        untold = len(set(inputs) - set(self._fields.values()) - self._ignored)
        if untold:
            found.append((NEEDS_YES, f"the rule was not told about {untold} of the inputs"))
        command = inputs.get(self._fields["command"])
        if type(command) is str and command.strip(_BLANK):
            texts = [command.strip(_BLANK)]
            parts, read = _read_line(texts[0])
            found += read
        elif type(command) is list and command and command[0] and all(type(text) is str for text in command):
            texts = command  # a list of words is a program started with no shell: nothing in it is worked out
            parts = [("", [_Word(text) for text in command])]
        else:
            return found + [(NEEDS_YES, _NO_COMMAND)]
        for text in texts:
            if any(ord(character) < 0x20 for character in text) or hidden(text):
                found.append((NEEDS_YES, _UNSEEN))
            found += [(NEEDS_YES, f"the command holds what looks like {kind}") for kind in sensitive(text)]
        if _FORK_BOMB.search(re.sub(r"\s", "", " ".join(texts))):
            found.append((NEVER, _BOMB))
        before = ""
        for join, words, where in _steps(parts):
            found += _wipes(words, where)
            # A part cut off by a bracket or a backtick is read for wipes alone: what it is cannot be told, and the line asks as it is.
            if join != "(" and not self._listed(words):
                found += [(NEEDS_YES, reason) for reason in _part_asks(words, where, piped=join == "|" and before in _FETCHERS)]
            before = words[0].text.rsplit("/", 1)[-1]
        return found

    def _listed(self, words: list) -> bool:
        return any(len(entry) <= len(words) and all(not word.pattern and word.text == told for word, told in zip(words, entry)) for entry in self._allowed)


def _part_asks(words: list, where: Optional[tuple], piped: bool) -> list:
    """The reasons one part of a command asks. None when the part only reads."""
    name, rest = words[0].text, words[1:]
    texts = [word.text for word in rest]
    use = _reader(name, texts)
    if use is None:
        return [_other_command(name, texts, piped)]
    reasons = [use] if use else []
    if name not in _PLAIN_READS and any(word.pattern for word in rest):
        reasons.append(_PATTERN_OPTION)
    if any(_secret_place(word) for word in rest):
        reasons.append(_SECRET_PLACE)
    if any(_hidden_pattern(word) for word in rest):
        reasons.append(_HIDDEN_FILES)
    deep = name == "rg" or (name in ("grep", "egrep", "fgrep") and any(_cluster(text, "rR") or text in ("--recursive", "--dereference-recursive") for text in texts))
    if deep and any(_top(word, where) for word in rest):
        reasons.append(_WIDE_SEARCH)
    return reasons


def _command_list(values: Any) -> frozenset:
    """The owner's own commands given at setup, checked and copied."""
    if values is None:
        return frozenset()
    if type(values) not in (list, tuple, set, frozenset):
        raise RulesError("allow must be a list of commands, given as the list itself")
    kept = set()
    for value in values:
        parts, found = _read_line(value) if type(value) is str else ([], [])
        if found or len(parts) != 1 or any(word.pattern for word in parts[0][1]) or any(_is_control(ord(character)) or ord(character) in (9, 10, 13) for character in value):
            raise RulesError(f"allow: {value!r} is not one plain command, such as 'pytest' or 'git add'")
        entry = tuple(word.text for word in parts[0][1])
        bases = [text.rsplit("/", 1)[-1] for text in entry]
        # What a launcher is told to run: a plain word that is not the value of the option before it.
        said = [
            text
            for before, text in zip(entry, entry[1:])
            if text[:1] != "-" and "=" not in text and not text.isdigit() and (before[:1] != "-" or (before == "-m" and bases[0] in _INTERPRETERS))
        ]
        # These hand their words to a shell as one line, so a ; inside a later word would start a second command.
        joined = any(base in _JOINED for base in (bases if bases[0] in _CARRIERS else bases[:1]))
        if joined or (bases[0] in _LAUNCHERS and not said):
            raise RulesError(f"allow: {value!r} would let anything at all run. Say what it runs, such as 'python -m pytest'")
        kept.add(entry)
    return frozenset(kept)


def shell(allow: Any = None, *, ignore: Any = (), command: str = "command") -> Rule:
    """A rule for a tool that runs a shell command.

    Runs without asking only when every part of the line (the parts are what
    |, &&, || and ; join) is one of these:

    - a command that only reads: ls, cat, head, tail, wc, grep, diff, pwd, echo
      and others like them; find, sort, uniq, rg, tree, file, date and
      sed -n '10,20p' when they are not told to write, delete or run anything;
      git status, log, diff, show, blame and other git commands that only read;
      and python --version, node --version and the like;
    - a command of your own in `allow`. "git add" allows `git add` followed by
      anything; "pytest" allows pytest with any options.

    Never: deleting a top folder of the machine or the whole home folder
    (rm -rf /, rm -rf ~, rm -rf /usr/*, the same after sudo, inside sh -c '...',
    or after cd /), the same done with find -delete or chmod -R, wiping or
    formatting a disk (mkfs, diskutil eraseDisk, dd of=/dev/..., > /dev/disk0),
    and a command that starts copies of itself without end.

    Everything else asks, and says why: deleting, installing, sudo, git push,
    running a script, the network, a download piped into a shell. So does
    anything the shell would work out for itself, because this rule does not
    work it out: a variable ($HOME), a command inside the command ($(...) or
    backticks), brackets and braces, a backslash, a file written with >, a
    command left running with &. A read of what looks like a place where keys
    are kept (.env, .ssh, a .pem file) asks too. Quiet endings are fine:
    2>/dev/null, >/dev/null and 2>&1.

    The command may be one line of text, or a list of words if your tool starts
    the program itself with no shell. `ignore` names inputs that do not change
    what runs, such as a time limit; any other input the rule was not told about
    asks.

    What it cannot do. Reading a shell line is not a wall: it is a way to be
    asked less about ordinary work. A command that only reads can still read
    something private that has an ordinary name. Programs can be set up to run
    other programs (a git folder's own settings, your shell's aliases, PATH): do
    not point the agent at a folder you do not trust. A command in `allow` runs
    with any arguments, so list "npm test", not "npm". For a real wall, run the
    tool where a wipe cannot hurt: a container, or a user with few rights.
    """
    allowed = _command_list(allow)
    fields = _fields(command=command)
    if type(ignore) not in (list, tuple, set, frozenset) or any(type(name) is not str or not name for name in ignore):
        raise RulesError("ignore must be a list of the names of inputs")
    if command in ignore:
        raise RulesError("the input that holds the command cannot be ignored")
    return _Shell(allowed, frozenset(ignore), fields)


# ---- files ---------------------------------------------------------------------------
#
# One rule for each file tool: reading, writing or deleting. The rule works out where a
# path really leads (.. and links followed) and judges that place.

_F_FINE = "the path is inside the folders you allow"
_F_UNREAD = "the path cannot be read"
_F_UNSEEN = "the path holds a line break or a character that cannot be seen"
_F_NOT_PLAIN = "the path is not written plainly, so a tool might take it for another place"
_F_PATTERN = "the path holds a pattern, and this rule does not work out which files it stands for"
_F_RELATIVE = "the path does not start from / or ~, and the rule was not told which folder the tool starts in"
_F_OUTSIDE = "the path is outside the folders you allow"
_F_LINK = "a link on the way leads outside the folders you allow"
_F_LEADS = "it really leads to {}"
MAX_PLACE = 120  # the longest place a reason writes out
_F_READ_ONLY = "you allow reading there, not changing it"
_F_KEYS = "it is a place where keys and passwords are kept"
_F_PROTECTED = "it is one of the paths you protect"
_F_SYSTEM = "it changes a system folder"
_F_WHOLE = "it deletes the home folder or a top folder of the machine"
_F_RUNS_ITSELF = "it changes a file that other tools run or obey"
_F_FOLDER = "it deletes a whole folder"
_F_MANY = "it deletes more than {} paths at once"

_DOES = ("read", "write", "delete")
_SYSTEM_FOLDERS = frozenset("bin boot dev etc lib lib32 lib64 library proc root sbin sys system usr".split())
_KEY_PIECES = frozenset(
    ".ssh .aws .gnupg .kube .netrc .npmrc .pypirc .git-credentials .htpasswd .env .envrc id_rsa id_dsa id_ecdsa id_ed25519 keychains".split()
)
_KEY_PAIRS = ((".docker", "config.json"), (".config", "gh"), (".config", "gcloud"), ("etc", "shadow"), ("etc", "sudoers"), ("etc", "master.passwd"))
_KEY_STEMS = frozenset("credentials password passwords secret secrets".split())
_EXAMPLE_ENDINGS = (".example", ".sample", ".template", ".dist")
_OBEYED_FOLDERS = frozenset(
    ".git .github .husky .vscode .claude .cursor .devcontainer launchagents launchdaemons"
    # what coding agents load from a project: their settings, the tool servers they start, the rules they follow
    " .gemini .codex .windsurf .amazonq .continue .clinerules".split()
)
_OBEYED_FILES = frozenset(
    ".zshrc .zshenv .zprofile .zlogin .bashrc .bash_profile .bash_login .profile .gitconfig"
    " .mcp.json agents.md claude.md claude.local.md gemini.md .cursorrules .windsurfrules".split()  # .clinerules is a folder above, or a file of that name
)
# Another program's settings and the words it was started with, which is where secrets passed to it are found.
_PROC_SECRETS = ("environ", "cmdline")
# ..namedfork is how macOS reaches a file's contents through a path that goes on past the file's name.
_NOT_PLAIN = re.compile(r"[$\\`]|^~[^/]|^[A-Za-z]:|^\s|\s$|(?i:\.\.namedfork)")


def _same(path: str) -> str:
    """A path as a disk that ignores capitals and accents would see it."""
    return unicodedata.normalize("NFC", path).casefold()


def _under(path: str, roots: Iterable[str], exact: bool = False) -> bool:
    """True if `path` is one of `roots` or inside one.

    When the answer makes the rule stricter, capitals and accents are passed over, because
    many disks pass over them. When the answer lets an action run, `exact` is asked for:
    on a disk that tells capitals apart, a name in other capitals is another place.
    """
    if not exact:
        path, roots = _same(path), map(_same, roots)
    return any(path == root or path.startswith(root.rstrip("/") + "/") for root in roots)


def _pieces(path: str) -> list:
    return [piece for piece in path.lower().split("/") if piece]


def _system_place(path: str) -> bool:
    pieces = _pieces(path)
    return bool(pieces) and (pieces[0] in _SYSTEM_FOLDERS or pieces[:2] == ["private", "etc"])


def _whole_place(path: str, home: str) -> bool:
    """True for /, a top folder of the machine, the home folder, or a folder the home folder is in."""
    pieces = _pieces(path)
    return len(pieces) < 2 or (pieces[0] == "private" and len(pieces) == 2) or _under(home, [path])


def _key_name(name: str) -> bool:
    if name in _KEY_PIECES:
        return True
    if name.endswith(_EXAMPLE_ENDINGS):
        return False
    if name.startswith(".env.") or name.endswith(_SECRET_ENDINGS):
        return True
    return (name.startswith(".") and name.endswith("_history")) or name.split(".")[0] in _KEY_STEMS


def _key_place(path: str) -> bool:
    """True if any name on the way is one that keys are kept under: a folder called secrets counts, and so does what is in it."""
    pieces = _pieces(path)
    if pieces[:1] == ["proc"] and pieces[-1] in _PROC_SECRETS:
        return True
    return any(_key_name(piece) for piece in pieces) or any(pair in _KEY_PAIRS for pair in zip(pieces, pieces[1:]))


def _obeyed_place(path: str) -> bool:
    pieces = _pieces(path)
    return any(piece in _OBEYED_FOLDERS for piece in pieces) or (bool(pieces) and pieces[-1] in _OBEYED_FILES)


# Top folders that the system itself makes as links: on macOS /tmp, /var and /etc lead into /private.
_SYSTEM_ALIASES = ("/tmp", "/var", "/etc")


def _system_alias(real: str, tidy: str) -> bool:
    """True when the only link on the way is one of the system's own top folders, which is no news to the owner."""
    top = next((alias for alias in _SYSTEM_ALIASES if _same(tidy) == alias or _same(tidy).startswith(alias + "/")), None)
    return top is not None and real == _real(top) + tidy[len(top):]


def _shown_place(path: str, home: str) -> str:
    """A place for a reason: ~ for the home folder, a letter that cannot be shown as ?, cut at MAX_PLACE with a mark of what was cut."""
    shown = "~" + path[len(home):] if _under(path, [home], exact=True) else path
    shown = "".join(letter if letter.isprintable() else "?" for letter in shown)
    if len(shown) <= MAX_PLACE:
        return shown
    mark = "... #" + hashlib.sha256(path.encode("utf-8", "surrogatepass")).hexdigest()[:8]
    return shown[: MAX_PLACE - len(mark)] + mark


def _whole_path(text: str, home: str) -> Optional[str]:
    """`text` with ~ put in, or None if it does not start from / or ~."""
    if text == "~" or text.startswith("~/"):
        return home + text[1:]
    return text if text.startswith("/") else None


def _tidy(path: str) -> str:
    return re.sub(r"^/+", "/", os.path.normpath(path))


def _real(path: str) -> str:
    return re.sub(r"^/+", "/", os.path.realpath(path))


class _Files(Rule):
    kind = "files"
    _fine = _F_FINE

    def __init__(self, does, folders, read_only, protect, base, home, many, ignored, fields) -> None:
        for name, value in (("_does", does), ("_folders", folders), ("_read_only", read_only), ("_protect", protect), ("_base", base)):
            object.__setattr__(self, name, value)
        for name, value in (("_home", home), ("_many", many), ("_ignored", ignored), ("_fields", fields)):
            object.__setattr__(self, name, value)
        super().__init__(
            {
                "does": does, "folders": list(folders), "read_only": list(read_only), "protect": list(protect), "base": base,
                "home": home, "many": many, "ignore": sorted(ignored), "fields": fields,
            }
        )

    def _look(self, inputs: dict) -> list:
        found = []
        known = {self._fields["path"]} | ({self._fields["content"]} if self._does == "write" else set()) | self._ignored
        untold = len(set(inputs) - known)
        if untold:
            found.append((NEEDS_YES, f"the rule was not told about {untold} of the inputs"))
        value = inputs.get(self._fields["path"])
        paths = [value] if type(value) is str else value
        if type(paths) is not list or not paths or any(type(path) is not str or not path for path in paths):
            return found + [(NEEDS_YES, _F_UNREAD)]
        if self._does == "delete" and len(paths) > self._many:
            found.append((NEEDS_YES, _F_MANY.format(self._many)))
        for path in paths:
            found += self._judge(path)
        return found

    def _judge(self, text: str) -> list:
        found = []
        if any(ord(character) < 0x20 for character in text) or hidden(text):
            found.append((NEEDS_YES, _F_UNSEEN))
        if _NOT_PLAIN.search(text):
            found.append((NEEDS_YES, _F_NOT_PLAIN))
        if any(mark in text for mark in "*?["):
            found.append((NEEDS_YES, _F_PATTERN))
        whole = _whole_path(text, self._home)
        if whole is None and self._base is not None and not text.startswith("~"):
            whole = self._base + "/" + text
        if whole is None:
            return found + [(NEEDS_YES, _F_RELATIVE)]
        try:
            # The real place is worked out from the path as it was given: a/link/.. is not a.
            real, tidy = _real(whole), _tidy(whole)
            folders, read_only, protect = ([_real(place) for place in places] for places in (self._folders, self._read_only, self._protect))
            home = _real(self._home)
        except (OSError, ValueError):
            return found + [(NEEDS_YES, _F_UNREAD)]
        changes = self._does != "read"
        inside = _under(real, folders, exact=True)
        allowed = inside or (not changes and _under(real, read_only, exact=True))
        if _under(real, protect) or _under(tidy, self._protect):
            found.append((NEVER if changes else NEEDS_YES, _F_PROTECTED))
        if self._does == "delete" and (_whole_place(real, home) or _whole_place(tidy, self._home)):
            found.append((NEVER, _F_WHOLE))
        if changes and not inside and _system_place(real):
            found.append((NEVER, _F_SYSTEM))
        if _key_place(real) or _key_place(tidy):
            found.append((NEVER if changes and not inside else NEEDS_YES, _F_KEYS))
        if not allowed:
            if _under(tidy, self._folders if changes else self._folders + self._read_only, exact=True):
                found.append((NEEDS_YES, _F_LINK))
            elif _under(real, read_only, exact=True):
                found.append((NEEDS_YES, _F_READ_ONLY))
            else:
                found.append((NEEDS_YES, _F_OUTSIDE))
        if changes and (_obeyed_place(real) or _obeyed_place(tidy)):
            found.append((NEEDS_YES, _F_RUNS_ITSELF))
        if self._does == "delete" and (text.endswith("/") or os.path.isdir(real)):
            found.append((NEEDS_YES, _F_FOLDER))
        if real != tidy and found and not _system_alias(real, tidy):
            # Said first, so the card shows it: the owner is asked about where the write lands, not the name it was given.
            found.insert(0, (NEEDS_YES, _F_LEADS.format(_shown_place(real, self._home))))
        return found


def _place_list(values: Any, name: str, home: str, whole_allowed: bool = False) -> tuple:
    """The owner's list of folders or paths, checked, with ~ put in and tidied."""
    if values is None:
        return ()
    if type(values) not in (list, tuple):
        raise RulesError(f"{name} must be a list of paths")
    kept = []
    for value in values:
        if type(value) is not str or not value:
            raise RulesError(f"{name} must be a list of paths, each as text")
        if any(ord(character) in (9, 10, 13) for character in value) or hidden(value):
            raise RulesError(f"{name}: a path holds a line break or a character that cannot be seen")
        if _NOT_PLAIN.search(value) or any(mark in value for mark in "*?["):
            raise RulesError(f"{name}: {value!r} must be one plain path, with no pattern and nothing to work out")
        whole = _whole_path(value, home)
        if whole is None:
            raise RulesError(f"{name}: {value!r} must start from / or ~")
        whole = _tidy(whole)
        if not whole_allowed and (_whole_place(whole, home) or (_system_place(whole) and len(_pieces(whole)) < 3)):
            raise RulesError(f"{name}: {value!r} is the home folder or a folder of the system. Name the folders the agent works in")
        if whole not in kept:
            kept.append(whole)
    return tuple(kept)


def files(
    folders: Any = None,
    *,
    does: str,
    read_only: Any = None,
    protect: Any = None,
    base: Optional[str] = None,
    many: int = 10,
    ignore: Any = (),
    path: str = "path",
    content: str = "content",
) -> Rule:
    """A rule for a tool that reads, writes or deletes files. Make one for each tool.

        read = rules.files(["~/Projects/my-app"], does="read", read_only=["~/Documents/specs"])
        write = rules.files(["~/Projects/my-app"], does="write")
        delete = rules.files(["~/Projects/my-app"], does="delete")

    Runs without asking when the place the path really leads to (.. and links
    followed) is inside `folders`. A tool that reads may also read inside
    `read_only`. The path may be text, or a list of paths.

    Never: writing or deleting where keys are kept outside your folders (~/.ssh,
    ~/.aws, a .pem file and so on), in a system folder (/etc, /usr, /System and
    so on), or at a path in `protect`; and deleting the home folder, a folder it
    is in, or a top folder of the machine.

    Asks, and says why: anything outside your folders, a link that leads outside
    them, a place where keys are kept (.env, credentials.json, an id_rsa file)
    even inside your folders, a read of a path you protect, changing a file that
    other tools run or obey (.git, .github, .vscode, .zshrc and the like),
    deleting a whole folder or more than `many` paths at once, a path with a
    pattern (*), a path that is not written plainly ($HOME, a backslash,
    ~someone), a path that does not start from / or ~ when `base` is not given,
    and any input the rule was not told about. `ignore` names inputs that do not
    change what happens. For a tool that writes, the input named by `content`
    is expected and is not read.

    `protect` is for files the agent must not change even inside its folders:
    the checkpoint's own file, your lists, the program that sets the rules.
    `base` is the folder your tool starts in, if it takes paths like "src/app.py".

    What it cannot do. It judges where the path leads at the moment it is asked;
    a link made afterwards is not seen, and neither is a second name for the
    same file (a hard link). It does not read what is written: an agent that
    may write files and run your tests can run what it wrote. It knows the usual
    places for keys, not what is inside a file: a private file with an ordinary
    name inside your folders is read without asking. It reads macOS and Linux
    paths; a Windows path asks.
    """
    if does not in _DOES:
        raise RulesError('does must be "read", "write" or "delete"')
    home = os.path.expanduser("~")
    if type(home) is not str or not home.startswith("/") or _tidy(home) == "/":
        raise RulesError("the home folder of this user cannot be worked out")
    home = _tidy(home)
    kept = _place_list(folders, "folders", home)
    reads = _place_list(read_only, "read_only", home)
    guarded = _place_list(protect, "protect", home, whole_allowed=True)
    start = None
    if base is not None:
        if type(base) is not str:
            raise RulesError("base must be one folder, as text")
        start = _place_list([base], "base", home, whole_allowed=True)[0]
    if type(many) is not int or many < 1:
        raise RulesError("many must be a whole number, 1 or more")
    fields = _fields(path=path, content=content)
    if type(ignore) not in (list, tuple, set, frozenset) or any(type(name) is not str or not name for name in ignore):
        raise RulesError("ignore must be a list of the names of inputs")
    if path in ignore:
        raise RulesError("the input that holds the path cannot be ignored")
    return _Files(does, kept, reads, guarded, start, home, many, frozenset(ignore), fields)


# ---- calendar ------------------------------------------------------------------------
#
# A calendar tool sends too: everyone invited gets the title, the place and the
# description. So the rule for one is the email rule's idea with one thing added.
# An event with no one on it but the owner is sent to nobody, and runs.

_G_FINE = "nobody is invited who is not you or in your contacts, and nothing unusual was found in what a guest would be sent"
_G_UNTOLD = "the rule was not told about {} of the inputs of this event"
_G_BLOCKED = "a guest is on your block list"
_G_UNREAD = "the guests cannot be read for certain as a list of addresses"
_G_MANY = "it invites {} guests, more than {}"
_G_STRANGER = "{} is invited and is not in your contacts"
_G_ALIKE = "{} is invited and is not in your contacts, and it looks like {}, which is"
_G_ALIKE_DOMAIN = "{} is invited and is not in your contacts, and its domain looks like the one in {}, which is"


def _barred(address: str, blocked: frozenset) -> bool:
    """True if the address, or the whole of its domain, is on the block list."""
    domain = address.partition("@")[2]
    return address in blocked or any(entry[:1] == "@" and (domain == entry[1:] or domain.endswith("." + entry[1:])) for entry in blocked)


class _Calendar(Rule):
    kind = "calendar"
    _fine = _G_FINE

    def __init__(self, contacts, me, blocked, max_guests, ignored, fields) -> None:
        object.__setattr__(self, "_contacts", contacts)
        object.__setattr__(self, "_me", me)
        object.__setattr__(self, "_blocked", blocked)
        object.__setattr__(self, "_most", max_guests)
        object.__setattr__(self, "_ignored", ignored)
        object.__setattr__(self, "_fields", fields)
        super().__init__(
            {"contacts": sorted(contacts), "me": sorted(me), "blocked": sorted(blocked), "max_guests": max_guests, "ignore": sorted(ignored), "fields": fields}
        )

    def _look(self, inputs: dict) -> list:
        named = self._fields["attendees"]
        found = []
        unnamed = len(set(inputs) - set(self._fields.values()) - self._ignored)
        if unnamed:
            found.append((NEEDS_YES, _G_UNTOLD.format(unnamed)))

        # The block list is read loosely, so a guest written in an odd way is still caught.
        if any(_barred(address, self._blocked) for address in _loose_addresses(inputs.get(named))):
            found.append((NEVER, _G_BLOCKED))

        everyone = _recipients(inputs.get(named))
        if everyone is None:
            return found + [(NEEDS_YES, _G_UNREAD)] + _content(inputs, skip=(named,))
        guests = [address for address in everyone if address not in self._me]
        if not guests:
            return found  # nobody is sent anything
        if len(guests) > self._most:
            found.append((NEEDS_YES, _G_MANY.format(len(guests), self._most)))
        for address in guests:
            if address in self._contacts:
                continue
            alike = _looks_like_address(address, self._contacts | self._me)
            if alike is None:
                found.append((NEEDS_YES, _G_STRANGER.format(_shown_address(address))))
            else:
                found.append((NEEDS_YES, (_G_ALIKE_DOMAIN if alike[1] else _G_ALIKE).format(_shown_address(address), alike[0])))
        return found + _content(inputs, skip=(named,))


def calendar(
    contacts: Any = None,
    *,
    me: Any = (),
    blocked: Any = (),
    max_guests: int = 10,
    ignore: Any = (),
    attendees: str = "attendees",
    title: str = "title",
    description: str = "description",
    location: str = "location",
    start: str = "start",
    end: str = "end",
) -> Rule:
    """A rule for a tool that puts a new event in the owner's calendar.

    Runs without asking when nobody is invited but the owner (an address in `me`,
    or no address at all): such an event is sent to nobody. It also runs when
    every guest is in `contacts`, there are no more than `max_guests` of them, and
    nothing in the rest of the inputs looks like private data or holds text that
    cannot be seen. The guests get all of it, so all of it is looked at.

    Never: a guest in `blocked`. An entry such as "@example.net" blocks a whole domain.
    Everything else asks: a guest who is not a contact, a list of guests that
    cannot be read for certain, too many guests, and any input the rule was not
    told the name of. The last six settings say what your tool calls its inputs,
    and `ignore` names inputs that are fine to pass over, such as a reminder time.
    The guests must reach the rule as text: one address, a line of them, or a list.

    What this rule cannot see. It gets the inputs of one action, so it does not
    know who is already on an event: for a tool that changes or cancels events,
    use NEEDS_YES. It does not know who else can see the calendar, so a private
    note on an event with no guests runs. It does not judge when the event is.
    """
    known = _address_list("contacts", contacts)
    mine = _address_list("me", me)
    barred = _address_list("blocked", blocked, domains=True)
    if type(max_guests) is not int or max_guests < 1:
        raise RulesError("max_guests must be a whole number, 1 or more")
    both = sorted(address for address in known | mine if _barred(address, barred))
    if both:
        raise RulesError(f"{both[0]} is a contact or one of your own addresses, and is blocked as well")
    fields = _fields(attendees=attendees, title=title, description=description, location=location, start=start, end=end)
    if type(ignore) not in (list, tuple, set, frozenset) or not all(type(name) is str and name for name in ignore):
        raise RulesError("ignore must be a list of the names of inputs, each as text")
    if attendees in ignore:
        raise RulesError("the input that holds the guests cannot be ignored")
    return _Calendar(known, mine, barred, max_guests, frozenset(ignore), fields)


# ---- database ------------------------------------------------------------------------
#
# A statement that only reads is the ordinary work of a database tool, and one
# that changes or deletes is the kind to be asked about. The rule reads the words
# of the statement and never runs it. Where two databases would read the same
# text in two ways (a backslash in a quote, a comment), it asks.

_D_FINE = "it is one statement that only reads, and it names nothing you protect"
_D_UNTOLD = "the rule was not told about {} of the inputs of this query"
_D_UNREAD = "the statement cannot be read"
_D_UNSEEN = "the statement holds a character that cannot be seen"
_D_BACKSLASH = "it holds a backslash, which some databases read as part of a quote and some do not"
_D_COMMENT = "it holds a comment, and some databases run what is inside one"
_D_OPEN = "a quote in it is never closed"
_D_PREFIX = "a quote in it has a letter or a number stuck to its front, which can change how it is read"
_D_BACKTICK = "a name in backticks holds more than a plain name"
_D_DOLLAR = "it holds a $ that is not a numbered placeholder such as $1"
_D_BRACKET = "it uses square brackets or braces in a way the rule does not read"
_D_NUMBER = "a number in it runs into a word"
_D_NOT_PLAIN = "it holds a character outside quotes that the rule does not read"
_D_MORE = "it holds more than one statement"
_D_NOT_SELECT = "it does not start with SELECT or WITH, so the rule cannot tell that it only reads"
_D_CHANGES = "it holds {}, which can change the database"
_D_CALL = "it calls {}, and the rule does not know that it only reads"
_D_QUOTED_CALL = "it calls a function whose name is in quotes"
_D_PROTECTED = "it names {}, which you protect"
_D_PASSWORDS = "it names a place where the database keeps its own passwords"
_D_DROPS = "it holds DROP or TRUNCATE, which remove a whole table, column or database"
_D_EVERY_ROW = "it is a DELETE or an UPDATE with no WHERE of its own, so it would reach every row"

_SQL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SQL_DOTTED = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_SQL_DIGITS = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_SQL_PLACEHOLDER = re.compile(r"\$[0-9]+(?![A-Za-z0-9_$])")
_SQL_BRACKETS = re.compile(r"\[[A-Za-z0-9_ ,.:+-]*\]")
_SQL_MARKS = frozenset("()*,.;=<>!+-/%|&^~:?]")
_SQL_SHOWN = 40  # how much of a function's name a reason writes out

_SQL_CHANGES = frozenset("insert update delete merge into alter create grant revoke replace".split())
_SQL_WHOLE = frozenset("drop truncate".split())
_SQL_BEFORE_BRACKET = frozenset(
    "select from where and or not in exists any all some on using join lateral values as over by case when then else between union except intersect having limit offset filter distinct like group rollup cube sets".split()
)
_SQL_TYPES = frozenset("char varchar nchar nvarchar decimal numeric float binary varbinary bit time timestamp".split())
_SQL_READS = frozenset(
    (
        "count sum avg min max total group_concat string_agg array_agg json_agg bool_and bool_or stddev variance "
        "coalesce nullif ifnull isnull nvl iif if greatest least "
        "abs round floor ceil ceiling trunc mod power sqrt sign "
        "lower upper length char_length substr substring left right trim ltrim rtrim replace concat concat_ws instr position strpos "
        "cast convert try_cast to_char to_date to_timestamp to_number "
        "date datetime julianday strftime now curdate getdate date_trunc date_part extract date_add date_sub datediff date_format dateadd age "
        "year month day hour minute second "
        "row_number rank dense_rank ntile lag lead first_value last_value nth_value percent_rank cume_dist "
        "json_extract json_object json_array json_array_length json_value "
        "unnest array_length cardinality array row"
    ).split()
)
_SQL_SECRETS = ("pg_shadow", "pg_authid", "pg_user_mapping", "pg_user_mappings", "sql_logins", "dba_users")


def _read_sql(text: str) -> tuple:
    """The pieces of a statement, and what about it cannot be read for certain.

    A piece is (kind, text): a "word" outside quotes in small letters, a "text"
    in single quotes, a "name" in double quotes or backticks, a "number", or a
    "mark" such as ( or ;. A comment is not skipped: what is inside it is read
    like the rest, because some databases run it.
    """
    pieces, odd = [], []
    if "\\" in text:
        odd.append(_D_BACKSLASH)
    at = 0
    while at < len(text):
        character = text[at]
        if character in " \t\r\n":
            at += 1
        elif character in "'\"`":
            if at and (text[at - 1].isalnum() or text[at - 1] in "_&"):
                odd.append(_D_PREFIX)
            end = text.find(character, at + 1)
            while end >= 0 and text[end + 1 : end + 2] == character:  # the quote written twice is one quote inside
                end = text.find(character, end + 2)
            if end < 0:
                odd.append(_D_OPEN)
                end = len(text)
            inside = text[at + 1 : end]
            if character == "`" and not _SQL_NAME.fullmatch(inside):
                odd.append(_D_BACKTICK)
            pieces.append(("text" if character == "'" else "name", inside.lower()))
            at = end + 1
        elif character == "#" or text.startswith(("--", "/*"), at):
            odd.append(_D_COMMENT)
            at += 1 if character == "#" else 2
        elif character == "$":
            holder = _SQL_PLACEHOLDER.match(text, at)
            if holder is None:
                odd.append(_D_DOLLAR)
            at = at + 1 if holder is None else holder.end()
        elif character in "[{}":
            if character != "[" or not _SQL_BRACKETS.match(text, at):
                odd.append(_D_BRACKET)
            at += 1
        elif "0" <= character <= "9":
            end = _SQL_DIGITS.match(text, at).end()
            if text[end : end + 1].isalnum() or text[end : end + 1] in ("_", "."):
                odd.append(_D_NUMBER)
            pieces.append(("number", text[at:end]))
            at = end
        elif _SQL_NAME.match(text, at):
            end = _SQL_NAME.match(text, at).end()
            pieces.append(("word", text[at:end].lower()))
            at = end
        else:
            if character in _SQL_MARKS:
                pieces.append(("mark", character))
            else:
                odd.append(_D_NOT_PLAIN)
            at += 1
    return pieces, odd


def _statements(pieces: list) -> list:
    """The pieces cut at each ; into statements. One with nothing in it is left out."""
    found, now = [], []
    for piece in pieces + [("mark", ";")]:
        if piece != ("mark", ";"):
            now.append(piece)
        elif now:
            found.append(now)
            now = []
    return found


def _every_row(statement: list) -> bool:
    """True if a DELETE or an UPDATE in the statement has no WHERE of its own.

    A WHERE inside brackets belongs to what is in the brackets, so it does not
    count for a DELETE outside them, and a DELETE inside brackets (as WITH ...
    AS (DELETE ...) has it) needs a WHERE inside the same brackets.
    """
    reaches, before = [False], None
    for piece in statement:
        if piece == ("mark", "("):
            reaches.append(False)
        elif piece == ("mark", ")"):
            if len(reaches) > 1 and reaches.pop():
                return True
        elif piece in (("word", "delete"), ("word", "update")) and before in (None, ("mark", "("), ("mark", ")")):
            reaches[-1] = True  # the statement itself, one that follows WITH ... AS (...), or one inside brackets
        elif piece == ("word", "where"):
            reaches[-1] = False
        before = piece
    return any(reaches)


def _called(pieces: list, at: int) -> tuple:
    """The whole name of the function called at `at`, with any schema in front, and whether part of it is in quotes."""
    names, quoted = [pieces[at][1]], pieces[at][0] == "name"
    while at >= 2 and pieces[at - 1] == ("mark", ".") and pieces[at - 2][0] in ("word", "name"):
        at -= 2
        names.insert(0, pieces[at][1])
        quoted = quoted or pieces[at][0] == "name"
    return ".".join(names), quoted


def _whole_word(name: str, text: str) -> bool:
    return re.search(rf"(?<![a-z0-9_]){name}(?![a-z0-9_])", text) is not None


class _Database(Rule):
    kind = "database"
    _fine = _D_FINE

    def __init__(self, protect, functions, live, ignored, fields) -> None:
        object.__setattr__(self, "_protect", protect)
        object.__setattr__(self, "_functions", functions)
        object.__setattr__(self, "_live", live)
        object.__setattr__(self, "_ignored", ignored)
        object.__setattr__(self, "_fields", fields)
        super().__init__({"protect": sorted(protect), "functions": sorted(functions), "live": live, "ignore": sorted(ignored), "fields": fields})

    def _look(self, inputs: dict) -> list:
        found = []
        extra = len(set(inputs) - set(self._fields.values()) - self._ignored)
        if extra:
            found.append((NEEDS_YES, _D_UNTOLD.format(extra)))
        sql = inputs.get(self._fields["sql"])
        if type(sql) is not str:
            return found + [(NEEDS_YES, _D_UNREAD)]
        if any(_is_hidden(ord(character)) or _is_control(ord(character)) for character in sql):
            found.append((NEEDS_YES, _D_UNSEEN))
        pieces, odd = _read_sql(sql)
        statements = _statements(pieces)
        if not statements:
            return found + [(NEEDS_YES, _D_UNREAD)]
        found += [(NEEDS_YES, reason) for reason in odd]
        if len(statements) > 1:
            found.append((NEEDS_YES, _D_MORE))

        # Names are looked for in the whole text, in quotes or out of them.
        lowered = sql.lower()
        found += [(NEEDS_YES, _D_PROTECTED.format(name)) for name in sorted(self._protect) if _whole_word(name, lowered)]
        secret = any(_whole_word(name, lowered) for name in _SQL_SECRETS)
        if secret or any(piece[0] in ("word", "name", "text") and piece[1] == "mysql" and after == ("mark", ".") for piece, after in zip(pieces, pieces[1:])):
            found.append((NEEDS_YES, _D_PASSWORDS))

        worst = NEVER if self._live else NEEDS_YES
        reads = True
        for statement in statements:
            if statement[0] not in (("word", "select"), ("word", "with")):
                found.append((NEEDS_YES, _D_NOT_SELECT))
                reads = False
            if _every_row(statement):
                found.append((worst, _D_EVERY_ROW))
        for (kind, text), after in zip(pieces, pieces[1:] + [None]):
            if kind != "word" or (text in ("replace", "truncate") and after == ("mark", "(")):
                continue
            if text in _SQL_WHOLE:
                found.append((worst, _D_DROPS))
                reads = False
            elif text in _SQL_CHANGES:
                found.append((NEEDS_YES, _D_CHANGES.format(text.upper())))
                reads = False
        if not reads:
            return found  # it has said what kind of statement this is: the brackets in it are not calls to look into

        for at, (kind, text) in enumerate(pieces[:-1]):
            if pieces[at + 1] != ("mark", "(") or kind not in ("word", "name"):
                continue
            name, quoted = _called(pieces, at)
            if quoted:
                found.append((NEEDS_YES, _D_QUOTED_CALL))
            elif name not in self._functions and name not in _SQL_BEFORE_BRACKET | _SQL_READS | _SQL_TYPES:
                found.append((NEEDS_YES, _D_CALL.format(name if len(name) <= _SQL_SHOWN else name[:_SQL_SHOWN] + "...")))
        return found


def _name_list(label: str, values: Any, pattern: Any, example: str) -> frozenset:
    """The owner's own names given at setup, checked and copied in small letters."""
    if values is None:
        return frozenset()
    if type(values) not in (list, tuple, set, frozenset):
        raise RulesError(f"{label} must be a list of names, given as the list itself")
    for value in values:
        if type(value) is not str or not pattern.fullmatch(value):
            raise RulesError(f"{label}: {value!r} is not a plain name, such as '{example}'")
    return frozenset(value.lower() for value in values)


def database(protect: Any = None, *, functions: Any = None, live: bool = False, ignore: Any = (), sql: str = "sql", params: str = "params") -> Rule:
    """A rule for a tool that runs one SQL statement on a database.

    Runs without asking only when all of this holds: the text is one statement
    (a ; at the end is fine); it starts with SELECT or WITH; no word in it,
    outside quotes, is one that changes a database (INSERT, UPDATE, DELETE,
    MERGE, INTO, ALTER, CREATE, GRANT, REVOKE, REPLACE, DROP, TRUNCATE); every
    function it calls is one the rule knows only reads (COUNT, SUM, COALESCE,
    LOWER, SUBSTR, CAST, DATE, STRFTIME, ROW_NUMBER and others like them) or is
    one of your own in `functions`; and it names nothing in `protect`, which
    lists the tables and columns you want to be asked about, and no place where
    a database keeps its own passwords (pg_shadow, mysql.user).

    Everything else asks, and says why. So does anything that two databases
    would read in two ways: a backslash, a comment, a quote with a letter stuck
    to its front (E'...'), a $ that is not a placeholder such as $1, a name in
    square brackets or backticks that is more than a plain name. A value passed
    in `params` is not part of the statement and is not judged. `ignore` names
    inputs that do not change what runs, such as a time limit; any other input
    the rule was not told about asks, because it may choose the database.

    With `live=True` the worst kinds are refused, not asked about: DROP and
    TRUNCATE anywhere in the text outside quotes (in a comment too), and a
    DELETE or an UPDATE with no WHERE of its own. Use it for a database you
    cannot lose.

    What it cannot do. It reads names, not data: a private table with an
    ordinary name runs unless you list it in `protect`, and so does a view of a
    protected table under another name. A WHERE that is always true (WHERE 1=1)
    only asks, even with `live=True`. It does not judge how heavy a query is.
    It trusts that a function with an ordinary name is the ordinary one. The
    real wall is a database user that may only read: give the tool one, and use
    this rule to be asked less about the rest.
    """
    guarded = _name_list("protect", protect, _SQL_NAME, "payroll")
    own = _name_list("functions", functions, _SQL_DOTTED, "monthly_total")
    if type(live) is not bool:
        raise RulesError("live must be True or False")
    fields = _fields(sql=sql, params=params)
    if type(ignore) not in (list, tuple, set, frozenset) or not all(type(name) is str and name for name in ignore):
        raise RulesError("ignore must be a list of the names of inputs, each as text")
    if sql in ignore:
        raise RulesError("the input that holds the statement cannot be ignored")
    return _Database(guarded, own, live, frozenset(ignore), fields)
