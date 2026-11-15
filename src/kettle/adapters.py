"""Small pieces for plugging Kettle into a tool loop you already have. They need no other package.

Everything here works with one shape: call(name, inputs) -> text.

- The attack test hands your agent that shape as tools.call.
- through() makes the same shape out of a checkpoint, for your real tools.

So the same few lines work for both. With the Anthropic Messages API:

    tools = anthropic_tools(specs)                        # the tool list for the request
    results = anthropic_tool_results(reply.content, call) # runs what the model asked for
    # no results: the model is done. Otherwise add the model's turn, then
    # {"role": "user", "content": results}, and ask again.

With the OpenAI Chat Completions API:

    tools = openai_tools(specs)
    message = completion.choices[0].message
    answers = openai_tool_messages(message.tool_calls, call)
    # no answers: the model is done. Otherwise add openai_assistant_message(message),
    # then the answers, and ask again.

The replies can be the packages' own objects or plain dicts.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable, Iterable, Optional

from .checkpoint import APPROVED, HELD, RAN, Decision

Call = Callable[[Any, Any], str]

WAITING = "This action needs the owner's yes and is waiting for it. Nothing has been run."
SAID_NO = "This action needs the owner's yes. The owner was asked and said no. Nothing was run."
QUESTION = "Type yes to run this, or anything else to refuse: "


def _get(item: Any, key: str) -> Any:
    return item.get(key) if isinstance(item, dict) else getattr(item, key, None)


def _text(value: Any) -> str:
    return value if type(value) is str else str(value)


# ---- the tool list ---------------------------------------------------------


def anthropic_tools(specs: Iterable[Any]) -> list[dict]:
    """The tool list as the Anthropic Messages API takes it. Each spec has .name, .description and .parameters."""
    return [{"name": spec.name, "description": spec.description, "input_schema": spec.parameters} for spec in specs]


def openai_tools(specs: Iterable[Any]) -> list[dict]:
    """The tool list as the OpenAI Chat Completions API takes it."""
    return [{"type": "function", "function": {"name": spec.name, "description": spec.description, "parameters": spec.parameters}} for spec in specs]


# ---- running what the model asked for ---------------------------------------


def anthropic_tool_results(content: Iterable[Any], call: Call) -> list[dict]:
    """Run every tool_use block of a reply through call, in the order the model asked.

    Returns the tool_result blocks, which are the content of the next user message.
    An empty list means the model asked for no tool.
    """
    results = []
    for block in content or []:
        if _get(block, "type") == "tool_use":
            results.append({"type": "tool_result", "tool_use_id": _get(block, "id"), "content": _text(call(_get(block, "name"), _get(block, "input")))})
    return results


def openai_arguments(arguments: Any) -> Any:
    """The inputs of an OpenAI tool call.

    The API sends them as JSON text that the model wrote, and it can be wrong. Text
    that is not JSON is handed on as it is, so the call is still seen and refused
    and is not quietly dropped.
    """
    if type(arguments) is not str:
        return arguments
    if not arguments.strip():
        return {}
    try:
        return json.loads(arguments)
    except (ValueError, RecursionError):
        return arguments


def _function_of(tool_call: Any) -> Any:
    function = _get(tool_call, "function")
    if function is None:
        raise ValueError("the reply has a tool call that is not a function call, and only function calls are handled")
    return function


def openai_tool_messages(tool_calls: Optional[Iterable[Any]], call: Call) -> list[dict]:
    """Run every tool call of a Chat Completions reply through call, in the order the model asked.

    Returns one "tool" message per call, to add after the assistant's own message.
    An empty list means the model asked for no tool.

    Raises ValueError, before anything runs, if one of the calls is not a function call.
    """
    calls = list(tool_calls or [])
    functions = [_function_of(tool_call) for tool_call in calls]  # nothing runs if one of them cannot be handled
    messages = []
    for tool_call, function in zip(calls, functions):
        text = _text(call(_get(function, "name"), openai_arguments(_get(function, "arguments"))))
        messages.append({"role": "tool", "tool_call_id": _get(tool_call, "id"), "content": text})
    return messages


def openai_assistant_message(message: Any) -> dict:
    """The model's own turn as a plain dict, to add to the messages before the tool messages."""
    turn: dict = {"role": "assistant", "content": _get(message, "content")}
    calls = list(_get(message, "tool_calls") or [])
    if calls:
        turn["tool_calls"] = []
        for tool_call in calls:
            function = _function_of(tool_call)
            arguments = _get(function, "arguments")
            if type(arguments) is not str:
                arguments = json.dumps(arguments)
            turn["tool_calls"].append({"id": _get(tool_call, "id"), "type": "function", "function": {"name": _get(function, "name"), "arguments": arguments}})
    return turn


# ---- a checkpoint in front of your own tools ---------------------------------


def through(gate: Any, on_held: Optional[Callable[[Decision], Any]] = None) -> Call:
    """A call(name, inputs) -> text that sends every tool call through a checkpoint.

    gate is checkpoint.gate, or checkpoint.gate_for("a name"). The text is what to
    hand back to the model:

    - a free tool runs, and the text is its result;
    - a refused call does not run, and the text is the reason;
    - a held action does not run. It is passed to on_held(decision), and the text
      is whatever that returns. With no on_held the model is told the action is
      waiting, and it stays held until your own code calls approve and run.
    """

    def call(name: Any, inputs: Any) -> str:
        decision = gate.request(name, inputs)
        if decision.status == RAN:
            return _text(decision.result)
        if decision.status == HELD:
            return WAITING if on_held is None else _text(on_held(decision))
        return decision.reason

    return call


def _discard_typed_ahead() -> None:
    """Throw away what was typed before the question was on screen, so it cannot answer it."""
    try:
        import termios
    except ImportError:  # Windows
        import msvcrt

        while msvcrt.kbhit():
            msvcrt.getwch()
        return
    termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)


def _keyboard(question: str) -> str:
    if sys.stdin is None or not sys.stdin.isatty():
        raise EOFError("there is no keyboard to ask at")
    try:
        _discard_typed_ahead()
    except Exception:
        raise EOFError("what was typed before the question could not be thrown away")
    return input(question)


def ask_in_terminal(
    checkpoint: Any, *, approver: str = "owner", ask: Optional[Callable[[str], str]] = None, show: Callable[[str], Any] = print
) -> Callable[[Decision], str]:
    """An on_held for through(): show the held action in the terminal and ask for a yes.

    Only the word yes runs the action. Anything else is a no, and so is having no
    keyboard to ask at (input that is piped in is not a person). The yes covers the
    action that was shown and nothing else. Anything typed before the question was
    on screen is thrown away, so a yes typed too early does not answer it. (With
    your own ask, that part is up to you.)

    This is for trying things out on your own machine. The question is asked in
    the program the agent runs in, so it is only as good as that program.
    """

    def on_held(decision: Decision) -> str:
        show("")
        show("The agent wants to do this. Nothing has run yet:")
        show("")
        show(decision.preview)
        show("")
        try:
            answer = (ask or _keyboard)(QUESTION)
        except EOFError:
            answer = ""
        if type(answer) is not str or answer.strip() != "yes":
            checkpoint.deny(decision.request_id, approver)
            show("Refused. Nothing was run.")
            return SAID_NO
        approved = checkpoint.approve(decision.request_id, decision.fingerprint, approver)
        if approved.status != APPROVED:
            show(approved.reason)
            return approved.reason
        done = checkpoint.run(decision.request_id)
        show(done.reason)
        return _text(done.result) if done.status == RAN else done.reason

    return on_held
