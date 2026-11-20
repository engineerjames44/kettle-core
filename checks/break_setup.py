"""Break python -m kettle.setup on purpose, one way at a time, and see whether the tests notice.

    .venv/bin/python checks/break_setup.py

kettle.setup changes an app's MCP settings, so the breaks here are ways it could lose
or spread what was in them (the server's env, which may hold secrets), make Kettle
looser than it says, or fail to put things back. The tests use settings files in a
temporary folder and never the real Keychain.
"""

from _runner import rep, run

TESTS = ["test_setup.py", "test_the_tests_stay_on_this_machine.py"]
S, M = "setup.py", "mcp.py"

MUTANTS = [
    ("the server's env is dropped when it is wrapped", S, rep('new = {key: value for key, value in entry.items() if key not in ("command", "args")}', "new = {}")),
    ("the server's env is copied into the rules file", S, rep('original = {"command": entry["command"], "args": list(entry.get("args", []))}', "original = dict(entry)")),
    ("the rules file can be read by anyone", S, rep("os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)", "os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)")),
    ("no copy is kept of the settings it changes", S, rep("        shutil.copy2(path, path.with_name(", "        (path, path.with_name(")),
    ("a server Kettle is already in front of is wrapped again", S, rep("if not wrapped(servers[usable[number - 1]])]", "]")),
    ("every tool is free unless named", S, rep("""lines += ["[tools]", 'default = "ask"']""", """lines += ["[tools]", 'default = "free"']""")),
    ("the tools found are not written down", S, rep("""        lines += [f"# {json.dumps(name)} = \\"free\\"" for name in tools]\n""", "")),
    ("the phone's chat is not written down", S, rep('lines += ["[approver]", f"chat_id = {chat_id}"]', 'lines += ["[approver]"]')),
    ("undo puts back a server that was changed by hand since", S, rep("        if not wrapped(entry) or str(rules) not in [str(arg) for arg in entry.get(\"args\", [])]:\n            continue", "        if entry is None:\n            continue")),
    ("undo drops the server's env", S, rep('data["mcpServers"][server] = {**{key: value for key, value in entry.items() if key not in ("command", "args")}, **original}', 'data["mcpServers"][server] = original')),
    ("undo leaves the rules file in place", S, rep('        rules.rename(rules.with_name(rules.name + ".undone"))\n', "")),
    ("a server that never answers is waited for", S, rep("    timer.start()\n", "")),
    ("one broken settings file stops the undo", S, rep("        except (OSError, ValueError):\n            say(f\"{path} could not be read as JSON", "        except ZeroDivisionError:\n            say(f\"{path} could not be read as JSON")),
    ("two names that read alike share a rules file", S, rep('return kettle_dir / f"{safe_name(app)}-{safe_name(server)}-{tag}.toml"', 'return kettle_dir / f"{safe_name(server)}.toml"')),
    ("a wrong number is taken", S, rep("if answer.isdigit() and 1 <= int(answer) <= most:", "if answer.isdigit():")),
    ("the Keychain step is not said", S, rep('            say(f"    security add-generic-password -U -a kettle -s {KEYCHAIN_SERVICE} -w")\n', "")),
    ("the Keychain is asked before the environment", M, rep("    if token or platform != \"darwin\":\n        return token", "    if platform != \"darwin\":\n        return token")),
    ("the Keychain is asked off a Mac", M, rep('if token or platform != "darwin":', "if token:")),
    ("a Keychain that fails gives what it printed", M, rep('return found.stdout.strip() if found.returncode == 0 else ""', "return found.stdout.strip()")),
]

if __name__ == "__main__":
    run(MUTANTS, TESTS)
