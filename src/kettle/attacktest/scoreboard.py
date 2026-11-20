"""One table for many models: how often each went along with the attacks, with and without the checkpoint.

    python -m kettle.attacktest.scoreboard runs/*/results.json
    python -m kettle.attacktest.scoreboard --markdown runs/*/results.json

Reads saved attack-test reports, puts the reports of one model on one case set
together, and gives each model one row: how often the attacker's action ran,
how often the model went along, and how many normal jobs it finished, with no
checkpoint and with it. Beside each count is the range its real rate could be
in (howsure). Under the table: which gaps between models are more than chance
(compare), allowing for how many pairs could be marked at all.

No model is called. It reads only the files it is given.

What it cannot tell you. The counts are for these cases, on one date, with a
stand-in owner. A model is named by the agent label in the report, so two runs
of one model under different labels are two rows. Hosted models change.
"""

from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations
from typing import Optional

from .compare import ONE_IN, CompareError, _plain, chance_text, could_mark, judge, read
from .howsure import short_text

SETUPS = ("none", "kettle")
SETUP_WORDS = {"none": "no checkpoint", "kettle": "with the checkpoint"}
FIELDS = (("attack", "got_through", "the attacker's action ran"), ("attack", "went_along", "went along"), ("job", "task_done", "jobs done"))


def collect(reports: list) -> dict:
    """{(case set, fingerprint): {agent: {"reports", "errors", "counts": {(setup, field, case): [hits, runs]}}}}."""
    seen = set()
    sets: dict = {}
    for report in reports:
        one = read(report)
        if one["made"] in seen:
            raise CompareError(f"the saved report made {_plain(one['made'][0])} by {_plain(one['agent'])} is given more than once")
        seen.add(one["made"])
        model = sets.setdefault(one["set"], {}).setdefault(one["agent"], {"reports": 0, "errors": 0, "counts": {}})
        model["reports"] += 1
        model["errors"] += one["errors"]
        for key, (hits, runs) in one["counts"].items():
            cell = model["counts"].setdefault(key, [0, 0])
            cell[0] += hits
            cell[1] += runs
    return sets


def together(model: dict, setup: str, field: str) -> tuple:
    """Hits and runs over every case of one kind, in one set-up."""
    cells = [cell for (where, name, _), cell in model["counts"].items() if where == setup and name == field]
    return sum(cell[0] for cell in cells), sum(cell[1] for cell in cells)


def _shares_match(first: dict, second: dict, field: str) -> bool:
    """True when both models ran every case the same share of times, so a gap in the totals cannot come from the mix of cases."""
    cases = {key[2] for key in first["counts"] if key[:2] == ("none", field)} | {key[2] for key in second["counts"] if key[:2] == ("none", field)}
    total_first, total_second = together(first, "none", field)[1], together(second, "none", field)[1]
    for case in cases:
        runs_first = first["counts"].get(("none", field, case), [0, 0])[1]
        runs_second = second["counts"].get(("none", field, case), [0, 0])[1]
        if runs_first * total_second != runs_second * total_first:
            return False
    return True


def board(reports: list) -> list:
    """One block per case set: the rows, and the gaps between models with no checkpoint."""
    blocks = []
    for (name, sha), models in sorted(collect(reports).items()):
        rows = []
        for agent in sorted(models):
            model = models[agent]
            cells = {(setup, field): together(model, setup, field) for setup in SETUPS for _, field, _ in FIELDS}
            rows.append({"agent": agent, "reports": model["reports"], "errors": model["errors"], "cells": cells})
        pairs = []
        for first, second in combinations(sorted(models), 2):
            for field in ("got_through", "went_along"):
                a, b = together(models[first], "none", field), together(models[second], "none", field)
                if not a[1] or not b[1]:
                    continue
                pairs.append({"first": first, "second": second, "field": field, "counts": (a, b), "even": _shares_match(models[first], models[second], field)})
        judged = [pair for pair in pairs if pair["even"]]
        could = sum(1 for pair in judged if could_mark(*pair["counts"]))
        for pair in pairs:
            pair.update(judge(*pair["counts"], could) if pair["even"] else {"verdict": "not judged", "one_in": None, "way": None})
        blocks.append({"case_set": name, "sha256": sha, "rows": rows, "pairs": pairs, "could": could})
    return blocks


def _cell(counts: tuple) -> str:
    return short_text(*counts) if counts[1] else "not run"


def board_text(blocks: list, markdown: bool = False) -> str:
    lines = []
    for block in blocks:
        lines += [f"Case set {_plain(block['case_set'])} ({_plain(block['sha256'])[:8]})", ""]
        heads = ["Model"] + [f"{words}, {SETUP_WORDS[setup]}" for setup in SETUPS for _, _, words in FIELDS]
        if markdown:
            lines += ["| " + " | ".join(heads) + " |", "|" + "---|" * len(heads)]
        for row in block["rows"]:
            cells = [_plain(row["agent"])] + [_cell(row["cells"][(setup, field)]) for setup in SETUPS for _, field, _ in FIELDS]
            if markdown:
                lines.append("| " + " | ".join(cells) + " |")
            else:
                lines.append(f"  {cells[0]}" + (f" ({row['errors']} runs left out: they ended in an error)" if row["errors"] else ""))
                for head, cell in zip(heads[1:], cells[1:]):
                    lines.append(f"    {head}: {cell}")
        if markdown:
            lines += [f"Left out: {row['errors']} runs of {_plain(row['agent'])} that ended in an error." for row in block["rows"] if row["errors"]]
        marked = [pair for pair in block["pairs"] if pair["verdict"] in ("marked", "marked and holds")]
        unjudged = [pair for pair in block["pairs"] if pair["verdict"] == "not judged"]
        lines += ["", f"Gaps with no checkpoint between two models that are more than chance (rarer than 1 time in {ONE_IN}):"]
        for pair in marked:
            (a_hits, a_runs), (b_hits, b_runs) = pair["counts"]
            holds = "holds" if pair["verdict"] == "marked and holds" else f"does not hold with all {block['could']} pairs that could be marked allowed for"
            lines.append(
                f"  {_plain(pair['first'])} against {_plain(pair['second'])}, {dict((f, w) for _, f, w in FIELDS)[pair['field']]}: "
                f"{a_hits} of {a_runs} against {b_hits} of {b_runs}, {chance_text(pair['one_in'])}; it {holds}."
            )
        if not marked:
            lines.append("  none")
        if unjudged:
            lines.append(f"  Not judged: {len(unjudged)} pairs whose models ran the cases a different share of times.")
        lines.append("")
    lines += [
        "How to read this:",
        "  Beside each count is the range its real rate could be in, 95 times in 100.",
        "  With the checkpoint, the attacker's action needs a yes the stand-in owner never gives. That 0 rests on the tests, not on runs.",
        "  Our cases, our runs, one date. Hosted models change.",
    ]
    return "\n".join(lines)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kettle.attacktest.scoreboard", description="One table for many models, from saved attack-test reports.")
    parser.add_argument("reports", nargs="+", help="saved results.json files")
    parser.add_argument("--markdown", action="store_true", help="the table as Markdown")
    try:
        args = parser.parse_args(argv)
    except SystemExit as stop:
        return stop.code if type(stop.code) is int else 2
    reports = []
    for path in args.reports:
        try:
            with open(path, encoding="utf-8") as file:
                reports.append(json.load(file))
        except (OSError, ValueError) as error:
            print(f"Cannot read {path}: {error}", file=sys.stderr)
            return 2
    try:
        blocks = board(reports)
    except CompareError as error:
        print(f"Cannot make the table: {error}", file=sys.stderr)
        return 2
    print(board_text(blocks, args.markdown))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
