"""Say yes from your phone: a held action is sent to you on Telegram with an Approve and a Deny button.

    from kettle.adapters import through
    from kettle.telegram import TelegramApprover

    approver = TelegramApprover(checkpoint, token=os.environ["KETTLE_TELEGRAM_TOKEN"], chat_id=123456789)
    approver.start()
    call = through(checkpoint.gate, approver.on_held)

It needs no other package. It talks to the Telegram Bot API over HTTPS, so what
it sends (the preview of each held action) leaves your machine and passes through
Telegram.

What counts as a yes, and what does not:

  - Only a press of the Approve button counts. Typed text is never an answer.
  - Only a press by the owner, in the owner's private chat with the bot, counts.
    chat_id is that chat. A group is refused at setup: anyone in it could press.
  - The press must come from the very message this object sent for that action.
    A button carries a random code that is kept in memory here, not the request's
    id, so a button made by anyone else names nothing.
  - The yes is given to the checkpoint with the fingerprint that was on the
    screen. If the stored action is no longer that one, the checkpoint refuses.
  - A press sooner than min_read_seconds after the buttons appeared is not
    counted, so a tap that was meant for something else does not approve.
  - An action too long to read on a phone is sent with a Deny button only.
  - With trust and on_trust, an action can also get an "Approve and trust" button.
    It is a yes in the same way as Approve, with the same checks. Only once the
    checkpoint has taken the yes is on_trust handed the stored values of the inputs
    it was offered for, so the app can add them to its own list. A plain Approve
    never trusts anything, and Kettle itself never changes a list.
  - With on_message, the owner's own typed messages in that chat are handed to
    the app, so one bot can carry the app's chat and the buttons. A typed message
    is still never an answer: on_message only gets the text.
  - At most at_once actions are on the phone at a time. The rest wait.
  - If Telegram cannot be reached, or answers with an error, nothing is approved.

Everything else is still the checkpoint's job: a yes covers one exact action,
once, until it expires. This object only carries the question and the answer.

The token is the key to your bot. It is never put in an error, in repr() or in
anything this module prints. Give the bot no other job: two programs cannot
listen on one bot.

This is not a wall against code that runs in the same process: such code can
reach the checkpoint itself. See the README.

To find your chat_id, with the token in KETTLE_TELEGRAM_TOKEN:

    python -m kettle.telegram

It shows a code, waits for you to send that code to your bot, and prints the
number of the chat it came from.
"""

from __future__ import annotations

import hmac
import json
import queue
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

from .adapters import SAID_NO
from .checkpoint import APPROVED, DENIED, RAN, Decision

API = "https://api.telegram.org"
MESSAGE_LIMIT = 4096  # characters Telegram takes in one message
PART_CHARS = 3600  # of a preview in one message; the rest of the room is for the words around it
MAX_PARTS = 5  # a preview that needs more messages than this cannot be approved on the phone
TOKEN_REMOVED = "[token removed]"
REPORT_AGAIN_SECONDS = 300.0  # a fault that goes on is reported again this often

FIRST_LINE = "Approval needed"
HOW_TO = "Approve runs exactly what is in the box, once. Deny runs nothing."
HOW_TO_PARTS = "Approve runs exactly what is in the boxes of all the parts, once. Deny runs nothing."
FIRST_TIME = "\U0001f195 First time: "  # the NEW sign
APPROVE, DENY = "\u2705 Approve", "\u274c Deny"  # a tick and a cross
TRUST = "\u2705 Approve and trust"
HOW_TO_TRUST = "Approve and trust also adds {what} to the app's list."
TRUSTED = "Approved, and {what} added to the app's list. It runs once, exactly as shown."
NOT_TRUSTED = "Approved. It runs once, exactly as shown. Nothing was added to the app's list: the app could not take it."
SENT_NOTE = "kettle.telegram: {tool} is with Telegram, on its way to your phone (fingerprint {start}...). Waiting for your answer."
NAMES_SHOWN = 3  # first-time inputs named above the box; more than this are counted
NOT_YOURS = "Only the owner can answer this."
NOT_OPEN = "That request is no longer open."
TOO_SOON = "Too soon. Read it, then press again."
NOT_HERE = "This action is too long to approve on a phone."
NO_ANSWER = "This action needs the owner's yes. No answer came in time. Nothing was run."

TOKEN_NAME = "KETTLE_TELEGRAM_TOKEN"
CODE_DIGITS = 6  # in the code that shows which chat is yours
WRONG_CODES = 5  # wrong codes taken before the search stops
OLD_ROUNDS = 50  # calls made to pass over what was sent before the code was shown
FOUND_NOTE = "Kettle found this chat. Held actions are sent here once your agent is given this chat's number."
USAGE = "usage: python -m kettle.telegram    (it takes no arguments; the token is read from KETTLE_TELEGRAM_TOKEN)"
NO_TOKEN = """KETTLE_TELEGRAM_TOKEN is not set. Give the token to this terminal without showing it or saving it:

    read -s KETTLE_TELEGRAM_TOKEN && export KETTLE_TELEGRAM_TOKEN

Paste the token, press Enter, and run this again."""


class TelegramError(Exception):
    """Telegram could not be set up or reached. The message never holds the token."""


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **more: Any) -> None:
        return None  # a redirect is an error: the token goes to the address given and nowhere else


class _Shown:
    """One held action as it stands on the phone."""

    __slots__ = ("request_id", "fingerprint", "tool", "nonce", "parts", "can_approve", "trust", "sent", "buttons_message", "shown_at", "answered")

    def __init__(self, request_id: str, fingerprint: str, tool: str, parts: list, can_approve: bool, trust: tuple = ()) -> None:
        self.request_id, self.fingerprint, self.tool = request_id, fingerprint, tool
        self.trust = trust  # the inputs "Approve and trust" was offered for; none: no such button
        self.nonce = secrets.token_urlsafe(24)
        self.parts = parts  # (text, entities) of each message to send
        self.can_approve = can_approve
        self.sent = 0  # how many of the parts have gone out
        self.buttons_message: Optional[int] = None  # the message the buttons are on, once it is out
        self.shown_at = 0.0
        self.answered = False  # a press has been counted, and the checkpoint is being told


class TelegramApprover:
    def __init__(
        self,
        checkpoint: Any,
        *,
        token: str,
        chat_id: int,
        api: str = API,
        approver: str = "owner, on Telegram",
        at_once: int = 3,
        min_read_seconds: float = 2.0,
        max_parts: int = MAX_PARTS,
        poll_seconds: float = 0.5,
        long_poll_seconds: int = 25,
        retry_seconds: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        problem: Optional[Callable[[str], Any]] = None,
        sent: Optional[Callable[[str], Any]] = None,
        trust: Optional[Callable[[dict], Any]] = None,
        on_trust: Optional[Callable[[str, dict], Any]] = None,
        on_message: Optional[Callable[[str], Any]] = None,
    ) -> None:
        """checkpoint is the Checkpoint whose held actions are sent. Keep this object on the owner's side of your app.

        token is the bot's token and chat_id is the number of your own private chat
        with the bot. approver is the name the log keeps for a yes given here.

        problem is called with a short line when Telegram cannot be reached. With
        none, the line is printed to stderr. It never holds the token.

        sent is called with a short line each time Telegram has taken a held action,
        buttons and all. With none, nothing is said. The line names the tool and the
        start of the fingerprint, never a value. Telegram having it does not mean
        the phone shows it yet.

        trust and on_trust come together, or not at all. trust is called with each
        held action as pending() gives it, and returns the names of the inputs to
        offer "Approve and trust" for: watched inputs only, and none for no such
        button. on_trust(request_id, values) is called after that button's yes has
        been taken by the checkpoint, with the stored value of each of those inputs,
        so the app can add them to its own list. Keep both on the owner's side.

        on_message(text) is called with each text message the owner types in their
        private chat with the bot, in order, one at a time, on a thread of its own.
        Messages from anyone else, from anywhere else, or sent before start() are
        passed over, and so is anything sent in the same second as start(), since
        Telegram dates a message only to the second. It never answers a held action. With it, give the bot no other
        job, as always: this object is then the only thing that listens to it.
        """
        if type(token) is not str or not re.fullmatch(r"[0-9]{1,20}:[A-Za-z0-9_-]{1,120}", token):
            raise TelegramError("that is not the shape of a bot token (the value given is not shown)")
        if type(chat_id) is not int or chat_id <= 0:
            raise TelegramError("chat_id must be the number of your own private chat with the bot; a group or channel is refused")
        if type(approver) is not str or not approver:
            raise TelegramError("approver must be non-empty text")
        if type(at_once) is not int or at_once < 1:
            raise TelegramError("at_once must be a whole number, 1 or more")
        if type(min_read_seconds) not in (int, float) or min_read_seconds < 0:
            raise TelegramError("min_read_seconds must be a number, 0 or more")
        if type(max_parts) is not int or max_parts < 1:
            raise TelegramError("max_parts must be a whole number, 1 or more")
        if (trust is None) != (on_trust is None) or not all(found is None or callable(found) for found in (trust, on_trust)):
            raise TelegramError("trust and on_trust come together: two functions, or neither")
        if on_message is not None and not callable(on_message):
            raise TelegramError("on_message must be a function")
        self._api = _checked_api(api)
        self._token = token
        self._chat_id = chat_id
        self._checkpoint = checkpoint
        self._approver = approver
        self._at_once = at_once
        self._min_read = float(min_read_seconds)
        self._max_parts = max_parts
        self._poll, self._long_poll, self._retry = float(poll_seconds), int(long_poll_seconds), float(retry_seconds)
        self._clock = clock
        self._problem = problem
        self._sent = sent
        self._trust, self._on_trust = trust, on_trust
        self._on_message = on_message
        self._messages: "queue.Queue[Optional[str]]" = queue.Queue()
        self._since = 0  # the time start() was called, by the clock Telegram dates messages with
        self._drained = True
        handlers: list = [_NoRedirects]
        if self._api.startswith("http://"):  # this machine: never by way of a proxy
            handlers.append(urllib.request.ProxyHandler({}))
        self._opener = urllib.request.build_opener(*handlers)
        self._lock = threading.Lock()
        self._shown: dict[str, _Shown] = {}  # by request id: what is on the phone, or on its way
        self._nonces: dict[str, _Shown] = {}
        self._offset = 0
        self._stop: Optional[threading.Event] = None
        self._threads: list = []
        self._reported: dict[str, float] = {}
        self.last_error: Optional[str] = None  # the last fault, in words; it never holds the token

    def __repr__(self) -> str:
        return f"TelegramApprover(chat {self._chat_id}, {'running' if self._stop is not None else 'stopped'})"

    # ---- starting and stopping ---------------------------------------------------

    def start(self) -> None:
        """Start sending held actions and listening for answers, on two background threads."""
        with self._lock:
            if self._stop is not None:
                return
            self._stop = stop = threading.Event()
            self._since = int(time.time())  # Telegram dates a message in whole seconds of wall-clock time
            self._messages = queue.Queue()  # nothing left over from an earlier start
            self._drained = self._on_message is None  # with on_message, what waits at Telegram is cleared first
            self._threads = [
                threading.Thread(target=self._loop, args=(self._send_step, self._poll, stop), daemon=True, name="kettle-telegram-send"),
                threading.Thread(target=self._loop, args=(self._listen_step, 0.05, stop), daemon=True, name="kettle-telegram-listen"),
            ]
            if self._on_message is not None:
                self._threads.append(threading.Thread(target=self._hand_on, args=(stop,), daemon=True, name="kettle-telegram-messages"))
        for thread in self._threads:
            thread.start()

    def stop(self, wait_seconds: float = 2.0) -> None:
        """Stop. Buttons already on the phone stay there and no longer answer anything."""
        with self._lock:
            stop, threads = self._stop, self._threads
            self._stop, self._threads = None, []
            self._shown.clear()
            self._nonces.clear()
        if stop is not None:
            stop.set()
            self._messages.put(None)  # wakes the thread that hands messages on
            for thread in threads:
                thread.join(wait_seconds)

    # ---- for the agent loop -------------------------------------------------------

    def wait(self, request_id: str, timeout: Optional[float] = None) -> str:
        """Wait until the request is answered or has expired. Returns its state, or "held" if the time ran out first."""
        end = None if timeout is None else time.monotonic() + timeout
        while True:
            found = self._checkpoint.status(request_id)
            state = found["state"] if found else "unknown"
            if state != "held" or (end is not None and time.monotonic() >= end):
                return state
            time.sleep(0.05 if end is None else max(0.0, min(0.05, end - time.monotonic())))

    def on_held(self, decision: Decision) -> str:
        """An on_held for through(): wait for the owner's answer on the phone, and run the action if it is a yes."""
        self.start()
        state = self.wait(decision.request_id)
        if state == APPROVED:
            done = self._checkpoint.run(decision.request_id)
            return (done.result if type(done.result) is str else str(done.result)) if done.status == RAN else done.reason
        return SAID_NO if state == DENIED else NO_ANSWER

    # ---- the two loops ------------------------------------------------------------

    def _loop(self, step: Callable[[], None], pause: float, stop: threading.Event) -> None:
        retry = self._retry
        while not stop.is_set():
            try:
                step()
                wait, retry = pause, self._retry
            except Exception as error:  # nothing is approved while this lasts, and the loop carries on
                self._note(error if isinstance(error, TelegramError) else TelegramError(f"the Telegram approver hit a fault ({type(error).__name__})"))
                wait, retry = retry, min(retry * 2, 30.0)
            stop.wait(wait)

    def _note(self, error: Exception) -> None:
        text = self._clean(str(error))
        now = time.monotonic()
        with self._lock:
            self.last_error = text
            new = now - self._reported.get(text, -REPORT_AGAIN_SECONDS) >= REPORT_AGAIN_SECONDS
            if new:
                if len(self._reported) >= 50:
                    self._reported.clear()
                self._reported[text] = now
        if new:  # the same fault is reported once, not on every try
            line = f"kettle.telegram: {text}. Nothing is approved while this lasts."
            try:
                self._problem(line) if self._problem is not None else print(line, file=sys.stderr)
            except Exception:
                pass

    def _send_step(self) -> None:
        waiting = self._checkpoint.pending()
        open_ids = {item["request_id"] for item in waiting}
        with self._lock:
            gone = [shown for shown in self._shown.values() if shown.request_id not in open_ids and not shown.answered]
            for shown in gone:
                self._forget(shown)
            new = [item for item in waiting if item["request_id"] not in self._shown]
            room = self._at_once - len(self._shown)
            for index, item in enumerate(new[: max(room, 0)]):
                offered = self._offered(item)
                parts, can_approve = _parts(item["preview"], len(new) - index - 1, self._max_parts, item["tool"], item.get("first_time"), offered)
                shown = _Shown(item["request_id"], item["fingerprint"], item["tool"], parts, can_approve, offered if can_approve else ())
                self._shown[shown.request_id] = self._nonces[shown.nonce] = shown
            to_send = [shown for shown in self._shown.values() if shown.buttons_message is None]
        for shown in gone:  # answered somewhere else, or expired
            found = self._checkpoint.status(shown.request_id)
            self._take_buttons_off(shown, f"No longer open ({found['state'] if found else 'gone'}). Nothing more can be done with it here.")
        for shown in to_send:
            self._deliver(shown)

    def _offered(self, item: dict) -> tuple:
        """The inputs to offer "Approve and trust" for: the app's choice, kept to watched inputs. A broken choice offers none."""
        if self._trust is None:
            return ()
        try:
            names = list(self._trust(dict(item)) or ())
        except Exception:
            self._report("trust", "kettle.telegram: the app's trust function failed, so no Approve and trust button was offered.")
            return ()
        watched = item.get("watched") if type(item.get("watched")) in (list, tuple) else []
        return tuple(sorted({name for name in names if type(name) is str and name in watched}))

    def _report(self, key: str, line: str) -> None:
        try:
            (self._problem or (lambda text: print(text, file=sys.stderr)))(line)
        except Exception:
            pass

    def _deliver(self, shown: _Shown) -> None:
        """Send the parts that have not gone out yet. The buttons go on the last one, after all the rest."""
        while shown.sent < len(shown.parts):
            text, entities = shown.parts[shown.sent]
            body: dict = {"chat_id": self._chat_id, "text": text, "entities": entities, "link_preview_options": {"is_disabled": True}}
            last = shown.sent == len(shown.parts) - 1
            if last:
                keys = [{"text": APPROVE, "callback_data": "a:" + shown.nonce}] if shown.can_approve else []
                rows = [keys + [{"text": DENY, "callback_data": "d:" + shown.nonce}]]
                if shown.trust:  # a row of its own, so it is not pressed for Approve by mistake
                    rows.append([{"text": TRUST, "callback_data": "t:" + shown.nonce}])
                body["reply_markup"] = {"inline_keyboard": rows}
            sent = self._call("sendMessage", body)
            message_id = sent.get("message_id") if type(sent) is dict else None
            if type(message_id) is not int:
                raise TelegramError("Telegram did not say which message it sent")
            with self._lock:
                shown.sent += 1
                if last:
                    shown.buttons_message, shown.shown_at = message_id, self._clock()
            if last:
                self._say_sent(shown)

    def _say_sent(self, shown: _Shown) -> None:
        """Tell the owner's side that Telegram has the question. Whether the phone shows it is not known here."""
        if self._sent is None:
            return
        try:
            self._sent(SENT_NOTE.format(tool=shown.tool if _plain(shown.tool) else "an action", start=shown.fingerprint[:12]))
        except Exception:  # a broken reporter does not stop the approver
            pass

    def _listen_step(self) -> None:
        if not self._drained:
            # Whatever was waiting at Telegram when this started is passed over, whatever its date says:
            # a clock a little behind Telegram's could make an old message look new.
            # A button press in it is dealt with as usual: old buttons answer nothing, and a new one counts.
            backlog = self._call("getUpdates", {"offset": self._offset, "timeout": 0, "allowed_updates": ["callback_query", "message"]})
            for update in backlog if type(backlog) is list else []:
                number = update.get("update_id") if type(update) is dict else None
                if type(number) is not int:
                    continue
                self._offset = max(self._offset, number + 1)
                if type(update.get("callback_query")) is dict:
                    self._on_update(update)
            self._drained = not backlog  # Telegram hands over at most 100 at a time: clear until nothing is left
            return
        kinds = ["callback_query", "message"] if self._on_message is not None else ["callback_query"]
        updates = self._call("getUpdates", {"offset": self._offset, "timeout": self._long_poll, "allowed_updates": kinds}, self._long_poll + 10)
        for update in updates if type(updates) is list else []:
            number = update.get("update_id") if type(update) is dict else None
            if type(number) is not int:
                continue
            self._offset = max(self._offset, number + 1)  # first, so one update that cannot be handled is not handed over for ever
            self._on_update(update)

    def _on_update(self, update: dict) -> None:
        query = update.get("callback_query")
        if type(query) is not dict:
            self._typed(update.get("message"))
            return  # typed text, and everything else that is not a button press, is not an answer
        query_id, data = query.get("id"), query.get("data")
        sender = query.get("from") if type(query.get("from")) is dict else {}
        message = query.get("message") if type(query.get("message")) is dict else {}
        chat = message.get("chat") if type(message.get("chat")) is dict else {}
        ids = (sender.get("id"), chat.get("id"))
        if any(type(found) is not int or found != self._chat_id for found in ids) or chat.get("type") != "private":
            return self._answer(query_id, NOT_YOURS)
        kind, _, nonce = data.partition(":") if type(data) is str else ("", "", "")
        with self._lock:
            shown = self._nonces.get(nonce) if kind in ("a", "d", "t") else None
            if shown is not None and shown.buttons_message is None:
                return_text = TOO_SOON  # the buttons are out, and this object has not been told so yet
            elif shown is None or message.get("message_id") != shown.buttons_message:
                return_text = NOT_OPEN
            elif kind == "t" and not shown.trust:
                return_text = NOT_OPEN  # no such button was sent for this action
            elif kind in ("a", "t") and not shown.can_approve:
                return_text = NOT_HERE
            elif kind in ("a", "t") and self._clock() - shown.shown_at < self._min_read:
                return_text = TOO_SOON
            else:
                return_text = None
                shown.answered = True
                self._nonces.pop(shown.nonce, None)  # from here on its buttons answer nothing, whatever the checkpoint says
        if return_text is not None:
            return self._answer(query_id, return_text, alert=True)
        try:
            if kind in ("a", "t"):
                decision = self._checkpoint.approve(shown.request_id, shown.fingerprint, self._approver)
                text = "Approved. It runs once, exactly as shown." if decision.status == APPROVED else decision.reason
                if kind == "t" and decision.status == APPROVED:  # only a yes the checkpoint took is passed on
                    text = self._keep(shown)
            else:
                decision = self._checkpoint.deny(shown.request_id, self._approver)
                text = "Denied. Nothing was run." if decision.status == DENIED else decision.reason
        finally:
            with self._lock:
                self._forget(shown)
        self._answer(query_id, text)
        self._take_buttons_off(shown, text)

    # ---- inside -------------------------------------------------------------------

    def _typed(self, message: Any) -> None:
        """Queue the owner's own typed text for on_message. Anything else is passed over."""
        if self._on_message is None or type(message) is not dict:
            return
        sender = message.get("from") if type(message.get("from")) is dict else {}
        chat = message.get("chat") if type(message.get("chat")) is dict else {}
        if sender.get("id") != self._chat_id or type(sender.get("id")) is not int or chat.get("id") != self._chat_id or chat.get("type") != "private":
            return
        if type(message.get("date")) is not int or message["date"] <= self._since:
            return  # Telegram dates in whole seconds: anything from the second it started in may be older, so it is passed over
        if type(message.get("text")) is str and message["text"]:
            self._messages.put(message["text"])

    def _hand_on(self, stop: threading.Event) -> None:
        """Give the app each typed message in turn. A slow or broken on_message never holds up a button press."""
        while not stop.is_set():
            text = self._messages.get()
            if text is None or stop.is_set():
                return
            try:
                self._on_message(text)
            except Exception:
                self._report("message", "kettle.telegram: the app's on_message failed on a message. The next one is still handed on.")

    def _keep(self, shown: _Shown) -> str:
        """Hand the app the stored values of the inputs it offered trust for. The action is approved whatever comes of this."""
        try:
            stored = self._checkpoint.inputs(shown.request_id)
            if type(stored) is not dict or any(name not in stored for name in shown.trust):
                raise LookupError("the stored inputs are not there")
            self._on_trust(shown.request_id, {name: stored[name] for name in shown.trust})
        except Exception:
            self._report("trust", "kettle.telegram: the app could not take what was trusted. The action is approved; nothing was added.")
            return NOT_TRUSTED
        return TRUSTED.format(what=_what(shown.trust))

    def _forget(self, shown: _Shown) -> None:
        if self._shown.get(shown.request_id) is shown:
            del self._shown[shown.request_id]
        self._nonces.pop(shown.nonce, None)

    def _answer(self, query_id: Any, text: str, alert: bool = False) -> None:
        """Tell the person who pressed what came of it. The decision is already made; this only reports it."""
        if type(query_id) is not str:
            return
        try:
            self._call("answerCallbackQuery", {"callback_query_id": query_id, "text": text[:190], "show_alert": alert})
        except TelegramError as error:
            self._note(error)

    def _take_buttons_off(self, shown: _Shown, text: str) -> None:
        try:
            if shown.buttons_message is not None:
                self._call("editMessageReplyMarkup", {"chat_id": self._chat_id, "message_id": shown.buttons_message, "reply_markup": {"inline_keyboard": []}})
            if shown.sent:
                self._call("sendMessage", {"chat_id": self._chat_id, "text": f"{text}\n\n{shown.tool}, fingerprint {shown.fingerprint[:12]}..."[:MESSAGE_LIMIT]})
        except TelegramError as error:
            self._note(error)

    def _clean(self, text: str) -> str:
        return text.replace(self._token, TOKEN_REMOVED)[:300]

    def _call(self, method: str, body: dict, timeout: float = 20.0) -> Any:
        """One call to the Bot API. Returns its result, or raises TelegramError with the token left out."""
        request = urllib.request.Request(
            f"{self._api}/bot{self._token}/{method}", data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with self._opener.open(request, timeout=timeout) as reply:
                raw = reply.read(4_000_000)
        except urllib.error.HTTPError as error:
            try:
                said = json.loads(error.read(100_000)).get("description")
            except Exception:
                said = None
            said = said if type(said) is str else "no reason given"
            raise TelegramError(self._clean(f"Telegram refused {method} ({error.code}: {said})")) from None
        except Exception as error:
            raise TelegramError(f"Telegram could not be reached for {method} ({type(error).__name__})") from None
        try:
            answer = json.loads(raw)
        except ValueError:
            answer = None
        if type(answer) is not dict or answer.get("ok") is not True:
            raise TelegramError(f"Telegram gave an answer to {method} that could not be read")
        return answer.get("result")


def _checked_api(api: Any) -> str:
    """The address of the Bot API: HTTPS, or plain HTTP only to this machine (a stand-in for tests)."""
    try:
        parts = urllib.parse.urlsplit(api if type(api) is str else "")
        host, port = parts.hostname, parts.port
    except ValueError:
        host = None
    if not host or parts.username or parts.password or parts.path not in ("", "/") or parts.query or parts.fragment:
        raise TelegramError("api must be an address such as https://api.telegram.org, with nothing after it")
    if parts.scheme != "https" and not (parts.scheme == "http" and host in ("127.0.0.1", "localhost", "::1")):
        raise TelegramError("api must start with https://. Plain http:// is taken only for this machine (127.0.0.1)")
    return f"{parts.scheme}://{parts.netloc}"


def _parts(preview: str, behind: int, max_parts: int = MAX_PARTS, tool: Any = None, first_time: Any = None, trust: tuple = ()) -> tuple[list, bool]:
    """The messages for one held action, each as (text, entities), and whether it can be approved here.

    The preview is sent as it is, as a block of fixed-width text. It is marked as
    such with an entity, never with markup in the text, so nothing in a value can
    be read as formatting or as a link. A preview that does not fit in one message
    carries on in the next. One that would need more than max_parts is too long to
    read on a phone: its start is sent, with a Deny button only.

    Above the box, in bold, is a headline with the tool's name, and a line that
    names the inputs marked first time. Both are names from your own rules, never
    a value, and only a short plain name is put there. The box says all of it.
    """
    lines = preview.split("\n")
    blocks, block = [], ""
    for line in lines:
        while len(line) > PART_CHARS:  # the checkpoint writes no such line; this is for a preview from somewhere else
            lines_cut, line = line[:PART_CHARS], line[PART_CHARS:]
            blocks, block = blocks + ([block] if block else []) + [lines_cut], ""
        if block and len(block) + 1 + len(line) > PART_CHARS:
            blocks, block = blocks + [block], line
        else:
            block = line if not block else block + "\n" + line
    blocks.append(block)
    can_approve = len(blocks) <= max_parts
    if not can_approve:
        blocks = blocks[:1]
    parts = []
    for number, block in enumerate(blocks, 1):
        head, marks = [], []
        if number == 1:
            head.append(FIRST_LINE)
            if _plain(tool):
                head.append(tool)
            marks.append({"type": "bold", "offset": 0, "length": _units("\n".join(head))})
            new = list(first_time) if type(first_time) in (list, tuple) else []
            if new:
                named = len(new) <= NAMES_SHOWN and all(_plain(name) for name in new)
                head.append(FIRST_TIME + (", ".join(new) if named else f"{len(new)} input{'' if len(new) == 1 else 's'}"))
            if behind:
                head.append(f"{behind} more {'is' if behind == 1 else 'are'} waiting after this one.")
        if len(blocks) > 1:
            head.append(f"Part {number} of {len(blocks)}." + (" The buttons are under the last part." if number < len(blocks) else ""))
        above = "\n".join(head) + "\n\n"
        if not can_approve:
            below = f"\n\n{NOT_HERE} It is {len(lines)} lines long and only the start is shown. Approve it where you can read all of it, or deny it here."
        elif number == len(blocks):
            below = "\n\n" + (HOW_TO if len(blocks) == 1 else HOW_TO_PARTS) + (" " + HOW_TO_TRUST.format(what=_what(trust)) if trust else "")
        else:
            below = ""
        block = block or " "
        marks.append({"type": "pre", "offset": _units(above), "length": _units(block)})
        if can_approve and number == len(blocks):
            marks.append({"type": "italic", "offset": _units(above + block) + 2, "length": _units(below) - 2})
        parts.append((above + block + below, marks))
    return parts, can_approve


def _what(names: tuple) -> str:
    """The inputs offered for trust, in words: their names when they are few, short and plain, or else how many."""
    if len(names) <= NAMES_SHOWN and all(_plain(name) for name in names):
        return "the " + ", ".join(f'"{name}"' for name in names) + " in the box"
    return f"the {len(names)} inputs offered"


def _plain(name: Any) -> bool:
    """Whether a name is short and plain enough to stand above the box."""
    return type(name) is str and re.fullmatch(r"[A-Za-z0-9_.:-]{1,48}", name) is not None


def _units(text: str) -> int:
    """The length of text as Telegram counts it, in UTF-16 units."""
    return len(text.encode("utf-16-le")) // 2


def find_chat_id(
    token: str,
    *,
    api: str = API,
    wait_seconds: float = 120.0,
    long_poll_seconds: int = 25,
    say: Callable[[str], Any] = print,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """Find the number of your own private chat with the bot, to pass as chat_id.

    Anyone who knows a bot's name can write to it, so the first chat that writes is
    not taken as yours. A code is shown here, on your screen, and only a private
    chat that sends that code is yours. A code that turns up in a group has been
    seen by the group and is no longer good. What was sent to the bot before the
    code was shown is passed over. Raises TelegramError if no chat is found; the
    message never holds the token.
    """
    if type(wait_seconds) not in (int, float) or wait_seconds <= 0:
        raise TelegramError("wait_seconds must be a number above 0")
    line = TelegramApprover(None, token=token, chat_id=1, api=api)  # only its line to Telegram is used; nothing is sent or listened to as chat 1
    bot = line._call("getMe", {})
    name = bot.get("username") if type(bot) is dict else None
    if type(name) is not str or not re.fullmatch(r"[A-Za-z0-9_]{1,64}", name):
        raise TelegramError("Telegram did not say which bot this token belongs to")
    offset = _skip_old(line)
    code = "".join(secrets.choice("0123456789") for _ in range(CODE_DIGITS))
    say(f"This token belongs to the bot @{name}.")
    say(f"Open your chat with @{name} in Telegram and send it this code: {code}")
    say(f"Waiting up to {int(wait_seconds)} seconds. Only that code, sent in a private chat, counts.")
    end = clock() + wait_seconds
    wrong = 0
    while True:
        left = end - clock()
        if left <= 0:
            raise TelegramError("no message with the code came in time")
        poll = max(0, min(int(long_poll_seconds), max(1, int(left))))  # a wait does not run far past the limit
        updates = line._call("getUpdates", {"offset": offset, "timeout": poll, "allowed_updates": ["message"]}, poll + 10)
        for update in updates if type(updates) is list else []:
            number = update.get("update_id") if type(update) is dict else None
            if type(number) is not int:
                continue
            offset = max(offset, number + 1)
            message = update.get("message") if type(update.get("message")) is dict else {}
            sent = message.get("text")
            if type(sent) is not str or not re.fullmatch(rf"[0-9]{{{CODE_DIGITS}}}", sent.strip()):
                continue  # anything that is not a code is not looked at, and is not shown
            sender, chat = (message.get(key) if type(message.get(key)) is dict else {} for key in ("from", "chat"))
            chat_id = chat.get("id")
            right = hmac.compare_digest(sent.strip(), code)
            private = chat.get("type") == "private" and type(chat_id) is int and chat_id > 0 and sender.get("id") == chat_id
            if right and private:
                _found(line, chat_id, offset)
                return chat_id
            if right:
                raise TelegramError("the code was sent in a group, so others have seen it. Run this again and send the new code in your private chat with the bot")
            wrong += 1
            if wrong >= WRONG_CODES:
                raise TelegramError(f"{WRONG_CODES} wrong codes were sent. Run this again for a new code")


def _skip_old(line: TelegramApprover) -> int:
    """Pass over what was sent to the bot before the code was shown: none of it can be the code. Returns where to listen from."""
    offset = 0
    for _ in range(OLD_ROUNDS):
        updates = line._call("getUpdates", {"offset": offset, "timeout": 0, "allowed_updates": ["message"]})
        numbers = [update.get("update_id") for update in updates if type(update) is dict] if type(updates) is list else []
        numbers = [number for number in numbers if type(number) is int]
        if not numbers:
            break
        offset = max(offset, max(numbers) + 1)
    return offset


def _found(line: TelegramApprover, chat_id: int, offset: int) -> None:
    """Tell Telegram the code has been read, and say so in the chat. The chat is already found: a fault here changes nothing."""
    for method, body in (
        ("getUpdates", {"offset": offset, "timeout": 0, "allowed_updates": ["message"]}),
        ("sendMessage", {"chat_id": chat_id, "text": FOUND_NOTE}),
    ):
        try:
            line._call(method, body)
        except TelegramError:
            pass


def main(
    argv: Optional[list] = None, *, environ: Optional[Any] = None, api: str = API, say: Callable[[str], Any] = print, wait_seconds: float = 120.0
) -> int:
    """python -m kettle.telegram: print your chat id and the next step. Returns 0 if found, 1 if not, 2 if it could not start."""
    argv = sys.argv[1:] if argv is None else argv
    environ = os.environ if environ is None else environ
    if argv:
        say(USAGE)
        return 2
    token = environ.get(TOKEN_NAME, "").strip()
    if not token:
        say(NO_TOKEN)
        return 2
    try:
        chat_id = find_chat_id(token, api=api, say=say, wait_seconds=wait_seconds)
    except TelegramError as error:
        say(f"No chat id: {error}.")
        return 1
    say("")
    say(f"Your chat id is {chat_id}")
    say("")
    say("Next step: give that number to the approver in your agent's code.")
    say("")
    say(f'    approver = TelegramApprover(cp, token=os.environ["{TOKEN_NAME}"], chat_id={chat_id})')
    say("")
    say("Only a button pressed in that chat will count as an answer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
