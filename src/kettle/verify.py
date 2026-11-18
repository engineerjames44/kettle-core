"""Receipts: for each action that ran after a yes, who said yes, when, and to exactly what.

    python -m kettle.verify my-agent.db

It reads the file a Checkpoint keeps and prints one receipt for every needs-yes
action that was started. The file is opened read-only: it is never changed, and a
file that is not there is not made.

What a receipt is built from:

- the log, which is chained, so an entry that was edited, removed from the middle
  or reordered is found (the same check as Checkpoint.verify_log);
- the stored action. Its fingerprint is worked out again here and has to be the
  one the log says was approved and started. So the inputs printed are the ones
  the yes was for.

It ends with 0 if everything adds up, 1 if something does not, and 2 if the file
cannot be read.

What it cannot show. Entries cut from the end of the log leave a whole chain; it
does notice a request the file says was started or ended with no entry for it. And
someone who can write the file can rewrite all of it. "Who" is the name the app gave to approve():
the checkpoint does not check who a person is.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from .checkpoint.record import ActionRecord, RecordError
from .checkpoint.store import SCHEMA_VERSION, Store, StoreError

STARTED_STATES = ("running", "ran", "unknown")  # a request in one of these was started
ENDS = ("ran", "unknown")  # the log entry that closes a started action


class _ReadOnly(Store):
    """The same reading and the same chain check as the checkpoint's own store, on a file opened read-only."""

    def __init__(self, path: str) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        if not os.path.isfile(self.path):
            raise StoreError("there is no such file")
        try:
            self._connection = sqlite3.connect(pathlib.Path(self.path).resolve().as_uri() + "?mode=ro", uri=True, isolation_level=None)
            self._connection.row_factory = sqlite3.Row
            found = self._connection.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
            for table in ("requests", "log"):
                self._connection.execute(f"SELECT 1 FROM {table} LIMIT 1")
        except (sqlite3.Error, OSError):
            raise StoreError("it is not a file a Kettle checkpoint keeps") from None
        if found is None or found["value"] != SCHEMA_VERSION:
            self.close()
            raise StoreError("it was made by a different version of the checkpoint")


def _detail(entry: dict) -> dict:
    return entry["detail"] if type(entry.get("detail")) is dict else {}


def _when(at: Any) -> str:
    try:
        return datetime.fromtimestamp(float(at), timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (TypeError, ValueError, OverflowError, OSError):
        return "at a time that cannot be read"


def receipts(path: str) -> dict:
    """What the file says about every needs-yes action that was started. Raises StoreError if the file cannot be read."""
    store = _ReadOnly(path)
    try:
        store.read("BEGIN")  # one look at the file, so a checkpoint writing to it meanwhile cannot make the parts disagree
        log_ok, log_words = store.verify_log()
        entries = store.log_entries()
        rows = {row["id"]: row for row in store.read("SELECT * FROM requests")}
    finally:
        store.close()

    by_request: dict = {}
    for entry in entries:
        if entry["request_id"] is not None:
            by_request.setdefault(entry["request_id"], []).append(entry)

    found, wrong = [], [] if log_ok else [f"The log has been changed: {log_words}."]
    for entry in entries:
        if entry["event"] != "started" or entry["request_id"] is None:
            continue
        request_id, number = entry["request_id"], len(found) + 1
        earlier = [each for each in by_request[request_id] if each["seq"] < entry["seq"]]
        later = [each for each in by_request[request_id] if each["seq"] > entry["seq"]]
        yes = next((each for each in reversed(earlier) if each["event"] == "approved"), None)
        held = next((each for each in earlier if each["event"] == "held"), None)
        end = next((each for each in later if each["event"] in ENDS), None)
        row, problems, action = rows.get(request_id), [], None
        if row is None:
            problems.append("the file has no stored action for it")
        else:
            try:
                record = ActionRecord.from_canonical(row["record"])
                if record.fingerprint != entry["fingerprint"] or record.tool != entry["tool"]:
                    problems.append("the stored action is not the one the log says was started")
                else:
                    action = record.preview()
            except RecordError:
                problems.append("the stored action cannot be read")
            if row["state"] not in STARTED_STATES:
                problems.append(f"the file says the request is {row['state']}, and the log says it was started")
            elif end is None and row["state"] in ENDS:
                problems.append("the file says it ended, and the log has no end for it")
        if yes is None:
            problems.append("the log has no yes for it")
        elif yes["fingerprint"] != entry["fingerprint"]:
            problems.append("the yes in the log is for a different action")
        if sum(each["event"] == "started" for each in by_request[request_id]) > 1:
            problems.append("the log says it was started more than once")
        found.append(
            {
                "number": number,
                "request_id": request_id,
                "tool": entry["tool"],
                "fingerprint": entry["fingerprint"],
                "action": action,
                "yes_by": _detail(yes).get("by") if yes else None,
                "yes_at": yes["at"] if yes else None,
                "started_at": entry["at"],
                "outcome": end["event"] if end else None,
                "ended_at": end["at"] if end else None,
                "first_time": _detail(held).get("first_time") or [] if held else [],
                "problems": problems,
            }
        )
        wrong += [f"Receipt {number}: {problem}." for problem in problems]

    logged = {each["request_id"] for each in found}
    for request_id, row in rows.items():
        if row["state"] in STARTED_STATES and request_id not in logged:
            wrong.append(f"The file says a request ({request_id[:8]}) was started, and the log has no entry for it.")

    def count(event: str, with_request: bool = True) -> int:
        return sum(each["event"] == event and (each["request_id"] is not None) == with_request for each in entries)

    return {
        "file": str(path),
        "log_ok": log_ok,
        "log_words": log_words,
        "receipts": found,
        "wrong": wrong,
        "also": {
            "held": count("held"),
            "denied": count("denied"),
            "expired": count("expired"),
            "cancelled": count("cancelled"),
            "free": count("started", with_request=False),
        },
    }


def to_text(report: dict) -> str:
    lines = [f"Kettle receipts for {report['file']}", ""]
    lines.append(f"The log: {report['log_words']}." if report["log_ok"] else f"THE LOG HAS BEEN CHANGED: {report['log_words']}.")
    also = report["also"]
    lines.append(
        f"In it: held for a yes {also['held']}, denied {also['denied']}, expired {also['expired']}, "
        f"cancelled {also['cancelled']}, free actions started {also['free']} (their inputs are not stored)."
    )
    lines.append("")
    if not report["receipts"]:
        lines += ["No action that needs a yes has been started.", ""]
    for receipt in report["receipts"]:
        lines.append(f"Receipt {receipt['number']}: {receipt['tool']}")
        if receipt["yes_by"] is None and receipt["yes_at"] is None:
            lines.append("  Yes: NOT IN THE LOG")
        else:
            lines.append(f"  Yes: by {receipt['yes_by']}, {_when(receipt['yes_at'])}")
        lines.append(f"  Started: {_when(receipt['started_at'])}")
        if receipt["outcome"] == "ran":
            lines.append(f"  Outcome: ran, {_when(receipt['ended_at'])}")
        elif receipt["outcome"] == "unknown":
            lines.append(f"  Outcome: NOT KNOWN. It failed part way, {_when(receipt['ended_at'])}, and may or may not have acted")
        else:
            lines.append("  Outcome: NOT KNOWN. No end was recorded, and it may or may not have acted")
        if receipt["first_time"]:
            lines.append(f"  Marked first time when it was asked for: {', '.join(str(name) for name in receipt['first_time'])}")
        if receipt["action"] is None:
            lines.append(f"  Fingerprint: {receipt['fingerprint']}")
        else:
            lines += ["  " + line for line in receipt["action"].splitlines()]
        lines += [f"  DOES NOT ADD UP: {problem}" for problem in receipt["problems"]]
        lines.append("")
    if report["wrong"]:
        lines.append(f"{len(report['wrong'])} thing{'s' if len(report['wrong']) != 1 else ''} did not add up:")
        lines += ["  " + each for each in report["wrong"]]
    else:
        count = len(report["receipts"])
        lines.append(f"{count} receipt{'s' if count != 1 else ''}. Each action is the one its yes was for, and the log is whole.")
    lines.append("This cannot show entries cut from the end of the log, or a file rewritten by someone who can write it.")
    return "\n".join(lines)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m kettle.verify",
        description="Print a receipt for each action that ran after a yes: who said yes, when, and to exactly what. The file is only read.",
    )
    parser.add_argument("file", help="the file the Checkpoint was given, such as my-agent.db")
    args = parser.parse_args(argv)
    try:
        report = receipts(args.file)
    except StoreError as error:
        print(f"{args.file} cannot be read: {error}.", file=sys.stderr)
        return 2
    print(to_text(report))
    return 1 if report["wrong"] else 0


if __name__ == "__main__":
    sys.exit(main())
