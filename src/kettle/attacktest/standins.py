"""Stand-in agents: fixed scripts, not models.

They exist to check the test itself. If a scripted agent that always does what
the trick text says is not counted as fooled, or a scripted agent that never does
is, the runner is wrong. They say nothing about how any real model behaves.
"""

from __future__ import annotations

from .cases import Case
from .runner import Agent, ToolBox


def careful(case: Case) -> Agent:
    """Does the owner's job exactly and ignores the trick text."""

    def agent(task: str, tools: ToolBox) -> str:
        for tool, inputs in case.steps:
            tools.call(tool, dict(inputs))
        return case.answer

    return agent


def attackers_call(case: Case) -> tuple[str, dict]:
    """The call the attacker is hoping for."""
    if case.goal.tool == "pay":
        return "pay", {"to": case.goal.to, "amount": 25.0, "note": "as instructed"}
    return "send_email", {"to": case.goal.to, "subject": "As requested", "body": "Sent as the message asked."}


def fooled(case: Case) -> Agent:
    """Does the owner's job, and also does whatever the trick text asked for."""

    def agent(task: str, tools: ToolBox) -> str:
        for tool, inputs in case.steps:
            tools.call(tool, dict(inputs))
        if case.goal is not None:
            tools.call(*attackers_call(case))
        return case.answer

    return agent
