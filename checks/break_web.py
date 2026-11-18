"""Break the ready-made web rule one way at a time, and see whether its tests notice.

    .venv/bin/python checks/break_web.py             every break (about two minutes)
    .venv/bin/python checks/break_web.py home        only the breaks with "home" in their name

The web rule lets a request run without asking when the site is on the owner's
list and nothing about it is unusual, and never lets one reach this machine or
the owner's own network. So the breaks that matter most here each let one more
request run, or turn a refusal into an ask: an address read the loose way, a way
of writing 127.0.0.1 that is not known, a long string of data in an address, a
send taken for a read. Others make the rule say the wrong reason or take a wrong
setting, and the last group breaks the rules set's own web cases.

A few guards are doubled: a numbered address that cannot be read is treated as
home, so a break in reading one form of number changes the reason and not the
answer. Those are caught by the tests of the pieces.

Only tests/test_web_rule.py and tests/test_rules_set.py are run.
"""

from _runner import rep, run

TESTS = ["test_web_rule.py", "test_rules_set.py"]

R, S = "rules.py", "attacktest/rules_set.py"


def without_line(words):
    """Take out the one line that holds `words`."""

    def change(text):
        lines = text.split("\n")
        kept = [line for line in lines if words not in line]
        return "\n".join(kept) if len(kept) == len(lines) - 1 else text

    return change


ODD = 'if found is None or any(not 0x20 < ord(character) < 0x7F or character == "\\\\" for character in address):'
UNSURE = "unsure = (NEVER, _MAYBE_HOME) if any(_local(host) for host in _loose_hosts(plain)) else (NEEDS_YES, _UNSURE)"
PORT = "if port is not None and (not _PORT.fullmatch(port) or int(port[1:]) > 65535):"
NUMBERED = '    if _is_number(host):\n        return NEEDS_YES, "the address is a number, not the name of a site"\n'
NAMES = 'return "." not in name or name == "localhost" or name.endswith(_LOCAL_ENDINGS)'
UNREAD_FOUR = 'return address is None or not _public(address)\n    return "." not in name'
UNREAD_SIX = "return address is None or not _public(address)\n    name = host"
INSIDE = "if inside is None and int(address) >> 32 in (0, 0x64FF9B << 64):"
KEPT = '    text = "".join(character for character in text if 0x20 < ord(character) < 0x7F)\n'
DECODE = 'return unquote(text.replace("\\\\", "/"), errors="replace").lower()'
PIECES = 'for piece in re.split(r"[/?#]", after, maxsplit=1)[0].split("@"):'
MEASURE = 'if measure and (len(rest) > 4 * most or len(query) > most or len(fragment) > most or any(len(piece) > most for piece in path.split("/"))):'
PRIVATE = '        found += [(NEEDS_YES, f"the address holds what looks like {kind}") for kind in sensitive(text)]\n'
UNSEEN = "if any(ord(character) < 0x20 for character in decoded) or hidden(decoded):"
ENDING = 'name = unquote(path, errors="replace").rsplit("/", 1)[-1].rstrip(". ").lower()'
PROGRAMS = "apk app appimage bat bin cmd deb dmg exe jar msi pkg ps1 rpm run scr sh vbs"
ENDINGS = (".localhost", ".local", ".localdomain", ".internal", ".intranet", ".lan", ".home", ".home.arpa", ".corp", ".private")
METHODS = '_READS, _SENDS, _REMOVES = ("GET", "HEAD"), ("POST", "PUT", "PATCH"), ("DELETE",)'
METHOD = 'method = "GET" if method is None else method.upper() if type(method) is str and method.isascii() else None'
DELETE = '        elif method in _REMOVES:\n            found.append((NEEDS_YES, "a DELETE request removes something"))\n'
SENDING = 'sending = method in _SENDS or _has_any(inputs.get(fields["body"])) or _has_any(inputs.get(fields["headers"]))'
CONTENT = '        return found + _content(inputs, skip=(fields["url"], fields["method"]))'
SITE_CHECK = 'if not _SITE.fullmatch(site) or len(site) > 253 or "." not in site or _is_number(site):'
SET_RULE = "web = rules.web(read=[DOCS, CODE], send=[API])"

MUTANTS = [
    # ---- reading the address ----
    ("address: odd characters in an address are let through", R, rep(ODD, "if found is None:")),
    ("address: a backslash in an address is let through", R, rep(ODD, "if found is None or any(not 0x20 < ord(character) < 0x7F for character in address):")),
    ("address: an address not written the plain way is read the loose way", R, rep("    found = _WEB_ADDRESS.fullmatch(address)\n", '    found = _WEB_ADDRESS.fullmatch(address) or _WEB_ADDRESS.fullmatch("https://" + address.rsplit("@", 1)[-1])\n')),
    ("address: what comes before an @ may be part of the site", R, rep(r"(\[[^\[\]/?#@]*\]|[^\[\]/?#@:]*)(:[^/?#@]*)?(/.*)?", r"(?:[^/?#@]*@)?(\[[^\[\]/?#@]*\]|[^\[\]/?#@:]*)(:[^/?#@]*)?(/.*)?")),
    ("address: a question mark may follow the site with no slash", R, rep(r'(:[^/?#@]*)?(/.*)?")', r'(:[^/?#@]*)?([/?#].*)?")')),
    ("address: any way of writing http is taken, ftp too", R, rep("([Hh][Tt][Tt][Pp][Ss]?)://", "([A-Za-z]+)://")),
    ("address: the site is not checked to be a plain name", R, rep("    if not _SITE.fullmatch(host) or len(host) > 253:", "    if len(host) > 253:")),
    ("address: a site name of any length is taken", R, rep("    if not _SITE.fullmatch(host) or len(host) > 253:", "    if not _SITE.fullmatch(host):")),
    ("address: a port over 65535 is taken", R, rep(PORT, "if port is not None and not _PORT.fullmatch(port):")),
    ("address: a port with a 0 in front is taken", R, rep('_PORT = re.compile(r":[1-9][0-9]{0,4}")', '_PORT = re.compile(r":[0-9]{1,5}")')),
    ("address: http counts as https", R, rep('secure = found.group(1).lower() == "https"', "secure = True")),
    ("address: HTTPS in capitals counts as http", R, rep('secure = found.group(1).lower() == "https"', 'secure = found.group(1) == "https"')),
    ("address: every port is the usual one", R, rep("port is None or int(port[1:]) == (443 if secure else 80)", "True")),
    ("address: 443 is the usual port for http too", R, rep("(443 if secure else 80)", "443")),
    ("address: the site is kept as written, capitals and all", R, rep("    host = found.group(2).lower()\n", "    host = found.group(2)\n")),
    ("address: what follows the site is dropped", R, rep('found.group(4) or "")', '"")')),
    ("address: an address that is not text is read as text", R, rep("    if type(address) is not str or not address:", "    address = address.decode() if type(address) is bytes else address\n    if type(address) is not str or not address:")),
    ("address: a numbered public address is judged like a name", R, rep(NUMBERED, "")),
    ("address: a numbered public address is refused", R, rep('return NEEDS_YES, "the address is a number, not the name of a site"', 'return NEVER, "the address is a number, not the name of a site"')),
    # ---- this machine and your own network ----
    ("home: an address on this machine only asks", R, rep("        return NEVER, _HOME\n", "        return NEEDS_YES, _HOME\n")),
    ("home: an address on this machine is not looked for", R, rep('    if _local(host) or _local(unquote(host, errors="replace")):\n        return NEVER, _HOME\n', "")),
    ("home: a hard-to-read address that may point home only asks", R, rep(UNSURE, "unsure = (NEEDS_YES, _UNSURE)")),
    ("home: every hard-to-read address is refused", R, rep(UNSURE, "unsure = (NEVER, _MAYBE_HOME)")),
    ("home: a coded site name is not decoded", R, rep('if _local(host) or _local(unquote(host, errors="replace")):', "if _local(host):")),
    ("home: a file address only asks", R, rep('return NEVER, "the address is a file on this machine"', 'return NEEDS_YES, "the address is a file on this machine"')),
    ("home: file is looked for in the address as written", R, rep('if plain.startswith("file:"):', 'if address.startswith("file:"):')),
    ("home: a name with no dot is taken for a public site", R, rep(NAMES, 'return name == "localhost" or name.endswith(_LOCAL_ENDINGS)')),
    ("home: no ending marks a name as home", R, rep(NAMES, 'return "." not in name or name == "localhost"')),
    ("home: a dot at the end hides home", R, rep('    name = host[:-1] if host.endswith(".") else host\n', "    name = host\n")),
    ("home: a numbered address that cannot be read is taken as public", R, rep(UNREAD_FOUR, 'return address is not None and not _public(address)\n    return "." not in name')),
    ("home: a long-form address that cannot be read is taken as public", R, rep(UNREAD_SIX, "return address is not None and not _public(address)\n    name = host")),
    ("home: a bracket left open is taken as public", R, rep('address = _six(host[1:-1]) if host.endswith("]") else None', "address = _six(host[1:-1]) or ipaddress.IPv6Address('2606:4700::1')")),
    ("home: private networks count as public", R, rep("return address.is_global and not address.is_multicast", "return not address.is_loopback")),
    ("home: only private networks count as home, not what is merely not public", R, rep("return address.is_global and not address.is_multicast", "return not address.is_private")),
    ("home: addresses for a group of machines count as public", R, rep("return address.is_global and not address.is_multicast", "return address.is_global")),
    ("home: a number is only one written with digits and dots", R, rep('bool(_NUMBER_LABEL.fullmatch(host.rstrip(".").rsplit(".", 1)[-1]))', 'bool(re.fullmatch(r"[0-9.]+", host))')),
    ("home: a number in base 16 is not a number", R, rep('_NUMBER_LABEL = re.compile(r"[0-9]+|0x[0-9a-f]*")', '_NUMBER_LABEL = re.compile(r"[0-9]+")')),
    ("number: a 0 in front is read as base 10", R, rep('return int(text, 8) if re.fullmatch(r"[0-7]+", text) else None', 'return int(text) if re.fullmatch(r"[0-9]+", text) else None')),
    ("number: 0x is read as nothing", R, rep('return int(text[2:] or "0", 16) if re.fullmatch(r"[0-9a-f]*", text[2:]) else None', "return 0")),
    ("number: 0x alone cannot be read", R, rep('return int(text[2:] or "0", 16) if re.fullmatch(r"[0-9a-f]*", text[2:]) else None', 'return int(text[2:], 16) if re.fullmatch(r"[0-9a-f]+", text[2:]) else None')),
    ("number: the short forms are not filled out", R, rep("numbers[-1] >= 256 ** (5 - len(numbers))", "numbers[-1] > 255")),
    ("number: the last piece may be as big as it likes", R, rep(" or numbers[-1] >= 256 ** (5 - len(numbers)):", " or numbers[-1] >= 256**4:")),
    ("number: five pieces are read", R, rep("if len(numbers) > 4 or None in numbers:", "if len(numbers) > 5 or None in numbers:")),
    ("number: a very long piece is read", R, rep("    if len(text) > 20:\n        return None\n", "")),
    ("six: the short address inside a long one is not looked at", R, rep("inside = address.ipv4_mapped or address.sixtofour", "inside = None")),
    ("six: a 6to4 address is not looked inside", R, rep("inside = address.ipv4_mapped or address.sixtofour", "inside = address.ipv4_mapped")),
    ("six: an address that ends in a short one is not looked inside", R, rep(INSIDE, "if False:")),
    ("six: only ::a.b.c.d is looked inside, not 64:ff9b::", R, rep(INSIDE, "if inside is None and int(address) >> 32 == 0:")),
    ("six: every long address is read by its last four pieces", R, rep(INSIDE, "if inside is None:")),
    ("six: the zone after % is kept", R, rep('ipaddress.IPv6Address(text.partition("%")[0])', "ipaddress.IPv6Address(text)")),
    # ---- the loose reading ----
    ("plain: wide and circled letters are not made plain", R, rep('unicodedata.normalize("NFKC", address)', "address")),
    ("plain: the wide full stop is not a dot", R, rep('.replace("。", ".")', "")),
    ("plain: spaces and unseen characters are kept", R, rep(KEPT, "")),
    ("plain: a backslash is not read as a slash", R, rep(DECODE, 'return unquote(text, errors="replace").lower()')),
    ("plain: coded letters are not decoded", R, rep(DECODE, 'return text.replace("\\\\", "/").lower()')),
    ("plain: capitals are kept", R, rep(DECODE, 'return unquote(text.replace("\\\\", "/"), errors="replace")')),
    ("loose: only what follows the last @ is looked at", R, rep(PIECES, PIECES[:-1] + "[-1:]:")),
    ("loose: only what comes before the first @ is looked at", R, rep(PIECES, PIECES[:-1] + "[:1]:")),
    ("loose: the port is not cut off", R, rep('hosts += [piece, piece.rsplit(":", 1)[0]]', "hosts += [piece]")),
    ("loose: only the part before the port is looked at", R, rep('hosts += [piece, piece.rsplit(":", 1)[0]]', 'hosts += [piece.rsplit(":", 1)[0]]')),
    ("loose: http: at the front is taken for a site", R, rep('after = re.sub(r"^(?:[a-z][a-z0-9+.-]*:/+|/+)", "", plain)', "after = plain")),
    ("loose: slashes at the front are not cut off", R, rep('after = re.sub(r"^(?:[a-z][a-z0-9+.-]*:/+|/+)", "", plain)', 'after = re.sub(r"^[a-z][a-z0-9+.-]*://", "", plain)')),
    ("loose: the path is looked at for sites too", R, rep('re.split(r"[/?#]", after, maxsplit=1)[0].split("@")', 're.split(r"[/?#@]", after)')),
    ("loose: a question mark does not end the site", R, rep('re.split(r"[/?#]", after, maxsplit=1)', 're.split(r"[/#]", after, maxsplit=1)')),
    ("loose: a hash does not end the site", R, rep('re.split(r"[/?#]", after, maxsplit=1)', 're.split(r"[/?]", after, maxsplit=1)')),
    # ---- what the address carries ----
    ("carried: a long query runs", R, rep(" or len(query) > most", "")),
    ("carried: a long piece after the # runs", R, rep(" or len(fragment) > most", "")),
    ("carried: a long piece of the path runs", R, rep(' or any(len(piece) > most for piece in path.split("/"))', "")),
    ("carried: the whole of what follows the site is not measured", R, rep("len(rest) > 4 * most or ", "")),
    ("carried: the whole may be eight times the limit", R, rep("len(rest) > 4 * most", "len(rest) > 8 * most")),
    ("carried: the whole may be one longer", R, rep("len(rest) > 4 * most", "len(rest) >= 4 * most + 2")),
    ("carried: a query may be one longer", R, rep("len(query) > most", "len(query) > most + 1")),
    ("carried: a query at the limit asks", R, rep("len(query) > most", "len(query) >= most")),
    ("carried: a piece after the # may be one longer", R, rep("len(fragment) > most", "len(fragment) > most + 1")),
    ("carried: a piece of the path may be one longer", R, rep("any(len(piece) > most", "any(len(piece) > most + 1")),
    ("carried: a piece of the path at the limit asks", R, rep("any(len(piece) > most", "any(len(piece) >= most")),
    ("carried: the path is measured whole, not piece by piece", R, rep('any(len(piece) > most for piece in path.split("/"))', "len(path) > most")),
    ("carried: the # is measured as part of the query", R, rep('    before, _, fragment = rest.partition("#")\n', '    before, fragment = rest, ""\n')),
    ("carried: a site you send to is measured too", R, rep("measure=place.site not in self._send", "measure=True")),
    ("carried: no address is measured", R, rep("measure=place.site not in self._send", "measure=False")),
    ("carried: a site you read is not measured", R, rep("measure=place.site not in self._send", "measure=place.site not in self._read")),
    ("carried: the address is not looked at for private data", R, rep(PRIVATE, "        pass\n")),
    ("carried: only the address as written is looked at for private data", R, rep("for text in (rest, decoded):", "for text in (rest,):")),
    ("carried: coded line breaks are let through", R, rep(UNSEEN, "if hidden(decoded):")),
    ("carried: coded unseen characters are let through", R, rep(UNSEEN, "if any(ord(character) < 0x20 for character in decoded):")),
    ("carried: a program ending is let through", R, rep('if "." in name and name.rsplit(".", 1)[1] in _PROGRAMS:', "if False:")),
    ("carried: a word that is an ending asks with no dot", R, rep('if "." in name and name.rsplit(".", 1)[1] in _PROGRAMS:', 'if name.rsplit(".", 1)[-1] in _PROGRAMS:')),
    ("carried: an ending anywhere in the name asks", R, rep('if "." in name and name.rsplit(".", 1)[1] in _PROGRAMS:', 'if set(name.split(".")[1:]) & _PROGRAMS:')),
    ("carried: an ending is read without decoding", R, rep(ENDING, 'name = path.rsplit("/", 1)[-1].rstrip(". ").lower()')),
    ("carried: capitals hide an ending", R, rep(ENDING, 'name = unquote(path, errors="replace").rsplit("/", 1)[-1].rstrip(". ")')),
    ("carried: a dot at the end hides an ending", R, rep(ENDING, 'name = unquote(path, errors="replace").rsplit("/", 1)[-1].rstrip(" ").lower()')),
    ("carried: a space at the end hides an ending", R, rep(ENDING, 'name = unquote(path, errors="replace").rsplit("/", 1)[-1].rstrip(".").lower()')),
    ("carried: a query hides an ending", R, rep(ENDING, ENDING.replace("unquote(path,", "unquote(rest,"))),
    ("carried: an ending is looked for in every folder of the path", R, rep(ENDING, ENDING.replace('.rsplit("/", 1)[-1]', '.split("/")[1]'))),
    # ---- reading or sending ----
    ("method: an unknown method is taken as a read", R, rep("        if method not in _READS + _SENDS + _REMOVES:", "        if False:")),
    ("method: an unknown method is not said", R, rep('            found.append((NEEDS_YES, "the method is not GET, HEAD, POST, PUT, PATCH or DELETE"))\n', '            found.append((NEEDS_YES, "the method is unusual"))\n')),
    ("method: DELETE counts as a send", R, rep(DELETE, "        elif method in _REMOVES:\n            sending = True\n")),
    ("method: DELETE counts as a read", R, rep(DELETE, "        elif method in _REMOVES:\n            pass\n")),
    ("method: POST counts as a read", R, rep(METHODS, '_READS, _SENDS, _REMOVES = ("GET", "HEAD", "POST"), ("PUT", "PATCH"), ("DELETE",)')),
    ("method: PUT counts as a read", R, rep(METHODS, '_READS, _SENDS, _REMOVES = ("GET", "HEAD", "PUT"), ("POST", "PATCH"), ("DELETE",)')),
    ("method: PATCH counts as a read", R, rep(METHODS, '_READS, _SENDS, _REMOVES = ("GET", "HEAD", "PATCH"), ("POST", "PUT"), ("DELETE",)')),
    ("method: OPTIONS and TRACE count as reads", R, rep(METHODS, '_READS, _SENDS, _REMOVES = ("GET", "HEAD", "OPTIONS", "TRACE"), ("POST", "PUT", "PATCH"), ("DELETE",)')),
    ("method: HEAD is unknown", R, rep(METHODS, '_READS, _SENDS, _REMOVES = ("GET",), ("POST", "PUT", "PATCH"), ("DELETE",)')),
    ("method: letters that only look like POST are made into POST", R, rep(METHOD, 'method = "GET" if method is None else method.upper() if type(method) is str else None')),
    ("method: spaces around a method are trimmed", R, rep(METHOD, METHOD.replace("method.upper()", "method.strip().upper()"))),
    ("method: only the first word of a method is read", R, rep(METHOD, METHOD.replace("method.upper()", "(method.split() or [''])[0].upper()"))),
    ("method: small letters are unknown", R, rep(METHOD, METHOD.replace("method.upper()", "method"))),
    ("method: an empty method is GET", R, rep(METHOD, METHOD.replace("if method is None", "if not method"))),
    ("method: a missing method is unknown", R, rep(METHOD, METHOD.replace('"GET" if method is None else ', ""))),
    ("send: a body does not make a read into a send", R, rep(SENDING, 'sending = method in _SENDS or _has_any(inputs.get(fields["headers"]))')),
    ("send: headers do not make a read into a send", R, rep(SENDING, 'sending = method in _SENDS or _has_any(inputs.get(fields["body"]))')),
    ("send: POST with nothing in it is a read", R, rep(SENDING, 'sending = _has_any(inputs.get(fields["body"])) or _has_any(inputs.get(fields["headers"]))')),
    ("send: every request is a send", R, rep(SENDING, "sending = True")),
    ("send: a send is checked against the read list", R, rep("allowed = self._send if sending else self._read", "allowed = self._read")),
    ("send: a read is checked against the send list", R, rep("allowed = self._send if sending else self._read", "allowed = self._send")),
    ("send: a site you send to may not be read", R, rep('object.__setattr__(self, "_read", read | send)', 'object.__setattr__(self, "_read", read)')),
    ("send: a site you read may be sent to", R, rep('object.__setattr__(self, "_send", send)', 'object.__setattr__(self, "_send", read | send)')),
    # ---- which site ----
    ("site: a site that is not on the list runs", R, rep("            if place.site not in allowed:\n", "            if False:\n")),
    ("site: a site is matched by how its name ends", R, rep("            if place.site not in allowed:\n", "            if not any(place.site.endswith(known) for known in allowed):\n")),
    ("site: a site is matched by how its name starts", R, rep("            if place.site not in allowed:\n", "            if not any(place.site.startswith(known) for known in allowed):\n")),
    ("site: http runs", R, rep("            if not place.secure:\n", "            if False:\n")),
    ("site: an unusual port runs", R, rep("            if not place.usual_port:\n", "            if False:\n")),
    ("site: a look-alike is not pointed out", R, rep('return reason if alike is None else f"{reason}, and it looks like {alike}, which is"', "return reason")),
    ("site: only a swapped letter is pointed out, not a name inside a longer one", R, rep("if _mistaken(site, known) or known in site), None)", "if _mistaken(site, known)), None)")),
    ("site: only a name inside a longer one is pointed out", R, rep("if _mistaken(site, known) or known in site), None)", "if known in site), None)")),
    ("site: a site you read but may not send to is called a stranger", R, rep("        if sending and site in self._read:\n", "        if False:\n")),
    ("site: a stranger read is said to be a send", R, rep("{'sending to' if sending else 'reading'}", "{'sending to'}")),
    ("site: a long site name is written out in full", R, rep('reason = f"{_shown_address(site)} is not one of the sites', 'reason = f"{site} is not one of the sites')),
    # ---- what is sent, and inputs the rule does not know ----
    ("content: what is sent is not looked at", R, rep(CONTENT, "        return found")),
    ("content: the address is looked at again as what is sent", R, rep(CONTENT, '        return found + _content(inputs, skip=(fields["method"],))')),
    ("content: the headers are not looked at", R, rep(CONTENT, '        return found + _content(inputs, skip=(fields["url"], fields["method"], fields["headers"]))')),
    ("content: the body is not looked at", R, rep(CONTENT, '        return found + _content(inputs, skip=(fields["url"], fields["method"], fields["body"]))')),
    ("untold: an input the rule was not told about is let through", R, rep("        if untold:\n", "        if False:\n")),
    ("untold: the inputs it was not told about are counted wrongly", R, rep("untold = len(set(inputs) - set(fields.values()))", "untold = min(1, len(set(inputs) - set(fields.values())))")),
    ("fine: the wrong words are given when a request runs", R, rep('_fine = "the site is one you allow for this, and nothing unusual was found"', '_fine = "nothing unusual was found"')),
    # ---- setting it up ----
    ("setup: text is taken as a list", R, rep("    if type(values) not in (list, tuple, set, frozenset):\n", "    if False:\n")),
    ("setup: a dict is taken as a list", R, rep("(list, tuple, set, frozenset):", "(list, tuple, set, frozenset, dict):")),
    ("setup: a tuple is not taken as a list", R, rep("    if type(values) not in (list, tuple, set, frozenset):", "    if type(values) not in (list, set, frozenset):")),
    ("setup: a name on this machine can be listed", R, rep("        if _local(site):\n", "        if False:\n")),
    ("setup: a numbered address can be listed", R, rep(SITE_CHECK, 'if not _SITE.fullmatch(site) or len(site) > 253 or "." not in site:')),
    ("setup: a name with no dot is said to be home, not refused as no site", R, rep(SITE_CHECK, "if not _SITE.fullmatch(site) or len(site) > 253 or _is_number(site):")),
    ("setup: what is listed is not checked to be a name", R, rep(SITE_CHECK, 'if len(site) > 253 or "." not in site or _is_number(site):')),
    ("setup: a name of any length can be listed", R, rep(SITE_CHECK, 'if not _SITE.fullmatch(site) or "." not in site or _is_number(site):')),
    ("setup: a listed name keeps its capitals", R, rep('site = value.strip(" ").lower() if type(value) is str else ""', 'site = value.strip(" ") if type(value) is str else ""')),
    ("setup: spaces round a listed name are kept", R, rep('site = value.strip(" ").lower() if type(value) is str else ""', 'site = value.lower() if type(value) is str else ""')),
    ("setup: bytes can be listed", R, rep('site = value.strip(" ").lower() if type(value) is str else ""', 'site = (value.decode() if type(value) is bytes else value).strip(" ").lower() if type(value) in (str, bytes) else ""')),
    ("setup: max_data can be anything", R, rep("    if type(max_data) is not int or not 8 <= max_data <= 2000:\n", "    if False:\n")),
    ("setup: max_data can be as small as you like", R, rep("not 8 <= max_data <= 2000", "not max_data <= 2000")),
    ("setup: max_data can be 7", R, rep("not 8 <= max_data <= 2000", "not 7 <= max_data <= 2000")),
    ("setup: max_data cannot be 8", R, rep("not 8 <= max_data <= 2000", "not 8 < max_data <= 2000")),
    ("setup: max_data can be as large as you like", R, rep("not 8 <= max_data <= 2000", "not 8 <= max_data")),
    ("setup: max_data cannot be 2000", R, rep("not 8 <= max_data <= 2000", "not 8 <= max_data < 2000")),
    ("setup: max_data given as text is taken", R, rep("    if type(max_data) is not int or not 8 <= max_data <= 2000:", "    max_data = int(max_data) if type(max_data) in (str, float) else max_data\n    if type(max_data) is not int or not 8 <= max_data <= 2000:")),
    ("setup: max_data is not used", R, rep("    return _Web(read, send, max_data, fields)", "    return _Web(read, send, 80, fields)")),
    ("setup: the send list is used for reading only", R, rep("    return _Web(read, send, max_data, fields)", "    return _Web(read | send, frozenset(), max_data, fields)")),
    ("setup: the other names for the inputs are not used", R, rep("fields = _fields(url=url, method=method, body=body, headers=headers)", 'fields = _fields(url="url", method="method", body="body", headers="headers")')),
    ("setup: max_data is left out of the rule's settings", R, rep('"send": sorted(send), "max_data": most, "fields": fields}', '"send": sorted(send), "fields": fields}')),
    ("setup: the send list is left out of the rule's settings", R, rep('{"read": sorted(read), "send": sorted(send), "max_data": most', '{"read": sorted(read), "send": [], "max_data": most')),
    ("setup: the lists are kept in the order given", R, rep('{"read": sorted(read), "send": sorted(send)', '{"read": list(read), "send": list(send)')),
    ("setup: the web rule goes by another kind", R, rep('    kind = "web"\n', '    kind = "email"\n')),
    ("setup: web is not one of the names the module gives out", R, rep('"payment", "web", "shell"', '"payment", "shell"')),
    # ---- the rules set's web cases ----
    ("set: the thief's site is on the set's read list", S, rep(SET_RULE, "web = rules.web(read=[DOCS, CODE, THIEF_SITE], send=[API])")),
    ("set: the thief's site is on the set's send list", S, rep(SET_RULE, "web = rules.web(read=[DOCS, CODE], send=[API, THIEF_SITE])")),
    ("set: the set's read sites can all be sent to", S, rep(SET_RULE, "web = rules.web(send=[DOCS, CODE, API])")),
    ("set: the set's web rule has no lists", S, rep(SET_RULE, "web = rules.web()")),
    ("set: the set's web rule lets longer addresses run", S, rep(SET_RULE, "web = rules.web(read=[DOCS, CODE], send=[API], max_data=2000)")),
    ("set: the fetch tool runs without the rule", S, rep('checkpoint.tool("fetch", desk.fetch, level=web, describe=web.why, watch=["url"])', 'checkpoint.tool("fetch", desk.fetch, level="free")')),
    ("set: a fetch is not counted as the desk acting", S, rep("return len(self.sent) + len(self.paid) + len(self.fetched)", "return len(self.sent) + len(self.paid)")),
    ("set: the fetch tool does nothing", S, rep('        self.fetched.append({"url": url, "method": method})\n', "")),
    ("set: a web case is taken out", S, without_line('RulesCase("web-localhost", WEB,')),
    ("set: a normal web job is taken out", S, without_line('RulesCase("normal-web-read", NORMAL,')),
    ("set: a web trick is expected to run", S, rep('_get(f"https://{THIEF_SITE}/"), ASKS)', '_get(f"https://{THIEF_SITE}/"), RUNS)')),
    ("set: a refused address is expected to ask", S, rep('_get("http://localhost:8080/admin"), NEVER)', '_get("http://localhost:8080/admin"), ASKS)')),
    ("set: the page the set reads is on another site", S, rep('def _get(address=f"https://{DOCS}/guide/rooms.html"', 'def _get(address=f"https://{THIEF_SITE}/guide/rooms.html"')),
]

MUTANTS += [(f"home: a name ending {ending} is taken for a public site", R, rep(f'"{ending}", ', "") if ending != ".private" else rep(', ".private")', ")")) for ending in ENDINGS]
MUTANTS += [(f"carried: a .{ending} file is not taken for a program", R, rep(f'"{PROGRAMS}"', '"' + " ".join(word for word in PROGRAMS.split() if word != ending) + '"')) for ending in PROGRAMS.split()]

KNOWN = {}

if __name__ == "__main__":
    run(MUTANTS, TESTS, expected_to_survive=KNOWN)
