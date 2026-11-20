"""kettle, or python -m kettle: one command for every part of Kettle.

    kettle test ...          the attack test (python -m kettle.attacktest)
    kettle scoreboard ...    one table from saved attack-test reports
    kettle howsure ...       the range a count leaves open
    kettle compare ...       is a gap between two counts more than chance?
    kettle mcp ...           Kettle in front of an MCP server
    kettle setup ...         put Kettle in front of Claude Desktop's or Cursor's MCP servers
    kettle claude-code ...   Kettle in front of Claude Code
    kettle telegram          find your Telegram chat id
    kettle demo ...          the browser demo
    kettle verify ...        check a receipt

Each one takes the same options as its python -m form; add --help after its name.
"""

from __future__ import annotations

import importlib
import sys
from typing import Optional

from . import __version__

COMMANDS = {
    "test": "kettle.attacktest.__main__",
    "scoreboard": "kettle.attacktest.scoreboard",
    "howsure": "kettle.attacktest.howsure",
    "compare": "kettle.attacktest.compare",
    "mcp": "kettle.mcp",
    "setup": "kettle.setup",
    "claude-code": "kettle.claude_code",
    "telegram": "kettle.telegram",
    "demo": "kettle.demo.app",
    "verify": "kettle.verify",
}


def usage() -> str:
    return (__doc__ or "").strip()


def main(argv: Optional[list] = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(usage())
        return 0 if argv else 2
    if argv[0] in ("-V", "--version"):
        print(f"kettle {__version__}")
        return 0
    name, rest = argv[0], argv[1:]
    if name not in COMMANDS:
        print(f"kettle: there is no command {name!r}.\n\n{usage()}", file=sys.stderr)
        return 2
    module = importlib.import_module(COMMANDS[name])
    try:
        code = module.main(rest)
    except SystemExit as stop:  # argparse ends --help and its own errors this way
        code = stop.code
    return code if type(code) is int else (0 if code is None else 1)


if __name__ == "__main__":
    raise SystemExit(main())
