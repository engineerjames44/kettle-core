"""The attack test: plant trick text where an agent reads, and count what gets through."""

from .cases import Case, CaseError, CaseSet, load_cases
from .report import save_report, to_markdown
from .runner import KETTLE, NONE, SETUPS, ToolBox, run_case, run_test
from .sandbox import TOOL_SPECS, Sandbox, ToolSpec

__all__ = [
    "KETTLE",
    "NONE",
    "SETUPS",
    "TOOL_SPECS",
    "Case",
    "CaseError",
    "CaseSet",
    "Sandbox",
    "ToolBox",
    "ToolSpec",
    "load_cases",
    "run_case",
    "run_test",
    "save_report",
    "to_markdown",
]
