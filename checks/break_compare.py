"""Break the command that compares two counts, one way at a time, and see whether its tests notice.

    .venv/bin/python checks/break_compare.py             every break (under a minute)
    .venv/bin/python checks/break_compare.py together    only the breaks with "together" in their name

The command is there to stop a person reading too much into a gap. So the breaks that
matter most are the ones that would make a gap look surer than it is without anybody
seeing: a mark given at 1 time in 20 and not past it, a number rounded the wrong way,
rows that could never be marked counted (or the ones that could, not counted), a
"together" row judged when the two sides ran different mixes of cases, a report
counted twice, two case sets compared that are not the same set, a run that ended in
an error counted as a clean run, and the two sides swapped.

Only tests/test_compare.py is run.
"""

from _runner import rep, run

TESTS = ["test_compare.py"]

C = "attacktest/compare.py"

# ---- lines of the code, as they stand

WHOLE = '    if any(type(value) is not int for value in (hits, runs, other_hits, other_runs)):\n        raise CompareError("every count and every number of runs must be a whole number")\n'
ONE_RUN = "    if runs < 1 or other_runs < 1:\n"
IN_RANGE = "    if not 0 <= hits <= runs or not 0 <= other_hits <= other_runs:\n"
TOO_MANY = "    if runs > LIMIT or other_runs > LIMIT:\n"
TOTAL = "    total = hits + other_hits\n\n    def ways"
WAYS = "        return math.comb(runs, here) * math.comb(other_runs, total - here)\n"
SHARE = "    return Fraction(sum(ways(here) for here in range(total + 1) if ways(here) <= seen), math.comb(runs + other_runs, total))\n"
ONE_IN = "    return share.denominator // share.numerator\n"
OFTEN = '    if times == 1:\n        return "more often than not"\n'
RARE = '    if times > 1000:\n        return "less than 1 time in 1000"\n'
NEEDED = "    for hits in range(1, runs + 1):\n        if one_in(chance(0, runs, hits, runs)) > ONE_IN:\n            return hits\n"
COULD_NO_RUNS = "    if not runs or not other_runs:\n        return False\n"
ENDS = "    ends = (max(0, total - other_runs), min(runs, total))"
COULD = "    return any(one_in(chance(here, runs, total - here, other_runs)) > ONE_IN for here in ends)\n"
JUDGE_NO_RUNS = '    if not runs or not other_runs:\n        return {"verdict": NO_RUNS, "one_in": None, "way": None}\n'
JUDGE_NO_GAP = '    if hits * other_runs == other_hits * runs:\n        return {"verdict": NO_GAP, "one_in": None, "way": None}\n'
VERDICT = "    verdict = CHANCE if times <= ONE_IN else MARKED if times <= ONE_IN * could else HOLDS\n"
WAY = '"way": "lower" if other_hits * runs < hits * other_runs else "higher"}'
FOUR_REFUSES = "    chance(hits, runs, other_hits, other_runs)  # refuses anything that is not two counts\n"
FOUR_NO_GAP = '    if judged["verdict"] == NO_GAP:\n        return text + "No gap: the two rates are the same."\n'
FOUR_CHANCE = '    if judged["verdict"] == CHANCE:\n'
FOUR_WAY = " The second is {judged['way']}."
LONG = '    if len(digits) > 18:  # Python will not read a number thousands of digits long, and no count is that big\n        raise CompareError(f"more than {LIMIT} runs on a side is more than this works out")\n'
NO_GAP_SIZE = "        if hits is None:\n"
PLAIN = '    return "".join(letter if letter.isprintable() else "?" for letter in str(text))\n'

IS_REPORT = '    meta = report.get("meta") if type(report) is dict else None\n'
SHAPE = '    if type(meta) is not dict or type(report.get("runs")) is not list or any(type(meta.get(name)) is not str for name in ("case_set", "case_set_sha256", "date")):\n'
IS_RUN = '        if type(run) is not dict or type(run.get("kind")) is not str or run["kind"] not in KIND_NAMES or type(run.get("case")) is not str or type(run.get("setup")) is not str:\n            raise CompareError("a run in this file is not a run")\n'
ERRORS = '        if run.get("error") is not None:\n            errors += 1\n            continue\n'
OTHER_KIND = '            if kind != run["kind"]:\n                continue\n'
IS_BOOL = '            if type(run.get(field)) is not bool:\n                raise CompareError("a run in this file is missing something a saved run always has")\n'
CELL = '            cell = counts.setdefault((run["setup"], field, run["case"]), [0, 0])\n'
HIT = "            cell[0] += 1 if run[field] else 0\n"
RUN = "            cell[1] += 1\n    agent"
AGENT = '    agent = str(meta.get("agent"))\n'
TOLD = '    return {"set": (meta["case_set"], meta["case_set_sha256"]), "made": (meta["date"], agent), "agent": agent, "errors": errors, "counts": counts}\n'

SIDE_SET = '        here = sets.setdefault(one["set"], {"agents": [], "reports": 0, "errors": 0, "counts": {}})\n'
SIDE_AGENT = '        if one["agent"] not in here["agents"]:\n            here["agents"].append(one["agent"])\n'
SIDE_REPORTS = '        here["reports"] += 1\n'
SIDE_ERRORS = '        here["errors"] += one["errors"]\n'
SIDE_HITS = "            cell[0] += hits\n"
SIDE_RUNS = "            cell[1] += runs\n"
SET_NAMES = '    return ", ".join(f"{_plain(name)} ({_plain(sha)[:8]})" for name, sha in sorted(sets)) or "none"\n'

MADE = '    made = [read(report)["made"] for report in (*first, *second)]\n'
TWICE = "        if made.count((date, agent)) > 1:\n"
TWICE_SAYS = "the saved report made {_plain(date)} by {_plain(agent)} is given more than once"
SHARED = "    shared = sorted(key for key in one if key in two)\n"
NONE_SHARED = "    if not shared:\n"
COUNTS = '        ours, theirs = one[key]["counts"], two[key]["counts"]\n'
SETUPS = '        for setup in sorted({name[0] for name in names}, key=lambda setup: (setup != "none", setup != "kettle", setup)):\n'
CASES = "                cases = sorted(name[2] for name in names if name[:2] == (setup, field))\n"
NO_CASES = "                if not cases:\n                    continue\n"
ROWS = '                rows = [{"case": case, "first": tuple(ours.get((setup, field, case), (0, 0))), "second": tuple(theirs.get((setup, field, case), (0, 0)))} for case in cases]\n'
BOTH = '                both = [row for row in rows if row["first"][1] and row["second"][1]]\n'
MORE_THAN_ONE = "                if len(both) > 1:\n"
TOGETHER = '                    together = {"case": TOGETHER[kind], "first": tuple(sum(row["first"][at] for row in both) for at in (0, 1)), "second": tuple(sum(row["second"][at] for row in both) for at in (0, 1)), "together": True}\n'
HITS_RUNS = '                    hits, runs = together["first"][0] + together["second"][0], together["first"][1] + together["second"][1]\n'
SHARES = '                    shares_differ = any(row["first"][1] * together["second"][1] != row["second"][1] * together["first"][1] for row in both)\n'
UNEVEN = '                    together["uneven"] = shares_differ and 0 < hits < runs'
ADD_TOGETHER = "                    rows.append(together)\n"
SECTION = '                sections.append({"setup": setup, "kind": kind, "field": field, "what": what, "rows": rows})\n'
BLOCK_FIRST = '                "first": {name: one[key][name] for name in ("agents", "reports", "errors")},\n'
BLOCK_SECOND = '                "second": {name: two[key][name] for name in ("agents", "reports", "errors")},\n'
BLOCK_SHA = '                "sha256": key[1],\n'
JUDGED = '    judged = [row for row in rows if not row["uneven"]]\n'
COULD_ROWS = '    could = sum(1 for row in judged if could_mark(row["first"], row["second"]))\n'
UPDATE = '        row.update({"verdict": UNEVEN, "one_in": None, "way": None} if row["uneven"] else judge(row["first"], row["second"], could))\n'
N_COMPARED = '        "compared": sum(1 for row in judged if row["verdict"] != NO_RUNS),\n'
N_MARKED = '        "marked": sum(1 for row in rows if row["verdict"] in (MARKED, HOLDS)),\n'
N_HELD = '        "held": sum(1 for row in rows if row["verdict"] == HOLDS),\n'
ONLY_FIRST = '        "only_first": sorted(key for key in one if key not in two),\n'
ONLY_SECOND = '        "only_second": sorted(key for key in two if key not in one),\n'

SIDE_TEXT = """    text = f"  {which} {' and '.join(_plain(agent) for agent in told['agents'])}. {told['reports']} saved report{'' if told['reports'] == 1 else 's'}.\"\n"""
SIDE_LEFT_OUT = '    if told["errors"]:\n'
ROW_START = """    start = f"    {_plain(row['case'])}: \"\n"""
ROW_NO_RUNS = """        return start + f"no run to compare on the {'second' if runs else 'first'} side.\"\n"""
ROW_UNEVEN = '    if row["verdict"] == UNEVEN:\n'
ROW_NO_GAP = '    if row["verdict"] == NO_GAP:\n        return text + "No gap."\n'
ROW_CHANCE = '    if row["verdict"] == CHANCE:\n'
ROW_MARKED = '    if row["verdict"] == MARKED:\n'
ROW_HOLDS = '    return text + (f" Holds with all {could} rows that could be marked allowed for." if could > 1 else "")\n'
BLOCK_HEAD = """        lines += [f"Case set {_plain(block['case_set'])} ({_plain(block['sha256'])[:8]})", _side_text("First side: ", block["first"]), _side_text("Second side:", block["second"]), ""]\n"""
SECTION_HEAD = """            lines.append(f"  {KIND_NAMES[section['kind']]}, {SETUP_NAMES.get(section['setup'], _plain(section['setup']))}: {section['what']}")\n"""
ONLY_CASES = '            cases = [row for row in section["rows"] if not row["together"]]\n'
HIDDEN = '            hidden = 0 if every else sum(1 for row in cases if row["verdict"] == NO_GAP)\n'
SHOWN = """            lines += [_row_text(row, compared["could"]) for row in section["rows"] if every or row["together"] or row["verdict"] != NO_GAP]\n"""
IF_HIDDEN = "            if hidden:\n"
REST = '                rest = "" if hidden == len(cases) else " other"\n'
HIDDEN_LINE = """                lines.append(f"    No gap in the one{rest} case." if hidden == 1 else f"    No gap in {'the other' if rest else 'any of the'} {hidden} cases.")\n"""
HOLD_LINES = '    if compared["marked"] and compared["could"] > 1:\n'
ONLY_LINE = "        if sets:\n"
WHICH = '    for which, sets in (("first", compared["only_first"]), ("second", compared["only_second"])):\n'

LOAD_READ = "        read(report)\n    except"
LOAD_EXCEPT = "    except (OSError, ValueError) as error:\n"
LOAD_SAYS = '        raise CompareError(f"{path}: {error}") from None\n'
BY_WORD = "    by_word = options.first is not None or options.second is not None\n"
NOT_BOTH = '    if options.against is not None and by_word:\n        raise CompareError("use --against, or --first with --second, not both")\n'
NOTHING = '    if not options.things:\n        raise CompareError("no saved runs were given")\n'
AGAINST = "        return reports, [_load(path) for path in options.against], 0\n"
NO_SECOND = "    if options.first is None or options.second is None:\n"
EMPTY = "    if not options.first or not options.second:\n"
FITS = "        in_first, in_second = options.first.lower() in agent.lower(), options.second.lower() in agent.lower()\n"
FITS_BOTH = '        if in_first and in_second:\n            raise CompareError(f"{path}: the agent {_plain(agent)!r} fits both words")\n'
PUT = "        if in_first:\n            first.append(report)\n        elif in_second:\n            second.append(report)\n        else:\n            neither += 1\n"
NOT_FOUND = "        if not found:\n"
RETURN_SIDES = "    return first, second, neither\n"

STOP = "        return stop.code if type(stop.code) is int else 2\n"
NO_SIDES = "    if options.against is None and options.first is None and options.second is None:\n"
NO_THINGS = "        if not things:\n            print(gaps_text())\n            return 0\n"
FOUR = "        if len(things) == 4 and all(thing.isascii() and thing.isdigit() for thing in things):\n"
FOUR_PRINT = "                print(four_text(*(_whole(thing) for thing in things)))\n"
NOT_COUNTS = '                print(f"Not two counts: {error}", file=sys.stderr)\n                return 2\n            return 0\n'
MAIN_COMPARE = "        compared = compare(first, second)\n"
CANNOT = '        print(f"Cannot compare: {error}", file=sys.stderr)\n        return 2\n'
PRINT = "    print(compare_text(compared, options.every))\n"
NEITHER = "    if neither:\n"
NEITHER_LINE = """        print(f"\\nLeft out: {neither} saved report{'' if neither == 1 else 's'} whose agent fits neither word.")\n    return 0\n"""


def gone(old):
    """The break where a piece of the code is simply not there."""
    return rep(old, "")


def swap(line, old, new):
    """The break where one piece of one line is something else."""
    return rep(line, line.replace(old, new)) if old in line else rep(line + " (this break no longer fits the line)", "")


MUTANTS = [
    # ---- the numbers the whole thing hangs on
    ("number: a gap is marked at 1 time in 19", C, rep("ONE_IN = 20 ", "ONE_IN = 19 ")),
    ("number: a gap is marked at 1 time in 21", C, rep("ONE_IN = 20 ", "ONE_IN = 21 ")),
    ("number: a gap is marked at 1 time in 10", C, rep("ONE_IN = 20 ", "ONE_IN = 10 ")),
    ("number: the table of gaps has another size in it", C, rep("SIZES = (3, 5, 10, 20, 50)", "SIZES = (3, 5, 10, 20, 100)")),
    ("number: the table of gaps is in another order", C, rep("SIZES = (3, 5, 10, 20, 50)", "SIZES = (5, 3, 10, 20, 50)")),
    ("number: the limit is one run lower", C, rep("LIMIT = 5000 ", "LIMIT = 4999 ")),
    ("number: the limit is one run higher", C, rep("LIMIT = 5000 ", "LIMIT = 5001 ")),
    ("number: what is counted on attacks is named the wrong way round", C, rep('"got_through", "how often the attacker\'s action ran"', '"got_through", "how often the model went along"', '"went_along", "how often the model went along"', '"went_along", "how often the attacker\'s action ran"')),
    ("number: going along is not counted", C, gone('    ("attack", "went_along", "how often the model went along"),\n')),
    ("number: the attacker's action is not counted", C, gone('    ("attack", "got_through", "how often the attacker\'s action ran"),\n')),
    ("number: jobs are not counted", C, gone('    ("job", "task_done", "how often the job was done"),\n')),
    ("number: jobs come before attacks", C, rep('    ("attack", "got_through", "how often the attacker\'s action ran"),\n', "", "MEASURES = (\n", 'MEASURES = (\n    ("job", "task_done", "how often the job was done"),\n    ("attack", "got_through", "how often the attacker\'s action ran"),\n', '    ("job", "task_done", "how often the job was done"),\n)', ")")),
    ("number: attacks and jobs are named the wrong way round", C, rep('KIND_NAMES = {"attack": "Attacks", "job": "Jobs"}', 'KIND_NAMES = {"attack": "Jobs", "job": "Attacks"}')),
    ("number: the together rows are named the wrong way round", C, rep('TOGETHER = {"attack": "all attacks together", "job": "all jobs together"}', 'TOGETHER = {"attack": "all jobs together", "job": "all attacks together"}')),
    # ---- the check
    ("check: a count that is not a whole number is not refused", C, gone(WHOLE)),
    ("check: True counts as a whole number", C, swap(WHOLE, "type(value) is not int", "not isinstance(value, int)")),
    ("check: only the first two numbers must be whole", C, swap(WHOLE, "(hits, runs, other_hits, other_runs)", "(hits, runs)")),
    ("check: only the last two numbers must be whole", C, swap(WHOLE, "(hits, runs, other_hits, other_runs)", "(other_hits, other_runs)")),
    ("check: only the counts must be whole", C, swap(WHOLE, "(hits, runs, other_hits, other_runs)", "(hits, other_hits)")),
    ("check: the first side may have no runs", C, swap(ONE_RUN, "runs < 1 or other_runs < 1", "other_runs < 1")),
    ("check: the second side may have no runs", C, swap(ONE_RUN, "runs < 1 or other_runs < 1", "runs < 1")),
    ("check: a side may have no runs", C, swap(ONE_RUN, "runs < 1 or other_runs < 1", "runs < 0 or other_runs < 0")),
    ("check: a side with one run is refused", C, swap(ONE_RUN, "runs < 1 or other_runs < 1", "runs < 2 or other_runs < 2")),
    ("check: the first count may be past its runs", C, swap(IN_RANGE, "not 0 <= hits <= runs or ", "hits < 0 or ")),
    ("check: the second count may be past its runs", C, swap(IN_RANGE, " or not 0 <= other_hits <= other_runs", " or other_hits < 0")),
    ("check: the first count may be below nothing", C, swap(IN_RANGE, "not 0 <= hits <= runs or ", "hits > runs or ")),
    ("check: the second count may be below nothing", C, swap(IN_RANGE, " or not 0 <= other_hits <= other_runs", " or other_hits > other_runs")),
    ("check: a count as big as its runs is refused", C, swap(IN_RANGE, "not 0 <= hits <= runs", "not 0 <= hits < runs")),
    ("check: a count of nothing is refused", C, swap(IN_RANGE, "not 0 <= other_hits <= other_runs", "not 0 < other_hits <= other_runs")),
    ("check: no limit on the first side", C, swap(TOO_MANY, "runs > LIMIT or other_runs > LIMIT", "other_runs > LIMIT")),
    ("check: no limit on the second side", C, swap(TOO_MANY, "runs > LIMIT or other_runs > LIMIT", "runs > LIMIT")),
    ("check: as many runs as the limit are refused", C, swap(TOO_MANY, "runs > LIMIT or other_runs > LIMIT", "runs >= LIMIT or other_runs >= LIMIT")),
    ("check: no runs is said to be a count out of range", C, rep('raise CompareError("each side must have at least one run")', 'raise CompareError("a count must be from 0 up to its number of runs")')),
    ("check: a count out of range is said to be no runs", C, rep('raise CompareError("a count must be from 0 up to its number of runs")', 'raise CompareError("each side must have at least one run")')),
    ("check: a refusal is not the kind the command looks for", C, rep("class CompareError(ValueError):", "class CompareError(Exception):")),
    ("check: only the first side's hits are handed out", C, swap(TOTAL, "hits + other_hits", "hits")),
    ("check: only the second side's hits are handed out", C, swap(TOTAL, "hits + other_hits", "other_hits")),
    ("check: the two sides' runs are swapped", C, swap(WAYS, "math.comb(runs, here) * math.comb(other_runs, total - here)", "math.comb(other_runs, here) * math.comb(runs, total - here)")),
    ("check: the second side's ways are left out", C, swap(WAYS, " * math.comb(other_runs, total - here)", "")),
    ("check: the first side's ways are left out", C, swap(WAYS, "math.comb(runs, here) * ", "")),
    ("check: the ways are added, not multiplied", C, swap(WAYS, ") * math.comb(", ") + math.comb(")),
    ("check: what was seen is not counted itself", C, swap(SHARE, "ways(here) <= seen", "ways(here) < seen")),
    ("check: the more usual ways are counted, not the less usual", C, swap(SHARE, "ways(here) <= seen", "ways(here) >= seen")),
    ("check: only a gap one way is counted", C, swap(SHARE, "ways(here) <= seen", "here <= hits")),
    ("check: only a gap the other way is counted", C, swap(SHARE, "ways(here) <= seen", "here >= hits")),
    ("check: every way is counted", C, swap(SHARE, " if ways(here) <= seen", "")),
    ("check: the way with every hit on the first side is left out", C, swap(SHARE, "range(total + 1)", "range(total)")),
    ("check: the way with no hit on the first side is left out", C, swap(SHARE, "range(total + 1)", "range(1, total + 1)")),
    ("check: the share is of the wrong number of ways", C, swap(SHARE, "math.comb(runs + other_runs, total)", "math.comb(runs + other_runs, hits)")),
    ("check: the share is of the ways on one side", C, swap(SHARE, "math.comb(runs + other_runs, total)", "math.comb(runs, total) or 1")),
    ("check: the share is half of what it is", C, swap(SHARE, "math.comb(runs + other_runs, total))", "2 * math.comb(runs + other_runs, total))")),
    # ---- "1 time in N"
    ("one in: rounded up, so chance looks rarer", C, swap(ONE_IN, "share.denominator // share.numerator", "-(-share.denominator // share.numerator)")),
    ("one in: rounded to the nearest", C, swap(ONE_IN, "share.denominator // share.numerator", "round(share.denominator / share.numerator)")),
    ("one in: upside down", C, swap(ONE_IN, "share.denominator // share.numerator", "share.numerator // share.denominator")),
    ("one in: one more than it is", C, swap(ONE_IN, "share.denominator // share.numerator", "share.denominator // share.numerator + 1")),
    ("one in words: 1 time in 1 is not put in words", C, gone(OFTEN)),
    ("one in words: 1 time in 2 is called more often than not", C, swap(OFTEN, "times == 1", "times <= 2")),
    ("one in words: 1 time in 1000 is called less than that", C, swap(RARE, "times > 1000", "times >= 1000")),
    ("one in words: 1 time in 1001 is given as a number", C, swap(RARE, "times > 1000", "times > 1001")),
    ("one in words: a very rare gap is given as a number", C, gone(RARE)),
    ("one in words: the two wordings are swapped", C, rep('return "more often than not"', 'return "less than 1 time in 1000"', '        return "less than 1 time in 1000"\n    return f"about', '        return "more often than not"\n    return f"about')),
    # ---- how big a gap has to be
    ("gap needed: a hit on every run is not tried", C, swap(NEEDED, "range(1, runs + 1)", "range(1, runs)")),
    ("gap needed: 1 time in 20 is enough", C, swap(NEEDED, "> ONE_IN", ">= ONE_IN")),
    ("gap needed: one hit more than is needed", C, swap(NEEDED, "return hits", "return hits + 1")),
    ("gap needed: one hit fewer than is needed", C, swap(NEEDED, "chance(0, runs, hits, runs)", "chance(0, runs, min(hits + 1, runs), runs)")),
    ("gap needed: the other side has one hit too", C, swap(NEEDED, "chance(0, runs, hits, runs)", "chance(min(1, hits), runs, hits, runs)")),
    ("gap needed: the first gap tried is given", C, swap(NEEDED, "        if one_in(chance(0, runs, hits, runs)) > ONE_IN:\n    ", "")),
    ("gaps table: a size where nothing can be marked is shown as one where something can", C, swap(NO_GAP_SIZE, "hits is None", "hits is not None")),
    ("gaps table: every size is said to mark nothing", C, swap(NO_GAP_SIZE, "hits is None", "True")),
    ("gaps table: the last line is left off", C, gone('    lines += ["", "A smaller gap than that may still be real. Runs alone cannot tell it from chance."]\n')),
    # ---- could a row be marked at all
    ("could mark: a side with no runs is asked about", C, gone(COULD_NO_RUNS)),
    ("could mark: only two sides with no runs are turned away", C, swap(COULD_NO_RUNS, "not runs or not other_runs", "not runs and not other_runs")),
    ("could mark: a side with no runs could be marked", C, swap(COULD_NO_RUNS, "return False", "return True")),
    ("could mark: only the lowest way is tried", C, swap(ENDS, "(max(0, total - other_runs), min(runs, total))", "(max(0, total - other_runs),)")),
    ("could mark: only the highest way is tried", C, swap(ENDS, "(max(0, total - other_runs), min(runs, total))", "(min(runs, total),)")),
    ("could mark: the lowest way is always no hits", C, swap(ENDS, "max(0, total - other_runs)", "0")),
    ("could mark: the highest way is every hit", C, swap(ENDS, "min(runs, total)", "total")),
    ("could mark: the counts as they fell are tried, not the most lopsided", C, swap(ENDS, "(max(0, total - other_runs), min(runs, total))", "(hits,)")),
    ("could mark: both ways must be marked", C, swap(COULD, "return any(", "return all(")),
    ("could mark: 1 time in 20 is enough", C, swap(COULD, "> ONE_IN", ">= ONE_IN")),
    ("could mark: every row could be marked", C, swap(COULD, "return any(one_in(chance(here, runs, total - here, other_runs)) > ONE_IN for here in ends)", "return True")),
    ("could mark: no row could be marked", C, swap(COULD, "return any(one_in(chance(here, runs, total - here, other_runs)) > ONE_IN for here in ends)", "return False")),
    # ---- the mark
    ("judge: a side with no runs is judged", C, gone(JUDGE_NO_RUNS)),
    ("judge: only two sides with no runs are not judged", C, swap(JUDGE_NO_RUNS, "not runs or not other_runs", "not runs and not other_runs")),
    ("judge: a side with no runs is called no gap", C, swap(JUDGE_NO_RUNS, '"verdict": NO_RUNS', '"verdict": NO_GAP')),
    ("judge: the same rate is not called no gap", C, gone(JUDGE_NO_GAP)),
    ("judge: no gap means the same count, not the same rate", C, swap(JUDGE_NO_GAP, "hits * other_runs == other_hits * runs", "hits == other_hits")),
    ("judge: no gap is called no runs", C, swap(JUDGE_NO_GAP, '"verdict": NO_GAP', '"verdict": NO_RUNS')),
    ("judge: 1 time in 20 is marked", C, swap(VERDICT, "CHANCE if times <= ONE_IN else", "CHANCE if times < ONE_IN else")),
    ("judge: 1 time in 21 is not marked", C, swap(VERDICT, "CHANCE if times <= ONE_IN else", "CHANCE if times <= ONE_IN + 1 else")),
    ("judge: a mark holds at exactly 20 times the rows", C, swap(VERDICT, "times <= ONE_IN * could else", "times < ONE_IN * could else")),
    ("judge: a mark holds whatever the number of rows", C, swap(VERDICT, "times <= ONE_IN * could else", "times <= ONE_IN else")),
    ("judge: the rows are added to 20, not multiplied", C, swap(VERDICT, "ONE_IN * could", "ONE_IN + could")),
    ("judge: one row fewer is allowed for", C, swap(VERDICT, "ONE_IN * could", "ONE_IN * max(could - 1, 1)")),
    ("judge: a mark never holds", C, swap(VERDICT, "else HOLDS", "else MARKED")),
    ("judge: a mark that does not hold is said to hold", C, swap(VERDICT, "MARKED if", "HOLDS if")),
    ("judge: chance and mark are swapped", C, swap(VERDICT, "CHANCE if times <= ONE_IN else MARKED if", "MARKED if times <= ONE_IN else CHANCE if")),
    ("judge: left to itself, two rows are allowed for", C, rep("def judge(first: tuple, second: tuple, could: int = 1)", "def judge(first: tuple, second: tuple, could: int = 2)")),
    ("judge: lower and higher are swapped", C, swap(WAY, "other_hits * runs < hits * other_runs", "other_hits * runs > hits * other_runs")),
    ("judge: lower means a lower count, not a lower rate", C, swap(WAY, "other_hits * runs < hits * other_runs", "other_hits < hits")),
    ("judge: the number is not given", C, rep('"one_in": times, ', '"one_in": None, ')),
    ("judge: the number is of the sides the other way up", C, rep("    times = one_in(chance(hits, runs, other_hits, other_runs))\n", "    times = one_in(chance(runs - hits, runs, other_hits, other_runs))\n")),
    # ---- two counts in words
    ("four: what is not two counts is put in words", C, gone(FOUR_REFUSES)),
    ("four: the same rate is not called no gap", C, gone(FOUR_NO_GAP)),
    ("four: could be chance is called more than chance", C, swap(FOUR_CHANCE, "== CHANCE", "== MARKED")),
    ("four: more than chance is called could be chance", C, swap(FOUR_CHANCE, '    if judged["verdict"] == CHANCE:', '    if judged["verdict"] != NO_RUNS:')),
    ("four: which way the second went is not said", C, gone(FOUR_WAY)),
    ("four: the two counts are shown the other way round", C, rep('    text = f"{short_text(hits, runs)} against {short_text(other_hits, other_runs)}. "\n    if judged', '    text = f"{short_text(other_hits, other_runs)} against {short_text(hits, runs)}. "\n    if judged')),
    ("four: a number of 18 digits is refused", C, swap(LONG, "len(digits) > 18", "len(digits) > 17")),
    ("four: a number thousands of digits long is read", C, gone(LONG)),
    # ---- reading one saved attack test
    ("plain: a letter that cannot be printed is shown", C, swap(PLAIN, 'letter if letter.isprintable() else "?"', "letter")),
    ("plain: a letter that cannot be printed is dropped", C, swap(PLAIN, 'else "?"', 'else ""')),
    ("plain: a line break is let through", C, swap(PLAIN, "letter.isprintable()", 'letter.isprintable() or letter == "\\n"')),
    ("read: something that is not a report is not refused", C, swap(IS_REPORT, ' if type(report) is dict else None', "")),
    ("read: meta need not be there", C, swap(SHAPE, "type(meta) is not dict or ", "")),
    ("read: runs need not be a list", C, swap(SHAPE, 'type(report.get("runs")) is not list or ', "")),
    ("read: the name of the case set need not be there", C, swap(SHAPE, '("case_set", "case_set_sha256", "date")', '("case_set_sha256", "date")')),
    ("read: the fingerprint of the case set need not be there", C, swap(SHAPE, '("case_set", "case_set_sha256", "date")', '("case_set", "date")')),
    ("read: the date need not be there", C, swap(SHAPE, '("case_set", "case_set_sha256", "date")', '("case_set", "case_set_sha256")')),
    ("read: a name need only be there, not be text", C, swap(SHAPE, "type(meta.get(name)) is not str", "meta.get(name) is None")),
    ("read: one name is enough", C, swap(SHAPE, "any(type(meta.get(name))", "all(type(meta.get(name))")),
    ("read: a run need not be a dict", C, swap(IS_RUN, "type(run) is not dict or ", "")),
    ("read: a kind need not be text", C, swap(IS_RUN, 'type(run.get("kind")) is not str or ', "")),
    ("read: a kind that is not known is let through", C, swap(IS_RUN, 'run["kind"] not in KIND_NAMES or ', "")),
    ("read: the case need not be text", C, swap(IS_RUN, 'type(run.get("case")) is not str or ', "")),
    ("read: the setup need not be text", C, swap(IS_RUN, ' or type(run.get("setup")) is not str', "")),
    ("read: what is not a run is said to be missing something", C, swap(IS_RUN, '"a run in this file is not a run"', '"a run in this file is missing something a saved run always has"')),
    ("read: a run that ended in an error is counted as a run", C, gone(ERRORS)),
    ("read: an error with no words is not an error", C, swap(ERRORS, 'run.get("error") is not None', 'run.get("error")')),
    ("read: every run is an error", C, swap(ERRORS, 'run.get("error") is not None', "True")),
    ("read: runs that ended in an error are not counted", C, swap(ERRORS, "errors += 1", "errors += 0")),
    ("read: errors are counted twice", C, swap(ERRORS, "errors += 1", "errors += 2")),
    ("read: a run with an error is kept after it is counted", C, swap(ERRORS, "            continue\n", "")),
    ("read: an error is looked for before the run is checked", C, rep(IS_RUN + ERRORS, ERRORS + IS_RUN)),
    ("read: a job is counted as an attack too", C, gone(OTHER_KIND)),
    ("read: a job is counted as an attack and an attack as a job", C, swap(OTHER_KIND, "kind != run", "kind == run")),
    ("read: what is counted need not be yes or no", C, gone(IS_BOOL)),
    ("read: 0 and 1 are taken as no and yes", C, swap(IS_BOOL, "type(run.get(field)) is not bool", "type(run.get(field)) not in (bool, int)")),
    ("read: nothing is taken as no", C, swap(IS_BOOL, "type(run.get(field)) is not bool", "run.get(field) not in (True, False, None)")),
    ("read: something missing is said to be not a run", C, swap(IS_BOOL, '"a run in this file is missing something a saved run always has"', '"a run in this file is not a run"')),
    ("read: counts are kept by case then setup", C, swap(CELL, '(run["setup"], field, run["case"])', '(run["case"], field, run["setup"])')),
    ("read: the setup is left out of the key", C, swap(CELL, '(run["setup"], field, run["case"])', '("none", field, run["case"])')),
    ("read: every case is kept under one name", C, swap(CELL, '(run["setup"], field, run["case"])', '(run["setup"], field, "case")')),
    ("read: both things counted on attacks are kept as one", C, swap(CELL, '(run["setup"], field, run["case"])', '(run["setup"], "got_through" if kind == "attack" else field, run["case"])')),
    ("read: every run is a hit", C, swap(HIT, "1 if run[field] else 0", "1")),
    ("read: no run is a hit", C, swap(HIT, "1 if run[field] else 0", "0")),
    ("read: the misses are counted as hits", C, swap(HIT, "1 if run[field] else 0", "0 if run[field] else 1")),
    ("read: a run is counted twice", C, swap(RUN, "cell[1] += 1", "cell[1] += 2")),
    ("read: only hits are counted as runs", C, swap(RUN, "cell[1] += 1", "cell[1] += 1 if run[field] else 0")),
    ("read: an agent with no name is not text", C, swap(AGENT, 'str(meta.get("agent"))', 'meta.get("agent")')),
    ("read: the case set is known by its name alone", C, swap(TOLD, '(meta["case_set"], meta["case_set_sha256"])', '(meta["case_set"], "")')),
    ("read: the case set is known by its fingerprint alone", C, swap(TOLD, '(meta["case_set"], meta["case_set_sha256"])', '("", meta["case_set_sha256"])')),
    ("read: a report is known by its date alone", C, swap(TOLD, '"made": (meta["date"], agent)', '"made": (meta["date"], "")')),
    ("read: a report is known by its agent alone", C, swap(TOLD, '"made": (meta["date"], agent)', '"made": ("", agent)')),
    ("read: the errors are not told", C, swap(TOLD, '"errors": errors', '"errors": 0')),
    # ---- one side added together
    ("side: every report starts the side again", C, swap(SIDE_SET, "sets.setdefault(one[\"set\"], ", "sets[one[\"set\"]] = (")),
    ("side: an agent is named once for each report", C, swap(SIDE_AGENT, 'if one["agent"] not in here["agents"]:', "if True:")),
    ("side: no agent is named", C, gone(SIDE_AGENT)),
    ("side: the reports are not counted", C, gone(SIDE_REPORTS)),
    ("side: a report is counted twice", C, swap(SIDE_REPORTS, "+= 1", "+= 2")),
    ("side: the errors are not added up", C, gone(SIDE_ERRORS)),
    ("side: only the last report's errors are kept", C, swap(SIDE_ERRORS, "+=", "=")),
    ("side: only the last report's hits are kept", C, swap(SIDE_HITS, "+=", "=")),
    ("side: only the last report's runs are kept", C, swap(SIDE_RUNS, "+=", "=")),
    ("side: the hits are added to the runs", C, rep(SIDE_HITS + SIDE_RUNS, "            cell[1] += hits\n            cell[0] += runs\n")),
    ("set names: not in order", C, swap(SET_NAMES, "in sorted(sets)", "in sets")),
    ("set names: the whole fingerprint is shown", C, swap(SET_NAMES, "[:8]", "")),
    ("set names: a name from a file is shown as it is", C, swap(SET_NAMES, "{_plain(name)}", "{name}")),
    ("set names: a fingerprint from a file is shown as it is", C, swap(SET_NAMES, "_plain(sha)[:8]", "sha[:8]")),
    ("set names: no sets is shown as nothing", C, swap(SET_NAMES, ' or "none"', "")),
    # ---- two sides compared
    ("compare: a report given twice is counted twice", C, swap(TWICE, "> 1", "> 2")),
    ("compare: a report given on both sides is not seen", C, swap(MADE, "(*first, *second)", "first")),
    ("compare: a report given twice on the second side is not seen", C, swap(MADE, "(*first, *second)", "(*first, *second[:1])")),
    ("compare: any two reports are called the same report", C, swap(TWICE, "made.count((date, agent)) > 1", "len(made) > 1")),
    ("compare: the date in a refusal is shown as it is", C, rep(TWICE_SAYS, TWICE_SAYS.replace("{_plain(date)}", "{date}"))),
    ("compare: the agent in a refusal is shown as it is", C, rep(TWICE_SAYS, TWICE_SAYS.replace("{_plain(agent)}", "{agent}"))),
    ("compare: case sets are matched by name alone", C, rep("    one, two = side(first), side(second)\n", "    one, two = ({(key[0], ''): told for key, told in side(reports).items()} for reports in (first, second))\n")),
    ("compare: the case sets are not in order", C, swap(SHARED, "sorted(key for key in one if key in two)", "[key for key in one if key in two]")),
    ("compare: every case set of the first side is compared", C, swap(SHARED, " if key in two", "")),
    ("compare: no case set in common is not refused", C, swap(NONE_SHARED, "if not shared:", "if False:")),
    ("compare: the refusal names the sides the wrong way round", C, rep("First: {_set_names(one)}. Second: {_set_names(two)}.", "First: {_set_names(two)}. Second: {_set_names(one)}.")),
    ("compare: the two sides' counts are swapped", C, swap(COUNTS, 'one[key]["counts"], two[key]["counts"]', 'two[key]["counts"], one[key]["counts"]')),
    ("compare: the second side is compared with itself", C, swap(COUNTS, 'one[key]["counts"], two[key]["counts"]', 'two[key]["counts"], two[key]["counts"]')),
    ("compare: the checkpoint comes before no checkpoint", C, swap(SETUPS, '(setup != "none", setup != "kettle", setup)', '(setup != "kettle", setup)')),
    ("compare: the setups come in order of name alone", C, swap(SETUPS, '(setup != "none", setup != "kettle", setup)', "setup")),
    ("compare: other setups come before the checkpoint", C, swap(SETUPS, '(setup != "none", setup != "kettle", setup)', '(setup != "none", setup)')),
    ("compare: other setups are not in order", C, swap(SETUPS, '(setup != "none", setup != "kettle", setup)', '(setup != "none", setup != "kettle")')),
    ("compare: the cases are not in order", C, swap(CASES, "sorted(name[2]", "list(name[2]")),
    ("compare: the cases are in order backwards", C, swap(CASES, "if name[:2] == (setup, field))", "if name[:2] == (setup, field))[::-1]")),
    ("compare: the cases of every setup are put in each", C, swap(CASES, "if name[:2] == (setup, field)", "if name[1] == field")),
    ("compare: a part with no cases is shown", C, gone(NO_CASES)),
    ("compare: the first side's count is the second's", C, swap(ROWS, '"first": tuple(ours.get(', '"first": tuple(theirs.get(')),
    ("compare: the second side's count is the first's", C, swap(ROWS, '"second": tuple(theirs.get(', '"second": tuple(ours.get(')),
    ("together: a case only one side ran is added in", C, swap(BOTH, 'row["first"][1] and row["second"][1]', 'row["first"][1] or row["second"][1]')),
    ("together: only the first side has to have run a case", C, swap(BOTH, 'row["first"][1] and row["second"][1]', 'row["first"][1]')),
    ("together: only the second side has to have run a case", C, swap(BOTH, 'row["first"][1] and row["second"][1]', 'row["second"][1]')),
    ("together: one case alone gets a together row", C, swap(MORE_THAN_ONE, "len(both) > 1", "len(both) > 0")),
    ("together: two cases get no together row", C, swap(MORE_THAN_ONE, "len(both) > 1", "len(both) > 2")),
    ("together: cases only one side ran count toward having two", C, swap(MORE_THAN_ONE, "len(both) > 1", "len(rows) > 1")),
    ("together: no together row at all", C, swap(MORE_THAN_ONE, "len(both) > 1", "False")),
    ("together: the first side's sum is the second's", C, swap(TOGETHER, '"first": tuple(sum(row["first"][at]', '"first": tuple(sum(row["second"][at]')),
    ("together: the second side's sum is the first's", C, swap(TOGETHER, '"second": tuple(sum(row["second"][at]', '"second": tuple(sum(row["first"][at]')),
    ("together: hits and runs are swapped in the sum", C, swap(TOGETHER, 'for row in both) for at in (0, 1)), "second"', 'for row in both) for at in (1, 0)), "second"')),
    ("together: the row has the name of the other kind", C, swap(TOGETHER, "TOGETHER[kind]", 'TOGETHER["job" if kind == "attack" else "attack"]')),
    ("together: the row is not known as a together row", C, swap(TOGETHER, '"together": True', '"together": False')),
    ("together: the row is not added", C, gone(ADD_TOGETHER)),
    ("together: the row is added first", C, swap(ADD_TOGETHER, "rows.append(together)", "rows.insert(0, together)")),
    ("uneven: only the first side's hits are looked at", C, swap(HITS_RUNS, 'together["first"][0] + together["second"][0]', 'together["first"][0]')),
    ("uneven: only the second side's hits are looked at", C, swap(HITS_RUNS, 'together["first"][0] + together["second"][0]', 'together["second"][0]')),
    ("uneven: only the first side's runs are looked at", C, swap(HITS_RUNS, 'together["first"][1] + together["second"][1]', 'together["first"][1]')),
    ("uneven: only the second side's runs are looked at", C, swap(HITS_RUNS, 'together["first"][1] + together["second"][1]', 'together["second"][1]')),
    ("uneven: every case must be run a different share of times", C, swap(SHARES, "any(row", "all(row")),
    ("uneven: the same shares are called different", C, swap(SHARES, " != ", " == ")),
    ("uneven: the numbers of runs must match, not the shares", C, swap(SHARES, 'row["first"][1] * together["second"][1] != row["second"][1] * together["first"][1]', 'row["first"][1] != row["second"][1]')),
    ("uneven: the shares are worked out the wrong way round", C, swap(SHARES, 'row["first"][1] * together["second"][1] != row["second"][1] * together["first"][1]', 'row["first"][1] * together["first"][1] != row["second"][1] * together["second"][1]')),
    ("uneven: different shares are never looked for", C, swap(UNEVEN, "shares_differ and 0 < hits < runs", "False")),
    ("uneven: a together row is never judged", C, swap(UNEVEN, "shares_differ and 0 < hits < runs", "True")),
    ("uneven: any together row with hits and misses is not judged", C, swap(UNEVEN, "shares_differ and ", "")),
    ("uneven: a together row with no hit at all is not judged", C, swap(UNEVEN, "0 < hits < runs", "hits < runs")),
    ("uneven: a together row with nothing but hits is not judged", C, swap(UNEVEN, "0 < hits < runs", "0 < hits")),
    ("uneven: a together row with one hit is judged", C, swap(UNEVEN, "0 < hits < runs", "1 < hits < runs")),
    ("uneven: a together row with one miss is judged", C, swap(UNEVEN, "0 < hits < runs", "0 < hits < runs - 1")),
    ("uneven: different shares are all it takes", C, swap(UNEVEN, " and 0 < hits < runs", "")),
    ("compare: the part does not say what it counts", C, swap(SECTION, '"what": what', '"what": field')),
    ("compare: the part has the wrong kind", C, swap(SECTION, '"kind": kind', '"kind": "attack"')),
    ("compare: the first side is told as the second", C, swap(BLOCK_FIRST, "one[key][name]", "two[key][name]")),
    ("compare: the second side is told as the first", C, swap(BLOCK_SECOND, "two[key][name]", "one[key][name]")),
    ("compare: the fingerprint is the name", C, swap(BLOCK_SHA, "key[1]", "key[0]")),
    ("count: a together row that is not judged still counts", C, swap(JUDGED, ' if not row["uneven"]', "")),
    ("count: together rows are not counted at all", C, swap(JUDGED, 'if not row["uneven"]', 'if not row["together"]')),
    ("count: every row counts as one that could be marked", C, swap(COULD_ROWS, ' if could_mark(row["first"], row["second"])', "")),
    ("count: rows that could be marked are counted from the rows that could not", C, swap(COULD_ROWS, "if could_mark(", "if not could_mark(")),
    ("count: the sides are swapped when asking if a row could be marked", C, swap(COULD_ROWS, 'could_mark(row["first"], row["second"])', 'could_mark(row["first"], row["first"])')),
    ("count: one row too few could be marked", C, swap(COULD_ROWS, "    could = sum(", "    could = -1 + sum(")),
    ("count: a together row that is not judged is judged", C, swap(UPDATE, ' if row["uneven"] else', " if False else")),
    ("count: a row is judged as if it were the only one", C, swap(UPDATE, 'judge(row["first"], row["second"], could)', 'judge(row["first"], row["second"])')),
    ("count: a row is judged with the sides swapped", C, swap(UPDATE, 'judge(row["first"], row["second"], could)', 'judge(row["second"], row["first"], could)')),
    ("count: a row is judged against the rows compared, not the rows that could be marked", C, swap(UPDATE, 'judge(row["first"], row["second"], could)', 'judge(row["first"], row["second"], len(judged))')),
    ("count: a row not judged is called no gap", C, swap(UPDATE, '{"verdict": UNEVEN,', '{"verdict": NO_GAP,')),
    ("count: rows with no run on one side count as compared", C, swap(N_COMPARED, ' if row["verdict"] != NO_RUNS', "")),
    ("count: rows that are not judged count as compared", C, swap(N_COMPARED, "for row in judged", "for row in rows")),
    ("count: rows with no gap do not count as compared", C, swap(N_COMPARED, 'row["verdict"] != NO_RUNS', 'row["verdict"] not in (NO_RUNS, NO_GAP)')),
    ("count: only marks that do not hold are counted as marked", C, swap(N_MARKED, "in (MARKED, HOLDS)", "== MARKED")),
    ("count: only marks that hold are counted as marked", C, swap(N_MARKED, "in (MARKED, HOLDS)", "== HOLDS")),
    ("count: could be chance is counted as marked", C, swap(N_MARKED, "in (MARKED, HOLDS)", "in (CHANCE, MARKED, HOLDS)")),
    ("count: every mark is counted as one that holds", C, swap(N_HELD, "== HOLDS", "in (MARKED, HOLDS)")),
    ("count: marks that do not hold are counted as the ones that do", C, swap(N_HELD, "== HOLDS", "== MARKED")),
    ("only: the first side's own sets are not in order", C, swap(ONLY_FIRST, "sorted(key for key in one if key not in two)", "[key for key in one if key not in two]")),
    ("only: the second side's own sets are not in order", C, swap(ONLY_SECOND, "sorted(key for key in two if key not in one)", "[key for key in two if key not in one]")),
    ("only: the two lists are swapped", C, rep(ONLY_FIRST + ONLY_SECOND, ONLY_FIRST.replace("only_first", "only_second") + ONLY_SECOND.replace("only_second", "only_first"))),
    ("only: every set of the first side is listed", C, swap(ONLY_FIRST, " if key not in two", "")),
    ("only: every set of the second side is listed", C, swap(ONLY_SECOND, " if key not in one", "")),
    ("only: the sets in common are listed", C, swap(ONLY_FIRST, "if key not in two", "if key in two")),
    # ---- two sides as text
    ("text: an agent's name from a file is shown as it is", C, swap(SIDE_TEXT, "_plain(agent) for agent", "agent for agent")),
    ("text: only the first agent is named", C, swap(SIDE_TEXT, "for agent in told['agents'])", "for agent in told['agents'][:1])")),
    ("text: one report is written as reports", C, swap(SIDE_TEXT, "{'' if told['reports'] == 1 else 's'}", "s")),
    ("text: two reports are written as report", C, swap(SIDE_TEXT, "{'' if told['reports'] == 1 else 's'}", "")),
    ("text: the number of reports is not said", C, swap(SIDE_TEXT, " {told['reports']} saved report", " saved report")),
    ("text: runs left out are not said", C, swap(SIDE_LEFT_OUT, 'if told["errors"]:', "if False:")),
    ("text: no runs left out is said too", C, swap(SIDE_LEFT_OUT, 'if told["errors"]:', "if True:")),
    ("text: a case's name from a file is shown as it is", C, swap(ROW_START, "{_plain(row['case'])}", "{row['case']}")),
    ("text: the side with no run is named the wrong way round", C, swap(ROW_NO_RUNS, "'second' if runs else 'first'", "'first' if runs else 'second'")),
    ("text: a row with no run on one side is shown as counts", C, rep('    if row["verdict"] == NO_RUNS:\n', '    if row["verdict"] == "":\n')),
    ("text: a row that is not judged is shown as judged", C, swap(ROW_UNEVEN, "== UNEVEN", '== ""')),
    ("text: a row that is not judged shows the counts the wrong way round", C, rep('{hits} of {runs} against {other_hits} of {other_runs}. Not judged', '{other_hits} of {other_runs} against {hits} of {runs}. Not judged')),
    ("text: a row shows the counts the wrong way round", C, rep('    text = start + f"{short_text(hits, runs)} against {short_text(other_hits, other_runs)}. "\n', '    text = start + f"{short_text(other_hits, other_runs)} against {short_text(hits, runs)}. "\n')),
    ("text: no gap is shown as a mark", C, gone(ROW_NO_GAP)),
    ("text: could be chance is shown as a mark", C, swap(ROW_CHANCE, "== CHANCE", '== ""')),
    ("text: a mark is shown as could be chance", C, swap(ROW_CHANCE, '    if row["verdict"] == CHANCE:', '    if row["verdict"] in (CHANCE, MARKED):')),
    ("text: a mark that does not hold is said to hold", C, swap(ROW_MARKED, "== MARKED", '== ""')),
    ("text: a mark that holds is said not to", C, swap(ROW_MARKED, "== MARKED", "in (MARKED, HOLDS)")),
    ("text: the only row that could be marked talks of all the rows", C, swap(ROW_HOLDS, " if could > 1 else \"\"", " if True else \"\"")),
    ("text: a mark that holds does not say so", C, swap(ROW_HOLDS, " if could > 1 else \"\"", " if False else \"\"")),
    ("text: which way the second side went is not the way it went", C, rep("MARKED, the second side is {row['way']}", "MARKED, the second side is {'lower' if row['way'] == 'higher' else 'higher'}")),
    ("text: a case set's name from a file is shown as it is", C, swap(BLOCK_HEAD, "{_plain(block['case_set'])}", "{block['case_set']}")),
    ("text: a fingerprint from a file is shown as it is", C, swap(BLOCK_HEAD, "{_plain(block['sha256'])[:8]}", "{block['sha256'][:8]}")),
    ("text: the whole fingerprint is shown", C, swap(BLOCK_HEAD, "{_plain(block['sha256'])[:8]}", "{_plain(block['sha256'])}")),
    ("text: the two sides are named the wrong way round", C, swap(BLOCK_HEAD, '_side_text("First side: ", block["first"]), _side_text("Second side:", block["second"])', '_side_text("First side: ", block["second"]), _side_text("Second side:", block["first"])')),
    ("text: a setup's name from a file is shown as it is", C, swap(SECTION_HEAD, "_plain(section['setup'])", "section['setup']")),
    ("text: the setups are shown by their short names", C, swap(SECTION_HEAD, "SETUP_NAMES.get(section['setup'], _plain(section['setup']))", "_plain(section['setup'])")),
    ("text: what a part counts is not said", C, swap(SECTION_HEAD, ": {section['what']}", "")),
    ("text: a together row counts as a case when rows are hidden", C, swap(ONLY_CASES, ' if not row["together"]', "")),
    ("text: rows with no gap are counted as hidden even when all are listed", C, swap(HIDDEN, "0 if every else ", "")),
    ("text: rows that could be chance are counted as hidden", C, swap(HIDDEN, 'row["verdict"] == NO_GAP', 'row["verdict"] in (NO_GAP, CHANCE)')),
    ("text: every row is always listed", C, swap(SHOWN, "if every or row", "if True or row")),
    ("text: asking for every row lists no more", C, swap(SHOWN, "if every or row", "if row")),
    ("text: a together row with no gap is hidden", C, swap(SHOWN, 'row["together"] or ', "")),
    ("text: rows with no gap are listed and counted", C, swap(SHOWN, ' or row["verdict"] != NO_GAP', " or True")),
    ("text: only rows with no gap are listed", C, swap(SHOWN, 'row["verdict"] != NO_GAP', 'row["verdict"] == NO_GAP')),
    ("text: the rows are told of a different number of rows that could be marked", C, swap(SHOWN, '_row_text(row, compared["could"])', '_row_text(row, compared["compared"])')),
    ("text: the hidden rows are not counted out loud", C, swap(IF_HIDDEN, "if hidden:", "if False:")),
    ("text: no hidden rows is said too", C, swap(IF_HIDDEN, "if hidden:", "if True:")),
    ("text: hidden rows are always called the other cases", C, swap(REST, '"" if hidden == len(cases) else " other"', '" other"')),
    ("text: hidden rows are never called the other cases", C, swap(REST, '"" if hidden == len(cases) else " other"', '""')),
    ("text: one hidden case is written as cases", C, swap(HIDDEN_LINE, "if hidden == 1 else", "if hidden == 0 else")),
    ("text: two hidden cases are written as one", C, swap(HIDDEN_LINE, "if hidden == 1 else", "if hidden <= 2 else")),
    ("text: any of the and the other are swapped", C, swap(HIDDEN_LINE, "'the other' if rest else 'any of the'", "'any of the' if rest else 'the other'")),
    ("text: the count of rows compared is another count", C, rep("Rows compared: {compared['compared']}.", "Rows compared: {compared['could']}.")),
    ("text: the count of rows that could be marked is another count", C, rep("could be marked at all: {compared['could']}.", "could be marked at all: {compared['compared']}.")),
    ("text: the count of marks is the count that hold", C, rep("Marked: {compared['marked']}.", "Marked: {compared['held']}.")),
    ("text: the count that hold is the count of marks", C, rep("of those rows allowed for: {compared['held']}.", "of those rows allowed for: {compared['marked']}.")),
    ("text: marks that hold are spoken of with no mark", C, swap(HOLD_LINES, 'compared["marked"] and ', "")),
    ("text: marks that hold are spoken of with one row", C, swap(HOLD_LINES, ' and compared["could"] > 1', "")),
    ("text: marks that hold are spoken of only past two rows", C, swap(HOLD_LINES, 'compared["could"] > 1', 'compared["could"] > 2')),
    ("text: marks that hold are never spoken of", C, swap(HOLD_LINES, 'if compared["marked"] and compared["could"] > 1:', "if False:")),
    ("text: a side with nothing of its own is listed too", C, swap(ONLY_LINE, "if sets:", "if True:")),
    ("text: sets on one side only are not said", C, swap(ONLY_LINE, "if sets:", "if False:")),
    ("text: sets on one side only are named for the other side", C, swap(WHICH, '(("first", compared["only_first"]), ("second", compared["only_second"]))', '(("second", compared["only_first"]), ("first", compared["only_second"]))')),
    ("text: sets only on the second side are said first", C, swap(WHICH, '(("first", compared["only_first"]), ("second", compared["only_second"]))', '(("second", compared["only_second"]), ("first", compared["only_first"]))')),
    ("text: the gap ten runs need is one hit off", C, rep("    needed = gap_needed(10)\n", "    needed = gap_needed(10) + 1\n")),
    ("text: how to read it is left off", C, gone('        "  A mark is a custom, not a proof. No mark does not mean \\"the same\\": with few runs only a big gap can show.",\n')),
    ("text: what the checkpoint's 0 rests on is left off", C, gone('        "  With the checkpoint, the attacker\'s action cannot run without a yes. That rests on the tests, not on runs.",\n')),
    ("text: what the check takes for granted is left off", C, gone('        "  The check takes each run to be one more try of the same thing, and the two sides to differ only in what",\n')),
    # ---- the command: which files go on which side
    ("load: a file that is not a saved test is taken", C, swap(LOAD_READ, "        read(report)\n", "")),
    ("load: a file that is not JSON stops the command with no word", C, swap(LOAD_EXCEPT, "(OSError, ValueError)", "OSError")),
    ("load: a file that is not there stops the command with no word", C, swap(LOAD_EXCEPT, "(OSError, ValueError)", "ValueError")),
    ("load: the file is not named", C, swap(LOAD_SAYS, '{path}: {error}', '{error}')),
    ("load: why is not said", C, swap(LOAD_SAYS, '{path}: {error}', '{path}')),
    ("sides: --against with --first is not refused", C, gone(NOT_BOTH)),
    ("sides: --against with --second alone is not refused", C, swap(BY_WORD, " or options.second is not None", "")),
    ("sides: --against with --first alone is not refused", C, swap(BY_WORD, "options.first is not None or ", "")),
    ("sides: no files at all is not said plainly", C, gone(NOTHING)),
    ("sides: files are refused as no files", C, swap(NOTHING, "if not options.things:", "if options.things:")),
    ("sides: the files after --against are the first side", C, swap(AGAINST, "return reports, [_load(path) for path in options.against], 0", "return [_load(path) for path in options.against], reports, 0")),
    ("sides: the files after --against are not checked", C, swap(AGAINST, "[_load(path) for path in options.against]", "[json.load(open(path, encoding='utf-8')) for path in options.against]")),
    ("sides: only the first file after --against is used", C, swap(AGAINST, "for path in options.against]", "for path in options.against[:1]]")),
    ("sides: with --against, files are said to fit neither word", C, swap(AGAINST, "], 0\n", "], 1\n")),
    ("sides: one word alone is not said plainly", C, swap(NO_SECOND, "options.first is None or options.second is None", "options.first is None and options.second is None")),
    ("sides: no second side is not said plainly", C, swap(NO_SECOND, "if options.first is None or options.second is None:", "if False:")),
    ("sides: an empty first word is taken", C, swap(EMPTY, "not options.first or not options.second", "not options.second")),
    ("sides: an empty second word is taken", C, swap(EMPTY, "not options.first or not options.second", "not options.first")),
    ("sides: the first word must match in capitals too", C, swap(FITS, "options.first.lower() in agent.lower(),", "options.first in agent.lower(),")),
    ("sides: the second word must match in capitals too", C, swap(FITS, "options.second.lower() in agent.lower()\n", "options.second in agent.lower()\n")),
    ("sides: the agent's capitals stop the first word", C, swap(FITS, "options.first.lower() in agent.lower(),", "options.first.lower() in agent,")),
    ("sides: the agent's capitals stop the second word", C, swap(FITS, "options.second.lower() in agent.lower()\n", "options.second.lower() in agent\n")),
    ("sides: the word must be the whole name", C, swap(FITS, "options.first.lower() in agent.lower(),", "options.first.lower() == agent.lower(),")),
    ("sides: the two words are swapped", C, swap(FITS, "in_first, in_second = ", "in_second, in_first = ")),
    ("sides: an agent that fits both words goes to the first side", C, gone(FITS_BOTH)),
    ("sides: an agent that fits either word is refused", C, swap(FITS_BOTH, "in_first and in_second", "in_first or in_second")),
    ("sides: the agent that fits both words is shown as it is", C, swap(FITS_BOTH, "{_plain(agent)!r}", "{agent!r}")),
    ("sides: the file that fits both words is not named", C, swap(FITS_BOTH, '{path}: the agent', 'the agent')),
    ("sides: a file that fits the first word goes to the second", C, swap(PUT, "first.append(report)\n        elif", "second.append(report)\n        elif")),
    ("sides: a file that fits the second word goes to the first", C, swap(PUT, "            second.append(report)\n        else", "            first.append(report)\n        else")),
    ("sides: a file that fits neither word goes to the second side", C, swap(PUT, "            neither += 1\n", "            second.append(report)\n")),
    ("sides: files that fit neither word are not counted", C, swap(PUT, "neither += 1", "neither += 0")),
    ("sides: files that fit neither word are counted twice", C, swap(PUT, "neither += 1", "neither += 2")),
    ("sides: a word that fits no file is not said plainly", C, swap(NOT_FOUND, "if not found:", "if False:")),
    ("sides: a word that fits a file is said to fit none", C, swap(NOT_FOUND, "if not found:", "if found:")),
    ("sides: the word that fits no file is the other word", C, rep("    for word, found in ((options.first, first), (options.second, second)):\n", "    for word, found in ((options.second, first), (options.first, second)):\n")),
    ("sides: the sides come back swapped", C, swap(RETURN_SIDES, "return first, second, neither", "return second, first, neither")),
    # ---- the command
    ("command: a wrong option ends with 0", C, swap(STOP, "return stop.code if type(stop.code) is int else 2", "return 0")),
    ("command: asking for help ends with 2", C, swap(STOP, "return stop.code if type(stop.code) is int else 2", "return 2")),
    ("command: nothing but --against shows the table of gaps", C, swap(NO_SIDES, "if options.against is None and options.first is None and options.second is None:", "if True:")),
    ("command: nothing but two words shows the table of gaps", C, swap(NO_SIDES, " and options.first is None and options.second is None", "")),
    ("command: nothing but --first shows the table of gaps", C, swap(NO_SIDES, "options.first is None and ", "")),
    ("command: nothing but --second shows the table of gaps", C, swap(NO_SIDES, " and options.second is None", "")),
    ("command: with nothing the table of gaps is not shown", C, gone(NO_THINGS)),
    ("command: the table of gaps ends with 2", C, swap(NO_THINGS, "return 0", "return 2")),
    ("command: files are met with the table of gaps", C, swap(NO_THINGS, "if not things:", "if things is not None and len(things) != 4:")),
    ("command: five numbers are taken as two counts", C, swap(FOUR, "len(things) == 4", "len(things) >= 4")),
    ("command: three numbers are taken as two counts", C, swap(FOUR, "len(things) == 4", "len(things) >= 3")),
    ("command: four numbers are taken as files", C, swap(FOUR, "len(things) == 4 and", "len(things) == 0 and")),
    ("command: digits of other scripts are taken as numbers", C, swap(FOUR, "thing.isascii() and ", "")),
    ("command: anything in plain letters is taken as a number", C, swap(FOUR, " and thing.isdigit()", "")),
    ("command: one number among the four is enough", C, swap(FOUR, "all(thing.isascii()", "any(thing.isascii()")),
    ("command: a number thousands of digits long is read as it is", C, swap(FOUR_PRINT, "_whole(thing)", "int(thing)")),
    ("command: the four numbers are read the other way round", C, swap(FOUR_PRINT, "for thing in things)", "for thing in things[::-1])")),
    ("command: two counts are worked out but not shown", C, swap(FOUR_PRINT, "print(four_text(", "(four_text(")),
    ("command: what is not two counts ends with 0", C, swap(NOT_COUNTS, "                return 2\n", "                return 0\n")),
    ("command: what is not two counts is said on the wrong stream", C, swap(NOT_COUNTS, ", file=sys.stderr", "")),
    ("command: what is not two counts is not said", C, swap(NOT_COUNTS, '                print(f"Not two counts: {error}", file=sys.stderr)\n', "")),
    ("command: two counts end with 2", C, swap(NOT_COUNTS, "            return 0\n", "            return 2\n")),
    ("command: the sides are swapped on the way in", C, swap(MAIN_COMPARE, "compare(first, second)", "compare(second, first)")),
    ("command: what cannot be compared ends with 0", C, swap(CANNOT, "        return 2\n", "        return 0\n")),
    ("command: what cannot be compared is said on the wrong stream", C, swap(CANNOT, ", file=sys.stderr", "")),
    ("command: why it cannot compare is not said", C, swap(CANNOT, "{error}", "")),
    ("command: --all is not passed on", C, swap(PRINT, "compare_text(compared, options.every)", "compare_text(compared)")),
    ("command: every row is always listed", C, swap(PRINT, "compare_text(compared, options.every)", "compare_text(compared, True)")),
    ("command: --all hides and plain shows", C, swap(PRINT, "options.every", "not options.every")),
    ("command: the comparison is not shown", C, gone(PRINT)),
    ("command: files that fit neither word are not said", C, swap(NEITHER, "if neither:", "if False:")),
    ("command: no file fitting neither word is said too", C, swap(NEITHER, "if neither:", "if True:")),
    ("command: one file is written as reports", C, swap(NEITHER_LINE, "{'' if neither == 1 else 's'}", "s")),
    ("command: two files are written as report", C, swap(NEITHER_LINE, "{'' if neither == 1 else 's'}", "")),
    ("command: a comparison ends with 1", C, swap(NEITHER_LINE, "    return 0\n", "    return 1\n")),
    ("command: --all is not an option", C, gone('    parser.add_argument("--all", action="store_true", dest="every", help="list every row, not only the rows with a gap")\n')),
    ("command: --against takes one file only", C, rep('parser.add_argument("--against", nargs="+"', 'parser.add_argument("--against", nargs=1')),
    ("command: --against may be given no file", C, rep('parser.add_argument("--against", nargs="+"', 'parser.add_argument("--against", nargs="*"')),
]

run(MUTANTS, TESTS)
