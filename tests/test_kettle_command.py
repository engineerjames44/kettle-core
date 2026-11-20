"""kettle, the one command: it only hands each name on to the module's own main."""

import importlib
import subprocess
import sys

import pytest

import kettle
from kettle import __main__ as one


def test_every_name_leads_to_a_module_with_a_main():
    for name, module in one.COMMANDS.items():
        assert callable(importlib.import_module(module).main), name
    assert set(one.COMMANDS) == {"test", "scoreboard", "howsure", "compare", "mcp", "setup", "claude-code", "telegram", "demo", "verify"}
    for name in one.COMMANDS:
        assert f"kettle {name}" in one.usage()


def test_help_version_and_a_wrong_name(capsys):
    assert one.main(["--help"]) == 0 and "kettle test" in capsys.readouterr().out
    assert one.main([]) == 2
    capsys.readouterr()
    assert one.main(["--version"]) == 0 and capsys.readouterr().out.strip() == f"kettle {kettle.__version__}"
    assert one.main(["tset"]) == 2 and "no command 'tset'" in capsys.readouterr().err


def test_the_rest_goes_to_the_module_as_it_is(capsys):
    assert one.main(["test", "--list", "--cases", "trusted"]) == 0
    assert capsys.readouterr().out.startswith("kettle-trusted-1:")
    assert one.main(["howsure", "0", "22"]) == 0
    assert "0 of 22" in capsys.readouterr().out
    assert one.main(["test", "--self-check"]) == 0


def test_a_modules_own_help_and_errors_come_back_as_codes(capsys):
    assert one.main(["test", "--help"]) == 0
    assert "--agent-command" in capsys.readouterr().out
    assert one.main(["test", "--no-such-option"]) == 2


def test_python_dash_m_kettle_is_the_same_command():
    done = subprocess.run([sys.executable, "-m", "kettle", "--version"], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0 and done.stdout.strip() == f"kettle {kettle.__version__}"
