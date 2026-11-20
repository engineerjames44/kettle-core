"""Put Kettle in front of the MCP servers your app already uses, in one run.

    python -m kettle.setup            (asks a few questions)
    python -m kettle.setup --undo     (puts every server it wrapped back as it was)

It reads the MCP settings of Claude Desktop or Cursor, lists the servers there,
and wraps the ones you pick in kettle.mcp: the app then starts kettle.mcp, and
kettle.mcp starts the server. Each wrapped server gets a rules file in ~/.kettle
with every tool set to "ask"; the tools the server offers are written in it, as
comments, to set one by one. The original entry is kept in that file, so --undo
can put it back (its command and arguments; its env stays in the app's own file
and is never copied). A copy of the settings file is kept beside it before any change.

The bot token for the phone is never written by this command. On a Mac it is kept
in the Keychain, typed by you at the Keychain's own prompt; anywhere else, give it
to the app as KETTLE_TELEGRAM_TOKEN.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Optional

from .mcp import KEYCHAIN_SERVICE, TOKEN_NAME

MARK = "kettle.mcp"


def app_configs(home: pathlib.Path, platform: str = sys.platform, environ: Optional[dict] = None) -> dict[str, pathlib.Path]:
    """Where each app keeps its MCP settings on this machine."""
    environ = os.environ if environ is None else environ
    if platform == "darwin":
        claude = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif platform.startswith("win"):
        claude = pathlib.Path(environ.get("APPDATA", str(home / "AppData" / "Roaming"))) / "Claude" / "claude_desktop_config.json"
    else:
        claude = home / ".config" / "Claude" / "claude_desktop_config.json"
    return {"Claude Desktop": claude, "Cursor": home / ".cursor" / "mcp.json"}


def wrapped(entry: Any) -> bool:
    return type(entry) is dict and MARK in [str(arg) for arg in entry.get("args", [])]


def wrap(entry: dict, rules: pathlib.Path, python: str) -> dict:
    """The entry that starts kettle.mcp in front of the server the original entry starts."""
    command = [str(entry["command"])] + [str(arg) for arg in entry.get("args", [])]
    new = {key: value for key, value in entry.items() if key not in ("command", "args")}
    new["command"] = python
    new["args"] = ["-m", MARK, "--config", str(rules), "--"] + command
    return new


def probe_tools(entry: dict, timeout: float = 15.0) -> list[str]:
    """Start the server once, ask it for its tools, and stop it. Returns [] if it does not answer."""
    env = dict(os.environ)
    env.update({str(key): str(value) for key, value in (entry.get("env") or {}).items()})
    try:
        server = subprocess.Popen([str(entry["command"])] + [str(arg) for arg in entry.get("args", [])], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
    except OSError:
        return []
    names: list[str] = []
    timer = threading.Timer(timeout, server.kill)  # a server that never answers is stopped, which ends the read below
    timer.daemon = True
    timer.start()
    try:
        for message in (
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "kettle.setup", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ):
            server.stdin.write(json.dumps(message) + "\n")
        server.stdin.flush()
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            line = server.stdout.readline()
            if not line:
                break
            try:
                reply = json.loads(line)
            except ValueError:
                continue
            if type(reply) is dict and reply.get("id") == 2:
                tools = (reply.get("result") or {}).get("tools") or []
                names = [tool["name"] for tool in tools if type(tool) is dict and type(tool.get("name")) is str]
                break
    except (OSError, ValueError):
        pass
    finally:
        timer.cancel()
        try:
            server.kill()
            server.wait(5)
        except (OSError, subprocess.SubprocessError):
            pass
    return names


def rules_text(server: str, app: str, original: dict, tools: list[str], chat_id: Optional[int], width: Optional[int], store: pathlib.Path) -> str:
    lines = [
        f"# Kettle's rules for the MCP server {json.dumps(server)} in {app}, written by python -m kettle.setup.",
        '# Every tool asks unless it is named below with "free" or "never". Restart the app after a change.',
        f"store = {json.dumps(str(store))}",
        "hold_seconds = 300",
        "",
    ]
    if chat_id is not None:
        lines += ["[approver]", f"chat_id = {chat_id}"] + ([f"preview_width = {width}"] if width else []) + [""]
    lines += ["[tools]", 'default = "ask"']
    if tools:
        lines.append("# The tools this server offered when this file was written:")
        lines += [f"# {json.dumps(name)} = \"free\"" for name in tools]
    else:
        lines.append("# The server did not list its tools when asked, so none are named here.")
    lines += ["", "[setup]  # for python -m kettle.setup --undo", f"app = {json.dumps(app)}", f"server = {json.dumps(server)}", f"original = {json.dumps(json.dumps(original))}", ""]
    return "\n".join(lines)


def safe_name(server: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "-" for char in server)[:60] or "server"


def rules_path(kettle_dir: pathlib.Path, app: str, server: str) -> pathlib.Path:
    """One rules file for each server of each app. Two names that read alike still get files of their own."""
    tag = hashlib.sha256(f"{app}\0{server}".encode()).hexdigest()[:8]
    return kettle_dir / f"{safe_name(app)}-{safe_name(server)}-{tag}.toml"


def save(path: pathlib.Path, data: dict) -> None:
    """Write the settings file, keeping a copy of the one it replaces beside it."""
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + f".before-kettle-{time.strftime('%Y%m%d-%H%M%S')}"))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".kettle-tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)


def run_setup(
    ask: Callable[[str], str],
    say: Callable[[str], None],
    home: pathlib.Path,
    apps: Optional[dict[str, pathlib.Path]] = None,
    python: str = sys.executable,
    probe: Callable[[dict], list[str]] = probe_tools,
    platform: str = sys.platform,
) -> int:
    apps = app_configs(home, platform) if apps is None else apps
    found = {name: path for name, path in apps.items() if path.exists()}
    if not found:
        say("No MCP settings were found for " + " or ".join(apps) + ". Add a server to your app first, then run this again.")
        return 1
    names = list(found)
    say("Apps with MCP settings on this machine:")
    for number, name in enumerate(names, 1):
        say(f"  {number}. {name}")
    app = names[_pick(ask, "Which app? ", len(names)) - 1] if len(names) > 1 else names[0]
    path = found[app]
    try:
        data = json.loads(path.read_text() or "{}")
    except ValueError:
        say(f"{path} is not valid JSON, so it was left as it is.")
        return 1
    servers = data.get("mcpServers") if type(data.get("mcpServers")) is dict else {}
    usable = [name for name, entry in servers.items() if type(entry) is dict and type(entry.get("command")) is str]
    if not usable:
        say(f"{app} has no MCP servers that start with a command. Add one first, then run this again.")
        return 1
    say(f"MCP servers in {app}:")
    for number, name in enumerate(usable, 1):
        say(f"  {number}. {name}" + ("   (Kettle is already in front of it)" if wrapped(servers[name]) else ""))
    picked = _many(ask, "Which ones should Kettle stand in front of? Numbers with spaces, or 'all': ", len(usable))
    chosen = [usable[number - 1] for number in picked if not wrapped(servers[usable[number - 1]])]
    if not chosen:
        say("Nothing to do: each one picked already has Kettle in front of it.")
        return 0
    chat_id, width = None, None
    if _yes(ask("Send the actions that need a yes to your phone, on Telegram? (y/n) ")):
        chat_id = _number(ask, "Your Telegram chat id (python -m kettle.telegram finds it): ")
        width = _number(ask, "How many characters your phone shows on a line, 32 to 78 (Enter for 78): ", allow_empty=True, low=32, high=78)
    kettle_dir = home / ".kettle"
    kettle_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in chosen:
        entry = servers[name]
        tools = probe(entry) if _yes(ask(f"Start {name} once now, to read the tools it offers? (y/n) ")) else []
        rules = rules_path(kettle_dir, app, name)
        original = {"command": entry["command"], "args": list(entry.get("args", []))}  # not its env, which may hold secrets and stays in the app's file
        fd = os.open(rules, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(rules_text(name, app, original, tools, chat_id, width, rules.with_suffix(".db")))
        servers[name] = wrap(entry, rules, python)
        say(f"Kettle is now in front of {name}. Its rules: {rules}" + (f" ({len(tools)} tools listed in it)" if tools else ""))
    data["mcpServers"] = servers
    save(path, data)
    say(f"Saved {path}. A copy of how it was is beside it. Restart {app} to start using Kettle.")
    if chat_id is not None and not os.environ.get(TOKEN_NAME):
        if platform == "darwin":
            say("One step left: keep your bot token in the Keychain. Run this, and paste the token when it asks:")
            say(f"    security add-generic-password -U -a kettle -s {KEYCHAIN_SERVICE} -w")
        else:
            say(f"One step left: give {app} your bot token as {TOKEN_NAME} in that server's env settings.")
    return 0


def run_undo(say: Callable[[str], None], home: pathlib.Path, apps: Optional[dict[str, pathlib.Path]] = None, platform: str = sys.platform) -> int:
    import tomllib

    apps = app_configs(home, platform) if apps is None else apps
    put_back = 0
    for rules in sorted((home / ".kettle").glob("*.toml")):
        try:
            setup = tomllib.loads(rules.read_text()).get("setup", {})
            app, server, original = setup["app"], setup["server"], json.loads(setup["original"])
        except (OSError, ValueError, KeyError, TypeError, tomllib.TOMLDecodeError):
            continue
        path = apps.get(app)
        if path is None or not path.exists():
            continue
        try:
            data = json.loads(path.read_text() or "{}")
        except (OSError, ValueError):
            say(f"{path} could not be read as JSON, so {server} in {app} was left as it is.")
            continue
        entry = (data.get("mcpServers") or {}).get(server) if type(data) is dict else None
        if not wrapped(entry) or str(rules) not in [str(arg) for arg in entry.get("args", [])]:
            continue  # changed by hand since, or wrapped by something else: left alone
        data["mcpServers"][server] = {**{key: value for key, value in entry.items() if key not in ("command", "args")}, **original}
        save(path, data)
        rules.rename(rules.with_name(rules.name + ".undone"))
        say(f"{server} in {app} is back as it was.")
        put_back += 1
    say(f"{put_back} server{'' if put_back == 1 else 's'} put back." + (" Restart the app." if put_back else ""))
    return 0


def _yes(answer: str) -> bool:
    return answer.strip().lower() in ("y", "yes")


def _pick(ask: Callable[[str], str], question: str, most: int) -> int:
    while True:
        answer = ask(question).strip()
        if answer.isdigit() and 1 <= int(answer) <= most:
            return int(answer)


def _many(ask: Callable[[str], str], question: str, most: int) -> list[int]:
    while True:
        answer = ask(question).strip().lower()
        if answer == "all":
            return list(range(1, most + 1))
        parts = answer.replace(",", " ").split()
        if parts and all(part.isdigit() and 1 <= int(part) <= most for part in parts):
            return sorted({int(part) for part in parts})


def _number(ask: Callable[[str], str], question: str, allow_empty: bool = False, low: int = 1, high: Optional[int] = None) -> Optional[int]:
    while True:
        answer = ask(question).strip()
        if allow_empty and not answer:
            return None
        if answer.isdigit() and int(answer) >= low and (high is None or int(answer) <= high):
            return int(answer)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kettle.setup", description="Put Kettle in front of the MCP servers your app already uses.")
    parser.add_argument("--undo", action="store_true", help="put every server this wrapped back as it was")
    args = parser.parse_args(argv)
    home = pathlib.Path.home()
    try:
        if args.undo:
            return run_undo(print, home)
        return run_setup(input, print, home)
    except (EOFError, KeyboardInterrupt):
        print("\nStopped. Nothing was changed after the last line above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
