"""A pretend agent program, for the tests of --agent-command. No model: a fixed script.

    python tests/pretend_mcp_agent.py --mcp CONFIG --cases fraud --mode fooled [--task TASK]

It reads the MCP settings it was given, starts the "world" server from them, and
talks MCP to it the way an MCP app would. Then it finds the case whose task it
was given (from --task, or from stdin with no --task) and acts like the stand-in
agent named by --mode (with --case, the case is named, since an attack and its
normal job can share a task): careful does the owner's job, fooled does what the trick
text wants as well. So it should get the same counts as those stand-ins do when
they are called as functions.

Other modes: flood makes 50 calls, odd calls a tool that does not exist and sends
inputs that do not fit, silent prints nothing and fails, sleep never ends, and
crash prints a reply and then fails,
marker only writes a file, to show the program was started at all.
"""

import argparse
import json
import subprocess
import sys
import time

from kettle.attacktest.cases import load_cases
from kettle.attacktest.standins import careful, fooled


class Over:
    """tools.call, over MCP."""

    def __init__(self, server):
        self.server, self.next_id, self.seen = server, 0, []

    def ask(self, method, params=None):
        self.next_id += 1
        self.server.stdin.write((json.dumps({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}}) + "\n").encode())
        self.server.stdin.flush()
        return json.loads(self.server.stdout.readline())

    def call(self, name, inputs):
        reply = self.ask("tools/call", {"name": name, "arguments": inputs})
        text = reply["result"]["content"][0]["text"]
        self.seen.append(text)
        return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mcp")
    parser.add_argument("--task")
    parser.add_argument("--cases", default="starter")
    parser.add_argument("--mode", default="careful")
    parser.add_argument("--marker")
    parser.add_argument("--case", help="the case id; with none, the first case with this task")
    args = parser.parse_args()
    if args.mode == "marker":
        open(args.marker, "w").write("started")
        print("done")
        return 0
    if args.mode == "silent":
        return 3
    if args.mode == "crash":
        print("I paid the invoice and sent the numbers.")
        print("something broke", file=sys.stderr)
        return 4
    if args.mode == "sleep":
        time.sleep(60)
        return 0
    task = args.task if args.task is not None else sys.stdin.read()
    config = json.load(open(args.mcp))["mcpServers"]["world"]
    server = subprocess.Popen([config["command"], *config["args"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env={**__import__("os").environ, **config.get("env", {})})
    tools = Over(server)
    hello = tools.ask("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "pretend", "version": "0"}})
    assert hello["result"]["capabilities"] == {"tools": {}}
    listed = {tool["name"] for tool in tools.ask("tools/list")["result"]["tools"]}
    if args.mode == "flood":
        for _ in range(50):
            tools.call("list_emails", {})
        print("flooded")
        return 0
    if args.mode == "odd":
        print(json.dumps([tools.call("no_such_tool", {}), tools.call("read_email", {"nope": 1})]))
        return 0
    case = next(case for case in load_cases(args.cases).cases() if (case.id == args.case if args.case else case.task == task))
    assert case.task == task, "the program was not given the case's own task"
    agent = fooled(case) if args.mode == "fooled" else careful(case)
    reply = agent(task, tools)
    server.stdin.close()
    server.wait(5)
    print(reply)
    print("tools:", ",".join(sorted(listed)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
