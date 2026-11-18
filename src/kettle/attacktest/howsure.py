"""How sure a count can make you: the range the real rate could be in, given how many runs were made.

    python -m kettle.attacktest.howsure
    python -m kettle.attacktest.howsure 0 22
    python -m kettle.attacktest.howsure runs/*/results.json

No model takes part and nothing here costs anything.

"0 of 22" is a count, not a rate. If an attack really got through one time in
twenty, 22 runs would show none at all about one time in three. So beside each
count this gives a range: the lowest and the highest rate that still fit what
was seen. With two numbers it gives the range for that one count. With the paths
of saved attack tests it counts, for each agent and each attack, how often the
attacker's action ran and how often the model went along, in the runs made with
no checkpoint and in the runs made with it. With nothing, it shows how many runs
with no hit at all a claim such as "under 5%" needs.

The range is the Wilson score interval at 95 in 100. In plain words: if the same
number of runs were made many times over, a range worked out this way would hold
the real rate about 95 times in 100.

What this cannot show. The range takes each run to be one more try of the same
thing. Runs of one attack on one model on one day are close to that. Runs of
different attacks added together are not: that range is about these attacks, and
says nothing about an attack nobody has written yet. A hosted model changes, so
a range is for the days the runs were made. And a run that ended in an error is
left out and counted apart, since it shows nothing either way.
"""

from __future__ import annotations

import json
import math
import sys
from typing import Optional

Z95 = 1.959963984540054  # the two-sided 95 in 100 point of the normal curve
CLAIMS = (0.20, 0.10, 0.05, 0.02, 0.01)
SETUP_NAMES = {"none": "no checkpoint", "kettle": "with the checkpoint"}
ALL = "all attacks together"


class HowSureError(ValueError):
    """The numbers given cannot be a count out of a number of runs."""


def _whole(value: object) -> bool:
    return type(value) is int


def between(count: int, runs: int) -> tuple[float, float]:
    """The lowest and highest real rate that fit `count` hits in `runs` runs, each from 0 to 1."""
    if not _whole(count) or not _whole(runs):
        raise HowSureError("the count and the runs must be whole numbers")
    if runs < 1:
        raise HowSureError("there must be at least one run")
    if count < 0 or count > runs:
        raise HowSureError("the count must be from 0 up to the number of runs")
    seen = count / runs
    square = Z95 * Z95
    middle = seen + square / (2 * runs)
    spread = Z95 * math.sqrt(seen * (1 - seen) / runs + square / (4 * runs * runs))
    under = 1 + square / runs
    low = 0.0 if count == 0 else max(0.0, (middle - spread) / under)
    high = 1.0 if count == runs else min(1.0, (middle + spread) / under)
    return low, high


def runs_needed(below: float) -> int:
    """How many runs with no hit at all it takes before the top of the range is under `below`."""
    if type(below) is not float or not 0 < below < 1:
        raise HowSureError("the rate to get under must be a number between 0 and 1")
    runs = max(1, math.floor(Z95 * Z95 * (1 - below) / below))
    while between(0, runs)[1] >= below:
        runs += 1
    return runs


def percents(low: float, high: float) -> tuple[int, int]:
    """The range in whole percents, rounded outwards so the range said is never tighter than the one worked out."""
    return math.floor(low * 100 + 1e-9), math.ceil(high * 100 - 1e-9)


def range_text(count: int, runs: int) -> str:
    """One count in words: "0 of 22 (the real rate could be anywhere from 0% to 15%)"."""
    low, high = percents(*between(count, runs))
    return f"{count} of {runs} (the real rate could be anywhere from {low}% to {high}%)"


def short_text(count: int, runs: int) -> str:
    """One count for a table: "0 of 22 (0% to 15%)"."""
    low, high = percents(*between(count, runs))
    return f"{count} of {runs} ({low}% to {high}%)"


def tally(reports: list[dict]) -> list[dict]:
    """Add saved attack tests together: one block for each agent and case set, with a row for each attack and setup.

    Reports are only added together when the agent, the name of the case set and the
    set's fingerprint are all the same. Jobs are left out: this is about attacks.
    """
    blocks: dict[tuple, dict] = {}
    for report in reports:
        meta = report["meta"]
        key = (str(meta.get("agent")), str(meta.get("case_set")), str(meta.get("case_set_sha256")))
        block = blocks.setdefault(key, {"agent": key[0], "case_set": key[1], "sha256": key[2], "reports": 0, "rows": {}})
        block["reports"] += 1
        for run in report["runs"]:
            if run["kind"] != "attack":
                continue
            for case in (run["case"], ALL):
                row = block["rows"].setdefault((case, run["setup"]), {"case": case, "setup": run["setup"], "runs": 0, "errors": 0, "ran": 0, "went_along": 0})
                if run["error"] is not None:
                    row["errors"] += 1
                    continue
                row["runs"] += 1
                row["ran"] += 1 if run["got_through"] else 0
                row["went_along"] += 1 if run["went_along"] else 0
    tallied = []
    for block in blocks.values():
        rows = sorted(block["rows"].values(), key=lambda row: (row["case"] == ALL, row["case"], row["setup"] != "none", row["setup"]))
        tallied.append({**block, "rows": rows})
    return tallied


def _row_text(row: dict) -> str:
    name = SETUP_NAMES.get(row["setup"], row["setup"])
    if row["runs"] == 0:
        text = f"    {name}: no run to count."
    else:
        text = f"    {name}: ran {short_text(row['ran'], row['runs'])}; went along {short_text(row['went_along'], row['runs'])}."
    if row["errors"]:
        text += f" Left out: {row['errors']} that ended in an error."
    return text


def tally_text(tallied: list[dict]) -> str:
    """The blocks from `tally` as text for a person to read."""
    lines = [
        "\"ran\" is how often the attacker's action ran. \"went along\" is how often the model tried it.",
        "After each count, in brackets: the lowest and the highest real rate that still fit that count.",
        "",
    ]
    for block in tallied:
        lines += [f"{block['agent']}, {block['case_set']} ({block['sha256'][:8]}), {block['reports']} saved report{'' if block['reports'] == 1 else 's'}"]
        case = None
        for row in block["rows"]:
            if row["case"] != case:
                case = row["case"]
                lines.append(f"  {case}")
            lines.append(_row_text(row))
        lines.append("")
    lines += [
        "How to read this:",
        "  A range is what the runs alone can show, 95 times in 100, if each run is one more try of the same thing.",
        f"  The \"{ALL}\" rows are about these attacks only. They say nothing about an attack nobody has written yet.",
        "  With the checkpoint, the count does not rest on the runs: a tool that needs a yes cannot run without one,",
        "  and the tests hold that. The range there only says how little a small number of runs can show by itself.",
        f"  From runs alone, \"under 5%\" takes {runs_needed(0.05)} runs with no hit, and \"under 1%\" takes {runs_needed(0.01)}.",
    ]
    return "\n".join(lines)


def claims_text() -> str:
    """How many runs with no hit each claim needs."""
    lines = ["Runs with no hit at all that it takes before the runs alone can say the real rate is:"]
    lines += [f"  under {round(below * 100)}%: {runs_needed(below)} runs" for below in CLAIMS]
    lines += ["", "One hit in those runs and the claim is gone: " + range_text(1, runs_needed(0.05)) + "."]
    return "\n".join(lines)


def main(argv: Optional[list] = None) -> int:
    """0 if something was shown, 2 if the numbers were not a count or no saved run could be read."""
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print(claims_text())
        return 0
    if len(args) == 2 and all(arg.isascii() and arg.isdigit() for arg in args):
        try:
            print(range_text(int(args[0]), int(args[1])))
        except HowSureError as error:
            print(f"Not a count: {error}", file=sys.stderr)
            return 2
        return 0
    reports = []
    for path in args:
        try:
            with open(path, encoding="utf-8") as file:
                report = json.load(file)
            tally([report])
            reports.append(report)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            print(f"Left out: {path}: {error!r}", file=sys.stderr)
    if not reports:
        return 2
    print(tally_text(tally(reports)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
