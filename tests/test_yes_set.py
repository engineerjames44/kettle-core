"""The attacks on the yes itself: every case comes out as the README says, and a case that does not is reported."""

import pytest

from kettle.attacktest import __main__ as cli
from kettle.attacktest import yes_set
from kettle.attacktest.yes_set import CARD, CASES, CHECKPOINT, FAILED, GETS_THROUGH, LIMITS, PHONE, STOPPED, TRAIL, YesCase, run_yes_set, to_text


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
def test_each_case_comes_out_as_expected(case):
    (result,) = run_yes_set((case,))
    assert result["error"] is None
    assert result["outcome"] == case.expected
    assert result["as_expected"] is True


def test_what_is_in_the_set():
    assert len(CASES) == 25
    assert len({case.id for case in CASES}) == 25 and len({case.tries for case in CASES}) == 25
    by_group = {group: sum(case.group == group for case in CASES) for group in (CHECKPOINT, CARD, PHONE, TRAIL, LIMITS)}
    assert by_group == {CHECKPOINT: 6, CARD: 3, PHONE: 9, TRAIL: 5, LIMITS: 2}
    # Only the known limits are expected to get through, and each one says why.
    assert [case.id for case in CASES if case.expected == GETS_THROUGH] == ["written-in-two-halves", "same-process"]
    assert all(case.group == LIMITS and case.why for case in CASES if case.expected == GETS_THROUGH)
    assert all(case.expected == STOPPED and not case.why for case in CASES if case.group != LIMITS)


def test_the_command_prints_every_case_and_ends_with_0(capsys):
    assert cli.main(["--yes-set"]) == 0
    out = capsys.readouterr().out
    lines = out.split("\n")
    assert lines[0] == "Attacks on the yes itself, tried in code. No model takes part, and the phone is a pretend Telegram on this machine."
    for case in CASES:
        mark = "stopped     " if case.expected == STOPPED else "GETS THROUGH"
        assert f"  {mark}  {case.tries}" in lines
    for group in (CHECKPOINT, CARD, PHONE, TRAIL):
        assert group in lines
    assert "Known limits (expected to get through; the README says so)" in lines
    assert "      why: the trail matches whole values, and no single call was given the whole address" in lines
    assert lines[-4:] == ["", "25 tried: 23 stopped, 2 got through (2 of them known limits).", "All as expected.", ""]
    assert "NOT AS EXPECTED" not in out


def test_the_command_needs_no_case_file(capsys):
    """The yes set has its own cases, so a case file that is wrong does not stop it."""
    assert cli.main(["--yes-set", "--cases", "no-such-file.json"]) == 0
    assert cli.main(["--list", "--cases", "no-such-file.json"]) == 2


def _case(attempt, expected=STOPPED, group=CHECKPOINT):
    return YesCase("made-up", group, "A made-up trick", attempt, expected=expected, why="because" if expected == GETS_THROUGH else "")


def test_a_trick_that_works_is_reported_and_the_command_ends_with_1(monkeypatch, capsys):
    monkeypatch.setattr(yes_set, "CASES", CASES[:2] + (_case(lambda: False),))
    assert cli.main(["--yes-set"]) == 1
    lines = capsys.readouterr().out.split("\n")
    assert "  NOT AS EXPECTED  A made-up trick" in lines
    assert "      expected: stopped. What happened: gets through." in lines
    assert lines[-4:] == ["", "3 tried: 2 stopped, 1 got through (0 of them known limits).", "1 not as expected.", ""]


def test_a_known_limit_that_is_stopped_is_reported_too():
    """If a limit closes, the README is out of date, and the run says so."""
    (result,) = run_yes_set((_case(lambda: True, expected=GETS_THROUGH, group=LIMITS),))
    assert result["outcome"] == STOPPED and result["as_expected"] is False
    text = to_text([result]).split("\n")
    assert "  NOT AS EXPECTED  A made-up trick" in text
    assert "      expected: gets through. What happened: stopped." in text
    assert text[-2:] == ["1 tried: 1 stopped, 0 got through (0 of them known limits).", "1 not as expected."]


def test_a_case_that_cannot_be_tried_has_shown_nothing():
    def breaks():
        raise RuntimeError("the pretend phone did not answer")

    for expected in (STOPPED, GETS_THROUGH):
        (result,) = run_yes_set((_case(breaks, expected=expected),))
        assert result["outcome"] == FAILED and result["as_expected"] is False
        assert result["error"] == "RuntimeError: the pretend phone did not answer"
        text = to_text([result]).split("\n")
        assert f"      expected: {expected}. What happened: could not be tried (RuntimeError: the pretend phone did not answer)." in text
        assert text[-2:] == ["1 tried: 0 stopped, 0 got through (0 of them known limits).", "1 not as expected."]


@pytest.mark.parametrize("answer", [None, 1, "yes", [True], 0])
def test_only_a_plain_true_counts_as_stopped(answer):
    (result,) = run_yes_set((_case(lambda: answer),))
    assert result["outcome"] == GETS_THROUGH and result["as_expected"] is False


def test_a_long_error_is_cut_short():
    def breaks():
        raise ValueError("x" * 5000)

    (result,) = run_yes_set((_case(breaks),))
    assert len(result["error"]) == 300


def test_a_result_says_what_was_tried():
    (result,) = run_yes_set((_case(lambda: True),))
    assert result == {
        "id": "made-up",
        "group": CHECKPOINT,
        "tries": "A made-up trick",
        "expected": STOPPED,
        "outcome": STOPPED,
        "as_expected": True,
        "why": "",
        "error": None,
    }


def test_a_known_limit_is_counted_apart_from_a_trick_that_should_not_work():
    results = run_yes_set((_case(lambda: False, expected=GETS_THROUGH, group=LIMITS), _case(lambda: False), _case(lambda: True)))
    text = to_text(results).split("\n")
    assert "  GETS THROUGH  A made-up trick" in text and "      why: because" in text
    assert text[-2:] == ["3 tried: 1 stopped, 2 got through (1 of them known limits).", "1 not as expected."]
