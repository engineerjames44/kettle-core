"""Break Kettle-for-Claude-Code one way at a time, and see whether its tests notice.

    .venv/bin/python checks/break_claude_code.py          every break (about a minute)
    .venv/bin/python checks/break_claude_code.py hook     only the breaks with "hook" in their name

The breaks that matter most would let a risky call run with no yes: a dead
daemon read as "no decision", an answer the hook does not check, a yes that
skips the last look, a hook that gave up still getting its call run, Kettle's
own folder left open, the home folder made free.

Only tests/test_claude_code.py and tests/test_claude_code_setup.py are run.
"""

from _runner import rep, run

TESTS = ["test_claude_code.py", "test_claude_code_setup.py"]

C = "claude_code.py"
S = "claude_code_setup.py"

MUTANTS = [
    ("hook: a dead daemon is no decision", C, rep("    except (OSError, ValueError):\n        return deny(NOT_RUNNING)\n    return answer", "    except (OSError, ValueError):\n        return {}\n    return answer")),
    ("hook: the daemon's answer is not checked", C, rep("    return answer if _answer_ok(answer) else deny(BROKE)\n", "    return answer\n")),
    ("hook: any decision passes the check", C, rep('        and inner["permissionDecision"] in ("allow", "deny")\n', "")),
    ("hook: more than the decision passes the check", C, rep('    if type(answer) is not dict or set(answer) != {"hookSpecificOutput"}:\n', "    if type(answer) is not dict:\n")),
    ("hook: a call it cannot read is no decision", C, rep("    except (OSError, ValueError):\n        return deny(BAD_CALL)\n", "    except (OSError, ValueError):\n        return {}\n")),
    ("hook: a reply of any size is read", C, rep("                if not part or len(reply) + len(part) > MAX_REPLY:\n", "                if not part:\n")),
    ("hook: a big call is sent anyway", C, rep("        if len(data) > MAX_CALL:\n            return deny(TOO_BIG)\n", "")),
    ("decide: a yes runs without the last look", C, rep('            return allow(APPROVED_TEXT) if done.status == self._states["ran"] else deny(done.reason or BROKE)\n', "            return allow(APPROVED_TEXT)\n")),
    ("decide: no answer is a yes", C, rep("        return deny(DENIED_TEXT if state == self._states[\"denied\"] else NO_ANSWER)\n", "        return deny(DENIED_TEXT) if state == self._states[\"denied\"] else allow(APPROVED_TEXT)\n")),
    ("decide: a hook that gave up still gets a decision", C, rep("        if stop.is_set():\n            return deny(GAVE_UP)\n", "")),
    ("decide: no phone is no decision", C, rep("        if self._approver is None:\n            return deny(NO_PHONE)\n", "        if self._approver is None:\n            return {}\n")),
    ("decide: a refusal is no decision", C, rep('        if decision.status != self._states["held"]:\n            return deny(_with_why(decision.reason or BROKE, rule, shaped))\n', '        if decision.status != self._states["held"]:\n            return {}\n')),
    ("decide: a refusal does not say why", C, rep("            return deny(_with_why(decision.reason or BROKE, rule, shaped))\n", "            return deny(decision.reason or BROKE)\n")),
    ("decide: a failure inside is no decision", C, rep("        except Exception:\n            return deny(BROKE)\n", "        except Exception:\n            return {}\n")),
    ("decide: a call that is not PreToolUse is looked at", C, rep(' or call.get("hook_event_name") != "PreToolUse":\n', ":\n")),
    ("decide: a relative folder is taken", C, rep(" or not os.path.isabs(cwd) or", " or")),
    ("decide: every folder shares one tool", C, rep("            known = self._known.get(key)\n", "            known = next(iter(v for k, v in self._known.items() if k[0] == tool), None)\n")),
    ("tools: the shell reads anywhere", C, rep(', folders=free + config["read_only"], base=folder or cwd or os.path.expanduser("~"))', ")")),
    ("tools: a home session's shell runs in the home folder whatever its place", C, rep('        key = (tool, folder, cwd if folder is None and tool == "Bash" else None)\n', "        key = (tool, folder, None)\n")),
    ("folders: the home folder is made free", C, rep("    if folder == os.sep or home == folder or home.startswith(folder.rstrip(os.sep) + os.sep):\n        return None\n", "")),
    ("folders: Kettle's own folder is not protected", C, rep('    common = {"base": folder, "protect": [KETTLE_HOME]}\n', '    common = {"base": folder}\n')),
    ("folders: extra folders are left out", C, rep('    free = ([folder] if folder else []) + config["folders"]\n', '    free = [folder] if folder else []\n')),
    ("tools: the sandbox switch is ignored", C, rep('_BASH_IGNORE = ("description", "timeout", "run_in_background")\n', '_BASH_IGNORE = ("description", "timeout", "run_in_background", "dangerouslyDisableSandbox")\n')),
    ("tools: Edit ignores any input", C, rep('ignore=("old_string", "replace_all")', 'ignore=("old_string", "replace_all", "surprise")')),
    ("tools: Grep with no path gets none", C, rep('    if tool in ("Grep", "Glob") and "path" not in shaped:\n', "    if False:\n")),
    ("tools: WebFetch's prompt is looked at", C, rep('        shaped.pop("prompt", None)\n', "        pass\n")),
    ("tools: a long write is kept whole", C, rep("        if type(text) is str and len(text) > BIG_TEXT:\n", "        if False:\n")),
    ("tools: a long write is kept as its length only", C, rep(", sha256 {hashlib.sha256(text.encode('utf-8', 'surrogatepass')).hexdigest()})", ")")),
    ("daemon: the socket is open to others", C, rep("        old = os.umask(0o177)\n", "        old = os.umask(0o022)\n")),
    ("daemon: the folder keeps loose rights", C, rep("        os.chmod(folder, 0o700)\n", "")),
    ("daemon: a running daemon is pushed aside", C, rep('            if _answers(path):\n                raise ConfigError("Kettle is already running for Claude Code")\n', "")),
    ("daemon: a hook that hangs up is not watched", C, rep("        threading.Thread(target=_watch, args=(self.request, stop), daemon=True).start()\n", "")),
    ("daemon: a big call is read anyway", C, rep("        if len(line) > MAX_CALL or not line.endswith(b\"\\n\"):\n", "        if not line.endswith(b\"\\n\") and len(line) <= MAX_CALL:\n")),
    ("settings: wait_seconds is not bounded", C, rep("    if not 5 <= wait <= 3600:\n", "    if False:\n")),
    ("settings: an unknown setting is taken", C, rep("        if kind is None:\n            raise", "        if kind is None:\n            continue\n            raise")),
    ("settings: true is taken as a number", C, rep("        if type(value) is bool or not isinstance(value, kind):\n", "        if not isinstance(value, kind):\n")),
    ("command: status says running when it is not", C, rep('        return 0 if running else 1\n', "        return 0\n")),
    ("setup: the hook goes in before the daemon runs", S, rep("""        if self.platform == "darwin":
            if not self._agent():""", """        self._hook(wait)
        if self.platform == "darwin":
            if not self._agent():""")),
    ("setup: a failed hook does not block", S, rep(', "onFailure": "block"}', "}")),
    ("setup: the hook waits no longer than the phone", S, rep('"timeout": int(wait) + 60', '"timeout": int(wait)')),
    ("setup: the matcher leaves tools out", S, rep('{"matcher": "*", "hooks"', '{"matcher": "Bash", "hooks"')),
    ("setup: any answer is a yes", S, rep('.strip().lower() == "yes"', '.strip().lower() != "no"')),
    ("setup: no answer is a yes", S, rep("        except EOFError:\n            return False\n", "        except EOFError:\n            return True\n")),
    ("setup: the settings file is open to others", S, rep("def _write_atomically(path: Path, text: str, mode: int = 0o600) -> None:", "def _write_atomically(path: Path, text: str, mode: int = 0o644) -> None:")),
    ("setup: Kettle's folder keeps loose rights", S, rep("        os.chmod(self.config.parent, 0o700)\n", "")),
    ("setup: the old settings are not kept", S, rep("            shutil.copy2(self.settings, self._kept())\n", "")),
    ("setup: a daemon that never answers still gets the hook", S, rep('        self.say(f"The daemon did not answer. Its log is {self.home / \'.kettle\' / \'claude-code.log\'}.")\n        return False\n', '        return True\n')),
    ("setup: a hook is added twice", S, rep("            if has_hook(current):\n", "            if False:\n")),
    ("setup: a settings file it cannot read is written over", S, rep("    data = json.loads(path.read_text(encoding=\"utf-8\"))\n", "    try:\n        data = json.loads(path.read_text(encoding=\"utf-8\"))\n    except ValueError:\n        data = {}\n")),
    ("setup: the old settings file is written over", S, rep("    made = json.loads(json.dumps(settings))\n    hooks = made.setdefault", "    made = {}\n    hooks = made.setdefault")),
    ("setup: the source folder is left out of the hook", S, rep('    return f"PYTHONPATH={shlex.quote(root)} {command}" if root else command\n', "    return command\n")),
    ("setup: the python path is not quoted", S, rep('    command = f"{shlex.quote(python)} {MARK}"\n', '    command = f"{python} {MARK}"\n')),
    ("setup: a chat that cannot be found goes on", S, rep('                self.say(f"No chat id: {error}.")\n                return False\n', '                self.say(f"No chat id: {error}.")\n                chat_id = 0\n')),
    ("uninstall: the daemon stops before the hook comes out", S, rep("""        if has_hook(current):
            if not self._yes(f"Take the Kettle hook out of {self.settings}?"):""", """        self.run(["launchctl", "bootout", f"gui/{self.uid}/{LABEL}"], capture_output=True)
        if has_hook(current):
            if not self._yes(f"Take the Kettle hook out of {self.settings}?"):""")),
    ("uninstall: other hooks are taken out too", S, rep("            handlers = [handler for handler in group[\"hooks\"] if not _ours(handler)]\n", "            handlers = []\n")),
    ("uninstall: the log is deleted", S, rep("            self.plist.unlink()\n", "            self.plist.unlink()\n            shutil.rmtree(self.home / \".kettle\", ignore_errors=True)\n")),
]

run(MUTANTS, TESTS)
