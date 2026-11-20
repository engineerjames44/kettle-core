"""Break kettle.mcp on purpose, one way at a time, and see whether the tests notice.

    .venv/bin/python checks/break_mcp.py

kettle.mcp stands between an MCP app and an MCP server, so the breaks here are ways a
tool call could reach the server without the checkpoint, or run without the owner's
yes; ways the box could lose what it says; and ways the config could be read more
loosely than it is written. The tests talk to a pretend MCP server on this machine.
"""

from _runner import rep, run

TESTS = ["test_mcp.py", "test_the_tests_stay_on_this_machine.py"]
M = "mcp.py"

MUTANTS = [
    # the call goes through the checkpoint
    ("a tool call goes straight to the server", M, rep('message.get("method") == "tools/call" and "id" in message:', 'False:')),
    ("a refused call goes to the server anyway", M, rep("        if decision.status != HELD:\n            return _error_result(decision.reason)\n", "        if decision.status != HELD:\n            return self._ask_server(name, arguments)\n")),
    ("with no phone a held call goes to the server", M, rep("            return _error_result(NO_APPROVER)\n", "            return self._ask_server(name, arguments)\n")),
    ("a held call runs whatever the owner says", M, rep("        if state == APPROVED:\n            done = self._cp.run(", "        if True:\n            self._cp.approve(decision.request_id, self._cp.status(decision.request_id)['fingerprint'], 'kettle.mcp')\n            done = self._cp.run(")),
    ("a no is answered as a yes would be", M, rep("return _error_result(DENIED_TEXT if state == DENIED else NO_ANSWER)", 'return {"content": [{"type": "text", "text": "done"}]}')),
    # what the server lists, and how each tool is set
    ("every listed tool is free", M, rep("level, describe, watch = level_for(name, self._tools)", "level, describe, watch = FREE, None, ()")),
    ("the tools the server lists are not learned", M, rep("            if listing:\n                self._learn(message.get(\"result\"))\n", "")),
    ("the watched inputs are not passed on", M, rep("watch=list(watch))", "watch=[])")),
    ("a rule's own words are not put in the box", M, rep("return rule, rule.why, tuple(watch)", "return rule, None, tuple(watch)")),
    ("the box does not say who asked", M, rep("self._gate = checkpoint.gate_for(ACTOR)", "self._gate = checkpoint.gate")),
    ("ask means free", M, rep('LEVELS = {"free": FREE, "ask": NEEDS_YES, "never": NEVER}', 'LEVELS = {"free": FREE, "ask": FREE, "never": NEVER}')),
    ("never means ask", M, rep('LEVELS = {"free": FREE, "ask": NEEDS_YES, "never": NEVER}', 'LEVELS = {"free": FREE, "ask": NEEDS_YES, "never": NEEDS_YES}')),
    ("with no default, a tool the config does not name is free", M, rep('entry = tools.get(name, tools.get("default", "ask"))', 'entry = tools.get(name, tools.get("default", "free"))')),
    # the app gives up
    ("a cancelled call is still waited for", M, rep("            if stop is not None:\n                stop.set()\n", "            if stop is not None:\n                pass\n")),
    ("a cancelled call is answered", M, rep("        if gave_up is not None and gave_up.is_set():\n            return  #", "        if False:\n            return  #")),
    ("a cancelled call runs if the owner says yes later", M, rep("        if stop.is_set():\n            return _error_result(GAVE_UP)\n", "")),
    # the proxy's own talk with the server
    ("the server's answers to the proxy also go to the app", M, rep("                ours[\"done\"].set()\n                return\n", "                ours[\"done\"].set()\n")),
    ("the app can use the proxy's own ids", M, rep('if type(message) is dict and type(message.get("id")) is str and message["id"].startswith("kettle-"):', "if False:")),
    ("an error from the server comes back as a result", M, rep("            raise RuntimeError(FAILED)", '            return {"content": [{"type": "text", "text": "done: fails"}]}')),
    # the config
    ("any level word is taken", M, rep("        if entry not in LEVELS:\n            raise ConfigError(", "        if False:\n            raise ConfigError(")),
    ("any rule name is taken", M, rep("    if kind not in RULES:\n        raise ConfigError(", "    if kind not in RULES and False:\n        raise ConfigError(")),
    ("a level table may carry anything else", M, rep("if options or level not in LEVELS:", "if level not in LEVELS:")),
    ("watch may be one name instead of a list", M, rep("if type(watch) is not list or not all(type(item) is str for item in watch):", "if not all(type(item) is str for item in watch):")),
    ("a rule's bad options pass", M, rep("    except (TypeError, ValueError) as error:\n        raise ConfigError(", "    except ZeroDivisionError as error:\n        raise ConfigError(")),
    ("the command line goes on after a config mistake", M, rep('        print(f"kettle.mcp: {error}", file=sys.stderr)\n        return 2', '        print(f"kettle.mcp: {error}", file=sys.stderr)\n        return 0')),
]

if __name__ == "__main__":
    run(MUTANTS, TESTS)
