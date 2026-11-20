"""Put Kettle in front of Claude Code: risky tool calls wait for your yes on your phone.

    python -m kettle.claude_code serve     the daemon (one for every Claude Code session)
    python -m kettle.claude_code hook      what Claude Code runs before each tool call
    python -m kettle.claude_code status    is the daemon answering?
    python -m kettle.claude_code setup     the token check, your chat, the login item, the hook (each on your yes)
    python -m kettle.claude_code uninstall

Claude Code runs the hook before each tool call (its PreToolUse hook). The hook
holds no secret and decides nothing: it passes the call to the daemon over a
local socket and prints the daemon's answer. The daemon owns the checkpoint, its
hash-chained log, the ready-made rules and the Telegram approver.

What the hook answers:

    the rule says free        no decision: Claude Code's own permission flow, unchanged
    the rule needs a yes      Approve on the phone: allow. Deny, or no answer in time: deny
    the rule says never       deny, with the rule's reason, which Claude is shown
    anything goes wrong       deny: Kettle is not running, so nothing risky can run

Kettle only adds asks. It never turns off one of Claude Code's own.

Which rule for which tool:

    Bash                         the shell rule, with your own commands in `allow`; a read
                                 outside the folders below asks, as it does for Read
    Write, Edit, NotebookEdit    the files rule for writing: the session's own folder is free
    Read, Grep, Glob             the files rule for reading: the session's own folder is free
    WebFetch                     the web rule, with the sites in `sites` free to read
    every other tool             no decision (MCP tools, WebSearch, Agent and so on)

~/.kettle, where the daemon keeps its log and its settings, is protected: reading
it asks, and writing it is never allowed. A session started in the home folder
itself, or in a folder above it, gets no folder free.

The settings file, ~/.kettle/claude-code.toml (TOML, every line optional):

    chat_id = 123456789                 # your Telegram chat; with none, every ask is denied
    wait_seconds = 300                  # how long a call waits for the phone
    allow = ["pytest", "npm test"]      # shell commands that run free
    folders = ["~/Projects/shared"]     # more folders where reading and writing are free
    read_only = ["~/Documents/specs"]   # more folders where reading is free
    sites = ["docs.python.org"]         # sites WebFetch may read without asking

The bot token is read from KETTLE_TELEGRAM_TOKEN or, on a Mac, from the Keychain
(service kettle-telegram), never from a file of ours.

What it cannot do:

  - Kettle decides; Claude Code runs. Kettle asks the rule again when the yes
    comes, but cannot look again at the moment Claude Code runs the call: a link
    swapped in between is not seen. The window is short, but it is there.
  - Claude Code's tools run as you, and so does the daemon. A program of yours
    that is already running free can do what the hook never sees. The hook is a
    seatbelt, not a wall; the wall is Claude Code in a container or as another user.
  - Changing .claude/ or your shell's start-up files asks, so turning the hook
    off by editing settings lands on the phone like any other risky step. But a
    project's settings can set disableAllHooks, and a project you open may
    already have that line. Claude Code's managed settings
    (allowManagedHooksOnly) are the only way a project cannot turn it off.
  - It sees a tool's inputs, not what a script does once it runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import socketserver
import sys
import threading
from typing import Any, Callable, Optional

KETTLE_HOME = "~/.kettle"
CONFIG = "~/.kettle/claude-code.toml"
SOCKET = "~/.kettle/claude-code.sock"
STORE = "~/.kettle/claude-code.db"
ACTOR = "Claude Code, through kettle.claude_code"
MAX_CALL = 16 * 1024 * 1024  # a Write of a big file comes whole
MAX_REPLY = 64 * 1024
CONNECT_SECONDS = 3.0

NOT_RUNNING = "Kettle is not running, so nothing risky can run. Start it with: python -m kettle.claude_code serve"
BROKE = "Kettle could not deal with this call. Nothing was run."
BAD_CALL = "Kettle was given a call it could not read. Nothing was run."
TOO_BIG = "This call is too big for Kettle to look at. Nothing was run."
NO_FOLDER = "Kettle could not tell which folder this session works in. Nothing was run."
NO_PHONE = "This call needs the owner's yes, and no phone is set up to ask (chat_id in ~/.kettle/claude-code.toml). Nothing was run."
DENIED_TEXT = "The owner said no on their phone. Nothing was run."
NO_ANSWER = "This call needs the owner's yes. No answer came from the phone in time. Nothing was run."
GAVE_UP = "Claude Code stopped waiting for this call. Nothing was run."
APPROVED_TEXT = "The owner approved this on their phone."


class ConfigError(Exception):
    pass


# ---- the answers the hook prints ---------------------------------------------------------


def deny(reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}


def allow(reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow", "permissionDecisionReason": reason}}


def _answer_ok(answer: Any) -> bool:
    """An answer the hook may print: no decision ({}), or an allow or deny with a reason, and nothing else."""
    if answer == {}:
        return True
    if type(answer) is not dict or set(answer) != {"hookSpecificOutput"}:
        return False
    inner = answer["hookSpecificOutput"]
    return (
        type(inner) is dict
        and set(inner) == {"hookEventName", "permissionDecision", "permissionDecisionReason"}
        and inner["hookEventName"] == "PreToolUse"
        and inner["permissionDecision"] in ("allow", "deny")
        and type(inner["permissionDecisionReason"]) is str
    )


# ---- the settings ------------------------------------------------------------------------

_KEYS = {"chat_id": int, "wait_seconds": (int, float), "allow": list, "folders": list, "read_only": list, "sites": list, "store": str, "socket": str}


def read_config(path: Optional[str] = None) -> dict:
    """The settings, with every missing line at its default. No file is the same as an empty one."""
    import tomllib

    where = os.path.expanduser(path or CONFIG)
    try:
        with open(where, "rb") as handle:
            raw = tomllib.load(handle)
    except FileNotFoundError:
        if path is not None:
            raise ConfigError(f"no settings file at {where}") from None
        raw = {}
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"the settings could not be read: {error}") from None
    for key, value in raw.items():
        kind = _KEYS.get(key)
        if kind is None:
            raise ConfigError(f"{key} is not a setting (the settings are {', '.join(_KEYS)})")
        if type(value) is bool or not isinstance(value, kind):
            raise ConfigError(f"{key} has the wrong kind of value")
        if type(value) is list and not all(type(item) is str and item for item in value):
            raise ConfigError(f"{key} must be a list of text")
    wait = float(raw.get("wait_seconds", 300))
    if not 5 <= wait <= 3600:
        raise ConfigError("wait_seconds must be between 5 and 3600")
    return {
        "chat_id": raw.get("chat_id"),
        "wait_seconds": wait,
        "allow": list(raw.get("allow", [])),
        "folders": [os.path.realpath(os.path.expanduser(folder)) for folder in raw.get("folders", [])],
        "read_only": [os.path.realpath(os.path.expanduser(folder)) for folder in raw.get("read_only", [])],
        "sites": list(raw.get("sites", [])),
        "store": raw.get("store", STORE),
        "socket": raw.get("socket", SOCKET),
    }


# ---- which rule for which tool -----------------------------------------------------------

_BASH_IGNORE = ("description", "timeout", "run_in_background")
_GREP_IGNORE = ("pattern", "glob", "output_mode", "-A", "-B", "-C", "-n", "-i", "type", "head_limit", "offset", "multiline", "context")


def _rule_for(tool: str, folder: Optional[str], config: dict, cwd: Optional[str] = None) -> Any:
    from . import rules

    free = ([folder] if folder else []) + config["folders"]
    common = {"base": folder, "protect": [KETTLE_HOME]}
    if tool == "Bash":
        # Reads by the shell are kept to the same folders as the Read tool, so Bash is not a way around it.
        return rules.shell(config["allow"], ignore=_BASH_IGNORE, folders=free + config["read_only"], base=folder or cwd or os.path.expanduser("~"))
    if tool == "Write":
        return rules.files(free, does="write", path="file_path", content="content", **common)
    if tool == "Edit":
        return rules.files(free, does="write", path="file_path", content="new_string", ignore=("old_string", "replace_all"), **common)
    if tool == "NotebookEdit":
        return rules.files(free, does="write", path="notebook_path", content="new_source", ignore=("cell_id", "cell_type", "edit_mode"), **common)
    if tool == "Read":
        return rules.files(free, does="read", read_only=config["read_only"], path="file_path", ignore=("offset", "limit", "pages"), **common)
    if tool == "Grep":
        return rules.files(free, does="read", read_only=config["read_only"], path="path", ignore=_GREP_IGNORE, **common)
    if tool == "Glob":
        return rules.files(free, does="read", read_only=config["read_only"], path="path", ignore=("pattern",), **common)
    if tool == "WebFetch":
        return rules.web(config["sites"])
    return None


TOOLS = ("Bash", "Write", "Edit", "NotebookEdit", "Read", "Grep", "Glob", "WebFetch")


_CONTENTS = {"Write": ("content",), "Edit": ("old_string", "new_string"), "NotebookEdit": ("new_source",)}
BIG_TEXT = 64 * 1024  # longer contents are kept in the log as their length and hash


def _inputs_for(tool: str, inputs: dict, folder: str) -> dict:
    """What the rule looks at and the log keeps.

    Grep and Glob with no path search the session's folder. WebFetch's prompt
    only says what to pull out of the page. The rules do not read what is
    written, and Kettle does not do the writing, so a long text is kept as its
    length and hash: enough to tell it from any other, and a log that stays small.
    """
    shaped = dict(inputs)
    for field in _CONTENTS.get(tool, ()):
        text = shaped.get(field)
        if type(text) is str and len(text) > BIG_TEXT:
            shaped[field] = f"({len(text)} characters, sha256 {hashlib.sha256(text.encode('utf-8', 'surrogatepass')).hexdigest()})"
    if tool in ("Grep", "Glob") and "path" not in shaped:
        shaped["path"] = folder
    if tool == "WebFetch":
        shaped.pop("prompt", None)
    return shaped


def _free_folder(cwd: str) -> Optional[str]:
    """The session's folder, free to read and write in, unless it is the home folder, a folder above it, or the top of the machine."""
    folder = os.path.realpath(cwd)
    home = os.path.realpath(os.path.expanduser("~"))
    if folder == os.sep or home == folder or home.startswith(folder.rstrip(os.sep) + os.sep):
        return None
    return folder


def _shown(folder: Optional[str]) -> str:
    if folder is None:
        return "no folder"
    home = os.path.realpath(os.path.expanduser("~"))
    shown = "~" + folder[len(home):] if folder == home or folder.startswith(home + os.sep) else folder
    return "".join(letter if letter.isprintable() else "?" for letter in shown)[:120]


# ---- deciding ----------------------------------------------------------------------------


class Decider:
    """Turn one PreToolUse call into the hook's answer, through one checkpoint."""

    def __init__(self, checkpoint: Any, config: dict, approver: Any = None) -> None:
        from .checkpoint import APPROVED, DENIED, HELD, RAN

        self._states = {"approved": APPROVED, "denied": DENIED, "held": HELD, "ran": RAN}
        self._cp = checkpoint
        self._gate = checkpoint.gate_for(ACTOR)
        self._config = config
        self._approver = approver
        self._wait = config["wait_seconds"]
        self._lock = threading.Lock()
        self._known: dict = {}  # (tool, folder) -> (the name in the checkpoint, its rule)

    def decide(self, call: Any, stop: Optional[threading.Event] = None) -> dict:
        try:
            return self._decide(call, stop or threading.Event())
        except Exception:
            return deny(BROKE)

    def _decide(self, call: Any, stop: threading.Event) -> dict:
        if type(call) is not dict or call.get("hook_event_name") != "PreToolUse":
            return deny(BAD_CALL)
        tool, inputs, cwd = call.get("tool_name"), call.get("tool_input"), call.get("cwd")
        if type(tool) is not str or type(inputs) is not dict:
            return deny(BAD_CALL)
        if tool not in TOOLS:
            return {}
        if type(cwd) is not str or not os.path.isabs(cwd) or "\x00" in cwd:
            return deny(NO_FOLDER)
        folder = _free_folder(cwd)
        name, rule = self._tool_for(tool, folder, os.path.realpath(cwd))
        shaped = _inputs_for(tool, inputs, folder or os.path.realpath(cwd))
        decision = self._gate.request(name, shaped)
        if decision.status == self._states["ran"]:
            return {}
        if decision.status != self._states["held"]:
            return deny(_with_why(decision.reason or BROKE, rule, shaped))
        if self._approver is None:
            return deny(NO_PHONE)
        self._approver.start()
        state = self._wait_for(decision.request_id, stop)
        if stop.is_set():
            return deny(GAVE_UP)
        if state == self._states["approved"]:
            done = self._cp.run(decision.request_id)
            return allow(APPROVED_TEXT) if done.status == self._states["ran"] else deny(done.reason or BROKE)
        return deny(DENIED_TEXT if state == self._states["denied"] else NO_ANSWER)

    def _tool_for(self, tool: str, folder: Optional[str], cwd: str) -> tuple:
        """One checkpoint tool for each tool in each folder, since the rule depends on the folder. The phone shows this name."""
        # A session with no folder free still runs its shell somewhere: that place is part of the Bash rule.
        key = (tool, folder, cwd if folder is None and tool == "Bash" else None)
        with self._lock:
            known = self._known.get(key)
            if known is None:
                name = f"{tool} in {_shown(folder or (cwd if tool == 'Bash' else None))}"
                taken = {name for name, _ in self._known.values()}
                number = 2
                while name in taken:  # two folders that show the same way
                    name = f"{tool} in {_shown(folder)} ({number})"
                    number += 1
                rule = _rule_for(tool, folder, self._config, cwd)
                self._cp.tool(name, _decided, level=rule, describe=rule.why)
                known = self._known[key] = (name, rule)
        return known

    def _wait_for(self, request_id: str, stop: threading.Event) -> str:
        """Wait for the owner a little at a time, so that a hook that gives up is noticed."""
        waited = 0.0
        while True:
            state = self._approver.wait(request_id, timeout=0.5)
            if state != self._states["held"] or stop.is_set():
                return state
            waited += 0.5
            if waited >= self._wait:
                return state


def _with_why(reason: str, rule: Any, inputs: dict) -> str:
    """The checkpoint's refusal, with the rule's own words after it, so Claude knows why."""
    try:
        why = rule.why(inputs)
    except Exception:
        return reason
    return f"{reason} {why}" if type(why) is str and why and why not in reason else reason


def _decided(**inputs: Any) -> dict:
    """What 'running' a call means here: Kettle has said yes. Claude Code runs it."""
    return {"decided": True}


# ---- the daemon --------------------------------------------------------------------------


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        decider: Decider = self.server.decider  # type: ignore[attr-defined]
        line = self.rfile.readline(MAX_CALL + 1)
        if len(line) > MAX_CALL or not line.endswith(b"\n"):
            self._reply(deny(TOO_BIG) if len(line) > MAX_CALL else deny(BAD_CALL))
            return
        try:
            call = json.loads(line)
        except ValueError:
            self._reply(deny(BAD_CALL))
            return
        if call == {"kettle": "status"}:
            self._reply({"kettle": "running"})
            return
        stop = threading.Event()
        threading.Thread(target=_watch, args=(self.request, stop), daemon=True).start()
        self._reply(decider.decide(call, stop))

    def _reply(self, answer: dict) -> None:
        try:
            self.wfile.write(json.dumps(answer).encode() + b"\n")
            self.wfile.flush()
        except OSError:
            pass  # the hook has gone


def _watch(connection: socket.socket, stop: threading.Event) -> None:
    """The hook sends one line and then only waits. If its end closes, it has given up."""
    try:
        while connection.recv(1):
            pass
    except OSError:
        pass
    stop.set()


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, path: str, decider: Decider) -> None:
        self.decider = decider
        folder = os.path.dirname(path)
        os.makedirs(folder, mode=0o700, exist_ok=True)
        if os.stat(folder).st_uid != os.getuid():
            raise ConfigError(f"{folder} belongs to someone else")
        os.chmod(folder, 0o700)
        if os.path.exists(path) or os.path.islink(path):
            if _answers(path):
                raise ConfigError("Kettle is already running for Claude Code")
            os.unlink(path)
        old = os.umask(0o177)
        try:
            super().__init__(path, _Handler)
        finally:
            os.umask(old)


def _answers(path: str) -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(CONNECT_SECONDS)
            probe.connect(path)
            probe.sendall(b'{"kettle": "status"}\n')
            return b"running" in probe.recv(MAX_REPLY)
    except OSError:
        return False


def serve(config: dict, approver_for: Optional[Callable[[Any], Any]] = None, ready: Optional[threading.Event] = None, server_box: Optional[list] = None) -> int:
    """Run the daemon until stopped. approver_for(checkpoint) makes the approver; with none, chat_id makes a TelegramApprover."""
    from .checkpoint import Checkpoint

    store = os.path.expanduser(config["store"])
    if store != ":memory:":
        os.makedirs(os.path.dirname(store), mode=0o700, exist_ok=True)
    checkpoint = Checkpoint(store, hold_seconds=config["wait_seconds"] + 60, trail=True)
    approver = approver_for(checkpoint) if approver_for is not None else None
    if approver is None and config["chat_id"] is not None:
        from .mcp import KEYCHAIN_SERVICE, TOKEN_NAME, bot_token
        from .telegram import TelegramApprover

        token = bot_token()
        if not token:
            checkpoint.close()
            raise ConfigError(f"chat_id is set, but {TOKEN_NAME} is not, and no token is in the Keychain as {KEYCHAIN_SERVICE}")
        approver = TelegramApprover(checkpoint, token=token, chat_id=config["chat_id"], approver="owner, on Telegram, through kettle.claude_code")
    server = Server(os.path.expanduser(config["socket"]), Decider(checkpoint, config, approver))
    if server_box is not None:
        server_box.append(server)
    if ready is not None:
        ready.set()
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
        try:
            os.unlink(os.path.expanduser(config["socket"]))
        except OSError:
            pass
        if approver is not None:
            approver.stop()
        checkpoint.close()
    return 0


# ---- the hook ----------------------------------------------------------------------------


def hook(stdin: Any = None, stdout: Any = None, socket_path: Optional[str] = None) -> int:
    """Read the call Claude Code gives, ask the daemon, print its answer. Always ends with 0: a deny is printed, not signalled."""
    stdin = stdin if stdin is not None else sys.stdin.buffer
    stdout = stdout if stdout is not None else sys.stdout
    answer = _ask_daemon(stdin, os.path.expanduser(socket_path or SOCKET))
    if answer:
        stdout.write(json.dumps(answer) + "\n")
        stdout.flush()
    return 0


def _ask_daemon(stdin: Any, path: str) -> dict:
    try:
        data = stdin.read(MAX_CALL + 1)
        if len(data) > MAX_CALL:
            return deny(TOO_BIG)
        call = json.loads(data)
    except (OSError, ValueError):
        return deny(BAD_CALL)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as line:
            line.settimeout(CONNECT_SECONDS)
            line.connect(path)
            line.settimeout(None)  # Claude Code's own timeout for the hook is the limit; it blocks the call when it runs out
            line.sendall(json.dumps(call).encode() + b"\n")
            reply = b""
            while not reply.endswith(b"\n"):
                part = line.recv(MAX_REPLY)
                if not part or len(reply) + len(part) > MAX_REPLY:
                    return deny(NOT_RUNNING)
                reply += part
        answer = json.loads(reply)
    except (OSError, ValueError):
        return deny(NOT_RUNNING)
    return answer if _answer_ok(answer) else deny(BROKE)


# ---- the command -------------------------------------------------------------------------


def status(socket_path: Optional[str] = None) -> bool:
    return _answers(os.path.expanduser(socket_path or SOCKET))


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kettle.claude_code", description="Put Kettle in front of Claude Code.")
    parser.add_argument("command", choices=["serve", "hook", "status", "setup", "uninstall"])
    parser.add_argument("--chat-id", type=int, help="setup: your Telegram chat id, if you know it")
    parser.add_argument("--project", help="setup, uninstall: one project's folder only, not every session")
    parser.add_argument("--config", help=f"the settings file (default {CONFIG})")
    parser.add_argument("--socket", help=f"the daemon's socket (default {SOCKET})")
    try:
        args = parser.parse_args(argv)
    except SystemExit as stop:
        return stop.code if type(stop.code) is int else 2
    if args.command == "hook":
        return hook(socket_path=args.socket)
    if args.command in ("setup", "uninstall"):
        from .claude_code_setup import for_real

        made = for_real(project=args.project)
        return made.setup(args.chat_id) if args.command == "setup" else made.uninstall()
    if args.command == "status":
        running = status(args.socket)
        print("Kettle is running for Claude Code." if running else "Kettle is not running for Claude Code.")
        return 0 if running else 1
    try:
        config = read_config(args.config)
        if args.socket:
            config["socket"] = args.socket
        return serve(config)
    except ConfigError as error:
        print(f"kettle.claude_code: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
