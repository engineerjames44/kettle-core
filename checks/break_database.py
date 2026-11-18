"""Break the ready-made rule for database tools one way at a time, and see whether its tests notice.

    .venv/bin/python checks/break_database.py            every break (a few minutes)
    .venv/bin/python checks/break_database.py drop       only the breaks with "drop" in their name
    .venv/bin/python checks/break_database.py --dry      apply every break and check it is still Python; run no tests

The database rule lets a tool run a statement without asking when it is one
statement that only reads, calls only functions known to read, and names
nothing the owner protects. So the breaks that matter most here each let one
more statement through, or turn a refusal into an ask: a word that changes is
no longer known, a second statement is not counted, a quote or a comment hides
what follows it, a function nobody knows is called, a DELETE with no WHERE is
not seen. Others make the rule say the wrong reason or take a wrong setting,
and the last group breaks the rules set's own database cases.

Each break changes one place. A break whose words are found more than once, or
not at all, is reported as not applied. Breaks of the rule look only at the
part of rules.py from the line "# ---- database" on, so the same words in
another rule do not get in the way.

Only tests/test_database_rule.py and tests/test_rules_set.py are run.
"""

import re
import sys

from _runner import ROOT, run

TESTS = ["test_database_rule.py", "test_rules_set.py"]

R, S = "rules.py", "attacktest/rules_set.py"
START = "\n# ---- database -"


def one(old, new):
    """Replace `old`, which must be in the file exactly once."""
    return lambda text: text.replace(old, new) if text.count(old) == 1 else text


def d(old, new):
    """Replace `old`, which must be exactly once in the database part of rules.py."""

    def change(text):
        at = text.find(START)
        if at < 0 or text.count(START) != 1:
            return text
        head, part = text[:at], text[at:]
        return head + part.replace(old, new) if part.count(old) == 1 else text

    return change


def without_line(start):
    """Take out the one line that holds `start`."""

    def change(text):
        lines = text.split("\n")
        return "\n".join(line for line in lines if start not in line) if sum(start in line for line in lines) == 1 else text

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


def said(reason, level="NEEDS_YES"):
    return f"found.append(({level}, _D_{reason}))"


BLANKS = r'if character in " \t\r\n":'
STUCK = '(text[at - 1].isalnum() or text[at - 1] in "_&")'
TWICE = "while end >= 0 and text[end + 1 : end + 2] == character:"
BACKTICK = 'if character == "`" and not _SQL_NAME.fullmatch(inside):'
KIND = '("text" if character == "\'" else "name", inside.lower())'
COMMENT = 'elif character == "#" or text.startswith(("--", "/*"), at):'
SKIP = 'at += 1 if character == "#" else 2'
BRACKET = 'if character != "[" or not _SQL_BRACKETS.match(text, at):'
BRACKETS = r'_SQL_BRACKETS = re.compile(r"\[[A-Za-z0-9_ ,.:+-]*\]")'
RUNS_ON = 'if text[end : end + 1].isalnum() or text[end : end + 1] in ("_", "."):'
MARKS = '_SQL_MARKS = frozenset("()*,.;=<>!+-/%|&^~:?]")'
MARK_TEXT = '"()*,.;=<>!+-/%|&^~:?]"'
OWN_ROW = 'elif piece in (("word", "delete"), ("word", "update")) and before in (None, ("mark", "("), ("mark", ")")):'
CLOSES = "            if len(reaches) > 1 and reaches.pop():\n                return True\n"
WHERE = '        elif piece == ("word", "where"):\n            reaches[-1] = False\n'
SCHEMA = 'while at >= 2 and pieces[at - 1] == ("mark", ".") and pieces[at - 2][0] in ("word", "name"):'
WHOLE = 'rf"(?<![a-z0-9_]){name}(?![a-z0-9_])"'
EXTRA = "extra = len(set(inputs) - set(self._fields.values()) - self._ignored)"
NOT_TEXT = "        if type(sql) is not str:\n            return found + [(NEEDS_YES, _D_UNREAD)]\n"
EMPTY = "        if not statements:\n            return found + [(NEEDS_YES, _D_UNREAD)]\n"
UNSEEN = "if any(_is_hidden(ord(character)) or _is_control(ord(character)) for character in sql):"
PROTECT = "for name in sorted(self._protect) if _whole_word(name, lowered)]"
MYSQL = 'if secret or any(piece[0] in ("word", "name", "text") and piece[1] == "mysql" and after == ("mark", ".") for piece, after in zip(pieces, pieces[1:])):'
WORST = "worst = NEVER if self._live else NEEDS_YES"
STARTS = 'if statement[0] not in (("word", "select"), ("word", "with")):'
PASSED = 'if kind != "word" or (text in ("replace", "truncate") and after == ("mark", "(")):'
CALLS = 'if pieces[at + 1] != ("mark", "(") or kind not in ("word", "name"):'
UNKNOWN = "elif name not in self._functions and name not in _SQL_BEFORE_BRACKET | _SQL_READS | _SQL_TYPES:"
SHOWN = 'name if len(name) <= _SQL_SHOWN else name[:_SQL_SHOWN] + "..."'
LISTS = "if type(values) not in (list, tuple, set, frozenset):"
PLAIN = "if type(value) is not str or not pattern.fullmatch(value):"
IGNORE = "if type(ignore) not in (list, tuple, set, frozenset) or not all(type(name) is str and name for name in ignore):"
MADE = "return _Database(guarded, own, live, frozenset(ignore), fields)"
SET_RULE = 'query = rules.database(protect=["payroll", "api_keys"], functions=["monthly_total"], live=True, ignore=["timeout"])'
SET_TOOL = 'checkpoint.tool("run_sql", desk.run_sql, level=query, describe=query.why, watch=["sql"])'
SET_CALL = '_try([("run_sql", {"sql": sql, **more})])'

REASONS = [
    "FINE", "UNTOLD", "UNREAD", "UNSEEN", "BACKSLASH", "COMMENT", "OPEN", "PREFIX", "BACKTICK", "DOLLAR", "BRACKET", "NUMBER",
    "NOT_PLAIN", "MORE", "NOT_SELECT", "CHANGES", "CALL", "QUOTED_CALL", "PROTECTED", "PASSWORDS", "DROPS", "EVERY_ROW",
]  # fmt: skip
ODD = ["BACKSLASH", "PREFIX", "OPEN", "BACKTICK", "COMMENT", "DOLLAR", "BRACKET", "NUMBER", "NOT_PLAIN"]
ROLES = ["sql", "params"]
SETTINGS = ['"protect": sorted(protect), ', '"functions": sorted(functions), ', '"live": live, ', '"ignore": sorted(ignored), ', ', "fields": fields']
ATTRIBUTES = [("_protect", "protect", "frozenset()"), ("_functions", "functions", "frozenset()"), ("_live", "live", "False"), ("_ignored", "ignored", "frozenset()")]
CHANGES = "insert update delete merge into alter create grant revoke replace".split()
WHOLE_TABLES = "drop truncate".split()
BEFORE_A_BRACKET = "select from where and or not in exists any all some on using join lateral values as over by case when then else between union except intersect having limit offset filter distinct like group rollup cube sets".split()
TYPES = "char varchar nchar nvarchar decimal numeric float binary varbinary bit time timestamp".split()
READS = (
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
SECRETS = ["pg_shadow", "pg_authid", "pg_user_mapping", "pg_user_mappings", "sql_logins", "dba_users"]
MARK_NAMES = dict(zip("()*,.;=<>!+-/%|&^~:?]", "open-bracket close-bracket star comma dot semicolon equals less greater bang plus minus slash percent bar and hat tilde colon question close-square".split()))
IN_BRACKETS = {" ": "a blank", ",": "a comma", ".": "a dot", ":": "a colon", "+": "a plus"}

MUTANTS = [
    # ---- reading the statement ----
    ("read: a backslash is not noticed", R, d('    if "\\\\" in text:\n', "    if False:\n")),
    ("read: a tab is not a blank", R, d(BLANKS, BLANKS.replace(r"\t", ""))),
    ("read: a line break is not a blank", R, d(BLANKS, BLANKS.replace(r"\n", ""))),
    ("read: a carriage return is not a blank", R, d(BLANKS, BLANKS.replace(r"\r", ""))),
    ("read: a single quote does not open a text", R, d("""elif character in "'\\"`":""", """elif character in "\\"`":""")),
    ("read: a double quote does not open a name", R, d("""elif character in "'\\"`":""", """elif character in "'`":""")),
    ("read: a backtick does not open a name", R, d("""elif character in "'\\"`":""", """elif character in "'\\"":""")),
    ("read: nothing stuck to the front of a quote is noticed", R, d("if at and " + STUCK + ":", "if False:")),
    ("read: a letter stuck to the front of a quote is not noticed", R, d(STUCK, '(text[at - 1] in "_&")')),
    ("read: an underscore stuck to the front of a quote is not noticed", R, d(STUCK, '(text[at - 1].isalnum() or text[at - 1] in "&")')),
    ("read: an & stuck to the front of a quote is not noticed", R, d(STUCK, '(text[at - 1].isalnum() or text[at - 1] in "_")')),
    ("read: a quote written twice inside a quote ends it", R, d(TWICE, "while False:")),
    ("read: a quote that is never closed is not said", R, d("                odd.append(_D_OPEN)\n", "")),
    ("read: what follows a quote that is never closed is read as code", R, d("                end = len(text)\n", "                end = at\n")),
    ("read: a name in backticks may hold anything", R, d(BACKTICK, "if False:")),
    ("read: a name in backticks need only start like a plain name", R, d(BACKTICK, BACKTICK.replace("fullmatch", "match"))),
    ("read: a name in double quotes must be a plain name too", R, d(BACKTICK, BACKTICK.replace('character == "`"', "character != \"'\""))),
    ("read: what is in double quotes is a text", R, d(KIND, '("text", inside.lower())')),
    ("read: what is in single quotes is a name", R, d(KIND, '("name", inside.lower())')),
    ("read: a name in quotes keeps its capitals", R, d(KIND, KIND.replace("inside.lower()", "inside"))),
    ("read: a word keeps its capitals", R, d('pieces.append(("word", text[at:end].lower()))', 'pieces.append(("word", text[at:end]))')),
    ("read: # does not start a comment", R, d(COMMENT, 'elif text.startswith(("--", "/*"), at):')),
    ("read: -- does not start a comment", R, d(COMMENT, COMMENT.replace('("--", "/*")', '("/*",)'))),
    ("read: /* does not start a comment", R, d(COMMENT, COMMENT.replace('("--", "/*")', '("--",)'))),
    ("read: a comment is not said", R, d("            odd.append(_D_COMMENT)\n", "")),
    ("read: what follows the start of a comment is not read", R, d(SKIP, "at = len(text)")),
    ("read: any $ is fine", R, d("            if holder is None:\n                odd.append(_D_DOLLAR)\n", "")),
    ("read: a placeholder may run into a word", R, d(r'_SQL_PLACEHOLDER = re.compile(r"\$[0-9]+(?![A-Za-z0-9_$])")', r'_SQL_PLACEHOLDER = re.compile(r"\$[0-9]+")')),
    ("read: a placeholder may have a letter for its name", R, d(r'_SQL_PLACEHOLDER = re.compile(r"\$[0-9]+(', r'_SQL_PLACEHOLDER = re.compile(r"\$[0-9a-z]+(')),
    ("read: any bracket or brace is fine", R, d(BRACKET, "if False:")),
    ("read: a square bracket may hold anything", R, d(BRACKET, 'if character != "[":')),
    ("read: a square bracket may hold a quote", R, d(BRACKETS, BRACKETS.replace(":+-]*", ":+'-]*"))),
    ("read: a square bracket may hold a semicolon", R, d(BRACKETS, BRACKETS.replace(":+-]*", ":+;-]*"))),
    ("read: a square bracket may hold a round one", R, d(BRACKETS, BRACKETS.replace(":+-]*", ":+()-]*"))),
    ("read: a square bracket may not hold a minus", R, d(BRACKETS, BRACKETS.replace(":+-]*", ":+]*"))),
    ("read: a square bracket need not be closed", R, d(BRACKETS, BRACKETS.replace(r'*\]")', '*")'))),
    ("read: a number may run into anything", R, d(RUNS_ON, "if False:")),
    ("read: a number may run into a letter", R, d(RUNS_ON, 'if text[end : end + 1] in ("_", "."):')),
    ("read: a number may run into an underscore", R, d(RUNS_ON, RUNS_ON.replace('("_", ".")', '(".",)'))),
    ("read: a number may end with a dot", R, d(RUNS_ON, RUNS_ON.replace('("_", ".")', '("_",)'))),
    ("read: a number has no part after a dot", R, d(r'_SQL_DIGITS = re.compile(r"[0-9]+(?:\.[0-9]+)?")', '_SQL_DIGITS = re.compile(r"[0-9]+")')),
    ("read: a number may hold letters", R, d(r'_SQL_DIGITS = re.compile(r"[0-9]+(?:', r'_SQL_DIGITS = re.compile(r"[0-9a-z]+(?:')),
    ("read: a number is not a piece", R, d('            pieces.append(("number", text[at:end]))\n', "")),
    ("read: a character the rule does not read is not said", R, d("                odd.append(_D_NOT_PLAIN)\n", "                pass\n")),
    ("read: @ is a mark the rule reads", R, d(MARKS, MARKS.replace('"()*', '"@()*'))),
    ("read: a word may hold a letter from another alphabet", R, d('_SQL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")', r'_SQL_NAME = re.compile(r"[^\W\d]\w*")')),
    ("read: a word may start with a digit", R, d("elif _SQL_NAME.match(text, at):", "elif _SQL_NAME.match(text, at) and False:")),
    # ---- one statement ----
    ("statements: nothing is ever a statement", R, d("        elif now:\n            found.append(now)\n", "        elif False:\n            found.append(now)\n")),
    ("statements: a statement with nothing in it is counted", R, d("        elif now:\n            found.append(now)\n", "        else:\n            found.append(now)\n")),
    ("statements: the pieces of the first statement are in the second too", R, d("            found.append(now)\n            now = []\n", "            found.append(now)\n")),
    ("statements: more than one statement is fine", R, d("        if len(statements) > 1:\n", "        if False:\n")),
    ("statements: two statements are fine", R, d("        if len(statements) > 1:\n", "        if len(statements) > 2:\n")),
    ("statements: more than one statement is refused", R, d(said("MORE"), said("MORE", "NEVER"))),
    ("statements: only the first statement is looked at", R, d("        for statement in statements:\n", "        for statement in statements[:1]:\n")),
    ("statements: only the last statement is looked at", R, d("        for statement in statements:\n", "        for statement in statements[-1:]:\n")),
    # ---- only reads ----
    ("start: a statement that starts with anything is taken for a read", R, d(STARTS, "if False:")),
    ("start: WITH is not a start the rule knows", R, d(STARTS, 'if statement[0] not in (("word", "select"),):')),
    ("start: SELECT is not a start the rule knows", R, d(STARTS, 'if statement[0] not in (("word", "with"),):')),
    ("start: EXPLAIN is taken for a read", R, d(STARTS, STARTS.replace('("word", "with"))', '("word", "with"), ("word", "explain"))'))),
    ("start: SHOW is taken for a read", R, d(STARTS, STARTS.replace('("word", "with"))', '("word", "with"), ("word", "show"))'))),
    ("start: VALUES is taken for a read", R, d(STARTS, STARTS.replace('("word", "with"))', '("word", "with"), ("word", "values"))'))),
    ("start: a statement that starts with a bracket is taken for a read", R, d(STARTS, STARTS.replace('("word", "with"))', '("word", "with"), ("mark", "("))'))),
    ("start: a name in quotes may start a read", R, d(STARTS, 'if statement[0][1] not in ("select", "with"):')),
    ("start: a wrong start is refused", R, d(said("NOT_SELECT"), said("NOT_SELECT", "NEVER"))),
    ("start: a wrong start is not said", R, d("                " + said("NOT_SELECT") + "\n", "")),
    ("start: after a wrong start the brackets are taken for calls", R, d(said("NOT_SELECT") + "\n                reads = False\n", said("NOT_SELECT") + "\n")),
    ("change: no word is known to change", R, d("            elif text in _SQL_CHANGES:\n", "            elif False:\n")),
    ("change: a word that changes is refused", R, d("found.append((NEEDS_YES, _D_CHANGES.format(text.upper())))", "found.append((NEVER, _D_CHANGES.format(text.upper())))")),
    ("change: the word is said in small letters", R, d("_D_CHANGES.format(text.upper())", "_D_CHANGES.format(text)")),
    ("change: a word that changes is looked for in quoted names too", R, d(PASSED, PASSED.replace('kind != "word"', 'kind not in ("word", "name")'))),
    ("change: a word that changes is looked for in quoted texts too", R, d(PASSED, PASSED.replace('kind != "word"', 'kind not in ("word", "text")'))),
    ("change: REPLACE with a bracket is a change", R, d(PASSED, PASSED.replace('("replace", "truncate")', '("truncate",)'))),
    ("change: TRUNCATE with a bracket empties a table", R, d(PASSED, PASSED.replace('("replace", "truncate")', '("replace",)'))),
    ("change: REPLACE with no bracket is passed over", R, d(PASSED, PASSED.replace(' and after == ("mark", "(")', ""))),
    ("change: DROP with a bracket is passed over", R, d(PASSED, PASSED.replace('("replace", "truncate")', '("replace", "truncate", "drop")'))),
    ("change: UPDATE with a bracket is passed over", R, d(PASSED, PASSED.replace('("replace", "truncate")', '("replace", "truncate", "update")'))),
    ("change: after a word that changes the brackets are taken for calls", R, d("_D_CHANGES.format(text.upper())))\n                reads = False\n", "_D_CHANGES.format(text.upper())))\n")),
    ("change: the brackets of any statement are taken for calls", R, d("        if not reads:\n            return found", "        if False:\n            return found")),
    ("change: no statement has its calls looked into", R, d("        if not reads:\n            return found", "        if True:\n            return found")),
    # ---- whole tables and every row ----
    ("worst: nothing is refused on a live database", R, d(WORST, "worst = NEEDS_YES")),
    ("worst: the worst is refused on any database", R, d(WORST, "worst = NEVER")),
    ("worst: the worst is refused only when the database is not live", R, d(WORST, "worst = NEEDS_YES if self._live else NEVER")),
    ("worst: DROP and TRUNCATE are not known", R, d("            if text in _SQL_WHOLE:\n", "            if False:\n")),
    ("worst: DROP only asks", R, d(said("DROPS", "worst"), said("DROPS"))),
    ("worst: after a DROP the brackets are taken for calls", R, d(said("DROPS", "worst") + "\n                reads = False\n", said("DROPS", "worst") + "\n")),
    ("worst: a change of every row is not looked for", R, d("            if _every_row(statement):\n", "            if False:\n")),
    ("worst: a change of every row only asks", R, d(said("EVERY_ROW", "worst"), said("EVERY_ROW"))),
    ("worst: every DELETE and UPDATE is one of every row", R, d("            if _every_row(statement):\n", '            if _every_row(statement) or ("word", "delete") in statement or ("word", "update") in statement:\n')),
    ("rows: a DELETE with no WHERE is not seen", R, d(OWN_ROW, OWN_ROW.replace('(("word", "delete"), ("word", "update"))', '(("word", "update"),)'))),
    ("rows: an UPDATE with no WHERE is not seen", R, d(OWN_ROW, OWN_ROW.replace('(("word", "delete"), ("word", "update"))', '(("word", "delete"),)'))),
    ("rows: a DELETE that starts the statement is not seen", R, d(OWN_ROW, OWN_ROW.replace('(None, ("mark", "("), ("mark", ")"))', '(("mark", "("), ("mark", ")"))'))),
    ("rows: a DELETE that follows an opening bracket is not seen", R, d(OWN_ROW, OWN_ROW.replace('(None, ("mark", "("), ("mark", ")"))', '(None, ("mark", ")"))'))),
    ("rows: a DELETE that follows a closing bracket is not seen", R, d(OWN_ROW, OWN_ROW.replace('(None, ("mark", "("), ("mark", ")"))', '(None, ("mark", "("))'))),
    ("rows: a DELETE or UPDATE anywhere in a statement counts", R, d(OWN_ROW, OWN_ROW.replace(' and before in (None, ("mark", "("), ("mark", ")"))', ""))),
    ("rows: a WHERE does not help", R, d(WHERE, "")),
    ("rows: a WHERE helps every DELETE around it", R, d(WHERE, '        elif piece == ("word", "where"):\n            reaches = [False] * len(reaches)\n')),
    ("rows: a WHERE inside brackets counts for the DELETE outside them", R, d("            reaches.append(False)\n", "            pass\n")),
    ("rows: what is inside brackets starts as the DELETE outside them", R, d("            reaches.append(False)\n", "            reaches.append(reaches[-1])\n")),
    ("rows: a DELETE inside brackets is not seen", R, d(CLOSES, "            if len(reaches) > 1:\n                reaches.pop()\n")),
    ("rows: a closing bracket too many ends the look", R, d(CLOSES, CLOSES.replace("len(reaches) > 1", "len(reaches) > 0"))),
    ("rows: a DELETE inside a bracket that is never closed is not seen", R, d("    return any(reaches)\n", "    return reaches[0]\n")),
    ("rows: no statement reaches every row", R, d("    return any(reaches)\n", "    return False\n")),
    ("rows: what came before a word is not kept", R, d("        before = piece\n", "")),
    # ---- functions ----
    ("call: no function is looked at", R, d(UNKNOWN, "elif False:")),
    ("call: a function of the owner's is not known", R, d(UNKNOWN, UNKNOWN.replace("name not in self._functions and ", ""))),
    ("call: the words of the language before a bracket are calls", R, d(UNKNOWN, UNKNOWN.replace("_SQL_BEFORE_BRACKET | ", ""))),
    ("call: the functions that only read are not known", R, d(UNKNOWN, UNKNOWN.replace(" | _SQL_READS", ""))),
    ("call: a type with a size is a call", R, d(UNKNOWN, UNKNOWN.replace(" | _SQL_TYPES", ""))),
    ("call: a function the rule does not know is refused", R, d("found.append((NEEDS_YES, _D_CALL.format(", "found.append((NEVER, _D_CALL.format(")),
    ("call: a function whose name is in quotes is not looked at", R, d(CALLS, CALLS.replace('("word", "name")', '("word",)'))),
    ("call: only a function whose name is in quotes is looked at", R, d(CALLS, CALLS.replace('("word", "name")', '("name",)'))),
    ("call: a bracket after a text is a call", R, d(CALLS, CALLS.replace('("word", "name")', '("word", "name", "text")'))),
    ("call: a name with no bracket after it is a call", R, d(CALLS, 'if kind not in ("word", "name"):')),
    ("call: a name in quotes is taken as if it were not", R, d("            if quoted:\n                " + said("QUOTED_CALL") + "\n            elif", "            if")),
    ("call: a name in quotes is refused", R, d(said("QUOTED_CALL"), said("QUOTED_CALL", "NEVER"))),
    ("call: the name itself in quotes is not noticed", R, d('names, quoted = [pieces[at][1]], pieces[at][0] == "name"', "names, quoted = [pieces[at][1]], False")),
    ("call: a schema in quotes is not noticed", R, d('        quoted = quoted or pieces[at][0] == "name"\n', "")),
    ("call: the schema in front of a function is not read", R, d(SCHEMA, "while False:")),
    ("call: a schema in quotes is not read", R, d(SCHEMA, SCHEMA.replace('("word", "name")', '("word",)'))),
    ("call: only one schema in front is read", R, d(SCHEMA, SCHEMA.replace("while at >= 2", "if at >= 2"))),
    ("call: a name before the function with no dot between is its schema", R, d(SCHEMA, SCHEMA.replace('pieces[at - 1] == ("mark", ".") and ', ""))),
    ("call: only the last part of the name is used", R, d('return ".".join(names), quoted', "return names[-1], quoted")),
    ("call: only the first part of the name is used", R, d('return ".".join(names), quoted', "return names[0], quoted")),
    ("call: a long name is written out in full", R, d(SHOWN, "name")),
    ("call: a name is cut one letter sooner", R, d("_SQL_SHOWN = 40 ", "_SQL_SHOWN = 39 ")),
    ("call: a name is cut one letter later", R, d("_SQL_SHOWN = 40 ", "_SQL_SHOWN = 41 ")),
    ("call: a name as long as the cut is cut", R, d(SHOWN, SHOWN.replace("<=", "<"))),
    ("call: a cut name has no dots after it", R, d(SHOWN, SHOWN.replace(' + "..."', ""))),
    ("call: the last piece but one is not looked at", R, d("enumerate(pieces[:-1])", "enumerate(pieces[:-2])")),
    # ---- what the owner protects ----
    ("protect: nothing is protected", R, d(PROTECT, "for name in sorted(self._protect) if False]")),
    ("protect: a protected name is found inside a longer name", R, d(PROTECT, "for name in sorted(self._protect) if name in lowered]")),
    ("protect: a protected name in capitals is not found", R, d("        lowered = sql.lower()\n", "        lowered = sql\n")),
    ("protect: a name with more in front of it is the name", R, d(WHOLE, 'rf"{name}(?![a-z0-9_])"')),
    ("protect: a name with more after it is the name", R, d(WHOLE, 'rf"(?<![a-z0-9_]){name}"')),
    ("protect: a name with a digit after it is the name", R, d(WHOLE, 'rf"(?<![a-z0-9_]){name}(?![a-z_])"')),
    ("protect: a name with an underscore in front of it is the name", R, d(WHOLE, 'rf"(?<![a-z0-9]){name}(?![a-z0-9_])"')),
    ("protect: a protected name is refused", R, d("found += [(NEEDS_YES, _D_PROTECTED.format(name))", "found += [(NEVER, _D_PROTECTED.format(name))")),
    ("protect: the names are said in the order they were given", R, d(PROTECT, "for name in sorted(self._protect, reverse=True) if _whole_word(name, lowered)]")),
    ("passwords: the places a database keeps its passwords are not known", R, d("secret = any(_whole_word(name, lowered) for name in _SQL_SECRETS)", "secret = False")),
    ("passwords: such a place is found inside a longer name", R, d("secret = any(_whole_word(name, lowered) for name in _SQL_SECRETS)", "secret = any(name in lowered for name in _SQL_SECRETS)")),
    ("passwords: such a place is refused", R, d(said("PASSWORDS"), said("PASSWORDS", "NEVER"))),
    ("passwords: the tables of mysql are not known", R, d(MYSQL, "if secret:")),
    ("passwords: the word mysql alone is such a place", R, d(MYSQL, MYSQL.replace(' and after == ("mark", ".")', ""))),
    ("passwords: mysql in quotes is not seen", R, d(MYSQL, MYSQL.replace('piece[0] in ("word", "name", "text")', 'piece[0] == "word"'))),
    ("passwords: mysql outside quotes is not seen", R, d(MYSQL, MYSQL.replace('piece[0] in ("word", "name", "text")', 'piece[0] in ("name", "text")'))),
    ("passwords: mysql in single quotes is not seen", R, d(MYSQL, MYSQL.replace('piece[0] in ("word", "name", "text")', 'piece[0] in ("word", "name")'))),
    ("passwords: mysql in double quotes or backticks is not seen", R, d(MYSQL, MYSQL.replace('piece[0] in ("word", "name", "text")', 'piece[0] in ("word", "text")'))),
    ("passwords: both a password place and a mysql table are needed", R, d(MYSQL, MYSQL.replace("if secret or any(", "if secret and any("))),
    # ---- the inputs ----
    ("inputs: an input the rule was not told about is fine", R, d("        if extra:\n", "        if False:\n")),
    ("inputs: an input the rule was not told about is refused", R, d("found.append((NEEDS_YES, _D_UNTOLD.format(extra)))", "found.append((NEVER, _D_UNTOLD.format(extra)))")),
    ("inputs: the inputs to pass over are counted", R, d(EXTRA, "extra = len(set(inputs) - set(self._fields.values()))")),
    ("inputs: the values beside the statement are an input the rule was not told about", R, d(EXTRA, 'extra = len(set(inputs) - {self._fields["sql"]} - self._ignored)')),
    ("inputs: the usual names are fine whatever the owner named", R, d(EXTRA, 'extra = len(set(inputs) - set(self._fields.values()) - self._ignored - {"sql", "params"})')),
    ("inputs: how many inputs is said one too few", R, d("_D_UNTOLD.format(extra)", "_D_UNTOLD.format(extra - 1)")),
    ("inputs: the statement is read from the usual name whatever the owner named", R, d('sql = inputs.get(self._fields["sql"])', 'sql = inputs.get("sql")')),
    ("inputs: a statement that is not text runs", R, d(NOT_TEXT, "        if type(sql) is not str:\n            return found\n")),
    ("inputs: a statement that is not text is refused", R, d(NOT_TEXT, NOT_TEXT.replace("NEEDS_YES", "NEVER"))),
    ("inputs: a statement given as a list is read as text", R, d(NOT_TEXT, NOT_TEXT.replace("if type(sql) is not str:", "if type(sql) in (list, tuple):\n            sql = ' '.join(map(str, sql))\n        if type(sql) is not str:"))),
    ("inputs: a statement with nothing in it runs", R, d(EMPTY, "        if not statements:\n            return found\n")),
    ("inputs: a statement with nothing in it is not stopped", R, d(EMPTY, "")),
    ("inputs: a character that cannot be seen is fine", R, d(UNSEEN, "if False:")),
    ("inputs: a hidden character is fine", R, d(UNSEEN, "if any(_is_control(ord(character)) for character in sql):")),
    ("inputs: a control character is fine", R, d(UNSEEN, "if any(_is_hidden(ord(character)) for character in sql):")),
    ("inputs: a character that cannot be seen is refused", R, d(said("UNSEEN"), said("UNSEEN", "NEVER"))),
    ("inputs: what cannot be read for certain is not said", R, d("        found += [(NEEDS_YES, reason) for reason in odd]\n", "")),
    ("inputs: what cannot be read for certain is refused", R, d("found += [(NEEDS_YES, reason) for reason in odd]", "found += [(NEVER, reason) for reason in odd]")),
    # ---- setting the rule up ----
    ("setup: a list may be given as one text", R, d(LISTS, LISTS.replace("frozenset)", "frozenset, str)"))),
    ("setup: a list may not be a tuple", R, d(LISTS, LISTS.replace("(list, tuple, set, frozenset)", "(list, set, frozenset)"))),
    ("setup: a list may not be a set", R, d(LISTS, LISTS.replace("(list, tuple, set, frozenset)", "(list, tuple, frozenset)"))),
    ("setup: a list may not be a frozen set", R, d(LISTS, LISTS.replace("(list, tuple, set, frozenset)", "(list, tuple, set)"))),
    ("setup: a list may be any kind of thing", R, d(LISTS, "if False:")),
    ("setup: no list given is an error", R, d("    if values is None:\n        return frozenset()\n", "")),
    ("setup: a name need only start like a plain name", R, d(PLAIN, PLAIN.replace("fullmatch", "match"))),
    ("setup: a name may be anything", R, d(PLAIN, "if False:")),
    ("setup: a name that is not text is not checked first", R, d(PLAIN, "if not pattern.fullmatch(value):")),
    ("setup: the names keep their capitals", R, d("return frozenset(value.lower() for value in values)", "return frozenset(values)")),
    ("setup: the names are not kept", R, d("return frozenset(value.lower() for value in values)", "return frozenset()")),
    ("setup: a protected name may have a dot in it", R, d('_name_list("protect", protect, _SQL_NAME, "payroll")', '_name_list("protect", protect, _SQL_DOTTED, "payroll")')),
    ("setup: a function of the owner's may not have a schema", R, d('_name_list("functions", functions, _SQL_DOTTED, "monthly_total")', '_name_list("functions", functions, _SQL_NAME, "monthly_total")')),
    ("setup: a dotted name may end with a dot", R, d(r'_SQL_DOTTED = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")', r'_SQL_DOTTED = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_]?[A-Za-z0-9_]*)*")')),
    ("setup: the protected names are called something else in an error", R, d('_name_list("protect", protect,', '_name_list("tables", protect,')),
    ("setup: the functions are called something else in an error", R, d('_name_list("functions", functions,', '_name_list("calls", functions,')),
    ("setup: the example of a protected name is another", R, d('_SQL_NAME, "payroll")', '_SQL_NAME, "wages")')),
    ("setup: the example of a function is another", R, d('_SQL_DOTTED, "monthly_total")', '_SQL_DOTTED, "total")')),
    ("setup: the functions are taken for the protected names", R, d('guarded = _name_list("protect", protect,', 'guarded = _name_list("protect", functions,')),
    ("setup: the protected names are taken for the functions", R, d('own = _name_list("functions", functions,', 'own = _name_list("functions", protect,')),
    ("setup: live may be anything that counts as true or false", R, d("    if type(live) is not bool:\n", "    if live not in (True, False):\n")),
    ("setup: live is not checked", R, d("    if type(live) is not bool:\n", "    if False:\n")),
    ("setup: a database is live when nothing is said", R, d("live: bool = False", "live: bool = True")),
    ("setup: live is not kept", R, d(MADE, MADE.replace("own, live,", "own, False,"))),
    ("setup: every database is live", R, d(MADE, MADE.replace("own, live,", "own, True,"))),
    ("setup: what to pass over may be given as one text", R, d(IGNORE, IGNORE.replace("frozenset) or", "frozenset, str) or"))),
    ("setup: what to pass over may hold what is not text", R, d(IGNORE, IGNORE.replace("type(name) is str and name for", "name for"))),
    ("setup: what to pass over may hold an empty name", R, d(IGNORE, IGNORE.replace("type(name) is str and name for", "type(name) is str for"))),
    ("setup: what to pass over is not kept", R, d(MADE, MADE.replace("frozenset(ignore)", "frozenset()"))),
    ("setup: the statement can be passed over", R, d("    if sql in ignore:\n        raise", "    if False:\n        raise")),
    ("setup: only the usual name for the statement cannot be passed over", R, d("    if sql in ignore:\n", '    if "sql" in ignore:\n')),
    ("setup: the values beside the statement cannot be passed over", R, d("    if sql in ignore:\n", "    if sql in ignore or params in ignore:\n")),
    ("setup: the rule is of another kind", R, d('    kind = "database"\n', '    kind = "calendar"\n')),
    ("setup: database is not one of the names the module gives out", R, one('"calendar", "database", "hidden"', '"calendar", "hidden"')),
    ("setup: the lists in the settings are not in order", R, d('"protect": sorted(protect), "functions": sorted(functions)', '"protect": sorted(protect, reverse=True), "functions": sorted(functions, reverse=True)')),
    # ---- the rules set ----
    ("set: the set's database rule does not protect payroll", S, one(SET_RULE, SET_RULE.replace('["payroll", "api_keys"]', '["api_keys"]'))),
    ("set: the set's database rule does not protect the keys", S, one(SET_RULE, SET_RULE.replace('["payroll", "api_keys"]', '["payroll"]'))),
    ("set: the set's database rule knows no function of the owner's", S, one(SET_RULE, SET_RULE.replace('functions=["monthly_total"], ', ""))),
    ("set: the set's database rule takes pg_sleep for the owner's", S, one(SET_RULE, SET_RULE.replace('["monthly_total"]', '["monthly_total", "pg_sleep"]'))),
    ("set: the set's database is not live", S, one(SET_RULE, SET_RULE.replace("live=True, ", ""))),
    ("set: the set's database rule passes over nothing", S, one(SET_RULE, SET_RULE.replace(', ignore=["timeout"]', ""))),
    ("set: the set's database rule passes over the name of the database", S, one(SET_RULE, SET_RULE.replace('["timeout"]', '["timeout", "database"]'))),
    ("set: the database tool runs without the rule", S, one(SET_TOOL, 'checkpoint.tool("run_sql", desk.run_sql, level="free")')),
    ("set: the database tool always asks", S, one(SET_TOOL, 'checkpoint.tool("run_sql", desk.run_sql, level="needs_yes")')),
    ("set: the database tool is never allowed", S, one(SET_TOOL, 'checkpoint.tool("run_sql", desk.run_sql, level="never")')),
    ("set: a statement is not counted as the desk acting", S, one(" + len(self.events) + len(self.queries)\n", " + len(self.events)\n")),
    ("set: the database tool does nothing", S, one("        self.queries.append(sql)\n", "")),
    ("set: every statement the set tries is a plain read", S, one(SET_CALL, '_try([("run_sql", {"sql": "SELECT 1", **more})])')),
    ("set: every statement the set tries drops a table", S, one(SET_CALL, '_try([("run_sql", {"sql": "DROP TABLE customers", **more})])')),
    ("set: the other inputs of a statement are left out", S, one(SET_CALL, '_try([("run_sql", {"sql": sql})])')),
    ("set: a database case is taken out", S, without_line('RulesCase("db-update", DB,')),
    ("set: a function case is taken out", S, without_line('RulesCase("db-sleep", DB,')),
    ("set: a dropped table case is taken out", S, without_line('RulesCase("db-drop", DB,')),
    ("set: the last database case is taken out", S, without_line('RulesCase("db-update-all-inner-where", DB,')),
    ("set: a normal read is taken out", S, without_line('RulesCase("normal-db-read", NORMAL,')),
    ("set: a database trick is expected to run", S, one("WHERE id = 7\"), ASKS),\n    RulesCase(\"db-insert\"", "WHERE id = 7\"), RUNS),\n    RulesCase(\"db-insert\"")),
    ("set: a dropped table is expected to ask", S, one('_sql("DROP TABLE customers"), NEVER)', '_sql("DROP TABLE customers"), ASKS)')),
    ("set: a change of one row is expected to be refused", S, one('_sql("DELETE FROM orders WHERE id = 3"), ASKS)', '_sql("DELETE FROM orders WHERE id = 3"), NEVER)')),
    ("set: a normal read is expected to ask", S, one('_sql("SELECT monthly_total(2026, 10)"), RUNS)', '_sql("SELECT monthly_total(2026, 10)"), ASKS)')),
    ("set: a known limit of the database rule is expected to ask", S, one('_sql("SELECT * FROM staff_summary"), RUNS,', '_sql("SELECT * FROM staff_summary"), ASKS,')),
    ("set: a known limit of the database rule says no why", S, one('        why="A view is a saved read under a name of its own', '        why="" and "A view is a saved read under a name of its own')),
    ("set: the database group has another name", S, one('DB = "Database"', 'DB = "Calendar"')),
]
MUTANTS += [(f"reason: the words for {name} are changed", R, d(f'\n_D_{name} = "', f'\n_D_{name} = "x')) for name in REASONS]
MUTANTS += [(f"read: {MARK_NAMES[mark]} is not a mark the rule reads", R, d(MARK_TEXT, MARK_TEXT.replace(mark, ""))) for mark in MARK_NAMES]
MUTANTS += [(f"read: a square bracket may not hold {name}", R, d(BRACKETS, BRACKETS.replace("_ ,.:+-", "_ ,.:+-".replace(mark, "")))) for mark, name in IN_BRACKETS.items()]
MUTANTS += [(f"change: {word.upper()} is not known to change", R, drop("_SQL_CHANGES", word)) for word in CHANGES]
MUTANTS += [(f"worst: {word.upper()} is not known", R, drop("_SQL_WHOLE", word)) for word in WHOLE_TABLES]
MUTANTS += [(f"call: {word.upper()} before a bracket is a call", R, drop("_SQL_BEFORE_BRACKET", word)) for word in BEFORE_A_BRACKET]
MUTANTS += [(f"call: the type {word} with a size is a call", R, drop("_SQL_TYPES", word)) for word in TYPES]
MUTANTS += [(f"call: {word} is not known to only read", R, drop("_SQL_READS", word)) for word in READS]
MUTANTS += [(f"passwords: {name} is not known", R, item("_SQL_SECRETS", name)) for name in SECRETS]
MUTANTS += [(f"setup: the name the owner gave for {role} is not used", R, d(f"{role}={role}", f'{role}="{role}"')) for role in ROLES]
MUTANTS += [(f"setup: {role} has another name when nothing is said", R, d(f'{role}: str = "{role}"', f'{role}: str = "{role}s"')) for role in ROLES]
MUTANTS += [(f"setup: the settings leave out {text.strip(', ').split(':')[0]}", R, d(text, "")) for text in SETTINGS]
MUTANTS += [(f"setup: {name} is not kept on the rule", R, d(f'object.__setattr__(self, "{attribute}", {name})', f'object.__setattr__(self, "{attribute}", {empty})')) for attribute, name, empty in ATTRIBUTES]
MUTANTS += [
    (f"setup: the words of the error are changed: {words[:28]}", R, d(words, "x" + words))
    for words in (
        "live must be True or False",
        "ignore must be a list of the names of inputs, each as text",
        "the input that holds the statement cannot be ignored",
        " must be a list of names, given as the list itself",
        " is not a plain name, such as ",
    )
]

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
