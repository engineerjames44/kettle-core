"""Break the checkpoint on purpose, one way at a time, and see whether the tests notice.

    .venv/bin/python checks/break_checkpoint.py            every break (under a minute)
    .venv/bin/python checks/break_checkpoint.py expiry     only the breaks with "expiry" in their name

Each break is one small change to a copy of the code, such as "a yes can be used twice".
The fixed tests are then run against the copy. A break the tests do not notice is a hole
in the tests. The code in src/ is never changed.
"""

from _runner import nth, rep, run

C, R, S, U = "checkpoint/checkpoint.py", "checkpoint/record.py", "checkpoint/store.py", "checkpoint/rules.py"
TESTS = ["test_fixed_ways_around.py", "test_record_and_preview.py", "test_log_and_setup.py", "test_workers.py", "test_first_time.py"]

CLOCK_IN = "            with self._store.write() as tx:\n                now = self._clock()\n                row = tx.get(request_id)"
CLOCK_OUT = "            now = self._clock()\n            with self._store.write() as tx:\n                row = tx.get(request_id)"

MUTANTS = [
    ("a yes can be used twice", C, rep('if row["state"] != "approved":\n                    words', 'if row["state"] not in ("approved", "ran"):\n                    words', 'tx.move(request_id, ("approved",), "running"', 'tx.move(request_id, ("approved", "ran"), "running"')),
    ("run without a yes allowed", C, rep('if row["state"] == "held":\n                    tx.log(now, "refused"', 'if False:\n                    tx.log(now, "refused"', 'if row["state"] != "approved":\n                    words', 'if row["state"] not in ("approved", "held"):\n                    words', 'tx.move(request_id, ("approved",), "running"', 'tx.move(request_id, ("approved", "held"), "running"', 'if not _same(row["approved_fingerprint"], record.fingerprint):', 'if False:')),
    ("no expiry at run", C, lambda t: nth(t, 'if now >= row["expires_at"]:', 'if False:', 2)),
    ("no expiry at approve", C, lambda t: nth(t, 'if now >= row["expires_at"]:', 'if False:', 1)),
    ("expiry boundary off by one at run", C, lambda t: nth(t, 'if now >= row["expires_at"]:', 'if now > row["expires_at"]:', 2)),
    ("yes need not name the fingerprint", C, rep('if not _same(fingerprint, record.fingerprint):', 'if False:')),
    ("approved fingerprint not compared at run", C, rep('if not _same(row["approved_fingerprint"], record.fingerprint):', 'if False:')),
    ("stored fingerprint not compared to stored record", C, rep('if not _same(row["fingerprint"], record.fingerprint):', 'if False:')),
    ("both stored checks off", C, rep('if not _same(row["fingerprint"], record.fingerprint):', 'if False:', 'if not _same(row["approved_fingerprint"], record.fingerprint):', 'if False:')),
    ("non-canonical stored text accepted", R, rep('if record.canonical != canonical:', 'if False:')),
    ("free tool runs even if the log cannot be written", C, rep('        except Exception as error:\n            return self._broken(error, tool_name)\n        return self._execute(found, record, None)', '        except Exception as error:\n            pass\n        return self._execute(found, record, None)')),
    ("no re-check of the rules at run", C, rep('found = self._recheck(record)\n                except', 'found = self._rules.find(record.tool)\n                except')),
    ("no re-check, and removed tools kept", C, rep('self._rules.remove(name)', 'pass')),
    ("dict subclasses accepted", R, rep('if kind is dict:', 'if isinstance(value, dict):', 'if type(inputs) is not dict:', 'if not isinstance(inputs, dict):')),
    ("never tools can be held", C, lambda t: nth(t, 'if level == NEVER:', 'if False:', 1)),
    ("inputs not checked against the tool", U, rep('tool.signature.bind(**inputs)', 'pass')),
    ("rule junk treated as needs_yes", U, rep('raise Refused(f"the rule for {tool.name} did not give a level")', 'level = NEEDS_YES')),
    ("rule failure treated as free", U, rep('raise Refused(f"the rule for {tool.name} failed ({type(error).__name__})") from None', 'level = FREE')),
    ("failed tool can be retried", C, rep('self._finish(request_id, record, "unknown", _error_note(error))', 'self._finish(request_id, record, "approved", _error_note(error))', 'tx.move(request_id, ("running",), state, finished_at=now, note=note)', 'tx.move(request_id, ("running",), state, note=note)')),
    ("deny does not withdraw a yes", C, rep('tx.move(request_id, ("held", "approved"), "denied"', 'tx.move(request_id, ("held",), "denied"')),
    ("denied request can be approved", C, rep('if row["state"] != "held":\n                    return Decision(REFUSED, f"Refused: that request is {_STATE_WORDS', 'if row["state"] not in ("held", "denied"):\n                    return Decision(REFUSED, f"Refused: that request is {_STATE_WORDS', 'request_id, ("held",), "approved", decided_at', 'request_id, ("held", "denied"), "approved", decided_at')),
    ("inputs taken from the caller's object", R, rep('"inputs": _plain(inputs, 0, "inputs"),', '"inputs": inputs,')),
    ("NaN allowed", R, rep('if not math.isfinite(value):', 'if False:', 'allow_nan=False', 'allow_nan=True')),
    ("log chain not checked", S, rep('if row["hash"] != wanted:', 'if False:')),
    ("log gaps not checked", S, rep('if row["seq"] != expected_seq:', 'if False:', 'if row["prev_hash"] != prev_hash:', 'if False:')),
    ("no write lock (plain BEGIN) and no thread lock", S, rep('BEGIN IMMEDIATE', 'BEGIN')),
    ("state change not conditional", S, rep('f"UPDATE requests SET {sets} WHERE id = ? AND state IN ({marks})",\n            (to_state, *fields.values(), request_id, *from_states),', 'f"UPDATE requests SET {sets} WHERE id = ?",\n            (to_state, *fields.values(), request_id),')),
    ("run reads state outside the transaction", C, rep(CLOCK_IN + '\n                if row is None:\n                    return Decision(REFUSED, "Refused: there is no such request. Nothing was run.")', '            rows = self._store.read("SELECT * FROM requests WHERE id = ?", (request_id,)) if type(request_id) is str else []\n            import time as _t; _t.sleep(0.01)\n            with self._store.write() as tx:\n                now = self._clock()\n                row = rows[0] if rows else None\n                if row is None:\n                    return Decision(REFUSED, "Refused: there is no such request. Nothing was run.")', 'if not tx.move(request_id, ("approved",), "running", started_at=now, worker=self._worker):', 'tx.move(request_id, ("approved", "running", "ran"), "running", started_at=now, worker=self._worker)\n                if False:')),
    ("gate exposes approve", C, rep('__slots__ = ("_request", "_names", "_actor")', 'approve = None')),
    ("non-ASCII not named", R, rep('if not odd:', 'if True:')),
    ("unlisted near-miss names are trimmed", U, rep('tool = self._tools.get(name) if type(name) is str else None', 'tool = self._tools.get(name.strip().lower()) if type(name) is str else None')),
    # ---- the preview, as rewritten ----
    ("characters that are not plain ASCII written as themselves", R, rep('            out.append(f"\\\\u{{{ord(char):04X}}}")', '            out.append(char)')),
    ("block lines not marked", R, rep('_fold(indent + "| ", _pieces(part, quoted=False), more)', '_fold(indent, _pieces(part, quoted=False), more)')),
    ("an empty block line not marked", R, rep('if part else [indent + "|"]', 'if part else [indent]')),
    ("quotes not escaped in preview", R, rep("""elif char == '"' and quoted:""", "elif False:")),
    ("backslash not escaped in preview", R, rep('        if char == "\\\\":\n            out.append("\\\\\\\\")\n        elif char ==', '        if False:\n            pass\n        elif char ==')),
    ("edge and double spaces not written out", R, rep('out.append(" " if alone else _SPACE)', 'out.append(" ")')),
    ("leading space not written out", R, rep('alone = 0 < index < last and', 'alone = index < last and')),
    ("trailing space not written out", R, rep('alone = 0 < index < last and', 'alone = 0 < index and')),
    ("long lines not cut", R, rep('if count and len(line) + len(piece) > room:', 'if False:')),
    ("a cut line may end in a bare space", R, rep('            if last == " ":\n                line = line[:-1] + last_space', '            if False:\n                pass')),
    ("a carried-on line may start with a bare space", R, rep('piece = space if piece == " " else piece[1:]', 'piece = piece if piece == " " else piece[1:]')),
    ("the gap is kept at the start of a carried-on line", R, rep('piece = space if piece == " " else piece[1:]', 'piece = space if piece == " " else piece')),
    ("a key's cut space written the JSON way", R, rep('space = _SPACE if json_from is None or index < json_from else _JSON_SPACE', 'space = _SPACE if json_from is None else _JSON_SPACE')),
    ("double spaces inside a JSON value not written out", R, rep('pieces.append(" " if text[index - 1] != " " and text[index + 1] != " " else _JSON_SPACE)', 'pieces.append(" ")')),
    ("a code inside a list or dict value can be cut in two", R, rep('size = 6 if text[index + 1] == "u" else 2', "size = 1")),
    ("carried-on lines not marked", R, rep('    more = indent + "+ "\n', '    more = indent + "  "\n', 'indent + "+ ", json_from=len(label))', 'indent + "  ", json_from=len(label))')),
    ("the line count of a block is not shown", R, rep('label + [f"{gap}[{len(parts)} lines]"]', 'label + [f"{gap}[lines]"]')),
    ("the actor is not shown", R, rep('if self.actor is not None:', 'if False:')),
    ("actor not checked", R, rep('"actor": None if actor is None else _plain(actor, 0, "actor"),', '"actor": actor,')),
    ("refusing a key prints the key", R, rep('(a {type(key).__name__})")', '({key!r})")')),
    # ---- found by the independent review ----
    ("the gate's caller can name the actor", C, rep('    def request(self, tool: str, inputs: dict) -> Decision:\n        return self._request(tool, inputs, self._actor)', '    def request(self, tool, inputs, actor=None):\n        return self._request(tool, inputs, actor or self._actor)')),
    ("gate_for forgets the actor", C, rep('return Gate(self, actor)', 'return Gate(self)')),
    ("gate_for takes an empty actor", C, rep('if type(actor) is not str or not actor:', 'if False:')),
    ("clock read before the wait for the store, at approve", C, lambda t: nth(t, CLOCK_IN, CLOCK_OUT, 1)),
    ("clock read before the wait for the store, at run", C, lambda t: nth(t, CLOCK_IN, CLOCK_OUT, 3)),
    ("hold time starts before the wait for the store", C, rep('                with self._store.write() as tx:\n                    now = self._clock()\n                    expires_at = now + self._hold_seconds', '                now = self._clock()\n                with self._store.write() as tx:\n                    expires_at = now + self._hold_seconds')),
    ("error note written without care", C, rep('self._finish(request_id, record, "unknown", _error_note(error))', 'self._finish(request_id, record, "unknown", f"{type(error).__name__}: {error}")')),
    ("error note can be any length", C, rep('return _clip(text, 500)', 'return _clip(text, 10**9)')),
    ("short text made with repr", C, rep('text = value if type(value) is str else f"<{type(value).__name__}>"', 'text = value if type(value) is str else repr(value)')),
    ("short text not made storable", C, rep('return text.encode("utf-8", "backslashreplace").decode("utf-8")', 'return text')),
    ("a failing checkpoint is not logged", C, rep('if not isinstance(error, StoreError):', 'if False:')),
    ("refusal reason not cut short", C, rep('detail={"reason": _clip(str(error), 500)}', 'detail={"reason": str(error)}')),
    ("asking to run before a yes is not logged", C, rep('                    tx.log(now, "refused", request_id, tool, row["fingerprint"], {"reason": "asked to run before anyone said yes"})\n', '')),
    ("asking to run a used yes is not logged", C, rep('                    tx.log(now, "refused", request_id, tool, row["fingerprint"], {"reason": f"asked to run a request that is {words}"})\n', '')),
    ("a refusal is not logged", C, rep('            self._log_quietly("refused", tool=_clip(tool), detail={"reason": _clip(str(error), 500)})\n', '')),
    ("unreadable function accepted at setup", U, rep('    if signature is None:\n        raise RulesError(', '    if False:\n        raise RulesError(')),
    ("no second try at reading type hints", U, rep('signature = inspect.signature(run, annotation_format=annotationlib.Format.STRING)', 'raise ValueError')),
    ("an input fixed by name can be given again", U, rep('fixed |= set(target.keywords)', 'pass')),
    ("an input fixed by position can be given again", U, rep('fixed |= set(names[: len(target.args)])', 'pass')),
    ("an input named like the tool's own object is let through", U, rep('fixed.add(code.co_varnames[0])', 'pass')),
    ("fixed inputs not checked", U, rep('        if taken:\n', '        if False:\n')),
    ("checking the log crashes on odd values", S, rep('except (TypeError, ValueError):  # a value of a kind', 'except ZeroDivisionError:  # a value of a kind')),
    ("reading the log crashes on odd values", S, rep('except (ValueError, TypeError):  # edited by hand', 'except ZeroDivisionError:  # edited by hand')),
    # ---- the first-time mark ----
    ("a new value is not marked", C, rep('elif not seen(_mark(record.tool, key, value)):', 'elif False:')),
    ("new items of a list are not marked", C, rep('            if items:\n                new[key] = items', '            if False:\n                new[key] = items')),
    ("a list is compared whole, not item by item", C, rep('        if type(value) is list:\n            items = [number', '        if False:\n            items = [number')),
    ("a list is remembered whole, not item by item", C, rep('for item in (value if type(value) is list else [value])]', 'for item in [value]]')),
    ("list items are numbered from 0", C, rep('enumerate(value, 1)', 'enumerate(value)')),
    ("asking makes a value known", C, rep('                    tx.insert_request(request_id, record.fingerprint, record.canonical, now, expires_at)\n', '                    tx.insert_request(request_id, record.fingerprint, record.canonical, now, expires_at)\n                    [tx.mark_seen(mark, now) for mark in _marks(record)]\n')),
    ("a yes makes a value known before it is used", C, rep('                if not moved:\n', '                [tx.mark_seen(mark, now) for mark in _marks(record)]\n                if not moved:\n')),
    ("a used yes does not make a value known", C, rep('                    tx.mark_seen(mark, now)', '                    pass')),
    ("what is known is not kept apart by tool", C, rep('text = json.dumps([tool, key, value], sort_keys=True', 'text = json.dumps(["", key, value], sort_keys=True')),
    ("what is known is not kept apart by input", C, rep('text = json.dumps([tool, key, value], sort_keys=True', 'text = json.dumps([tool, "", value], sort_keys=True')),
    ("values compared without regard to capitals", C, rep('allow_nan=False)\n    return hashlib.sha256(b"kettle-seen-v1', 'allow_nan=False).lower()\n    return hashlib.sha256(b"kettle-seen-v1')),
    ("values trimmed before they are compared", C, rep('text = json.dumps([tool, key, value], sort_keys=True', 'text = json.dumps([tool, key, value.strip() if type(value) is str else value], sort_keys=True')),
    ("numbers and text that look alike compared as the same", C, rep('text = json.dumps([tool, key, value], sort_keys=True', 'text = json.dumps([tool, key, str(value)], sort_keys=True')),
    ("the value itself is kept, not a hash", C, rep('    return hashlib.sha256(b"kettle-seen-v1\\n" + text.encode("ascii")).hexdigest()', '    return text')),
    ("what is known cannot be read, so the value is treated as known", C, rep('                    first_time = _first_time(found, record, tx.seen)\n', '                    try:\n                        first_time = _first_time(found, record, tx.seen)\n                    except Exception:\n                        first_time = {}\n')),
    ("what is known cannot be written, and the action runs anyway", S, rep('        self._connection.execute("INSERT OR IGNORE INTO seen (mark, first_at) VALUES (?, ?)", (mark, float(at)))', '        try:\n            self._connection.execute("INSERT OR IGNORE INTO seen (mark, first_at) VALUES (?, ?)", (mark, float(at)))\n        except Exception:\n            pass')),
    ("the held log entry does not say what was marked", C, rep('                        detail["first_time"] = sorted(first_time)', '                        pass')),
    ("pending leaves the mark out", C, rep('record.preview(self._summary(found, record), first_time),', 'record.preview(self._summary(found, record)),')),
    ("the decision does not say what was marked", C, rep('                    first_time=tuple(sorted(first_time)),\n', '')),
    ("the mark is left out of the preview", R, rep('            lines += marked.get(key, [])\n', '')),
    ("the count of marked inputs is left off the top", R, rep('        if marked:\n            lines.append(', '        if False:\n            lines.append(')),
    ("the mark is written without its ! sign", R, lambda t: nth(t, 'mark = indent + "! "', 'mark = indent', 2)),
    ("only the first twelve new items are named", R, rep('+ _in_runs(items)', '+ _in_runs(items[:12]) + (f" and {len(items) - 12} more" if len(items) > 12 else "")')),
    ("a run of new items is named without its last one", R, rep("            runs[-1][1] = item\n", "            pass\n")),
    ("new items next to a known one are named as one run", R, rep("if runs and item == runs[-1][1] + 1:", "if runs:")),
    ("two new items in a row are written as a run, like 17 to 18", R, rep('f"{first}, {last}" if last == first + 1 else ', "")),
    ("item numbers that make no sense are written anyway", R, rep('if type(items) is not list or not items or any(type(item) is not int or item < 1 for item in items):', 'if False:')),
    ("a watched name that is not an input is accepted", U, rep('if key in fixed or not (takes_any or key in by_name):', 'if False:')),
    ("watch can be something that is not a list", U, rep('    if type(watch) not in (tuple, list):', '    if False:')),
    ("a tool with nothing to run can watch", U, rep('    if signature is None:\n        raise RulesError(f"{name}: a tool with no function', '    if False:\n        raise RulesError(f"{name}: a tool with no function')),
    ("watched inputs are left out of the rules digest", U, rep('listed.append([name, level, list(watch)] if watch else [name, level])', 'listed.append([name, level])')),
    ("the rules digest changes for tools that watch nothing", U, rep('listed.append([name, level, list(watch)] if watch else [name, level])', 'listed.append([name, level, list(watch)])')),
]

if __name__ == "__main__":
    run(MUTANTS, TESTS)
