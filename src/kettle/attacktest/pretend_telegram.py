"""A pretend Telegram that runs on this machine only, for the tests and for --yes-set.

It speaks the four Bot API methods the approver uses (sendMessage, getUpdates,
answerCallbackQuery, editMessageReplyMarkup), and getMe, and keeps to the limits the real one
documents: 4096 characters in a message and 64 bytes in a button's data.

It is not Telegram. It shows that the approver does what it should with the
answers it is given. How the real service behaves has to be tried with a real bot.

    with PretendTelegram() as telegram:
        ...  # point the approver at telegram.api with telegram.token
        telegram.press(message_id, "Approve")
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Optional

MESSAGE_LIMIT = 4096
DATA_LIMIT = 64
TOKEN = "1234567890:pretend-token-made-up-for-the-tests"  # the shape of a bot token; it opens nothing


class PretendTelegram:
    def __init__(self, token: str = TOKEN) -> None:
        self.token = token
        self.username = "kettle_pretend_bot"
        self.messages: list[dict] = []  # every message sent, as {"message_id", "chat_id", "text", "entities", "reply_markup"}
        self.answers: list[dict] = []  # every answer to a button press
        self.calls: list[tuple] = []  # (method, body) of every call that named the right token
        self.wrong_token = 0  # calls that named another token
        self._updates: list[dict] = []
        self._ids = {"update": 0, "message": 0, "query": 0}
        self._failing: list[dict] = []  # the calls still to fail
        self._changed = threading.Condition()
        self._closed = False
        pretend = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def do_POST(self) -> None:
                try:
                    size = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(size) or b"{}")
                except ValueError:
                    return self._reply(400, "Bad Request: the body is not JSON")
                parts = self.path.split("/")
                if len(parts) != 3 or parts[1] != "bot" + pretend.token:
                    with pretend._changed:
                        pretend.wrong_token += 1
                    return self._reply(401, "Unauthorized")
                code, result = pretend._handle(parts[2], body if type(body) is dict else {})
                self._reply(code, result)

            def _reply(self, code: int, result: Any) -> None:
                if code == 200:
                    text = json.dumps({"ok": True, "result": result})
                else:
                    text = json.dumps({"ok": False, "error_code": code, "description": result})
                data = text.encode("utf-8")
                try:
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:  # the caller gave up waiting
                    pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self._thread.start()

    # ---- for the code under test ---------------------------------------------

    @property
    def api(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self) -> "PretendTelegram":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        with self._changed:
            if self._closed:
                return
            self._closed = True
            self._changed.notify_all()
        self._server.shutdown()
        self._server.server_close()

    # ---- what a test does ------------------------------------------------------

    def press(
        self,
        message_id: int,
        button: str = "Approve",
        *,
        from_id: Optional[int] = None,
        chat_id: Optional[int] = None,
        data: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> str:
        """Someone presses a button. By default it is the person the message was sent to, in that chat.

        data, from_id, chat_id and kind can each be set to something else, to make
        a press that should not count. Returns the id of the press, for answer_to().
        """
        with self._changed:
            sent = next((message for message in self.messages if message["message_id"] == message_id), None)
            owner = sent["chat_id"] if sent else 0
            if data is None:
                rows = ((sent or {}).get("reply_markup") or {}).get("inline_keyboard") or []
                found = [key["callback_data"] for row in rows for key in row if button in (key["text"], key["text"].split()[-1])]  # "Approve" finds a button that reads "(tick) Approve"
                if not found:
                    raise LookupError(f"message {message_id} has no {button} button")
                data = found[0]
            chat = owner if chat_id is None else chat_id
            self._ids["query"] += 1
            query_id = str(self._ids["query"])
            self._add(
                {
                    "callback_query": {
                        "id": query_id,
                        "from": {"id": owner if from_id is None else from_id, "is_bot": False, "first_name": "Someone"},
                        "message": {
                            "message_id": message_id,
                            "chat": {"id": chat, "type": kind or ("private" if chat > 0 else "group")},
                            "date": int(time.time()),
                            "text": sent["text"] if sent else "",
                        },
                        "chat_instance": "1",
                        "data": data,
                    }
                }
            )
            return query_id

    def say(self, text: str, *, from_id: int, chat_id: Optional[int] = None) -> None:
        """Someone types a message to the bot. It is handed over even if only button presses were asked for."""
        with self._changed:
            self._ids["message"] += 1
            chat = from_id if chat_id is None else chat_id
            self._add(
                {
                    "message": {
                        "message_id": self._ids["message"],
                        "from": {"id": from_id, "is_bot": False, "first_name": "Someone"},
                        "chat": {"id": chat, "type": "private" if chat > 0 else "group"},
                        "date": int(time.time()),
                        "text": text,
                    }
                }
            )

    def hand_over(self, update: dict) -> None:
        """Hand over an update exactly as given, in any shape."""
        with self._changed:
            self._add(dict(update))

    def fail(self, times: int = 1, method: Optional[str] = None, code: int = 500, said: Optional[str] = None, after: int = 0) -> None:
        """The next `times` calls (of this method, or of any) are answered with an error and do nothing.

        said is the reason given. after lets that many such calls through first.
        """
        with self._changed:
            self._failing.append({"method": method, "code": code, "said": said, "after": after, "times": times})

    def wait_for(self, check: Callable[[], Any], timeout: float = 5.0) -> bool:
        """Wait until check() is true. Returns whether it became true in time."""
        end = time.monotonic() + timeout
        with self._changed:
            while not check():
                left = end - time.monotonic()
                if left <= 0:
                    return False
                self._changed.wait(min(left, 0.05))
            return True

    def with_buttons(self) -> list[dict]:
        """The messages that have buttons on them right now."""
        with self._changed:
            return [message for message in self.messages if (message.get("reply_markup") or {}).get("inline_keyboard")]

    def answer_to(self, query_id: str, timeout: float = 5.0) -> Optional[dict]:
        """The answer given to one press, once it has been given."""

        def found() -> list:
            return [answer for answer in self.answers if answer.get("callback_query_id") == query_id]

        return found()[0] if self.wait_for(found, timeout) else None

    def made(self, method: str) -> list[dict]:
        with self._changed:
            return [body for name, body in self.calls if name == method]

    # ---- inside ----------------------------------------------------------------

    def _add(self, update: dict) -> None:
        self._ids["update"] += 1
        update["update_id"] = self._ids["update"]
        self._updates.append(update)
        self._changed.notify_all()

    def _handle(self, method: str, body: dict) -> tuple[int, Any]:
        with self._changed:
            self.calls.append((method, body))
            for failing in self._failing:
                if failing["method"] not in (None, method):
                    continue
                if failing["after"] > 0:
                    failing["after"] -= 1
                    continue
                failing["times"] -= 1
                self._failing = [each for each in self._failing if each["times"] > 0]
                self._changed.notify_all()
                code = failing["code"]
                return code, failing["said"] or ("Internal Server Error" if code >= 500 else "Bad Request: made to fail by the test")
        handler = getattr(self, "_" + method, None)
        if handler is None:
            return 404, "Not Found: method not found"
        code, result = handler(body)
        with self._changed:
            self._changed.notify_all()
        return code, result

    def _sendMessage(self, body: dict) -> tuple[int, Any]:
        text, chat_id = body.get("text"), body.get("chat_id")
        if type(chat_id) is not int:
            return 400, "Bad Request: chat not found"
        if type(text) is not str or not text:
            return 400, "Bad Request: message text is empty"
        units = len(text.encode("utf-16-le")) // 2  # Telegram counts in UTF-16 units, so the NEW sign counts as two
        if units > MESSAGE_LIMIT:
            return 400, "Bad Request: message is too long"
        if "parse_mode" in body:
            return 400, "Bad Request: the pretend Telegram takes no parse_mode, so no text can be read as markup"
        entities = body.get("entities") or []
        for entity in entities:
            if type(entity) is not dict or type(entity.get("offset")) is not int or type(entity.get("length")) is not int:
                return 400, "Bad Request: can't parse entities"
            if entity["offset"] < 0 or entity["length"] <= 0 or entity["offset"] + entity["length"] > units:
                return 400, "Bad Request: an entity is outside the text"
        markup = body.get("reply_markup")
        problem = _markup_problem(markup)
        if problem:
            return 400, problem
        with self._changed:
            self._ids["message"] += 1
            message = {"message_id": self._ids["message"], "chat_id": chat_id, "text": text, "entities": entities, "reply_markup": markup}
            self.messages.append(message)
        return 200, {"message_id": message["message_id"], "chat": {"id": chat_id, "type": "private"}, "date": int(time.time()), "text": text}

    def _editMessageReplyMarkup(self, body: dict) -> tuple[int, Any]:
        problem = _markup_problem(body.get("reply_markup"))
        if problem:
            return 400, problem
        with self._changed:
            for message in self.messages:
                if message["message_id"] == body.get("message_id") and message["chat_id"] == body.get("chat_id"):
                    message["reply_markup"] = body.get("reply_markup")
                    return 200, True
        return 400, "Bad Request: message to edit not found"

    def _answerCallbackQuery(self, body: dict) -> tuple[int, Any]:
        if type(body.get("callback_query_id")) is not str:
            return 400, "Bad Request: query is too old or the id is wrong"
        with self._changed:
            self.answers.append(body)
        return 200, True

    def _getMe(self, body: dict) -> tuple[int, Any]:
        return 200, {"id": int(self.token.split(":")[0]), "is_bot": True, "first_name": "Pretend", "username": self.username}

    def _getUpdates(self, body: dict) -> tuple[int, Any]:
        offset = body.get("offset") if type(body.get("offset")) is int else 0
        wait = body.get("timeout") if type(body.get("timeout")) in (int, float) else 0
        end = time.monotonic() + min(max(wait, 0), 50)
        with self._changed:
            while True:
                self._updates = [update for update in self._updates if update["update_id"] >= offset]
                left = end - time.monotonic()
                if self._updates or left <= 0 or self._closed:
                    return 200, list(self._updates)
                self._changed.wait(min(left, 0.05))


def _markup_problem(markup: Any) -> Optional[str]:
    if markup is None:
        return None
    rows = markup.get("inline_keyboard") if type(markup) is dict else None
    if type(rows) is not list:
        return "Bad Request: can't parse reply keyboard markup"
    for row in rows:
        for key in row if type(row) is list else [None]:
            if type(key) is not dict or type(key.get("text")) is not str or not key["text"]:
                return "Bad Request: can't parse inline keyboard button"
            data = key.get("callback_data")
            if type(data) is not str or not 1 <= len(data.encode("utf-8")) <= DATA_LIMIT:
                return "Bad Request: BUTTON_DATA_INVALID"
    return None
