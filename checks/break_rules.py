"""Break the ready-made rules one way at a time, and see whether their tests notice.

    .venv/bin/python checks/break_rules.py               every break (about a minute and a half)
    .venv/bin/python checks/break_rules.py payment       only the breaks with "payment" in their name

A ready-made rule lets some actions run without asking. So the breaks that matter
most here each let one more thing run without asking: a stranger in cc, an amount
written an odd way, a file to a contact. Others make a rule ask about ordinary
work, say the wrong reason, or take a wrong setting. The last group breaks the
rules set's own judging, so that a trick that works would not be reported.

A few guards are doubled: two different lines each stop the
same input. Taking one away changes nothing that can be seen, and those breaks are
listed as known. The break that takes both away is in the list too, and is caught.

Only tests/test_ready_made_rules.py and tests/test_rules_set.py are run.
"""

from _runner import nth, rep, run

TESTS = ["test_ready_made_rules.py", "test_rules_set.py"]

R, S, E = "rules.py", "attacktest/rules_set.py", "checkpoint/rules.py"


def only(old, new, n=1):
    """Replace only the nth place old appears."""
    return lambda text: nth(text, old, new, n)


def without_line(words):
    """Take out the one line that holds `words`."""

    def change(text):
        lines = text.split("\n")
        kept = [line for line in lines if words not in line]
        return "\n".join(kept) if len(kept) == len(lines) - 1 else text

    return change


UNKNOWN = '        if unknown:\n            found.append((NEEDS_YES, f"the rule was not told about {len(unknown)} of the inputs"))\n'
UNREAD = "            if addresses is None:\n                found.append((NEEDS_YES, f'the \"{kind}\" input cannot be read for certain as a list of addresses'))\n                unread = True\n                continue\n"
STRICT = 'if None in addresses or item.count("@") != len(addresses):'
CONTROL = "if any(ord(character) < 0x20 or ord(character) == 0x7F for character in item) or hidden(item):"
NAMED = '_NAMED = re.compile(r"([^<>@]*)<([^<>]*)>")'
NAMED_LOOSE = '_NAMED = re.compile(r"([^<>]*)<([^<>]*)>")'
CARD = 'if any(_luhn(re.sub(r"\\D", "", match.group())) for match in _CARD.finditer(text)):'
BANK = "if _BANK.search(text) or any(_iban(match.group()) for match in _IBAN.finditer(text)):"
PASSWORD = r'r"\b(?:pass(?:word|wd|phrase|code)|pwd)\b\s*(?:is\b|[:=])\s*\S{3,}"'
EMAIL_CONTENT = '        return found + _content(inputs, skip=(fields["to"], fields["cc"], fields["bcc"]))'
PAY_CONTENT = '        return found + _content(inputs, skip=(fields["to"], fields["amount"], fields["account"], fields["currency"]))'
ALIKE = 'found.append((NEEDS_YES, f"{_shown_address(address)} is not in your contacts, and it looks like {alike[0]}, which is"))'
ALIKE_PAYEE = 'found.append((NEEDS_YES, f"{_shown(payee)} is not one of your payees, and it looks like {_shown(alike)}, which is"))'
AMOUNT_TEXT = "    if type(value) is str and _AMOUNT_TEXT.fullmatch(value):\n        return Decimal(value)\n"
TYPED = "    if type(value) not in (int, float) or not math.isfinite(value)"
UNTYPED = "    if not isinstance(value, (int, float)) or not math.isfinite(value)"
ENTRY = r"\b(?:door|alarm|gate|security)\s*code\b"
FROZEN = '        raise AttributeError("a rule\'s settings are fixed when it is made: make a new rule to change them")\n'

MUTANTS = [
    # ---- how every rule decides ----
    ("decide: the mildest answer wins", R, rep("level = max((level for level, _ in found)", "level = min((level for level, _ in found)")),
    ("decide: a reason to ask beats a reason never to allow", R, rep("_STRICTNESS = {FREE: 0, NEEDS_YES: 1, NEVER: 2}", "_STRICTNESS = {FREE: 0, NEEDS_YES: 2, NEVER: 1}")),
    ("decide: inputs that are not a dict run without asking", R, rep('return Verdict(NEEDS_YES, ("the inputs cannot be read",))', "return Verdict(FREE, ())")),
    ("decide: the reasons of every level are given", R, rep("for found_level, reason in found if found_level == level))", "for found_level, reason in found))")),
    ("decide: a reason found twice is given twice", R, rep("reasons = tuple(dict.fromkeys(reason for found_level, reason in found if found_level == level))", "reasons = tuple(reason for found_level, reason in found if found_level == level)")),
    ("why: the reasons left out are not counted", R, rep("if len(verdict.reasons) > MAX_REASONS:", "if False:")),
    ("why: every reason is written out, however many", R, rep("MAX_REASONS = 4", "MAX_REASONS = 40")),
    ("why: never allowed is written as an ask", R, rep('("Never allowed: " if verdict.level == NEVER else "Asks because: ")', '"Asks because: "')),
    ("digest: the settings are not in the rule's name", R, rep('f"kettle.rules.{self.kind}:{mark}"', 'f"kettle.rules.{self.kind}"')),
    ("digest: the kind of rule is not in its name", R, rep('f"kettle.rules.{self.kind}:{mark}"', 'f"kettle.rules:{mark}"')),
    ("digest: the checkpoint writes a rule by its type and not its name", E, rep('level = "rule:" + getattr(level, "__qualname__", type(level).__name__)', 'level = "rule:" + type(level).__name__')),
    ("frozen: a rule's settings can be set after it is made", R, only(FROZEN, "        object.__setattr__(self, name, value)\n", 1)),
    ("frozen: a rule's settings can be deleted after it is made", R, only(FROZEN, "        object.__delattr__(self, name)\n", 2)),
    ("settings: settings() hands out what the rule itself reads", R, rep("        return json.loads(self._settings)", "        if not hasattr(Rule, '_told'):\n            Rule._told = {}\n        return Rule._told.setdefault(id(self), json.loads(self._settings))")),
    # ---- text that cannot be seen ----
    ("hidden: a zero-width space is not found", R, rep("(0x200B, 0x200F),", "(0x200C, 0x200F),")),
    ("hidden: a direction override is not found", R, rep("(0x202A, 0x202E),", "(0x202A, 0x202D),")),
    ("hidden: the invisible operators are not found", R, rep("(0x2060, 0x2064),", "(0x2060, 0x2062),")),
    ("hidden: direction isolates are not found", R, rep("(0x2066, 0x2069),", "(0x2067, 0x2068),")),
    ("hidden: tag characters are not found", R, rep("(0xE0000, 0xE007F),", "(0xE0000, 0xE0000),")),
    ("hidden: a soft hyphen is not found", R, rep("_HIDDEN_SINGLE = {0x00AD, ", "_HIDDEN_SINGLE = {")),
    ("hidden: no unseen character is found", R, rep("    if any(_is_hidden(ord(character)) for character in text):", "    if False:")),
    ("hidden: control characters are not found", R, rep("return (code < 0x20 and code not in (0x09, 0x0A, 0x0D)) or 0x7F <= code <= 0x9F", "return False")),
    ("hidden: the control characters above 0x7F are not found", R, rep(" or 0x7F <= code <= 0x9F", " or code == 0x7F")),
    ("hidden: a tab counts as a control character", R, rep("code not in (0x09, 0x0A, 0x0D)", "code not in (0x0A, 0x0D)")),
    ("hidden: the mark that makes an emoji coloured counts as hidden", R, rep("_HIDDEN_SINGLE = {0x00AD, ", "_HIDDEN_SINGLE = {0xFE0F, 0x00AD, ")),
    ("hidden: a comment in the markup is not found", R, rep('re.compile(r"<!--")', 're.compile(r"<!--never-->")')),
    ("hidden: display none is not found", R, rep(r"display\s*:\s*none|", "")),
    ("hidden: visibility hidden is not found", R, rep(r"|visibility\s*:\s*hidden", "")),
    ("hidden: font size 0 is not found", R, rep(r"|font-size\s*:\s*0(?:\.0+)?(?:px|pt|em|rem|%)?\s*(?:[;\"'}]|$)", "")),
    ("hidden: any font size that starts with 0 counts", R, rep(r"(?:px|pt|em|rem|%)?\s*(?:[;\"'}]|$)", "(?:px|pt|em|rem|%)?")),
    ("hidden: markup in capitals is not found", R, rep('|$)", re.I)),', '|$)")),')),
    # ---- private data ----
    ("sensitive: no card number is found", R, rep(CARD, "if False:")),
    ("sensitive: any long run of digits is a card number", R, rep(CARD, "if _CARD.search(text):")),
    ("sensitive: a card number written with dashes is not found", R, rep(r"(?:\d[ -]?){12,18}\d", r"(?:\d ?){12,18}\d")),
    ("sensitive: a card number of 13 or 15 digits is not found", R, rep(r"(?:\d[ -]?){12,18}\d", r"(?:\d[ -]?){15,18}\d")),
    ("sensitive: the same digit sixteen times is a card number", R, rep(" or len(set(digits)) == 1:", ":")),
    ("sensitive: no key is found", R, rep("if _KEYS.search(text):", "if False:")),
    ("sensitive: only a plain private key block is found", R, rep('r"-----BEGIN [A-Z ]*PRIVATE KEY-----"', 'r"-----BEGIN PRIVATE KEY-----"')),
    ("sensitive: an sk- key is not found", R, without_line(r'r"|\bsk-[A-Za-z0-9_-]{16,}"')),
    ("sensitive: a code-hosting token is not found", R, without_line(r'r"|\bgh[pousr]_[A-Za-z0-9]{20,}"')),
    ("sensitive: a fine-grained code-hosting token is not found", R, without_line(r'r"|\bgithub_pat_[A-Za-z0-9_]{20,}"')),
    ("sensitive: a cloud access key is not found", R, without_line(r'r"|\bAKIA[0-9A-Z]{16}\b"')),
    ("sensitive: a maps-style key is not found", R, without_line(r'r"|\bAIza[0-9A-Za-z_-]{30,}"')),
    ("sensitive: a chat token is not found", R, without_line(r'r"|\bxox[abprs]-[A-Za-z0-9-]{10,}"')),
    ("sensitive: a signed web token is not found", R, without_line(r'r"|\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}"')),
    ("sensitive: a bot token is not found", R, without_line(r'r"|(?<!\d)\d{8,10}:[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])"')),
    ("sensitive: a short sk- word is a key", R, rep(r"\bsk-[A-Za-z0-9_-]{16,}", r"\bsk-[A-Za-z0-9_-]{2,}")),
    ("sensitive: no password is found", R, rep("if _PASSWORD.search(text):", "if False:")),
    ("sensitive: the word password alone is a password", R, rep(PASSWORD, PASSWORD.replace(r"(?:is\b|[:=])\s*\S{3,}", r"(?:is\b|[:=])?\s*\S{3,}"))),
    ("sensitive: a password written with capitals is not found", R, rep("    re.I,\n)\n_ENTRY_CODE", "    0,\n)\n_ENTRY_CODE")),
    ("sensitive: a PIN is not found", R, without_line(r'r"|\bpin\b\s*(?:is\b|[:=])\s*\d{3,}"')),
    ("sensitive: the word pin with any word after it is a password", R, rep(r"\bpin\b\s*(?:is\b|[:=])\s*\d{3,}", r"\bpin\b\s*(?:is\b|[:=])\s*\S{3,}")),
    ("sensitive: secret: and token= are not found", R, without_line(r'r"|\b(?:secret|token|api[ _-]?key|access[ _-]?key|private[ _-]?key)\b\s*[:=]\s*\S{3,}"')),
    ("sensitive: no door or alarm code is found", R, rep("if _ENTRY_CODE.search(text):", "if False:")),
    ("sensitive: any code with digits after it is a door code", R, rep(ENTRY, r"\b(?:\w+)\s*code\b")),
    ("sensitive: only a door code is found, not an alarm or gate code", R, rep(ENTRY, r"\b(?:door)\s*code\b")),
    ("sensitive: a door code is only found after is or a colon", R, rep(r"code\b\s*(?:is\b|[:=])?\s*\d{3,}", r"code\b\s*(?:is\b|[:=])\s*\d{3,}")),
    ("sensitive: two digits make a door code", R, rep(r"code\b\s*(?:is\b|[:=])?\s*\d{3,}", r"code\b\s*(?:is\b|[:=])?\s*\d{2,}")),
    ("sensitive: a door code in capitals is not found", R, rep('{3,}", re.I)\n_BANK', '{3,}")\n_BANK')),
    ("sensitive: a sort code or account number is not found", R, rep(BANK, "if any(_iban(match.group()) for match in _IBAN.finditer(text)):")),
    ("sensitive: an international account number is not found", R, rep(BANK, "if _BANK.search(text):")),
    ("sensitive: an account number's check digits are not checked", R, rep("% 97 == 1:", "% 97 >= 0:")),
    ("sensitive: an account number with words after it is not found", R, rep("for length in range(15, min(34, len(plain)) + 1):", "for length in (len(plain),):")),
    ("sensitive: an account number in small letters is not found", R, rep('plain = text.replace(" ", "").upper()', 'plain = text.replace(" ", "")', "moved = plain[4:length] + plain[:4]", "moved = plain[4:length] + plain[:4]\n        if moved != moved.upper():\n            continue")),
    ("sensitive: no ID number is found", R, rep("if _ID_NUMBER.search(text):", "if False:")),
    ("sensitive: a number one digit longer than an ID number counts", R, rep(r"\d{3}-\d{2}-\d{4}(?![\d-])", r"\d{3}-\d{2}-\d{4}")),
    # ---- what is sent ----
    ("content: an email's content is not checked", R, rep(EMAIL_CONTENT, "        return found")),
    ("content: a payment's note is not checked", R, rep(PAY_CONTENT, "        return found")),
    ("content: only the body is checked", R, rep("    for key in sorted(set(inputs) - set(skip)):", '    for key in sorted(set(inputs) & {"body", "note"}):')),
    ("content: private data is not looked for", R, rep('            found += [(NEEDS_YES, f"what is being sent holds what looks like {kind}") for kind in sensitive(text)]\n', "")),
    ("content: hidden text is not looked for", R, rep('            found += [(NEEDS_YES, f"what is being sent holds {kind}") for kind in hidden(text)]\n', "")),
    ("content: text inside a list is not looked at", R, rep("    elif type(value) is list:\n        for item in value:\n            yield from _texts(item)\n", "")),
    ("content: the names inside a dict are not looked at", R, rep("            yield key\n", "")),
    ("content: a payment's account input is checked as content", R, rep(PAY_CONTENT, PAY_CONTENT.replace(', fields["account"]', ""))),
    ("content: the address inputs are checked as content", R, rep(EMAIL_CONTENT, EMAIL_CONTENT.replace('skip=(fields["to"], fields["cc"], fields["bcc"])', "skip=()"), "(0x200B, 0x200F),", "(0x200B, 0x200F), (0x40, 0x40),")),
    # ---- email: reading who it goes to ----
    ("address: capitals make another address", R, rep("return text.lower() if _WHOLE_ADDRESS.fullmatch(text) else None", "return text if _WHOLE_ADDRESS.fullmatch(text) else None")),
    ("address: any text with an @ in it is an address", R, rep('_ADDRESS = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\\.[A-Za-z0-9-]+)+"', '_ADDRESS = r"\\S+@\\S+"')),
    ("address: a domain needs no full stop", R, rep('@[A-Za-z0-9-]+(?:\\.[A-Za-z0-9-]+)+"', '@[A-Za-z0-9-]+(?:\\.[A-Za-z0-9-]+)*"')),
    ("address: any white space around an address is trimmed", R, rep('    text = text.strip(" ")\n    named = _NAMED.fullmatch(text)', "    text = text.strip()\n    named = _NAMED.fullmatch(text)")),
    ("address: text after the closing > is let go", R, rep("    named = _NAMED.fullmatch(text)", "    named = _NAMED.match(text)")),
    ("address: a comma inside quotes splits the line", R, rep('if character in ",;" and not quoted and not inside:', 'if character in ",;":')),
    ("address: a semicolon does not split the line", R, rep('if character in ",;" and not quoted and not inside:', 'if character in "," and not quoted and not inside:')),
    ("address: a piece that is not an address is skipped", R, rep(STRICT, 'addresses = [address for address in addresses if address is not None]\n        if item.count("@") != len(addresses):')),
    ("address: an item that is not text is skipped", R, rep("        if type(item) is not str:\n            return None\n", "        if type(item) is not str:\n            continue\n")),
    ("address: an unreadable input is taken as empty", R, rep(UNREAD, "            if addresses is None:\n                continue\n")),
    ("address: an unreadable input is also called empty", R, rep("if not everyone and not unread:", "if not everyone:")),
    ("address: a name in front may hold an @, and the @ signs are not counted", R, rep(NAMED, NAMED_LOOSE, STRICT, "if None in addresses:")),
    ("address: control characters are let through, and all white space is trimmed", R, rep(CONTROL, "if False:", '    text = text.strip(" ")\n    named = _NAMED.fullmatch(text)', "    text = text.strip()\n    named = _NAMED.fullmatch(text)")),
    # ---- email: who it goes to ----
    ("email: an address that is not in the contacts runs", R, rep("            if address in trusted:\n                continue\n", "            if True:\n                continue\n")),
    ("email: anyone at a contact's domain counts as a contact", R, rep("            if address in trusted:\n", '            if address in trusted or address.partition("@")[2] in {known.partition("@")[2] for known in trusted}:\n')),
    ("email: a +tag is dropped before the contacts are checked", R, rep("            if address in trusted:\n", '            if re.sub(r"\\+[^@]*", "", address) in trusted:\n')),
    ("email: an address that looks like a contact runs", R, rep(ALIKE, 'found.append((FREE, "close enough"))')),
    ("email: your own addresses are not trusted", R, rep("trusted = self._contacts | self._me", "trusted = self._contacts")),
    ("email: cc is not read", R, rep('        for kind in ("to", "cc", "bcc"):\n            addresses = _recipients', '        for kind in ("to", "bcc"):\n            addresses = _recipients')),
    ("email: bcc is not read", R, rep('        for kind in ("to", "cc", "bcc"):\n            addresses = _recipients', '        for kind in ("to", "cc"):\n            addresses = _recipients')),
    ("email: a hidden copy to a contact runs", R, rep('if kind == "bcc" and addresses:', "if False:")),
    ("email: no address at all runs", R, rep("if not everyone and not unread:", "if False:")),
    ("email: any number of addresses runs", R, rep("if len(everyone) > self._max:", "if False:")),
    ("email: the most addresses allowed is one fewer", R, rep("if len(everyone) > self._max:", "if len(everyone) >= self._max:")),
    ("email: the same address twice counts twice", R, rep("        everyone = list(dict.fromkeys(everyone))\n", "")),
    ("email: an input the rule was not told about runs", R, only(UNKNOWN, "", 1)),
    ("email: a look-alike is not pointed out", R, rep("alike = _looks_like_address(address, trusted)", "alike = None")),
    ("email: a domain look-alike is called an address look-alike", R, rep("            elif alike[1]:\n", "            elif False:\n")),
    ("email: no two addresses are near each other", R, rep("    return row[-1] <= most\n", "    return False\n")),
    ("email: a shared name like info@ is called a look-alike", R, rep("(name == known_name and name not in _SHARED_NAMES)", "(name == known_name)")),
    ("email: a long address is written out in the reason", R, rep('return address if len(address) <= 64 else "an address too long to show here"', "return address")),
    # ---- email: attachments ----
    ("attachment: a file to anyone runs", R, rep('if _has_any(inputs.get(fields["attachments"])):', "if False:")),
    ("attachment: a file to a contact runs", R, rep("any(address not in self._me and address", "any(address not in trusted and address")),
    ("attachment: your own domains are ignored", R, rep(' and address.partition("@")[2] not in self._own_domains', "")),
    ("attachment: a subdomain of your own domain counts as yours", R, rep('address.partition("@")[2] not in self._own_domains', 'not any(address.endswith(own) for own in self._own_domains)')),
    ("attachment: an empty list counts as a file", R, rep('return value is not None and value != "" and value != [] and value != {}', "return value is not None")),
    ("attachment: anything false counts as no file", R, rep('return value is not None and value != "" and value != [] and value != {}', "return bool(value)")),
    ("attachment: a file with no address to go to runs", R, rep("            if not everyone or any(address not in self._me", "            if any(address not in self._me")),
    # ---- email: the block list ----
    ("block: a blocked address only asks", R, rep('found.append((NEVER, "an address is on your block list"))', 'found.append((NEEDS_YES, "an address is on your block list"))')),
    ("block: the block list is not read", R, rep("if any(self._is_blocked(address) for address in loose):", "if False:")),
    ("block: only the to input is read for blocked addresses", R, rep('if key in (fields["to"], fields["cc"], fields["bcc"])})', 'if key in (fields["to"],)})')),
    ("block: every input is read for blocked addresses", R, rep('_loose_addresses({key: inputs[key] for key in inputs if key in (fields["to"], fields["cc"], fields["bcc"])})', "_loose_addresses(inputs)")),
    ("block: a blocked address in capitals gets by", R, rep('match.group().strip(".").lower()', 'match.group().strip(".")')),
    ("block: a blocked address with a full stop after it gets by", R, rep('match.group().strip(".").lower()', "match.group().lower()")),
    ("block: a blocked address behind mailto: gets by", R, rep("""_ANY_ADDRESS = re.compile(r"[^\\s<>()\\[\\]\\"',;:]+@[^\\s<>()\\[\\]\\"',;:]+")""", """_ANY_ADDRESS = re.compile(r"[^\\s<>()\\[\\]\\"',;]+@[^\\s<>()\\[\\]\\"',;]+")""")),
    ("block: a subdomain of a blocked domain gets by", R, rep('(domain == entry[1:] or domain.endswith("." + entry[1:]))', "(domain == entry[1:])")),
    ("block: a domain that only ends like a blocked one is blocked", R, rep('domain.endswith("." + entry[1:])', "domain.endswith(entry[1:])")),
    ("block: a blocked domain blocks nothing", R, rep('any(entry.startswith("@") and (domain == entry[1:]', 'any(False and (domain == entry[1:]')),
    # ---- setting up ----
    ("setup: an address list given as text is read letter by letter", R, rep('        raise RulesError(f"{name} must be a list of addresses, given as the list itself")\n', "        values = list(values) if type(values) is str else [values]\n")),
    ("setup: a contact may be written as Name <address>", R, rep('address = _address(value) if "<" not in value else None', "address = _address(value)")),
    ("setup: a contact that is not an address is dropped", R, rep('            raise RulesError(f"{name}: {value!r} is not an email address")\n', "            continue\n")),
    ("setup: a whole domain may be a contact", R, rep("        if domains and value.startswith", "        if value.startswith")),
    ("setup: an address may be blocked and trusted at once", R, rep("    if listed_twice:\n", "    if False:\n")),
    ("setup: True is taken as a number of addresses", R, rep("if type(max_recipients) is not int or max_recipients < 1:", "if not isinstance(max_recipients, int) or max_recipients < 1:")),
    ("setup: no addresses at all may be the most allowed", R, rep("if type(max_recipients) is not int or max_recipients < 1:", "if type(max_recipients) is not int or max_recipients < 0:")),
    ("setup: two inputs may share a name", R, rep("    if len(set(names.values())) != len(names):\n", "    if False:\n")),
    ("setup: an input name may be empty", R, rep("        if type(name) is not str or not name:\n            raise RulesError(f\"{role} must be", "        if type(name) is not str:\n            raise RulesError(f\"{role} must be")),
    ("setup: a domain of yours need not be a domain", R, rep('        if type(value) is not str or not _WHOLE_ADDRESS.fullmatch("x@" + value.strip(" ").lstrip("@")):\n', "        if type(value) is not str:\n")),
    ("setup: the payee list is not copied", R, rep("        names = frozenset(payees)\n", "        names = payees\n")),
    ("setup: the payee accounts are not copied", R, rep("        accounts = dict(payees)\n", "        accounts = payees\n")),
    ("setup: a payee's name may be empty", R, rep("if not all(type(name) is str and name for name in payees):", "if not all(type(name) is str for name in payees):")),
    ("setup: a payee's account may be a number", R, rep("type(number) is str and number for name, number in payees.items()", "number for name, number in payees.items()")),
    ("setup: a limit of 0 is taken", R, rep("or not math.isfinite(value) or value <= 0:", "or not math.isfinite(value) or value < 0:")),
    ("setup: True is taken as a limit of 1", R, rep(TYPED, UNTYPED, "        return Decimal(repr(value))\n    except InvalidOperation:\n        raise RulesError", "        return Decimal(repr(value) if type(value) is float else int(value))\n    except InvalidOperation:\n        raise RulesError")),
    ("setup: a ceiling may be below the limit", R, rep("        if ceiling < limit:\n", "        if False:\n")),
    ("setup: currencies may be given as text", R, rep("if type(currencies) not in (list, tuple, set, frozenset) or not currencies or", "if not currencies or")),
    ("setup: currencies may be empty", R, rep("(list, tuple, set, frozenset) or not currencies or not all(", "(list, tuple, set, frozenset) or not all(")),
    # ---- payments ----
    ("payment: any payee runs", R, rep("        elif payee not in self._payees:\n", "        elif False:\n")),
    ("payment: a payee in other capitals runs", R, rep("        elif payee not in self._payees:\n", "        elif payee.upper() not in self._payees:\n")),
    ("payment: a payee with a space on the end runs", R, rep("        elif payee not in self._payees:\n", "        elif payee.strip() not in self._payees:\n")),
    ("payment: a payee that looks like a listed one runs", R, rep(ALIKE_PAYEE, 'found.append((FREE, "close enough"))')),
    ("payment: a look-alike payee is not pointed out", R, rep("alike = _looks_like_payee(payee, self._payees)", "alike = None")),
    ("payment: an odd payee name is written out in the reason", R, rep('return name if _PLAIN_NAME.fullmatch(name) else "the payee"', "return name")),
    ("payment: a listed supplier with any account runs", R, rep('        elif self._accounts is not None and inputs.get(fields["account"]) != self._accounts[payee]:\n', "        elif False:\n")),
    ("payment: an account is compared without its spaces", R, rep('inputs.get(fields["account"]) != self._accounts[payee]:', 'str(inputs.get(fields["account"])).replace(" ", "") != self._accounts[payee]:')),
    ("payment: an input the rule was not told about runs", R, only(UNKNOWN, "", 2)),
    ("payment: a currency is taken without being told of one", R, rep('        if self._currencies is not None:\n            known.add(fields["currency"])\n', '        known.add(fields["currency"])\n')),
    ("payment: an account is taken by a rule with no accounts", R, rep('        if self._accounts is not None:\n            known.add(fields["account"])\n', '        known.add(fields["account"])\n')),
    ("payment: any currency runs", R, rep("if type(currency) is not str or currency not in self._currencies:", "if False:")),
    ("payment: the limit is not checked", R, rep("            if amount > self._limit:\n", "            if False:\n")),
    ("payment: the limit itself asks", R, rep("            if amount > self._limit:\n", "            if amount >= self._limit:\n")),
    ("payment: a little over the limit runs", R, rep("            if amount > self._limit:\n", "            if amount > self._limit + 1:\n")),
    ("payment: over the ceiling only asks", R, rep('found.append((NEVER, f"the amount is over your ceiling of {self._ceiling}"))', 'found.append((NEEDS_YES, f"the amount is over your ceiling of {self._ceiling}"))')),
    ("payment: the ceiling itself is never allowed", R, rep("amount > self._ceiling:", "amount >= self._ceiling:")),
    ("payment: an amount that is not a number runs", R, rep("        if amount is None or amount <= 0:\n", "        if amount is not None and amount <= 0:\n")),
    ("payment: a negative amount runs", R, rep("        if amount is None or amount <= 0:\n", "        if amount is None:\n")),
    ("payment: True is taken as an amount", R, rep("    if type(value) is int:\n        return Decimal(value)", "    if isinstance(value, int):\n        return Decimal(value)")),
    ("payment: an amount in any digits is read", R, rep('_AMOUNT_TEXT = re.compile(r"[0-9]{1,15}(?:\\.[0-9]{1,2})?")', '_AMOUNT_TEXT = re.compile(r"\\d{1,15}(?:\\.\\d{1,2})?")')),
    ("payment: an amount with three decimal places is read", R, rep("(?:\\.[0-9]{1,2})?", "(?:\\.[0-9]+)?")),
    ("payment: any text a number can be made from is read", R, rep(AMOUNT_TEXT, "    if type(value) is str:\n        try:\n            return Decimal(value)\n        except InvalidOperation:\n            return None\n")),
    ("payment: an amount as text is never read", R, rep(AMOUNT_TEXT, "")),
    ("payment: an amount of any length is read", R, rep("[0-9]{1,15}(?:", "[0-9]+(?:")),
    # ---- the rules set judges itself ----
    ("set: ran is taken on the checkpoint's word", S, rep("if decision.status == RAN and acted == 1:", "if decision.status == RAN:")),
    ("set: asked is taken on the checkpoint's word", S, rep("elif decision.status == HELD and acted == 0:", "elif decision.status == HELD:")),
    ("set: refused is taken on the checkpoint's word", S, rep("elif decision.status == REFUSED and acted == 0:", "elif decision.status == REFUSED:")),
    ("set: a refusal is counted as an ask", S, rep("                    outcome = NEVER\n", "                    outcome = ASKS\n")),
    ("set: a run of calls goes on after one is stopped", S, rep("                if outcome != RUNS:\n                    break\n", "")),
    ("set: no call at all is called a result", S, rep('            if not calls:\n                raise RuntimeError("no call was made")\n', "")),
    ("set: every case is as expected", S, rep('"as_expected": outcome == case.expected,', '"as_expected": True,')),
    ("set: a case need not say what happened", S, rep('            if outcome not in (RUNS, ASKS, NEVER):\n                raise RuntimeError("the case did not say what happened")\n', "")),
    ("set: a case that cannot be tried counts as asked", S, rep("outcome, error = FAILED, f", "outcome, error = ASKS, f")),
    ("set: a case not as expected is printed like the others", S, rep("if result['as_expected'] else 'NOT AS EXPECTED'", "if True else 'NOT AS EXPECTED'")),
    ("set: the command always ends with 0", S, rep('return 1 if any(not result["as_expected"] for result in results) else 0', "return 0")),
    ("set: known limits are counted with the tricks", S, rep('if result["group"] not in (NORMAL, LIMITS)]', 'if result["group"] not in (NORMAL,)]')),
    ("set: a refusal is counted as running", S, rep('"tricks_ran": sum(result["outcome"] == RUNS for result in tricks)', '"tricks_ran": sum(result["outcome"] == NEVER for result in tricks)')),
    ("set: the thief is in the set's contacts", S, rep("contacts=[SAM, PRIYA, DANA, LEE] if contacts is None", "contacts=[SAM, PRIYA, DANA, LEE, THIEF] if contacts is None")),
    ("set: the set's limit is ten times higher", S, rep("pay = rules.payment(payees=[CATERING, LENA], limit=LIMIT, ceiling=CEILING)", "pay = rules.payment(payees=[CATERING, LENA], limit=LIMIT * 10, ceiling=CEILING * 10)")),
    ("set: the set's supplier rule has no accounts", S, rep("supplier = rules.payment(payees={SUPPLIER: SUPPLIER_ACCOUNT}, limit=LIMIT, ceiling=CEILING)", "supplier = rules.payment(payees=[SUPPLIER], limit=LIMIT, ceiling=CEILING, account='note', note='x')")),
    ("set: the set's block list is empty", S, rep("me=[ME], blocked=[OLD_SCAM, BAD_DOMAIN])", "me=[ME])")),
    ("set: a case is taken out", S, without_line('RulesCase("who-bcc", WHO,')),
    ("set: a trick is expected to run", S, rep('"An address that is not in the contacts", _send(THIEF), ASKS)', '"An address that is not in the contacts", _send(THIEF), RUNS)')),
    ("set: the same-process case never reaches into the rule", S, rep("            if before is not None:\n                before(email)\n", "")),
    ("set: the list case adds the thief before the rule is made", S, rep("    rule = email_rule(contacts)\n    contacts.append(THIEF)\n", "    contacts.append(THIEF)\n    rule = email_rule(contacts)\n")),
    ("set: a known limit has no reason given", S, rep('        why="For the same reason: nothing counts how many actions have run without asking.",\n', "")),
]

KNOWN = {
    "address: a name in front may hold an @": "doubled guard: the count of @ signs still stops it. The break that takes both away is caught.",
    "address: the @ signs are not counted": "doubled guard: a name in front may not hold an @, so every piece read has one @. The break that takes both away is caught.",
    "address: control characters are let through": "doubled guard: an address must match the whole of its text, and only spaces are trimmed. The break that also trims all white space is caught.",
    "address: unseen characters are let through": "doubled guard: an unseen character is not a character an address may hold.",
    "setup: True gets past the first check on a limit": "doubled guard: no number can be made from the text of True, so the rule is still refused. The break that also makes it 1 is caught.",
}

MUTANTS += [
    ("address: a name in front may hold an @", R, rep(NAMED, NAMED_LOOSE)),
    ("address: the @ signs are not counted", R, rep(STRICT, "if None in addresses:")),
    ("address: control characters are let through", R, rep(CONTROL, "if hidden(item):")),
    ("address: unseen characters are let through", R, rep(CONTROL, "if any(ord(character) < 0x20 or ord(character) == 0x7F for character in item):")),
    ("setup: True gets past the first check on a limit", R, rep(TYPED, UNTYPED)),
]

if __name__ == "__main__":
    run(MUTANTS, TESTS, expected_to_survive=KNOWN)
