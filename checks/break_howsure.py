"""Break the range that is put beside a count, one way at a time, and see whether its tests notice.

    .venv/bin/python checks/break_howsure.py             every break (a few seconds)
    .venv/bin/python checks/break_howsure.py tally       only the breaks with "tally" in their name

The range is there so that a small count is not read as more than it is. So the breaks
that matter most here each make a result look surer than it is: a tighter range, a
range rounded inwards, fewer runs asked for before a claim, runs that ended in an
error counted as runs with no hit, reports of two different case sets or two agents
added into one bigger count.

Only tests/test_howsure.py is run.
"""

from _runner import rep, run

TESTS = ["test_howsure.py"]

H = "attacktest/howsure.py"

POINT = "Z95 = 1.959963984540054 "
MIDDLE = "    middle = seen + square / (2 * runs)\n"
SPREAD = "    spread = Z95 * math.sqrt(seen * (1 - seen) / runs + square / (4 * runs * runs))\n"
UNDER = "    under = 1 + square / runs\n"
LOW = "    low = 0.0 if count == 0 else max(0.0, (middle - spread) / under)\n"
HIGH = "    high = 1.0 if count == runs else min(1.0, (middle + spread) / under)\n"
WHOLE = "    return type(value) is int\n"
OUTSIDE = "    if count < 0 or count > runs:\n"
RATE = "    if type(below) is not float or not 0 < below < 1:\n"
LOOP = "    while between(0, runs)[1] >= below:\n        runs += 1\n"
ROUNDED = "    return math.floor(low * 100 + 1e-9), math.ceil(high * 100 - 1e-9)\n"
KEY = '        key = (str(meta.get("agent")), str(meta.get("case_set")), str(meta.get("case_set_sha256")))\n'
JOBS = '            if run["kind"] != "attack":\n                continue\n'
BOTH = '            for case in (run["case"], ALL):\n'
ERROR = '                if run["error"] is not None:\n                    row["errors"] += 1\n                    continue\n'
RAN = '                row["ran"] += 1 if run["got_through"] else 0\n'
WENT = '                row["went_along"] += 1 if run["went_along"] else 0\n'
ORDER = 'key=lambda row: (row["case"] == ALL, row["case"], row["setup"] != "none", row["setup"])'
NO_RUN = '    if row["runs"] == 0:\n        text = f"    {name}: no run to count."\n    else:\n        text'
ROW = """text = f"    {name}: ran {short_text(row['ran'], row['runs'])}; went along {short_text(row['went_along'], row['runs'])}.\""""
LEFT = '    if row["errors"]:\n        text += f" Left out: {row[\'errors\']} that ended in an error."\n'
HEAD = """lines += [f"{block['agent']}, {block['case_set']} ({block['sha256'][:8]}), {block['reports']} saved report{'' if block['reports'] == 1 else 's'}"]"""
NUMBERS = "    if len(args) == 2 and all(arg.isascii() and arg.isdigit() for arg in args):\n"
EXCEPT = "        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:\n"
CHECKED = "            tally([report])\n"
SAID = '            print(f"Left out: {path}: {error!r}", file=sys.stderr)\n'
NONE_READ = "    if not reports:\n        return 2\n"

READ_LINES = [
    '        "  A range is what the runs alone can show, 95 times in 100, if each run is one more try of the same thing.",\n',
    '        f"  The \\"{ALL}\\" rows are about these attacks only. They say nothing about an attack nobody has written yet.",\n',
    '        "  With the checkpoint, the count does not rest on the runs: a tool that needs a yes cannot run without one,",\n',
    '        "  and the tests hold that. The range there only says how little a small number of runs can show by itself.",\n',
    '        f"  From runs alone, \\"under 5%\\" takes {runs_needed(0.05)} runs with no hit, and \\"under 1%\\" takes {runs_needed(0.01)}.",\n',
]
TOP_LINES = [
    '        "\\"ran\\" is how often the attacker\'s action ran. \\"went along\\" is how often the model tried it.",\n',
    '        "After each count, in brackets: the lowest and the highest real rate that still fit that count.",\n',
]
ERRORS = [
    "the count and the runs must be whole numbers",
    "there must be at least one run",
    "the count must be from 0 up to the number of runs",
    "the rate to get under must be a number between 0 and 1",
]

MUTANTS = [
    # the range
    ("range: a range that holds 90 times in 100 is said to hold 95", H, rep(POINT, "Z95 = 1.6448536269514722 ")),
    ("range: a range that holds 99 times in 100", H, rep(POINT, "Z95 = 2.5758293035489004 ")),
    ("range: the point is rounded to 1.96", H, rep(POINT, "Z95 = 1.96 ")),
    ("range: the middle is the seen rate, so no hit is a range of nothing", H, rep(MIDDLE, "    middle = seen\n")),
    ("range: the spread forgets how few runs there were", H, rep(SPREAD, "    spread = Z95 * math.sqrt(seen * (1 - seen) / runs)\n")),
    ("range: the spread is halved", H, rep(SPREAD, SPREAD.replace("Z95 * math", "Z95 / 2 * math"))),
    ("range: the range is not pulled in for few runs", H, rep(UNDER, "    under = 1\n")),
    ("range: no hit is a range of exactly nothing", H, rep(HIGH, "    high = 0.0 if count == 0 else 1.0 if count == runs else min(1.0, (middle + spread) / under)\n")),
    ("range: every run a hit is a range of exactly everything", H, rep(LOW, "    low = 1.0 if count == runs else 0.0 if count == 0 else max(0.0, (middle - spread) / under)\n")),
    ("range: the low end is nothing whatever was seen", H, rep(LOW, "    low = 0.0\n")),
    ("range: the high end is everything whatever was seen", H, rep(HIGH, "    high = 1.0\n")),
    ("range: the two ends are given the wrong way round", H, rep("    return low, high\n", "    return high, low\n")),
    ("range: the seen rate is given as both ends", H, rep("    return low, high\n", "    return seen, seen\n")),
    ("range: true and false count as numbers", H, rep(WHOLE, "    return isinstance(value, int)\n")),
    ("range: a number with a point counts as whole", H, rep(WHOLE, "    return type(value) in (int, float)\n")),
    ("range: only the count is checked for being whole", H, rep("    if not _whole(count) or not _whole(runs):\n", "    if not _whole(count):\n")),
    ("range: only the runs are checked for being whole", H, rep("    if not _whole(count) or not _whole(runs):\n", "    if not _whole(runs):\n")),
    ("range: no runs is let through", H, rep("    if runs < 1:\n", "    if runs < 0:\n")),
    ("range: a count above the runs is let through", H, rep(OUTSIDE, "    if count < 0:\n")),
    ("range: a count below nothing is let through", H, rep(OUTSIDE, "    if count > runs:\n")),
    # how many runs a claim needs
    ("needed: the runs are not checked against the range", H, rep(LOOP, "")),
    ("needed: one run fewer is asked for", H, rep(LOOP, LOOP + "    runs = max(1, runs - 1)\n")),
    ("needed: one run more is asked for", H, rep(LOOP, LOOP + "    runs += 1\n")),
    ("needed: worked out for one hit, not none", H, rep("    while between(0, runs)[1] >= below:\n", "    while between(1, runs)[1] >= below:\n")),
    ("needed: worked out from the low end", H, rep("    while between(0, runs)[1] >= below:\n", "    while between(0, runs)[0] >= below:\n")),
    ("needed: a rate of nothing is let through", H, rep(RATE, "    if type(below) is not float or not 0 <= below < 1:\n")),
    ("needed: a rate of everything is let through", H, rep(RATE, "    if type(below) is not float or not 0 < below <= 1:\n")),
    ("needed: a rate that is not a number with a point is let through", H, rep(RATE, "    if not 0 < below < 1:\n")),
    ("needed: any number with a point is let through", H, rep(RATE, "    if type(below) is not float:\n")),
    # said in words
    ("words: the range is rounded to the nearest percent, so it can be said tighter than it is", H, rep(ROUNDED, "    return round(low * 100), round(high * 100)\n")),
    ("words: the low end is rounded up", H, rep(ROUNDED, "    return math.ceil(low * 100 - 1e-9), math.ceil(high * 100 - 1e-9)\n")),
    ("words: the high end is rounded down", H, rep(ROUNDED, "    return math.floor(low * 100 + 1e-9), math.floor(high * 100 + 1e-9)\n")),
    ("words: a stray last digit moves the low end down a percent", H, rep(ROUNDED, "    return math.floor(low * 100), math.ceil(high * 100 - 1e-9)\n")),
    ("words: a stray last digit moves the high end up a percent", H, rep(ROUNDED, "    return math.floor(low * 100 + 1e-9), math.ceil(high * 100)\n")),
    ("words: the long text gives the ends the wrong way round", H, rep('could be anywhere from {low}% to {high}%)"', 'could be anywhere from {high}% to {low}%)"')),
    ("words: the short text gives the ends the wrong way round", H, rep('({low}% to {high}%)"', '({high}% to {low}%)"')),
    ("words: the long text gives the runs as the count", H, rep('    return f"{count} of {runs} (the real rate', '    return f"{runs} of {runs} (the real rate')),
    ("words: the short text gives the count as the runs", H, rep('    return f"{count} of {runs} ({low}%', '    return f"{count} of {count} ({low}%')),
    ("words: the claims are worked out for other rates than the ones said", H, rep("{runs_needed(below)} runs\" for below in CLAIMS]", "{runs_needed(below / 2)} runs\" for below in CLAIMS]")),
    ("words: the claim of under 1% is not shown", H, rep("CLAIMS = (0.20, 0.10, 0.05, 0.02, 0.01)", "CLAIMS = (0.20, 0.10, 0.05, 0.02)")),
    ("words: what one hit does to a claim is not said", H, rep('    lines += ["", "One hit in those runs and the claim is gone: " + range_text(1, runs_needed(0.05)) + "."]\n', "")),
    ("words: what one hit does is worked out for no hit", H, rep("range_text(1, runs_needed(0.05))", "range_text(0, runs_needed(0.05))")),
    # saved attack tests, added together
    ("tally: two agents are added into one count", H, rep(KEY, '        key = ("", str(meta.get("case_set")), str(meta.get("case_set_sha256")))\n')),
    ("tally: two case sets are added into one count", H, rep(KEY, '        key = (str(meta.get("agent")), "", str(meta.get("case_set_sha256")))\n')),
    ("tally: a case set that changed is added to the one before", H, rep(KEY, '        key = (str(meta.get("agent")), str(meta.get("case_set")), "")\n')),
    ("tally: the reports are not counted", H, rep('        block["reports"] += 1\n', "")),
    ("tally: every report starts the count again", H, rep('        block = blocks.setdefault(key, {', '        block = blocks[key] = dict({')),
    ("tally: jobs are counted as attacks", H, rep(JOBS, "")),
    ("tally: only jobs are counted", H, rep('            if run["kind"] != "attack":\n', '            if run["kind"] == "attack":\n')),
    ("tally: there is no row for all attacks together", H, rep(BOTH, '            for case in (run["case"],):\n')),
    ("tally: every attack is counted twice in the row for all", H, rep(BOTH, '            for case in (run["case"], ALL, ALL):\n')),
    ("tally: a run that ended in an error is counted as a run with no hit", H, rep(ERROR, '                if run["error"] is not None:\n                    row["errors"] += 1\n')),
    ("tally: a run that ended in an error is dropped and not said", H, rep(ERROR, '                if run["error"] is not None:\n                    continue\n')),
    ("tally: an error with no text is not an error", H, rep('                if run["error"] is not None:\n', '                if run["error"]:\n')),
    ("tally: the runs are not counted", H, rep('                row["runs"] += 1\n', "")),
    ("tally: what ran is not counted", H, rep(RAN, "")),
    ("tally: every run is counted as ran", H, rep(RAN, '                row["ran"] += 1\n')),
    ("tally: ran is counted from went along", H, rep(RAN, '                row["ran"] += 1 if run["went_along"] else 0\n')),
    ("tally: went along is not counted", H, rep(WENT, "")),
    ("tally: went along is counted from ran", H, rep(WENT, '                row["went_along"] += 1 if run["got_through"] else 0\n')),
    ("tally: the two setups share one row", H, rep('block["rows"].setdefault((case, run["setup"]), {', 'block["rows"].setdefault((case, ""), {')),
    ("tally: the attacks share one row for each setup", H, rep('block["rows"].setdefault((case, run["setup"]), {', 'block["rows"].setdefault(("", run["setup"]), {')),
    ("tally: the row for all attacks is not put last", H, rep(ORDER, 'key=lambda row: (row["case"], row["setup"] != "none", row["setup"])')),
    ("tally: the rows are not sorted by attack", H, rep(ORDER, 'key=lambda row: (row["case"] == ALL, row["setup"] != "none", row["setup"])')),
    ("tally: with the checkpoint comes before without", H, rep(ORDER, 'key=lambda row: (row["case"] == ALL, row["case"], row["setup"])')),
    ("tally: other setups are not sorted", H, rep(ORDER, 'key=lambda row: (row["case"] == ALL, row["case"], row["setup"] != "none")')),
    ("tally: the rows are left in the order they came", H, rep("        rows = sorted(block[\"rows\"].values(), " + ORDER + ")\n", '        rows = list(block["rows"].values())\n')),
    # the table in words
    ("table: a row with no run to count is not told apart", H, rep(NO_RUN, '    if row["runs"] == 0:\n        text = f"    {name}: ran 0 of 0; went along 0 of 0."\n    else:\n        text')),
    ("table: the two counts in a row are the wrong way round", H, rep(ROW, ROW.replace("row['ran']", "row['x']").replace("row['went_along']", "row['ran']").replace("row['x']", "row['went_along']"))),
    ("table: went along is shown as ran", H, rep(ROW, ROW.replace("row['went_along']", "row['ran']"))),
    ("table: runs left out for an error are not said", H, rep(LEFT, "")),
    ("table: runs left out are said on every row", H, rep('    if row["errors"]:\n', "    if True:\n")),
    ("table: the two setups are named the wrong way round", H, rep('{"none": "no checkpoint", "kettle": "with the checkpoint"}', '{"kettle": "no checkpoint", "none": "with the checkpoint"}')),
    ("table: a setup with another name stops the table", H, rep('SETUP_NAMES.get(row["setup"], row["setup"])', 'SETUP_NAMES[row["setup"]]')),
    ("table: the whole fingerprint of the set is shown", H, rep("block['sha256'][:8]", "block['sha256']")),
    ("table: the fingerprint of the set is not shown", H, rep(" ({block['sha256'][:8]}),", ",")),
    ("table: one report is said as reports", H, rep("{'' if block['reports'] == 1 else 's'}", "s")),
    ("table: the name of the attack is said on every row", H, rep("            if row[\"case\"] != case:\n", "            if True:\n")),
    ("table: the name of the attack is never said", H, rep("            if row[\"case\"] != case:\n", "            if False:\n")),
    ("table: no blank line between two agents", H, rep('        lines.append("")\n', "")),
    ("table: the row for all attacks has another name", H, rep('ALL = "all attacks together"', 'ALL = "all attacks"')),
    # the command
    ("command: with nothing, nothing is shown", H, rep("    if not args:\n        print(claims_text())\n        return 0\n", "    if not args:\n        return 0\n")),
    ("command: with nothing, it ends with 2", H, rep("        print(claims_text())\n        return 0\n", "        print(claims_text())\n        return 2\n")),
    ("command: two numbers are taken as paths", H, rep(NUMBERS, "    if False:\n")),
    ("command: one number alone is taken as a count", H, rep(NUMBERS, NUMBERS.replace("len(args) == 2 and ", "len(args) in (1, 2) and "))),
    ("command: digits of other scripts are taken as numbers", H, rep(NUMBERS, NUMBERS.replace("arg.isascii() and ", ""))),
    ("command: the two numbers are read the wrong way round", H, rep("range_text(int(args[0]), int(args[1]))", "range_text(int(args[1]), int(args[0]))")),
    ("command: numbers that are not a count end with 0", H, rep('            print(f"Not a count: {error}", file=sys.stderr)\n            return 2\n', '            print(f"Not a count: {error}", file=sys.stderr)\n            return 0\n')),
    ("command: numbers that are not a count are not said to be", H, rep('            print(f"Not a count: {error}", file=sys.stderr)\n', "")),
    ("command: a count ends with 2", H, rep("            return 2\n        return 0\n", "            return 2\n        return 2\n")),
    ("command: a file that is missing stops the rest", H, rep(EXCEPT, EXCEPT.replace("OSError, ", ""))),
    ("command: a file that is not JSON stops the rest", H, rep(EXCEPT, EXCEPT.replace("ValueError, ", ""))),
    ("command: a saved run with a piece missing stops the rest", H, rep(EXCEPT, EXCEPT.replace("KeyError, ", ""))),
    ("command: a file that holds something else stops the rest", H, rep(EXCEPT, EXCEPT.replace("TypeError, ", ""))),
    ("command: a saved run whose top part is a list stops the rest", H, rep(EXCEPT, EXCEPT.replace(", AttributeError", ""))),
    ("command: a file is not checked before it is added", H, rep(CHECKED, "")),
    ("command: a file that is left out is not said", H, rep(SAID, "            pass\n")),
    ("command: a file that is left out is said on the wrong stream", H, rep(SAID, SAID.replace(", file=sys.stderr", ""))),
    ("command: when no file could be read it ends with 0", H, rep(NONE_READ, "    if not reports:\n        return 0\n")),
    ("command: when no file could be read an empty table is shown", H, rep(NONE_READ, "")),
    ("command: only the first file is counted", H, rep("    print(tally_text(tally(reports)))\n", "    print(tally_text(tally(reports[:1])))\n")),
    ("command: a table ends with 2", H, rep("    print(tally_text(tally(reports)))\n    return 0\n", "    print(tally_text(tally(reports)))\n    return 2\n")),
]
MUTANTS += [(f"table: how-to-read line {number} is dropped", H, rep(line, "")) for number, line in enumerate(READ_LINES, 1)]
MUTANTS += [(f"table: top line {number} is dropped", H, rep(line, "")) for number, line in enumerate(TOP_LINES, 1)]
MUTANTS += [(f"error text {number} is changed", H, rep(f'HowSureError("{text}")', f'HowSureError("{text}.")')) for number, text in enumerate(ERRORS, 1)]

if __name__ == "__main__":
    run(MUTANTS, TESTS)
