"""Break the scoreboard, one way at a time, and see whether its tests notice.

    .venv/bin/python checks/break_scoreboard.py          every break (under a minute)
    .venv/bin/python checks/break_scoreboard.py pairs    only the breaks with "pairs" in their name

The breaks that matter most would make a public table say more than the runs
do: a report counted twice, runs that ended in an error counted, a gap marked
between models that ran different mixes of cases, a mark said to hold when it
does not, two models swapped.

Only tests/test_scoreboard.py is run.
"""

from _runner import rep, run

TESTS = ["test_scoreboard.py"]

S = "attacktest/scoreboard.py"

MUTANTS = [
    ("collect: a report given twice is counted twice", S, rep('        if one["made"] in seen:\n', "        if False:\n")),
    ("collect: the reports are not counted", S, rep('        model["reports"] += 1\n', "")),
    ("collect: the errors are not added up", S, rep('        model["errors"] += one["errors"]\n', "")),
    ("collect: only the last report's hits are kept", S, rep("            cell[0] += hits\n", "            cell[0] = hits\n")),
    ("collect: only the last report's runs are kept", S, rep("            cell[1] += runs\n", "            cell[1] = runs\n")),
    ("collect: models are told apart by case set only", S, rep('.setdefault(one["agent"], {', '.setdefault("one model", {')),
    ("together: the set-up is not looked at", S, rep("if where == setup and name == field]", "if name == field]")),
    ("together: what is counted is not looked at", S, rep("if where == setup and name == field]", "if where == setup]")),
    ("shares: never different", S, rep("        if runs_first * total_second != runs_second * total_first:\n            return False\n", "")),
    ("shares: the raw numbers of runs must match", S, rep("        if runs_first * total_second != runs_second * total_first:\n", "        if runs_first != runs_second:\n")),
    ("shares: only the first model's cases are looked at", S, rep(' | {key[2] for key in second["counts"] if key[:2] == ("none", field)}', "")),
    ("pairs: only going along is compared", S, rep('            for field in ("got_through", "went_along"):\n', '            for field in ("went_along",):\n')),
    ("pairs: a pair with no runs on one side is judged", S, rep("                if not a[1] or not b[1]:\n                    continue\n", "")),
    ("pairs: every pair counts as one that could be marked", S, rep("        could = sum(1 for pair in judged if could_mark(*pair[\"counts\"]))\n", "        could = len(judged)\n")),
    ("pairs: pairs that are not judged count as could be marked", S, rep('        could = sum(1 for pair in judged if could_mark(*pair["counts"]))\n', '        could = sum(1 for pair in pairs if could_mark(*pair["counts"]))\n')),
    ("pairs: an uneven pair is judged anyway", S, rep('            pair.update(judge(*pair["counts"], could) if pair["even"] else', '            pair.update(judge(*pair["counts"], could) if True else')),
    ("pairs: each pair is judged as if it were the only one", S, rep('            pair.update(judge(*pair["counts"], could) if pair["even"]', '            pair.update(judge(*pair["counts"]) if pair["even"]')),
    ("pairs: the two models are swapped", S, rep('                a, b = together(models[first], "none", field), together(models[second], "none", field)\n', '                a, b = together(models[second], "none", field), together(models[first], "none", field)\n')),
    ("pairs: compared with the checkpoint, not without", S, rep('                a, b = together(models[first], "none", field), together(models[second], "none", field)\n', '                a, b = together(models[first], "kettle", field), together(models[second], "kettle", field)\n')),
    ("text: a mark that does not hold is said to hold", S, rep('            holds = "holds" if pair["verdict"] == "marked and holds" else', '            holds = "holds" if True else')),
    ("text: a mark that holds is not listed", S, rep('        marked = [pair for pair in block["pairs"] if pair["verdict"] in ("marked", "marked and holds")]\n', '        marked = [pair for pair in block["pairs"] if pair["verdict"] == "marked"]\n')),
    ("text: pairs not judged are not said", S, rep("        if unjudged:\n", "        if False:\n")),
    ("text: errors are not said", S, rep('                lines.append(f"  {cells[0]}" + (f" ({row[\'errors\']} runs left out: they ended in an error)" if row["errors"] else ""))\n', '                lines.append(f"  {cells[0]}")\n')),
    ("text: errors are not said in the markdown table", S, rep("""            lines += [f"Left out: {row['errors']} runs of {_plain(row['agent'])} that ended in an error." for row in block["rows"] if row["errors"]]\n""", "")),
    ("text: a set-up not run is shown as 0 of 0", S, rep('    return short_text(*counts) if counts[1] else "not run"\n', '    return f"{counts[0]} of {counts[1]}"\n')),
    ("text: a name from a file is shown as it is", S, rep('            cells = [_plain(row["agent"])] +', '            cells = [row["agent"]] +')),
    ("text: the ranges are left off", S, rep('    return short_text(*counts) if counts[1] else "not run"\n', '    return f"{counts[0]} of {counts[1]}" if counts[1] else "not run"\n')),
    ("command: a file that cannot be read stops with no word", S, rep("        except (OSError, ValueError) as error:\n", "        except OSError as error:\n")),
    ("command: a report given twice is printed anyway", S, rep("    except CompareError as error:\n        print(f\"Cannot make the table: {error}\", file=sys.stderr)\n        return 2\n", "    except CompareError as error:\n        return 0\n")),
    ("command: the markdown option is not passed on", S, rep("    print(board_text(blocks, args.markdown))\n", "    print(board_text(blocks))\n")),
    ("command: a wrong option ends with 0", S, rep("        return stop.code if type(stop.code) is int else 2\n", "        return 0\n")),
]

KNOWN = {
    "shares: only the first model's cases are looked at": "a case only the second model ran makes the shares of the cases both ran differ too, so the pair is found uneven either way",
}

run(MUTANTS, TESTS, expected_to_survive=KNOWN)
