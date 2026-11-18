"""Break the ready-made rule for file tools one way at a time, and see whether its tests notice.

    .venv/bin/python checks/break_files.py            every break (a few minutes)
    .venv/bin/python checks/break_files.py link       only the breaks with "link" in their name
    .venv/bin/python checks/break_files.py --dry      apply every break and check it is still Python; run no tests

The files rule lets a file tool act without asking when the path really leads
into a folder the owner allows, and never lets one change keys, a system folder
or a path the owner protects, or delete the home folder. So the breaks that
matter most here each let one more path through, or turn a refusal into an ask:
a link that is not followed, a .. that is tidied away before the link is, a
folder whose name only starts the same, a key place that is not known, a
protected file reached in other capitals. Others make the rule say the wrong
reason or take a wrong setting, and the last group breaks the rules set's own
file cases.

Each break changes one place. A break whose words are found more than once, or
not at all, is reported as not applied. Breaks of the rule look only at the
part of rules.py from the line "# ---- files" to the line "# ---- calendar",
so the same words in another rule do not get in the way.

Only tests/test_files_rule.py and tests/test_rules_set.py are run.
"""

import re
import sys

from _runner import ROOT, run

TESTS = ["test_files_rule.py", "test_rules_set.py"]

R, S = "rules.py", "attacktest/rules_set.py"
START, END = "\n# ---- files -", "\n# ---- calendar -"


def one(old, new):
    """Replace `old`, which must be in the file exactly once."""
    return lambda text: text.replace(old, new) if text.count(old) == 1 else text


def f(old, new):
    """Replace `old`, which must be exactly once in the files part of rules.py."""

    def change(text):
        at = text.find(START)
        if at < 0 or text.count(START) != 1:
            return text
        stop = text.find(END, at)
        stop = len(text) if stop < 0 else stop
        head, part, tail = text[:at], text[at:stop], text[stop:]
        return head + part.replace(old, new) + tail if part.count(old) == 1 else text

    return change


def _named(text, name):
    """Where the lines that set `name` start and stop."""
    start = text.find(f"\n{name} = ")
    if start < 0:
        return 0, 0
    stop = text.find("\n", start + 1)
    return start, text.find("\n)", stop) if text[start:stop].endswith("(") else stop


def drop(name, word):
    """Take one word out of the set of words called `name`, where the words are written as one text."""

    def change(text):
        start, stop = _named(text, name)

        def fix(found):
            words = found.group(1).split(" ")
            return '"' + " ".join(kept for kept in words if kept != word) + '"' if word in words else found.group(0)

        return text[:start] + re.sub(r'"([^"\n]*)"', fix, text[start:stop]) + text[stop:]

    return change


def item(name, word):
    """Take one text out of the list called `name`, where each is written in its own quotes."""

    def change(text):
        start, stop = _named(text, name)
        return text[:start] + re.sub(rf'"{re.escape(word)}",? ?', "", text[start:stop], count=1) + text[stop:]

    return change


SYSTEM_FOLDERS = "bin boot dev etc lib lib32 lib64 library proc root sbin sys system usr".split()
KEY_PIECES = ".ssh .aws .gnupg .kube .netrc .npmrc .pypirc .git-credentials .htpasswd .env .envrc id_rsa id_dsa id_ecdsa id_ed25519 keychains".split()
KEY_PAIRS = [(".docker", "config.json"), (".config", "gh"), (".config", "gcloud"), ("etc", "shadow"), ("etc", "sudoers"), ("etc", "master.passwd")]
KEY_STEMS = "credentials password passwords secret secrets".split()
KEY_ENDINGS = [".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".kdbx", ".ppk"]
EXAMPLE_ENDINGS = [".example", ".sample", ".template", ".dist"]
OBEYED_FOLDERS = ".git .github .husky .vscode .claude .cursor .devcontainer launchagents launchdaemons".split()
OBEYED_FILES = ".zshrc .zshenv .zprofile .zlogin .bashrc .bash_profile .bash_login .profile .gitconfig".split()
REASONS = "FINE UNREAD UNSEEN NOT_PLAIN PATTERN RELATIVE OUTSIDE LINK READ_ONLY KEYS PROTECTED SYSTEM WHOLE RUNS_ITSELF FOLDER MANY".split()

MUTANTS = [
    # ---- where a path leads ----
    ("link: links are not followed at all", R, f("real, tidy = _real(whole), _tidy(whole)", "real, tidy = _tidy(whole), _tidy(whole)")),
    ("link: the path is tidied before links are followed, so a/link/.. is taken for a", R, f("real, tidy = _real(whole), _tidy(whole)", "real, tidy = _real(_tidy(whole)), _tidy(whole)")),
    ("link: the owner's folders are not followed to where they lead", R, f("([_real(place) for place in places] for places in", "(list(places) for places in")),
    ("link: a home folder named through a link is not followed", R, f("home = _real(self._home)\n", "home = self._home\n")),
    ("link: two slashes at the start of the real path are kept", R, f('    return re.sub(r"^/+", "/", os.path.realpath(path))', "    return os.path.realpath(path)")),
    ("link: two slashes at the start of the tidy path are kept", R, f('    return re.sub(r"^/+", "/", os.path.normpath(path))', "    return os.path.normpath(path)")),
    ("link: a path that cannot be worked out stops the rule", R, f("except (OSError, ValueError):", "except OSError:")),
    ("inside: a folder whose name starts the same counts as inside", R, f('path.startswith(root.rstrip("/") + "/")', 'path.startswith(root.rstrip("/"))')),
    ("inside: the folder itself is not inside", R, f("path == root or path.startswith", "path.startswith")),
    ("inside: only the folder itself is inside", R, f('path == root or path.startswith(root.rstrip("/") + "/")', "path == root")),
    ("inside: a root that ends in a slash covers nothing", R, f('root.rstrip("/") + "/"', 'root + "/"')),
    ("inside: a folder in other capitals is taken for the owner's", R, f("inside = _under(real, folders, exact=True)", "inside = _under(real, folders)")),
    ("inside: a folder for reading in other capitals is taken for the owner's", R, f("_under(real, read_only, exact=True))\n", "_under(real, read_only))\n")),
    ("inside: capitals are never passed over", R, f("    if not exact:\n", "    if False:\n")),
    ("inside: capitals are told apart when a path is compared", R, f('unicodedata.normalize("NFC", path).casefold()', 'unicodedata.normalize("NFC", path)')),
    ("inside: accents written two ways are told apart", R, f('unicodedata.normalize("NFC", path).casefold()', "path.casefold()")),
    ("inside: everything is inside", R, f("        inside = _under(real, folders, exact=True)\n", "        inside = True\n")),
    ("inside: nothing is inside", R, f("        inside = _under(real, folders, exact=True)\n", "        inside = False\n")),
    ("read only: a change is allowed there too", R, f("inside or (not changes and _under(real, read_only, exact=True))", "inside or _under(real, read_only, exact=True)")),
    ("read only: reading is not allowed there", R, f("        allowed = inside or (not changes and _under(real, read_only, exact=True))\n", "        allowed = inside\n")),
    ("read only: a delete is not a change", R, f('changes = self._does != "read"', 'changes = self._does == "write"')),
    ("read only: a write is not a change", R, f('changes = self._does != "read"', 'changes = self._does == "delete"')),
    ("read only: a read is a change", R, f('changes = self._does != "read"', "changes = True")),
    ("outside: a path outside is free", R, f("        if not allowed:\n", "        if False:\n")),
    ("outside: a link out is said to be outside", R, f("                found.append((NEEDS_YES, _F_LINK))\n", "                found.append((NEEDS_YES, _F_OUTSIDE))\n")),
    ("outside: a change through the read-only folder is said to be a link", R, f("self._folders if changes else self._folders + self._read_only", "self._folders + self._read_only")),
    ("outside: a link out of the read-only folder is said to be outside", R, f("self._folders if changes else self._folders + self._read_only", "self._folders")),
    ("outside: a change in the read-only folder is said to be outside", R, f("            elif _under(real, read_only, exact=True):\n", "            elif False:\n")),
    # ---- how a path is written ----
    ("written: ~ alone is not the home folder", R, f('if text == "~" or text.startswith("~/"):', 'if text.startswith("~/"):')),
    ("written: ~/ is not the home folder", R, f('if text == "~" or text.startswith("~/"):', 'if text == "~":')),
    ("written: a path from the top is not known", R, f('return text if text.startswith("/") else None', "return None")),
    ("written: any path is taken as starting from the top", R, f('return text if text.startswith("/") else None', "return text")),
    ("written: a path with no start is free when no starting folder was given", R, f("            return found + [(NEEDS_YES, _F_RELATIVE)]\n", "            return found\n")),
    ("written: the starting folder is not used", R, f('if whole is None and self._base is not None and not text.startswith("~"):', "if False:")),
    ("written: ~name is put under the starting folder", R, f(' and not text.startswith("~"):\n', ":\n")),
    ("written: the starting folder is glued on with no slash", R, f('whole = self._base + "/" + text', "whole = self._base + text")),
    ("written: a line break or a tab in a path is free", R, f("        if any(ord(character) < 0x20 for character in text) or hidden(text):\n", "        if hidden(text):\n")),
    ("written: a character that cannot be seen in a path is free", R, f("        if any(ord(character) < 0x20 for character in text) or hidden(text):\n", "        if any(ord(character) < 0x20 for character in text):\n")),
    ("written: an unseen character is not said", R, f("            found.append((NEEDS_YES, _F_UNSEEN))\n", "            pass\n")),
    ("written: a path that is not plain is free", R, f("        if _NOT_PLAIN.search(text):\n", "        if False:\n")),
    ("written: a $ in a path is plain", R, f('re.compile(r"[$\\\\`]|', 're.compile(r"[\\\\`]|')),
    ("written: a backslash in a path is plain", R, f('re.compile(r"[$\\\\`]|', 're.compile(r"[$`]|')),
    ("written: a backtick in a path is plain", R, f('re.compile(r"[$\\\\`]|', 're.compile(r"[$\\\\]|')),
    ("written: ~name is plain", R, f("|^~[^/]|", "|")),
    ("written: a drive letter is plain", R, f("|^[A-Za-z]:|", "|")),
    ("written: a blank at the start is plain", R, f("|^\\s|", "|")),
    ("written: a blank at the end is plain", R, f("|\\s$|", "|")),
    ("written: ..namedfork is plain", R, f("|(?i:\\.\\.namedfork)", "")),
    ("written: ..namedfork in other capitals is plain", R, f("|(?i:\\.\\.namedfork)", "|\\.\\.namedfork")),
    ("written: a pattern in a path is free", R, f('        if any(mark in text for mark in "*?["):\n', "        if False:\n")),
    ("written: * in a path is not a pattern", R, f('if any(mark in text for mark in "*?["):', 'if any(mark in text for mark in "?["):')),
    ("written: ? in a path is not a pattern", R, f('if any(mark in text for mark in "*?["):', 'if any(mark in text for mark in "*["):')),
    ("written: [ in a path is not a pattern", R, f('if any(mark in text for mark in "*?["):', 'if any(mark in text for mark in "*?"):')),
    # ---- the path input ----
    ("input: a path that is not text or a list crashes or runs", R, f("if type(paths) is not list or not paths or any(", "if not paths or any(")),
    ("input: a tuple of paths is read", R, f("if type(paths) is not list or", "if not isinstance(paths, (list, tuple)) or")),
    ("input: an empty list of paths is free", R, f("is not list or not paths or any(", "is not list or any(")),
    ("input: a path in a list that is not text is not looked at", R, f("any(type(path) is not str or not path for path in paths)", "any(type(path) is str and not path for path in paths)")),
    ("input: an empty path is judged", R, f("any(type(path) is not str or not path for path in paths)", "any(type(path) is not str for path in paths)")),
    ("input: a path that cannot be read is free", R, f("            return found + [(NEEDS_YES, _F_UNREAD)]\n        if self._does", "            return found\n        if self._does")),
    ("input: only the first path of a list is judged", R, f("        for path in paths:\n", "        for path in paths[:1]:\n")),
    ("input: only the last path of a list is judged", R, f("        for path in paths:\n", "        for path in paths[-1:]:\n")),
    ("input: an input the rule was not told about is free", R, f("        if untold:\n", "        if False:\n")),
    ("input: the count of untold inputs is one too many", R, f("untold = len(set(inputs) - known)", "untold = len(set(inputs) - known) + 1")),
    ("input: the content is known to a rule for reading too", R, f('if self._does == "write" else set())', "if True else set())")),
    ("input: the content is not known to a rule for writing", R, f('if self._does == "write" else set())', "if False else set())")),
    ("input: the inputs to pass over are not passed over", R, f(" else set()) | self._ignored\n", " else set())\n")),
    ("input: the path input is counted as untold", R, f('known = {self._fields["path"]} | (', "known = set() | (")),
    # ---- what is protected ----
    ("protect: a protected path is free", R, f("        if _under(real, protect) or _under(tidy, self._protect):\n", "        if False:\n")),
    ("protect: a protected path reached through a link is free", R, f("if _under(real, protect) or _under(tidy, self._protect):", "if _under(tidy, self._protect):")),
    ("protect: a path that is the protected one before links are followed is free", R, f("if _under(real, protect) or _under(tidy, self._protect):", "if _under(real, protect):")),
    ("protect: a change to a protected path only asks", R, f("found.append((NEVER if changes else NEEDS_YES, _F_PROTECTED))", "found.append((NEEDS_YES, _F_PROTECTED))")),
    ("protect: a read of a protected path is refused", R, f("found.append((NEVER if changes else NEEDS_YES, _F_PROTECTED))", "found.append((NEVER, _F_PROTECTED))")),
    ("protect: the protect list may not hold the home folder", R, f('guarded = _place_list(protect, "protect", home, whole_allowed=True)', 'guarded = _place_list(protect, "protect", home)')),
    ("protect: the protect list is not kept", R, f("return _Files(does, kept, reads, guarded, start,", "return _Files(does, kept, reads, (), start,")),
    # ---- the whole machine ----
    ("whole: deleting the home folder or a top folder only asks", R, f('        if self._does == "delete" and (_whole_place(real, home) or _whole_place(tidy, self._home)):\n', "        if False:\n")),
    ("whole: a write to the home folder is refused as a delete", R, f('if self._does == "delete" and (_whole_place(real, home)', "if changes and (_whole_place(real, home)")),
    ("whole: the home folder reached through a link may be deleted", R, f("(_whole_place(real, home) or _whole_place(tidy, self._home))", "(_whole_place(tidy, self._home))")),
    ("whole: a path that is the home folder before links are followed may be deleted", R, f("(_whole_place(real, home) or _whole_place(tidy, self._home))", "(_whole_place(real, home))")),
    ("whole: a top folder of the machine is not a whole place", R, f("return len(pieces) < 2 or (pieces[0]", "return len(pieces) < 1 or (pieces[0]")),
    ("whole: a folder two deep is a whole place", R, f("return len(pieces) < 2 or (pieces[0]", "return len(pieces) < 3 or (pieces[0]")),
    ("whole: a top folder under /private is not a whole place", R, f(' or (pieces[0] == "private" and len(pieces) == 2) or ', " or ")),
    ("whole: everything under /private is a whole place", R, f('(pieces[0] == "private" and len(pieces) == 2)', '(pieces[0] == "private")')),
    ("whole: the home folder and the folders it is in are not whole places", R, f(" or _under(home, [path])\n", "\n")),
    ("whole: a folder inside the home folder is a whole place", R, f("or _under(home, [path])\n", "or _under(path, [home])\n")),
    # ---- system folders ----
    ("system: a change to a system folder only asks", R, f("        if changes and not inside and _system_place(real):\n", "        if False:\n")),
    ("system: a read of a system folder is refused", R, f("if changes and not inside and _system_place(real):", "if not inside and _system_place(real):")),
    ("system: the owner's own folder inside a system folder is refused", R, f("if changes and not inside and _system_place(real):", "if changes and _system_place(real):")),
    ("system: a system folder reached through a link is not seen", R, f("if changes and not inside and _system_place(real):", "if changes and not inside and _system_place(tidy):")),
    ("system: /private/etc is not a system folder", R, f(' or pieces[:2] == ["private", "etc"])', ")")),
    ("system: a system folder in capitals is not known", R, f('[piece for piece in path.lower().split("/") if piece]', '[piece for piece in path.split("/") if piece]')),
    ("system: a system folder is known anywhere in a path", R, f("(pieces[0] in _SYSTEM_FOLDERS or", "(any(piece in _SYSTEM_FOLDERS for piece in pieces) or")),
    # ---- where keys are kept ----
    ("keys: a key place is free", R, f("        if _key_place(real) or _key_place(tidy):\n", "        if False:\n")),
    ("keys: a key place reached through a link is not seen", R, f("if _key_place(real) or _key_place(tidy):", "if _key_place(tidy):")),
    ("keys: a link with the name of a key file is not seen", R, f("if _key_place(real) or _key_place(tidy):", "if _key_place(real):")),
    ("keys: a change to a key place outside only asks", R, f("found.append((NEVER if changes and not inside else NEEDS_YES, _F_KEYS))", "found.append((NEEDS_YES, _F_KEYS))")),
    ("keys: a change to a key place inside is refused", R, f("found.append((NEVER if changes and not inside else NEEDS_YES, _F_KEYS))", "found.append((NEVER if changes else NEEDS_YES, _F_KEYS))")),
    ("keys: a read of a key place outside is refused", R, f("found.append((NEVER if changes and not inside else NEEDS_YES, _F_KEYS))", "found.append((NEVER if not inside else NEEDS_YES, _F_KEYS))")),
    ("keys: only the last name of a path is looked at", R, f("return any(_key_name(piece) for piece in pieces) or any(pair", "return any(_key_name(piece) for piece in pieces[-1:]) or any(pair")),
    ("keys: the last name of a path is not looked at", R, f("return any(_key_name(piece) for piece in pieces) or any(pair", "return any(_key_name(piece) for piece in pieces[:-1]) or any(pair")),
    ("keys: no name is known by itself", R, f("    if name in _KEY_PIECES:\n        return True\n", "")),
    ("keys: two names together are not known", R, f(" or any(pair in _KEY_PAIRS for pair in zip(pieces, pieces[1:]))", "")),
    ("keys: two names are known with a name between them", R, f("zip(pieces, pieces[1:])", "zip(pieces, pieces[2:])")),
    ("keys: an example of a key file is a key file", R, f("    if name.endswith(_EXAMPLE_ENDINGS):\n        return False\n", "")),
    ("keys: .env.local is not known", R, f('if name.startswith(".env.") or name.endswith(_SECRET_ENDINGS):', "if name.endswith(_SECRET_ENDINGS):")),
    ("keys: any name that starts .env is known", R, f('name.startswith(".env.")', 'name.startswith(".env")')),
    ("keys: no key file ending is known", R, f('if name.startswith(".env.") or name.endswith(_SECRET_ENDINGS):', 'if name.startswith(".env."):')),
    ("keys: a history file is not known", R, f('return (name.startswith(".") and name.endswith("_history")) or ', "return ")),
    ("keys: any name that ends _history is known", R, f('(name.startswith(".") and name.endswith("_history"))', 'name.endswith("_history")')),
    ("keys: any hidden file is taken for a history file", R, f('(name.startswith(".") and name.endswith("_history"))', 'name.startswith(".")')),
    ("keys: a file named for what it holds is not known", R, f(' or name.split(".")[0] in _KEY_STEMS\n', "\n")),
    ("keys: a name is known only when it is the whole name", R, f('name.split(".")[0] in _KEY_STEMS', "name in _KEY_STEMS")),
    ("keys: a name is known by its last part", R, f('name.split(".")[0] in _KEY_STEMS', 'name.split(".")[-1] in _KEY_STEMS')),
    # ---- files other tools obey ----
    ("obeyed: a change to a file other tools obey is free", R, f("        if changes and (_obeyed_place(real) or _obeyed_place(tidy)):\n", "        if False:\n")),
    ("obeyed: a read of a file other tools obey asks", R, f("if changes and (_obeyed_place(real) or _obeyed_place(tidy)):", "if _obeyed_place(real) or _obeyed_place(tidy):")),
    ("obeyed: an obeyed folder reached through a link is not seen", R, f("(_obeyed_place(real) or _obeyed_place(tidy))", "(_obeyed_place(tidy))")),
    ("obeyed: a link with the name of an obeyed folder is not seen", R, f("(_obeyed_place(real) or _obeyed_place(tidy))", "(_obeyed_place(real))")),
    ("obeyed: no folder is known", R, f("return any(piece in _OBEYED_FOLDERS for piece in pieces) or (", "return (")),
    ("obeyed: no file is known", R, f(" or (bool(pieces) and pieces[-1] in _OBEYED_FILES)", "")),
    ("obeyed: a folder with the name of an obeyed file counts", R, f("(bool(pieces) and pieces[-1] in _OBEYED_FILES)", "any(piece in _OBEYED_FILES for piece in pieces)")),
    ("obeyed: only the last name is looked at for a folder", R, f("any(piece in _OBEYED_FOLDERS for piece in pieces)", "any(piece in _OBEYED_FOLDERS for piece in pieces[-1:])")),
    # ---- deleting folders and many files ----
    ("folder: deleting a whole folder is free", R, f('        if self._does == "delete" and (text.endswith("/") or os.path.isdir(real)):\n', "        if False:\n")),
    ("folder: reading or writing a folder asks", R, f('if self._does == "delete" and (text.endswith("/") or os.path.isdir(real)):', 'if text.endswith("/") or os.path.isdir(real):')),
    ("folder: a path written as a folder is not taken for one", R, f('(text.endswith("/") or os.path.isdir(real))', "(os.path.isdir(real))")),
    ("folder: a folder on the disk is not seen", R, f('(text.endswith("/") or os.path.isdir(real))', '(text.endswith("/"))')),
    ("many: deleting many paths at once is free", R, f('        if self._does == "delete" and len(paths) > self._many:\n', "        if False:\n")),
    ("many: reading or writing many paths asks", R, f('if self._does == "delete" and len(paths) > self._many:', "if len(paths) > self._many:")),
    ("many: the limit itself asks", R, f("len(paths) > self._many:", "len(paths) >= self._many:")),
    ("many: one over the limit is free", R, f("len(paths) > self._many:", "len(paths) > self._many + 1:")),
    ("many: the reason gives a wrong number", R, f("_F_MANY.format(self._many)", "_F_MANY.format(len(paths))")),
    # ---- the owner's lists ----
    ("lists: no list given is an error", R, f("    if values is None:\n        return ()\n", "")),
    ("lists: one path given as text is taken letter by letter", R, f('    if type(values) not in (list, tuple):\n        raise RulesError(f"{name} must be a list of paths")\n', "")),
    ("lists: a set is taken", R, f("if type(values) not in (list, tuple):", "if type(values) not in (list, tuple, set):")),
    ("lists: a tuple is not taken", R, f("if type(values) not in (list, tuple):", "if type(values) is not list:")),
    ("lists: a path that is not text is taken", R, f("        if type(value) is not str or not value:\n", "        if type(value) is str and not value:\n")),
    ("lists: an empty path gets the wrong error", R, f("        if type(value) is not str or not value:\n", "        if type(value) is not str:\n")),
    ("lists: a path with an unseen character is taken", R, f("        if any(ord(character) in (9, 10, 13) for character in value) or hidden(value):\n", "        if False:\n")),
    ("lists: a path with a line break or a tab is taken", R, f("if any(ord(character) in (9, 10, 13) for character in value) or hidden(value):", "if hidden(value):")),
    ("lists: a path with a hidden character is taken", R, f(" in (9, 10, 13) for character in value) or hidden(value):", " in (9, 10, 13) for character in value):")),
    ("lists: a path that is not plain is taken", R, f('if _NOT_PLAIN.search(value) or any(mark in value for mark in "*?["):', 'if any(mark in value for mark in "*?["):')),
    ("lists: a path with a pattern is taken", R, f('if _NOT_PLAIN.search(value) or any(mark in value for mark in "*?["):', "if _NOT_PLAIN.search(value):")),
    ("lists: a path with a * is taken", R, f('any(mark in value for mark in "*?["):', 'any(mark in value for mark in "?["):')),
    ("lists: a path with a ? is taken", R, f('any(mark in value for mark in "*?["):', 'any(mark in value for mark in "*["):')),
    ("lists: a path with a [ is taken", R, f('any(mark in value for mark in "*?["):', 'any(mark in value for mark in "*?"):')),
    ("lists: a path with no start is taken", R, f('        if whole is None:\n            raise RulesError(f"{name}: {value!r} must start from / or ~")\n', '        if whole is None:\n            whole = "/" + value\n')),
    ("lists: the paths are not tidied", R, f("        whole = _tidy(whole)\n        if not whole_allowed", "        if not whole_allowed")),
    ("lists: the home folder and the system may be a folder to work in", R, f("        if not whole_allowed and (_whole_place(whole, home) or (_system_place(whole) and len(_pieces(whole)) < 3)):\n", "        if False:\n")),
    ("lists: nothing may be protected that is a whole place", R, f("if not whole_allowed and (_whole_place", "if (_whole_place")),
    ("lists: the home folder may be a folder to work in", R, f("(_whole_place(whole, home) or (_system_place(whole) and len(_pieces(whole)) < 3))", "((_system_place(whole) and len(_pieces(whole)) < 3))")),
    ("lists: a system folder may be a folder to work in", R, f("(_whole_place(whole, home) or (_system_place(whole) and len(_pieces(whole)) < 3))", "(_whole_place(whole, home))")),
    ("lists: a system folder two deep may be a folder to work in", R, f("len(_pieces(whole)) < 3))", "len(_pieces(whole)) < 2))")),
    ("lists: a system folder three deep may not be a folder to work in", R, f("len(_pieces(whole)) < 3))", "len(_pieces(whole)) < 4))")),
    ("lists: a path given twice is kept twice", R, f("        if whole not in kept:\n            kept.append(whole)\n", "        kept.append(whole)\n")),
    ("lists: only the first path of a list is kept", R, f("    return tuple(kept)\n", "    return tuple(kept[:1])\n")),
    # ---- making the rule ----
    ("setup: files is not one of the names the module gives out", R, one('"shell", "files", "calendar"', '"shell", "calendar"')),
    ("setup: the kind is wrong", R, f('    kind = "files"\n', '    kind = "file"\n')),
    ("setup: the fine reason is not given", R, f("    _fine = _F_FINE\n", "")),
    ("setup: does is not checked", R, f("    if does not in _DOES:\n        raise RulesError('does must be \"read\", \"write\" or \"delete\"')\n", "")),
    ("setup: a home folder that does not start from the top is taken", R, f('if type(home) is not str or not home.startswith("/") or _tidy(home) == "/":', 'if type(home) is not str or _tidy(home) == "/":')),
    ("setup: a home folder of / is taken", R, f('if type(home) is not str or not home.startswith("/") or _tidy(home) == "/":', 'if type(home) is not str or not home.startswith("/"):')),
    ("setup: the home folder is not tidied", R, f("    home = _tidy(home)\n", "")),
    ("setup: the home folder is read again each time", R, f("        whole = _whole_path(text, self._home)\n", '        whole = _whole_path(text, os.path.expanduser("~"))\n')),
    ("setup: the folders are not kept", R, f("return _Files(does, kept, reads,", "return _Files(does, (), reads,")),
    ("setup: the read-only folders are not kept", R, f("return _Files(does, kept, reads,", "return _Files(does, kept, (),")),
    ("setup: the read-only folders are kept as folders to work in", R, f("return _Files(does, kept, reads,", "return _Files(does, kept + reads, reads,")),
    ("setup: the starting folder is not kept", R, f("guarded, start, home, many,", "guarded, None, home, many,")),
    ("setup: the starting folder may not be the home folder or /", R, f('start = _place_list([base], "base", home, whole_allowed=True)[0]', 'start = _place_list([base], "base", home)[0]')),
    ("setup: a starting folder that is not text is taken", R, f('        if type(base) is not str:\n            raise RulesError("base must be one folder, as text")\n', "")),
    ("setup: many may be 0", R, f("if type(many) is not int or many < 1:", "if type(many) is not int or many < 0:")),
    ("setup: many may be a number that is not whole, or True", R, f("if type(many) is not int or many < 1:", "if not isinstance(many, (int, float)) or many < 1:")),
    ("setup: many is not checked", R, f('    if type(many) is not int or many < 1:\n        raise RulesError("many must be a whole number, 1 or more")\n', "")),
    ("setup: many is not kept", R, f("start, home, many, frozenset(ignore), fields)", "start, home, 10, frozenset(ignore), fields)")),
    ("setup: the names of the inputs are not checked", R, f("    fields = _fields(path=path, content=content)\n", '    fields = {"path": path, "content": content}\n')),
    ("setup: the name of the path input is not used", R, f("    fields = _fields(path=path, content=content)\n", '    fields = _fields(path="path", content=content)\n')),
    ("setup: the name of the content input is not used", R, f("    fields = _fields(path=path, content=content)\n", '    fields = _fields(path=path, content="content")\n')),
    ("setup: ignore given as one text is taken letter by letter", R, f("    if type(ignore) not in (list, tuple, set, frozenset) or any(", "    if any(")),
    ("setup: a name to ignore that is not text is taken", R, f(" or any(type(name) is not str or not name for name in ignore):\n        raise RulesError(\"ignore must be", " or any(type(name) is str and not name for name in ignore):\n        raise RulesError(\"ignore must be")),
    ("setup: an empty name to ignore is taken", R, f("any(type(name) is not str or not name for name in ignore):", "any(type(name) is not str for name in ignore):")),
    ("setup: the path input may be ignored", R, f('    if path in ignore:\n        raise RulesError("the input that holds the path cannot be ignored")\n', "")),
    ("setup: the names to ignore are not kept", R, f("many, frozenset(ignore), fields)", "many, frozenset(), fields)")),
    ("setup: the settings leave out the home folder", R, f('"home": home, "many": many,', '"many": many,')),
    ("setup: the settings leave out what the rule does", R, f('"does": does, "folders"', '"folders"')),
    ("setup: the settings leave out the folders", R, f('"folders": list(folders), ', "")),
    ("setup: the settings leave out the read-only folders", R, f('"read_only": list(read_only), ', "")),
    ("setup: the settings leave out the protected paths", R, f('"protect": list(protect), ', "")),
    ("setup: the settings leave out the starting folder", R, f('"base": base,\n', "\n")),
    ("setup: the settings leave out many", R, f('"many": many, ', "")),
    ("setup: the settings leave out the names to ignore", R, f('"ignore": sorted(ignored), ', "")),
    ("setup: the settings leave out the names of the inputs", R, f(', "fields": fields,\n', ",\n")),
    ("setup: the names to ignore are not sorted in the settings", R, f('"ignore": sorted(ignored)', '"ignore": sorted(ignored, reverse=True)')),
    # ---- the rules set's own file cases ----
    ("set: the read tool is given the rule for writing", S, one("desk.read_file, level=read, describe=read.why", "desk.read_file, level=write, describe=read.why")),
    ("set: the write tool is given the rule for reading", S, one("desk.write_file, level=write, describe=write.why", "desk.write_file, level=read, describe=write.why")),
    ("set: the delete tool is given the rule for writing", S, one("desk.delete_file, level=delete, describe=delete.why", "desk.delete_file, level=write, describe=delete.why")),
    ("set: the read tool is free", S, one("desk.read_file, level=read, describe=read.why", "desk.read_file, level=rules.FREE if hasattr(rules, 'FREE') else 'free', describe=read.why")),
    ("set: the rule for reading has no folder for reading only", S, one("read_only=[SPECS], ", "")),
    ("set: the rule for reading protects nothing", S, one("read_only=[SPECS], protect=[LOG], ", "read_only=[SPECS], ")),
    ("set: the rule for writing protects nothing", S, one('does="write", protect=[LOG], ', 'does="write", ')),
    ("set: the rule for deleting protects nothing", S, one('does="delete", protect=[LOG], ', 'does="delete", ')),
    ("set: the rule for reading has no starting folder", S, one('base=APP, ignore=["encoding"]', 'ignore=["encoding"]')),
    ("set: the rule for writing has no starting folder", S, one('does="write", protect=[LOG], base=APP', 'does="write", protect=[LOG]')),
    ("set: the rule for deleting has no starting folder", S, one('does="delete", protect=[LOG], base=APP', 'does="delete", protect=[LOG]')),
    ("set: the rule for reading passes over no input", S, one(', ignore=["encoding"]', "")),
    ("set: the rule for writing is a rule for deleting", S, one('rules.files([APP], does="write"', 'rules.files([APP], does="delete"')),
    ("set: the rules are made with the real home folder", S, one('    os.environ["HOME"] = home\n    try:\n', "    try:\n")),
    ("set: HOME is not put back", S, one('        else:\n            os.environ["HOME"] = before\n', "        else:\n            pass\n")),
    ("set: HOME is not taken away again when there was none", S, one('            del os.environ["HOME"]\n', "            pass\n")),
    ("set: the small home folder is not worked out to its real place", S, one('home = os.path.join(os.path.realpath(folder), "home")', 'home = os.path.join(folder, "home")')),
    ("set: there is no link from the project to the papers", S, one('    os.symlink(os.path.join(home, "Documents"), os.path.join(app, "shared"))\n', "")),
    ("set: there is no link from the project to the keys", S, one('    os.symlink(os.path.join(home, ".ssh"), os.path.join(app, "keys"))\n', "")),
    ("set: there is no link to Kettle's log", S, one('    os.symlink(os.path.join(app, "kettle.db"), os.path.join(app, "src", "data"))\n', "")),
    ("set: there is no second name for the private paper", S, one('    os.link(os.path.join(home, "Documents", TAX), os.path.join(app, "src", "second-name.txt"))\n', "")),
    ("set: the desk does not write down a read", S, one('        self.files.append(("read", path))\n', "")),
    ("set: the desk does not write down a write", S, one('        self.files.append(("write", path))\n', "")),
    ("set: the desk does not write down a delete", S, one('        self.files.append(("delete", path))\n', "")),
    ("set: the desk does not count the file tools", S, one(" + len(self.commands) + len(self.files)", " + len(self.commands)")),
    ("set: the files group has the name of the shell group", S, one('FILES = "Files"', 'FILES = "Shell commands"')),
    ("set: a file trick is filed as normal work", S, one('"files-read-outside", FILES,', '"files-read-outside", NORMAL,')),
    ("set: a file limit is filed as a trick", S, one('"limit-files-second-name", LIMITS,', '"limit-files-second-name", FILES,')),
    ("set: a refusal is expected to be an ask", S, one('_write("/etc/hosts"), NEVER)', '_write("/etc/hosts"), ASKS)')),
    ("set: an ask is expected to be a refusal", S, one('_read(".env"), ASKS)', '_read(".env"), NEVER)')),
    ("set: a file trick is expected to run", S, one('_delete("src"), ASKS)', '_delete("src"), RUNS)')),
    ("set: normal file work is expected to ask", S, one('_read("src/app.py"), RUNS)', '_read("src/app.py"), ASKS)')),
]

MUTANTS += [(f"reason: the words for {name} are changed", R, f(f'\n_F_{name} = "', f'\n_F_{name} = "x')) for name in REASONS]
MUTANTS += [(f"system: /{name} is not known as a system folder", R, drop("_SYSTEM_FOLDERS", name)) for name in SYSTEM_FOLDERS]
MUTANTS += [(f"keys: {name} is not known as a place for keys", R, drop("_KEY_PIECES", name)) for name in KEY_PIECES]
MUTANTS += [(f"keys: {first}/{second} is not known as a place for keys", R, f(f'("{first}", "{second}"), ' if second != "master.passwd" else f', ("{first}", "{second}")', "")) for first, second in KEY_PAIRS]
MUTANTS += [(f"keys: a file called {name} is not known", R, drop("_KEY_STEMS", name)) for name in KEY_STEMS]
MUTANTS += [(f"keys: a file ending {name} is not known as a key", R, item("_SECRET_ENDINGS", name)) for name in KEY_ENDINGS]
MUTANTS += [(f"keys: a file ending {name} is not known as an example", R, item("_EXAMPLE_ENDINGS", name)) for name in EXAMPLE_ENDINGS]
MUTANTS += [(f"obeyed: the folder {name} is not known", R, drop("_OBEYED_FOLDERS", name)) for name in OBEYED_FOLDERS]
MUTANTS += [(f"obeyed: the file {name} is not known", R, drop("_OBEYED_FILES", name)) for name in OBEYED_FILES]
MUTANTS += [
    (f"setup: does may not be {name}", R, f('_DOES = ("read", "write", "delete")', "_DOES = " + repr(tuple(kept for kept in ("read", "write", "delete") if kept != name))))
    for name in ("read", "write", "delete")
]

KNOWN = {
    "link: two slashes at the start of the real path are kept": "os.path.realpath already gives a path with one slash at the start, on every Python this package runs on. The rule tidies the start again so that it does not lean on that; no test can show the difference.",
}


def dry():
    """Apply every break and say which change nothing, or leave a file that is no longer Python."""
    bad = 0
    for label, rel, change in MUTANTS:
        before = (ROOT / "src" / "kettle" / rel).read_text(encoding="utf-8")
        after = change(before)
        try:
            compile(after, rel, "exec")
            problem = "changes nothing" if after == before else ""
        except SyntaxError as error:
            problem = f"not Python any more: {error}"
        if problem:
            bad += 1
            print(f"{label}  |  {problem}")
    labels = [label for label, _, _ in MUTANTS]
    for label in sorted({label for label in labels if labels.count(label) > 1}):
        bad += 1
        print(f"{label}  |  the name is used twice")
    print(f"{len(MUTANTS)} breaks, {bad} with a problem.")
    return bad


if __name__ == "__main__":
    if sys.argv[1:] == ["--dry"]:
        sys.exit(1 if dry() else 0)
    run(MUTANTS, TESTS, expected_to_survive=KNOWN)
