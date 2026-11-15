"""Break the adapters on purpose, one way at a time, and see whether the tests notice.

    .venv/bin/python checks/break_adapters.py

The adapters sit between a model's reply and the tools, so the breaks here are ways a
call could be lost, run when it should not, or answered wrongly, and ways the terminal
question could take something other than a typed yes.
"""

from _runner import nth, rep, run

TESTS = ["test_adapters.py", "test_openai_agent.py", "test_claude_agent.py", "test_examples.py"]

ADA = "adapters.py"

MUTANTS = [
    ("anthropic: the schema goes under the wrong name", ADA, rep('"input_schema": spec.parameters', '"parameters": spec.parameters')),
    ("anthropic: blocks that are not tool calls are run", ADA, rep('if _get(block, "type") == "tool_use":', "if True:")),
    ("anthropic: results come back in the wrong order", ADA, lambda t: nth(t, "    return results\n", "    return results[::-1]\n")),
    ("anthropic: a result is tied to the wrong call", ADA, rep('"tool_use_id": _get(block, "id")', '"tool_use_id": _get(block, "name")')),
    ("anthropic: a result that is not text is passed on as it is", ADA, rep('"content": _text(call(_get(block, "name"), _get(block, "input")))', '"content": call(_get(block, "name"), _get(block, "input"))')),
    ("openai: the tool list is not wrapped as functions", ADA, rep('[{"type": "function", "function": {"name": spec.name, "description": spec.description, "parameters": spec.parameters}} for spec in specs]', '[{"name": spec.name, "description": spec.description, "parameters": spec.parameters} for spec in specs]')),
    ("openai: inputs that are not JSON become empty inputs", ADA, rep("    except (ValueError, RecursionError):\n        return arguments", "    except (ValueError, RecursionError):\n        return {}")),
    ("openai: very deep JSON stops the program", ADA, rep("except (ValueError, RecursionError):", "except ValueError:")),
    ("openai: blank inputs are handed on as text", ADA, rep("    if not arguments.strip():\n        return {}", "    if not arguments.strip():\n        return arguments")),
    ("openai: calls before one that cannot be handled still run", ADA, rep("functions = [_function_of(tool_call) for tool_call in calls]", "functions = (_function_of(tool_call) for tool_call in calls)")),
    ("openai: a call that is not a function is passed over", ADA, rep("    calls = list(tool_calls or [])\n    functions", '    calls = [c for c in (tool_calls or []) if _get(c, "function") is not None]\n    functions')),
    ("openai: an answer is tied to the wrong call", ADA, rep('"tool_call_id": _get(tool_call, "id")', '"tool_call_id": _get(function, "name")')),
    ("openai: answers come back in the wrong order", ADA, rep("    return messages\n", "    return messages[::-1]\n")),
    ("openai: an answer that is not text is passed on as it is", ADA, rep('text = _text(call(_get(function, "name"), openai_arguments(_get(function, "arguments"))))', 'text = call(_get(function, "name"), openai_arguments(_get(function, "arguments")))')),
    ("openai: the model's turn loses its tool calls", ADA, rep("    if calls:\n        turn", "    if False:\n        turn")),
    ("openai: the model's turn has its inputs rewritten", ADA, rep("            if type(arguments) is not str:\n                arguments = json.dumps(arguments)", "            arguments = json.dumps(openai_arguments(arguments))")),
    ("openai: the model's turn loses its text", ADA, rep('{"role": "assistant", "content": _get(message, "content")}', '{"role": "assistant", "content": None}')),
    ("through: the model is not told that a held action is waiting", ADA, rep("return WAITING if on_held is None else _text(on_held(decision))", 'return "Done." if on_held is None else _text(on_held(decision))')),
    ("through: nobody is asked about a held action", ADA, rep("return WAITING if on_held is None else _text(on_held(decision))", "return WAITING")),
    ("through: a refusal comes back without its reason", ADA, rep("        return decision.reason\n\n    return call", '        return ""\n\n    return call')),
    ("through: a result that is not text is passed on as it is", ADA, rep("        if decision.status == RAN:\n            return _text(decision.result)", "        if decision.status == RAN:\n            return decision.result")),
    ("through: a held action is reported as its result", ADA, rep("        if decision.status == RAN:\n            return _text(decision.result)", "        if decision.status in (RAN, HELD):\n            return _text(decision.result)")),
    ("terminal: anything but no is a yes", ADA, rep('answer.strip() != "yes"', 'answer.strip() == "no"')),
    ("terminal: yes in capitals is a yes", ADA, rep('answer.strip() != "yes"', 'answer.strip().lower() != "yes"')),
    ("terminal: y is a yes", ADA, rep('answer.strip() != "yes"', 'answer.strip() not in ("yes", "y")')),
    ("terminal: a word that starts with yes is a yes", ADA, rep('answer.strip() != "yes"', 'not answer.strip().startswith("yes")')),
    ("terminal: letters that look like yes are a yes", ADA, rep('answer.strip() != "yes"', 'answer.strip().casefold().replace("\\u0443", "y").replace("\\u0435", "e") != "yes"')),
    ("terminal: an answer that is not text stops the program", ADA, rep('if type(answer) is not str or answer.strip() != "yes":', 'if answer.strip() != "yes":')),
    ("terminal: input that is piped in is read as the answer", ADA, rep("if sys.stdin is None or not sys.stdin.isatty():", "if sys.stdin is None:")),
    ("terminal: no input at all stops the program", ADA, rep("if sys.stdin is None or not sys.stdin.isatty():", "if not sys.stdin.isatty():")),
    ("terminal: a yes typed before the question was on screen answers it", ADA, rep("        _discard_typed_ahead()\n", "        pass\n")),
    ("terminal: asks anyway when what was typed early cannot be thrown away", ADA, rep('        raise EOFError("what was typed before the question could not be thrown away")\n', "        pass\n")),
    ("terminal: no keyboard stops the program", ADA, rep('        except EOFError:\n            answer = ""', "        except EOFError:\n            raise")),
    ("terminal: a no is not written down", ADA, rep("            checkpoint.deny(decision.request_id, approver)\n", "")),
    ("terminal: the yes is not tied to what was shown", ADA, rep("checkpoint.approve(decision.request_id, decision.fingerprint, approver)", 'checkpoint.approve(decision.request_id, next(p["fingerprint"] for p in checkpoint.pending() if p["request_id"] == decision.request_id), approver)')),
    ("terminal: who said yes is not written down", ADA, rep("checkpoint.approve(decision.request_id, decision.fingerprint, approver)", "checkpoint.approve(decision.request_id, decision.fingerprint)")),
    ("terminal: who said no is not written down", ADA, rep("checkpoint.deny(decision.request_id, approver)", "checkpoint.deny(decision.request_id)")),
    ("terminal: the action is not shown", ADA, rep("        show(decision.preview)\n", "")),
    ("terminal: a yes that was refused is reported as done", ADA, rep("        if approved.status != APPROVED:\n            show(approved.reason)\n            return approved.reason\n", "")),
    ("terminal: a failure after the yes is reported as the result", ADA, rep("return _text(done.result) if done.status == RAN else done.reason", "return _text(done.result)")),
    ("terminal: a run that could not be recorded is shown as a clean run", ADA, rep("        show(done.reason)\n", '        show("Ran.")\n')),
    ("terminal: the action runs twice after one yes", ADA, rep("        done = checkpoint.run(decision.request_id)\n", "        checkpoint.run(decision.request_id)\n        done = checkpoint.run(decision.request_id)\n")),
    ("terminal: the action runs before the question", ADA, rep("        try:\n            answer = (ask or _keyboard)(QUESTION)", "        checkpoint.approve(decision.request_id, decision.fingerprint, approver)\n        checkpoint.run(decision.request_id)\n        try:\n            answer = (ask or _keyboard)(QUESTION)")),
]

if __name__ == "__main__":
    run(MUTANTS, TESTS)
