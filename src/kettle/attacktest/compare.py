"""Is the gap between two counts more than chance would give?

    python -m kettle.attacktest.compare
    python -m kettle.attacktest.compare 11 11 5 11
    python -m kettle.attacktest.compare before/results.json --against after/results.json
    python -m kettle.attacktest.compare runs/*/results.json --first opus --second haiku
    python -m kettle.attacktest.compare before/results.json --against after/results.json --all

No model takes part and nothing here costs anything.

"11 of 11" against "5 of 11" looks like a gap. "1 of 3" against "0 of 3" looks like
one too, and is nothing: chance gives a gap that big more often than not. This puts
a number on that. With four numbers it compares the two counts. With saved attack
tests it compares two sides, case by case: how often the attacker's action ran, how
often the model went along, and how often the job was done. The two sides are the
files before and after --against, or the files split by a word in the agent's name.
With nothing, it shows how big a gap has to be before runs alone can show it.

Beside each pair of counts it says how often chance alone would give a gap at least
that big if the two sides really had the same rate (Fisher's exact test, both ways).
A row is MARKED when that is less often than 1 time in 20. Rows with no gap are
counted, not listed, unless --all is given.

What this cannot show. A mark is a custom, not a proof, and with many rows some
marks come by chance: each mark says whether it still holds with every row that
could have been marked allowed for. A "together" row is not judged when the two
sides did not run each case the same share of times, because a gap there could
come from that alone. No mark does not mean "the same": with few runs only a big
gap can show. The check is worked out exactly, so it stops at 5000 runs a side. It
takes each run to be one more try of the same thing, and the two sides to differ
only in the thing you changed. Runs made on different days with a hosted model may
differ for other reasons. Runs are only compared when the case set is the same on
both sides, by name and by fingerprint. A run that ended in an error is left out
and counted apart.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from fractions import Fraction
from typing import Optional

from .howsure import SETUP_NAMES, short_text

ONE_IN = 20  # a gap is marked when chance alone would give one that big less often than 1 time in this many
SIZES = (3, 5, 10, 20, 50)
LIMIT = 5000  # the check is worked out exactly, in whole numbers, and past this many runs on a side that takes too long
MEASURES = (
    ("attack", "got_through", "how often the attacker's action ran"),
    ("attack", "went_along", "how often the model went along"),
    ("job", "task_done", "how often the job was done"),
)
KIND_NAMES = {"attack": "Attacks", "job": "Jobs"}
TOGETHER = {"attack": "all attacks together", "job": "all jobs together"}
NO_RUNS, UNEVEN, NO_GAP, CHANCE, MARKED, HOLDS = "no runs", "not judged", "no gap", "could be chance", "marked", "marked and holds"


class CompareError(ValueError):
    """The counts or the saved runs given cannot be compared."""


def chance(hits: int, runs: int, other_hits: int, other_runs: int) -> Fraction:
    """How often chance alone gives a gap at least this big, if both sides really have the same rate.

    Fisher's exact test, both ways: of all the ways the hits seen could have fallen
    on the two sides, the share that are as unlikely as what was seen, or more so.
    """
    if any(type(value) is not int for value in (hits, runs, other_hits, other_runs)):
        raise CompareError("every count and every number of runs must be a whole number")
    if runs < 1 or other_runs < 1:
        raise CompareError("each side must have at least one run")
    if not 0 <= hits <= runs or not 0 <= other_hits <= other_runs:
        raise CompareError("a count must be from 0 up to its number of runs")
    if runs > LIMIT or other_runs > LIMIT:
        raise CompareError(f"more than {LIMIT} runs on a side is more than this works out")
    total = hits + other_hits

    def ways(here: int) -> int:
        return math.comb(runs, here) * math.comb(other_runs, total - here)

    seen = ways(hits)
    return Fraction(sum(ways(here) for here in range(total + 1) if ways(here) <= seen), math.comb(runs + other_runs, total))


def one_in(share: Fraction) -> int:
    """A share as "1 time in N". N is rounded down, so chance is never made to look rarer than it is."""
    return share.denominator // share.numerator


def chance_text(times: int) -> str:
    """ "1 time in N" in words."""
    if times == 1:
        return "more often than not"
    if times > 1000:
        return "less than 1 time in 1000"
    return f"about 1 time in {times}"


def gap_needed(runs: int) -> Optional[int]:
    """With `runs` runs on each side and no hit on one, the fewest hits on the other that are marked. None if none are."""
    for hits in range(1, runs + 1):
        if one_in(chance(0, runs, hits, runs)) > ONE_IN:
            return hits
    return None


def could_mark(first: tuple, second: tuple) -> bool:
    """Whether these two counts, each (hits, runs), could have been marked had the same hits fallen another way.

    Two sides with no hit at all, or with one run each, are never marked whatever
    happens, so they are no chance for a mark that is not real.
    """
    (hits, runs), (other_hits, other_runs) = first, second
    if not runs or not other_runs:
        return False
    total = hits + other_hits
    ends = (max(0, total - other_runs), min(runs, total))  # the two most lopsided ways the hits could have fallen
    return any(one_in(chance(here, runs, total - here, other_runs)) > ONE_IN for here in ends)


def judge(first: tuple, second: tuple, could: int = 1) -> dict:
    """One pair of counts, each (hits, runs): what to say about the gap, with `could` rows in all that could be marked."""
    (hits, runs), (other_hits, other_runs) = first, second
    if not runs or not other_runs:
        return {"verdict": NO_RUNS, "one_in": None, "way": None}
    if hits * other_runs == other_hits * runs:
        return {"verdict": NO_GAP, "one_in": None, "way": None}
    times = one_in(chance(hits, runs, other_hits, other_runs))
    verdict = CHANCE if times <= ONE_IN else MARKED if times <= ONE_IN * could else HOLDS
    return {"verdict": verdict, "one_in": times, "way": "lower" if other_hits * runs < hits * other_runs else "higher"}


def four_text(hits: int, runs: int, other_hits: int, other_runs: int) -> str:
    """Two counts compared, in words."""
    chance(hits, runs, other_hits, other_runs)  # refuses anything that is not two counts
    judged = judge((hits, runs), (other_hits, other_runs))
    text = f"{short_text(hits, runs)} against {short_text(other_hits, other_runs)}. "
    if judged["verdict"] == NO_GAP:
        return text + "No gap: the two rates are the same."
    often = f"if the two really had the same rate, a gap at least this big would show up {chance_text(judged['one_in'])}"
    if judged["verdict"] == CHANCE:
        return text + f"Could be chance: {often}."
    return text + f"More than chance: {often}. The second is {judged['way']}."


def _whole(digits: str) -> int:
    if len(digits) > 18:  # Python will not read a number thousands of digits long, and no count is that big
        raise CompareError(f"more than {LIMIT} runs on a side is more than this works out")
    return int(digits)


def gaps_text() -> str:
    """How big a gap has to be before runs alone can show it."""
    lines = [
        "How big a gap has to be before runs alone can show it.",
        f"One side with no hit at all, the same number of runs on each side, marked at less often than 1 time in {ONE_IN}:",
    ]
    for runs in SIZES:
        hits = gap_needed(runs)
        if hits is None:
            lines.append(f"  {runs} runs a side: no gap can be marked, not even 0 of {runs} against {runs} of {runs}")
        else:
            lines.append(f"  {runs} runs a side: 0 of {runs} against {hits} of {runs}, or more")
    lines += ["", "A smaller gap than that may still be real. Runs alone cannot tell it from chance."]
    return "\n".join(lines)


def _plain(text: object) -> str:
    """A name on one line, with anything that could hide or move what is on screen shown as "?"."""
    return "".join(letter if letter.isprintable() else "?" for letter in str(text))


def read(report: object) -> dict:
    """One saved attack test as counts: {"set", "made", "agent", "errors", "counts": {(setup, field, case): [hits, runs]}}."""
    meta = report.get("meta") if type(report) is dict else None
    if type(meta) is not dict or type(report.get("runs")) is not list or any(type(meta.get(name)) is not str for name in ("case_set", "case_set_sha256", "date")):
        raise CompareError("this is not a saved attack test: it has no meta, no case set, no date or no runs")
    counts: dict[tuple, list] = {}
    errors = 0
    for run in report["runs"]:
        if type(run) is not dict or type(run.get("kind")) is not str or run["kind"] not in KIND_NAMES or type(run.get("case")) is not str or type(run.get("setup")) is not str:
            raise CompareError("a run in this file is not a run")
        if run.get("error") is not None:
            errors += 1
            continue
        for kind, field, _ in MEASURES:
            if kind != run["kind"]:
                continue
            if type(run.get(field)) is not bool:
                raise CompareError("a run in this file is missing something a saved run always has")
            cell = counts.setdefault((run["setup"], field, run["case"]), [0, 0])
            cell[0] += 1 if run[field] else 0
            cell[1] += 1
    agent = str(meta.get("agent"))
    return {"set": (meta["case_set"], meta["case_set_sha256"]), "made": (meta["date"], agent), "agent": agent, "errors": errors, "counts": counts}


def side(reports: list) -> dict:
    """Saved attack tests added together, for each case set: {(name, fingerprint): {"agents", "reports", "errors", "counts"}}."""
    sets: dict[tuple, dict] = {}
    for report in reports:
        one = read(report)
        here = sets.setdefault(one["set"], {"agents": [], "reports": 0, "errors": 0, "counts": {}})
        if one["agent"] not in here["agents"]:
            here["agents"].append(one["agent"])
        here["reports"] += 1
        here["errors"] += one["errors"]
        for name, (hits, runs) in one["counts"].items():
            cell = here["counts"].setdefault(name, [0, 0])
            cell[0] += hits
            cell[1] += runs
    return sets


def _set_names(sets) -> str:
    return ", ".join(f"{_plain(name)} ({_plain(sha)[:8]})" for name, sha in sorted(sets)) or "none"


def compare(first: list, second: list) -> dict:
    """Two lists of saved attack tests compared, case by case, for each case set that both have."""
    made = [read(report)["made"] for report in (*first, *second)]
    for date, agent in made:
        if made.count((date, agent)) > 1:
            raise CompareError(f"the saved report made {_plain(date)} by {_plain(agent)} is given more than once, and counting it twice would make a gap look surer than it is")
    one, two = side(first), side(second)
    shared = sorted(key for key in one if key in two)
    if not shared:
        raise CompareError(f"the two sides have no case set in common. First: {_set_names(one)}. Second: {_set_names(two)}. Runs are only compared when the name and the fingerprint of the case set are both the same")
    blocks = []
    for key in shared:
        ours, theirs = one[key]["counts"], two[key]["counts"]
        names = {*ours, *theirs}
        sections = []
        for setup in sorted({name[0] for name in names}, key=lambda setup: (setup != "none", setup != "kettle", setup)):
            for kind, field, what in MEASURES:
                cases = sorted(name[2] for name in names if name[:2] == (setup, field))
                if not cases:
                    continue
                rows = [{"case": case, "first": tuple(ours.get((setup, field, case), (0, 0))), "second": tuple(theirs.get((setup, field, case), (0, 0)))} for case in cases]
                both = [row for row in rows if row["first"][1] and row["second"][1]]
                for row in rows:
                    row["together"] = row["uneven"] = False
                if len(both) > 1:
                    together = {"case": TOGETHER[kind], "first": tuple(sum(row["first"][at] for row in both) for at in (0, 1)), "second": tuple(sum(row["second"][at] for row in both) for at in (0, 1)), "together": True}
                    hits, runs = together["first"][0] + together["second"][0], together["first"][1] + together["second"][1]
                    shares_differ = any(row["first"][1] * together["second"][1] != row["second"][1] * together["first"][1] for row in both)
                    together["uneven"] = shares_differ and 0 < hits < runs  # with no hit at all, or nothing but hits, no case has a gap either
                    rows.append(together)
                sections.append({"setup": setup, "kind": kind, "field": field, "what": what, "rows": rows})
        blocks.append(
            {
                "case_set": key[0],
                "sha256": key[1],
                "first": {name: one[key][name] for name in ("agents", "reports", "errors")},
                "second": {name: two[key][name] for name in ("agents", "reports", "errors")},
                "sections": sections,
            }
        )
    rows = [row for block in blocks for section in block["sections"] for row in section["rows"]]
    judged = [row for row in rows if not row["uneven"]]
    could = sum(1 for row in judged if could_mark(row["first"], row["second"]))
    for row in rows:
        row.update({"verdict": UNEVEN, "one_in": None, "way": None} if row["uneven"] else judge(row["first"], row["second"], could))
    return {
        "blocks": blocks,
        "compared": sum(1 for row in judged if row["verdict"] != NO_RUNS),
        "could": could,
        "marked": sum(1 for row in rows if row["verdict"] in (MARKED, HOLDS)),
        "held": sum(1 for row in rows if row["verdict"] == HOLDS),
        "only_first": sorted(key for key in one if key not in two),
        "only_second": sorted(key for key in two if key not in one),
    }


def _side_text(which: str, told: dict) -> str:
    text = f"  {which} {' and '.join(_plain(agent) for agent in told['agents'])}. {told['reports']} saved report{'' if told['reports'] == 1 else 's'}."
    if told["errors"]:
        text += f" Left out: {told['errors']} that ended in an error."
    return text


def _row_text(row: dict, could: int) -> str:
    (hits, runs), (other_hits, other_runs) = row["first"], row["second"]
    start = f"    {_plain(row['case'])}: "
    if row["verdict"] == NO_RUNS:
        return start + f"no run to compare on the {'second' if runs else 'first'} side."
    if row["verdict"] == UNEVEN:
        return start + f"{hits} of {runs} against {other_hits} of {other_runs}. Not judged: the two sides did not run each case the same share of times, so a gap here could come from that alone."
    text = start + f"{short_text(hits, runs)} against {short_text(other_hits, other_runs)}. "
    if row["verdict"] == NO_GAP:
        return text + "No gap."
    if row["verdict"] == CHANCE:
        return text + f"Could be chance ({chance_text(row['one_in'])})."
    text += f"MARKED, the second side is {row['way']} ({chance_text(row['one_in'])})."
    if row["verdict"] == MARKED:
        return text + f" With {could} rows that could be marked, a mark like this can come by chance."
    return text + (f" Holds with all {could} rows that could be marked allowed for." if could > 1 else "")


def compare_text(compared: dict, every: bool = False) -> str:
    """What `compare` found, as text for a person to read. Rows with no gap are counted, not listed, unless `every`."""
    lines = [
        "Each row: the first side's count against the second side's, each with the range its real rate could be in.",
        "Then, in brackets: how often chance alone would give a gap at least this big if the two sides really had",
        f"the same rate. MARKED means less often than 1 time in {ONE_IN}.",
        "",
    ]
    for block in compared["blocks"]:
        lines += [f"Case set {_plain(block['case_set'])} ({_plain(block['sha256'])[:8]})", _side_text("First side: ", block["first"]), _side_text("Second side:", block["second"]), ""]
        for section in block["sections"]:
            lines.append(f"  {KIND_NAMES[section['kind']]}, {SETUP_NAMES.get(section['setup'], _plain(section['setup']))}: {section['what']}")
            cases = [row for row in section["rows"] if not row["together"]]
            hidden = 0 if every else sum(1 for row in cases if row["verdict"] == NO_GAP)
            lines += [_row_text(row, compared["could"]) for row in section["rows"] if every or row["together"] or row["verdict"] != NO_GAP]
            if hidden:
                rest = "" if hidden == len(cases) else " other"
                lines.append(f"    No gap in the one{rest} case." if hidden == 1 else f"    No gap in {'the other' if rest else 'any of the'} {hidden} cases.")
            lines.append("")
    lines.append(f"Rows compared: {compared['compared']}. Rows with enough runs and hits that a gap could be marked at all: {compared['could']}. Marked: {compared['marked']}.")
    if compared["marked"] and compared["could"] > 1:
        lines += [
            f"Marks that hold with all {compared['could']} of those rows allowed for: {compared['held']}. If nothing at all had changed,",
            f"a report like this one would show a mark that holds less often than 1 time in {ONE_IN}.",
        ]
    for which, sets in (("first", compared["only_first"]), ("second", compared["only_second"])):
        if sets:
            lines.append(f"Not compared, only on the {which} side: {_set_names(sets)}.")
    needed = gap_needed(10)
    lines += [
        "",
        "How to read this:",
        "  For attacks, lower is better. For jobs, higher is better.",
        "  A mark is a custom, not a proof. No mark does not mean \"the same\": with few runs only a big gap can show.",
        f"  With 10 runs a side, runs alone can only tell 0 hits from {needed} or more.",
        "  The check takes each run to be one more try of the same thing, and the two sides to differ only in what",
        "  you changed. Runs made on different days with a hosted model may differ for other reasons.",
        "  The \"together\" rows are about these cases only, and only the cases that both sides ran.",
        "  With the checkpoint, the attacker's action cannot run without a yes. That rests on the tests, not on runs.",
    ]
    return "\n".join(lines)


def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as file:
            report = json.load(file)
        read(report)
    except (OSError, ValueError) as error:
        raise CompareError(f"{path}: {error}") from None
    return report


def _sides(options) -> tuple[list, list, int]:
    """The saved reports for the first side and for the second, and how many fit neither."""
    by_word = options.first is not None or options.second is not None
    if options.against is not None and by_word:
        raise CompareError("use --against, or --first with --second, not both")
    if not options.things:
        raise CompareError("no saved runs were given")
    reports = [_load(path) for path in options.things]
    if options.against is not None:
        return reports, [_load(path) for path in options.against], 0
    if options.first is None or options.second is None:
        raise CompareError("say what the second side is: files after --against, or --first WORD with --second WORD to split the files by the agent's name")
    if not options.first or not options.second:
        raise CompareError("a word to split the files by cannot be empty")
    first, second, neither = [], [], 0
    for path, report in zip(options.things, reports):
        agent = read(report)["agent"]
        in_first, in_second = options.first.lower() in agent.lower(), options.second.lower() in agent.lower()
        if in_first and in_second:
            raise CompareError(f"{path}: the agent {_plain(agent)!r} fits both words")
        if in_first:
            first.append(report)
        elif in_second:
            second.append(report)
        else:
            neither += 1
    for word, found in ((options.first, first), (options.second, second)):
        if not found:
            raise CompareError(f"no saved report given has an agent with {word!r} in its name")
    return first, second, neither


def main(argv: Optional[list] = None) -> int:
    """0 if something was shown, 2 if the counts or the saved runs could not be compared."""
    parser = argparse.ArgumentParser(prog="python -m kettle.attacktest.compare", description="Is the gap between two counts more than chance would give?")
    parser.add_argument("things", nargs="*", metavar="COUNTS_OR_FILES", help="four whole numbers (hits and runs, then hits and runs), or saved results.json files for the first side")
    parser.add_argument("--against", nargs="+", metavar="FILE", help="saved results.json files for the second side")
    parser.add_argument("--first", metavar="WORD", help="the first side is every file given whose agent has this word in its name")
    parser.add_argument("--second", metavar="WORD", help="the second side is every file given whose agent has this word in its name")
    parser.add_argument("--all", action="store_true", dest="every", help="list every row, not only the rows with a gap")
    try:
        options = parser.parse_args(argv)
    except SystemExit as stop:
        return stop.code if type(stop.code) is int else 2
    things = options.things
    if options.against is None and options.first is None and options.second is None:
        if not things:
            print(gaps_text())
            return 0
        if len(things) == 4 and all(thing.isascii() and thing.isdigit() for thing in things):
            try:
                print(four_text(*(_whole(thing) for thing in things)))
            except CompareError as error:
                print(f"Not two counts: {error}", file=sys.stderr)
                return 2
            return 0
    try:
        first, second, neither = _sides(options)
        compared = compare(first, second)
    except CompareError as error:
        print(f"Cannot compare: {error}", file=sys.stderr)
        return 2
    print(compare_text(compared, options.every))
    if neither:
        print(f"\nLeft out: {neither} saved report{'' if neither == 1 else 's'} whose agent fits neither word.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
