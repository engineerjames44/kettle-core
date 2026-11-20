"""The attack test's pretend world as an MCP server, for an agent that is a program of its own.

    python -m kettle.attacktest.world_server --socket PATH

The attack test starts the agent's program, and that program starts this, with
the path it was given in the MCP settings. This speaks MCP over its own stdin and
stdout (JSON-RPC, one message per line) and hands each tools/call to the test
over the socket. So every call lands in the run's own tool box, the same place a
function agent's tools.call goes: the checkpoint, the call limit and the world's
record all see it. This file holds no world of its own and decides nothing.

It needs no other package.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from typing import Any, Optional

from .. import __version__
from .sandbox import TOOL_SPECS

PROTOCOL = "2025-06-18"
NAME = "kettle-attack-test-world"
MAX_LINE = 1024 * 1024
LOST = "The attack test is no longer answering. Nothing was run."


def tool_list() -> list[dict]:
    return [{"name": spec.name, "description": spec.description, "inputSchema": spec.parameters} for spec in TOOL_SPECS]


class TestLine:
    """One connection to the attack test. Each call is one line out and one line back."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._line: Optional[socket.socket] = None
        self._file: Any = None

    def call(self, name: Any, inputs: Any) -> str:
        try:
            if self._line is None:
                self._line = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self._line.connect(self._path)
                self._file = self._line.makefile("rb")
            self._line.sendall(json.dumps({"name": name, "inputs": inputs}).encode() + b"\n")
            reply = self._file.readline(MAX_LINE + 1)
            text = json.loads(reply)["text"]
        except (OSError, ValueError, KeyError, TypeError):
            return LOST
        return text if type(text) is str else LOST


def answer(message: Any, line: TestLine) -> Optional[dict]:
    """The reply to one message, or None for a notification."""
    if type(message) is not dict or "id" not in message:
        return None
    ident, method = message["id"], message.get("method")
    if method == "initialize":
        asked = (message.get("params") or {}).get("protocolVersion") if type(message.get("params")) is dict else None
        result = {
            "protocolVersion": asked if type(asked) is str else PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": NAME, "version": __version__},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": tool_list()}
    elif method == "tools/call":
        params = message.get("params") if type(message.get("params")) is dict else {}
        arguments = params.get("arguments")
        text = line.call(params.get("name"), arguments if type(arguments) is dict else {})
        result = {"content": [{"type": "text", "text": text}]}
    else:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": f"no such method: {method}"}}
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def serve(path: str, app_in: Any = None, app_out: Any = None) -> int:
    app_in = app_in if app_in is not None else sys.stdin.buffer
    app_out = app_out if app_out is not None else sys.stdout.buffer
    line = TestLine(path)
    while True:
        raw = app_in.readline(MAX_LINE + 1)
        if not raw:
            return 0
        try:
            message = json.loads(raw)
        except ValueError:
            continue
        reply = answer(message, line)
        if reply is not None:
            app_out.write(json.dumps(reply).encode() + b"\n")
            app_out.flush()


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kettle.attacktest.world_server", description="The attack test's pretend world as an MCP server.")
    parser.add_argument("--socket", required=True, help="the path the attack test gave in the MCP settings")
    args = parser.parse_args(argv)
    return serve(args.socket)


if __name__ == "__main__":
    raise SystemExit(main())
