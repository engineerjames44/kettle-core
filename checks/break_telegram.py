"""Break the Telegram approver on purpose, one way at a time, and see whether the tests notice.

    .venv/bin/python checks/break_telegram.py

The approver carries a question to a phone and an answer back, so the breaks here are
ways a yes could come from the wrong person, the wrong message or the wrong action,
ways the owner could be shown something other than the action, and ways the token
could leak. The tests talk to a pretend Telegram on this machine, never the real one.
"""

from _runner import nth, rep, run

TESTS = ["test_telegram.py", "test_the_tests_stay_on_this_machine.py"]

TG = "telegram.py"

APPROVE = "decision = self._checkpoint.approve(shown.request_id, shown.fingerprint, self._approver)"
DENY = "decision = self._checkpoint.deny(shown.request_id, self._approver)"
WHO = "if any(type(found) is not int or found != self._chat_id for found in ids) or chat.get(\"type\") != \"private\":"

MUTANTS = [
    # setting it up
    ("setup: a token of any shape is taken", TG, rep('if type(token) is not str or not re.fullmatch(r"[0-9]{1,20}:[A-Za-z0-9_-]{1,120}", token):', "if type(token) is not str:")),
    ("setup: a token is matched only at its start", TG, rep('re.fullmatch(r"[0-9]{1,20}:[A-Za-z0-9_-]{1,120}", token)', 're.match(r"[0-9]{1,20}:[A-Za-z0-9_-]{1,120}", token)')),
    ("setup: a refused token is repeated in the error", TG, rep('"that is not the shape of a bot token (the value given is not shown)"', 'f"that is not the shape of a bot token: {token!r}"')),
    ("setup: a group can be the owner's chat", TG, rep("if type(chat_id) is not int or chat_id <= 0:", "if type(chat_id) is not int:")),
    ("setup: chat 0 is taken", TG, rep("chat_id <= 0:", "chat_id < 0:")),
    ("setup: True is taken as a chat", TG, rep("if type(chat_id) is not int or chat_id <= 0:", "if not isinstance(chat_id, (int, float)) or chat_id <= 0:")),
    ("setup: a chat given as text is taken", TG, rep("if type(chat_id) is not int or chat_id <= 0:", "if int(chat_id or 0) <= 0:")),
    ("setup: an empty approver name is taken", TG, rep("if type(approver) is not str or not approver:", "if False:")),
    ("setup: none at once is taken", TG, rep("at_once < 1:", "at_once < 0:")),
    ("setup: a part of a number at once is taken", TG, rep("if type(at_once) is not int or at_once < 1:", "if at_once < 1:")),
    ("setup: a time to read below nothing is taken", TG, rep("or min_read_seconds < 0:", "or False:")),
    ("setup: a time to read given as text is taken", TG, rep("if type(min_read_seconds) not in (int, float) or min_read_seconds < 0:", "if float(min_read_seconds) < 0:")),
    ("setup: no parts at all is taken", TG, rep("max_parts < 1:", "max_parts < 0:")),
    ("setup: the api address is not checked", TG, rep("self._api = _checked_api(api)", "self._api = api")),
    ("setup: plain http to any machine is taken", TG, rep('if parts.scheme != "https" and not (parts.scheme == "http" and host in ("127.0.0.1", "localhost", "::1")):', 'if parts.scheme not in ("https", "http"):')),
    ("setup: a host that only starts like this machine is taken", TG, rep('host in ("127.0.0.1", "localhost", "::1")', 'host.startswith(("127.0.0.1", "localhost", "::1"))')),
    ("setup: an address with a name and password in it is taken", TG, rep("or parts.username or parts.password or", "or")),
    ("setup: an address with a path is taken", TG, rep('parts.path not in ("", "/")', "False")),
    ("setup: an address with a query is taken", TG, rep('or parts.query or parts.fragment:', "or parts.fragment:")),
    ("setup: an address with a fragment is taken", TG, rep('or parts.query or parts.fragment:', "or parts.query:")),
    ("setup: an address with a port that is no number stops the program", TG, rep("    except ValueError:\n        host = None\n", "    except KeyError:\n        host = None\n")),
    ("setup: the default settings are looser", TG, rep("min_read_seconds: float = 2.0,", "min_read_seconds: float = 0.0,")),
    ("setup: more are shown at once by default", TG, rep("at_once: int = 3,", "at_once: int = 30,")),
    ("setup: a proxy is used to reach this machine", TG, rep("            handlers.append(urllib.request.ProxyHandler({}))\n", "            pass\n")),
    # the token
    ("token: a redirect is followed", TG, rep("handlers: list = [_NoRedirects]", "handlers: list = []")),
    ("token: it is left in what is reported", TG, rep("return text.replace(self._token, TOKEN_REMOVED)[:300]", "return text[:300]")),
    ("token: repr shows it", TG, rep('return f"TelegramApprover(chat {self._chat_id},', 'return f"TelegramApprover({self._token}, chat {self._chat_id},')),
    ("token: the address that failed is put in the error", TG, rep('raise TelegramError(f"Telegram could not be reached for {method} ({type(error).__name__})") from None', 'raise TelegramError(f"Telegram could not be reached for {method} at {request.full_url} ({type(error).__name__})") from None')),
    # what is sent
    ("sent: the preview is not marked as fixed-width text", TG, rep('"text": text, "entities": entities, "link_preview_options"', '"text": text, "link_preview_options"')),
    ("sent: the text is read as markup", TG, rep('"link_preview_options": {"is_disabled": True}}', '"link_preview_options": {"is_disabled": True}, "parse_mode": "HTML"}')),
    ("sent: links in the preview get a preview of their own", TG, rep(', "link_preview_options": {"is_disabled": True}}', "}")),
    ("sent: a button names the request", TG, rep('"callback_data": "a:" + shown.nonce', '"callback_data": "a:" + shown.request_id')),
    ("sent: a button names the action", TG, rep("self.nonce = secrets.token_urlsafe(24)", "self.nonce = fingerprint[:32]")),
    ("sent: the code on a button is short", TG, rep("self.nonce = secrets.token_urlsafe(24)", "self.nonce = secrets.token_urlsafe(3)")),
    ("sent: two actions share one code", TG, rep("self.nonce = secrets.token_urlsafe(24)", 'self.nonce = "the-same-code-for-every-action-there-is"')),
    ("sent: an action too long to read still gets an Approve button", TG, rep('[{"text": "Approve", "callback_data": "a:" + shown.nonce}] if shown.can_approve else []', '[{"text": "Approve", "callback_data": "a:" + shown.nonce}]')),
    ("sent: the buttons go out before the rest of the action", TG, rep("last = shown.sent == len(shown.parts) - 1", "last = shown.sent == 0")),
    ("sent: an answer that names no message counts as sent", TG, rep('            if type(message_id) is not int:\n                raise TelegramError("Telegram did not say which message it sent")\n', "")),
    ("sent: every held action is sent at once", TG, rep("room = self._at_once - len(self._shown)", "room = len(new)")),
    ("sent: one more than at_once is sent", TG, rep("room = self._at_once - len(self._shown)", "room = self._at_once - len(self._shown) + 1")),
    ("sent: how many are waiting is not said", TG, rep('parts, can_approve = _parts(item["preview"], len(new) - index - 1, self._max_parts)', 'parts, can_approve = _parts(item["preview"], 0, self._max_parts)')),
    ("sent: how many are waiting is one too many", TG, rep('parts, can_approve = _parts(item["preview"], len(new) - index - 1, self._max_parts)', 'parts, can_approve = _parts(item["preview"], len(new) - index, self._max_parts)')),
    ("sent: the setting for the most parts is not used", TG, rep('parts, can_approve = _parts(item["preview"], len(new) - index - 1, self._max_parts)', 'parts, can_approve = _parts(item["preview"], len(new) - index - 1)')),
    ("sent: an action that is no longer open keeps its buttons", TG, rep("        for shown in gone:  # answered somewhere else, or expired\n", "        for shown in []:  # answered somewhere else, or expired\n")),
    ("sent: an action that is no longer open is never forgotten", TG, rep("            for shown in gone:\n                self._forget(shown)\n", "")),
    ("sent: the state of an action that closed is not said", TG, rep("f\"No longer open ({found['state'] if found else 'gone'}). Nothing more can be done with it here.\"", '"No longer open. Nothing more can be done with it here."')),
    # the parts of a long preview
    ("parts: any number of parts can be approved", TG, rep("can_approve = len(blocks) <= max_parts", "can_approve = True")),
    ("parts: exactly the most parts cannot be approved", TG, rep("can_approve = len(blocks) <= max_parts", "can_approve = len(blocks) < max_parts")),
    ("parts: all of an action too long to read is sent", TG, rep("    if not can_approve:\n        blocks = blocks[:1]\n", "")),
    ("parts: a part is longer than a message can be", TG, rep("PART_CHARS = 3600 ", "PART_CHARS = 5000 ")),
    ("parts: lines are joined up", TG, rep('block = line if not block else block + "\\n" + line', 'block = line if not block else block + " " + line')),
    ("parts: the line a part breaks at is lost", TG, rep("            blocks, block = blocks + [block], line\n", '            blocks, block = blocks + [block], ""\n')),
    ("parts: the last part is lost", TG, rep("    blocks.append(block)\n", "")),
    ("parts: the first line is missing", TG, rep("            head.append(FIRST_LINE)\n", "            pass\n")),
    ("parts: the parts are not numbered", TG, rep("        if len(blocks) > 1:\n            head.append", "        if False:\n            head.append")),
    ("parts: where the buttons are is not said", TG, rep('(" The buttons are under the last part." if number < len(blocks) else "")', '""')),
    ("parts: what Approve does is not said", TG, rep('            below = "\\n\\n" + HOW_TO\n', '            below = ""\n')),
    ("parts: an action too long to read does not say so", TG, rep('below = f"\\n\\n{NOT_HERE} It is', 'below = f"\\n\\nIt is')),
    ("parts: the fixed-width mark starts in the wrong place", TG, rep('"offset": _units(above)', '"offset": 0')),
    ("parts: the fixed-width mark stops short", TG, rep('"length": _units(block)}', '"length": _units(block) - 1}')),
    # who pressed, and where
    ("press: the sender is not checked", TG, rep('ids = (sender.get("id"), chat.get("id"))', 'ids = (chat.get("id"),)')),
    ("press: the chat is not checked", TG, rep('ids = (sender.get("id"), chat.get("id"))', 'ids = (sender.get("id"),)')),
    ("press: the kind of chat is not checked", TG, rep(WHO, 'if any(type(found) is not int or found != self._chat_id for found in ids):')),
    ("press: an id that is not a number can match", TG, rep(WHO, 'if any(str(found) != str(self._chat_id) for found in ids) or chat.get("type") != "private":')),
    ("press: either the sender or the chat is enough", TG, rep("if any(type(found) is not int or found != self._chat_id for found in ids)", "if all(type(found) is not int or found != self._chat_id for found in ids)")),
    ("press: a press by someone else gets no answer", TG, rep("            return self._answer(query_id, NOT_YOURS)\n", "            return None\n")),
    ("press: a press with no sender stops the listener", TG, rep('sender = query.get("from") if type(query.get("from")) is dict else {}', 'sender = query.get("from")')),
    ("press: a press with no message stops the listener", TG, rep('message = query.get("message") if type(query.get("message")) is dict else {}', 'message = query.get("message")')),
    ("press: a press with no chat stops the listener", TG, rep('chat = message.get("chat") if type(message.get("chat")) is dict else {}', 'chat = message.get("chat")')),
    ("press: data that is not text stops the listener", TG, rep('data.partition(":") if type(data) is str else ("", "", "")', 'data.partition(":")')),
    ("press: an update that is not a press stops the listener", TG, rep("        if type(query) is not dict:\n            return  #", "        if query is None:\n            return  #")),
    ("press: a button counts on any message", TG, rep("elif shown is None or message.get(\"message_id\") != shown.buttons_message:", "elif shown is None:")),
    ("press: any letter before the code is a deny", TG, rep('shown = self._nonces.get(nonce) if kind in ("a", "d") else None', "shown = self._nonces.get(nonce)")),
    ("press: the code alone is enough", TG, rep('shown = self._nonces.get(nonce) if kind in ("a", "d") else None', "shown = self._nonces.get(nonce) or self._nonces.get(kind)")),
    ("press: the start of the code is enough", TG, rep('shown = self._nonces.get(nonce) if kind in ("a", "d") else None', 'shown = next((each for code, each in self._nonces.items() if nonce and code.startswith(nonce)), None) if kind in ("a", "d") else None')),
    ("press: an approve made up for a Deny-only action counts", TG, rep('            elif kind == "a" and not shown.can_approve:\n                return_text = NOT_HERE\n', "")),
    ("press: an approve at once counts", TG, rep('            elif kind == "a" and self._clock() - shown.shown_at < self._min_read:\n                return_text = TOO_SOON\n', "")),
    ("press: an approve exactly on time is too soon", TG, rep("self._clock() - shown.shown_at < self._min_read:", "self._clock() - shown.shown_at <= self._min_read:")),
    ("press: a deny can be too soon", TG, rep('elif kind == "a" and self._clock() - shown.shown_at < self._min_read:', "elif self._clock() - shown.shown_at < self._min_read:")),
    ("press: the time to read is counted from when the approver was made", TG, rep("shown.buttons_message, shown.shown_at = message_id, self._clock()", "shown.buttons_message = message_id")),
    ("press: a press that does not count gets no answer", TG, rep("            return self._answer(query_id, return_text, alert=True)\n", "            return None\n")),
    ("press: a press that does not count is not shown as an alert", TG, rep("return self._answer(query_id, return_text, alert=True)", "return self._answer(query_id, return_text)")),
    # the answer
    ("answer: a deny is a yes", TG, rep('            if kind == "a":\n                ' + APPROVE, "            if True:\n                " + APPROVE)),
    ("answer: an approve is a no", TG, rep('            if kind == "a":\n                ' + APPROVE, "            if False:\n                " + APPROVE)),
    ("answer: the yes is for whatever is stored now", TG, rep(APPROVE, 'decision = self._checkpoint.approve(shown.request_id, next((p["fingerprint"] for p in self._checkpoint.pending() if p["request_id"] == shown.request_id), shown.fingerprint), self._approver)')),
    ("answer: the action runs as soon as it is approved", TG, rep(APPROVE, APPROVE + "\n                self._checkpoint.run(shown.request_id)")),
    ("answer: who said yes is not written down", TG, rep(APPROVE, "decision = self._checkpoint.approve(shown.request_id, shown.fingerprint)")),
    ("answer: who said no is not written down", TG, rep(DENY, "decision = self._checkpoint.deny(shown.request_id)")),
    ("answer: a yes the checkpoint refused is reported as approved", TG, rep('text = "Approved. It runs once, exactly as shown." if decision.status == APPROVED else decision.reason', 'text = "Approved. It runs once, exactly as shown."')),
    ("answer: a no the checkpoint refused is reported as denied", TG, rep('text = "Denied. Nothing was run." if decision.status == DENIED else decision.reason', 'text = "Denied. Nothing was run."')),
    ("answer: the person is not told what came of the press", TG, rep("        self._answer(query_id, text)\n        self._take_buttons_off(shown, text)\n", "        self._take_buttons_off(shown, text)\n")),
    ("answer: the buttons stay on after the answer", TG, rep("        self._answer(query_id, text)\n        self._take_buttons_off(shown, text)\n", "        self._answer(query_id, text)\n")),
    ("answer: the buttons are not taken off, only a note is sent", TG, rep("            if shown.buttons_message is not None:\n                self._call(\"editMessageReplyMarkup\"", "            if False:\n                self._call(\"editMessageReplyMarkup\"")),
    ("answer: no note says what was answered", TG, rep("            if shown.sent:\n                self._call(\"sendMessage\"", "            if False:\n                self._call(\"sendMessage\"")),
    ("answer: the note does not name the action", TG, rep('"text": f"{text}\\n\\n{shown.tool}, fingerprint {shown.fingerprint[:12]}..."[:MESSAGE_LIMIT]', '"text": text[:MESSAGE_LIMIT]')),
    ("answer: the note holds the whole fingerprint", TG, rep("fingerprint {shown.fingerprint[:12]}...", "fingerprint {shown.fingerprint}...")),
    ("answer: an answered action is left on the list", TG, rep("        finally:\n            with self._lock:\n                self._forget(shown)\n", "        finally:\n            pass\n")),
    # listening
    ("listen: an update is handed over again and again", TG, rep("            self._offset = max(self._offset, number + 1)  #", "            pass  #")),
    ("listen: typed messages are asked for too", TG, rep('"allowed_updates": ["callback_query"]', '"allowed_updates": ["callback_query", "message"]')),
    ("listen: an answer that is not ok is taken", TG, rep('if type(answer) is not dict or answer.get("ok") is not True:', "if type(answer) is not dict:")),
    # faults
    ("fault: one fault stops the loop for good", TG, rep("                wait, retry = retry, min(retry * 2, 30.0)\n", "                return\n")),
    ("fault: the same fault is reported on every try", TG, rep("        if new:  # the same fault is reported once, not on every try\n", "        if True:  # the same fault is reported once, not on every try\n")),
    ("fault: a fault is not reported at all", TG, rep("        if new:  # the same fault is reported once, not on every try\n", "        if False:  # the same fault is reported once, not on every try\n")),
    ("fault: the last fault is not kept", TG, rep("            self.last_error = text\n", "            pass\n")),
    ("fault: the report does not say that nothing is approved", TG, rep('line = f"kettle.telegram: {text}. Nothing is approved while this lasts."', 'line = f"kettle.telegram: {text}."')),
    ("fault: a reporter that fails stops the approver", TG, rep("            except Exception:\n                pass\n\n    def _send_step", "            except ZeroDivisionError:\n                pass\n\n    def _send_step")),
    ("fault: Telegram's own reason is left out", TG, rep('said = said if type(said) is str else "no reason given"', 'said = "no reason given"')),
    ("fault: the code Telegram gave is left out", TG, rep("Telegram refused {method} ({error.code}: {said})", "Telegram refused {method} ({said})")),
    ("fault: a failed answer to a press stops the buttons coming off", TG, lambda t: nth(t, "        except TelegramError as error:\n            self._note(error)\n", "        except ZeroDivisionError as error:\n            self._note(error)\n", 1)),
    # starting, stopping and waiting
    ("start: starting twice makes two approvers", TG, rep("            if self._stop is not None:\n                return\n", "")),
    ("stop: the loops are not told to stop", TG, rep("            stop.set()\n", "            pass\n")),
    ("stop: old buttons work again after the next start", TG, rep("            self._shown.clear()\n            self._nonces.clear()\n", "")),
    ("stop: repr still says running", TG, rep("{'running' if self._stop is not None else 'stopped'}", "{'running'}")),
    ("wait: a request that is not there stops the program", TG, rep('state = found["state"] if found else "unknown"', 'state = found["state"]')),
    ("wait: the time limit is not kept", TG, rep('if state != "held" or (end is not None and time.monotonic() >= end):', 'if state != "held" or (end is not None and time.monotonic() >= end + 3):')),
    ("on_held: the action runs with no answer", TG, rep("        if state == APPROVED:\n            done", "        if state != DENIED:\n            done")),
    ("on_held: the action does not run after a yes", TG, rep("        if state == APPROVED:\n            done", "        if False:\n            done")),
    ("on_held: a failure after the yes is reported as the result", TG, rep("if done.status == RAN else done.reason", "if True else done.reason")),
    ("on_held: a no is reported as no answer", TG, rep("return SAID_NO if state == DENIED else NO_ANSWER", "return NO_ANSWER")),
    ("on_held: no answer is reported as a no", TG, rep("return SAID_NO if state == DENIED else NO_ANSWER", "return SAID_NO")),
    ("on_held: the approver is not started", TG, rep("        self.start()\n        state = self.wait(decision.request_id)", "        state = self.wait(decision.request_id, 3.0)")),
    ("on_held: a result that is not text is passed on as it is", TG, rep("(done.result if type(done.result) is str else str(done.result))", "done.result")),
]

if __name__ == "__main__":
    run(MUTANTS, TESTS)
