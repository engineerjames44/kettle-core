"""Put Kettle in front of any MCP server, with no code to write.

    python -m kettle.mcp --config kettle-mcp.toml -- <the server's own command>

An MCP app (Claude Desktop, Cursor, Claude Code) starts this in place of the
server. It starts the server itself and passes every message through unchanged,
except one: each tools/call goes through a Checkpoint first. A free call runs at
once. A call that needs a yes is held and sent to the owner's phone with the
Telegram approver, and runs only on Approve. A refused, denied or expired call
is answered with an error result and never reaches the server.

It needs no other package: MCP over stdio is one JSON-RPC message per line.

The config is TOML. Every tool the server offers gets the default level unless
it is named:

    store = "~/.kettle/mcp.db"          # the checkpoint's own file
    hold_seconds = 300                  # how long a held call waits for the owner

    [approver]                          # the token is read from KETTLE_TELEGRAM_TOKEN
    chat_id = 123456789
    preview_width = 36                  # optional: what your phone shows on a line

    [tools]
    default = "ask"                     # "free", "ask" or "never"
    read_file = "free"
    delete_file = "never"

    [tools.send_email]                  # a ready-made rule from kettle.rules
    rule = "email"
    contacts = ["sam@example.com"]
    me = ["alex@example.com"]
    watch = ["to", "cc"]

What it does not do:

  - It trusts the names the server gives its tools. A server that offers a
    dangerous tool under the name of one you set to "free" gets it run free.
    Set the default to "ask" and name only the tools you know.
  - It sees a tool's inputs, not what the server does with them.
  - An app that gives up waiting before the owner answers gets an error; the
    held call is then never run here, whatever the owner presses later.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import pathlib
import subprocess
import sys
import threading
from typing import Any, Callable, IO, Optional

from . import rules as ready_made
from .checkpoint import APPROVED, DENIED, FREE, HELD, NEEDS_YES, NEVER, RAN, Checkpoint

LEVELS = {"free": FREE, "ask": NEEDS_YES, "never": NEVER}
RULES = ("email", "payment", "web", "shell", "files", "calendar", "database")
ACTOR = "an MCP app, through kettle.mcp"
NO_APPROVER = "This call needs the owner's yes, and no phone is set up to ask. Nothing was run."
DENIED_TEXT = "The owner was asked and said no. Nothing was run."
NO_ANSWER = "This call needs the owner's yes. No answer came in time. Nothing was run."
GAVE_UP = "The app stopped waiting for this call. Nothing was run."
SERVER_GONE = "The MCP server is not running. Nothing was run."
FAILED = "The MCP server answered this call with an error."
TOKEN_NAME = "KETTLE_TELEGRAM_TOKEN"


class ConfigError(Exception):
    pass


def level_for(name: str, tools: dict) -> tuple[Any, Optional[Callable[[dict], str]], tuple]:
    """The level, the describe function and the watched inputs for one tool, from the [tools] table."""
    if type(tools) is not dict:
        raise ConfigError("[tools] must be a table")
    entry = tools.get(name, tools.get("default", "ask"))
    if type(entry) is str:
        if entry not in LEVELS:
            raise ConfigError(f'a tool\'s level must be "free", "ask" or "never", not {entry!r}')
        return LEVELS[entry], None, ()
    if type(entry) is not dict:
        raise ConfigError(f"tools.{name} must be a level or a table")
    options = dict(entry)
    watch = options.pop("watch", [])
    if type(watch) is not list or not all(type(item) is str for item in watch):
        raise ConfigError(f"tools.{name}.watch must be a list of input names")
    if "level" in options:
        level = options.pop("level")
        if options or level not in LEVELS:
            raise ConfigError(f'tools.{name} takes a level ("free", "ask" or "never") and watch, and nothing else')
        return LEVELS[level], None, tuple(watch)
    kind = options.pop("rule", None)
    if kind not in RULES:
        raise ConfigError(f"tools.{name}.rule must be one of {', '.join(RULES)}")
    try:
        rule = getattr(ready_made, kind)(**options)
    except (TypeError, ValueError) as error:
        raise ConfigError(f"tools.{name}: {error}") from None
    return rule, rule.why, tuple(watch)


def read_config(path: str) -> dict:
    import tomllib

    try:
        with open(path, "rb") as handle:
            config = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"the config could not be read: {error}") from None
    tools = config.get("tools", {"default": "ask"})
    level_for("a name no tool has", tools)  # the default is checked before anything starts
    for name in tools:
        if name != "default":
            level_for(name, tools)
    return config


class Proxy:
    """Relay one MCP app and one MCP server, and put each tools/call through a checkpoint."""

    def __init__(
        self,
        checkpoint: Checkpoint,
        tools: dict,
        server_in: IO[str],
        server_out: IO[str],
        app_out: IO[str],
        approver: Any = None,
        wait_seconds: Optional[float] = None,
    ) -> None:
        self._cp = checkpoint
        self._tools = tools
        self._server_in = server_in
        self._server_out = server_out
        self._app_out = app_out
        self._approver = approver
        self._wait = wait_seconds
        self._gate = checkpoint.gate_for(ACTOR)
        self._write_lock = threading.Lock()
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._ours: dict[str, dict] = {}  # our own requests to the server, by id: {"done": Event, "reply": ...}
        self._lists: dict[Any, bool] = {}  # the app's tools/list requests, by id
        self._calls: dict[Any, threading.Event] = {}  # the app's tools/call requests waiting here, by id: set when the app gives up
        self._known: set[str] = set()
        self._gone = threading.Event()

    # ---- the two directions -------------------------------------------------

    def from_app(self, line: str) -> None:
        """One line from the app. A tools/call is answered here; everything else goes to the server as it is."""
        try:
            message = json.loads(line)
        except ValueError:
            message = None
        if type(message) is dict and type(message.get("id")) is str and message["id"].startswith("kettle-"):
            if "method" in message:  # these ids are this proxy's own, for its calls to the server
                self._send(self._app_out, json.dumps({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32600, "message": "ids that start with kettle- are kept for kettle.mcp"}}))
            return
        if type(message) is dict and message.get("method") == "tools/call" and "id" in message:
            stop = threading.Event()
            with self._lock:
                self._calls[_key(message["id"])] = stop
            threading.Thread(target=self._call, args=(message, stop), daemon=True).start()
            return
        if type(message) is dict and message.get("method") == "notifications/cancelled":
            params = message.get("params") if type(message.get("params")) is dict else {}
            with self._lock:
                stop = self._calls.get(_key(params.get("requestId")))
            if stop is not None:
                stop.set()
                return  # the call never reached the server, so the server is not told
        if type(message) is dict and message.get("method") == "tools/list" and "id" in message:
            with self._lock:
                self._lists[_key(message["id"])] = True
        self._send(self._server_in, line)

    def from_server(self, line: str) -> None:
        """One line from the server. A reply to our own request is kept; everything else goes to the app as it is."""
        try:
            message = json.loads(line)
        except ValueError:
            message = None
        if type(message) is dict and "method" not in message and "id" in message:
            key = _key(message["id"])
            with self._lock:
                ours = self._ours.pop(key, None) if type(message["id"]) is str and message["id"].startswith("kettle-") else None
                listing = self._lists.pop(key, None)
            if ours is not None:
                ours["reply"] = message
                ours["done"].set()
                return
            if listing:
                self._learn(message.get("result"))
        self._send(self._app_out, line)

    def server_gone(self) -> None:
        """The server's output ended: every call waiting on it gets an answer."""
        self._gone.set()
        with self._lock:
            waiting, self._ours = list(self._ours.values()), {}
        for ours in waiting:
            ours["done"].set()

    # ---- inside -------------------------------------------------------------

    def _learn(self, result: Any) -> None:
        """Each tool the server lists is put in the checkpoint at the level the config gives its name."""
        found = result.get("tools") if type(result) is dict else None
        for tool in found if type(found) is list else []:
            name = tool.get("name") if type(tool) is dict else None
            if type(name) is not str or not name:
                continue
            level, describe, watch = level_for(name, self._tools)
            with self._lock:
                if name in self._known:
                    continue
                self._known.add(name)
            self._cp.tool(name, self._forwarder(name), level=level, describe=describe, watch=list(watch))

    def _forwarder(self, name: str) -> Callable[..., Any]:
        def forward(**arguments: Any) -> Any:
            return self._ask_server(name, arguments)

        return forward

    def _ask_server(self, name: str, arguments: dict) -> Any:
        if self._gone.is_set():
            raise ConnectionError(SERVER_GONE)
        key = f"kettle-{next(self._ids)}"
        ours: dict = {"done": threading.Event(), "reply": None}
        with self._lock:
            self._ours[_key(key)] = ours
        self._send(self._server_in, json.dumps({"jsonrpc": "2.0", "id": key, "method": "tools/call", "params": {"name": name, "arguments": arguments}}))
        ours["done"].wait()
        reply = ours["reply"]
        if type(reply) is not dict:
            raise ConnectionError(SERVER_GONE)
        if "error" in reply or type(reply.get("result")) is not dict:
            raise RuntimeError(FAILED)
        return reply["result"]

    def _call(self, message: dict, stop: threading.Event) -> None:
        params = message.get("params") if type(message.get("params")) is dict else {}
        name, arguments = params.get("name"), params.get("arguments", {})
        try:
            if type(name) is not str or type(arguments) is not dict:
                result = _error_result("A tools/call needs a tool name and its arguments. Nothing was run.")
            else:
                result = self._decide(name, arguments, stop)
        except Exception:
            result = _error_result("Kettle could not deal with this call. Nothing was run.")
        with self._lock:
            gave_up = self._calls.pop(_key(message["id"]), None)
        if gave_up is not None and gave_up.is_set():
            return  # the app cancelled it: no answer is sent for a cancelled request
        self._send(self._app_out, json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}))

    def _decide(self, name: str, arguments: dict, stop: threading.Event) -> dict:
        decision = self._gate.request(name, arguments)
        if decision.status == RAN:
            return decision.result
        if decision.status != HELD:
            return _error_result(decision.reason)
        if self._approver is None:
            return _error_result(NO_APPROVER)
        self._approver.start()
        state = self._wait_for(decision.request_id, stop)
        if stop.is_set():
            return _error_result(GAVE_UP)
        if state == APPROVED:
            done = self._cp.run(decision.request_id)
            return done.result if done.status == RAN and type(done.result) is dict else _error_result(done.reason)
        return _error_result(DENIED_TEXT if state == DENIED else NO_ANSWER)

    def _wait_for(self, request_id: str, stop: threading.Event) -> str:
        """Wait for the owner, a little at a time, so that an app that gives up is noticed."""
        waited = 0.0
        while True:
            state = self._approver.wait(request_id, timeout=0.5)
            if state != "held" or stop.is_set():
                return state
            waited += 0.5
            if self._wait is not None and waited >= self._wait:
                return state

    def _send(self, stream: IO[str], line: str) -> None:
        with self._write_lock:
            try:
                stream.write(line.rstrip("\n") + "\n")
                stream.flush()
            except (OSError, ValueError):
                pass  # the other side has gone; the reader on that side will notice


def _key(value: Any) -> str:
    return json.dumps(value)


def _error_result(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


def _pump(stream: IO[str], each: Callable[[str], None], end: Callable[[], None]) -> threading.Thread:
    def run() -> None:
        try:
            for line in stream:
                if line.strip():
                    each(line)
        finally:
            end()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def serve(
    config: dict,
    command: list[str],
    app_in: IO[str] = sys.stdin,
    app_out: IO[str] = sys.stdout,
    approver_for: Optional[Callable[[Checkpoint], Any]] = None,
) -> int:
    """Start the server, relay until the app or the server stops, and return the server's exit code.

    approver_for(checkpoint) makes the approver; with none, the [approver] table makes a TelegramApprover.
    """
    store = os.path.expanduser(str(config.get("store", "~/.kettle/mcp.db")))
    if store != ":memory:":
        pathlib.Path(store).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    settings = config.get("approver", {})
    width = settings.get("preview_width") if type(settings) is dict else None
    options = {"hold_seconds": float(config.get("hold_seconds", 300)), "trail": True}
    if width is not None:
        options["preview_width"] = width
    checkpoint = Checkpoint(store, **options)
    approver = approver_for(checkpoint) if approver_for is not None else None
    if approver is None and type(settings) is dict and "chat_id" in settings:
        from .telegram import TelegramApprover

        token = os.environ.get(TOKEN_NAME, "").strip()
        if not token:
            raise ConfigError(f"[approver] is set, but {TOKEN_NAME} is not")
        approver = TelegramApprover(checkpoint, token=token, chat_id=settings["chat_id"], approver="owner, on Telegram, through kettle.mcp")
    server = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
    proxy = Proxy(checkpoint, config.get("tools", {"default": "ask"}), server.stdin, server.stdout, app_out, approver, options["hold_seconds"])
    _pump(server.stdout, proxy.from_server, proxy.server_gone)
    done = threading.Event()
    _pump(app_in, proxy.from_app, done.set)
    try:
        while not done.wait(0.2):
            if server.poll() is not None:
                break
    finally:
        try:
            server.stdin.close()
        except OSError:
            pass
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
        if approver is not None:
            approver.stop()
        checkpoint.close()
    return server.returncode or 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kettle.mcp", description="Put Kettle in front of an MCP server.")
    parser.add_argument("--config", required=True, help="the TOML file that sets each tool's level")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="-- and then the MCP server's own command")
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("give the server's command after --")
    try:
        return serve(read_config(args.config), command)
    except ConfigError as error:
        print(f"kettle.mcp: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
