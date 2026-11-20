"""Open each hole the yes set looks for, one at a time, and see whether the yes set notices.

    .venv/bin/python checks/break_yes_set.py             every break (about a minute)
    .venv/bin/python checks/break_yes_set.py phone       only the breaks with "phone" in their name

`python -m kettle.attacktest --yes-set` says that a list of tricks is stopped. That is
only worth something if a trick that works would be seen. So each break here changes a
copy of the product so that one trick does work, and the yes set is run against the
copy. A break the yes set does not notice means the case for that trick proves nothing.

The last few breaks are to the yes set's own counting and reporting.

Only tests/test_yes_set.py is run. The other break scripts run the other tests against
many of the same changes.
"""

from _runner import rep, run

TESTS = ["test_yes_set.py"]

C, R, T, TG = "checkpoint/checkpoint.py", "checkpoint/record.py", "checkpoint/trail.py", "telegram.py"
Y, M = "attacktest/yes_set.py", "attacktest/__main__.py"

APPROVE = "decision = self._checkpoint.approve(shown.request_id, shown.fingerprint, self._approver)"
WHO = "if any(type(found) is not int or found != self._chat_id for found in ids) or chat.get(\"type\") != \"private\":"
NOT_FOUND = "if all(given or used for _, _, _, given, used in calls) and typed is not True and not any(listed for _, listed in lists):"
NOT_A_PRESS = '        if type(query) is not dict:\n            return  # typed text, and everything else that is not a button press, is not an answer\n'
TYPED_YES = (
    '        typed = update.get("message") if type(update.get("message")) is dict else {}\n'
    '        if type(query) is not dict and str(typed.get("text", "")).lower() in ("yes", "approve"):\n'
    "            for shown in list(self._shown.values()):\n"
    "                self._checkpoint.approve(shown.request_id, shown.fingerprint, self._approver)\n"
)

MUTANTS = [
    # the checkpoint
    ("checkpoint: the gate hands out approve", C, rep('__slots__ = ("_request", "_names", "_actor")', 'approve = None')),
    ("checkpoint: the gate hands out owner_said", C, rep('    def tool_names(self) -> list[str]:\n        return self._names()\n', '    def tool_names(self) -> list[str]:\n        return self._names()\n\n    def owner_said(self, text):\n        return self._request.__self__.owner_said(text)\n')),
    ("checkpoint: a yes need not name the action", C, rep('if not _same(fingerprint, record.fingerprint):', 'if False:')),
    ("checkpoint: a yes can be used twice", C, rep('if row["state"] != "approved":\n                    words', 'if row["state"] not in ("approved", "ran"):\n                    words', 'tx.move(request_id, ("approved",), "running"', 'tx.move(request_id, ("approved", "ran"), "running"')),
    ("checkpoint: an action runs with no yes", C, rep('if row["state"] == "held":\n                    tx.log(now, "refused"', 'if False:\n                    tx.log(now, "refused"', 'if row["state"] != "approved":\n                    words', 'if row["state"] not in ("approved", "held"):\n                    words', 'tx.move(request_id, ("approved",), "running"', 'tx.move(request_id, ("approved", "held"), "running"', 'if not _same(row["approved_fingerprint"], record.fingerprint):', 'if False:')),
    ("checkpoint: the action is run with the caller's own object, not the stored text", C, rep('                request_id = secrets.token_hex(16)\n', '                request_id = secrets.token_hex(16)\n                self.__dict__.setdefault("_callers", {})[request_id] = inputs\n', '            result = found.run(**record.inputs())', '            result = found.run(**self.__dict__.get("_callers", {}).get(request_id, record.inputs()))')),
    ("checkpoint: a stored action that was swapped still runs", C, rep('if not _same(row["fingerprint"], record.fingerprint):', 'if False:', 'if not _same(row["approved_fingerprint"], record.fingerprint):', 'if False:')),
    ("checkpoint: the yes is not compared with what is stored at run", C, rep('if not _same(row["approved_fingerprint"], record.fingerprint):', 'if False:')),
    ("checkpoint: a yes is taken after the time is up", C, lambda t: _nth(t, 'if now >= row["expires_at"]:', 'if False:', 1)),
    ("checkpoint: a yes can be used after the time is up", C, lambda t: _nth(t, 'if now >= row["expires_at"]:', 'if False:', 2)),
    # the card
    ("card: a long value is clipped, not carried on", R, rep('                lines.append(line)\n                line, count = more + lead + carried, 1 if carried else 0\n', '                return lines + [line]\n')),
    ("card: long lines are not cut", R, rep('if count and len(line) + size > room:', 'if False:')),
    ("card: carried-on lines are not marked", R, rep('    more = indent + "+ "\n', '    more = indent + "  "\n', 'indent + "+ ", json_from=len(label), width=width)', 'indent + "  ", json_from=len(label), width=width)')),
    ("card: runs of spaces are written as they are", R, rep('out.append(" " if alone else _SPACE)', 'out.append(" ")')),
    ("card: a look-alike letter is written as itself", R, rep('            out.append(f"\\\\u{{{ord(char):04X}}}")', '            out.append(char)')),
    ("card: a look-alike letter is not named", R, rep('if not odd:', 'if True:')),
    ("card: the lines of a block are not marked", R, rep('_fold(indent + "| ", _pieces(part, quoted=False), more, words=words, width=width)', '_fold(indent, _pieces(part, quoted=False), more, words=words, width=width)')),
    # the phone
    ("phone: the text is read as markup", TG, rep('"link_preview_options": {"is_disabled": True}}', '"link_preview_options": {"is_disabled": True}, "parse_mode": "HTML"}')),
    ("phone: the preview is not sent as fixed-width text", TG, rep('"text": text, "entities": entities, "link_preview_options"', '"text": text, "link_preview_options"')),
    ("phone: who pressed is not checked", TG, rep('ids = (sender.get("id"), chat.get("id"))', 'ids = (chat.get("id"),)')),
    ("phone: the chat is not checked", TG, rep('ids = (sender.get("id"), chat.get("id"))', 'ids = (sender.get("id"),)')),
    ("phone: the kind of chat is not checked", TG, rep(WHO, 'if any(type(found) is not int or found != self._chat_id for found in ids):')),
    ("phone: a button names the request", TG, rep('"callback_data": "a:" + shown.nonce', '"callback_data": "a:" + shown.request_id')),
    ("phone: a button names the action", TG, rep("self.nonce = secrets.token_urlsafe(24)", "self.nonce = fingerprint[:32]")),
    ("phone: a button counts on any message", TG, rep("elif shown is None or message.get(\"message_id\") != shown.buttons_message:", "elif shown is None:")),
    ("phone: an answered action is left on the list", TG, rep("        finally:\n            with self._lock:\n                self._forget(shown)\n", "        finally:\n            pass\n", "                self._nonces.pop(shown.nonce, None)  # from here on", "                pass  # from here on")),
    ("phone: old buttons work again after a restart", TG, rep("            self._shown.clear()\n            self._nonces.clear()\n", "")),
    ("phone: every held action is sent at once", TG, rep("room = self._at_once - len(self._shown)", "room = len(new)")),
    ("phone: an approve at once counts", TG, rep('            elif kind in ("a", "t") and self._clock() - shown.shown_at < self._min_read:\n                return_text = TOO_SOON\n', "")),
    ("phone: an action too long to read still gets an Approve button", TG, rep('[{"text": APPROVE, "callback_data": "a:" + shown.nonce}] if shown.can_approve else []', '[{"text": APPROVE, "callback_data": "a:" + shown.nonce}]')),
    ("phone: an approve made up for a Deny-only action counts", TG, rep('            elif kind in ("a", "t") and not shown.can_approve:\n                return_text = NOT_HERE\n', "")),
    ("phone: any number of parts can be approved", TG, rep("can_approve = len(blocks) <= max_parts", "can_approve = True")),
    ("phone: a typed yes counts", TG, rep(NOT_A_PRESS, TYPED_YES + NOT_A_PRESS)),
    ("phone: with no answer the action is run", TG, rep("        if state == APPROVED:\n            done", "        if state != DENIED:\n            done")),
    ("phone: no answer is reported as a no", TG, rep("return SAID_NO if state == DENIED else NO_ANSWER", "return SAID_NO")),
    ("phone: the yes is for whatever is stored now", TG, rep(APPROVE, 'decision = self._checkpoint.approve(shown.request_id, next((p["fingerprint"] for p in self._checkpoint.pending() if p["request_id"] == shown.request_id), shown.fingerprint), self._approver)')),
    # the source trail
    ("trail: a call that was handed the value counts as a source", T, rep('"found": any(not given and not used for _, given, used in seen) or', '"found": bool(seen) or')),
    ("trail: on the card, a call that was handed the value counts as a source", R, rep(NOT_FOUND, 'if not calls and typed is not True and not any(listed for _, listed in lists):')),
    ("trail: a value the agent had already used still counts as a source", T, rep('self._overfull or (first_use is not None and first_use < result[6])', 'self._overfull')),
    ("trail: the calls the agent asked for are not kept", C, rep('            self._trail.asked(inputs)  #', '            pass  #')),
    ("trail: on the card, a value the agent had already used counts as a source", R, rep(NOT_FOUND, 'if all(given for _, _, _, given, used in calls) and typed is not True and not any(listed for _, listed in lists):')),
    ("trail: a cut call name carries on looking like a note of its own", R, rep('mark, more = indent + "! ", indent + "! + "', 'mark, more = indent + "! ", indent + "! "')),
    ("trail: what a tool returned counts as typed by the owner", T, rep('            if texts:\n                self._results.append(', '            self._typed.extend(texts)\n            if texts:\n                self._results.append(')),
    ("trail: typed means anywhere in the text", T, rep('typed = any(whole_word(value, text) for text in self._typed)', 'typed = any(value in text for text in self._typed)')),
    ("trail: typed is matched without regard to capitals", T, rep('typed = any(whole_word(value, text) for text in self._typed)', 'typed = any(whole_word(value.lower(), text.lower()) for text in self._typed)')),
    ("trail: what stands after a typed value is not looked at", T, rep(' and (not after or after.isspace() or after in _CLOSERS):', ':')),
    ("trail: what stands before a typed value is not looked at", T, rep('if (not before or before.isspace() or before in _OPENERS) and (', 'if (')),
    ("trail: a list is matched by a part of an entry", T, rep('known = [[name, value in self._known[name]] for name in sorted(self._known)]', 'known = [[name, any(value in entry for entry in self._known[name])] for name in sorted(self._known)]')),
    ("trail: a list is matched without regard to capitals", T, rep('known = [[name, value in self._known[name]] for name in sorted(self._known)]', 'known = [[name, value.lower() in {entry.lower() for entry in self._known[name]}] for name in sorted(self._known)]')),
    # the yes set's own counting
    ("report: the command always ends with 0", M, rep('return 0 if all(result["as_expected"] for result in results) else 1', 'return 0')),
    ("report: the command ends with 0 if any case is as expected", M, rep('return 0 if all(result["as_expected"] for result in results) else 1', 'return 0 if any(result["as_expected"] for result in results) else 1')),
    ("report: a case that cannot be tried counts as stopped", Y, rep('outcome, error = FAILED, f"{type(problem).__name__}: {problem}"[:300]', 'outcome, error = STOPPED, f"{type(problem).__name__}: {problem}"[:300]')),
    ("report: a case that cannot be tried counts as getting through", Y, rep('outcome, error = FAILED, f"{type(problem).__name__}: {problem}"[:300]', 'outcome, error = GETS_THROUGH, f"{type(problem).__name__}: {problem}"[:300]')),
    ("report: anything that is not False counts as stopped", Y, rep('(STOPPED if case.attempt() is True else GETS_THROUGH)', '(STOPPED if case.attempt() else GETS_THROUGH)')),
    ("report: every case is as expected", Y, rep('"as_expected": outcome == case.expected,', '"as_expected": True,')),
    ("report: a stopped case is always as expected", Y, rep('"as_expected": outcome == case.expected,', '"as_expected": outcome in (case.expected, STOPPED),')),
    ("report: a case that is not as expected is not marked", Y, rep('            mark = "NOT AS EXPECTED"', '            mark = "stopped     "')),
    ("report: a known limit is printed as stopped", Y, rep('mark = "stopped     " if result["outcome"] == STOPPED else "GETS THROUGH"', 'mark = "stopped     "')),
    ("report: the last line always says all as expected", Y, rep('lines.append(f"{wrong} not as expected." if wrong else "All as expected.")', 'lines.append("All as expected.")')),
    ("report: a trick that works is counted as a known limit", Y, rep('known = sum(result["outcome"] == GETS_THROUGH and result["as_expected"] for result in results)', 'known = sum(result["outcome"] == GETS_THROUGH for result in results)')),
    ("report: why a limit gets through is left out", Y, rep('        elif result["why"]:\n', '        elif False:\n')),
    ("report: the error of a case that could not be tried is left out", Y, rep('(f" ({result[\'error\']})" if result["error"] else "")', '""')),
    ("report: the same-process limit is listed as stopped", Y, rep('        _code_in_the_same_process_reaches_past_the_gate,\n        expected=GETS_THROUGH,', '        _code_in_the_same_process_reaches_past_the_gate,\n        expected=STOPPED,')),
    ("report: the two-halves limit is listed as stopped", Y, rep('        _the_address_is_written_in_two_halves_and_read_back,\n        expected=GETS_THROUGH,', '        _the_address_is_written_in_two_halves_and_read_back,\n        expected=STOPPED,')),
    ("report: a case is dropped from the set", Y, rep('    YesCase("yes-used-twice", CHECKPOINT, "One yes is used to run the action a second time", _one_yes_is_used_twice),\n', '')),
]


def _nth(text, old, new, n):
    from _runner import nth

    return nth(text, old, new, n)


if __name__ == "__main__":
    run(MUTANTS, TESTS)
