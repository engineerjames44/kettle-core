"""The scoreboard: one table for many models, from saved attack-test reports. No model."""

import json
from itertools import count

import pytest

from kettle.attacktest import load_cases, run_test, standins
from kettle.attacktest.compare import CompareError
from kettle.attacktest.scoreboard import board, board_text, collect, main, together

FRAUD = load_cases("fraud")
DATES = count(1)


def report(agent_for, label, repeats=2, setups=("none", "kettle"), only=None):
    made = json.loads(json.dumps(run_test(agent_for=agent_for, cases=FRAUD, repeats=repeats, label=label, setups=setups, only=only)))
    made["meta"]["date"] = f"2026-11-19T00:00:{next(DATES):02d}+00:00"
    return made


@pytest.fixture(scope="module")
def two():
    return report(standins.fooled, "model A"), report(standins.careful, "model B")


def block_of(blocks):
    assert len(blocks) == 1
    return blocks[0]


def test_each_model_gets_one_row_with_its_totals(two):
    rows = block_of(board(list(two)))["rows"]
    assert [row["agent"] for row in rows] == ["model A", "model B"]
    fooled, careful = rows
    assert fooled["cells"][("none", "got_through")] == (14, 14) and careful["cells"][("none", "got_through")] == (0, 14)
    assert fooled["cells"][("kettle", "got_through")] == (0, 14) and fooled["cells"][("kettle", "went_along")] == (14, 14)
    assert careful["cells"][("none", "task_done")] == (14, 14)


def test_two_reports_of_one_model_are_added_together(two):
    more = report(standins.careful, "model B", repeats=1)
    rows = block_of(board([two[1], more]))["rows"]
    assert len(rows) == 1 and rows[0]["reports"] == 2 and rows[0]["cells"][("none", "got_through")] == (0, 21)


def test_a_gap_between_two_models_is_judged_and_marked(two):
    pairs = block_of(board(list(two)))["pairs"]
    assert [(pair["field"], pair["verdict"], pair["way"]) for pair in pairs] == [("got_through", "marked and holds", "lower"), ("went_along", "marked and holds", "lower")]
    text = board_text(board(list(two)))
    assert "model A against model B, the attacker's action ran: 14 of 14 against 0 of 14, less than 1 time in 1000; it holds." in text


def test_no_gap_is_not_marked():
    same = [report(standins.careful, "model A"), report(standins.careful, "model B")]
    block = block_of(board(same))
    assert all(pair["verdict"] == "no gap" for pair in block["pairs"]) and block["could"] == 0
    assert "more than chance (rarer than 1 time in 20):\n  none" in board_text([block])


def test_models_that_ran_the_cases_a_different_share_of_times_are_not_judged(two):
    uneven = report(standins.careful, "model C", repeats=1, only=["attack-notes-address", "attack-invoice-notice"])
    pairs = block_of(board([two[0], uneven]))["pairs"]
    assert {pair["verdict"] for pair in pairs} == {"not judged"}
    assert "Not judged: 2 pairs whose models ran the cases a different share of times." in board_text(board([two[0], uneven]))


def test_a_mark_that_does_not_hold_with_many_pairs_says_so():
    a, b, c = (report(standins.careful, name, repeats=1) for name in "abc")
    for run in [run for run in a["runs"] if run["kind"] == "attack" and run["setup"] == "none"][:5]:
        run["got_through"] = run["went_along"] = True  # 5 of 7 against 0 of 7: about 1 time in 47
    blocks = board([a, b, c])
    assert blocks[0]["could"] == 4  # a against b and a against c, two counts each; b against c can never be marked
    verdicts = {(pair["first"], pair["second"], pair["field"]): (pair["verdict"], pair["one_in"]) for pair in blocks[0]["pairs"]}
    assert verdicts[("a", "b", "got_through")] == ("marked", 47) and verdicts[("b", "c", "got_through")] == ("no gap", None)
    assert "5 of 7 against 0 of 7, about 1 time in 47; it does not hold with all 4 pairs that could be marked allowed for." in board_text(blocks)


def test_runs_that_ended_in_an_error_are_left_out_and_said(two):
    broken = json.loads(json.dumps(two[1]))
    broken["meta"]["date"] = "2026-11-19T01:00:00+00:00"
    broken["runs"][0]["error"] = "RuntimeError: x"
    row = block_of(board([broken]))["rows"][0]
    assert row["errors"] == 1 and together(collect([broken])[(FRAUD.name, FRAUD.sha256)]["model B"], "none", "task_done")[1] == 13
    assert "(1 runs left out: they ended in an error)" in board_text(board([broken]))
    assert "Left out: 1 runs of model B that ended in an error." in board_text(board([broken]), markdown=True)


def test_a_report_given_twice_is_refused(two):
    with pytest.raises(CompareError, match="is given more than once"):
        board([two[0], two[0]])


def test_each_case_set_is_its_own_block(two):
    other = json.loads(json.dumps(two[1]))
    other["meta"].update({"case_set_sha256": "0" * 64, "date": "2026-11-19T02:00:00+00:00"})
    blocks = board([two[0], other])
    assert len(blocks) == 2 and [len(block["rows"]) for block in blocks] == [1, 1] and all(not block["pairs"] for block in blocks)


def test_a_set_up_that_was_not_run_says_so():
    only_none = report(standins.careful, "model A", repeats=1, setups=("none",))
    text = board_text(board([only_none]))
    assert "the attacker's action ran, with the checkpoint: not run" in text


def test_the_markdown_table_has_one_line_per_model(two):
    text = board_text(board(list(two)), markdown=True)
    lines = [line for line in text.splitlines() if line.startswith("| ")]
    assert len(lines) == 3 and lines[0].startswith("| Model | the attacker's action ran, no checkpoint |")
    assert lines[1].startswith("| model A | 14 of 14 (78% to 100%) |")


def test_a_name_from_a_file_cannot_print_control_letters(two):
    odd = json.loads(json.dumps(two[1]))
    odd["meta"].update({"agent": "evil\x1b[2J", "date": "2026-11-19T03:00:00+00:00"})
    assert "\x1b" not in board_text(board([odd])) and "evil?[2J" in board_text(board([odd]))


def test_the_command_prints_the_table_and_refuses_what_it_cannot_read(two, tmp_path, capsys):
    paths = []
    for number, made in enumerate(two):
        path = tmp_path / f"{number}.json"
        path.write_text(json.dumps(made))
        paths.append(str(path))
    assert main(paths) == 0 and "model A against model B" in capsys.readouterr().out
    assert main(["--markdown", *paths]) == 0 and "| model A |" in capsys.readouterr().out
    (tmp_path / "bad.json").write_text("{")
    assert main([str(tmp_path / "bad.json")]) == 2 and "Cannot read" in capsys.readouterr().err
    assert main([paths[0], paths[0]]) == 2 and "Cannot make the table" in capsys.readouterr().err
    assert main([]) == 2


ATTACKS = [x.id for x in FRAUD.cases() if x.kind == "attack"]


def test_two_reports_of_one_model_add_their_hits():
    rows = block_of(board([report(standins.fooled, "model A"), report(standins.fooled, "model A", repeats=1)]))["rows"]
    assert rows[0]["cells"][("none", "got_through")] == (21, 21)


def test_models_whose_shares_match_are_judged_though_their_runs_differ():
    pairs = block_of(board([report(standins.fooled, "model A", repeats=2), report(standins.careful, "model B", repeats=1)]))["pairs"]
    assert pairs[0]["counts"] == ((14, 14), (0, 7)) and pairs[0]["verdict"] == "marked and holds"


def test_pairs_that_are_not_judged_do_not_raise_the_bar():
    a, b = report(standins.careful, "a", repeats=1), report(standins.careful, "b", repeats=1)
    c = report(standins.careful, "c", repeats=2, only=ATTACKS[:3])
    for run in [run for run in a["runs"] if run["kind"] == "attack" and run["setup"] == "none"][:5]:
        run["got_through"] = run["went_along"] = True
    block = block_of(board([a, b, c]))
    assert block["could"] == 2
    assert [(pair["second"], pair["verdict"]) for pair in block["pairs"] if pair["first"] == "a"] == [("b", "marked and holds")] * 2 + [("c", "not judged")] * 2


def test_a_model_with_no_runs_without_the_checkpoint_is_in_no_pair(two):
    only_kettle = report(standins.careful, "model K", repeats=1, setups=("kettle",))
    block = block_of(board([only_kettle, two[1]]))
    assert block["pairs"] == [] and len(block["rows"]) == 2
