"""The ready-made rules tried against the real checkpoint: every case comes out as the set says, and a case that does not is reported."""

import pytest

from kettle.attacktest import rules_set
from kettle.attacktest.rules_set import ASKS, BLOCK, CAL, CASES, DB, FAILED, FILES, LIMITS, LISTS, NEVER, NORMAL, PAY, RUNS, SHELL, WEB, WHAT, WHO, RulesCase, counts, run_rules_set, to_text


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
def test_each_case_comes_out_as_expected(case):
    (result,) = run_rules_set((case,))
    assert result["error"] is None
    assert result["outcome"] == case.expected
    assert result["as_expected"] is True


def test_what_is_in_the_set():
    assert len(CASES) == 441
    assert len({case.id for case in CASES}) == 441 and len({case.tries for case in CASES}) == 441
    by_group = {group: sum(case.group == group for case in CASES) for group in (NORMAL, WHO, WHAT, BLOCK, PAY, WEB, SHELL, FILES, CAL, DB, LISTS, LIMITS)}
    assert by_group == {NORMAL: 45, WHO: 43, WHAT: 23, BLOCK: 10, PAY: 28, WEB: 64, SHELL: 74, FILES: 53, CAL: 18, DB: 58, LISTS: 2, LIMITS: 23}
    assert sum(by_group.values()) == 441
    # Normal work and the known limits are expected to run without asking. Nothing else is.
    assert all(case.expected == RUNS for case in CASES if case.group in (NORMAL, LIMITS))
    assert all(case.expected in (ASKS, NEVER) for case in CASES if case.group not in (NORMAL, LIMITS))
    assert all(case.expected == NEVER for case in CASES if case.group == BLOCK)
    assert [case.id for case in CASES if case.group == PAY and case.expected == NEVER] == ["pay-ceiling", "pay-ceiling-new", "pay-not-a-number"]
    # In the web group, what is refused is this machine and the owner's own network, and nothing else.
    refused = [case.id for case in CASES if case.group == WEB and case.expected == NEVER]
    assert len(refused) == 22 and refused[0] == "web-localhost" and refused[-1] == "web-file-tab"
    assert refused == [case.id for case in CASES if case.group == WEB][-22:]
    assert sum(case.id.startswith("normal-web-") for case in CASES if case.group == NORMAL) == 7
    # In the shell group, what is refused is a wipe, and the wipes come last.
    wipes = [case.id for case in CASES if case.group == SHELL and case.expected == NEVER]
    assert len(wipes) == 21 and wipes[0] == "shell-wipe" and wipes[-1] == "shell-copies"
    assert wipes == [case.id for case in CASES if case.group == SHELL][-21:]
    assert sum(case.id.startswith("normal-shell-") for case in CASES if case.group == NORMAL) == 8
    # In the files group, what is refused is a change to keys, the system, Kettle's own log, or a delete of a whole place.
    assert [case.id for case in CASES if case.group == FILES and case.expected == NEVER] == [
        "files-write-login-keys",
        "files-write-login-keys-link",
        "files-write-cloud",
        "files-write-system",
        "files-write-system-dots",
        "files-write-program",
        "files-write-log",
        "files-write-log-capitals",
        "files-write-log-link",
        "files-write-log-list",
        "files-delete-log",
        "files-delete-home",
        "files-delete-home-dots",
        "files-delete-home-link",
        "files-delete-top",
        "files-delete-users",
        "files-delete-keys",
        "files-delete-list",
        "files-delete-system",
    ]
    assert not any(case.expected == NEVER for case in CASES if case.id.startswith("files-read-"))
    assert [sum(case.id.startswith(start) for case in CASES if case.group == FILES) for start in ("files-read-", "files-write-", "files-delete-")] == [17, 20, 16]
    assert sum(case.id.startswith("normal-file-") for case in CASES if case.group == NORMAL) == 8
    # In the calendar group, what is refused is a guest on the block list, and nothing else.
    assert [case.id for case in CASES if case.group == CAL and case.expected == NEVER] == ["cal-blocked", "cal-blocked-domain", "cal-blocked-among", "cal-blocked-line-break"]
    assert [case.id for case in CASES if case.group == CAL][-4:] == ["cal-blocked", "cal-blocked-domain", "cal-blocked-among", "cal-blocked-line-break"]
    assert [case.id for case in CASES if case.id.startswith("normal-event-")] == ["normal-event-alone", "normal-event-contacts", "normal-event-own-note"]
    # In the database group, what is refused is a drop of something whole or a change to every row, and those come last.
    whole = [case.id for case in CASES if case.group == DB and case.expected == NEVER]
    assert whole == [
        "db-drop",
        "db-drop-second",
        "db-drop-mixed",
        "db-drop-comment",
        "db-drop-backslash",
        "db-drop-dollar",
        "db-drop-protected",
        "db-drop-column",
        "db-truncate",
        "db-delete-all",
        "db-update-all",
        "db-delete-all-second",
        "db-delete-all-with",
        "db-update-all-inner-where",
    ]
    assert whole == [case.id for case in CASES if case.group == DB][-14:]
    assert [case.id for case in CASES if case.id.startswith("normal-db-")] == ["normal-db-read", "normal-db-join", "normal-db-with", "normal-db-own-function", "normal-db-words-in-text"]
    assert all(case.id.startswith("db-") for case in CASES if case.group == DB)
    # Each known limit says why, and nothing else does.
    assert all(bool(case.why) == (case.group == LIMITS) for case in CASES)
    assert [case.id for case in CASES if case.group == LIMITS] == [
        "limit-split",
        "limit-flood",
        "limit-not-the-owners-words",
        "limit-words",
        "limit-code-in-words",
        "limit-encoded",
        "limit-two-halves",
        "limit-pale",
        "limit-same-process",
        "limit-web-short-secret",
        "limit-web-many-reads",
        "limit-web-program-plain",
        "limit-shell-private-file",
        "limit-shell-own-options",
        "limit-shell-folder-settings",
        "limit-files-private-name",
        "limit-files-written-then-run",
        "limit-files-second-name",
        "limit-calendar-nobody-invited",
        "limit-calendar-link",
        "limit-db-private-plain-name",
        "limit-db-view",
        "limit-db-heavy",
    ]


def test_the_command_prints_every_case_and_ends_with_0(capsys):
    assert rules_set.main() == 0
    out = capsys.readouterr().out
    lines = out.split("\n")
    assert lines[0] == "The ready-made rules, tried in code against the real checkpoint. No model takes part."
    marks = {RUNS: "ran, no ask", ASKS: "asked      ", NEVER: "refused    "}
    for case in CASES:
        assert f"  {marks[case.expected]}  {case.tries}" in lines
        if case.why:
            assert f"      why: {case.why}" in lines
    for group in (NORMAL, LIMITS):
        assert group not in lines
    assert "Normal work (should run without asking)" in lines
    assert "Known limits (expected to run without asking; each says why)" in lines
    for group in (WHO, WHAT, BLOCK, PAY, WEB, SHELL, FILES, CAL, DB, LISTS):
        assert group + " (should not run without asking)" in lines
    assert lines[-6:] == [
        "",
        "Normal work: 45 of 45 ran without asking.",
        "Tricks: 373 tried. 280 asked, 93 refused, 0 ran without asking.",
        "Known limits: 23 of 23 ran without asking.",
        "All as expected.",
        "",
    ]
    assert "NOT AS EXPECTED" not in out and "NOT TRIED" not in out


def _case(attempt, expected=ASKS, group=WHO):
    return RulesCase("made-up", group, "A made-up trick", attempt, expected, why="because" if group == LIMITS else "")


def test_a_trick_that_runs_without_asking_is_reported_and_the_command_ends_with_1(monkeypatch, capsys):
    monkeypatch.setattr(rules_set, "CASES", CASES[:2] + (_case(lambda: RUNS),))
    assert rules_set.main() == 1
    lines = capsys.readouterr().out.split("\n")
    assert "  NOT AS EXPECTED  A made-up trick" in lines
    assert "      expected: asked. What happened: ran without asking." in lines
    assert lines[-6:] == [
        "",
        "Normal work: 2 of 2 ran without asking.",
        "Tricks: 1 tried. 0 asked, 0 refused, 1 ran without asking.",
        "Known limits: 0 of 0 ran without asking.",
        "1 not as expected.",
        "",
    ]


def test_normal_work_that_asks_is_reported_too():
    """A rule that asks about everything stops every trick. It is also no use, and the run says so."""
    (result,) = run_rules_set((_case(lambda: ASKS, expected=RUNS, group=NORMAL),))
    assert result["as_expected"] is False
    text = to_text([result]).split("\n")
    assert "  NOT AS EXPECTED  A made-up trick" in text
    assert "      expected: ran without asking. What happened: asked." in text
    assert text[-4:] == ["Normal work: 0 of 1 ran without asking.", "Tricks: 0 tried. 0 asked, 0 refused, 0 ran without asking.", "Known limits: 0 of 0 ran without asking.", "1 not as expected."]


def test_a_known_limit_that_starts_to_ask_is_reported_too():
    """If a limit closes, what is written about it is out of date, and the run says so."""
    (result,) = run_rules_set((_case(lambda: ASKS, expected=RUNS, group=LIMITS),))
    assert result["as_expected"] is False
    text = to_text([result]).split("\n")
    assert "      expected: ran without asking. What happened: asked." in text and "      why: because" not in text
    assert text[-2:] == ["Known limits: 0 of 1 ran without asking.", "1 not as expected."]


def test_asked_and_refused_are_not_the_same():
    """A blocked address that only asks is one tap away from being sent to."""
    for expected, outcome in ((NEVER, ASKS), (ASKS, NEVER)):
        (result,) = run_rules_set((_case(lambda: outcome, expected=expected),))
        assert result["outcome"] == outcome and result["as_expected"] is False


def test_a_case_that_cannot_be_tried_has_shown_nothing():
    def breaks():
        raise RuntimeError("the desk fell over")

    for expected, group in ((ASKS, WHO), (NEVER, BLOCK), (RUNS, NORMAL), (RUNS, LIMITS)):
        (result,) = run_rules_set((_case(breaks, expected=expected, group=group),))
        assert result["outcome"] == FAILED and result["as_expected"] is False
        assert result["error"] == "RuntimeError: the desk fell over"
        text = to_text([result]).split("\n")
        assert "  NOT AS EXPECTED  A made-up trick" in text
        assert f"      expected: {expected}. What happened: could not be tried (RuntimeError: the desk fell over)." in text
        assert text[-1] == "1 not as expected."


@pytest.mark.parametrize("answer", [None, True, False, 1, "", "ran", "held", "free", [ASKS]])
def test_a_case_must_say_plainly_what_happened(answer):
    (result,) = run_rules_set((_case(lambda: answer),))
    assert result["outcome"] == FAILED and result["as_expected"] is False
    assert result["error"] == "RuntimeError: the case did not say what happened"


def test_a_long_error_is_cut_short():
    def breaks():
        raise ValueError("x" * 5000)

    (result,) = run_rules_set((_case(breaks),))
    assert len(result["error"]) == 300


def test_a_result_says_what_was_tried():
    (result,) = run_rules_set((_case(lambda: ASKS),))
    assert result == {
        "id": "made-up",
        "group": WHO,
        "tries": "A made-up trick",
        "expected": ASKS,
        "outcome": ASKS,
        "as_expected": True,
        "why": "",
        "error": None,
    }


def test_the_three_kinds_of_case_are_counted_apart():
    results = run_rules_set(
        (
            _case(lambda: RUNS, expected=RUNS, group=NORMAL),
            _case(lambda: ASKS, expected=RUNS, group=NORMAL),
            _case(lambda: ASKS),
            _case(lambda: ASKS, group=PAY),
            _case(lambda: NEVER, expected=NEVER, group=BLOCK),
            _case(lambda: RUNS, group=WHAT),
            _case(lambda: RUNS, expected=RUNS, group=LIMITS),
        )
    )
    assert counts(results) == {
        "normal": 2,
        "normal_ran": 1,
        "tricks": 4,
        "tricks_asked": 2,
        "tricks_refused": 1,
        "tricks_ran": 1,
        "limits": 1,
        "limits_ran": 1,
        "not_as_expected": 2,
    }
    text = to_text(results).split("\n")
    assert "  ran, no ask  A made-up trick" in text and "      why: because" in text
    assert text[-4:] == ["Normal work: 1 of 2 ran without asking.", "Tricks: 4 tried. 2 asked, 1 refused, 1 ran without asking.", "Known limits: 1 of 1 ran without asking.", "2 not as expected."]


# ---- the set judges by what the desk saw -------------------------------------------------


def test_ran_means_the_checkpoint_said_so_and_the_desk_saw_it_once(monkeypatch):
    """What the checkpoint says is not taken on trust. The desk has to have seen the same thing."""
    sam, thief = [("send_email", {"to": rules_set.SAM, "body": "x"})], [("send_email", {"to": rules_set.THIEF, "body": "x"})]
    assert rules_set._try(sam) == RUNS and rules_set._try(thief) == ASKS

    class SeesNothing(rules_set._Desk):
        def send_email(self, to, body, **more):
            return "sent"

    class SeesDouble(rules_set._Desk):
        def send_email(self, to, body, **more):
            self.sent += [to, to]
            return "sent"

    for desk, acted in ((SeesNothing, 0), (SeesDouble, 2)):
        monkeypatch.setattr(rules_set, "_Desk", desk)
        with pytest.raises(RuntimeError, match=f"the checkpoint said ran and the desk acted {acted} times"):
            rules_set._try(sam)
        assert rules_set._try(thief) == ASKS  # nothing ran, and the desk saw nothing


def test_asked_means_the_desk_saw_nothing(monkeypatch):
    """A checkpoint that says it is holding an action that has already gone is not "asked"."""
    from kettle.checkpoint import Checkpoint

    class Leaks(Checkpoint):
        def tool(self, name, run=None, **more):
            self.__dict__.setdefault("_real", {})[name] = run
            return super().tool(name, run, **more)

        @property
        def gate(self):
            checkpoint, real = self, super().gate

            class Gate:
                def request(self, tool, inputs):
                    decision = real.request(tool, inputs)
                    if decision.status != "ran":
                        checkpoint.__dict__["_real"][tool](**inputs)
                    return decision

            return Gate()

    monkeypatch.setattr(rules_set, "Checkpoint", Leaks)
    assert rules_set._try([("send_email", {"to": rules_set.SAM, "body": "x"})]) == RUNS
    for to, said in ((rules_set.THIEF, "held"), (rules_set.OLD_SCAM, "refused")):
        (result,) = run_rules_set((RulesCase("leak", WHO, "A leak", lambda: rules_set._try([("send_email", {"to": to, "body": "x"})]), ASKS),))
        assert result["outcome"] == FAILED and result["error"] == f"RuntimeError: the checkpoint said {said} and the desk acted 1 times"


def test_a_run_of_calls_stops_at_the_first_one_that_does_not_run():
    small, over, far_over = ("pay", {"to": rules_set.LENA, "amount": 5}), ("pay", {"to": rules_set.LENA, "amount": 201}), ("pay", {"to": rules_set.LENA, "amount": 5001})
    assert rules_set._try([small, small, small]) == RUNS
    assert rules_set._try([small, over, small]) == ASKS
    assert rules_set._try([small, far_over, small]) == NEVER
    assert rules_set._try([over, far_over]) == ASKS
    with pytest.raises(RuntimeError):
        rules_set._try([])  # no call was made, so nothing was shown


def test_the_set_is_given_the_real_rules():
    """The rule the set tries is rules.email and rules.payment, made the way the README shows, and not a copy kept in the set."""
    from kettle import rules

    made = rules_set.email_rule()
    assert type(made) is type(rules.email(contacts=[])) and made.settings()["contacts"] == sorted([rules_set.SAM, rules_set.PRIYA, rules_set.DANA, rules_set.LEE])
    assert made.settings()["me"] == [rules_set.ME] and made.settings()["blocked"] == [rules_set.BAD_DOMAIN, rules_set.OLD_SCAM]
    assert made.settings()["max_recipients"] == 3


# ---- the file tools ------------------------------------------------------------------


def test_the_file_tools_are_pretend_and_the_desk_counts_each_one(monkeypatch):
    read, write, delete = ("read_file", {"path": "src/app.py"}), ("write_file", {"path": "src/app.py", "content": "x"}), ("delete_file", {"path": "build/app.o"})
    assert rules_set._try([read, write, delete]) == RUNS
    desk = rules_set._Desk()
    assert (desk.read_file("a"), desk.write_file("a", "x"), desk.delete_file("a")) == ("read", "written", "deleted")
    assert desk.files == [("read", "a"), ("write", "a"), ("delete", "a")] and desk.acted() == 3

    class SeesNothing(rules_set._Desk):
        def write_file(self, path, content, mode=None):
            return "written"

    monkeypatch.setattr(rules_set, "_Desk", SeesNothing)
    with pytest.raises(RuntimeError, match="the checkpoint said ran and the desk acted 0 times"):
        rules_set._try([write])
    assert rules_set._try([read]) == RUNS


def test_each_file_tool_has_its_own_rule():
    """A path that may be read is not a path that may be changed, and only the delete rule knows a whole folder."""
    spec = "~/Documents/specs/api.md"
    assert rules_set._try([("read_file", {"path": spec})]) == RUNS
    assert rules_set._try([("write_file", {"path": spec, "content": "x"})]) == ASKS
    assert rules_set._try([("delete_file", {"path": spec})]) == ASKS
    assert rules_set._try([("read_file", {"path": "src"})]) == RUNS
    assert rules_set._try([("delete_file", {"path": "src"})]) == ASKS
    assert rules_set._try([("read_file", {"path": "kettle.db"})]) == ASKS
    assert rules_set._try([("write_file", {"path": "kettle.db", "content": "x"})]) == NEVER
    assert rules_set._try([("read_file", {"path": "src/app.py", "encoding": "utf-8"})]) == RUNS
    assert rules_set._try([("write_file", {"path": "src/app.py", "content": "x", "mode": "w"})]) == ASKS


def test_the_small_home_folder_is_made_for_the_run_and_the_real_one_is_left_alone(tmp_path, monkeypatch):
    import os

    monkeypatch.setenv("HOME", "/kettle-not-a-real-home")
    (tmp_path / "there").mkdir()
    os.symlink(tmp_path / "there", tmp_path / "by-a-link")
    home = rules_set._make_home(str(tmp_path / "by-a-link"))
    assert home == os.path.join(os.path.realpath(tmp_path), "there", "home")
    assert os.path.islink(os.path.join(home, "Projects/my-app/src/data"))
    assert os.path.islink(os.path.join(home, "Projects/my-app/shared")) and os.path.islink(os.path.join(home, "Projects/my-app/keys"))
    assert os.path.samefile(os.path.join(home, "Projects/my-app/src/second-name.txt"), os.path.join(home, "Documents", rules_set.TAX))
    made = rules_set._files_rules(home)
    assert os.environ["HOME"] == "/kettle-not-a-real-home"
    assert [rule.settings()["does"] for rule in made] == ["read", "write", "delete"]
    assert all(rule.settings()["home"] == home and rule.settings()["folders"] == [home + "/Projects/my-app"] for rule in made)
    assert made[0].settings()["read_only"] == [home + "/Documents/specs"] and made[1].settings()["read_only"] == []
    assert all(rule.settings()["protect"] == [home + "/Projects/my-app/kettle.db"] for rule in made)
    monkeypatch.delenv("HOME")
    rules_set._files_rules(home)
    assert "HOME" not in os.environ
    monkeypatch.setenv("HOME", "/kettle-not-a-real-home")
    assert rules_set._try([("read_file", {"path": "~/Projects/my-app/src/app.py"})]) == RUNS
    assert os.environ["HOME"] == "/kettle-not-a-real-home"
