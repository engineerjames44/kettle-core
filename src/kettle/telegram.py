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
  - At most at_once actions are on the phone at a time. The rest wait.
  - If Telegram cannot be reached, or answers with an error, nothing is approved.

Everything else is still the checkpoint's job: a yes covers one exact action,
once, until it expires. This object only carries the question and the answer.

The token is the key to your bot. It is never put in an error, in repr() or in
anything this module prints. Give the bot no other job: two programs cannot
listen on one bot.

This is not a wall against code that runs in the same process: such code can
reach the checkpoint itself. See the README.
"""

from __future__ import annotations

import json
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

FIRST_LINE = "An agent wants to do this. Nothing has run yet."
HOW_TO = "Approve runs exactly what is shown above, once. Deny runs nothing."
NOT_YOURS = "Only the owner can answer this."
NOT_OPEN = "That request is no longer open."
TOO_SOON = "Too soon. Read it, then press again."
NOT_HERE = "This action is too long to approve on a phone."
NO_ANSWER = "This action needs the owner's yes. No answer came in time. Nothing was run."


class TelegramError(Exception):
    """Telegram could not be set up or reached. The message never holds the token."""


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **more: Any) -> None:
        return None  # a redirect is an error: the token goes to the address given and nowhere else


class _Shown:
    """One held action as it stands on the phone."""

    __slots__ = ("request_id", "fingerprint", "tool", "nonce", "parts", "can_approve", "sent", "buttons_message", "shown_at", "answered")

    def __init__(self, request_id: str, fingerprint: str, tool: str, parts: list, can_approve: bool) -> None:
        self.request_id, self.fingerprint, self.tool = request_id, fingerprint, tool
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
    ) -> None:
        """checkpoint is the Checkpoint whose held actions are sent. Keep this object on the owner's side of your app.

        token is the bot's token and chat_id is the number of your own private chat
        with the bot. approver is the name the log keeps for a yes given here.

        problem is called with a short line when Telegram cannot be reached. With
        none, the line is printed to stderr. It never holds the token.
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
            self._threads = [
                threading.Thread(target=self._loop, args=(self._send_step, self._poll, stop), daemon=True, name="kettle-telegram-send"),
                threading.Thread(target=self._loop, args=(self._listen_step, 0.05, stop), daemon=True, name="kettle-telegram-listen"),
            ]
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
                parts, can_approve = _parts(item["preview"], len(new) - index - 1, self._max_parts)
                shown = _Shown(item["request_id"], item["fingerprint"], item["tool"], parts, can_approve)
                self._shown[shown.request_id] = self._nonces[shown.nonce] = shown
            to_send = [shown for shown in self._shown.values() if shown.buttons_message is None]
        for shown in gone:  # answered somewhere else, or expired
            found = self._checkpoint.status(shown.request_id)
            self._take_buttons_off(shown, f"No longer open ({found['state'] if found else 'gone'}). Nothing more can be done with it here.")
        for shown in to_send:
            self._deliver(shown)

    def _deliver(self, shown: _Shown) -> None:
        """Send the parts that have not gone out yet. The buttons go on the last one, after all the rest."""
        while shown.sent < len(shown.parts):
            text, entities = shown.parts[shown.sent]
            body: dict = {"chat_id": self._chat_id, "text": text, "entities": entities, "link_preview_options": {"is_disabled": True}}
            last = shown.sent == len(shown.parts) - 1
            if last:
                keys = [{"text": "Approve", "callback_data": "a:" + shown.nonce}] if shown.can_approve else []
                body["reply_markup"] = {"inline_keyboard": [keys + [{"text": "Deny", "callback_data": "d:" + shown.nonce}]]}
            sent = self._call("sendMessage", body)
            message_id = sent.get("message_id") if type(sent) is dict else None
            if type(message_id) is not int:
                raise TelegramError("Telegram did not say which message it sent")
            with self._lock:
                shown.sent += 1
                if last:
                    shown.buttons_message, shown.shown_at = message_id, self._clock()

    def _listen_step(self) -> None:
        updates = self._call("getUpdates", {"offset": self._offset, "timeout": self._long_poll, "allowed_updates": ["callback_query"]}, self._long_poll + 10)
        for update in updates if type(updates) is list else []:
            number = update.get("update_id") if type(update) is dict else None
            if type(number) is not int:
                continue
            self._offset = max(self._offset, number + 1)  # first, so one update that cannot be handled is not handed over for ever
            self._on_update(update)

    def _on_update(self, update: dict) -> None:
        query = update.get("callback_query")
        if type(query) is not dict:
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
            shown = self._nonces.get(nonce) if kind in ("a", "d") else None
            if shown is not None and shown.buttons_message is None:
                return_text = TOO_SOON  # the buttons are out, and this object has not been told so yet
            elif shown is None or message.get("message_id") != shown.buttons_message:
                return_text = NOT_OPEN
            elif kind == "a" and not shown.can_approve:
                return_text = NOT_HERE
            elif kind == "a" and self._clock() - shown.shown_at < self._min_read:
                return_text = TOO_SOON
            else:
                return_text = None
                shown.answered = True
                self._nonces.pop(shown.nonce, None)  # from here on its buttons answer nothing, whatever the checkpoint says
        if return_text is not None:
            return self._answer(query_id, return_text, alert=True)
        try:
            if kind == "a":
                decision = self._checkpoint.approve(shown.request_id, shown.fingerprint, self._approver)
                text = "Approved. It runs once, exactly as shown." if decision.status == APPROVED else decision.reason
            else:
                decision = self._checkpoint.deny(shown.request_id, self._approver)
                text = "Denied. Nothing was run." if decision.status == DENIED else decision.reason
        finally:
            with self._lock:
                self._forget(shown)
        self._answer(query_id, text)
        self._take_buttons_off(shown, text)

    # ---- inside -------------------------------------------------------------------

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


def _parts(preview: str, behind: int, max_parts: int = MAX_PARTS) -> tuple[list, bool]:
    """The messages for one held action, each as (text, entities), and whether it can be approved here.

    The preview is sent as it is, as a block of fixed-width text. It is marked as
    such with an entity, never with markup in the text, so nothing in a value can
    be read as formatting or as a link. A preview that does not fit in one message
    carries on in the next. One that would need more than max_parts is too long to
    read on a phone: its start is sent, with a Deny button only.
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
        head = []
        if number == 1:
            head.append(FIRST_LINE)
            if behind:
                head.append(f"{behind} more {'is' if behind == 1 else 'are'} waiting after this one.")
        if len(blocks) > 1:
            head.append(f"Part {number} of {len(blocks)}." + (" The buttons are under the last part." if number < len(blocks) else ""))
        above = "\n".join(head) + "\n\n"
        if not can_approve:
            below = f"\n\n{NOT_HERE} It is {len(lines)} lines long and only the start is shown. Approve it where you can read all of it, or deny it here."
        elif number == len(blocks):
            below = "\n\n" + HOW_TO
        else:
            below = ""
        block = block or " "
        parts.append((above + block + below, [{"type": "pre", "offset": _units(above), "length": _units(block)}]))
    return parts, can_approve


def _units(text: str) -> int:
    """The length of text as Telegram counts it, in UTF-16 units."""
    return len(text.encode("utf-16-le")) // 2
