"""Break the ready-made shell rule one way at a time, and see whether its tests notice.

    .venv/bin/python checks/break_shell.py            every break (a few minutes)
    .venv/bin/python checks/break_shell.py wipe       only the breaks with "wipe" in their name
    .venv/bin/python checks/break_shell.py --dry      apply every break and check it is still Python; run no tests

The shell rule lets a command run without asking when every part of it only
reads, or is a command the owner allows, and never lets one wipe the machine,
the home folder or a disk. So the breaks that matter most here each let one more
command run, or turn a refusal into an ask: a quote read the loose way, a join
that is not seen, a wipe behind sudo or inside sh -c that is not looked for, a
reader told to write that is taken for a reader. Others make the rule say the
wrong reason or take a wrong setting, and the last group breaks the rules set's
own shell cases.

Each break changes one place. A break whose words are found more than once in
the file, or not at all, is reported as not applied.

Only tests/test_shell_rule.py and tests/test_rules_set.py are run.
"""

import re
import sys

from _runner import ROOT, run

TESTS = ["test_shell_rule.py", "test_rules_set.py"]

R, S = "rules.py", "attacktest/rules_set.py"


def one(old, new):
    """Replace `old`, which must be in the file exactly once."""
    return lambda text: text.replace(old, new) if text.count(old) == 1 else text


def sh(old, new):
    """Replace `old`, which must be exactly once in rules.py before the part for file tools, which says some lines again."""

    def change(text):
        at = text.find("\n# ---- files -")
        head = text[:at] if at >= 0 else text
        return head.replace(old, new) + text[len(head):] if head.count(old) == 1 else text

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


def without_line(words):
    """Take out the one line that holds `words`."""

    def change(text):
        lines = text.split("\n")
        kept = [line for line in lines if words not in line]
        return "\n".join(kept) if len(kept) == len(lines) - 1 else text

    return change


TOP = "applications bin boot dev etc home lib lib32 lib64 library media mnt opt private proc root run sbin srv sys system users usr var volumes".split()
PLAIN = (
    "basename cat cd cksum cmp column comm cut df diff dirname du echo egrep false fgrep fold grep head id ls md5 md5sum nl "
    "paste printf pwd realpath rev seq sha1sum sha256sum shasum stat tac tail tr true type uname wc which whoami"
).split()
VERSIONS = "cargo clang docker gcc git go java make node npm pip pip3 pnpm python python3 ruby rustc uv yarn".split()
GIT_READS = "blame cat-file describe diff log ls-files ls-tree merge-base name-rev rev-list rev-parse shortlog show status".split()
BRANCH_LOOKS = "-a -r -v -vv --all --remotes --verbose --list --show-current".split()
FIND_LOOKS = (
    "-a -and -atime -cmin -cnewer -ctime -d -depth -empty -E -false -follow -group -H -iname -ipath -iregex -L -links -maxdepth "
    "-mindepth -mmin -mtime -name -newer -nogroup -not -nouser -o -or -P -path -perm -print -print0 -prune -readable -regex -s "
    "-size -true -type -user -x -xdev"
).split()
FIND_ACTS = "-delete -exec -execdir -ok -okdir -fprint -fprint0 -fprintf -fls".split()
TREE_LOOKS = "--charset --device --dirsfirst --du --filelimit --gitignore --inodes --noreport --prune".split()
FILE_LOOKS = "-b -h -i -I -k -L --brief --mime --mime-encoding --mime-type".split()
DELETES = "rm rmdir shred srm trash unlink".split()
ADMIN = "doas su sudo".split()
SHELLS = "bash csh dash fish ksh sh tcsh zsh".split()
INTERPRETERS = "awk bun deno lua node osascript perl php python python3 ruby".split()
WRAPPERS = ". builtin command env eval exec nice nohup source time timeout watch xargs".split()
NETWORK = "ftp nc ncat netcat rsync scp sftp ssh telnet".split()
RUNNERS = "bunx npx pipx uvx".split()
INSTALLERS = "apt apt-get brew bun cargo conda dnf gem go npm pacman pip pip3 pnpm port uv yarn yum".split()
INSTALL_WORDS = "add ci get i install update upgrade".split()
JOINED = ["eval", "ssh", "su", "watch"]
ERASES = "erase secureerase zerodisk randomdisk reformat partitiondisk delete resetfusion".split()
SECRET_NAMES = [
    ".ssh", ".aws", ".gnupg", ".netrc", ".npmrc", ".pypirc", ".kube", ".docker/config",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "/etc/shadow", "/etc/sudoers", "keychain",
    "_history", ".config/gh/hosts", ".config/gcloud",
]  # fmt: skip
SECRET_ENDINGS = [".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".kdbx", ".ppk"]
SECRET_WORDS = ["secret", "password", "passwd", "credential"]
QUIET_DEVICES = ["/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"]

DEEP = 'text == "--recursive" or (name == "rm" and text.startswith("--r")) or (text[:1] == "-" and text[:2] != "--" and ("R" in text or (name == "rm" and "r" in text)))'
SAID = 'if text[:1] != "-" and "=" not in text and not text.isdigit() and (before[:1] != "-" or (before == "-m" and bases[0] in _INTERPRETERS))'
JOINED_LINE = "joined = any(base in _JOINED for base in (bases if bases[0] in _CARRIERS else bases[:1]))"
ONE_PLAIN = "if found or len(parts) != 1 or any(word.pattern for word in parts[0][1]) or any(_is_control(ord(character)) or ord(character) in (9, 10, 13) for character in value):"
LISTED = "return any(len(entry) <= len(words) and all(not word.pattern and word.text == told for word, told in zip(words, entry)) for entry in self._allowed)"
PIPED = 'piped=join == "|" and before in _FETCHERS'
SET_RULE = 'shell = rules.shell(allow=["pytest", "git add", "git commit"], ignore=["timeout"])'
SET_TOOL = 'checkpoint.tool("run_command", desk.run_command, level=shell, describe=shell.why, watch=["command"])'

MUTANTS = [
    # ---- reading the line: quotes ----
    ("read: single quotes are not followed", R, one("        elif character == \"'\":\n", '        elif character == "\\x00":\n')),
    ("read: a single quote that is never closed does not ask", R, one("            if stop < 0:\n                found.append((NEEDS_YES, _OPEN_QUOTE))\n", "            if stop < 0:\n")),
    ("read: a double quote that is never closed does not ask", R, one("            if at >= end:\n                found.append((NEEDS_YES, _OPEN_QUOTE))\n", "")),
    ("read: double quotes are not followed", R, one("        elif character == '\"':\n            grow()\n", "        elif character == '\\x00':\n            grow()\n")),
    ("read: an empty pair of double quotes is not a word", R, one("        elif character == '\"':\n            grow()\n", "        elif character == '\"':\n")),
    ("read: a $ or a backtick inside double quotes is not seen", R, one('                elif character in "$`":\n                    at = worked_out(at - 1, quoted=True)\n', "")),
    ("read: a backslash inside double quotes is not followed", R, one(r'if character == "\\" and at < end:', "if False:")),
    ("read: a backslash inside double quotes is always dropped", R, one(r'''grow(line[at] if line[at] in '$`"\\' else "\\" + line[at])''', "grow(line[at])")),
    ("read: a backslash inside double quotes is always kept", R, one(r'''grow(line[at] if line[at] in '$`"\\' else "\\" + line[at])''', r'grow("\\" + line[at])')),
    ("read: a backslash outside quotes does not ask", R, one("            found.append((NEEDS_YES, _BACKSLASH))\n", "")),
    ("read: the character after a backslash is read as if the backslash were not there", R, one("            if at < end:\n                grow(line[at])\n                at += 1\n", "")),
    # ---- reading the line: what the shell works out ----
    ("read: a $ or a backtick outside quotes is not seen", R, one('        elif character in "$`":\n            at = worked_out(at - 1, quoted=False)\n', "")),
    ("read: a variable or an inner command does not ask", R, one("        found.append((NEEDS_YES, _WORKED_OUT))\n", "")),
    ("read: $HOME is not read as the home folder", R, one("        home = _HOME_WORD.match(line, at)\n", "        home = None\n")),
    ("read: $HOME in the middle of a word is read as the home folder", R, one('grow("~" if word is None or not any(word[0]) else home.group())', 'grow("~")')),
    ("read: $HOME at the start of a word is left as it is", R, one('grow("~" if word is None or not any(word[0]) else home.group())', "grow(home.group())")),
    ("read: a longer name that starts $HOME is read as the home folder", R, one(r'_HOME_WORD = re.compile(r"\$HOME(?![A-Za-z0-9_])|\$\{HOME\}")', r'_HOME_WORD = re.compile(r"\$HOME|\$\{HOME\}")')),
    ("read: ${HOME} is not read as the home folder", R, one(r'_HOME_WORD = re.compile(r"\$HOME(?![A-Za-z0-9_])|\$\{HOME\}")', r'_HOME_WORD = re.compile(r"\$HOME(?![A-Za-z0-9_])")')),
    ("read: a variable in braces is not kept whole", R, one("        braced = _BRACED.match(line, at)\n", "        braced = None\n")),
    ("read: $( inside double quotes is not marked as an inner command", R, one('inner=line[at] == "`" or line[at + 1 : at + 2] == "("', 'inner=line[at] == "`"')),
    ("read: a backtick inside double quotes is not marked as an inner command", R, one('inner=line[at] == "`" or line[at + 1 : at + 2] == "("', 'inner=line[at + 1 : at + 2] == "("')),
    ("read: every $ inside double quotes is marked as an inner command", R, one('inner=line[at] == "`" or line[at + 1 : at + 2] == "("', "inner=True")),
    ("read: a backtick outside quotes does not cut the part", R, one('        elif line[at] == "`":\n            part("(")\n', '        elif line[at] == "`":\n            close()\n')),
    ("read: brackets and braces do not ask", R, one("            found.append((NEEDS_YES, _BRACKETS))\n", "")),
    ("read: a bracket or brace does not cut the part", R, one('            found.append((NEEDS_YES, _BRACKETS))\n            part("(")\n', "            found.append((NEEDS_YES, _BRACKETS))\n            close()\n")),
    ("read: a bracket is read as an ordinary character", R, one('        elif character in "(){}":\n', '        elif character in "{}":\n')),
    ("read: a brace is read as an ordinary character", R, one('        elif character in "(){}":\n', '        elif character in "()":\n')),
    ("read: a comment does not ask", R, one("            found.append((NEEDS_YES, _COMMENT))\n", "")),
    ("read: a # in the middle of a word is taken for a comment", R, one('        elif character == "#" and word is None:\n', '        elif character == "#":\n')),
    ("read: a * is not seen as a pattern", R, one('pattern=character in "*?["', 'pattern=character in "?["')),
    ("read: a ? is not seen as a pattern", R, one('pattern=character in "*?["', 'pattern=character in "*["')),
    ("read: a [ is not seen as a pattern", R, one('pattern=character in "*?["', 'pattern=character in "*?"')),
    ("read: a pattern mark inside quotes is seen as a pattern", R, one("            grow(line[at:stop])\n            at = stop + 1\n", '            grow(line[at:stop], pattern=any(mark in line[at:stop] for mark in "*?["))\n            at = stop + 1\n')),
    # ---- reading the line: joins ----
    ("read: a line break does not start a new part", R, one(r'''        elif character in "\r\n":''' + "\n" + r'''            part("\n")''', r'''        elif character in "\r\n":''' + "\n            close()")),
    ("read: a tab does not end a word", R, one(r'''        if character in " \t":''', '        if character == " ":')),
    ("read: a ; does not start a new part", R, one('        elif character == ";":\n            part(";")\n', '        elif character == ";":\n            close()\n')),
    ("read: a | does not start a new part", R, one('            part("||" if two else "|")\n', "            close()\n")),
    ("read: || is read as a pipe", R, one('            part("||" if two else "|")\n', '            part("|")\n')),
    ("read: a pipe is read as ||", R, one('            part("||" if two else "|")\n', '            part("||")\n')),
    ("read: an & does not start a new part", R, one('            part("&&" if two else "&")\n', "            close()\n")),
    ("read: an & by itself does not ask", R, one("            if not two:\n                found.append((NEEDS_YES, _NO_WAIT))\n", "")),
    ("read: && asks as if it were an & by itself", R, one("            if not two:\n                found.append((NEEDS_YES, _NO_WAIT))\n", "            found.append((NEEDS_YES, _NO_WAIT))\n")),
    ("read: a part with nothing in it does not ask", R, one("        if join in _JOINS and not parts[-1][1]:\n", "        if False:\n")),
    ("read: a part cut off by a bracket asks as a part with nothing in it", R, one("        if join in _JOINS and not parts[-1][1]:\n", "        if not parts[-1][1]:\n")),
    ("read: a line that ends with a join does not ask", R, one('    if parts[-1][0] in ("&&", "||", "|") and not parts[-1][1]:\n', "    if False:\n")),
    ("read: a ; at the very end asks", R, one('    if parts[-1][0] in ("&&", "||", "|") and not parts[-1][1]:\n', '    if parts[-1][0] in ("&&", "||", "|", ";") and not parts[-1][1]:\n')),
    ("read: the last word of the line is lost", R, one('            grow(character, pattern=character in "*?[")\n    close()\n', '            grow(character, pattern=character in "*?[")\n')),
    ("read: parts with nothing in them are kept", R, one("return [(join, words) for join, words in parts if words], found", "return [(join, words) for join, words in parts], found")),
    # ---- reading the line: < and > ----
    ("read: a < or a > is not seen", R, one('        elif character in "<>":\n            at = redirect(at - 1)\n', "")),
    ("read: output sent to a file does not ask", R, one("        found.append((NEEDS_YES, _TO_FILE))\n", "")),
    ("read: a > onto a disk is not refused", R, one('if line[at] == ">" and name.startswith("/dev/") and name not in _QUIET_DEVICES:', "if False:")),
    ("read: a < from a disk is refused", R, one('if line[at] == ">" and name.startswith("/dev/") and name not in _QUIET_DEVICES:', 'if name.startswith("/dev/") and name not in _QUIET_DEVICES:')),
    ("read: a > to /dev/null written out the long way is refused", R, one('if line[at] == ">" and name.startswith("/dev/") and name not in _QUIET_DEVICES:', 'if line[at] == ">" and name.startswith("/dev/"):')),
    ("read: a > onto a disk in capitals is not refused", R, one(""".replace('"', "").lower()\n        if line[at]""", """.replace('"', "")\n        if line[at]""")),
    ("read: a > onto a disk named in quotes is not refused", R, one("""name = target.group(1).replace("'", "").replace('"', "").lower()""", "name = target.group(1).lower()")),
    ("read: a file named in quotes after a > is skipped and not read", R, one("""return target.start(1) if "'" in target.group(1) or '"' in target.group(1) else target.end()""", "return target.end()")),
    ("read: a file named in single quotes after a > is skipped", R, one("""return target.start(1) if "'" in target.group(1) or '"' in target.group(1) else target.end()""", """return target.start(1) if '"' in target.group(1) else target.end()""")),
    ("read: a file named in double quotes after a > is skipped", R, one("""return target.start(1) if "'" in target.group(1) or '"' in target.group(1) else target.end()""", """return target.start(1) if "'" in target.group(1) else target.end()""")),
    ("read: the file after a > is read as a word of the command", R, one("""return target.start(1) if "'" in target.group(1) or '"' in target.group(1) else target.end()""", "return target.start(1)")),
    ("read: a file whose name starts /dev/null is a quiet ending", R, one(r'_QUIET = re.compile(r"(?:&[12]| */dev/null)(?=[ ;|&]|$)")', r'_QUIET = re.compile(r"(?:&[12]| */dev/null)")')),
    ("read: >/dev/null is not a quiet ending", R, one(r'_QUIET = re.compile(r"(?:&[12]| */dev/null)(?=[ ;|&]|$)")', r'_QUIET = re.compile(r"(?:&[12])(?=[ ;|&]|$)")')),
    ("read: 2>&1 is not a quiet ending", R, one(r'_QUIET = re.compile(r"(?:&[12]| */dev/null)(?=[ ;|&]|$)")', r'_QUIET = re.compile(r"(?: */dev/null)(?=[ ;|&]|$)")')),
    ("read: >&3 is a quiet ending", R, one(r'_QUIET = re.compile(r"(?:&[12]| */dev/null)(?=[ ;|&]|$)")', r'_QUIET = re.compile(r"(?:&[0-9]| */dev/null)(?=[ ;|&]|$)")')),
    ("read: input taken from /dev/null is a quiet ending", R, one('quiet = _QUIET.match(line, at + 1) if line[at] == ">" else None', "quiet = _QUIET.match(line, at + 1)")),
    ("read: no ending is quiet", R, one('quiet = _QUIET.match(line, at + 1) if line[at] == ">" else None', "quiet = None")),
    ("read: the number before a > or a < is kept as a word", R, one('if word is not None and "".join(word[0]) in ("1", "2"):', "if False:")),
    ("read: the number before a < is kept as a word", R, one('if word is not None and "".join(word[0]) in ("1", "2"):', 'if line[at] == ">" and word is not None and "".join(word[0]) in ("1", "2"):')),
    ("read: any word before a > is dropped", R, one('if word is not None and "".join(word[0]) in ("1", "2"):', "if word is not None:")),
    # ---- where a command runs ----
    ("path: a cd earlier in the line is not followed", R, one('        if words[0].text == "cd":\n', "        if False:\n")),
    ("path: cd with no folder is not read as the home folder", R, one("                where = (True, ())\n", "                where = None\n")),
    ("path: a cd that cannot be read leaves the folder as it was", R, one("            else:\n                where = None\n", "            else:\n                pass\n")),
    ("path: .. is not followed", R, one('        if piece == "..":\n            pieces[-1:] = []\n', '        if piece == "..":\n            pass\n')),
    ("path: . is taken for a folder", R, one('        elif piece not in ("", "."):\n', '        elif piece != "":\n')),
    ("path: two slashes are taken for a folder with no name", R, one('        elif piece not in ("", "."):\n', '        elif piece != ".":\n')),
    ("path: capital letters are not folded", R, one("            pieces.append(piece.lower())", "            pieces.append(piece)")),
    ("path: ~ is not read as the home folder", R, one('    if text.startswith("~"):\n        home, pieces, text = True, [], text.partition("/")[2]\n', '    if text.startswith("~"):\n        home, pieces, text = False, [], text.partition("/")[2]\n')),
    ("path: what follows ~/ is lost", R, one('home, pieces, text = True, [], text.partition("/")[2]', 'home, pieces, text = True, [], ""')),
    ("path: $HOME at the start of a word in a list is not read as the home folder", R, one('    text = _HOME_WORD.sub("~", text, count=1) if text.startswith("$") else text\n', "")),
    ("path: a path from the top is read from the folder of the cd", R, one('    elif text.startswith("/"):\n        home, pieces = False, []\n    elif where is None:\n        return None\n', "    elif where is None:\n        return None\n")),
    ("path: a path is read from the top when no folder is known", R, one("    elif where is None:\n        return None\n    else:", "    elif where is None:\n        home, pieces = False, []\n    else:")),
    ("path: a path under a cd forgets the cd", R, one("        home, pieces = where[0], list(where[1])\n", "        home, pieces = where[0], []\n")),
    ("path: a folder of the home folder is taken for the home folder", R, one("    return not pieces if home else len(pieces) == 2 and pieces[0] in _HOME_PARENTS", "    return True if home else len(pieces) == 2 and pieces[0] in _HOME_PARENTS")),
    ("path: /Users/name is not taken for a home folder", R, one("    return not pieces if home else len(pieces) == 2 and pieces[0] in _HOME_PARENTS", "    return not pieces if home else False")),
    ("path: /home/name is not taken for a home folder", R, item("_HOME_PARENTS", "home")),
    ("path: /Users/name is not taken for a home folder or a top folder", R, item("_HOME_PARENTS", "users")),
    ("path: a folder of the home folder is a top folder", R, one("    if home or not pieces:\n        return not pieces\n", "    if home or not pieces:\n        return True\n")),
    ("path: any folder just under / is a top folder", R, one("        return pieces[0] in _TOP_FOLDERS\n", "        return True\n")),
    ("path: no folder two deep is a top folder", R, one('    return len(pieces) == 2 and (pieces[0] in _HOME_PARENTS + ("usr",) or pieces in (("private", "etc"), ("private", "var")))', "    return False")),
    ("path: a folder three deep is a top folder", R, one('    return len(pieces) == 2 and (pieces[0] in _HOME_PARENTS + ("usr",) or pieces in (("private", "etc"), ("private", "var")))', '    return pieces[0] in _HOME_PARENTS + ("usr",) or pieces[:2] in (("private", "etc"), ("private", "var"))')),
    ("path: a folder of /usr is not a top folder", R, one('pieces[0] in _HOME_PARENTS + ("usr",)', "pieces[0] in _HOME_PARENTS")),
    ("path: /private/etc is not a top folder", R, one('pieces in (("private", "etc"), ("private", "var"))', 'pieces in (("private", "var"),)')),
    ("path: /private/var is not a top folder", R, one('pieces in (("private", "etc"), ("private", "var"))', 'pieces in (("private", "etc"),)')),
    ("path: /tmp is a top folder", R, one('srv sys system users usr var volumes".split()', 'srv sys system tmp users usr var volumes".split()')),
    ("path: a pattern always fits everything", R, one('everything = not pieces[first].strip("*?.")', "everything = True")),
    ("path: a pattern never fits everything", R, one('everything = not pieces[first].strip("*?.")', "everything = False")),
    ("path: .* is not taken to fit everything", R, one('everything = not pieces[first].strip("*?.")', 'everything = not pieces[first].strip("*?")')),
    ("path: a pattern is judged by itself and not by the folder it is in", R, one('        text = "/".join(pieces[:first]) or ("/" if text.startswith("/") else ".")\n', "")),
    ("path: a pattern just under / is read from the folder of the cd", R, one('or ("/" if text.startswith("/") else ".")', 'or "."')),
    ("path: a pattern with no folder is read from the top", R, one('or ("/" if text.startswith("/") else ".")', 'or "/"')),
    ("path: a pattern that fits some of a top folder is not a wipe", R, one("    return everything is None or everything or not _is_home(place)", "    return everything is None or everything")),
    ("path: a pattern that fits some of the home folder is a wipe", R, one("    return everything is None or everything or not _is_home(place)", "    return True")),
    ("path: a word with no pattern is never a top folder", R, one("    return everything is None or everything or not _is_home(place)", "    return bool(everything) or (everything is not None and not _is_home(place))")),
    ("path: a path that hangs on where the command runs is a top folder", R, one("    if place is None or not _is_top(place):\n        return False\n", "    if place is None:\n        return True\n    if not _is_top(place):\n        return False\n")),
    # ---- wipes ----
    ("wipe: no wipe is looked for", R, one("            found += _wipes(words, where)\n", "")),
    ("wipe: a wipe is looked for with the cd forgotten", R, one("            found += _wipes(words, where)\n", "            found += _wipes(words, None)\n")),
    ("wipe: capital letters in the name of a command are not folded", R, one('names = [word.text.rsplit("/", 1)[-1].lower() for word in words]', 'names = [word.text.rsplit("/", 1)[-1] for word in words]')),
    ("wipe: a command given by its path is not known", R, one('names = [word.text.rsplit("/", 1)[-1].lower() for word in words]', "names = [word.text.lower() for word in words]")),
    ("wipe: what follows sudo and the like is not looked at", R, one("for at in range(len(words) if names[0] in _CARRIERS else 1):", "for at in range(1):")),
    ("wipe: every word of every command is looked at as a command", R, one("for at in range(len(words) if names[0] in _CARRIERS else 1):", "for at in range(len(words)):")),
    ("wipe: what follows ssh is not looked at", R, one('_CARRIERS = _ADMIN | _WRAPPERS | {"ssh"}', "_CARRIERS = _ADMIN | _WRAPPERS")),
    ("wipe: rm is not looked for", R, one('if name in ("rm", "chmod", "chown", "chgrp"):', 'if name in ("chmod", "chown", "chgrp"):')),
    ("wipe: chmod is not looked for", R, one('if name in ("rm", "chmod", "chown", "chgrp"):', 'if name in ("rm", "chown", "chgrp"):')),
    ("wipe: chown is not looked for", R, one('if name in ("rm", "chmod", "chown", "chgrp"):', 'if name in ("rm", "chmod", "chgrp"):')),
    ("wipe: chgrp is not looked for", R, one('if name in ("rm", "chmod", "chown", "chgrp"):', 'if name in ("rm", "chmod", "chown"):')),
    ("wipe: --recursive is not known", R, one(DEEP, DEEP.replace('text == "--recursive" or ', ""))),
    ("wipe: a short form of --recursive is not known for rm", R, one(DEEP, DEEP.replace('(name == "rm" and text.startswith("--r")) or ', ""))),
    ("wipe: a short form of --recursive is known for chmod", R, one(DEEP, DEEP.replace('(name == "rm" and text.startswith("--r"))', 'text.startswith("--r")'))),
    ("wipe: -R is not known", R, one(DEEP, DEEP.replace('("R" in text or (name == "rm" and "r" in text))', '(name == "rm" and "r" in text)'))),
    ("wipe: -r is not known for rm", R, one(DEEP, DEEP.replace('("R" in text or (name == "rm" and "r" in text))', '("R" in text)'))),
    ("wipe: -r is taken to mean every file for chmod", R, one(DEEP, DEEP.replace('("R" in text or (name == "rm" and "r" in text))', '("R" in text or "r" in text)'))),
    ("wipe: an r in a long option is taken for -r", R, one(DEEP, DEEP.replace(' and text[:2] != "--"', ""))),
    ("wipe: an r in a word that is not an option is taken for -r", R, one(DEEP, DEEP.replace('text[:1] == "-" and ', ""))),
    ("wipe: rm told not to guard the top folder is not refused", R, one('(name == "rm" and any(text.startswith("--no-p") for text in texts)) or ', "")),
    ("wipe: chmod with --no-p is refused", R, one('(name == "rm" and any(text.startswith("--no-p") for text in texts))', '(any(text.startswith("--no-p") for text in texts))')),
    ("wipe: only --no-preserve-root in full is known", R, one('text.startswith("--no-p")', 'text == "--no-preserve-root"')),
    ("wipe: rm of a top folder is refused when it does not go into folders", R, one("or (deep and any(_top(word, where) for word in rest)):", "or (any(_top(word, where) for word in rest)):")),
    ("wipe: rm -r is refused whatever it names", R, one("or (deep and any(_top(word, where) for word in rest)):", "or deep:")),
    ("wipe: rm -r of a top folder is not refused", R, one("or (deep and any(_top(word, where) for word in rest)):", "or False:")),
    ("wipe: only the first name given to rm is looked at", R, one("or (deep and any(_top(word, where) for word in rest)):", "or (deep and any(_top(word, where) for word in rest[:2])):")),
    ("wipe: chmod -R says it would delete", R, one('found.append((NEVER, _WIPE if name == "rm" else _LOCK))', "found.append((NEVER, _WIPE))")),
    ("wipe: rm -rf says it would change who can use the files", R, one('found.append((NEVER, _WIPE if name == "rm" else _LOCK))', "found.append((NEVER, _LOCK))")),
    ("wipe: rm -rf of a top folder only asks", R, one('found.append((NEVER, _WIPE if name == "rm" else _LOCK))', 'found.append((NEEDS_YES, _WIPE if name == "rm" else _LOCK))')),
    ("wipe: find is not looked for", R, one('        elif name == "find":\n            if (', '        elif name == "findx":\n            if (')),
    ("wipe: find -delete on a top folder is not refused", R, one('if ("-delete" in texts or "rm" in names[at:]) and', 'if ("rm" in names[at:]) and')),
    ("wipe: find that runs rm on a top folder is not refused", R, one('if ("-delete" in texts or "rm" in names[at:]) and', 'if ("-delete" in texts) and')),
    ("wipe: find -delete is refused whatever folder it starts from", R, one('if ("-delete" in texts or "rm" in names[at:]) and any(_top(word, where) for word in rest):', 'if "-delete" in texts or "rm" in names[at:]:')),
    ("wipe: find on a top folder is refused when it deletes nothing", R, one('if ("-delete" in texts or "rm" in names[at:]) and any(_top(word, where) for word in rest):', "if any(_top(word, where) for word in rest):")),
    ("wipe: mkfs is not looked for", R, one('name.startswith(("mkfs", "newfs"))', 'name.startswith(("newfs",))')),
    ("wipe: newfs is not looked for", R, one('name.startswith(("mkfs", "newfs"))', 'name.startswith(("mkfs",))')),
    ("wipe: mkfs.ext4 and the like are not looked for", R, one('name.startswith(("mkfs", "newfs"))', 'name in ("mkfs", "newfs")')),
    ("wipe: mke2fs is not looked for", R, one('name in ("mke2fs", "wipefs")', 'name in ("wipefs",)')),
    ("wipe: wipefs is not looked for", R, one('name in ("mke2fs", "wipefs")', 'name in ("mke2fs",)')),
    ("wipe: diskutil is not looked for", R, one('        elif name == "diskutil":\n', '        elif name == "diskutilx":\n')),
    ("wipe: diskutil is refused whatever it is told", R, one("            if any(_ERASES.match(text.lower()) for text in texts):\n", "            if True:\n")),
    ("wipe: capital letters in what diskutil is told are not folded", R, one("_ERASES.match(text.lower())", "_ERASES.match(text)")),
    ("wipe: dd is not looked for", R, one('        elif name == "dd":\n', '        elif name == "ddx":\n')),
    ("wipe: dd is refused whatever it writes to", R, one('if any(text.lower().startswith("of=/dev/") and text.lower()[3:] not in _QUIET_DEVICES for text in texts):', 'if any(text.lower().startswith("of=") for text in texts):')),
    ("wipe: dd to /dev/null is refused", R, one(' and text.lower()[3:] not in _QUIET_DEVICES for text in texts):', " for text in texts):")),
    ("wipe: dd onto a disk in capitals is not refused", R, one('if any(text.lower().startswith("of=/dev/") and text.lower()[3:] not in _QUIET_DEVICES for text in texts):', 'if any(text.startswith("of=/dev/") and text[3:] not in _QUIET_DEVICES for text in texts):')),
    ("wipe: dd reading from a disk is refused", R, one('text.lower().startswith("of=/dev/")', 'text.lower().startswith(("of=/dev/", "if=/dev/"))')),
    ("wipe: a command handed to sh -c as text is not read", R, one("        elif name in _INSIDE and depth < 3:\n", "        elif False:\n")),
    ("wipe: only the first text handed to a shell is read", R, one("            for text in texts:\n                found += _wipes_inside(text, depth + 1)\n", "            for text in texts[:1]:\n                found += _wipes_inside(text, depth + 1)\n")),
    ("wipe: text handed to a shell is read two deep and no more", R, one("        elif name in _INSIDE and depth < 3:\n", "        elif name in _INSIDE and depth < 2:\n")),
    ("wipe: text handed to a shell is read four deep", R, one("        elif name in _INSIDE and depth < 3:\n", "        elif name in _INSIDE and depth < 4:\n")),
    ("wipe: the depth of text handed to a shell is not counted", R, one("                found += _wipes_inside(text, depth + 1)\n", "                found += _wipes_inside(text, depth)\n")),
    ("wipe: a command inside double quotes is not read", R, one("        if word.inner and depth < 3:\n", "        if False:\n")),
    ("wipe: every word is read again as a command", R, one("        if word.inner and depth < 3:\n", "        if depth < 3:\n")),
    ("wipe: a command inside double quotes is read two deep and no more", R, one("        if word.inner and depth < 3:\n", "        if word.inner and depth < 2:\n")),
    ("wipe: a > onto a disk inside sh -c is not refused", R, one("    found = [(level, reason) for level, reason in read if level == NEVER]\n", "    found = []\n")),
    ("wipe: the reasons to ask inside sh -c are given too", R, one("    found = [(level, reason) for level, reason in read if level == NEVER]\n", "    found = list(read)\n")),
    ("wipe: a cd inside sh -c is not followed", R, one("        found += _wipes(words, where, depth)\n", "        found += _wipes(words, None, depth)\n")),
    ("wipe: only the first part inside sh -c is read", R, one("    for _, words, where in _steps(parts):\n        found += _wipes(words, where, depth)\n", "    for _, words, where in list(_steps(parts))[:1]:\n        found += _wipes(words, where, depth)\n")),
    ("wipe: a command that copies itself without end is not refused", R, one('        if _FORK_BOMB.search(re.sub(r"\\s", "", " ".join(texts))):\n            found.append((NEVER, _BOMB))\n', "")),
    ("wipe: a command that copies itself only asks", R, one("            found.append((NEVER, _BOMB))\n", "            found.append((NEEDS_YES, _BOMB))\n")),
    ("wipe: a copying command with spaces in it is not refused", R, one('_FORK_BOMB.search(re.sub(r"\\s", "", " ".join(texts)))', '_FORK_BOMB.search(" ".join(texts))')),
    ("wipe: a copying command that has a name is not refused", R, one(r'_FORK_BOMB = re.compile(r"(:|\b\w{1,40})\(\)', r'_FORK_BOMB = re.compile(r"(:)\(\)')),
    ("wipe: a copying command called : is not refused", R, one(r'_FORK_BOMB = re.compile(r"(:|\b\w{1,40})\(\)', r'_FORK_BOMB = re.compile(r"(\b\w{1,40})\(\)')),
    ("wipe: two commands joined by a pipe and left running are taken for a copying command", R, one(r'\(\)\{\1\|\1&\};?\1")', r'\(\)\{\w+\|\w+&\};?\w+")')),
    # ---- commands that only read ----
    ("reader: tee is taken for a command that only reads", R, one('"paste printf pwd realpath', '"paste tee printf pwd realpath')),
    ("reader: rm is taken for a command that only reads", R, one('"paste printf pwd realpath', '"paste rm printf pwd realpath')),
    ("reader: a command with a version is free whatever it is told", R, one('(name in _VERSIONS and texts == ["--version"])', "(name in _VERSIONS)")),
    ("reader: --version with more after it is free", R, one('(name in _VERSIONS and texts == ["--version"])', '(name in _VERSIONS and texts[:1] == ["--version"])')),
    ("reader: --version anywhere in the command is free", R, one('(name in _VERSIONS and texts == ["--version"])', '(name in _VERSIONS and "--version" in texts)')),
    ("reader: --version is free for any command", R, one('(name in _VERSIONS and texts == ["--version"])', '(texts == ["--version"])')),
    ("reader: no command is free for its version", R, one('(name in _VERSIONS and texts == ["--version"])', "False")),
    ("reader: the careful readers are free whatever they are told", R, one("    return None if check is None else check(texts)", '    return None if check is None else ""')),
    ("reader: every command is taken for a reader", R, one("    return None if check is None else check(texts)", '    return "" if check is None else check(texts)')),
    ("reader: a group of one-letter options is not read", R, one('    return text[:1] == "-" and text[:2] != "--" and any(letter in text for letter in letters)', "    return False")),
    ("reader: a long option is read as a group of one-letter options", R, one('    return text[:1] == "-" and text[:2] != "--" and any(letter in text for letter in letters)', '    return text[:1] == "-" and any(letter in text for letter in letters)')),
    ("reader: a file name is read as a group of one-letter options", R, one('    return text[:1] == "-" and text[:2] != "--" and any(letter in text for letter in letters)', '    return text[:2] != "--" and any(letter in text for letter in letters)')),
    ("reader: sort told to write a file is free", R, one('    return "sort is told to write a file, or to run another program" if told else ""', '    return ""')),
    ("reader: sort --output is not known", R, one('text.startswith(("--o", "--c"))', 'text.startswith(("--c",))')),
    ("reader: sort --compress-program is not known", R, one('text.startswith(("--o", "--c"))', 'text.startswith(("--o",))')),
    ("reader: sort -o is not known", R, one(' or _cluster(text, "o") for text in texts)', " for text in texts)")),
    ("reader: uniq with a second file is free", R, one('    return "" if len(files) <= 1 and "--" not in texts else', '    return "" if "--" not in texts else')),
    ("reader: uniq with a file asks", R, one('    return "" if len(files) <= 1 and "--" not in texts else', '    return "" if len(files) < 1 and "--" not in texts else')),
    ("reader: uniq with -- is free", R, one('    return "" if len(files) <= 1 and "--" not in texts else', '    return "" if len(files) <= 1 else')),
    ("reader: the number after uniq -f is counted as a file", R, one('and (at == 0 or texts[at - 1] not in ("-f", "-s", "-w"))]', "]")),
    ("reader: what follows any uniq option is not counted as a file", R, one('texts[at - 1] not in ("-f", "-s", "-w")', 'texts[at - 1][:1] != "-"')),
    ("reader: an option of uniq is counted as a file", R, one('files = [text for at, text in enumerate(texts) if text[:1] != "-" and (', "files = [text for at, text in enumerate(texts) if (")),
    ("reader: find with any option is free", R, one('        if text[:1] == "-" and text not in _FIND_LOOKS and not _FIND_COUNT.fullmatch(text):\n', "        if False:\n")),
    ("reader: find -delete is taken for a way of looking", R, one('"-a -and -atime -cmin', '"-a -and -delete -atime -cmin')),
    ("reader: find -exec is taken for a way of looking", R, one('"-a -and -atime -cmin', '"-a -and -exec -atime -cmin')),
    ("reader: a number given to find as -1 asks", R, one(" and not _FIND_COUNT.fullmatch(text):", ":")),
    ("reader: any option of find that starts with a number is free", R, one("not _FIND_COUNT.fullmatch(text)", "not _FIND_COUNT.match(text)")),
    ("reader: a word of find that is not an option asks", R, one('        if text[:1] == "-" and text not in _FIND_LOOKS and', "        if text not in _FIND_LOOKS and")),
    ("reader: find says the same for an option it does not know and for a delete", R, one(' if text in _FIND_ACTS else "find is given an option this rule does not know"', "")),
    ("reader: only the first option of find is read", R, one("    for text in texts:\n        if text[:1] == \"-\" and text not in _FIND_LOOKS", "    for text in texts[:2]:\n        if text[:1] == \"-\" and text not in _FIND_LOOKS")),
    ("reader: rg told to run a program is free", R, one('    return "rg is told to run another program" if any(', '    return "" if any(')),
    ("reader: rg --pre is not known", R, one('text.startswith(("--pre", "--hostname-bin"))', 'text.startswith(("--hostname-bin",))')),
    ("reader: rg --hostname-bin is not known", R, one('text.startswith(("--pre", "--hostname-bin"))', 'text.startswith(("--pre",))')),
    ("reader: tree told to write a file is free", R, one('    return "tree is told to write a file, or is given an option this rule does not know" if told else ""', '    return ""')),
    ("reader: tree -o is not known", R, one('_cluster(text, "oR")', '_cluster(text, "R")')),
    ("reader: tree -R is not known", R, one('_cluster(text, "oR")', '_cluster(text, "o")')),
    ("reader: any long option of tree is free", R, one('told = any((text[:2] == "--" and text.partition("=")[0] not in _TREE_LOOKS) or ', "told = any(")),
    ("reader: a long option of tree with a value asks", R, one('text.partition("=")[0] not in _TREE_LOOKS', "text not in _TREE_LOOKS")),
    ("reader: file with any option is free", R, one('    return "file is given an option this rule does not know" if any(', '    return "" if any(')),
    ("reader: a name given to file asks", R, one('any(text[:1] == "-" and text not in _FILE_LOOKS for text in texts)', "any(text not in _FILE_LOOKS for text in texts)")),
    ("reader: date told to set the clock is free", R, one('    return "" if all(text == "-u" or text.startswith("+") for text in texts) else "date is told to do more than show the time"', '    return ""')),
    ("reader: date -u asks", R, one('all(text == "-u" or text.startswith("+") for text in texts)', 'all(text.startswith("+") for text in texts)')),
    ("reader: date with a format asks", R, one('all(text == "-u" or text.startswith("+") for text in texts)', 'all(text == "-u" for text in texts)')),
    ("reader: hostname told to set the name is free", R, one('    return "" if texts in ([], ["-s"], ["-f"]) else', '    return "" if True else')),
    ("reader: hostname -s asks", R, one('texts in ([], ["-s"], ["-f"])', 'texts in ([], ["-f"])')),
    ("reader: hostname -f asks", R, one('texts in ([], ["-s"], ["-f"])', 'texts in ([], ["-s"])')),
    ("reader: hostname by itself asks", R, one('texts in ([], ["-s"], ["-f"])', 'texts in (["-s"], ["-f"])')),
    ("reader: sed is free whatever it is told", R, one('    return "" if prints else "sed is used for more than printing chosen lines"', '    return ""')),
    ("reader: sed without -n is free", R, one('texts[0] == "-n" and _SED_PRINT', "_SED_PRINT")),
    ("reader: a sed script that starts like a print is free", R, one("_SED_PRINT.fullmatch(texts[1])", "_SED_PRINT.match(texts[1])")),
    ("reader: sed with an option after the script is free", R, one(' and not any(text.startswith("-") for text in texts[2:])', "")),
    ("reader: sed that prints one line and not a run of lines asks", R, one('_SED_PRINT = re.compile(r"[0-9]{1,9}(?:,[0-9]{1,9})?p")', '_SED_PRINT = re.compile(r"[0-9]{1,9}(?:,[0-9]{1,9})p")')),
    ("reader: sed that prints a run of lines asks", R, one('_SED_PRINT = re.compile(r"[0-9]{1,9}(?:,[0-9]{1,9})?p")', '_SED_PRINT = re.compile(r"[0-9]{1,9}p")')),
    # ---- git ----
    ("git: --no-pager is not skipped", R, one('    while texts[:1] == ["--no-pager"] or (texts[:1] == ["-C"] and len(texts) > 1):\n', '    while texts[:1] == ["-C"] and len(texts) > 1:\n')),
    ("git: -C and its folder are not skipped", R, one('    while texts[:1] == ["--no-pager"] or (texts[:1] == ["-C"] and len(texts) > 1):\n', '    while texts[:1] == ["--no-pager"]:\n')),
    ("git: -c and its setting are skipped as -C is", R, one('    while texts[:1] == ["--no-pager"] or (texts[:1] == ["-C"] and len(texts) > 1):\n        texts = texts[1 if texts[0] == "--no-pager" else 2 :]\n', '    while texts[:1] == ["--no-pager"] or (texts[:1] in (["-C"], ["-c"]) and len(texts) > 1):\n        texts = texts[1 if texts[0] == "--no-pager" else 2 :]\n')),
    ("git: checkout is taken for a command that only reads", R, one('"blame cat-file describe', '"blame checkout cat-file describe')),
    ("git: push is taken for a command that only reads", R, one('"blame cat-file describe', '"blame push cat-file describe')),
    ("git: a reading command told to write a file is free", R, one('        return "git is told to write a file, or to run another program" if any(text.startswith(("--ou", "--ext")) for text in rest) else ""\n', '        return ""\n')),
    ("git: --output is not known", R, one('text.startswith(("--ou", "--ext"))', 'text.startswith(("--ext",))')),
    ("git: --ext-diff is not known", R, one('text.startswith(("--ou", "--ext"))', 'text.startswith(("--ou",))')),
    ("git: only --output in full is known", R, one('text.startswith(("--ou", "--ext"))', 'text.startswith(("--output", "--ext"))')),
    ("git: branch is free whatever it is told", R, one('(command == "branch" and all(text in _BRANCH_LOOKS for text in rest))', '(command == "branch")')),
    ("git: tag is free whatever it is told", R, one('(command == "tag" and all(text in ("-l", "--list") for text in rest))', '(command == "tag")')),
    ("git: remote is free whatever it is told", R, one('(command == "remote" and all(text in ("-v", "--verbose") for text in rest))', '(command == "remote")')),
    ("git: stash is free whatever it is told", R, one('(command == "stash" and rest == ["list"])', '(command == "stash")')),
    ("git: stash list with more after it is free", R, one('(command == "stash" and rest == ["list"])', '(command == "stash" and rest[:1] == ["list"])')),
    ("git: branch asks", R, one('        (command == "branch" and all(text in _BRANCH_LOOKS for text in rest))\n        or ', "        ")),
    ("git: tag asks", R, one('        or (command == "tag" and all(text in ("-l", "--list") for text in rest))\n', "")),
    ("git: remote asks", R, one('        or (command == "remote" and all(text in ("-v", "--verbose") for text in rest))\n', "")),
    ("git: stash list asks", R, one('        or (command == "stash" and rest == ["list"])\n', "")),
    ("git: tag -l asks", R, one('text in ("-l", "--list") for text in rest', 'text in ("--list",) for text in rest')),
    ("git: tag --list asks", R, one('text in ("-l", "--list") for text in rest', 'text in ("-l",) for text in rest')),
    ("git: remote -v asks", R, one('text in ("-v", "--verbose") for text in rest', 'text in ("--verbose",) for text in rest')),
    ("git: remote --verbose asks", R, one('text in ("-v", "--verbose") for text in rest', 'text in ("-v",) for text in rest')),
    ("git: push is not told apart from other git commands", R, one('    if command == "push":\n', '    if command == "pushx":\n')),
    ("git: a forced push is not told apart from a push", R, one('        return "a forced git push can throw away work on the other side" if forced else "git push sends your work out"\n', '        return "git push sends your work out"\n')),
    ("git: push --force is not known as forced", R, one('text.startswith(("--force", "+"))', 'text.startswith(("+",))')),
    ("git: a push of +branch is not known as forced", R, one('text.startswith(("--force", "+"))', 'text.startswith(("--force",))')),
    ("git: push -f is not known as forced", R, one(' or _cluster(text, "f") for text in rest)', " for text in rest)")),
    ("git: reset --hard is not told apart", R, one('    if command == "reset" and "--hard" in rest:\n', "    if False:\n")),
    ("git: every reset is said to throw away changes", R, one('    if command == "reset" and "--hard" in rest:\n', '    if command == "reset":\n')),
    ("git: clean is not told apart", R, one('    if command == "clean":\n', "    if False:\n")),
    ("git: git by itself is free", R, one('    command, rest = (texts[0], texts[1:]) if texts else ("", [])\n', '    command, rest = (texts[0], texts[1:]) if texts else ("status", [])\n')),
    # ---- every other command ----
    ("other: a variable set before a command is not told apart", R, one("    if _ASSIGNMENT.match(name):\n", "    if False:\n")),
    ("other: a download piped into a shell is not told apart", R, one("    if piped and (base in _SHELLS | _INTERPRETERS or (base in _ADMIN and any(text in _SHELLS for text in texts))):\n", "    if False:\n")),
    ("other: a download piped into sudo sh is not told apart", R, one(" or (base in _ADMIN and any(text in _SHELLS for text in texts))):", "):")),
    ("other: a download piped into sudo is always said to reach a shell", R, one("(base in _ADMIN and any(text in _SHELLS for text in texts))", "(base in _ADMIN)")),
    ("other: a download piped into any command is said to reach a shell", R, one("    if piped and (base in _SHELLS | _INTERPRETERS or (base in _ADMIN and any(text in _SHELLS for text in texts))):\n", "    if piped:\n")),
    ("other: any shell is said to be fed a download", R, one("    if piped and (base in _SHELLS | _INTERPRETERS or", "    if (base in _SHELLS | _INTERPRETERS or")),
    (f"other: a pipe from any command into a shell is said to be a download ({PIPED})", R, one(PIPED, 'piped=join == "|"')),
    ("other: a download joined to a shell with && is said to be piped", R, one(PIPED, "piped=before in _FETCHERS")),
    ("other: a download fetched by its path and piped into a shell is not told apart", R, one('            before = words[0].text.rsplit("/", 1)[-1]\n', "            before = words[0].text\n")),
    ("other: the command before the pipe is not kept", R, one('            before = words[0].text.rsplit("/", 1)[-1]\n', "")),
    ("other: a delete is not told apart", R, one('    if base in _DELETES:\n        return "it deletes files"\n', "")),
    ("other: sudo is not told apart", R, one('    if base in _ADMIN:\n        return "it runs as the administrator"\n', "")),
    ("other: a script is not told apart", R, one('    if base in _SHELLS | _INTERPRETERS:\n        return "it runs a script, or program text this rule does not read"\n', "")),
    ("other: a shell is not said to run a script", R, one("    if base in _SHELLS | _INTERPRETERS:\n        return", "    if base in _INTERPRETERS:\n        return")),
    ("other: python and the like are not said to run a script", R, one("    if base in _SHELLS | _INTERPRETERS:\n        return", "    if base in _SHELLS:\n        return")),
    ("other: npx and the like are not told apart", R, one('    if base in _RUNNERS:\n        return "it downloads a program and runs it"\n', "")),
    ("other: an install is not told apart", R, one('    if base in _INSTALLERS and any(text in _INSTALL_WORDS for text in texts):\n        return "it installs software"\n', "")),
    ("other: an installer is said to install whatever it is told", R, one("    if base in _INSTALLERS and any(text in _INSTALL_WORDS for text in texts):\n", "    if base in _INSTALLERS:\n")),
    ("other: the network is not told apart", R, one('    if base in _NETWORK:\n        return "it reaches out over the network"\n', "")),
    ("other: curl is not said to reach the network", R, item("_FETCHERS", "curl")),
    ("other: wget is not said to reach the network", R, item("_FETCHERS", "wget")),
    ("other: a program run by its path is not told apart", R, one('    if "/" in name:\n        return "it runs a program by its path, which may be a script"\n', "")),
    ("other: a delete by its path is said to be a program run by its path", R, one('    base = name.rsplit("/", 1)[-1]\n    if _ASSIGNMENT.match(name):', "    base = name\n    if _ASSIGNMENT.match(name):")),
    ("other: a command with an odd name is shown as it is", R, one('    shown = name if _PLAIN_COMMAND.fullmatch(name) else "the command"\n', "    shown = name\n")),
    ("other: the name of the command is never shown", R, one('    shown = name if _PLAIN_COMMAND.fullmatch(name) else "the command"\n', '    shown = "the command"\n')),
    ("other: a long name is shown", R, one('_PLAIN_COMMAND = re.compile(r"[A-Za-z0-9._+-]{1,24}")', '_PLAIN_COMMAND = re.compile(r"[A-Za-z0-9._+-]{1,}")')),
    ("other: a name that starts plainly is shown whole", R, one("_PLAIN_COMMAND.fullmatch(name)", "_PLAIN_COMMAND.match(name)")),
    ("other: a word with = in the middle is not seen as setting a variable", R, one('_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\\+?=")', '_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\\+?=$")')),
    # ---- reads that reach for what is private ----
    ("private: a read of a place where keys are kept is free", R, one("    if any(_secret_place(word) for word in rest):\n        reasons.append(_SECRET_PLACE)\n", "")),
    ("private: .env is not known", R, one('piece == ".env" or piece == ".envrc" or', 'piece == ".envrc" or')),
    ("private: .envrc is not known", R, one('piece == ".env" or piece == ".envrc" or', 'piece == ".env" or')),
    ("private: .env.local and the like are not known", R, one(' or piece.startswith(".env.") for piece in pieces)', " for piece in pieces)")),
    ("private: any name that starts .env is taken for the .env file", R, one('piece.startswith(".env.")', 'piece.startswith(".env")')),
    ("private: .env after a / is not seen", R, one('pieces = re.split(r"[/=:,]", text)', 'pieces = re.split(r"[=:,]", text)')),
    ("private: .env after an = is not seen", R, one('pieces = re.split(r"[/=:,]", text)', 'pieces = re.split(r"[/:,]", text)')),
    ("private: .env after a : is not seen", R, one('pieces = re.split(r"[/=:,]", text)', 'pieces = re.split(r"[/=,]", text)')),
    ("private: .env after a , is not seen", R, one('pieces = re.split(r"[/=:,]", text)', 'pieces = re.split(r"[/=:]", text)')),
    ("private: capital letters in a private name are not folded", R, one("    text = word.text.lower()\n    on_the_way", "    text = word.text\n    on_the_way")),
    ("private: the usual key folders and files are not known", R, one("    if any(name in text for name in _SECRET_NAMES) or text.endswith(_SECRET_ENDINGS):\n", "    if text.endswith(_SECRET_ENDINGS):\n")),
    ("private: a key file is not known by its ending", R, one("    if any(name in text for name in _SECRET_NAMES) or text.endswith(_SECRET_ENDINGS):\n", "    if any(name in text for name in _SECRET_NAMES):\n")),
    ("private: a key ending in the middle of a name is taken for a key file", R, one("text.endswith(_SECRET_ENDINGS)", "any(ending in text for ending in _SECRET_ENDINGS)")),
    ("private: a file with password in its name is free", R, one('    return ("/" in text or "." in text) and any(name in text for name in _SECRET_WORDS)\n', "    return False\n")),
    ("private: the word password searched for is taken for a private file", R, one('    return ("/" in text or "." in text) and any(name in text for name in _SECRET_WORDS)\n', "    return any(name in text for name in _SECRET_WORDS)\n")),
    ("private: a file called passwords with a folder in front is free", R, one('("/" in text or "." in text) and any(name in text for name in _SECRET_WORDS)', '("." in text) and any(name in text for name in _SECRET_WORDS)')),
    ("private: a file called passwords.txt is free", R, one('("/" in text or "." in text) and any(name in text for name in _SECRET_WORDS)', '("/" in text) and any(name in text for name in _SECRET_WORDS)')),
    ("private: a pattern that reaches hidden files is free", R, one("    if any(_hidden_pattern(word) for word in rest):\n        reasons.append(_HIDDEN_FILES)\n", "")),
    ("private: a quoted word that starts with a dot and holds a * is taken for a pattern", R, one("    return word.pattern and any(piece.startswith(\".\")", "    return any(piece.startswith(\".\")")),
    ("private: any pattern is said to reach hidden files", R, one('any(piece.startswith(".") and any(mark in piece for mark in "*?[") for piece in word.text.split("/"))', 'any(any(mark in piece for mark in "*?[") for piece in word.text.split("/"))')),
    ("private: a pattern after a hidden folder is said to reach hidden files", R, one('any(piece.startswith(".") and any(mark in piece for mark in "*?[") for piece in word.text.split("/"))', 'any(piece.startswith(".") for piece in word.text.split("/"))')),
    ("private: a hidden pattern after a folder is not seen", R, one('any(mark in piece for mark in "*?[") for piece in word.text.split("/"))', 'any(mark in piece for mark in "*?[") for piece in [word.text])')),
    ("private: a search through the whole home folder is free", R, one("    if deep and any(_top(word, where) for word in rest):\n        reasons.append(_WIDE_SEARCH)\n", "")),
    ("private: any read of a top folder is said to search all of it", R, one("    if deep and any(_top(word, where) for word in rest):\n", "    if any(_top(word, where) for word in rest):\n")),
    ("private: any search that goes into folders is said to search a top folder", R, one("    if deep and any(_top(word, where) for word in rest):\n", "    if deep:\n")),
    ("private: a wide search forgets the cd before it", R, one("    if deep and any(_top(word, where) for word in rest):\n", "    if deep and any(_top(word, None) for word in rest):\n")),
    ("private: rg is not taken to go into folders", R, one('    deep = name == "rg" or (name in', "    deep = (name in")),
    ("private: grep is not taken to go into folders with -r", R, one('name in ("grep", "egrep", "fgrep") and any(', 'name in ("egrep", "fgrep") and any(')),
    ("private: egrep is not taken to go into folders with -r", R, one('name in ("grep", "egrep", "fgrep") and any(', 'name in ("grep", "fgrep") and any(')),
    ("private: fgrep is not taken to go into folders with -r", R, one('name in ("grep", "egrep", "fgrep") and any(', 'name in ("grep", "egrep") and any(')),
    ("private: grep is taken to go into folders without -r", R, one('(name in ("grep", "egrep", "fgrep") and any(_cluster(text, "rR") or text in ("--recursive", "--dereference-recursive") for text in texts))', '(name in ("grep", "egrep", "fgrep"))')),
    ("private: grep -r is not known", R, one('_cluster(text, "rR")', '_cluster(text, "R")')),
    ("private: grep -R is not known", R, one('_cluster(text, "rR")', '_cluster(text, "r")')),
    ("private: grep --recursive is not known", R, one('text in ("--recursive", "--dereference-recursive")', 'text in ("--dereference-recursive",)')),
    ("private: grep --dereference-recursive is not known", R, one('text in ("--recursive", "--dereference-recursive")', 'text in ("--recursive",)')),
    ("private: a pattern given to a careful reader is free", R, one("    if name not in _PLAIN_READS and any(word.pattern for word in rest):\n        reasons.append(_PATTERN_OPTION)\n", "")),
    ("private: a pattern given to a plain reader asks", R, one("    if name not in _PLAIN_READS and any(word.pattern for word in rest):\n", "    if any(word.pattern for word in rest):\n")),
    ("private: a careful reader is said to hold a pattern when it holds none", R, one("    if name not in _PLAIN_READS and any(word.pattern for word in rest):\n", "    if name not in _PLAIN_READS:\n")),
    ("private: the reason a reader gives is lost", R, one("    reasons = [use] if use else []\n", "    reasons = []\n")),
    # ---- the whole look ----
    ("look: an input the rule was not told about is free", R, one("        untold = len(set(inputs) - set(self._fields.values()) - self._ignored)\n", "        untold = 0\n")),
    ("look: an ignored input counts as one the rule was not told about", R, one("        untold = len(set(inputs) - set(self._fields.values()) - self._ignored)\n", "        untold = len(set(inputs) - set(self._fields.values()))\n")),
    ("look: the command itself counts as an input the rule was not told about", R, one("        untold = len(set(inputs) - set(self._fields.values()) - self._ignored)\n", "        untold = len(set(inputs) - self._ignored)\n")),
    ("look: the count of untold inputs is one too high", R, one('{untold} of the inputs"))\n        command = inputs.get(self._fields["command"])', '{untold + 1} of the inputs"))\n        command = inputs.get(self._fields["command"])')),
    ("look: the command is read from the input called command whatever the owner said", R, one('        command = inputs.get(self._fields["command"])\n        if type(command) is str and command.strip(_BLANK):', '        command = inputs.get("command")\n        if type(command) is str and command.strip(_BLANK):')),
    ("look: a command of only blanks is read", R, one("        if type(command) is str and command.strip(_BLANK):\n", "        if type(command) is str:\n")),
    ("look: blanks around the command are kept", R, one("            texts = [command.strip(_BLANK)]\n", "            texts = [command]\n")),
    ("look: an empty list is read as a command", R, one("        elif type(command) is list and command and command[0] and all(type(text) is str for text in command):\n", "        elif type(command) is list and all(type(text) is str for text in command):\n")),
    ("look: a list whose first word is empty is read as a command", R, one("type(command) is list and command and command[0] and all(", "type(command) is list and command and all(")),
    ("look: a tuple of words is read as a command", R, one("        elif type(command) is list and command and", "        elif type(command) in (list, tuple) and command and")),
    ("look: a list of words is read as one line by a shell", R, one("            parts = [(\"\", [_Word(text) for text in command])]\n", '            parts, read = _read_line(" ".join(command))\n            found += read\n')),
    ("look: a command that cannot be read is free", R, one("            return found + [(NEEDS_YES, _NO_COMMAND)]\n", "            return found\n")),
    ("look: a command that cannot be read forgets the untold inputs", R, one("            return found + [(NEEDS_YES, _NO_COMMAND)]\n", "            return [(NEEDS_YES, _NO_COMMAND)]\n")),
    ("look: a line break or a tab in the command is free", R, one("            if any(ord(character) < 0x20 for character in text) or hidden(text):\n", "            if hidden(text):\n")),
    ("look: a character that cannot be seen in the command is free", R, sh("for character in text) or hidden(text):\n", "for character in text):\n")),
    ("look: a key in the command is free", R, one('            found += [(NEEDS_YES, f"the command holds what looks like {kind}") for kind in sensitive(text)]\n', "")),
    ("look: only the first word of a list is checked for keys and unseen characters", R, one("        for text in texts:\n            if any(ord(character)", "        for text in texts[:1]:\n            if any(ord(character)")),
    ("look: only the first part of the command is looked at", R, one("        for join, words, where in _steps(parts):\n            found += _wipes(words, where)\n", "        for join, words, where in list(_steps(parts))[:1]:\n            found += _wipes(words, where)\n")),
    ("look: no part of the command is asked about", R, one('            if join != "(" and not self._listed(words):\n                found += [(NEEDS_YES, reason) for reason in _part_asks(words, where, piped=join == "|" and before in _FETCHERS)]\n', "")),
    ("look: a part cut off by a bracket is asked about like any other", R, one('            if join != "(" and not self._listed(words):\n', "            if not self._listed(words):\n")),
    ("look: the owner's own commands ask like any other", R, one('            if join != "(" and not self._listed(words):\n', '            if join != "(":\n')),
    ("look: a part asks with the cd before it forgotten", R, one("for reason in _part_asks(words, where, piped=", "for reason in _part_asks(words, None, piped=")),
    ("look: the first word of a part is not taken for its command", R, one("    name, rest = words[0].text, words[1:]\n    texts = [word.text for word in rest]\n    use = _reader(name, texts)\n", "    name, rest = words[-1].text, words[1:]\n    texts = [word.text for word in rest]\n    use = _reader(name, texts)\n")),
    # ---- the owner's list ----
    ("list: the start of an owner's command is enough", R, one(LISTED, LISTED.replace("len(entry) <= len(words) and ", ""))),
    ("list: a pattern can stand for an owner's command", R, one(LISTED, LISTED.replace("not word.pattern and ", ""))),
    ("list: a longer name that starts with an owner's command is allowed", R, one(LISTED, LISTED.replace("word.text == told", "word.text.startswith(told)"))),
    ("list: only the first word of an owner's command is checked", R, one(LISTED, LISTED.replace("zip(words, entry)", "zip(words[:1], entry)"))),
    ("list: every command is taken to be on the owner's list", R, one(LISTED, "return True")),
    ("list: an owner's command with nothing after it is not allowed", R, one(LISTED, LISTED.replace("len(entry) <= len(words)", "len(entry) < len(words)"))),
    ("list: capital letters in an owner's command are folded", R, one(LISTED, LISTED.replace("word.text == told", "word.text.lower() == told.lower()"))),
    # ---- setup ----
    ("setup: a list of commands given as one text is taken", R, one("    if type(values) not in (list, tuple, set, frozenset):\n        raise RulesError(\"allow must be", "    if type(values) not in (list, tuple, set, frozenset, str):\n        raise RulesError(\"allow must be")),
    ("setup: a list of commands given as a table is taken", R, one("    if type(values) not in (list, tuple, set, frozenset):\n        raise RulesError(\"allow must be", "    if type(values) not in (list, tuple, set, frozenset, dict):\n        raise RulesError(\"allow must be")),
    ("setup: no list of commands is the same as a mistake", R, one('checked and copied."""\n    if values is None:\n        return frozenset()\n    if type(values) not in (list, tuple, set, frozenset):\n        raise RulesError("allow must be a list of commands', 'checked and copied."""\n    if type(values) not in (list, tuple, set, frozenset):\n        raise RulesError("allow must be a list of commands')),
    ("setup: an allowed command with a quote left open is taken", R, one(ONE_PLAIN, ONE_PLAIN.replace("if found or ", "if "))),
    ("setup: two commands in one allowed entry are taken", R, one(ONE_PLAIN, ONE_PLAIN.replace("len(parts) != 1", "len(parts) > 2"))),
    ("setup: an allowed command with nothing in it is taken", R, one(ONE_PLAIN, ONE_PLAIN.replace("len(parts) != 1", "len(parts) > 1"))),
    ("setup: an allowed command with a pattern is taken", R, one(ONE_PLAIN, ONE_PLAIN.replace(" or any(word.pattern for word in parts[0][1])", ""))),
    ("setup: an allowed command with a character that cannot be seen is taken", R, one(ONE_PLAIN, ONE_PLAIN.replace("_is_control(ord(character)) or ", ""))),
    ("setup: an allowed command with a tab in it is taken", R, one(ONE_PLAIN, ONE_PLAIN.replace(" or ord(character) in (9, 10, 13)", ""))),
    ("setup: an allowed command that is not text is read as nothing and then crashes", R, one("_read_line(value) if type(value) is str else ([], [])", "_read_line(value)")),
    ("setup: the first word alone of an allowed command is kept", R, one("        entry = tuple(word.text for word in parts[0][1])\n", "        entry = tuple(word.text for word in parts[0][1][:1])\n")),
    ("setup: a launcher that is told nothing to run is allowed", R, one("        if joined or (bases[0] in _LAUNCHERS and not said):\n", "        if joined:\n")),
    ("setup: a launcher is refused even when it is told what to run", R, one("        if joined or (bases[0] in _LAUNCHERS and not said):\n", "        if joined or bases[0] in _LAUNCHERS:\n")),
    ("setup: eval, ssh and the like are allowed", R, one("        if joined or (bases[0] in _LAUNCHERS and not said):\n", "        if bases[0] in _LAUNCHERS and not said:\n")),
    ("setup: eval behind sudo is allowed", R, one(JOINED_LINE, "joined = any(base in _JOINED for base in bases[:1])")),
    ("setup: a command with the word watch anywhere in it is refused", R, one(JOINED_LINE, "joined = any(base in _JOINED for base in bases)")),
    ("setup: a launcher given by its path is allowed", R, one('        bases = [text.rsplit("/", 1)[-1] for text in entry]\n', "        bases = list(entry)\n")),
    ("setup: an option counts as what a launcher is told to run", R, one(SAID, SAID.replace('text[:1] != "-" and ', ""))),
    ("setup: a variable counts as what a launcher is told to run", R, one(SAID, SAID.replace('"=" not in text and ', ""))),
    ("setup: a number counts as what a launcher is told to run", R, one(SAID, SAID.replace("not text.isdigit() and ", ""))),
    ("setup: the value of an option counts as what a launcher is told to run", R, one(SAID, SAID.replace(' and (before[:1] != "-" or (before == "-m" and bases[0] in _INTERPRETERS))', ""))),
    ("setup: python -m with a module does not count as told what to run", R, one(SAID, SAID.replace('(before[:1] != "-" or (before == "-m" and bases[0] in _INTERPRETERS))', 'before[:1] != "-"'))),
    ("setup: -m counts as naming what to run for any launcher", R, one(SAID, SAID.replace(' and bases[0] in _INTERPRETERS', ""))),
    ("setup: an allowed command that would let anything run is said to be not plain", R, one("""            raise RulesError(f"allow: {value!r} would let anything at all run. Say what it runs, such as 'python -m pytest'")\n""", """            raise RulesError(f"allow: {value!r} is not one plain command, such as 'pytest' or 'git add'")\n""")),
    ("setup: the owner's commands are not kept", R, one("        kept.add(entry)\n", "")),
    ("setup: ignore given as one text is taken", R, sh("    if type(ignore) not in (list, tuple, set, frozenset) or any(", "    if type(ignore) not in (list, tuple, set, frozenset, str) or any(")),
    ("setup: a name to ignore that is not text is taken", R, sh("any(type(name) is not str or not name for name in ignore)", "any(type(name) is str and not name for name in ignore)")),
    ("setup: an empty name to ignore is taken", R, sh("any(type(name) is not str or not name for name in ignore)", "any(type(name) is not str for name in ignore)")),
    ("setup: the input that holds the command can be ignored", R, one('    if command in ignore:\n        raise RulesError("the input that holds the command cannot be ignored")\n', "")),
    ("setup: the names to ignore are not kept", R, one("    return _Shell(allowed, frozenset(ignore), fields)", "    return _Shell(allowed, frozenset(), fields)")),
    ("setup: the owner's commands are not handed to the rule", R, one("    return _Shell(allowed, frozenset(ignore), fields)", "    return _Shell(frozenset(), frozenset(ignore), fields)")),
    ("setup: the name of the command input is not checked", R, one("    fields = _fields(command=command)\n    if type(ignore)", '    fields = {"command": command}\n    if type(ignore)')),
    ("setup: the shell rule goes by another kind", R, one('    kind = "shell"\n', '    kind = "web"\n')),
    ("setup: shell is not one of the names the module gives out", R, one('"web", "shell", "files"', '"web", "files"')),
    ("setup: the name of the rule does not hang on the owner's commands", R, one('{"allow": sorted(list(entry) for entry in allowed), "ignore"', '{"allow": [], "ignore"')),
    ("setup: the name of the rule does not hang on the names to ignore", R, sh('"ignore": sorted(ignored), "fields": fields})', '"ignore": [], "fields": fields})')),
    ("setup: the name of the rule does not hang on the name of the command input", R, sh('"ignore": sorted(ignored), "fields": fields})', '"ignore": sorted(ignored), "fields": {}})')),
    ("setup: the words for a command that runs free are changed", R, one('    _fine = "every part of the command only reads, or is a command you allow"\n', '    _fine = "the command only reads"\n')),
    # ---- the rules set's shell cases ----
    ("set: rm is on the set's list of the owner's commands", S, one(SET_RULE, 'shell = rules.shell(allow=["pytest", "git add", "git commit", "rm"], ignore=["timeout"])')),
    ("set: every git command is on the set's list", S, one(SET_RULE, 'shell = rules.shell(allow=["pytest", "git"], ignore=["timeout"])')),
    ("set: the set's shell rule has no commands of the owner's", S, one(SET_RULE, 'shell = rules.shell(ignore=["timeout"])')),
    ("set: the set's shell rule is not told to ignore the time limit", S, one(SET_RULE, 'shell = rules.shell(allow=["pytest", "git add", "git commit"])')),
    ("set: the set's shell rule is told to ignore the folder too", S, one(SET_RULE, 'shell = rules.shell(allow=["pytest", "git add", "git commit"], ignore=["timeout", "cwd"])')),
    ("set: the command tool runs without the rule", S, one(SET_TOOL, 'checkpoint.tool("run_command", desk.run_command, level="free")')),
    ("set: the command tool always asks", S, one(SET_TOOL, 'checkpoint.tool("run_command", desk.run_command, level="needs_yes")')),
    ("set: a command is not counted as the desk acting", S, one("return len(self.sent) + len(self.paid) + len(self.fetched) + len(self.commands)", "return len(self.sent) + len(self.paid) + len(self.fetched)")),
    ("set: the command tool does nothing", S, one("        self.commands.append(command)\n", "")),
    ("set: a shell case is taken out", S, without_line('RulesCase("shell-delete", SHELL,')),
    ("set: a wipe case is taken out", S, without_line('RulesCase("shell-wipe-cd", SHELL,')),
    ("set: a normal shell job is taken out", S, without_line('RulesCase("normal-shell-git", NORMAL,')),
    ("set: a known limit of the shell rule is taken out", S, without_line('"limit-shell-own-options", LIMITS,')),
    ("set: a shell trick is expected to run", S, one('_sh("rm -rf build"), ASKS)', '_sh("rm -rf build"), RUNS)')),
    ("set: a wipe is expected to ask", S, one('''_sh("rm -rf /"), NEVER)''', '''_sh("rm -rf /"), ASKS)''')),
    ("set: a delete is expected to be refused", S, one('_sh("ls && rm notes.txt"), ASKS)', '_sh("ls && rm notes.txt"), NEVER)')),
    ("set: a normal shell job is expected to ask", S, one('_sh("ls -la src"), RUNS)', '_sh("ls -la src"), ASKS)')),
    ("set: the set's commands are sent to another tool", S, one('return lambda: _try([("run_command", {"command": command, **more})])', 'return lambda: _try([("fetch", {"url": f"https://{DOCS}/"})])')),
    ("set: the other inputs of a command are dropped", S, one('{"command": command, **more}', '{"command": command}')),
]

MUTANTS += [(f"path: /{name} is not a top folder", R, drop("_TOP_FOLDERS", name)) for name in TOP]
MUTANTS += [(f"wipe: what follows {name} is not looked at", R, drop("_ADMIN", name)) for name in ADMIN]
MUTANTS += [(f"wipe: what follows {name} is not looked at", R, drop("_WRAPPERS", name)) for name in WRAPPERS]
MUTANTS += [(f"wipe: text handed to {name} is not read", R, drop("_SHELLS", name)) for name in SHELLS]
MUTANTS += [(f"wipe: {name} is not known to join its words into one line", R, item("_JOINED", name)) for name in JOINED]
MUTANTS += [(f"wipe: diskutil {name} is not known", R, one(f"(?:{name}|", "(?:") if name == ERASES[0] else one(f"|{name}", "")) for name in ERASES]
MUTANTS += [(f"wipe: {name} is not a quiet place to write", R, item("_QUIET_DEVICES", name)) for name in QUIET_DEVICES]
MUTANTS += [(f"reader: {name} is not known to only read", R, drop("_PLAIN_READS", name)) for name in PLAIN]
MUTANTS += [(f"reader: {name} --version is not free", R, drop("_VERSIONS", name)) for name in VERSIONS]
MUTANTS += [(f"reader: find {name} is not known as a way of looking", R, drop("_FIND_LOOKS", name)) for name in FIND_LOOKS]
MUTANTS += [(f"reader: find {name} is not known as something find does", R, drop("_FIND_ACTS", name)) for name in FIND_ACTS]
MUTANTS += [(f"reader: tree {name} is not known", R, drop("_TREE_LOOKS", name)) for name in TREE_LOOKS]
MUTANTS += [(f"reader: file {name} is not known", R, drop("_FILE_LOOKS", name)) for name in FILE_LOOKS]
MUTANTS += [(f"reader: {name} is not known as a careful reader", R, one(f'"{name}": _{name}, ', "") if name != "git" else one(', "git": _git}', "}")) for name in "sort uniq find rg tree file date hostname sed git".split()]
MUTANTS += [(f"git: {name} is not known to only read", R, drop("_GIT_READS", name)) for name in GIT_READS]
MUTANTS += [(f"git: branch {name} is not known as a way of looking", R, drop("_BRANCH_LOOKS", name)) for name in BRANCH_LOOKS]
MUTANTS += [(f"other: {name} is not known to delete", R, drop("_DELETES", name)) for name in DELETES]
MUTANTS += [(f"other: {name} is not known to run program text", R, drop("_INTERPRETERS", name)) for name in INTERPRETERS]
MUTANTS += [(f"other: {name} is not known to reach the network", R, drop("_NETWORK", name)) for name in NETWORK]
MUTANTS += [(f"other: {name} is not known to download and run", R, drop("_RUNNERS", name)) for name in RUNNERS]
MUTANTS += [(f"other: {name} is not known to install", R, drop("_INSTALLERS", name)) for name in INSTALLERS]
MUTANTS += [(f"other: the word {name} is not known to mean an install", R, drop("_INSTALL_WORDS", name)) for name in INSTALL_WORDS]
MUTANTS += [(f"private: {name} is not known as a place for keys", R, item("_SECRET_NAMES", name)) for name in SECRET_NAMES]
MUTANTS += [(f"private: a file ending {name} is not known as a key", R, item("_SECRET_ENDINGS", name)) for name in SECRET_ENDINGS]
MUTANTS += [(f"private: a file with {name} in its name is free", R, item("_SECRET_WORDS", name)) for name in SECRET_WORDS]

KNOWN = {}


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
    print(f"{len(MUTANTS)} breaks, {bad} with a problem.")
    return bad


if __name__ == "__main__":
    if sys.argv[1:] == ["--dry"]:
        sys.exit(1 if dry() else 0)
    run(MUTANTS, TESTS, expected_to_survive=KNOWN)
