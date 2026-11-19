"""The checkpoint: plain code that sits between an agent and its tools.

The agent side asks with request(). A free action runs. A risky one is held and
nothing happens until a human says yes to that exact action with approve(), and
run() then carries it out once. Anything unlisted, never allowed, expired, changed
or already used is refused, and if the checkpoint itself is not working it refuses
too, so the failure mode is "nothing ran".

What this code cannot do is stop an agent that has another way to reach the tools.
The functions passed to tool() must not be reachable by the model except through
request(). That is the builder's job; see the README.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .record import MIN_PREVIEW_WIDTH, PREVIEW_WIDTH, ActionRecord, RecordError
from .rules import FREE, NEEDS_YES, NEVER, Level, Refused, Rules, Tool
from .store import Store, StoreError
from .trail import Trail, TrailError

RAN = "ran"
HELD = "held"
APPROVED = "approved"
DENIED = "denied"
REFUSED = "refused"
UNKNOWN = "unknown"

_STATE_WORDS = {
    "held": "still waiting for a yes",
    "approved": "approved",
    "denied": "denied",
    "expired": "expired",
    "cancelled": "cancelled",
    "running": "already used",
    "ran": "already used",
    "unknown": "already used",
}


class CheckpointError(Exception):
    """The checkpoint could not be set up."""


@dataclass(frozen=True)
class Decision:
    """What the checkpoint did with one call.

    status is one of: ran, held, approved, denied, refused, unknown.
    "unknown" means a tool was started and then failed, so it may or may not have
    acted. It is never retried; someone has to check.

    first_time is set on a held action: the watched inputs whose value no approved
    action has run with before. The preview marks the same inputs.

    trail is set on a held action when the checkpoint was made with trail=True: for
    each watched value, where it was seen before. The preview says the same.
    """

    status: str
    reason: str
    tool: Optional[str] = None
    request_id: Optional[str] = None
    fingerprint: Optional[str] = None
    preview: Optional[str] = None
    expires_at: Optional[float] = None
    result: Any = None
    first_time: tuple = ()
    trail: tuple = ()


class Checkpoint:
    def __init__(
        self,
        path: str,
        *,
        hold_seconds: float = 600.0,
        clock: Callable[[], float] = time.time,
        trail: bool = False,
        preview_width: int = PREVIEW_WIDTH,
    ) -> None:
        """path is the SQLite file that holds requests and the log (":memory:" for a throwaway one).

        hold_seconds is how long a held request stays answerable. The yes and the
        run must both happen before that time is up.

        trail=True turns the source trail on: this object keeps, in memory, what
        every call returned, and a held action's preview says where each watched
        value was seen before. See owner_said() and known().

        preview_width is the longest line a preview may have, for a screen that
        shows fewer characters on a line than the usual 78, such as a phone. A
        line the screen has to wrap can start with text from inside a value.
        """
        if type(hold_seconds) not in (int, float) or not math.isfinite(hold_seconds) or hold_seconds <= 0:
            raise CheckpointError("hold_seconds must be a positive number")
        if type(trail) is not bool:
            raise CheckpointError("trail must be True or False")
        if type(preview_width) is not int or not MIN_PREVIEW_WIDTH <= preview_width <= PREVIEW_WIDTH:
            raise CheckpointError(f"preview_width must be a whole number from {MIN_PREVIEW_WIDTH} to {PREVIEW_WIDTH}")
        self._preview_width = preview_width
        self._trail = Trail() if trail else None
        self._hold_seconds = float(hold_seconds)
        self._clock = clock
        self._rules = Rules()
        self._worker = f"{os.getpid()}-{secrets.token_hex(4)}"
        try:
            self._store = Store(path)
        except StoreError as error:
            raise CheckpointError(str(error)) from None

    # ---- setup -------------------------------------------------------------

    def tool(
        self,
        name: str,
        run: Optional[Callable[..., Any]] = None,
        *,
        level: Level,
        describe: Optional[Callable[[dict], str]] = None,
        replace: bool = False,
        watch: Any = (),
    ) -> None:
        """List a tool. level is FREE, NEEDS_YES, NEVER, or a function of the inputs returning one of them.

        watch names inputs, such as ["to"], to mark in the preview when they hold a
        value that no approved action of this tool has run with before.
        """
        self._rules.add(name, run, level=level, describe=describe, replace=replace, watch=watch)

    def remove_tool(self, name: str) -> None:
        self._rules.remove(name)

    def tool_names(self) -> list[str]:
        return self._rules.names()

    def rules_digest(self) -> str:
        return self._rules.digest()

    # ---- the source trail ----------------------------------------------------

    def owner_said(self, text: str) -> None:
        """Tell the trail what the owner typed, word for word, so a value they gave can be traced to them.

        Only ever pass text that came from the owner. Text from the model, a tool
        or a page must never reach this: the preview would then say the owner
        typed something they did not.
        """
        try:
            self._the_trail().owner_said(text)
        except TrailError as error:
            raise CheckpointError(str(error)) from None

    def known(self, name: str, values: Any) -> None:
        """Give the trail a list your app trusts, such as the owner's contacts, under a name the preview can show.

        A value is "in the list" only if it equals an entry, character for
        character. Giving the same name again replaces the list.
        """
        try:
            self._the_trail().known(name, values)
        except TrailError as error:
            raise CheckpointError(str(error)) from None

    def clear_trail(self) -> None:
        """Forget what earlier calls returned and what the owner typed, for example when a new task starts. Lists stay."""
        self._the_trail().clear()

    def _the_trail(self) -> Trail:
        if self._trail is None:
            raise CheckpointError("the source trail is off: make the checkpoint with trail=True")
        return self._trail

    @property
    def gate(self) -> "Gate":
        """What an agent loop needs: a way to ask, and the list of tool names.

        It keeps approve and run out of the agent loop's hands by accident. It is not
        a wall: code running in the same process can still reach the checkpoint.
        """
        return Gate(self)

    def gate_for(self, actor: str) -> "Gate":
        """A gate whose requests are all recorded as asked through `actor`, for example "research agent".

        The name is fixed here by your code. The caller of the gate cannot change it.
        """
        if type(actor) is not str or not actor:
            raise CheckpointError("the actor must be non-empty text")
        return Gate(self, actor)

    # ---- the agent side ------------------------------------------------------

    def request(self, tool: str, inputs: dict, actor: Optional[str] = None) -> Decision:
        """Ask for an action. Runs it if free, holds it if it needs a yes, refuses it otherwise.

        actor is for your own code to say which part of the app is asking. It is shown
        to the human as "set by the app", so never fill it in from the model's output.
        """
        tool_name = tool if type(tool) is str else None
        if self._trail is not None:
            self._trail.asked(inputs)  # whatever comes of the call: a value the agent has used is no longer news from a later result
        try:
            found, record, level = self._decide(tool, inputs, actor)
        except (Refused, RecordError) as error:
            self._log_quietly("refused", tool=_clip(tool), detail={"reason": _clip(str(error), 500)})
            return Decision(REFUSED, f"Refused: {error}. Nothing was run.", tool=tool_name)
        except Exception as error:
            return self._broken(error, tool_name)

        # The clock is always read after the write lock is held. Waiting for the lock
        # can take seconds, and a time read before the wait would be out of date.
        try:
            if level == FREE:
                with self._store.write() as tx:
                    now = self._clock()
                    tx.log(now, "started", None, record.tool, record.fingerprint, {"level": FREE, "rules": self._rules.digest()})
            else:
                request_id = secrets.token_hex(16)
                summary = self._summary(found, record)
                with self._store.write() as tx:
                    now = self._clock()
                    expires_at = now + self._hold_seconds
                    first_time = _first_time(found, record, tx.seen)
                    trail = self._trail.trace(found.watch, record.inputs(), now) if self._trail is not None else []
                    preview = record.preview(summary, first_time, trail, self._preview_width)
                    tx.insert_request(request_id, record.fingerprint, record.canonical, now, expires_at)
                    detail = {"expires_at": expires_at, "rules": self._rules.digest()}
                    if found.watch:
                        detail["first_time"] = sorted(first_time)
                    if trail:
                        detail["trail"] = trail
                    tx.log(now, "held", request_id, record.tool, record.fingerprint, detail)
                return Decision(
                    HELD,
                    "Held: this action needs a human yes. Nothing was run.",
                    tool=record.tool,
                    request_id=request_id,
                    fingerprint=record.fingerprint,
                    preview=preview,
                    expires_at=expires_at,
                    first_time=tuple(sorted(first_time)),
                    trail=tuple(trail),
                )
        except Exception as error:
            return self._broken(error, tool_name)
        return self._execute(found, record, None)

    # ---- the human side ------------------------------------------------------

    def approve(self, request_id: str, fingerprint: str, approver: str = "owner") -> Decision:
        """Record a human yes for one held request.

        The yes must name the fingerprint the human was shown. It covers that one
        record, and only until the request expires. It does not run anything.
        """
        try:
            with self._store.write() as tx:
                now = self._clock()
                row = tx.get(request_id)
                if row is None:
                    return Decision(REFUSED, "Refused: there is no such request.")
                tool = _tool_of(row)
                if row["state"] != "held":
                    return Decision(REFUSED, f"Refused: that request is {_STATE_WORDS.get(row['state'], 'not open')}.", tool=tool, request_id=request_id)
                if now >= row["expires_at"]:
                    tx.move(request_id, ("held",), "expired", note="expired before a yes")
                    tx.log(now, "expired", request_id, tool, row["fingerprint"], {})
                    return Decision(REFUSED, "Refused: that request has expired.", tool=tool, request_id=request_id)
                try:
                    record = self._stored_record(row)
                    self._recheck(record)
                except (Refused, RecordError) as error:
                    tx.move(request_id, ("held",), "cancelled", note=str(error))
                    tx.log(now, "cancelled", request_id, tool, row["fingerprint"], {"reason": str(error)})
                    return Decision(REFUSED, f"Refused and cancelled: {error}.", tool=tool, request_id=request_id)
                if not _same(fingerprint, record.fingerprint):
                    tx.log(now, "refused", request_id, tool, row["fingerprint"], {"reason": "yes named a different fingerprint"})
                    return Decision(REFUSED, "Refused: that yes is for a different action.", tool=tool, request_id=request_id)
                moved = tx.move(
                    request_id, ("held",), "approved", decided_at=now, decided_by=_clip(approver), approved_fingerprint=record.fingerprint
                )
                if not moved:
                    return Decision(REFUSED, "Refused: that request is no longer open.", tool=tool, request_id=request_id)
                tx.log(now, "approved", request_id, tool, record.fingerprint, {"by": _clip(approver)})
                return Decision(
                    APPROVED,
                    "Approved. It has not run yet.",
                    tool=tool,
                    request_id=request_id,
                    fingerprint=record.fingerprint,
                    expires_at=row["expires_at"],
                )
        except Exception as error:
            return self._broken(error, None)

    def deny(self, request_id: str, approver: str = "owner") -> Decision:
        """Record a human no. Also withdraws a yes that has not been used yet."""
        try:
            with self._store.write() as tx:
                now = self._clock()
                row = tx.get(request_id)
                if row is None:
                    return Decision(REFUSED, "Refused: there is no such request.")
                tool = _tool_of(row)
                if not tx.move(request_id, ("held", "approved"), "denied", decided_at=now, decided_by=_clip(approver)):
                    return Decision(REFUSED, f"Refused: that request is {_STATE_WORDS.get(row['state'], 'not open')}.", tool=tool, request_id=request_id)
                tx.log(now, "denied", request_id, tool, row["fingerprint"], {"by": _clip(approver)})
                return Decision(DENIED, "Denied. Nothing was run.", tool=tool, request_id=request_id)
        except Exception as error:
            return self._broken(error, None)

    def run(self, request_id: str) -> Decision:
        """Carry out an approved request, once.

        Everything is checked again here, at the last moment: the yes exists, has
        not been used, has not expired, the stored record is still the one that
        was approved, and the rules still allow it.
        """
        try:
            with self._store.write() as tx:
                now = self._clock()
                row = tx.get(request_id)
                if row is None:
                    return Decision(REFUSED, "Refused: there is no such request. Nothing was run.")
                tool = _tool_of(row)
                if row["state"] == "held":
                    tx.log(now, "refused", request_id, tool, row["fingerprint"], {"reason": "asked to run before anyone said yes"})
                    return Decision(REFUSED, "Refused: no one has said yes to that request. Nothing was run.", tool=tool, request_id=request_id)
                if row["state"] != "approved":
                    words = _STATE_WORDS.get(row["state"], "not open")
                    tx.log(now, "refused", request_id, tool, row["fingerprint"], {"reason": f"asked to run a request that is {words}"})
                    return Decision(REFUSED, f"Refused: that request is {words}. Nothing was run.", tool=tool, request_id=request_id)
                if now >= row["expires_at"]:
                    tx.move(request_id, ("approved",), "expired", note="expired before it was run")
                    tx.log(now, "expired", request_id, tool, row["fingerprint"], {})
                    return Decision(REFUSED, "Refused: that yes has expired. Nothing was run.", tool=tool, request_id=request_id)
                try:
                    record = self._stored_record(row)
                    if not _same(row["approved_fingerprint"], record.fingerprint):
                        raise Refused("the yes was given for a different action")
                    found = self._recheck(record)
                except (Refused, RecordError) as error:
                    tx.move(request_id, ("approved",), "cancelled", note=str(error))
                    tx.log(now, "cancelled", request_id, tool, row["fingerprint"], {"reason": str(error)})
                    return Decision(REFUSED, f"Refused and cancelled: {error}. Nothing was run.", tool=tool, request_id=request_id)
                if not tx.move(request_id, ("approved",), "running", started_at=now, worker=self._worker):
                    return Decision(REFUSED, "Refused: that yes was already used. Nothing was run.", tool=tool, request_id=request_id)
                for mark in _marks(record):  # from now on these values are not new for this tool
                    tx.mark_seen(mark, now)
                tx.log(now, "started", request_id, record.tool, record.fingerprint, {"level": NEEDS_YES, "rules": self._rules.digest()})
        except Exception as error:
            return self._broken(error, None)
        return self._execute(found, record, request_id)

    # ---- looking -------------------------------------------------------------

    def pending(self) -> list[dict]:
        """Held requests that can still be answered, with the preview a human should see."""
        now = self._clock()
        waiting = []
        for row in self._store.read("SELECT * FROM requests WHERE state = 'held' AND expires_at > ? ORDER BY created_at", (now,)):
            try:
                record = self._stored_record(row)
                found = self._rules.find(record.tool)
            except (Refused, RecordError):
                continue
            first_time = _first_time(found, record, self._store.seen)
            summary = self._summary(found, record)
            trail = self._held_trail(row["id"])
            try:
                preview = record.preview(summary, first_time, trail, self._preview_width)
            except RecordError:  # the stored trail was edited by hand; verify_log() reports it
                trail, preview = [], record.preview(summary, first_time, width=self._preview_width)
            waiting.append(
                {
                    "request_id": row["id"],
                    "tool": record.tool,
                    "fingerprint": record.fingerprint,
                    "preview": preview,
                    "expires_at": row["expires_at"],
                    "first_time": sorted(first_time),
                    "watched": sorted(key for key in found.watch if key in record.inputs()),  # every watched input it has, new or not
                    "trail": trail,
                }
            )
        return waiting

    def _held_trail(self, request_id: str) -> list:
        """The trail the log holds for a held request: what was worked out when it was asked.

        It is read from the log, not worked out again, so another process sharing
        the file shows the human the same thing.
        """
        rows = self._store.read("SELECT detail FROM log WHERE request_id = ? AND event = 'held' ORDER BY seq LIMIT 1", (request_id,))
        try:
            trail = json.loads(rows[0]["detail"]).get("trail", []) if rows else []
        except (ValueError, TypeError, AttributeError):
            return []
        return trail if type(trail) is list else []

    def status(self, request_id: str) -> Optional[dict]:
        rows = self._store.read("SELECT * FROM requests WHERE id = ?", (request_id,)) if type(request_id) is str else []
        if not rows:
            return None
        row = rows[0]
        state = row["state"]
        if state in ("held", "approved") and self._clock() >= row["expires_at"]:
            state = "expired"
        return {
            "request_id": row["id"],
            "state": state,
            "tool": _tool_of(row),
            "fingerprint": row["fingerprint"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "note": row["note"],
        }

    def needs_checking(self, older_than: float = 60.0) -> list[dict]:
        """Approved actions that were started and whose outcome is not known.

        Either the tool failed part-way, or the process stopped while it ran
        (still "running" after older_than seconds). They are never run again.

        Free actions are not listed here, because they have no request to list.
        A free tool that failed is in the log as "unknown". One whose process
        stopped part-way is in the log as "started" with nothing after it.
        """
        cutoff = self._clock() - older_than
        rows = self._store.read(
            "SELECT id FROM requests WHERE state = 'unknown' OR (state = 'running' AND started_at <= ?) ORDER BY started_at",
            (cutoff,),
        )
        return [self.status(row["id"]) for row in rows]

    def log(self) -> list[dict]:
        return self._store.log_entries()

    def verify_log(self) -> tuple[bool, str]:
        return self._store.verify_log()

    def close(self) -> None:
        self._store.close()

    # ---- inside --------------------------------------------------------------

    def _decide(self, tool: Any, inputs: Any, actor: Any) -> tuple[Tool, ActionRecord, str]:
        found = self._rules.find(tool)
        record = ActionRecord.make(tool, inputs, actor)
        level = self._rules.level_for(found, record.inputs())
        if level == NEVER:
            raise _never(found, record)
        self._rules.check_fits(found, record.inputs())
        return found, record, level

    def _recheck(self, record: ActionRecord) -> Tool:
        found = self._rules.find(record.tool)
        if self._rules.level_for(found, record.inputs()) == NEVER:
            raise _never(found, record)
        self._rules.check_fits(found, record.inputs())
        return found

    def _stored_record(self, row: Any) -> ActionRecord:
        record = ActionRecord.from_canonical(row["record"])
        if not _same(row["fingerprint"], record.fingerprint):
            raise Refused("the stored request was changed after it was made")
        return record

    def _summary(self, found: Tool, record: ActionRecord) -> Optional[str]:
        if found.describe is None:
            return None
        try:
            text = found.describe(record.inputs())
        except Exception:
            return None
        if type(text) is not str or not text:
            return None
        return text if len(text) <= 500 else text[:500] + " [summary cut at 500 characters]"

    def _execute(self, found: Tool, record: ActionRecord, request_id: Optional[str]) -> Decision:
        """Run the tool. From here on the answer is never "nothing was run"."""
        try:
            result = found.run(**record.inputs())
        except BaseException as error:
            self._finish(request_id, record, "unknown", _error_note(error))
            if not isinstance(error, Exception):
                raise
            return Decision(
                UNKNOWN,
                f"{record.tool} was started and failed ({type(error).__name__}). It may or may not have acted. "
                "It will not be retried; it needs checking.",
                tool=record.tool,
                request_id=request_id,
                fingerprint=record.fingerprint,
            )
        if self._trail is not None:
            self._remember(record, result)
        recorded = self._finish(request_id, record, "ran", None)
        reason = "Ran." if recorded else "Ran, but the checkpoint could not record it. It needs checking."
        return Decision(RAN, reason, tool=record.tool, request_id=request_id, fingerprint=record.fingerprint, result=result)

    def _remember(self, record: ActionRecord, result: Any) -> None:
        """Hand what a call returned to the trail. The call has happened, so nothing here may fail it."""
        try:
            self._trail.saw_result(record.tool, record.inputs(), result, self._clock())
        except Exception:
            self._trail.missed_one()

    def _finish(self, request_id: Optional[str], record: ActionRecord, state: str, note: Optional[str]) -> bool:
        try:
            with self._store.write() as tx:
                now = self._clock()
                if request_id is not None:
                    tx.move(request_id, ("running",), state, finished_at=now, note=note)
                tx.log(now, state, request_id, record.tool, record.fingerprint, {"note": note} if note else {})
            return True
        except Exception:
            return False

    def _log_quietly(self, event: str, tool: Optional[str], detail: dict) -> None:
        try:
            with self._store.write() as tx:
                tx.log(self._clock(), event, None, tool, None, detail)
        except Exception:
            pass

    def _broken(self, error: Exception, tool: Optional[str]) -> Decision:
        if not isinstance(error, StoreError):  # if the store itself is down there is nowhere to write this
            self._log_quietly("refused", tool=_clip(tool) if tool is not None else None, detail={"reason": f"the checkpoint is not working ({type(error).__name__})"})
        return Decision(
            REFUSED,
            f"Refused: the checkpoint is not working ({type(error).__name__}), so nothing was run.",
            tool=tool,
        )


class Gate:
    """What an agent loop is given: a way to ask, and the list of tool names."""

    __slots__ = ("_request", "_names", "_actor")

    def __init__(self, checkpoint: Checkpoint, actor: Optional[str] = None) -> None:
        self._request = checkpoint.request
        self._names = checkpoint.tool_names
        self._actor = actor

    def request(self, tool: str, inputs: dict) -> Decision:
        return self._request(tool, inputs, self._actor)

    def tool_names(self) -> list[str]:
        return self._names()


def _mark(tool: str, key: str, value: Any) -> str:
    """What the store keeps for "this tool has run with this value in this input". A hash, not the value."""
    text = json.dumps([tool, key, value], sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(b"kettle-seen-v1\n" + text.encode("ascii")).hexdigest()


def _marks(record: ActionRecord) -> list[str]:
    """A mark for every input of the record. A list is marked item by item."""
    marks = []
    for key, value in record.inputs().items():
        marks += [_mark(record.tool, key, item) for item in (value if type(value) is list else [value])]
    return marks


def _never(found: Tool, record: ActionRecord) -> Refused:
    """Why a call at the never level is refused. A tool whose level depends on its inputs is allowed with others, so it is not called never allowed."""
    if callable(found.level):
        return Refused(f"{record.tool} is not allowed with these inputs")
    return Refused(f"{record.tool} is never allowed")


def _first_time(found: Tool, record: ActionRecord, seen: Callable[[str], bool]) -> dict:
    """The watched inputs holding a value that is new: None for the whole value, or the new items of a list from 1.

    The match is exact. "Sam@example.com" is new even if "sam@example.com" is not.
    """
    new: dict = {}
    if not found.watch:
        return new
    inputs = record.inputs()
    for key in found.watch:
        if key not in inputs:
            continue
        value = inputs[key]
        if type(value) is list:
            items = [number for number, item in enumerate(value, 1) if not seen(_mark(record.tool, key, item))]
            if items:
                new[key] = items
        elif not seen(_mark(record.tool, key, value)):
            new[key] = None
    return new


def _same(left: Any, right: Any) -> bool:
    if type(left) is not str or type(right) is not str:
        return False
    return hmac.compare_digest(left.encode("utf-8", "replace"), right.encode("utf-8", "replace"))


def _clip(value: Any, limit: int = 200) -> str:
    """Short text that can always be stored. Never calls code on the value it is given."""
    text = value if type(value) is str else f"<{type(value).__name__}>"
    text = text if len(text) <= limit else text[:limit] + "..."
    return text.encode("utf-8", "backslashreplace").decode("utf-8")


def _error_note(error: BaseException) -> str:
    try:
        text = f"{type(error).__name__}: {error}"
    except Exception:  # an error whose own message cannot be written
        text = type(error).__name__
    return _clip(text, 500)


def _tool_of(row: Any) -> Optional[str]:
    try:
        return ActionRecord.from_canonical(row["record"]).tool
    except RecordError:
        return None
