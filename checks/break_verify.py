"""Break the receipts one way at a time, and see whether their tests notice.

    .venv/bin/python checks/break_verify.py           every break (under a minute)
    .venv/bin/python checks/break_verify.py yes       only the breaks with "yes" in their name

`python -m kettle.verify` says: the file is only read, each receipt is for an action
that was started after a yes, the action printed is the one the yes was for, and
anything that does not add up is said and ends with 1. Each break here makes one of
those untrue in a copy of the package, and tests/test_verify.py is run against the copy.

Only tests/test_verify.py is run. The checkpoint itself has its own break script.
"""

from _runner import rep, run

TESTS = ["test_verify.py"]

V = "verify.py"

CHECKED = 'if record.fingerprint != entry["fingerprint"] or record.tool != entry["tool"]:'
YES = 'yes = next((each for each in reversed(earlier) if each["event"] == "approved"), None)'
EARLIER = 'earlier = [each for each in by_request[request_id] if each["seq"] < entry["seq"]]'
LATER = 'later = [each for each in by_request[request_id] if each["seq"] > entry["seq"]]'
OUTCOME = '"outcome": end["event"] if end else None,'
EXIT = 'return 1 if report["wrong"] else 0'

MUTANTS = [
    # ---- the file is only read
    ("read only: the file is opened so that it can be written", V, rep('"?mode=ro"', '"?mode=rw"')),
    ("read only: a file that is not there is made", V, rep("if not os.path.isfile(self.path):", "if False:", '"?mode=ro"', '"?mode=rwc"')),
    ("read only: a file that is not there is not told apart", V, rep("if not os.path.isfile(self.path):", "if False:")),
    ("read only: the parts are read at different moments", V, rep('store.read("BEGIN")', "pass")),
    ("read only: a file from another version is read anyway", V, rep('if found is None or found["value"] != SCHEMA_VERSION:', "if found is None:")),
    ("read only: a file with no log in it is taken for a checkpoint's", V, rep('for table in ("requests", "log"):', "for table in ():")),
    ("read only: a file that cannot be read ends with 1", V, rep("        return 2", "        return 1")),
    ("read only: why it cannot be read is printed where the receipts go", V, rep('print(f"{args.file} cannot be read: {error}.", file=sys.stderr)', 'print(f"{args.file} cannot be read: {error}.")')),
    # ---- the log
    ("log: the chain is not checked", V, rep("log_ok, log_words = store.verify_log()", 'log_ok, log_words = True, "not checked"')),
    ("log: a changed log is not counted as wrong", V, rep(' [] if log_ok else [f"The log has been changed: {log_words}."]', " []")),
    ("log: a changed log is printed as whole", V, rep('if report["log_ok"] else f"THE LOG', 'if True else f"THE LOG')),
    ("log: a changed entry that cannot be read stops everything", V, rep('return entry["detail"] if type(entry.get("detail")) is dict else {}', 'return entry["detail"]')),
    ("log: what it cannot show is left out", V, rep('    lines.append("This cannot show entries cut from the end of the log, or a file rewritten by someone who can write it.")\n', "")),
    # ---- the action printed is the one the yes was for
    ("action: the stored action is not checked against the log", V, rep(CHECKED, "if False:")),
    ("action: only the tool name is checked", V, rep(CHECKED, 'if record.tool != entry["tool"]:')),
    ("action: only the fingerprint is checked", V, rep(CHECKED, 'if record.fingerprint != entry["fingerprint"]:')),
    ("action: the stored fingerprint is trusted, and not worked out again", V, rep(CHECKED, 'if row["fingerprint"] != entry["fingerprint"] or record.tool != entry["tool"]:')),
    ("action: an action that was swapped is still printed", V, rep("                else:\n                    action = record.preview()", "                action = record.preview()")),
    ("action: an action that cannot be read stops everything", V, rep("            except RecordError:", "            except ZeroDivisionError:")),
    ("action: an action that cannot be read is not reported", V, rep('problems.append("the stored action cannot be read")', "pass")),
    ("action: a stored action that is gone is not reported", V, rep('problems.append("the file has no stored action for it")', "pass")),
    ("action: the state the file gives is not compared with the log", V, rep('            if row["state"] not in STARTED_STATES:', "            if False:")),
    ("action: an end the file has and the log has not is not reported", V, rep('elif end is None and row["state"] in ENDS:', "elif False:")),
    ("action: the inputs are not printed", V, rep('            lines += ["  " + line for line in receipt["action"].splitlines()]', '            lines.append(f"  Fingerprint: {receipt[\'fingerprint\']}")')),
    # ---- the yes
    ("yes: a start with no yes is not reported", V, rep('problems.append("the log has no yes for it")', "pass")),
    ("yes: a yes after the start counts", V, rep(EARLIER, "earlier = by_request[request_id]")),
    ("yes: a yes for another request counts", V, rep(YES, 'yes = next((each for each in reversed(entries) if each["event"] == "approved" and each["seq"] < entry["seq"]), None)')),
    ("yes: a yes for a different action is not reported", V, rep('elif yes["fingerprint"] != entry["fingerprint"]:', "elif False:")),
    ("yes: who said it is not read from the log", V, rep('"yes_by": _detail(yes).get("by") if yes else None,', '"yes_by": "owner" if yes else None,')),
    ("yes: the time printed is when it started", V, rep('"yes_at": yes["at"] if yes else None,', '"yes_at": entry["at"] if yes else None,')),
    ("yes: a missing yes is printed as a yes by no one", V, rep('if receipt["yes_by"] is None and receipt["yes_at"] is None:', "if False:")),
    # ---- which actions get a receipt, and what it says happened
    ("receipts: an action that was only held gets one", V, rep('if entry["event"] != "started" or entry["request_id"] is None:', 'if entry["event"] not in ("started", "held") or entry["request_id"] is None:')),
    ("receipts: a free action gets one", V, rep('if entry["event"] != "started" or entry["request_id"] is None:', 'if entry["event"] != "started":', "earlier = [each for each in by_request[request_id]", "earlier = [each for each in by_request.get(request_id, [])", "later = [each for each in by_request[request_id]", "later = [each for each in by_request.get(request_id, [])", 'for each in by_request[request_id]) > 1:', 'for each in by_request.get(request_id, [])) > 1:')),
    ("receipts: an action started twice is not reported", V, rep('if sum(each["event"] == "started" for each in by_request[request_id]) > 1:', "if False:")),
    ("receipts: an action that failed part way is said to have run", V, rep(OUTCOME, '"outcome": "ran" if end else None,')),
    ("receipts: an action with no end is said to have run", V, rep(OUTCOME, '"outcome": end["event"] if end else "ran",')),
    ("receipts: the end of another action is used", V, rep(LATER, 'later = [each for each in entries if each["seq"] > entry["seq"]]')),
    ("receipts: the first-time marks are not shown", V, rep('"first_time": _detail(held).get("first_time") or [] if held else [],', '"first_time": [],')),
    ("receipts: the times are in this machine's own time", V, rep("datetime.fromtimestamp(float(at), timezone.utc)", "datetime.fromtimestamp(float(at))")),
    ("receipts: a time that cannot be read stops everything", V, rep("    except (TypeError, ValueError, OverflowError, OSError):", "    except TypeError:")),
    ("receipts: what does not add up is not printed with the receipt", V, rep('        lines += [f"  DOES NOT ADD UP: {problem}" for problem in receipt["problems"]]\n', "")),
    # ---- what else the log holds
    ("counts: every start is counted as a free action", V, rep('"free": count("started", with_request=False),', '"free": count("started"),')),
    ("counts: the denied are not counted", V, rep('"denied": count("denied"),', '"denied": 0,')),
    ("counts: the expired are not counted", V, rep('"expired": count("expired"),', '"expired": 0,')),
    ("counts: the cancelled are not counted", V, rep('"cancelled": count("cancelled"),', '"cancelled": 0,')),
    ("counts: the held are counted from the receipts", V, rep('"held": count("held"),', '"held": len(found),')),
    # ---- a log cut at the end
    ("cut: a request the file says was started, with nothing in the log, is not noticed", V, rep('if row["state"] in STARTED_STATES and request_id not in logged:', "if False:")),
    # ---- how it ends
    ("ends: something that does not add up still ends with 0", V, rep(EXIT, "return 0")),
    ("ends: a file where everything adds up ends with 1", V, rep(EXIT, "return 1")),
    ("ends: what does not add up is followed by 'the log is whole'", V, rep('    if report["wrong"]:\n        lines.append(f"{len(report[\'wrong\'])} thing', '    if False:\n        lines.append(f"{len(report[\'wrong\'])} thing')),
    ("ends: what does not add up is counted and not listed", V, rep('        lines += ["  " + each for each in report["wrong"]]\n', "")),
]

if __name__ == "__main__":
    run(MUTANTS, TESTS)
