"""Break --agent-command, --claude-code and the kettle command on purpose, one way at a time, and see whether the tests notice.

    .venv/bin/python checks/break_command_agent.py

An agent that is a program runs as you and can cost money, so the breaks here are
ways it could be started without --yes, be given more than the pretend world, have
its calls miss the run's own tool box (and so the checkpoint and the count), or
leave its folder open or behind. The tests use a pretend agent program, and `claude`
is never on their PATH.
"""

from _runner import rep, run

TESTS = ["test_command_agent.py", "test_kettle_command.py", "test_the_tests_stay_on_this_machine.py"]
C, W, CLI, ONE = "attacktest/command_agent.py", "attacktest/world_server.py", "attacktest/__main__.py", "__main__.py"

MUTANTS = [
    # started only on a yes
    ("a program is started without --yes", CLI, rep('        if not args.yes:\n            print(f"This would start', '        if False:\n            print(f"This would start')),
    ("a timeout of 0 is taken", CLI, rep("        if not args.agent_timeout > 0:", "        if False:")),
    # only the pretend world
    ("Claude Code keeps its own tools", C, rep('    "--tools", "",\n', "")),
    ("Claude Code also loads your other MCP servers", C, rep('"--mcp-config", MCP_CONFIG, "--strict-mcp-config",', '"--mcp-config", MCP_CONFIG,')),
    ("Claude Code is not limited to the world's tools", C, rep('"--allowedTools", f"mcp__{SERVER}__*",', '"--allowedTools", "*",')),
    ("the server can import from the program's folder", C, rep('"args": ["-P", "-m", "kettle.attacktest.world_server"', '"args": ["-m", "kettle.attacktest.world_server"')),
    # every call goes to the run's own tool box
    ("a call is answered without reaching the tool box", W, rep("        text = line.call(params.get(\"name\"), arguments if type(arguments) is dict else {})", '        text = "done"')),
    ("the server lists no tools", W, rep('    return [{"name": spec.name, "description": spec.description, "inputSchema": spec.parameters} for spec in TOOL_SPECS]', "    return []")),
    ("the server does not say it has tools", W, rep('"capabilities": {"tools": {}},', '"capabilities": {},')),
    ("the server answers a notification", W, rep('    if type(message) is not dict or "id" not in message:\n        return None', "    if type(message) is not dict:\n        return None")),
    ("a lost test reads as done", W, rep('LOST = "The attack test is no longer answering. Nothing was run."', 'LOST = "done"')),
    ("bad inputs reach the tool box as they are", W, rep("arguments if type(arguments) is dict else {}", "arguments")),
    ("the task is not sent on stdin", C, rep("input=task.encode() if asks_on_stdin else None,", "input=None,")),
    # the program's folder
    ("the folder can be read by others", C, rep("os.chmod(folder, 0o700)", "os.chmod(folder, 0o755)")),
    ("the socket can be used by others", C, rep("        os.chmod(path, 0o600)\n", "")),
    ("the folder is left behind", C, rep("            shutil.rmtree(folder, ignore_errors=True)", "            pass")),
    ("the program starts in the folder with the settings", C, rep("cwd=work,", "cwd=folder,")),
    # a program that fails
    ("a program that never ends is waited for", C, rep("                    timeout=self.timeout,\n", "                    timeout=None if self.timeout < 5 else self.timeout,\n")),
    ("a failed program with no reply counts as a reply", C, rep("            if done.returncode != 0:", "            if False:")),
    ("a failed program that printed something counts as a reply", C, rep("            if done.returncode != 0:", "            if done.returncode != 0 and not reply:")),
    ("a missing program stops the whole test", C, rep('            except FileNotFoundError:\n                raise CommandError(f"{words[0]} was not found") from None\n', "")),
    # the one command
    ("kettle loses a module's exit code", ONE, rep("    return code if type(code) is int else (0 if code is None else 1)", "    return 0")),
    ("kettle drops the module's options", ONE, rep("        code = module.main(rest)", "        code = module.main([])")),
    ("kettle with no command says all is well", ONE, rep("        return 0 if argv else 2", "        return 0")),
]

if __name__ == "__main__":
    run(MUTANTS, TESTS)
