"""An agent that is a program of its own, such as Claude Code, tested with the pretend world as an MCP server.

    python -m kettle.attacktest --agent-command 'my-agent --task {task} --mcp {mcp_config}' --yes
    python -m kettle.attacktest --claude-code --yes

For each run, the program is started once in an empty folder. In its arguments,
{task} becomes the owner's task and {mcp_config} the path of an MCP settings file
(the {"mcpServers": ...} shape that Claude Desktop, Claude Code and Cursor read)
with one server, "world", which is the run's pretend world. With no {task}, the task
is sent on the program's stdin. What the program prints is its reply, if it ends
with 0. A program that ends with anything else is an error in that run, and what it
ran before that still counts.

Every tool call the program makes through that server lands in the run's own tool
box, so the checkpoint, the call limit and the world's record work the same as for
a function agent. Whatever else the program does is not seen: if it has tools of
its own (a shell, files, the web), it can use them, and the test cannot count them.
So give it only the world's tools, the way --claude-code does.

The program runs as you, with your environment, so it can use your logins and
cost you money. That is why it needs --yes.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from typing import Any, Optional, Sequence

TASK, MCP_CONFIG = "{task}", "{mcp_config}"
SERVER = "world"
CLAUDE_CODE = [
    "claude", "-p", TASK,
    "--mcp-config", MCP_CONFIG, "--strict-mcp-config",
    "--tools", "",
    "--allowedTools", f"mcp__{SERVER}__*",
]  # fmt: skip
MAX_LINE = 1024 * 1024
MAX_REPLY = 100_000


class CommandError(RuntimeError):
    """The program could not be run, or did not finish."""


def parse(command: str) -> list[str]:
    """The program and its arguments, split the way a shell would split them, with nothing run through a shell."""
    words = shlex.split(command)
    if not words:
        raise ValueError("--agent-command is empty")
    return words


def claude_code(model: Optional[str] = None) -> list[str]:
    return CLAUDE_CODE + (["--model", model] if model else [])


class _World(threading.Thread):
    """The test's end of the line: each line in is one tool call, and each line out is its text."""

    def __init__(self, path: str, tools: Any) -> None:
        super().__init__(daemon=True)
        self._tools = tools
        self._listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._listener.bind(path)
        os.chmod(path, 0o600)
        self._listener.listen(4)
        self._stopped = threading.Event()

    def run(self) -> None:
        while not self._stopped.is_set():
            try:
                connection, _ = self._listener.accept()
            except OSError:
                return
            with connection, connection.makefile("rb") as lines:
                for raw in iter(lambda: lines.readline(MAX_LINE + 1), b""):
                    try:
                        call = json.loads(raw)
                        text = self._tools.call(call["name"], call["inputs"])
                    except (ValueError, KeyError, TypeError):
                        text = "The call could not be read. Nothing was run."
                    try:
                        connection.sendall(json.dumps({"text": text}).encode() + b"\n")
                    except OSError:
                        break

    def stop(self) -> None:
        self._stopped.set()
        try:
            self._listener.close()
        except OSError:
            pass


class CommandAgent:
    """agent(task, tools) -> reply, by running a program with the pretend world as its MCP server."""

    def __init__(self, command: Sequence[str], timeout: float = 600.0, python: str = sys.executable) -> None:
        if not command:
            raise ValueError("no command")
        self.command = list(command)
        self.timeout = timeout
        self.python = python
        self.settings = {"agent_command": shlex.join(self.command), "timeout_seconds": timeout}

    def arguments(self, task: str, mcp_config: str) -> list[str]:
        return [word.replace(TASK, task).replace(MCP_CONFIG, mcp_config) for word in self.command]

    def __call__(self, task: str, tools: Any) -> str:
        # A short folder: a socket's path has a length limit (about 100 characters on a Mac).
        folder = tempfile.mkdtemp(prefix="kw", dir="/tmp" if os.path.isdir("/tmp") else None)
        world = None
        try:
            os.chmod(folder, 0o700)
            path = os.path.join(folder, "w.sock")
            world = _World(path, tools)
            world.start()
            config = os.path.join(folder, "mcp.json")
            # -P: nothing is imported from the folder the server starts in, which the program may have written to.
            server = {"command": self.python, "args": ["-P", "-m", "kettle.attacktest.world_server", "--socket", path], "env": {"PYTHONPATH": _package_root()}}
            with open(config, "w", encoding="utf-8") as handle:
                json.dump({"mcpServers": {SERVER: server}}, handle)
            work = os.path.join(folder, "work")
            os.mkdir(work)
            words = self.arguments(task, config)
            asks_on_stdin = not any(TASK in word for word in self.command)
            try:
                done = subprocess.run(
                    words,
                    cwd=work,
                    input=task.encode() if asks_on_stdin else None,
                    stdin=None if asks_on_stdin else subprocess.DEVNULL,
                    capture_output=True,
                    timeout=self.timeout,
                )
            except FileNotFoundError:
                raise CommandError(f"{words[0]} was not found") from None
            except subprocess.TimeoutExpired:
                raise CommandError(f"the program did not finish in {self.timeout:g} seconds") from None
            reply = done.stdout.decode("utf-8", "replace").strip()[:MAX_REPLY]
            if done.returncode != 0:
                # A program that failed has no reply to judge, whatever it printed first. What it ran still counts.
                error = (done.stderr.decode("utf-8", "replace").strip() or reply)[-500:]
                raise CommandError(f"the program ended with {done.returncode}" + (f": {error}" if error else ""))
            return reply
        finally:
            if world is not None:
                world.stop()
            shutil.rmtree(folder, ignore_errors=True)


def _package_root() -> str:
    """The folder kettle is imported from, so the server runs the same code as the test."""
    import kettle

    return os.path.dirname(os.path.dirname(os.path.abspath(kettle.__file__)))
