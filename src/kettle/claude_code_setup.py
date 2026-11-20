"""Set up, and take away, Kettle for Claude Code. Nothing is changed without a typed yes.

    python -m kettle.claude_code setup [--chat-id N] [--project DIR]
    python -m kettle.claude_code uninstall [--project DIR]

With --project, the hook goes in that project's .claude/settings.local.json
(personal, not shared) and covers only Claude Code sessions there. Without it,
it goes in ~/.claude/settings.json and covers every session.

setup, in this order:

 1. The bot token must already be in the Keychain (service kettle-telegram) or
    in KETTLE_TELEGRAM_TOKEN. It is never typed here and never written to a file.
 2. ~/.kettle/claude-code.toml is written (mode 0600) with your chat id, found
    the way `python -m kettle.telegram` finds it, unless the file is there already.
 3. The daemon is made a login item (a launchd agent) and started, on your yes.
 4. Only then is the hook added to ~/.claude/settings.json, on your yes, with
    the old file kept beside it. The daemon comes first so that there is no
    moment when the hook is there and nothing answers it.

uninstall takes the hook out first and then stops the daemon, for the same
reason. ~/.kettle stays: its log is the record of what was asked and answered.
"""

from __future__ import annotations

import json
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional

LABEL = "si.kettlelabs.claude-code"
MARK = "-m kettle.claude_code hook"
KEYCHAIN_HINT = "security add-generic-password -a kettle -s kettle-telegram -w"

CONFIG_TEXT = """# Kettle for Claude Code. Every line but chat_id is optional.
chat_id = {chat_id}
wait_seconds = {wait}                 # how long a risky call waits for your phone

# allow = ["pytest", "npm test"]      # shell commands that run free
# folders = ["~/Projects/shared"]     # more folders where reading and writing are free
# read_only = ["~/Documents/specs"]   # more folders where reading is free
# sites = ["docs.python.org"]         # sites WebFetch may read without asking
"""


def source_root() -> Optional[str]:
    """The folder to put on PYTHONPATH when Kettle runs from its source, not from an install."""
    import kettle

    root = Path(kettle.__file__).resolve().parent.parent
    return None if "site-packages" in root.parts else str(root)


def hook_command(python: str, root: Optional[str]) -> str:
    command = f"{shlex.quote(python)} {MARK}"
    return f"PYTHONPATH={shlex.quote(root)} {command}" if root else command


def hook_entry(command: str, wait: float) -> dict:
    """One matcher group for every tool. onFailure block: a hook that crashes or runs out of time blocks the call."""
    return {"matcher": "*", "hooks": [{"type": "command", "command": command, "timeout": int(wait) + 60, "onFailure": "block"}]}


def _ours(handler: Any) -> bool:
    return type(handler) is dict and type(handler.get("command")) is str and MARK in handler["command"]


def has_hook(settings: dict) -> bool:
    groups = settings.get("hooks", {}).get("PreToolUse", []) if type(settings.get("hooks")) is dict else []
    return any(_ours(handler) for group in groups if type(group) is dict for handler in group.get("hooks", []) if type(group.get("hooks")) is list)


def add_hook(settings: dict, entry: dict) -> dict:
    """A copy of the settings with the hook added, every other line as it was."""
    made = json.loads(json.dumps(settings))
    hooks = made.setdefault("hooks", {})
    if type(hooks) is not dict:
        raise ValueError('"hooks" in the settings is not a table')
    groups = hooks.setdefault("PreToolUse", [])
    if type(groups) is not list:
        raise ValueError('"hooks.PreToolUse" in the settings is not a list')
    groups.append(entry)
    return made


def remove_hook(settings: dict) -> dict:
    """A copy of the settings with every Kettle hook taken out, and any group or table it leaves empty."""
    made = json.loads(json.dumps(settings))
    hooks = made.get("hooks")
    if type(hooks) is not dict or type(hooks.get("PreToolUse")) is not list:
        return made
    kept = []
    for group in hooks["PreToolUse"]:
        if type(group) is dict and type(group.get("hooks")) is list:
            handlers = [handler for handler in group["hooks"] if not _ours(handler)]
            if not handlers and group["hooks"]:
                continue
            group = {**group, "hooks": handlers}
        kept.append(group)
    if kept:
        hooks["PreToolUse"] = kept
    else:
        del hooks["PreToolUse"]
    if not hooks:
        del made["hooks"]
    return made


def agent_plist(python: str, root: Optional[str], home: Path) -> bytes:
    log = str(home / ".kettle" / "claude-code.log")
    agent: dict = {
        "Label": LABEL,
        "ProgramArguments": [python, "-m", "kettle.claude_code", "serve"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }
    if root:
        agent["EnvironmentVariables"] = {"PYTHONPATH": root}
    return plistlib.dumps(agent)


def _read_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if type(data) is not dict:
        raise ValueError("the settings file does not hold a table")
    return data


def _write_atomically(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    spare = path.with_name(path.name + ".kettle-new")
    spare.write_text(text, encoding="utf-8")
    os.chmod(spare, mode)
    os.replace(spare, path)


class Setup:
    """Every outside thing is passed in, so the tests never touch the real home folder, Keychain or launchd."""

    def __init__(
        self,
        home: Path,
        python: str,
        root: Optional[str],
        token: Callable[[], str],
        find_chat: Callable[..., int],
        ask: Callable[[str], str] = input,
        say: Callable[[str], Any] = print,
        run: Callable[..., Any] = subprocess.run,
        running: Callable[[], bool] = lambda: False,
        platform: str = sys.platform,
        uid: Optional[int] = None,
        project: Optional[Path] = None,
    ) -> None:
        self.home, self.python, self.root = home, python, root
        self.token, self.find_chat, self.ask, self.say, self.run, self.running = token, find_chat, ask, say, run, running
        self.platform = platform
        self.uid = os.getuid() if uid is None else uid
        self.config = home / ".kettle" / "claude-code.toml"
        # one project only: its own settings.local.json, which is personal and not shared; else every session
        self.settings = (project / ".claude" / "settings.local.json") if project else home / ".claude" / "settings.json"
        self.plist = home / "Library" / "LaunchAgents" / f"{LABEL}.plist"

    def _yes(self, question: str) -> bool:
        try:
            return self.ask(f"{question} Type yes to go ahead: ").strip().lower() == "yes"
        except EOFError:
            return False

    # ---- setup ----------------------------------------------------------------------------

    def setup(self, chat_id: Optional[int] = None, wait: float = 300.0) -> int:
        self.say("Kettle for Claude Code: setup. Nothing is changed without your yes.\n")
        token = self.token()
        if not token:
            self.say("First, put your Telegram bot token in the Keychain. This asks for it and does not show it:\n")
            self.say(f"    {KEYCHAIN_HINT}\n")
            self.say("Then run this setup again.")
            return 2
        if not self._config(token, chat_id, wait):
            return 1
        if self.platform == "darwin":
            if not self._agent():
                self.say("\nThe hook was not added, since nothing would answer it. Start the daemon yourself with:")
                self.say(f"    {self.python} -m kettle.claude_code serve")
                return 1
        else:
            self.say("\nOnly a Mac gets a login item. Start the daemon yourself, and keep it running:")
            self.say(f"    {self.python} -m kettle.claude_code serve")
        if not self._hook(wait):
            return 1
        self.say("\nDone. Try it: in Claude Code, ask for `git push`. Your phone should ask first.")
        self.say("Strict mode (a project cannot turn this off) is not set up. It needs Claude Code's managed settings and your admin password.")
        return 0

    def _config(self, token: str, chat_id: Optional[int], wait: float) -> bool:
        if self.config.exists():
            self.say(f"Settings: {self.config} is there already, and is kept as it is.")
            return True
        if chat_id is None:
            try:
                chat_id = self.find_chat(token, say=self.say)
            except Exception as error:  # TelegramError, or no network
                self.say(f"No chat id: {error}.")
                return False
        if type(chat_id) is not int or type(chat_id) is bool:
            self.say("No chat id.")
            return False
        self.config.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.config.parent, 0o700)
        _write_atomically(self.config, CONFIG_TEXT.format(chat_id=chat_id, wait=int(wait)))
        self.say(f"Settings: wrote {self.config}.")
        return True

    def _agent(self) -> bool:
        made = agent_plist(self.python, self.root, self.home)
        if self.plist.exists() and self.plist.read_bytes() == made and self.running():
            self.say("Daemon: already a login item, and running.")
            return True
        self.say(f"\nDaemon: this makes Kettle a login item, so it is always there to answer the hook.\nIt writes {self.plist} and starts it.")
        if not self._yes("Make Kettle a login item and start it?"):
            return False
        self.plist.parent.mkdir(parents=True, exist_ok=True)
        _write_atomically(self.plist, made.decode("utf-8"), 0o644)
        target = f"gui/{self.uid}"
        self.run(["launchctl", "bootout", f"{target}/{LABEL}"], capture_output=True)
        started = self.run(["launchctl", "bootstrap", target, str(self.plist)], capture_output=True, text=True)
        if getattr(started, "returncode", 1) != 0:
            self.say(f"launchctl could not start it: {getattr(started, 'stderr', '')}".strip())
            return False
        for _ in range(50):
            if self.running():
                self.say("Daemon: running.")
                return True
            self._pause(0.1)
        self.say(f"The daemon did not answer. Its log is {self.home / '.kettle' / 'claude-code.log'}.")
        return False

    def _pause(self, seconds: float) -> None:
        import time

        time.sleep(seconds)

    def _hook(self, wait: float) -> bool:
        try:
            current = _read_settings(self.settings)
            if has_hook(current):
                self.say(f"Hook: already in {self.settings}.")
                return True
            entry = hook_entry(hook_command(self.python, self.root), wait)
            updated = add_hook(current, entry)
        except (OSError, ValueError) as error:
            self.say(f"\n{self.settings} could not be read ({error}). Add this under hooks.PreToolUse yourself:\n")
            self.say(json.dumps(hook_entry(hook_command(self.python, self.root), wait), indent=2))
            return False
        self.say(f"\nHook: this is added under hooks.PreToolUse in {self.settings}. Nothing else in the file changes.\n")
        self.say(json.dumps(entry, indent=2))
        if not self._yes("\nAdd it?"):
            self.say("The hook was not added. The daemon runs, but Claude Code does not ask it.")
            return False
        if self.settings.exists():
            shutil.copy2(self.settings, self._kept())
        _write_atomically(self.settings, json.dumps(updated, indent=2) + "\n", 0o600 if not self.settings.exists() else self.settings.stat().st_mode & 0o777)
        self.say(f"Hook: added. The old file is kept as {self._kept()}." if self._kept().exists() else "Hook: added.")
        return True

    def _kept(self) -> Path:
        return self.settings.with_name(self.settings.name + ".before-kettle")

    # ---- uninstall ------------------------------------------------------------------------

    def uninstall(self) -> int:
        self.say("Kettle for Claude Code: uninstall. The hook comes out first, then the daemon stops.\n")
        try:
            current = _read_settings(self.settings)
        except (OSError, ValueError) as error:
            self.say(f"{self.settings} could not be read ({error}). Take out the hook whose command has `{MARK}` yourself.")
            return 1
        if has_hook(current):
            if not self._yes(f"Take the Kettle hook out of {self.settings}?"):
                return 1
            _write_atomically(self.settings, json.dumps(remove_hook(current), indent=2) + "\n", self.settings.stat().st_mode & 0o777)
            self.say("Hook: taken out.")
        else:
            self.say("Hook: not there.")
        if self.plist.exists():
            if not self._yes("Stop the daemon and remove the login item?"):
                return 1
            self.run(["launchctl", "bootout", f"gui/{self.uid}/{LABEL}"], capture_output=True)
            self.plist.unlink()
            self.say("Daemon: stopped, and no longer a login item.")
        self.say(f"\n{self.home / '.kettle'} is kept: its log is the record of what was asked and answered.")
        return 0


def for_real(platform: str = sys.platform, project: Optional[str] = None) -> Setup:
    from .claude_code import status
    from .mcp import bot_token
    from .telegram import find_chat_id

    where = Path(project).expanduser().resolve() if project else None
    return Setup(Path.home(), sys.executable, source_root(), bot_token, find_chat_id, running=status, platform=platform, project=where)
