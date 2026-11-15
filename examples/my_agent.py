"""The shape of an agent the attack test can run. Replace the body with your own agent.

Run it from the project folder:

    .venv/bin/python -m kettle.attacktest --agent examples.my_agent:agent --repeats 1

As written it does no real work, so the report will show no jobs finished and no
trick text reached. src/kettle/attacktest/claude_agent.py is a full example that
calls a model.
"""


def agent(task, tools):
    """task is what the owner asked for, as text. Return your agent's reply, as text.

    tools.specs lists the tools: each has .name, .description and .parameters (a JSON Schema).
    tools.call(name, inputs) calls one and always returns text.
    Every tool call your agent makes has to go through tools.call, or the test cannot see it.
    """
    inbox = tools.call("list_emails", {})
    return f"I have not been built yet. The inbox has {len(inbox.splitlines())} emails."
